"""
Live Track-A extraction against the real local Ollama server.

Skips cleanly (exit 0, prints "SKIPPED: Ollama not reachable") when GET /api/version fails, so the
offline suite never depends on it. Never runs Whisper: the transcript is the hand-written 11-line
RO/RU/EN fragment from tools/eval/gold/synthetic_trackA.json. The LLM (~2.7 GB) is loaded on the
GPU for the duration of the run and unloaded by the engine afterwards.

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_llm_extraction_live.py

Storage and SMTP are isolated through environment variables BEFORE any app import; the LLM endpoint
is the configured one (LLM_API_BASE_URL, default http://127.0.0.1:11434).
"""

import os
import sys
import tempfile
from pathlib import Path

_ISOLATED_ROOT = Path(os.environ.get("DATA_DIR") or os.path.join(tempfile.mkdtemp(prefix="medpark_test_llm_live_"), "data"))
os.environ.setdefault("DATA_DIR", str(_ISOLATED_ROOT))
os.environ.setdefault("UPLOADS_DIR", str(_ISOLATED_ROOT / "uploads"))
os.environ.setdefault("EXPORTS_DIR", str(_ISOLATED_ROOT / "exports"))
os.environ.setdefault("FIXTURES_DIR", str(_ISOLATED_ROOT / "fixtures"))
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import asyncio  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402
import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.meeting import Meeting, MeetingType, Attendee  # noqa: E402
from app.models.transcript import Transcript, TranscriptSegment  # noqa: E402
from app.services.extraction.llm_engine import LocalLLMExtractor  # noqa: E402
from app.services.extraction.llm_client import llm_client  # noqa: E402
from app.services.extraction.validator import normalise_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = REPO_ROOT / "tools" / "eval" / "gold" / "synthetic_trackA.json"
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def ollama_reachable() -> bool:
    try:
        resp = httpx.get(f"{settings.LLM_API_BASE_URL.rstrip('/')}/api/version", timeout=settings.LLM_HEALTH_TIMEOUT_S)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def model_loaded() -> bool:
    try:
        resp = httpx.get(f"{settings.LLM_API_BASE_URL.rstrip('/')}/api/ps", timeout=settings.LLM_HEALTH_TIMEOUT_S)
        names = [m.get("name", "").split(":")[0] for m in resp.json().get("models", [])]
        return settings.LLM_MODEL_NAME in names
    except (httpx.HTTPError, ValueError):
        return False


def build_track_a() -> tuple[Meeting, Transcript]:
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    meeting = Meeting(
        id="track-a-live",
        title=gold["meeting"]["title"],
        meeting_type=MeetingType(gold["meeting"]["meeting_type"]),
        scheduled_at=datetime.fromisoformat(gold["meeting"]["scheduled_at"]),
        attendees=[Attendee(**a) for a in gold["meeting"]["attendees"]],
    )
    segments = [
        TranscriptSegment(id=s["id"], start=s["start"], end=s["end"], speaker=s["speaker"], raw_text=s["text"], language=s["language"])
        for s in gold["segments"]
    ]
    transcript = Transcript(meeting_id=meeting.id, segments=segments)
    transcript.compute_stats()
    return meeting, transcript


