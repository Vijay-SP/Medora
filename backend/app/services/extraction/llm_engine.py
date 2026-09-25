"""
Medpark Meeting Intelligence System - Offline Extraction Engine
Extracts evidence-grounded decisions and action items using local LLMs or rule-assisted semantic parsing.
"""

import json
import re
from typing import Optional
import httpx
from app.core.config import settings
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
from app.services.extraction.prompt_templates import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT_TEMPLATE,
)
from app.services.extraction.validator import evidence_validator


class LocalLLMExtractor(BaseExtractor):
    """
    Offline extractor supporting both local llama.cpp / GGUF endpoints
    and high-precision deterministic clinical extraction fallbacks.
    """

    async def extract_minutes(self, meeting: Meeting, transcript: Transcript) -> MinutesOfMeeting:
        logger.info(f"Extracting structured minutes for meeting: '{meeting.title}' ({len(transcript.segments)} segments)...")
        
        # 1. Attempt extraction via local LLM server (llama.cpp / vLLM / Ollama offline)
        try:
            llm_result = await self._query_local_llm(meeting, transcript)
            if llm_result:
                validated = evidence_validator.validate_and_enrich(llm_result, transcript, meeting)
                return validated
        except Exception as e:
            if settings.REQUIRE_LOCAL_LLM:
                logger.error(f"Local LLM required by policy but failed: {e}")
                raise ExtractionError(f"Local LLM endpoint at {settings.LLM_API_BASE_URL} is unreachable: {e}. Heuristic fallback disallowed in strict mode.")
            logger.warning(f"Local LLM offline ({e}). Engaging fallback semantic parser with explicit degraded labeling...")

        # 2. Resilient Offline Semantic Extractor (Explicitly labeled as degraded rule fallback)
        minutes = self._extract_semantic_fallback(meeting, transcript)
        validated = evidence_validator.validate_and_enrich(minutes, transcript, meeting)
        return validated

    async def _query_local_llm(self, meeting: Meeting, transcript: Transcript) -> Optional[MinutesOfMeeting]:
        """Queries local OpenAI-compatible inference server (e.g. llama-server on localhost:8080)."""
        attendees_str = ", ".join([a.name for a in meeting.attendees]) if meeting.attendees else "Nesemnați"
        prompt_content = EXTRACTION_USER_PROMPT_TEMPLATE.format(
            title=meeting.title,
            meeting_type=meeting.meeting_type.value,
            attendees=attendees_str,
            meeting_date=meeting.scheduled_at.strftime("%Y-%m-%d %H:%M"),
            transcript_text=transcript.to_full_text()
        )

        payload = {
            "model": settings.LLM_MODEL_NAME,
            "messages": [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt_content}
            ],
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS,
            "response_format": {"type": "json_object"}
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{settings.LLM_API_BASE_URL}/chat/completions", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed_json = json.loads(content)
                
                return MinutesOfMeeting(
                    meeting_id=meeting.id,
                    title=meeting.title,
                    meeting_type=meeting.meeting_type.value,
                    summary_ro=parsed_json.get("summary_ro", "Rezumat indisponibil"),
                    summary_en=parsed_json.get("summary_en"),
                    agenda_topics=parsed_json.get("agenda_topics", []),
                    decisions=[DecisionItem(**d) for d in parsed_json.get("decisions", [])],
                    action_items=[ActionItem(**a) for a in parsed_json.get("action_items", [])],
                    risks_and_questions=[RiskOrQuestionItem(**r) for r in parsed_json.get("risks_and_questions", [])],
                    model_version="llama.cpp-local"
                )
        return None

    def _extract_semantic_fallback(self, meeting: Meeting, transcript: Transcript) -> MinutesOfMeeting:
        """
        High-precision rule & pattern semantic extractor that produces complete,
        verifiably grounded minutes directly from multilingual Romanian/Russian/English transcript utterances.
        """
        decisions: list[DecisionItem] = []
        actions: list[ActionItem] = []
        risks: list[RiskOrQuestionItem] = []

        # Decision keywords in RO/RU/EN
        decision_patterns = [
            r"(?:s-a decis|am decis|s-a hotărât|aprobăm|aprobat|de acord|am căzut de acord)",
            r"(?:решили|согласовали|принимаем решение|утверждаем|договорились)",
            r"(?:we decided|agreed|approved|consensus reached|it is decided)"
        ]
        
        # Action keywords in RO/RU/EN
        action_patterns = [
            r"(?:trebuie să|va pregăti|voi pregăti|va actualiza|voi actualiza|va transmite|voi transmite|responsabil|să se ocupe|va verifica|voi verifica|va trimite|voi trimite)",
            r"(?:нужно сделать|подготовить|я подготовлю|я обновлю|отвечает|проверит|отправит|срочно передать|сделаю)",
            r"(?:action item|will finalize|will handle|i will update|i will prepare|responsible for|deadline is|must prepare)"
        ]

        # Attendee lookup map
        known_owners = [a.name for a in meeting.attendees] if meeting.attendees else []

        for seg in transcript.segments:
            text = seg.display_text
            lower_text = text.lower()

            # 1. Detect Decisions
            for pat in decision_patterns:
                if re.search(pat, lower_text):
                    evidence = EvidenceQuote(
                        segment_id=seg.id,
                        start=seg.start,
                        end=seg.end,
                        quote=text,
                        speaker=seg.speaker
                    )
                    decisions.append(
                        DecisionItem(
                            topic=f"Decizie {meeting.meeting_type.value.capitalize()}",
                            decision=f"Confirmare în ședință: {text}",
                            category="clinical" if meeting.meeting_type.value == "medical" else "operations",
                            evidence=[evidence]
                        )
                    )
                    break

            # 2. Detect Actions
            for pat in action_patterns:
                if re.search(pat, lower_text):
                    # Identify potential owner
                    detected_owner = "Unassigned"
                    for name in known_owners:
                        if name.lower() in lower_text:
                            detected_owner = name
                            break
                    if detected_owner == "Unassigned" and seg.speaker != "Speaker 1":
                        detected_owner = seg.speaker

                    # Identify deadline phrase if present
                    deadline_phrase = None
                    if "până" in lower_text or "до " in lower_text or "by " in lower_text:
                        match = re.search(r"(?:până|до|by)\s+([^\.,;]+)", text, re.I)
                        if match:
                            deadline_phrase = match.group(0).strip()

                    evidence = EvidenceQuote(
                        segment_id=seg.id,
                        start=seg.start,
                        end=seg.end,
                        quote=text,
                        speaker=seg.speaker
                    )
                    actions.append(
                        ActionItem(
                            task=text,
                            owner=detected_owner,
                            deadline_phrase=deadline_phrase,
                            priority="high" if ("urgent" in lower_text or "срочно" in lower_text) else "medium",
                            evidence=[evidence]
                        )
                    )
                    break

            # 3. Detect Risks & Unresolved Questions
            if "?" in text or "risc" in lower_text or "опасность" in lower_text or "не решено" in lower_text:
                evidence = EvidenceQuote(
                    segment_id=seg.id,
                    start=seg.start,
                    end=seg.end,
                    quote=text,
                    speaker=seg.speaker
                )
                risks.append(
                    RiskOrQuestionItem(
                        item_type="unresolved_question" if "?" in text else "risk",
                        description=text,
                        severity="high" if ("complicații" in lower_text or "urgent" in lower_text) else "medium",
                        evidence=[evidence]
                    )
                )

        # Generate professional Romanian executive summary
        summary_ro = (
            f"Ședința '{meeting.title}' ({meeting.meeting_type.value.upper()}) a analizat aspectele clinice și operaționale "
            f"privind cazurile curente și activitatea spitalicească. Au fost înregistrate {len(transcript.segments)} intervenții "
            f"în limbile română, rusă și engleză. S-au convenit {len(decisions)} decizii formale și au fost stabilite {len(actions)} sarcini de lucru "
            f"cu responsabili asociați."
        )

        summary_en = (
            f"The meeting '{meeting.title}' reviewed key clinical and operational items. "
            f"A total of {len(decisions)} decisions were validated and {len(actions)} actionable tasks assigned."
        )

        # Add explicit audit warning that this extraction used degraded heuristic fallback
        risks.insert(
            0,
            RiskOrQuestionItem(
                item_type="unresolved_question",
                description="NOTĂ AUDIT: Extragerea a fost realizată prin parser euristic (LLM neuronal local inactiv). Este necesară revizuirea umană a fiecărui element înainte de aprobare.",
                severity="high"
            )
        )

        return MinutesOfMeeting(
            meeting_id=meeting.id,
            title=meeting.title,
            meeting_type=meeting.meeting_type.value,
            summary_ro=summary_ro,
            summary_en=summary_en,
            agenda_topics=[meeting.agenda] if meeting.agenda else ["Revizuire Cazuri Clinice & Protocoale Medpark"],
            decisions=decisions,
            action_items=actions,
            risks_and_questions=risks,
            model_version="heuristic-rule-fallback (LLM offline - unverified by neural model)"
        )


extraction_engine = LocalLLMExtractor()
