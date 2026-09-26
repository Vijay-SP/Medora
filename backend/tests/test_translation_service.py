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


# ---------------------------------------------------------------------------
# Speaker-label preservation (contract N5): translation runs on the STORED label text ("S3 a propus ...");
# the prompt forbids touching the labels, and any field whose translation drops / adds / renumbers a label
# falls back to the Romanian text with a WARNING. Names are never translated because they are never stored.
# ---------------------------------------------------------------------------
import logging
import re

from app.services.translation.translation_service import TRANSLATION_SYSTEM_PROMPT

_LABEL_TOKEN = re.compile(r"\bS(\d{1,2})\b")


def _labels(text: str | None) -> set[str]:
    return {"S" + m.group(1) for m in _LABEL_TOKEN.finditer(text or "")}


class _FakeTranslationClient:
    """Stands in for OllamaClient.complete_json: a scripted answer, keyed by item id, plus the captured prompts."""

    def __init__(self, answer: dict):
        self.answer = answer
        self.calls: list[dict] = []

    async def complete_json(self, system: str, user: str, schema: dict, max_tokens: int, seed: int, keep_alive: str):
        self.calls.append({"system": system, "user": user, "schema": schema})
        return dict(self.answer), {"prompt_tokens": 10, "completion_tokens": 10, "seconds": 0.01}

    async def unload(self) -> None:
        return None


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _make_labelled_minutes(meeting_id: str) -> MinutesOfMeeting:
    return MinutesOfMeeting(
        meeting_id=meeting_id,
        title="Consiliu Medical - etichete",
        meeting_type="medical",
        speaker_label_style="labels",
        summary_ro="S1 a deschis ședința. S2 a propus, S1 a aprobat.",
        agenda_topics=["Protocol anticoagulare (S1)", "Stoc meropenem"],
        decisions=[
            DecisionItem(id="dec-1", topic="Terapie anticoagulantă", decision="S2 a propus inițierea tratamentului cu Apixaban 5mg; S1 a aprobat.",
                         evidence=[EvidenceQuote(segment_id="seg-1", quote="Apixaban 5mg", start=10.0, end=14.0, speaker="Speaker 2")]),
            DecisionItem(id="dec-2", topic="Procedură TAVI", decision="S1 a aprobat intervenția TAVI pentru 15 octombrie.",
                         evidence=[EvidenceQuote(segment_id="seg-2", quote="aprobăm TAVI pe 15", start=25.0, end=28.0, speaker="Speaker 1")]),
        ],
        action_items=[
            ActionItem(id="act-1", task="S3 va efectua ecocardiografia transesofagiană preoperatorie.", owner="Speaker 3", owner_source="speaker",
                       deadline_phrase="până vineri",
                       evidence=[EvidenceQuote(segment_id="seg-3", quote="fac ecocardiografia până vineri", start=30.0, end=34.0, speaker="Speaker 3")]),
        ],
        risks_and_questions=[
            RiskOrQuestionItem(id="risk-1", item_type="risk", description="S2 a semnalat riscul hemoragic moderat (HAS-BLED).", severity="medium",
                               evidence=[EvidenceQuote(segment_id="seg-4", quote="scor HAS-BLED moderat", start=40.0, end=45.0, speaker="Speaker 2")]),
        ],
        generated_at=datetime.now(timezone.utc).isoformat(),
        model_version="test-fixture",
    )


def _with_fake_client(fake: _FakeTranslationClient):
    """Swaps the service's lazily-built Ollama client for the fake; restores the previous state afterwards."""
    class _Ctx:
        def __enter__(self):
            self.previous = translation_service._client
            translation_service._client = fake
            return fake

        def __exit__(self, *exc):
            translation_service._client = self.previous
            return False
    return _Ctx()


