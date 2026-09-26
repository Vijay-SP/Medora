"""
Offline tests proving that an outgoing email never carries a person's name outside its attachments.

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_delivery_body_has_no_names.py

Storage and SMTP are isolated before any app import (temp DATA_DIR, dead SMTP port 9, simulated delivery
off) and aiosmtplib.send / httpx are replaced by mocks, so nothing can leave the host.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_delivery_names_"))
_REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ["DATA_DIR"] = str(_ROOT / "data")
os.environ["UPLOADS_DIR"] = str(_ROOT / "uploads")
os.environ["EXPORTS_DIR"] = str(_ROOT / "exports")
os.environ["FIXTURES_DIR"] = str(_ROOT / "fixtures")
os.environ["VOICEPRINTS_DIR"] = str(_ROOT / "voiceprints")
os.environ.setdefault("MODELS_DIR", str(_REPO_ROOT / "data" / "models"))
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"
os.environ["ENABLE_DEFAULT_ROUTING_POLICIES"] = "false"
os.environ["N8N_ENABLED"] = "false"
os.environ["N8N_WEBHOOK_URL"] = "http://127.0.0.1:9/webhook/never"
os.environ["REQUIRE_LOCAL_LLM"] = "false"
os.environ["LLM_API_BASE_URL"] = "http://127.0.0.1:9"
os.environ["WHISPER_DEVICE"] = "cpu"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import asyncio  # noqa: E402
import sys  # noqa: E402
import zipfile  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.models.delivery import DeliveryStatus  # noqa: E402
from app.models.extraction import ActionItem, DecisionItem, EvidenceQuote, MinutesOfMeeting, RiskOrQuestionItem  # noqa: E402
from app.models.meeting import Attendee, Meeting, MeetingType, WorkflowMode  # noqa: E402
from app.models.transcript import Transcript, TranscriptSegment  # noqa: E402
from app.storage.repository import repository  # noqa: E402
from app.services.delivery import n8n_service as n8n_module  # noqa: E402
from app.services.delivery import smtp_service as smtp_module  # noqa: E402
from app.services.delivery.router import delivery_router  # noqa: E402
from app.services.documents.generator import document_generator  # noqa: E402

CONFIRMED = "Dr. Ana Popescu"
CORRECTED = "Dr. Ion Rusu"
ROSTER = "Dr. Elena Ceban"
SUGGESTED = "Dr. Maria Ciobanu"  # only ever proposed to the reviewer, never confirmed
MENTIONED = "Dr. Vasile Munteanu"
ALL_NAMES = [CONFIRMED, CORRECTED, ROSTER, SUGGESTED, MENTIONED]
# distinctive surname tokens: a body that carries "Popescu" without the honorific still leaks
SURNAMES = ["Popescu", "Rusu", "Ceban", "Ciobanu", "Munteanu"]


class _Skip(Exception):
    pass


def _build_meeting() -> Meeting:
    return Meeting(
        title="Ședință Consiliu Medical - Protocoale ATI",
        meeting_type=MeetingType.MEDICAL,
        workflow_mode=WorkflowMode.SUPERVISED,
        scheduled_at=datetime(2026, 9, 26, 9, 0, tzinfo=timezone.utc),
        attendees=[Attendee(name=ROSTER, role="Director Medical", email="reviewer@example.invalid")],
        distribution_list=["outbox@example.invalid"],
    )


def _build_minutes(meeting: Meeting) -> MinutesOfMeeting:
    """Minutes whose every name-bearing field is populated, including a summary that quotes a person."""
    confirmed_quote = EvidenceQuote(segment_id="a1", start=12.0, end=18.5, quote="Aprobăm protocolul de anticoagulare.",
                                    speaker=CONFIRMED, speaker_person_id="p-a", speaker_is_confirmed=True)
    corrected_quote = EvidenceQuote(segment_id="b1", start=40.0, end=46.0, quote="Eu pregătesc raportul până vineri.",
                                    speaker=CORRECTED, speaker_person_id="p-b", speaker_is_confirmed=True)
    anonymous_quote = EvidenceQuote(segment_id="c1", start=60.0, end=61.0, quote="Да.", speaker="Speaker 3")
    return MinutesOfMeeting(
        meeting_id=meeting.id,
        title=meeting.title,
        meeting_type=meeting.meeting_type.value,
        summary_ro=f"{CONFIRMED} a aprobat protocolul, iar {MENTIONED} a fost menționat ca responsabil.",
        summary_en=f"{CONFIRMED} approved the protocol.",
        agenda_topics=["Protocoale ATI", f"Raport {CORRECTED}"],
        decisions=[DecisionItem(topic="Protocoale ATI", decision="Se aprobă protocolul de anticoagulare.",
                                evidence=[confirmed_quote, anonymous_quote])],
        action_items=[
            ActionItem(task="Pregătirea raportului lunar.", owner=CORRECTED, owner_source="confirmed_speaker",
                       deadline_phrase="până vineri", evidence=[corrected_quote]),
            ActionItem(task="Verificarea dozajului.", owner=ROSTER, owner_source="roster", evidence=[confirmed_quote]),
            ActionItem(task="Actualizarea listei de medicamente.", owner=MENTIONED, owner_source="mention", evidence=[confirmed_quote]),
            ActionItem(task="Programarea ședinței următoare.", owner="Speaker 3", owner_source="speaker", evidence=[anonymous_quote]),
        ],
        risks_and_questions=[RiskOrQuestionItem(description=f"Întrebare deschisă pentru {SUGGESTED}.", evidence=[anonymous_quote])],
        revision=2,
        pdf_path=None,
        docx_path=None,
    )


def _assert_no_names(text: str, where: str) -> None:
    lowered = text.casefold()
    for name in ALL_NAMES + SURNAMES:
        assert name.casefold() not in lowered, f"{where} leaks the name {name!r}: {text[:200]!r}"


# ---------------------------------------------------------------- build_body / subject
def test_build_body_contains_counts_and_attachments_only():
    meeting = _build_meeting()
    minutes = _build_minutes(meeting)
    body = smtp_module.build_body(meeting, minutes, Path("Medpark_MoM_Rev2.pdf"), Path("Medpark_MoM_Rev2.docx"))
    assert isinstance(body, str) and body.strip()
    _assert_no_names(body, "build_body")
    assert "Decizii adoptate: 1" in body and "Sarcini de lucru stabilite: 4" in body
    assert "Medpark_MoM_Rev2.pdf" in body and "Medpark_MoM_Rev2.docx" in body
    assert minutes.summary_ro not in body and "anticoagulare" not in body, "no summary / decision prose in the body"
    # the guard helper agrees with the plain substring check
    assert smtp_module.find_person_names(body, smtp_module.collect_protected_names(meeting, minutes)) == []
    # and it is the same helper the n8n channel uses
    assert n8n_module.build_body is smtp_module.build_body


def test_subject_line_has_no_names():
    meeting = _build_meeting()
    minutes = _build_minutes(meeting)
    subject = delivery_router.get_subject_line(meeting, revision=minutes.revision)
    _assert_no_names(subject, "subject")
    assert "(Rev.2)" in subject and meeting.title in subject


def test_collect_protected_names_covers_roster_confirmed_and_named_owners():
    meeting = _build_meeting()
    minutes = _build_minutes(meeting)
    protected = smtp_module.collect_protected_names(meeting, minutes)
    for name in (CONFIRMED, CORRECTED, ROSTER, MENTIONED):
        assert name in protected, f"{name} must be protected"
    assert "Speaker 3" not in protected and "Unassigned" not in protected
    assert smtp_module.find_person_names("Raportul lui Popescu este gata", protected) == [CONFIRMED]
    assert smtp_module.find_person_names("Dr. a spus da", protected) == [], "an honorific alone is not a name"


# ---------------------------------------------------------------- the real SMTP path, transport mocked
def _store_confirmed_transcript(meeting: Meeting) -> None:
    """The document prints a name only from a stored transcript whose cited segments are printable."""
    now = datetime.now(timezone.utc)
    segments = [
        TranscriptSegment(id="a1", start=12.0, end=18.5, raw_text="Aprobăm protocolul de anticoagulare.", speaker="Speaker 1",
                          cluster_id="SPEAKER_01", attribution_state="confirmed", speaker_id="p-a", confirmed_display_name=CONFIRMED,
                          confirmed_by="Dr. Rev (Reviewer)", confirmed_at=now, confirmed_for_revision=2, speech_seconds=6.0, printable_name=True),
        TranscriptSegment(id="b1", start=40.0, end=46.0, raw_text="Eu pregătesc raportul până vineri.", speaker="Speaker 2",
                          cluster_id="SPEAKER_02", attribution_state="corrected", speaker_id="p-b", confirmed_display_name=CORRECTED,
                          confirmed_by="Dr. Rev (Reviewer)", confirmed_at=now, confirmed_for_revision=2, speech_seconds=5.5, printable_name=True),
        TranscriptSegment(id="c1", start=60.0, end=61.0, raw_text="Да.", speaker="Speaker 3", cluster_id="SPEAKER_03", speech_seconds=0.6),
    ]
    assert repository.storage_dir.is_relative_to(_ROOT)
    repository.save_meeting(meeting)
    repository.save_transcript(Transcript(meeting_id=meeting.id, segments=segments))


def test_smtp_deliver_puts_names_only_in_attachments():
    meeting = _build_meeting()
    minutes = _build_minutes(meeting)
    _store_confirmed_transcript(meeting)
    pdf_path = _ROOT / "exports" / meeting.id / "Medpark_MoM_Rev2.pdf"
    docx_path = pdf_path.with_suffix(".docx")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    document_generator.generate_all(meeting, minutes, pdf_path, docx_path)
    assert settings.SMTP_PORT == 9 and settings.ALLOW_SIMULATED_DELIVERY is False

    sent: list = []

    async def fake_send(message, **kwargs):
        sent.append((message, kwargs))
        return {}, "250 OK (mock)"

    with patch("aiosmtplib.send", new=AsyncMock(side_effect=fake_send)):
        record = asyncio.run(smtp_module.smtp_service.deliver(meeting, minutes, pdf_path, docx_path, ["outbox@example.invalid"]))

    assert record.status == DeliveryStatus.DISPATCHED, record.error_message
    assert len(sent) == 1
    message, kwargs = sent[0]
    from email import policy
    from email.parser import BytesParser
    message = BytesParser(policy=policy.default).parsebytes(message)
    assert kwargs["hostname"] == "127.0.0.1" and kwargs["port"] == 9
    _assert_no_names(message["Subject"], "SMTP subject")
    body_part = message.get_body(preferencelist=("plain", "html"))
    assert body_part is not None
    _assert_no_names(body_part.get_content(), "SMTP body")
    for header in ("To", "Cc", "From"):
        _assert_no_names(str(message[header] or ""), f"SMTP header {header}")
    # names DO travel in the attachments: that is the reviewed document
    attachments = {part.get_filename(): part.get_payload(decode=True) for part in message.iter_attachments()}
    assert set(attachments) == {pdf_path.name, docx_path.name}
    with zipfile.ZipFile(docx_path) as zf:
        docx_xml = zf.read("word/document.xml").decode("utf-8")
    assert CONFIRMED in docx_xml and CORRECTED in docx_xml, "the attached document carries the confirmed names"
    _assert_no_names(record.subject, "delivery record subject")


def test_smtp_deliver_refuses_a_subject_that_carries_a_name():
    meeting = _build_meeting()
    meeting.title = f"Ședință condusă de {ROSTER}"
    minutes = _build_minutes(meeting)
    with patch("aiosmtplib.send", new=AsyncMock()) as send:
        record = asyncio.run(smtp_module.smtp_service.deliver(meeting, minutes, None, None, ["outbox@example.invalid"]))
    assert record.status == DeliveryStatus.FAILED
    assert record.error_message and "nume" in record.error_message.casefold()
    send.assert_not_awaited()


# ---------------------------------------------------------------- the n8n path, webhook mocked
def test_n8n_payload_carries_no_names():
    meeting = _build_meeting()
    minutes = _build_minutes(meeting)
    captured: list = []

    async def fake_post(self, url, json=None, **kwargs):
        captured.append((url, json))
        return SimpleNamespace(status_code=200)

    previous = settings.N8N_ENABLED
    try:
        settings.N8N_ENABLED = True
        with patch("httpx.AsyncClient.post", new=fake_post):
            record = asyncio.run(n8n_module.n8n_service.trigger_workflow(meeting, minutes, ["outbox@example.invalid"]))
    finally:
        settings.N8N_ENABLED = previous
    assert record.status == DeliveryStatus.DISPATCHED, record.error_message
    assert len(captured) == 1
    url, payload = captured[0]
    assert url.startswith("http://127.0.0.1:9/")
    assert "summary_ro" not in payload and "summary_en" not in payload

    def walk(value, path="payload"):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")
        elif isinstance(value, str):
            _assert_no_names(value, path)

    walk(payload)


if __name__ == "__main__":
    import traceback

    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except _Skip as s:
            print(f"SKIP {name}: {s}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            print("    " + "\n    ".join(traceback.format_exc().strip().splitlines()[-4:]))
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
