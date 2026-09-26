"""
Tests for multilingual extraction, code-switching, and evidence grounding.

Runs OFFLINE on the heuristic fallback path: REQUIRE_LOCAL_LLM=false and LLM_FALLBACK_MODE=heuristic
are forced and the LLM endpoint is pointed at a dead port BEFORE any app import (the Ollama client
binds its base URL at import), so the test is deterministic whether or not an Ollama server is
running. The heuristic output is a degraded draft: is_degraded must be True.
"""

import os
import tempfile
from pathlib import Path

_ISOLATED_ROOT = Path(os.environ.get("DATA_DIR") or os.path.join(tempfile.mkdtemp(prefix="medpark_test_grounding_"), "data"))
os.environ.setdefault("DATA_DIR", str(_ISOLATED_ROOT))
os.environ.setdefault("UPLOADS_DIR", str(_ISOLATED_ROOT / "uploads"))
os.environ.setdefault("EXPORTS_DIR", str(_ISOLATED_ROOT / "exports"))
os.environ.setdefault("FIXTURES_DIR", str(_ISOLATED_ROOT / "fixtures"))
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"
os.environ["REQUIRE_LOCAL_LLM"] = "false"
os.environ["LLM_FALLBACK_MODE"] = "heuristic"
os.environ["LLM_API_BASE_URL"] = "http://127.0.0.1:9"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import asyncio  # noqa: E402
from datetime import datetime  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.models.meeting import Meeting, MeetingType, Attendee  # noqa: E402
from app.models.transcript import Transcript, TranscriptSegment  # noqa: E402
from app.services.extraction.llm_engine import extraction_engine  # noqa: E402
from app.services.extraction.llm_client import llm_client  # noqa: E402
from app.services.extraction.heuristic_extractor import DEGRADED_MODEL_VERSION  # noqa: E402


def test_code_switched_extraction_and_grounding():
    # Isolation preconditions: degraded policy on, no reachable LLM, no reachable mail server
    assert settings.REQUIRE_LOCAL_LLM is False and settings.LLM_FALLBACK_MODE == "heuristic"
    assert llm_client.base_url == "http://127.0.0.1:9"
    assert settings.SMTP_PORT == 9

    # Construct a realistic Medpark code-switched meeting transcript
    # Segment 1 (RO): Opening and proposal
    seg1 = TranscriptSegment(
        id="s1",
        start=0.0,
        end=5.2,
        speaker="Dr. Elena Ceban",
        raw_text="Bună dimineața tuturor. Deschidem ședința de comitet medical pentru revizuirea protocoalelor ATI."
    )
    # Segment 2 (RU): Discussion and decision agreement
    seg2 = TranscriptSegment(
        id="s2",
        start=5.5,
        end=11.0,
        speaker="Dr. Mihail Popov",
        raw_text="Да, по протоколу реанимации мы согласовали и утвердили новые дозировки антибиотиков."
    )
    # Segment 3 (RO/EN): Action item with deadline
    seg3 = TranscriptSegment(
        id="s3",
        start=11.2,
        end=17.5,
        speaker="Dr. Elena Ceban",
        raw_text="Perfect. Dr. Elena Ceban va pregăti documentația finală și raportul de gardă până vineri."
    )
    # Segment 4 (RO/RU): Operational risk
    seg4 = TranscriptSegment(
        id="s4",
        start=18.0,
        end=23.0,
        speaker="Dr. Mihail Popov",
        raw_text="Avem un risc cu stocul de hemostatice, нужно срочно проверить склад."
    )

    transcript = Transcript(
        meeting_id="med-test-01",
        segments=[seg1, seg2, seg3, seg4]
    )
    transcript.compute_stats()

    meeting = Meeting(
        id="med-test-01",
        title="Comitet Medical - Protocoale ATI & Hemostază",
        meeting_type=MeetingType.MEDICAL,
        scheduled_at=datetime(2026, 9, 25, 10, 0),
        attendees=[
            Attendee(name="Dr. Elena Ceban", role="Chirurg Șef", email="elena.ceban@medpark.md"),
            Attendee(name="Dr. Mihail Popov", role="Șef ATI", email="mihail.popov@medpark.md")
        ]
    )

    # Preflight reports the degraded path instead of raising, because policy explicitly allows it
    assert asyncio.run(extraction_engine.preflight()) == "heuristic-fallback"

    # Run extraction
    minutes = asyncio.run(extraction_engine.extract_minutes(meeting, transcript))

    # The heuristic parser produced this: it is a degraded, non-dispatchable draft and says so
    assert minutes.is_degraded is True
    assert minutes.model_version == DEGRADED_MODEL_VERSION
    assert any("NOTĂ AUDIT" in r.description for r in minutes.risks_and_questions)
    assert minutes.extraction_stats.get("engine") == "heuristic"

    # Verify structured outputs
    assert len(minutes.decisions) >= 1
    assert len(minutes.action_items) >= 1

    # Verify action item owner and deadline
    action = minutes.action_items[0]
    assert "Elena Ceban" in action.owner or action.owner != "Unassigned"
    assert action.deadline_phrase is not None
    assert action.deadline_date is not None  # Resolved to ISO date!

    # Verify Grounding: Every decision and action must cite valid audio timestamps
    for dec in minutes.decisions:
        assert len(dec.evidence) > 0
        assert dec.evidence[0].start >= 0.0

    for act in minutes.action_items:
        assert len(act.evidence) > 0
        assert act.evidence[0].quote in transcript.to_full_text()


if __name__ == "__main__":
    test_code_switched_extraction_and_grounding()
    print("Multilingual extraction and evidence grounding tests passed successfully!")
