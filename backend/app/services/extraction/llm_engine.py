"""
Medpark Meeting Intelligence System - Offline Extraction Engine
Extracts evidence-grounded decisions and action items with the local Ollama LLM via map/reduce over the indexed transcript.
"""

import math
import time
from typing import Any, Optional
from pydantic import ValidationError
from app.core.config import settings
from app.core.exceptions import ExtractionError, LLMUnavailable
from app.core.logging import logger
from app.models.meeting import Meeting
from app.models.transcript import Transcript, TranscriptSegment
from app.models.extraction import (
    MinutesOfMeeting,
    DecisionItem,
    ActionItem,
    RiskOrQuestionItem,
    EvidenceQuote,
)
from app.services.extraction.base import BaseExtractor
from app.services.extraction.chunker import Chunk, build_chunks, filter_chunk_items
from app.services.extraction.heuristic_extractor import extract_heuristic
from app.services.extraction.llm_client import llm_client
from app.services.extraction.merge import merge_items
from app.services.extraction.prompt_templates import (
    EXTRACTION_MAP_SYSTEM_PROMPT,
    EXTRACTION_MAP_USER_PROMPT_TEMPLATE,
    EXTRACTION_MAP_OVERLAP_SENTENCE_TEMPLATE,
    EXTRACTION_MAP_REPAIR_TEMPLATE,
    EXTRACTION_MAP_LENGTH_REPAIR_TEMPLATE,
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_USER_PROMPT_TEMPLATE,
    SYNTHESIS_REPAIR_TEMPLATE,
)
from app.services.extraction.schemas import MAP_SCHEMA, SYNTHESIS_SCHEMA, MapResult, SynthesisResult
from app.services.extraction.validator import evidence_validator, resolve_owner, audit_free_prose


HEURISTIC_FALLBACK_PROVENANCE = "heuristic-fallback"

# The Romanian instruction text tokenises at 3.05 chars/token on the Qwen3 tokenizer (measured via
# prompt_eval_count, 2026-09-26); 2.6 keeps ~15% margin. Transcript text keeps the conservative
# settings.LLM_CHARS_PER_TOKEN because mixed RO/RU ASR output measured ~2.35.
PROMPT_CHARS_PER_TOKEN = 2.6