def test_translation_prompt_pins_speaker_labels():
    assert "Etichetele vorbitorilor (S1, S2" in TRANSLATION_SYSTEM_PROMPT
    assert "rămân EXACT neschimbate" in TRANSLATION_SYSTEM_PROMPT
    m = _make_labelled_minutes("meet-trans-labels-prompt")
    fake = _FakeTranslationClient({"agenda_topics": [], "decisions": [], "action_items": [], "risks_and_questions": []})
    with _with_fake_client(fake):
        asyncio.run(translation_service.translate_mom(m, "en"))
    assert len(fake.calls) == 1
    assert "rămân EXACT neschimbate" in fake.calls[0]["system"]
    # the model is handed the stored label text, never a rendered name
    assert "S2 a propus inițierea" in fake.calls[0]["user"] and "S3 va efectua" in fake.calls[0]["user"]
    print("[PASS] test_translation_prompt_pins_speaker_labels")


def test_translation_keeps_labels_when_preserved():
    m = _make_labelled_minutes("meet-trans-labels-ok")
    answer = {
        "agenda_topics": ["Anticoagulation protocol (S1)", "Meropenem stock"],
        "decisions": [
            {"id": "dec-1", "topic": "Anticoagulant therapy", "decision": "S2 proposed starting Apixaban 5mg; S1 approved."},
            {"id": "dec-2", "topic": "TAVI procedure", "decision": "S1 approved the TAVI intervention for 15 October."},
        ],
        "action_items": [{"id": "act-1", "task": "S3 will perform the pre-operative transoesophageal echocardiography.", "deadline_phrase": "by Friday"}],
        "risks_and_questions": [{"id": "risk-1", "description": "S2 flagged a moderate bleeding risk (HAS-BLED)."}],
    }
    capture = _Capture()
    from app.core.logging import logger as app_logger
    app_logger.addHandler(capture)
    try:
        with _with_fake_client(_FakeTranslationClient(answer)):
            out = asyncio.run(translation_service.translate_mom(m, "en"))
    finally:
        app_logger.removeHandler(capture)
    assert out.decisions[0].decision_en == "S2 proposed starting Apixaban 5mg; S1 approved."
    assert out.decisions[1].decision_en == "S1 approved the TAVI intervention for 15 October."
    assert out.action_items[0].task_en == "S3 will perform the pre-operative transoesophageal echocardiography."
    assert out.action_items[0].deadline_phrase_en == "by Friday"
    assert out.risks_and_questions[0].description_en == "S2 flagged a moderate bleeding risk (HAS-BLED)."
    assert out.agenda_topics_en == ["Anticoagulation protocol (S1)", "Meropenem stock"]
    for src, dst in ((out.decisions[0].decision, out.decisions[0].decision_en), (out.action_items[0].task, out.action_items[0].task_en),
                     (out.risks_and_questions[0].description, out.risks_and_questions[0].description_en)):
        assert _labels(src) == _labels(dst), (src, dst)
    assert not [r for r in capture.records if "speaker labels" in r.getMessage()], [r.getMessage() for r in capture.records]
    assert translation_service.is_translated(out, "en") is True
    print("[PASS] test_translation_keeps_labels_when_preserved")


