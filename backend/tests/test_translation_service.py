"""
Test for Minutes of Meeting dynamic translation service, caching, fallback, and API endpoint.

    PYTHONPATH=backend F:\\DEEPTECH\\.venv\\Scripts\\python.exe backend\\tests\\test_translation_service.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_translation_"))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ISOLATION_ENV = {
    "DATA_DIR": str(_ROOT / "data"),
    "UPLOADS_DIR": str(_ROOT / "uploads"),
    "EXPORTS_DIR": str(_ROOT / "exports"),
    "FIXTURES_DIR": str(_ROOT / "fixtures"),
    "VOICEPRINTS_DIR": str(_ROOT / "voiceprints"),
    "SMTP_HOST": "127.0.0.1",
    "SMTP_PORT": "9",
    "ALLOW_SIMULATED_DELIVERY": "false",
    "REQUIRE_LOCAL_LLM": "false",
    "LLM_FALLBACK_MODE": "heuristic",
    "LLM_API_BASE_URL": "http://127.0.0.1:9",
    "WHISPER_DEVICE": "cpu",
}
os.environ.update(_ISOLATION_ENV)
os.environ.setdefault("MODELS_DIR", str(_REPO_ROOT / "data" / "models"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.models.meeting import Meeting, MeetingType, WorkflowMode
from app.models.extraction import (
    MinutesOfMeeting,
    DecisionItem,
    ActionItem,
    RiskOrQuestionItem,
    EvidenceQuote,
)
from app.services.translation import translation_service
from app.storage.repository import repository


def _make_dummy_minutes(meeting_id: str) -> MinutesOfMeeting:
    return MinutesOfMeeting(
        meeting_id=meeting_id,
        title="Consiliu Medical Cardiologie",
        meeting_type="medical",
        summary_ro="Discuție privind cazul pacientului cu stenoză aortică severă.",
        agenda_topics=[
            "Stenoză aortică severă",
            "Tratament anticoagulant",
            "Programare TAVI",
        ],
        decisions=[
            DecisionItem(
                id="dec-1",
                topic="Terapie anticoagulantă",
                decision="Se inițiază tratamentul cu Apixaban 5mg de două ori pe zi.",
                evidence=[EvidenceQuote(segment_id="seg-1", quote="Apixaban 5mg", start=10.0, end=14.0)],
            ),
            DecisionItem(
                id="dec-2",
                topic="Procedură TAVI",
                decision="Se aprobă intervenția TAVI pentru data de 15 octombrie.",
                evidence=[EvidenceQuote(segment_id="seg-2", quote="aprobăm TAVI pe 15", start=25.0, end=28.0)],
            ),
        ],
        action_items=[
            ActionItem(
                id="act-1",
                task="Efectuarea ecocardiografiei transesofagiene preoperatorii",
                owner="Dr. Rusu",
                deadline_phrase="până vineri",
                evidence=[EvidenceQuote(segment_id="seg-3", quote="Dr Rusu face ecocardiografia până vineri", start=30.0, end=34.0)],
            )
        ],
        risks_and_questions=[
            RiskOrQuestionItem(
                id="risk-1",
                item_type="risk",
                description="Risc hemoragic moderat conform scorului HAS-BLED.",
                severity="medium",
                evidence=[EvidenceQuote(segment_id="seg-4", quote="scor HAS-BLED moderat", start=40.0, end=45.0)],
            )
        ],
        generated_at=datetime.now(timezone.utc).isoformat(),
        model_version="qwen2.5:7b-instruct-q4_K_M",
    )


def test_is_translated_and_caching():
    m = _make_dummy_minutes("meet-trans-01")

    # Romanian is always considered translated
    assert translation_service.is_translated(m, "ro") is True

    # Russian & English initially untranslated
    assert translation_service.is_translated(m, "ru") is False
    assert translation_service.is_translated(m, "en") is False

    # Run translation for RU (will use deterministic fallback since test server has no mock LLM)
    updated_ru = asyncio.run(translation_service.translate_mom(m, "ru"))

    # Assert fields populated
    assert translation_service.is_translated(updated_ru, "ru") is True
    assert updated_ru.agenda_topics_ru is not None
    assert len(updated_ru.agenda_topics_ru) == 3
    assert updated_ru.decisions[0].decision_ru is not None
    assert updated_ru.action_items[0].task_ru is not None
    assert updated_ru.risks_and_questions[0].description_ru is not None

    # Verify cached call returns immediately
    again = asyncio.run(translation_service.translate_mom(updated_ru, "ru"))
    assert again.agenda_topics_ru == updated_ru.agenda_topics_ru

    # Now translate EN
    updated_en = asyncio.run(translation_service.translate_mom(updated_ru, "en"))
    assert translation_service.is_translated(updated_en, "en") is True
    assert updated_en.agenda_topics_en is not None
    assert updated_en.decisions[0].decision_en is not None
    assert updated_en.action_items[0].task_en is not None
    print("[PASS] test_is_translated_and_caching")


def test_get_localized_mom_reusability():
    m = _make_dummy_minutes("meet-trans-02")
    asyncio.run(translation_service.translate_mom(m, "ru"))
    asyncio.run(translation_service.translate_mom(m, "en"))

    # Localized for RO
    loc_ro = translation_service.get_localized_mom(m, "ro")
    assert loc_ro["summary"] == m.summary_ro
    assert loc_ro["agenda_topics"] == m.agenda_topics
    assert loc_ro["decisions"][0]["decision"] == m.decisions[0].decision

    # Localized for RU
    loc_ru = translation_service.get_localized_mom(m, "ru")
    assert loc_ru["agenda_topics"] == m.agenda_topics_ru
    assert loc_ru["decisions"][0]["decision"] == m.decisions[0].decision_ru
    assert loc_ru["action_items"][0]["task"] == m.action_items[0].task_ru

    # Localized for EN
    loc_en = translation_service.get_localized_mom(m, "en")
    assert loc_en["agenda_topics"] == m.agenda_topics_en
    assert loc_en["decisions"][0]["decision"] == m.decisions[0].decision_en
    assert loc_en["action_items"][0]["task"] == m.action_items[0].task_en
    print("[PASS] test_get_localized_mom_reusability")


def test_translate_api_endpoint():
    client = TestClient(app)

    # 1. Create meeting
    meeting = Meeting(
        title="Test Meeting API Translation",
        meeting_type=MeetingType.MEDICAL,
        workflow_mode=WorkflowMode.SUPERVISED,
        scheduled_at=datetime.now(timezone.utc).isoformat(),
        distribution_list=["doc@medpark.md"],
    )
    meeting = repository.save_meeting(meeting)

    # 2. Save minutes
    minutes = _make_dummy_minutes(meeting.id)
    repository.save_minutes(minutes)

    # 3. Call translation endpoint for Russian
    resp = client.post(f"/api/v1/meetings/{meeting.id}/translate?target_lang=ru")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["agenda_topics_ru"] is not None
    assert len(data["agenda_topics_ru"]) == 3
    assert data["decisions"][0]["decision_ru"] is not None

    # 4. Subsequent call uses cache (200 OK)
    resp2 = client.post(f"/api/v1/meetings/{meeting.id}/translate?target_lang=ru")
    assert resp2.status_code == 200
    assert resp2.json()["agenda_topics_ru"] == data["agenda_topics_ru"]

    # 5. Invalid language check (FastAPI Literal validation returns 422)
    resp_invalid = client.post(f"/api/v1/meetings/{meeting.id}/translate?target_lang=fr")
    assert resp_invalid.status_code == 422
    print("[PASS] test_translate_api_endpoint")


def test_automatic_translation_in_extraction():
    from app.models.transcript import Transcript, TranscriptSegment
    from app.services.extraction.llm_engine import extraction_engine

    meeting = Meeting(
        title="Test Automatic Translation In Extraction",
        meeting_type=MeetingType.MEDICAL,
        workflow_mode=WorkflowMode.SUPERVISED,
        scheduled_at=datetime.now(timezone.utc).isoformat(),
        distribution_list=["doc@medpark.md"],
    )
    meeting = repository.save_meeting(meeting)

    segments = [
        TranscriptSegment(
            id="seg-1",
            start=0.0,
            end=5.0,
            speaker="Speaker 1",
            raw_text="Aprobăm inițierea terapiei cu anticoagulante orale.",
            display_text="Aprobăm inițierea terapiei cu anticoagulante orale.",
            language="ro",
            confidence=0.98,
            is_flagged=False,
        ),
        TranscriptSegment(
            id="seg-2",
            start=6.0,
            end=12.0,
            speaker="Speaker 1",
            raw_text="Dr Ceban va monitoriza analizele de coagulare până marți.",
            display_text="Dr Ceban va monitoriza analizele de coagulare până marți.",
            language="ro",
            confidence=0.97,
            is_flagged=False,
        )
    ]
    transcript = Transcript(meeting_id=meeting.id, segments=segments)
    transcript.compute_stats()
    repository.save_transcript(transcript)

    # In test environment (offline, REQUIRE_LOCAL_LLM=False), extraction takes heuristic fallback
    # which now automatically triggers translate_mom for RU and EN!
    minutes = asyncio.run(extraction_engine.extract_minutes(meeting, transcript))

    assert minutes is not None
    # Verify RU & EN fields are populated immediately upon generation!
    assert translation_service.is_translated(minutes, "ro") is True
    assert translation_service.is_translated(minutes, "ru") is True
    assert translation_service.is_translated(minutes, "en") is True
    assert minutes.agenda_topics_ru is not None
    assert minutes.agenda_topics_en is not None
    print("[PASS] test_automatic_translation_in_extraction")


if __name__ == "__main__":
    test_is_translated_and_caching()
    test_get_localized_mom_reusability()
    test_translate_api_endpoint()
    test_automatic_translation_in_extraction()
    print("ALL TRANSLATION TESTS PASSED SUCCESSFULLY!")
