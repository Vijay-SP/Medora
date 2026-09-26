"""
Offline unit tests for the map/reduce LLM extraction stage.

Runs WITHOUT Ollama: a FakeClient is injected via LocalLLMExtractor(client=...). Covers the indexed
transcript rendering, the chunker, the deterministic merge, owner resolution, the free-prose name
audit and a full extract_minutes run incl. failed-chunk accounting and the failed-ratio abort.

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_llm_extraction_pipeline.py

Storage, SMTP and the LLM endpoint are isolated through environment variables BEFORE any app import:
the repository singleton binds DATA_DIR at import and the Ollama client binds its base URL at import.
"""

import os
import tempfile
from pathlib import Path

_ISOLATED_ROOT = Path(os.environ.get("DATA_DIR") or os.path.join(tempfile.mkdtemp(prefix="medpark_test_llm_"), "data"))
os.environ.setdefault("DATA_DIR", str(_ISOLATED_ROOT))
os.environ.setdefault("UPLOADS_DIR", str(_ISOLATED_ROOT / "uploads"))
os.environ.setdefault("EXPORTS_DIR", str(_ISOLATED_ROOT / "exports"))
os.environ.setdefault("FIXTURES_DIR", str(_ISOLATED_ROOT / "fixtures"))
# Never a real mail server, never a real LLM server: a dead port fails fast and deterministically
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"
os.environ["LLM_API_BASE_URL"] = "http://127.0.0.1:9"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import asyncio  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import datetime  # noqa: E402
from typing import Any, Optional  # noqa: E402
from unittest.mock import patch  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.exceptions import ExtractionError, LLMUnavailable  # noqa: E402
from app.models.meeting import Meeting, MeetingType, Attendee  # noqa: E402
from app.models.transcript import Transcript, TranscriptSegment  # noqa: E402
from app.models.extraction import MinutesOfMeeting  # noqa: E402
from app.services.extraction.chunker import build_chunks, filter_chunk_items, Chunk, estimate_tokens  # noqa: E402
from app.services.extraction.merge import merge_items  # noqa: E402
from app.services.extraction.validator import resolve_owner, audit_free_prose  # noqa: E402
from app.services.extraction.llm_engine import LocalLLMExtractor  # noqa: E402
from app.services.extraction.llm_client import llm_client  # noqa: E402
from app.services.extraction.heuristic_extractor import DEGRADED_MODEL_VERSION  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = REPO_ROOT / "tools" / "eval" / "gold" / "synthetic_trackA.json"
FAKE_PROVENANCE = "ollama 0.34.4 / medpark-extractor / Q4_K_M / ctx4096 (FAKE)"
_RANGE_PATTERN = re.compile(r"liniile (\d+)-(\d+)")


# ----------------------------------------------------------------------------- fixtures

def load_gold() -> dict[str, Any]:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def track_a_meeting_and_transcript() -> tuple[Meeting, Transcript]:
    """Builds the Track-A fragment with the SAME segment ids as the gold file, so the scorer maps evidence back."""
    gold = load_gold()
    meeting = Meeting(
        id="track-a-test",
        title=gold["meeting"]["title"],
        meeting_type=MeetingType(gold["meeting"]["meeting_type"]),
        scheduled_at=datetime.fromisoformat(gold["meeting"]["scheduled_at"]),
        attendees=[Attendee(**a) for a in gold["meeting"]["attendees"]],
    )
    segments = [
        TranscriptSegment(
            id=s["id"], start=s["start"], end=s["end"], speaker=s["speaker"], raw_text=s["text"], language=s["language"]
        )
        for s in gold["segments"]
    ]
    transcript = Transcript(meeting_id=meeting.id, segments=segments)
    transcript.compute_stats()
    return meeting, transcript


# Canned MAP answer for the whole 11-line fragment (indices are gold line indices)
TRACK_A_MAP: dict[str, Any] = {
    "decisions": [
        {
            "topic": "Protocol antibioterapie ATI",
            "decision": "Se aprobă noul protocol de antibioterapie pentru ATI, în vigoare de luni.",
            "category": "protocol",
            "evidence_idx": [4, 5],
        }
    ],
    "action_items": [
        {
            "task": "Actualizarea ghidului clinic și instruirea asistentelor conform noului protocol.",
            "owner_mention": "doctorul Popescu",
            "owner_speaker": "S1",
            "deadline_phrase": "până luni",
            "priority": "high",
            "evidence_idx": [6],
        },
        {
            "task": "Trimiterea tabelelor actualizate de dozare către toate secțiile.",
            "owner_mention": "I",
            "owner_speaker": "S3",
            "deadline_phrase": "by Friday",
            "priority": "medium",
            "evidence_idx": [7],
        },
    ],
    "risks_and_questions": [
        {
            "item_type": "risk",
            "description": "Stocul de meropenem din depozit se epuizează; este necesară o verificare urgentă.",
            "severity": "high",
            "evidence_idx": [8],
        }
    ],
}