def test_translation_falls_back_to_romanian_when_a_label_is_lost():
    m = _make_labelled_minutes("meet-trans-labels-lost")
    answer = {
        "agenda_topics": ["Протокол антикоагуляции (S1)", "Запас меропенема"],
        "decisions": [
            # S2 dropped -> the label set changed -> keep the Romanian text for this field only
            {"id": "dec-1", "topic": "Антикоагулянтная терапия", "decision": "Предложено начать Апиксабан 5 мг; S1 одобрил."},
            # S1 renumbered to S4 -> fallback as well
            {"id": "dec-2", "topic": "Процедура TAVI", "decision": "S4 одобрил вмешательство TAVI на 15 октября."},
        ],
        # label translated into a name-like word -> fallback for the task; the deadline has no labels and is kept
        "action_items": [{"id": "act-1", "task": "Спикер 3 выполнит чреспищеводную эхокардиографию.", "deadline_phrase": "до пятницы"}],
        # preserved -> translated text accepted
        "risks_and_questions": [{"id": "risk-1", "description": "S2 отметил умеренный риск кровотечения (HAS-BLED)."}],
    }
    capture = _Capture()
    from app.core.logging import logger as app_logger
    app_logger.addHandler(capture)
    try:
        with _with_fake_client(_FakeTranslationClient(answer)):
            out = asyncio.run(translation_service.translate_mom(m, "ru"))
    finally:
        app_logger.removeHandler(capture)
    assert out.decisions[0].decision_ru == out.decisions[0].decision, "lost S2 -> Romanian text kept"
    assert out.decisions[0].topic_ru == "Антикоагулянтная терапия", "a label-free topic is still translated"
    assert out.decisions[1].decision_ru == out.decisions[1].decision, "renumbered S1->S4 -> Romanian text kept"
    assert out.action_items[0].task_ru == out.action_items[0].task, "label rewritten as a word -> Romanian text kept"
    assert out.action_items[0].deadline_phrase_ru == "до пятницы"
    assert out.risks_and_questions[0].description_ru == "S2 отметил умеренный риск кровотечения (HAS-BLED)."
    assert out.agenda_topics_ru == ["Протокол антикоагуляции (S1)", "Запас меропенема"]
    # every RU field carries exactly the label set of its Romanian source
    for src, dst in ((out.decisions[0].decision, out.decisions[0].decision_ru), (out.decisions[1].decision, out.decisions[1].decision_ru),
                     (out.action_items[0].task, out.action_items[0].task_ru), (out.risks_and_questions[0].description, out.risks_and_questions[0].description_ru)):
        assert _labels(src) == _labels(dst), (src, dst)
    assert "S4" not in out.model_dump_json()
    warnings = [r.getMessage() for r in capture.records if r.levelno == logging.WARNING and "speaker labels" in r.getMessage()]
    assert len(warnings) == 3, warnings
    assert any("dec-1" in w for w in warnings) and any("dec-2" in w for w in warnings) and any("act-1" in w for w in warnings)
    assert translation_service.is_translated(out, "ru") is True, "the fallback still counts as a cached translation"
    print("[PASS] test_translation_falls_back_to_romanian_when_a_label_is_lost")


def test_translation_never_sees_rendered_names():
    """Stored text is label text: even when a cluster is confirmed, the translator prompt carries the token, not the name."""
    from app.models.transcript import Transcript, TranscriptSegment
    from app.services.extraction.attribution_render import render_minutes

    m = _make_labelled_minutes("meet-trans-labels-names")
    transcript = Transcript(meeting_id=m.meeting_id, segments=[
        TranscriptSegment(id="seg-1", start=10.0, end=14.0, speaker="Speaker 2", raw_text="Apixaban 5mg", speech_seconds=3.5,
                          attribution_state="corrected", speaker_id=None, attribution_basis="reviewer_label",
                          confirmed_display_name="Dr. Ana Popescu", confirmed_by="Dr. Rev (Reviewer)", confirmed_for_revision=1, printable_name=True),
    ])
    rendered = render_minutes(m, transcript)
    assert rendered.decisions[0].decision.startswith("Dr. Ana Popescu a propus")
    fake = _FakeTranslationClient({"agenda_topics": [], "decisions": [], "action_items": [], "risks_and_questions": []})
    with _with_fake_client(fake):
        asyncio.run(translation_service.translate_mom(m, "ru"))
    assert "Popescu" not in fake.calls[0]["user"] and "S2 a propus" in fake.calls[0]["user"]
    assert "Popescu" not in m.model_dump_json(), "the stored minutes stay name-free"
    print("[PASS] test_translation_never_sees_rendered_names")


if __name__ == "__main__":
    test_is_translated_and_caching()
    test_get_localized_mom_reusability()
    test_translate_api_endpoint()
    test_automatic_translation_in_extraction()
    test_translation_prompt_pins_speaker_labels()
    test_translation_keeps_labels_when_preserved()
    test_translation_falls_back_to_romanian_when_a_label_is_lost()
    test_translation_never_sees_rendered_names()
    print("ALL TRANSLATION TESTS PASSED SUCCESSFULLY!")