def _mmss(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


class LocalLLMExtractor(BaseExtractor):
    """
    Map/reduce extractor over the compact indexed transcript: sequential map calls per chunk with
    grammar-constrained JSON, deterministic merge in Python, one synthesis call for the summaries,
    evidence copied verbatim from the cited segments, then grounding validation and a prose audit.

    `client` may be overridden (tests inject a fake with assert_ready/complete_json/unload);
    None means the module-level Ollama singleton.
    """

    def __init__(self, client: Any = None):
        self._client = client

    @property
    def client(self) -> Any:
        return self._client if self._client is not None else llm_client

    async def preflight(self) -> str:
        """
        Confirms the local LLM is serving before the pipeline spends minutes on ASR.
        Returns the provenance string, or "heuristic-fallback" only when policy explicitly allows it.
        """
        try:
            return await self.client.assert_ready()
        except LLMUnavailable as e:
            if not settings.REQUIRE_LOCAL_LLM and settings.LLM_FALLBACK_MODE == "heuristic":
                logger.warning(f"{e.message}. Policy allows the degraded heuristic extractor (REQUIRE_LOCAL_LLM=False, LLM_FALLBACK_MODE=heuristic).")
                return HEURISTIC_FALLBACK_PROVENANCE
            raise

    async def extract_minutes(self, meeting: Meeting, transcript: Transcript) -> MinutesOfMeeting:
        logger.info(f"Extracting structured minutes for meeting: '{meeting.title}' ({len(transcript.segments)} segments)...")
        provenance = await self.preflight()

        if provenance == HEURISTIC_FALLBACK_PROVENANCE:
            minutes = extract_heuristic(meeting, transcript)
            return evidence_validator.validate_and_enrich(minutes, transcript, meeting)

        started = time.perf_counter()
        stats: dict[str, Any] = {
            "engine": "ollama",
            "model": settings.LLM_MODEL_NAME,
            "chunks": 0,
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "seconds": 0.0,
            "json_first_pass_rate": None,
            "map_calls": 0,
            "map_first_pass_ok": 0,
        }
        try:
            minutes = await self._extract_with_llm(meeting, transcript, provenance, stats)
        finally:
            # The LLM (~2.7 GB) and Whisper cannot share the 4 GB VRAM: free it for the next meeting's ASR
            await self.client.unload()

        stats["seconds"] = round(time.perf_counter() - started, 2)
        if stats["map_calls"]:
            stats["json_first_pass_rate"] = round(stats["map_first_pass_ok"] / stats["map_calls"], 3)
        minutes.extraction_stats = stats
        logger.info(
            f"Extraction complete: {len(minutes.decisions)} decisions, {len(minutes.action_items)} actions, "
            f"{len(minutes.risks_and_questions)} risks/questions in {stats['seconds']}s "
            f"({stats['calls']} LLM calls, {stats['prompt_tokens']} prompt / {stats['completion_tokens']} completion tokens)"
        )
        return minutes

    # ------------------------------------------------------------------ map / reduce

    async def _extract_with_llm(
        self, meeting: Meeting, transcript: Transcript, provenance: str, stats: dict[str, Any]
    ) -> MinutesOfMeeting:
        lines, segment_ids = transcript.to_indexed_lines()
        segments = transcript.segments
        meeting_type = meeting.meeting_type.value
        turn_starts = {i for i, seg in enumerate(segments) if i == 0 or seg.speaker != segments[i - 1].speaker}
        budget = self._effective_chunk_budget(meeting_type)
        chunks = build_chunks(lines, budget, settings.LLM_CHUNK_OVERLAP_TOKENS, turn_starts=turn_starts)
        stats["chunks"] = len(chunks)
        logger.info(f"Transcript rendered as {len(lines)} indexed lines in {len(chunks)} chunk(s) (chunk budget {budget} est. tokens)")

        raw_decisions: list[dict] = []
        raw_actions: list[dict] = []
        raw_risks: list[dict] = []
        failed_chunks: list[int] = []

        # Map: strictly sequential so the single GPU never sees two requests at once
        for chunk in chunks:
            result = await self._map_chunk(chunk, meeting_type, stats)
            if result is None:
                failed_chunks.append(chunk.ordinal)
                continue
            tag = {"chunk": chunk.ordinal}
            raw_decisions.extend(filter_chunk_items([d.model_dump() | tag for d in result.decisions], chunk))
            raw_actions.extend(filter_chunk_items([a.model_dump() | tag for a in result.action_items], chunk))
            raw_risks.extend(filter_chunk_items([r.model_dump() | tag for r in result.risks_and_questions], chunk))

        if chunks and len(failed_chunks) / len(chunks) > settings.LLM_MAX_FAILED_CHUNK_RATIO:
            raise ExtractionError(
                f"Extragerea a eșuat: {len(failed_chunks)} din {len(chunks)} fragmente nu au putut fi procesate de LLM-ul local "
                f"(limită {settings.LLM_MAX_FAILED_CHUNK_RATIO:.0%})."
            )

        # Reduce: deterministic de-duplication across overlapping chunks
        merged_decisions = merge_items(raw_decisions, "decision")
        merged_actions = merge_items(raw_actions, "task")
        merged_risks = merge_items(raw_risks, "description")

        minutes = MinutesOfMeeting(
            meeting_id=meeting.id,
            title=meeting.title,
            meeting_type=meeting_type,
            summary_ro="",
            model_version=provenance,
            failed_chunks=failed_chunks,
        )

        # Owner resolution happens ONCE on the merged dicts, before anything else reads them: the structured
        # ActionItem and the synthesis prompt must both see the enforced label, never the raw owner_mention
        # (a fabricated mention that resolve_owner discarded must not resurface in the summaries).
        for a in merged_actions:
            cited = [segments[i] for i in a["evidence_idx"]]
            a["owner"], a["owner_source"] = resolve_owner(a.get("owner_mention"), a.get("owner_speaker"), cited, meeting.attendees)

        # Convert indices to evidence copied from the cited segments
        for d in merged_decisions:
            minutes.decisions.append(
                DecisionItem(
                    topic=d["topic"],
                    decision=d["decision"],
                    category=d["category"],
                    evidence=self._evidence_from_indices(d["evidence_idx"], segments),
                )
            )
        for a in merged_actions:
            if a["owner_source"] == "mention":
                minutes.needs_name_review = True
            minutes.action_items.append(
                ActionItem(
                    task=a["task"],
                    owner=a["owner"],
                    owner_source=a["owner_source"],
                    deadline_phrase=a.get("deadline_phrase"),
                    priority=a["priority"],
                    evidence=self._evidence_from_indices(a["evidence_idx"], segments),
                )
            )
        for r in merged_risks:
            minutes.risks_and_questions.append(
                RiskOrQuestionItem(
                    item_type=r["item_type"],
                    description=r["description"],
                    severity=r["severity"],
                    evidence=self._evidence_from_indices(r["evidence_idx"], segments),
                )
            )

        # Synthesis: summaries and agenda from the merged items only (never the transcript)
        synthesis_note = await self._synthesise(minutes, merged_decisions, merged_actions, merged_risks, meeting_type, stats)

        # Prose audit over the LLM-authored text ONLY: it runs before any engine- or validator-authored note
        # ("NOTĂ AUDIT", "[NEVERIFICAT AUDIO]") is appended, so the engine can never flag its own vocabulary.
        suspects = audit_free_prose(minutes, transcript, meeting)

        engine_notes: list[RiskOrQuestionItem] = []
        if failed_chunks:
            intervals = ", ".join(self._chunk_interval(chunks[o], segments) for o in failed_chunks)
            engine_notes.append(
                RiskOrQuestionItem(
                    item_type="unresolved_question",
                    description=(
                        f"NOTĂ AUDIT: {len(failed_chunks)} din {len(chunks)} fragmente nu au putut fi procesate. "
                        f"Verificați manual intervalele {intervals}."
                    ),
                    severity="high",
                )
            )
        if synthesis_note is not None:
            engine_notes.append(synthesis_note)
        if suspects:
            logger.warning(f"Prose audit flagged {len(suspects)} unverified proper noun(s): {suspects}")
            minutes.needs_name_review = True
            engine_notes.append(
                RiskOrQuestionItem(
                    item_type="unresolved_question",
                    description=(
                        "NOTĂ AUDIT: Următoarele nume/termeni din text nu au fost regăsite în transcriere și necesită "
                        f"confirmare umană: {'; '.join(suspects)}."
                    ),
                    severity="high",
                )
            )
        minutes.risks_and_questions.extend(engine_notes)

        # Grounding validation (segment ids are authoritative: quotes were copied) and deadline resolution
        return evidence_validator.validate_and_enrich(minutes, transcript, meeting, trusted_evidence=True)

    @staticmethod
    def _effective_chunk_budget(meeting_type: str) -> int:
        """
        LLM_CHUNK_TOKENS capped so that prompt + num_predict always fits the context, even on the
        repair attempt: ctx - max_tokens - (system prompt + user template + overlap sentence + repair
        turn), all measured with the same conservative char/token estimate as the chunker. Without
        this cap a repair prompt measured 3,108 real tokens and Ollama silently truncated the input.
        """
        fixed_prompt = (
            EXTRACTION_MAP_SYSTEM_PROMPT.format(meeting_type=meeting_type)
            + EXTRACTION_MAP_USER_PROMPT_TEMPLATE
            + EXTRACTION_MAP_OVERLAP_SENTENCE_TEMPLATE
            + max(EXTRACTION_MAP_REPAIR_TEMPLATE, EXTRACTION_MAP_LENGTH_REPAIR_TEMPLATE, key=len)
        )
        # ~40 tokens for ChatML role markers and the rendered line numbers
        overhead = math.ceil(len(fixed_prompt) / PROMPT_CHARS_PER_TOKEN) + 40
        available = settings.LLM_CONTEXT_TOKENS - settings.LLM_MAX_TOKENS - overhead
        return max(256, min(settings.LLM_CHUNK_TOKENS, available))

    async def _map_chunk(self, chunk: Chunk, meeting_type: str, stats: dict[str, Any]) -> Optional[MapResult]:
        """One map call with a single repair attempt; returns None when the chunk fails twice."""
        system = EXTRACTION_MAP_SYSTEM_PROMPT.format(meeting_type=meeting_type)
        overlap_sentence = ""
        if chunk.ordinal > 0 and chunk.overlap_until > chunk.first_index:
            overlap_sentence = EXTRACTION_MAP_OVERLAP_SENTENCE_TEMPLATE.format(
                first=chunk.first_index,
                overlap_last=chunk.overlap_until - 1,
                overlap_until=chunk.overlap_until,
                last=chunk.last_index,
            )
        user = EXTRACTION_MAP_USER_PROMPT_TEMPLATE.format(
            chunk_text=chunk.text,
            first=chunk.first_index,
            last=chunk.last_index,
            overlap_sentence=overlap_sentence,
        )

        error_text = ""
        for attempt in range(1 + settings.LLM_MAX_REPAIR_ATTEMPTS):
            if attempt == 0:
                prompt = user
            elif "done_reason=length" in error_text:
                # Truncated answer: asking for the same output again would truncate again
                prompt = user + EXTRACTION_MAP_LENGTH_REPAIR_TEMPLATE.format(first=chunk.first_index, last=chunk.last_index)
            else:
                prompt = user + EXTRACTION_MAP_REPAIR_TEMPLATE.format(error=error_text, first=chunk.first_index, last=chunk.last_index)
            stats["map_calls"] += 1
            try:
                raw, call_stats = await self.client.complete_json(
                    system, prompt, MAP_SCHEMA, settings.LLM_MAX_TOKENS, settings.LLM_SEED + attempt, settings.LLM_KEEP_ALIVE
                )
                self._accumulate(stats, call_stats)
                result = MapResult.model_validate(raw)
                self._check_semantics(result, chunk)
                if attempt == 0:
                    stats["map_first_pass_ok"] += 1
                logger.info(
                    f"Chunk {chunk.ordinal} (lines {chunk.first_index}-{chunk.last_index}): "
                    f"{len(result.decisions)} decisions, {len(result.action_items)} actions, {len(result.risks_and_questions)} risks "
                    f"[{call_stats.get('prompt_tokens')} prompt / {call_stats.get('completion_tokens')} completion tokens, {call_stats.get('seconds')}s, attempt {attempt + 1}]"
                )
                return result
            except LLMUnavailable:
                raise
            except (ExtractionError, ValidationError) as e:
                error_text = str(e)[:400]
                logger.warning(f"Chunk {chunk.ordinal} attempt {attempt + 1} invalid: {error_text}")
        logger.error(f"Chunk {chunk.ordinal} (lines {chunk.first_index}-{chunk.last_index}) failed after repair; recorded in failed_chunks")
        return None

    @staticmethod
    def _check_semantics(result: MapResult, chunk: Chunk) -> None:
        """Schema-valid output can still be unusable: every reported item citing only lines outside the chunk."""
        items = [*result.decisions, *result.action_items, *result.risks_and_questions]
        if not items:
            return
        in_range = [any(chunk.first_index <= i <= chunk.last_index for i in it.evidence_idx) for it in items]
        if not any(in_range):
            raise ExtractionError(
                f"toate cele {len(items)} elemente citează linii inexistente în fragment ({chunk.first_index}-{chunk.last_index})"
            )

    async def _synthesise(
        self,
        minutes: MinutesOfMeeting,
        decisions: list[dict],
        actions: list[dict],
        risks: list[dict],
        meeting_type: str,
        stats: dict[str, Any],
    ) -> Optional[RiskOrQuestionItem]:
        """
        One synthesis call over the compact merged item list; a deterministic Romanian summary when there is
        nothing to summarise. Returns the engine's audit note when the narrative could not be generated; the
        caller appends it AFTER the prose audit so the note's own vocabulary is never audited.
        """
        if not decisions and not actions and not risks:
            minutes.summary_ro = (
                "Nu au fost identificate decizii ferme, sarcini atribuite sau riscuri semnalate în transcrierea acestei ședințe. "
                "Se recomandă verificarea calității înregistrării și a transcrierii."
            )
            minutes.summary_en = (
                "No firm decisions, assigned tasks or flagged risks were identified in this meeting's transcript. "
                "Recording and transcription quality should be checked."
            )
            minutes.agenda_topics = []
            return None

        block_lines: list[str] = []
        if decisions:
            block_lines.append("DECIZII:")
            block_lines.extend(f"- [{min(d['evidence_idx'])}] ({d['category']}) {d['topic']}: {d['decision']}" for d in decisions)
        if actions:
            block_lines.append("SARCINI:")
            for a in actions:
                # The label resolve_owner enforced (roster name / verified mention / Speaker N), never the raw mention
                owner = a["owner"] if a["owner_source"] != "unassigned" else "neatribuit"
                deadline = a.get("deadline_phrase") or "fără termen"
                block_lines.append(f"- [{min(a['evidence_idx'])}] ({a['priority']}) {a['task']} (responsabil: {owner}; termen: {deadline})")
        if risks:
            block_lines.append("RISCURI / ÎNTREBĂRI:")
            block_lines.extend(f"- [{min(r['evidence_idx'])}] ({r['item_type']}, {r['severity']}) {r['description']}" for r in risks)

        system = SYNTHESIS_SYSTEM_PROMPT.format(meeting_type=meeting_type)
        user = SYNTHESIS_USER_PROMPT_TEMPLATE.format(items_block="\n".join(block_lines))

        error_text = ""
        for attempt in range(1 + settings.LLM_MAX_REPAIR_ATTEMPTS):
            prompt = user if attempt == 0 else user + SYNTHESIS_REPAIR_TEMPLATE.format(error=error_text)
            try:
                raw, call_stats = await self.client.complete_json(
                    system, prompt, SYNTHESIS_SCHEMA, settings.LLM_MAX_TOKENS, settings.LLM_SEED + attempt, settings.LLM_KEEP_ALIVE
                )
                self._accumulate(stats, call_stats)
                result = SynthesisResult.model_validate(raw)
                minutes.summary_ro = result.summary_ro.strip() or "Rezumat indisponibil."
                minutes.summary_en = result.summary_en.strip() or None
                minutes.agenda_topics = [t.strip() for t in result.agenda_topics if t.strip()]
                return None
            except LLMUnavailable:
                raise
            except (ExtractionError, ValidationError) as e:
                error_text = str(e)[:400]
                logger.warning(f"Synthesis attempt {attempt + 1} invalid: {error_text}")

        # Items stay authoritative; only the narrative is missing
        logger.error("Synthesis failed after repair; using a deterministic summary")
        minutes.summary_ro = (
            f"Rezumatul narativ nu a putut fi generat automat. Ședința a înregistrat {len(decisions)} decizii, "
            f"{len(actions)} sarcini și {len(risks)} riscuri/întrebări, listate mai jos."
        )
        minutes.summary_en = (
            f"The narrative summary could not be generated automatically. The meeting recorded {len(decisions)} decisions, "
            f"{len(actions)} tasks and {len(risks)} risks/questions, listed below."
        )
        minutes.agenda_topics = []
        return RiskOrQuestionItem(
            item_type="unresolved_question",
            description="NOTĂ AUDIT: Rezumatul executiv nu a putut fi generat de LLM-ul local; redactați-l manual înainte de aprobare.",
            severity="medium",
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _accumulate(stats: dict[str, Any], call_stats: dict) -> None:
        stats["calls"] += 1
        stats["prompt_tokens"] += int(call_stats.get("prompt_tokens", 0) or 0)
        stats["completion_tokens"] += int(call_stats.get("completion_tokens", 0) or 0)

    @staticmethod
    def _evidence_from_indices(indices: list[int], segments: list[TranscriptSegment]) -> list[EvidenceQuote]:
        """Evidence is COPIED from the cited segment: the LLM never writes a quote, a timestamp or a speaker."""
        evidence: list[EvidenceQuote] = []
        for i in indices:
            if 0 <= i < len(segments):
                seg = segments[i]
                evidence.append(
                    EvidenceQuote(segment_id=seg.id, start=seg.start, end=seg.end, quote=seg.display_text, speaker=seg.speaker)
                )
        return evidence

    @staticmethod
    def _chunk_interval(chunk: Chunk, segments: list[TranscriptSegment]) -> str:
        first = segments[chunk.overlap_until] if chunk.overlap_until < len(segments) else segments[chunk.first_index]
        last = segments[chunk.last_index]
        return f"{_mmss(first.start)}-{_mmss(last.end)}"


extraction_engine = LocalLLMExtractor()