TRACK_A_SYNTHESIS: dict[str, Any] = {
    "summary_ro": "Comitetul a aprobat noul protocol de antibioterapie pentru ATI, în vigoare de luni. Doctorul Popescu actualizează ghidul clinic până luni, iar tabelele de dozare vor fi trimise până vineri. A fost semnalat riscul epuizării stocului de meropenem.",
    "summary_en": "The committee approved the new ICU antibiotic protocol, effective Monday. The clinical guide will be updated by Monday and the dosage tables sent by Friday. A meropenem stock shortage was flagged as a risk.",
    "agenda_topics": ["Protocol antibioterapie ATI", "Stoc meropenem"],
}

EMPTY_MAP: dict[str, Any] = {"decisions": [], "action_items": [], "risks_and_questions": []}


class FakeClient:
    """
    Stands in for OllamaClient. MAP answers are chosen per chunk from the "liniile {first}-{last}" range in the
    user prompt: items whose evidence falls inside the chunk are returned, others are omitted (exactly what a
    well-behaved model would do). Chunks whose first line is in `fail_first_indices` answer with schema-invalid
    JSON on every attempt, so the engine's repair turn and failed-chunk accounting are exercised.
    """

    def __init__(
        self,
        map_answer: dict[str, Any],
        synthesis_answer: dict[str, Any],
        fail_first_indices: Optional[set[int]] = None,
        unavailable_after_calls: Optional[int] = None,
        ready: bool = True,
    ):
        self.map_answer = map_answer
        self.synthesis_answer = synthesis_answer
        self.fail_first_indices = fail_first_indices or set()
        self.unavailable_after_calls = unavailable_after_calls
        self.ready = ready
        self.calls: list[dict[str, Any]] = []
        self.unload_calls = 0

    async def health(self) -> tuple[bool, str]:
        return self.ready, "fake"

    async def assert_ready(self) -> str:
        if not self.ready:
            raise LLMUnavailable("LLM local indisponibil: fake server down")
        return FAKE_PROVENANCE

    async def complete_json(self, system: str, user: str, schema: dict, max_tokens: int, seed: int, keep_alive: str) -> tuple[dict, dict]:
        is_synthesis = "summary_ro" in schema.get("properties", {})
        repair = "RĂSPUNSUL ANTERIOR A FOST INVALID" in user
        record = {"kind": "synthesis" if is_synthesis else "map", "seed": seed, "repair": repair, "user": user, "system": system}
        self.calls.append(record)
        if self.unavailable_after_calls is not None and len(self.calls) > self.unavailable_after_calls:
            raise LLMUnavailable("LLM local indisponibil: fake server went away mid-run")
        stats = {"prompt_tokens": max(1, len(user) // 4), "completion_tokens": 40, "seconds": 0.01}
        if is_synthesis:
            return dict(self.synthesis_answer), stats

        m = _RANGE_PATTERN.search(user)
        assert m, "map prompt must state the line range"
        first, last = int(m.group(1)), int(m.group(2))
        record["first"], record["last"] = first, last
        # Prompt hygiene: the roster, date and title must never reach the model
        assert "Ceban" not in user and "Ceban" not in system
        assert "2026" not in user and "2026" not in system
        if first in self.fail_first_indices:
            return {"decisions": [{"topic": "broken"}], "action_items": [], "risks_and_questions": []}, stats
        answer: dict[str, Any] = {}
        for key in ("decisions", "action_items", "risks_and_questions"):
            answer[key] = [
                dict(item) for item in self.map_answer.get(key, [])
                if any(first <= i <= last for i in item["evidence_idx"])
            ]
        return answer, stats

    async def unload(self) -> None:
        self.unload_calls += 1


def _run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------------------- C1 indexed lines

def test_to_indexed_lines():
    _, transcript = track_a_meeting_and_transcript()
    lines, ids = transcript.to_indexed_lines()
    assert len(lines) == len(ids) == 11
    assert ids == [f"seg_{i:02d}" for i in range(11)]
    # Speaker label only when the speaker changes, "Speaker N" shortened to "SN"
    assert lines[0].startswith("0 S1: ")
    assert lines[1].startswith("1 S2: ")
    assert lines[3].startswith("3 S2: ")           # S1 spoke line 2 in between
    assert lines[4].startswith("4 ") and not lines[4].startswith("4 S")   # same speaker as line 3
    assert lines[9].startswith("9 S1: ")                                   # S2 spoke line 8
    assert lines[10].startswith("10 ") and not lines[10].startswith("10 S")   # continuation of S1
    assert "Speaker" not in "\n".join(lines)
    # No timestamps ever reach the LLM; to_full_text keeps them for humans
    assert "[" not in "\n".join(lines)
    assert transcript.to_full_text().startswith("[00:00 - 00:06] Speaker 1:")
    # corrected_text wins over raw_text
    transcript.segments[2].corrected_text = "Text corectat"
    lines2, _ = transcript.to_indexed_lines()
    assert lines2[2] == "2 S1: Text corectat"
    print("PASSED: test_to_indexed_lines")


# ----------------------------------------------------------------------------- C13 chunker

def _padded_line(i: int, speaker: Optional[str], width: int) -> str:
    head = f"{i} {speaker}: " if speaker else f"{i} "
    body = "x" * max(0, width - len(head))
    return (head + body)[:width]


def _assert_chunks_cover_lines(chunks: list[Chunk], lines: list[str]) -> None:
    covered: list[int] = []
    for k, c in enumerate(chunks):
        assert c.ordinal == k
        assert c.first_index <= c.overlap_until <= c.last_index
        # Never splits a line: the chunk text is exactly the joined source lines
        assert c.text == "\n".join(lines[c.first_index:c.last_index + 1])
        covered.extend(range(c.overlap_until, c.last_index + 1))
    assert covered == list(range(len(lines))), "every line is fresh in exactly one chunk"


def test_build_chunks_never_splits_and_covers_everything():
    lines = [_padded_line(i, f"S{i % 3 + 1}" if i % 4 == 0 else None, 37 + (i * 7) % 23) for i in range(60)]
    for budget, overlap in [(50, 0), (120, 30), (300, 60), (10_000, 200)]:
        chunks = build_chunks(lines, budget, overlap)
        assert chunks, "non-empty input yields chunks"
        _assert_chunks_cover_lines(chunks, lines)
        for c in chunks:
            fresh_cost = sum(estimate_tokens(lines[i]) + 1 for i in range(c.overlap_until, c.last_index + 1))
            oversize_single = c.overlap_until == c.last_index
            assert fresh_cost <= budget or oversize_single
    assert build_chunks([], 100, 10) == []
    print("PASSED: test_build_chunks_never_splits_and_covers_everything")


def test_build_chunks_overlap_semantics():
    lines = [_padded_line(i, "S1" if i == 0 else None, 38) for i in range(20)]   # cost 20 each
    # Overlap counts against the budget: chunk 0 holds 5 fresh lines, every later chunk 2 overlap + 3 fresh
    chunks = build_chunks(lines, 100, 45)   # 2 overlap lines (2*20 <= 45 < 3*20)
    assert len(chunks) == 6
    assert (chunks[0].first_index, chunks[0].last_index) == (0, 4)
    assert (chunks[1].first_index, chunks[1].overlap_until, chunks[1].last_index) == (3, 5, 7)
    assert chunks[0].first_index == chunks[0].overlap_until == 0
    for prev, cur in zip(chunks, chunks[1:]):
        assert cur.overlap_until == prev.last_index + 1
        assert cur.first_index == cur.overlap_until - 2, "overlap re-shows the previous chunk's tail within the overlap budget"
        overlap_cost = sum(estimate_tokens(lines[i]) + 1 for i in range(cur.first_index, cur.overlap_until))
        assert overlap_cost <= 45
    # Zero overlap: chunks are disjoint
    for c in build_chunks(lines, 100, 0):
        assert c.first_index == c.overlap_until
    print("PASSED: test_build_chunks_overlap_semantics")


def test_build_chunks_oversize_line_is_its_own_chunk():
    lines = [_padded_line(0, "S1", 20), _padded_line(1, None, 600), _padded_line(2, "S2", 20)]
    chunks = build_chunks(lines, 50, 10)
    assert len(chunks) == 3
    assert (chunks[1].first_index, chunks[1].last_index) == (1, 1)
    assert chunks[1].text == lines[1]
    _assert_chunks_cover_lines(chunks, lines)
    print("PASSED: test_build_chunks_oversize_line_is_its_own_chunk")


def test_build_chunks_prefers_speaker_turn_boundary():
    # Every line costs 10 tokens (18 chars -> 9 + 1 newline); budget 50 fits 5 lines greedily.
    # Speaker turns start at 0, 3, 6: the cut must move back from line 4 to line 2 (within 3 candidates).
    lines = [_padded_line(i, f"S{i // 3 + 1}" if i % 3 == 0 else None, 18) for i in range(9)]
    chunks = build_chunks(lines, 50, 0, turn_starts={0, 3, 6})
    assert [(c.first_index, c.last_index) for c in chunks] == [(0, 2), (3, 5), (6, 8)]
    # Same result from the default "N SK: " detection when turn_starts is not passed
    chunks_auto = build_chunks(lines, 50, 0)
    assert [(c.first_index, c.last_index) for c in chunks_auto] == [(0, 2), (3, 5), (6, 8)]
    # The boundary is only used when it is within the last 3 candidate lines: turn at 1 is too far back
    chunks_far = build_chunks(lines, 50, 0, turn_starts={0, 1})
    assert (chunks_far[0].first_index, chunks_far[0].last_index) == (0, 4)
    print("PASSED: test_build_chunks_prefers_speaker_turn_boundary")


def test_filter_chunk_items():
    chunk = Chunk(ordinal=1, first_index=10, last_index=20, overlap_until=13, text="")
    items = [
        {"task": "in range", "evidence_idx": [15, 99]},
        {"task": "out of range only", "evidence_idx": [3, 99]},
        {"task": "overlap only (previous chunk reported it)", "evidence_idx": [10, 12]},
        {"task": "straddles overlap", "evidence_idx": [12, 13]},
    ]
    kept = filter_chunk_items(items, chunk)
    assert [k["task"] for k in kept] == ["in range", "straddles overlap"]
    assert kept[0]["evidence_idx"] == [15]
    # Chunk 0 has no previous chunk: nothing is treated as overlap
    kept0 = filter_chunk_items([{"task": "a", "evidence_idx": [0]}], Chunk(0, 0, 5, 0, ""))
    assert len(kept0) == 1
    print("PASSED: test_filter_chunk_items")


# ----------------------------------------------------------------------------- C13 merge

def test_merge_items_rules():
    # Rule 1: intersecting evidence -> one item, longer text, union evidence, max priority, first non-null owner
    a = {"task": "Actualizare ghid", "priority": "medium", "owner_mention": None, "deadline_phrase": "până luni", "evidence_idx": [6]}
    b = {"task": "Actualizarea ghidului clinic și instruirea asistentelor", "priority": "high", "owner_mention": "doctorul Popescu", "deadline_phrase": None, "evidence_idx": [6, 7]}
    merged = merge_items([a, b], "task")
    assert len(merged) == 1
    assert merged[0]["task"] == b["task"]
    assert merged[0]["evidence_idx"] == [6, 7]
    assert merged[0]["priority"] == "high"
    assert merged[0]["owner_mention"] == "doctorul Popescu"
    assert merged[0]["deadline_phrase"] == "până luni"

    # Rule 2: near-identical text within 12 lines -> merged; the same text 13+ lines apart stays separate
    near1 = {"decision": "Se aprobă protocolul de antibioterapie pentru ATI.", "evidence_idx": [4]}
    near2 = {"decision": "Se aproba protocolul de antibioterapie pentru ATI", "evidence_idx": [16]}
    far = {"decision": "Se aprobă protocolul de antibioterapie pentru ATI.", "evidence_idx": [40]}
    out = merge_items([near1, near2, far], "decision")
    assert len(out) == 2
    assert out[0]["evidence_idx"] == [4, 16]
    assert out[1]["evidence_idx"] == [40]

    # Different text, disjoint evidence -> never merged; output ordered by min(evidence_idx)
    x = {"decision": "Extindere secție ATI la anul", "evidence_idx": [30]}
    y = {"decision": "Se aprobă bugetul pentru RMN", "evidence_idx": [2]}
    out2 = merge_items([x, y], "decision")
    assert [o["evidence_idx"] for o in out2] == [[2], [30]]
    # Items without evidence are dropped
    assert merge_items([{"decision": "fără dovezi", "evidence_idx": []}], "decision") == []
    print("PASSED: test_merge_items_rules")


# ----------------------------------------------------------------------------- C10 owner resolution

def test_resolve_owner_branches():
    _, transcript = track_a_meeting_and_transcript()
    attendees = [
        Attendee(name="Dr. Elena Ceban", email="elena.ceban@medpark.md"),
        Attendee(name="Dr. Ion Popescu", email="ion.popescu@medpark.md"),
    ]
    seg6 = transcript.segments[6]   # "Atunci doctorul Popescu va actualiza ..."
    seg7 = transcript.segments[7]   # "I will send ..."

    # 3. roster: verbatim mention present in the cited line, fuzzy-matched to the roster
    assert resolve_owner("doctorul Popescu", "S1", [seg6], attendees) == ("Dr. Ion Popescu", "roster")
    assert resolve_owner("Doctorul POPESCU", "S1", [seg6], attendees) == ("Dr. Ion Popescu", "roster")
    # 2. fabricated: mention not spoken in the cited lines -> discarded, falls through to the speaker label
    assert resolve_owner("doctorul Ionescu", "S1", [seg6], attendees) == ("Speaker 1", "speaker")
    assert resolve_owner("Dr. Ion Popescu", "S1", [seg7], attendees) == ("Speaker 1", "speaker")
    # 1. pronoun / too short -> no mention
    assert resolve_owner("I", "S3", [seg7], attendees) == ("Speaker 3", "speaker")
    assert resolve_owner("eu", "S2", [seg6], attendees) == ("Speaker 2", "speaker")
    assert resolve_owner("я", None, [seg6], attendees) == ("Unassigned", "unassigned")
    assert resolve_owner("ab", "S4", [seg6], attendees) == ("Speaker 4", "speaker")
    # 4. mention: spoken, but nobody on the roster -> kept verbatim for a human to confirm
    seg_extra = TranscriptSegment(id="x", start=60.0, end=62.0, speaker="Speaker 2", raw_text="Asistenta Rusu va pregăti raportul de gardă.")
    assert resolve_owner("asistenta Rusu", "S2", [seg_extra], attendees) == ("asistenta Rusu", "mention")
    # 5. speaker label only (never a person name), 6. nothing verifiable
    assert resolve_owner(None, "S2", [seg6], attendees) == ("Speaker 2", "speaker")
    assert resolve_owner(None, None, [seg6], attendees) == ("Unassigned", "unassigned")
    assert resolve_owner(None, "somebody", [seg6], attendees) == ("Unassigned", "unassigned")
    print("PASSED: test_resolve_owner_branches")


# ----------------------------------------------------------------------------- C10 prose audit

def test_audit_free_prose():
    meeting, transcript = track_a_meeting_and_transcript()

    def minutes_with(summary_ro: str, **extra) -> MinutesOfMeeting:
        return MinutesOfMeeting(meeting_id=meeting.id, title=meeting.title, summary_ro=summary_ro, **extra)

    # Whitelisted institution/department/calendar words, roster names, transcript words and sentence starts pass
    clean = minutes_with(
        "Ședința comitetului Medpark a aprobat protocolul ATI. Doctorul Popescu actualizează ghidul până Luni. Dr. Elena Ceban a prezidat.",
        summary_en="The committee approved the ICU protocol. Sarah Mitchell sends the tables by Friday.",
        agenda_topics=["Protocol antibioterapie ATI", "Stoc meropenem"],
    )
    assert audit_free_prose(clean, transcript, meeting) == []

    # A name that was never spoken and is not on the roster is caught wherever it appears
    fabricated = minutes_with("Protocolul a fost prezentat de doctorul Ionescu în ședință.")
    suspects = audit_free_prose(fabricated, transcript, meeting)
    assert any("Ionescu" in s for s in suspects), suspects

    # The abbreviated form from the brief ("Dr. Ionescu") must be caught as well
    abbreviated = minutes_with("Protocolul a fost prezentat de Dr. Ionescu în ședință.")
    suspects_abbrev = audit_free_prose(abbreviated, transcript, meeting)
    assert any("Ionescu" in s for s in suspects_abbrev), f"'Dr. Ionescu' not flagged: {suspects_abbrev}"

    # Fabrication inside item texts and agenda topics is caught too
    in_topics = minutes_with("Rezumat.", agenda_topics=["Vizita Spitalul Sfântul Andrei"])
    assert audit_free_prose(in_topics, transcript, meeting), "agenda topic with an unknown proper noun run must be flagged"
    print("PASSED: test_audit_free_prose")


# ----------------------------------------------------------------------------- C6 full run with a FakeClient

def test_extract_minutes_with_fake_client() -> MinutesOfMeeting:
    meeting, transcript = track_a_meeting_and_transcript()
    fake = FakeClient(TRACK_A_MAP, TRACK_A_SYNTHESIS)
    engine = LocalLLMExtractor(client=fake)
    minutes = _run(engine.extract_minutes(meeting, transcript))

    # Provenance and audit flags
    assert minutes.model_version == FAKE_PROVENANCE
    assert minutes.is_degraded is False
    assert minutes.failed_chunks == []
    assert fake.unload_calls == 1, "VRAM is released after every meeting"
    stats = minutes.extraction_stats
    for key in ("engine", "model", "chunks", "calls", "prompt_tokens", "completion_tokens", "seconds", "json_first_pass_rate"):
        assert key in stats, key
    assert stats["chunks"] == 1 and stats["calls"] == 2 and stats["json_first_pass_rate"] == 1.0
    assert [c["kind"] for c in fake.calls] == ["map", "synthesis"]
    assert fake.calls[0]["seed"] == settings.LLM_SEED
    assert "liniile 0-10" in fake.calls[0]["user"]
    # Synthesis sees the merged item list, never the transcript lines
    assert "DECIZII:" in fake.calls[1]["user"] and "Bună dimineața" not in fake.calls[1]["user"]

    # Decision: evidence COPIED from the cited segments (quote, timestamps, speaker), never authored by the model
    assert len(minutes.decisions) == 1
    dec = minutes.decisions[0]
    assert [e.segment_id for e in dec.evidence] == ["seg_04", "seg_05"]
    for ev in dec.evidence:
        seg = next(s for s in transcript.segments if s.id == ev.segment_id)
        assert ev.quote == seg.display_text and ev.start == seg.start and ev.end == seg.end and ev.speaker == seg.speaker
    assert dec.category == "protocol"

    # Actions: roster owner via verbatim mention, deadline phrase resolved to an ISO date from the meeting date
    assert len(minutes.action_items) == 2
    a1, a2 = minutes.action_items
    assert (a1.owner, a1.owner_source) == ("Dr. Ion Popescu", "roster")
    assert a1.deadline_phrase == "până luni" and a1.deadline_date == "2026-09-28"
    assert a1.evidence[0].segment_id == "seg_06" and a1.evidence[0].quote == transcript.segments[6].display_text
    # The English first-person "I" is verbatim but useless: anonymous speaker label, never a person name
    assert (a2.owner, a2.owner_source) == ("Speaker 3", "speaker")
    assert a2.deadline_phrase == "by Friday" and a2.deadline_date == "2026-09-25"
    assert a2.priority == "medium" and a1.priority == "high"

    # Risk carried with copied evidence; no name review needed (roster owner + clean prose)
    assert len(minutes.risks_and_questions) == 1
    assert minutes.risks_and_questions[0].evidence[0].segment_id == "seg_08"
    assert minutes.needs_name_review is False
    assert minutes.summary_ro == TRACK_A_SYNTHESIS["summary_ro"]
    assert minutes.agenda_topics == TRACK_A_SYNTHESIS["agenda_topics"]

    out_path = Path(settings.DATA_DIR) / "trackA_fake_minutes.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(minutes.model_dump_json(indent=2), encoding="utf-8")
    print(f"PASSED: test_extract_minutes_with_fake_client (minutes written to {out_path})")
    return minutes


def test_needs_name_review_semantics():
    meeting, transcript = track_a_meeting_and_transcript()
    # A spoken, non-roster owner: kept verbatim, flagged for a human
    transcript.segments.append(
        TranscriptSegment(id="seg_11", start=58.5, end=62.0, speaker="Speaker 2", raw_text="Asistenta Rusu va pregăti raportul de gardă până vineri.")
    )
    map_answer = {
        "decisions": [],
        "action_items": [{
            "task": "Pregătirea raportului de gardă.", "owner_mention": "asistenta Rusu", "owner_speaker": "S2",
            "deadline_phrase": "până vineri", "priority": "medium", "evidence_idx": [11],
        }],
        "risks_and_questions": [],
    }
    synthesis = {"summary_ro": "Asistenta Rusu pregătește raportul de gardă până vineri.", "summary_en": "The duty report is due Friday.", "agenda_topics": ["Raport de gardă"]}
    minutes = _run(LocalLLMExtractor(client=FakeClient(map_answer, synthesis)).extract_minutes(meeting, transcript))
    assert minutes.needs_name_review is True
    assert (minutes.action_items[0].owner, minutes.action_items[0].owner_source) == ("asistenta Rusu", "mention")
    assert not any("NOTĂ AUDIT" in r.description for r in minutes.risks_and_questions), "a spoken name is not a prose fabrication"

    # A fabricated owner mention is discarded (falls back to the speaker label) and does not by itself flag review
    map_fab = {
        "decisions": [],
        "action_items": [{
            "task": "Pregătirea raportului de gardă.", "owner_mention": "doctorul Ionescu", "owner_speaker": "S2",
            "deadline_phrase": None, "priority": "low", "evidence_idx": [11],
        }],
        "risks_and_questions": [],
    }
    clean_synth = {"summary_ro": "Raportul de gardă va fi pregătit.", "summary_en": "The duty report will be prepared.", "agenda_topics": []}
    minutes2 = _run(LocalLLMExtractor(client=FakeClient(map_fab, clean_synth)).extract_minutes(meeting, transcript))
    assert (minutes2.action_items[0].owner, minutes2.action_items[0].owner_source) == ("Speaker 2", "speaker")
    assert minutes2.needs_name_review is False

    # A fabricated proper noun in the synthesis prose: ONE high-severity audit item + needs_name_review
    fab_synth = {"summary_ro": "Protocolul a fost prezentat de doctorul Vasilescu.", "summary_en": "Presented by doctor Vasilescu.", "agenda_topics": []}
    minutes3 = _run(LocalLLMExtractor(client=FakeClient(map_fab, fab_synth)).extract_minutes(meeting, transcript))
    audits = [r for r in minutes3.risks_and_questions if "NOTĂ AUDIT" in r.description and "Vasilescu" in r.description]
    assert len(audits) == 1 and audits[0].severity == "high"
    assert minutes3.needs_name_review is True
    print("PASSED: test_needs_name_review_semantics")


@contextmanager
def one_line_per_chunk():
    """
    Forces every Track-A line into its own chunk. The engine floors the chunk budget at 256 tokens, so the
    budget alone cannot do it; an absurd chars-per-token ratio makes each 40-110 char line an oversize line,
    which the chunker must emit on its own (11 lines -> 11 chunks, 11 map calls).
    """
    with patch.object(settings, "LLM_CHUNK_TOKENS", 256), \
         patch.object(settings, "LLM_CHUNK_OVERLAP_TOKENS", 0), \
         patch.object(settings, "LLM_CHARS_PER_TOKEN", 0.05):
        yield


def test_failed_chunk_accounting():
    meeting, transcript = track_a_meeting_and_transcript()
    fake = FakeClient(TRACK_A_MAP, TRACK_A_SYNTHESIS, fail_first_indices={6})   # chunk 6 = the Popescu action line
    with one_line_per_chunk():
        minutes = _run(LocalLLMExtractor(client=fake).extract_minutes(meeting, transcript))
    assert minutes.extraction_stats["chunks"] == 11, minutes.extraction_stats
    assert [c.get("first") for c in fake.calls if c["kind"] == "map" and not c["repair"]] == list(range(11))

    assert minutes.failed_chunks == [6]
    map_calls = [c for c in fake.calls if c["kind"] == "map"]
    assert len(map_calls) == 12, "11 chunks + exactly one repair attempt"
    repairs = [c for c in map_calls if c["repair"]]
    assert len(repairs) == 1 and repairs[0]["first"] == 6 and repairs[0]["seed"] == settings.LLM_SEED + 1
    assert minutes.extraction_stats["chunks"] == 11
    assert minutes.extraction_stats["calls"] == 13
    # One chunk needed a repair: the first-pass rate must drop below 1.0 (the engine divides by map calls incl. the repair)
    assert 0.8 <= minutes.extraction_stats["json_first_pass_rate"] < 1.0, minutes.extraction_stats
    # The rest of the meeting is still extracted; the failed interval is named for manual review (mm:ss-mm:ss)
    assert len(minutes.decisions) == 1 and [e.segment_id for e in minutes.decisions[0].evidence] == ["seg_04", "seg_05"]
    assert [a.evidence[0].segment_id for a in minutes.action_items] == ["seg_07"]
    notes = [r for r in minutes.risks_and_questions if r.description.startswith("NOTĂ AUDIT: 1 din 11 fragmente")]
    assert len(notes) == 1 and notes[0].severity == "high"
    assert re.search(r"\d{2}:\d{2}-\d{2}:\d{2}", notes[0].description), notes[0].description
    assert "00:35-00:41" in notes[0].description
    assert fake.unload_calls == 1
    print("PASSED: test_failed_chunk_accounting")


def test_failed_ratio_abort():
    meeting, transcript = track_a_meeting_and_transcript()
    fake = FakeClient(TRACK_A_MAP, TRACK_A_SYNTHESIS, fail_first_indices={1, 3, 8})   # 3/11 = 0.27 > 0.20
    with one_line_per_chunk():
        try:
            _run(LocalLLMExtractor(client=fake).extract_minutes(meeting, transcript))
            raise AssertionError("expected ExtractionError")
        except ExtractionError as e:
            assert not isinstance(e, LLMUnavailable)
            assert "3 din 11" in str(e)
    assert fake.unload_calls == 1, "unload runs in the finally-block even when the run aborts"
    assert not any(c["kind"] == "synthesis" for c in fake.calls)
    print("PASSED: test_failed_ratio_abort")


def test_llm_unavailable_mid_run_aborts():
    meeting, transcript = track_a_meeting_and_transcript()
    fake = FakeClient(TRACK_A_MAP, TRACK_A_SYNTHESIS, unavailable_after_calls=2)
    with one_line_per_chunk():
        try:
            _run(LocalLLMExtractor(client=fake).extract_minutes(meeting, transcript))
            raise AssertionError("expected LLMUnavailable")
        except LLMUnavailable:
            pass
    assert len(fake.calls) == 3, "no repair attempt and no further chunks after the server vanished"
    assert fake.unload_calls == 1
    print("PASSED: test_llm_unavailable_mid_run_aborts")


def test_kill_switch_policy():
    meeting, transcript = track_a_meeting_and_transcript()
    down = FakeClient(TRACK_A_MAP, TRACK_A_SYNTHESIS, ready=False)

    # Default policy: no LLM -> LLMUnavailable, no heuristic path
    with patch.object(settings, "REQUIRE_LOCAL_LLM", True), patch.object(settings, "LLM_FALLBACK_MODE", "fail"):
        try:
            _run(LocalLLMExtractor(client=down).preflight())
            raise AssertionError("expected LLMUnavailable")
        except LLMUnavailable:
            pass
    # REQUIRE_LOCAL_LLM off but fallback "fail": still no heuristic path
    with patch.object(settings, "REQUIRE_LOCAL_LLM", False), patch.object(settings, "LLM_FALLBACK_MODE", "fail"):
        try:
            _run(LocalLLMExtractor(client=down).extract_minutes(meeting, transcript))
            raise AssertionError("expected LLMUnavailable")
        except LLMUnavailable:
            pass
    # Explicitly allowed degraded mode: heuristic minutes, stamped and non-dispatchable
    with patch.object(settings, "REQUIRE_LOCAL_LLM", False), patch.object(settings, "LLM_FALLBACK_MODE", "heuristic"):
        engine = LocalLLMExtractor(client=down)
        assert _run(engine.preflight()) == "heuristic-fallback"
        minutes = _run(engine.extract_minutes(meeting, transcript))
    assert minutes.is_degraded is True
    assert minutes.model_version == DEGRADED_MODEL_VERSION == "DEGRADED-heuristic-no-LLM"
    assert down.calls == [] and down.unload_calls == 0
    # The module-level singleton was bound to the dead port by the env: nothing here can reach a real Ollama
    assert llm_client.base_url == "http://127.0.0.1:9"
    print("PASSED: test_kill_switch_policy")


if __name__ == "__main__":
    assert Path(settings.DATA_DIR) == _ISOLATED_ROOT, "storage isolation must be in place before app import"
    assert not Path(settings.DATA_DIR).resolve().is_relative_to(REPO_ROOT / "data") or os.environ.get("DATA_DIR"), "never the production data dir"
    test_to_indexed_lines()
    test_build_chunks_never_splits_and_covers_everything()
    test_build_chunks_overlap_semantics()
    test_build_chunks_oversize_line_is_its_own_chunk()
    test_build_chunks_prefers_speaker_turn_boundary()
    test_filter_chunk_items()
    test_merge_items_rules()
    test_resolve_owner_branches()
    test_audit_free_prose()
    test_extract_minutes_with_fake_client()
    test_needs_name_review_semantics()
    test_failed_chunk_accounting()
    test_failed_ratio_abort()
    test_llm_unavailable_mid_run_aborts()
    test_kill_switch_policy()
    print("All offline LLM extraction pipeline tests passed successfully!")