def test_track_a_live_extraction() -> None:
    meeting, transcript = build_track_a()
    segment_text = {s.id: s.display_text for s in transcript.segments}

    started = time.perf_counter()
    provenance = asyncio.run(llm_client.assert_ready())
    preflight_s = time.perf_counter() - started
    assert provenance.startswith("ollama ") and settings.LLM_MODEL_NAME in provenance, provenance

    started = time.perf_counter()
    # Spy on the unload so the VRAM hand-off is asserted even when other clients keep the model resident
    with patch.object(llm_client, "unload", new=AsyncMock(wraps=llm_client.unload)) as unload_spy:
        minutes = asyncio.run(LocalLLMExtractor().extract_minutes(meeting, transcript))
    elapsed = time.perf_counter() - started
    stats = minutes.extraction_stats

    print(f"provenance      : {provenance}  (preflight {preflight_s:.2f}s)")
    print(f"wall time       : {elapsed:.1f}s for {len(transcript.segments)} lines, {stats.get('chunks')} chunk(s), {stats.get('calls')} LLM calls")
    print(f"tokens          : {stats.get('prompt_tokens')} prompt / {stats.get('completion_tokens')} completion, first-pass rate {stats.get('json_first_pass_rate')}")
    for d in minutes.decisions:
        print(f"decision        : [{', '.join(e.segment_id for e in d.evidence)}] ({d.category}) {d.decision}")
    for a in minutes.action_items:
        print(f"action          : [{', '.join(e.segment_id for e in a.evidence)}] owner={a.owner!r} ({a.owner_source}) deadline={a.deadline_phrase!r} -> {a.deadline_date} :: {a.task}")
    for r in minutes.risks_and_questions:
        print(f"risk/question   : [{', '.join(e.segment_id for e in r.evidence)}] ({r.item_type}, {r.severity}) {r.description}")
    print(f"summary_ro      : {minutes.summary_ro}")
    print(f"needs_name_review={minutes.needs_name_review} is_degraded={minutes.is_degraded} failed_chunks={minutes.failed_chunks}")

    # Provenance and integrity
    assert minutes.is_degraded is False
    assert minutes.model_version == provenance
    assert minutes.failed_chunks == []
    assert stats["engine"] == "ollama" and stats["calls"] >= 2

    # Every citation is copied verbatim from the cited segment: the model cannot author evidence
    all_items = [*minutes.decisions, *minutes.action_items, *minutes.risks_and_questions]
    for item in all_items:
        for ev in item.evidence:
            assert ev.segment_id in segment_text, ev.segment_id
            assert ev.quote == segment_text[ev.segment_id]

    # ONE firm decision (RU decision + RO confirmation), cited on lines 4/5, written in Romanian
    assert len(minutes.decisions) == 1, [d.decision for d in minutes.decisions]
    dec = minutes.decisions[0]
    cited = {e.segment_id for e in dec.evidence}
    assert cited & {"seg_04", "seg_05"}, cited
    assert cited <= {"seg_03", "seg_04", "seg_05"}, cited
    assert "seg_02" not in cited, "the 'poate ar fi bine...' proposal is not a decision"
    assert not _CYRILLIC.search(dec.decision), dec.decision
    assert "antibio" in normalise_text(dec.decision), dec.decision

    # Actions: the Popescu task resolves to the roster through the verbatim mention, deadline "până luni" -> Monday
    by_segment = {e.segment_id: a for a in minutes.action_items for e in a.evidence}
    assert "seg_06" in by_segment, [a.task for a in minutes.action_items]
    popescu = by_segment["seg_06"]
    assert (popescu.owner, popescu.owner_source) == ("Dr. Ion Popescu", "roster"), (popescu.owner, popescu.owner_source)
    assert popescu.deadline_phrase and "pana luni" in normalise_text(popescu.deadline_phrase), popescu.deadline_phrase
    assert popescu.deadline_date == "2026-09-28", popescu.deadline_date
    # The English first-person task: verbatim "by Friday", owner is the anonymous speaker label, never a name
    assert "seg_07" in by_segment, [a.task for a in minutes.action_items]
    friday = by_segment["seg_07"]
    assert friday.deadline_phrase and "by friday" in normalise_text(friday.deadline_phrase), friday.deadline_phrase
    assert friday.deadline_date == "2026-09-25", friday.deadline_date
    assert friday.owner in ("Speaker 3", "Unassigned"), friday.owner
    # No action may carry a fabricated name
    for a in minutes.action_items:
        assert a.owner_source != "mention" or normalise_text(a.owner) in normalise_text(" ".join(segment_text.values())), a.owner

    # The meropenem risk line is found
    assert any(e.segment_id == "seg_08" for r in minutes.risks_and_questions for e in r.evidence), \
        [r.description for r in minutes.risks_and_questions]

    # Summaries exist and the engine released the VRAM for the next meeting's ASR. Residency itself is only
    # reported: another client of the same Ollama server may legitimately reload the model at any time.
    assert minutes.summary_ro.strip() and minutes.summary_en and minutes.summary_en.strip()
    assert unload_spy.await_count == 1, "engine must unload the model in its finally-block"
    print(f"model resident after unload: {model_loaded()} (True means another client reloaded it)")

    out_path = Path(settings.DATA_DIR) / "trackA_live_minutes.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(minutes.model_dump_json(indent=2), encoding="utf-8")
    print(f"PASSED: test_track_a_live_extraction ({elapsed:.1f}s; minutes written to {out_path})")
    print(f"score it: python tools/eval/run_extraction_eval.py --gold {GOLD_PATH} --minutes {out_path}")


if __name__ == "__main__":
    if not ollama_reachable():
        print(f"SKIPPED: Ollama not reachable at {settings.LLM_API_BASE_URL}")
        sys.exit(0)
    test_track_a_live_extraction()
    print("Live LLM extraction test passed successfully!")
