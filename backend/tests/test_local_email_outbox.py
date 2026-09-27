"""Offline delivery contracts. Run as a script; no external services are contacted."""
import asyncio
import os
import sys
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(tempfile.mkdtemp(prefix="medpark_outbox_"))
for key, directory in {
    "DATA_DIR": "data", "UPLOADS_DIR": "uploads", "EXPORTS_DIR": "exports",
    "FIXTURES_DIR": "fixtures", "VOICEPRINTS_DIR": "voiceprints", "OUTBOX_DIR": "outbox",
}.items():
    os.environ[key] = str(ROOT / directory)
os.environ.update({
    "SMTP_HOST": "127.0.0.1", "SMTP_PORT": "9", "DELIVERY_CHANNEL": "smtp",
    "ALLOW_SIMULATED_DELIVERY": "false", "ENABLE_LOCAL_OUTBOX_FALLBACK": "false",
    "ENABLE_DEFAULT_ROUTING_POLICIES": "false", "N8N_ENABLED": "false",
    "LLM_API_BASE_URL": "http://127.0.0.1:9", "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "WHISPER_DEVICE": "cpu",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.models.meeting import Attendee, Meeting, ProcessingStatus, ReviewStatus, WorkflowMode
from app.models.person import Person
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryRecord
from app.storage.repository import repository
from app.services.delivery import smtp_service as module


class OutboxTests(unittest.TestCase):
    def setUp(self):
        channel = patch.object(settings, "DELIVERY_CHANNEL", "local_outbox")
        channel.start()
        self.addCleanup(channel.stop)

    def fixture(self, languages=("ro",)):
        meeting = Meeting(title="Weekly review", processing_status=ProcessingStatus.COMPLETED,
                          attendees=[Attendee(name=f"Person Number{i}", email=f"user{i}@example.invalid",
                                              primary_language=lang) for i, lang in enumerate(languages)])
        folder = ROOT / "exports" / meeting.id
        folder.mkdir(parents=True)
        pdf, docx = folder / "minutes.pdf", folder / "minutes.docx"
        pdf.write_bytes(b"%PDF-reviewed-revision-1")
        docx.write_bytes(b"DOCX-reviewed-revision-1")
        minutes = MinutesOfMeeting(meeting_id=meeting.id, title=meeting.title, summary_ro="Reviewed summary",
                                   pdf_path=str(pdf), docx_path=str(docx))
        repository.save_meeting(meeting)
        repository.save_minutes(minutes)
        return meeting, minutes, pdf, docx

    def deliver(self, fixture):
        return asyncio.run(module.smtp_service.deliver(*fixture))

    def test_language_selection_and_legacy_profile_fallback(self):
        self.assertTrue(hasattr(module, "get_email_languages"), "Language resolution is missing")
        for langs, expected in [(("ro",), ["ro"]), (("ru",), ["ro", "ru"]),
                                (("en",), ["ro", "en"]), (("en", "ru", "ru"), ["ro", "ru", "en"])]:
            meeting, minutes, pdf, docx = self.fixture(langs)
            self.assertEqual(module.get_email_languages(meeting), expected)
            body = module.build_body(meeting, minutes, pdf, docx)
            self.assertEqual("Русский (RU)" in body, "ru" in expected)
            self.assertEqual("English (EN)" in body, "en" in expected)
            module.assert_no_person_names(body, meeting, minutes)
        person = repository.save_person(Person(full_name="Legacy Person", primary_language="ru"))
        meeting, *_ = self.fixture()
        meeting.attendees = [Attendee(name="Legacy Person", email="legacy@example.invalid", person_id=person.id)]
        self.assertEqual(module.get_email_languages(meeting), ["ro", "ru"])
        meeting.attendees[0].primary_language = "en"
        self.assertEqual(module.get_email_languages(meeting), ["ro", "en"])
        meeting.attendees[0].primary_language = None
        meeting.attendees[0].person_id = "deleted-person"
        self.assertEqual(module.get_email_languages(meeting), ["ro"])

    def test_local_save_has_exact_mime_and_never_calls_smtp(self):
        fixture = self.fixture(("ru", "en"))
        with patch("aiosmtplib.send", new=AsyncMock(side_effect=AssertionError("Network forbidden"))):
            record = self.deliver(fixture)
        self.assertEqual(record.status, "saved_locally", record.error_message)
        self.assertIsNone(record.sent_at)
        self.assertEqual(record.languages_included, ["ro", "ru", "en"])
        raw = (settings.OUTBOX_DIR / record.meeting_id / f"{record.id}.eml").read_bytes()
        message = BytesParser(policy=policy.default).parsebytes(raw)
        self.assertTrue(message["Message-ID"])
        self.assertTrue(message["Date"])
        self.assertIn("Русский (RU)", message.get_body().get_content())
        self.assertEqual({p.get_filename(): p.get_payload(decode=True) for p in message.iter_attachments()},
                         {"minutes.pdf": b"%PDF-reviewed-revision-1", "minutes.docx": b"DOCX-reviewed-revision-1"})

    def test_missing_attachment_and_name_guard_do_not_spool(self):
        fixture = self.fixture()
        fixture[2].unlink()
        record = self.deliver(fixture)
        self.assertEqual(record.status, "failed")
        self.assertFalse(getattr(record, "eml_available", False))
        fixture = self.fixture()
        fixture[0].title = "Review Person Number0"
        record = self.deliver(fixture)
        self.assertEqual(record.status, "failed")
        self.assertFalse(getattr(record, "eml_available", False))

    def test_smtp_failure_classification_and_opt_in_fallback(self):
        self.assertTrue(hasattr(settings, "ENABLE_LOCAL_OUTBOX_FALLBACK"))
        from aiosmtplib.errors import SMTPConnectError, SMTPAuthenticationError
        with patch.object(settings, "DELIVERY_CHANNEL", "smtp"):
            with patch("aiosmtplib.send", new=AsyncMock(return_value=({}, "OK"))):
                record = self.deliver(self.fixture())
            self.assertEqual(record.status, "dispatched")
            self.assertIsNotNone(record.sent_at)
            for fallback, error, status, retry in [
                (False, SMTPConnectError("refused"), "failed", True),
                (True, SMTPConnectError("refused"), "saved_locally", True),
                (True, SMTPAuthenticationError(535, "denied"), "failed", True),
                (True, TimeoutError("unknown outcome"), "failed", False),
            ]:
                with patch.object(settings, "ENABLE_LOCAL_OUTBOX_FALLBACK", fallback), \
                     patch("aiosmtplib.send", new=AsyncMock(side_effect=error)):
                    record = self.deliver(self.fixture())
                self.assertEqual(record.status, status)
                self.assertEqual(record.retry_allowed, retry)
                self.assertIsNone(record.sent_at)
            with patch("aiosmtplib.send", new=AsyncMock(return_value=({"one@example.invalid": "refused"}, "OK"))):
                record = self.deliver(self.fixture())
            self.assertEqual(record.status, "failed")
            self.assertFalse(record.retry_allowed)

    def test_approval_download_explicit_send_and_duplicate_protection(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        meeting, minutes, pdf, docx = self.fixture(("ru",))
        approval = {"reviewer_name": "Reviewer", "expected_revision": 1}
        url = f"/api/v1/meetings/{meeting.id}/review/approve"
        with patch("aiosmtplib.send", new=AsyncMock(side_effect=AssertionError("Network forbidden"))):
            response = client.post(url, json=approval)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result["status"], "approved")
            record = result["delivery_record"]
            self.assertEqual(record["status"], "saved_locally")
            duplicate = client.post(url, json=approval).json()
            self.assertEqual(duplicate["delivery_record"]["id"], record["id"])
        eml = client.get(f'/api/v1/deliveries/{record["id"]}/eml')
        self.assertEqual(eml.status_code, 200)
        self.assertIn("message/rfc822", eml.headers["content-type"])
        self.assertNotIn("eml_path", record)
        pdf.write_bytes(b"changed-later")
        captured = []
        async def send(message, **kwargs):
            captured.append(message)
            return {}, "OK"
        send_url = f'/api/v1/deliveries/{record["id"]}/send'
        with patch("aiosmtplib.send", new=AsyncMock(side_effect=send)):
            sent = client.post(send_url)
            self.assertEqual(sent.status_code, 200, sent.text)
            self.assertEqual(sent.json()["status"], "dispatched")
            duplicate = client.post(send_url)
            self.assertEqual(duplicate.json()["id"], sent.json()["id"])
        self.assertEqual(captured, [eml.content])
        self.assertEqual(repository.get_meeting(meeting.id).review_status, "delivered")
        repository.delete_meeting(meeting.id)
        self.assertFalse((settings.OUTBOX_DIR / meeting.id).exists())
        self.assertEqual(client.get(f'/api/v1/deliveries/{record["id"]}/eml').status_code, 404)

    def test_legacy_delivery_does_not_claim_preview(self):
        record = DeliveryRecord(meeting_id="old", status="dispatched")
        self.assertFalse(getattr(record, "eml_available", False))

    def test_stale_degraded_and_unapproved_snapshots_cannot_send(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        for change in ("unapproved", "stale", "degraded"):
            fixture = self.fixture()
            meeting, minutes, *_ = fixture
            record = self.deliver(fixture)
            repository.save_delivery(record)
            if change != "unapproved":
                from datetime import datetime, timezone
                meeting.review_status = ReviewStatus.APPROVED
                meeting.approved_by = "Reviewer"
                meeting.approved_at = datetime.now(timezone.utc)
                repository.save_meeting(meeting)
            if change == "stale":
                minutes.revision = 2
            if change == "degraded":
                minutes.is_degraded = True
            repository.save_minutes(minutes)
            with patch("aiosmtplib.send", new=AsyncMock(side_effect=AssertionError("Network forbidden"))):
                response = client.post(f"/api/v1/deliveries/{record.id}/send")
            self.assertEqual(response.status_code, 409, response.text)

    def test_artifact_tampering_missing_file_and_legacy_download(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        record = self.deliver(self.fixture())
        repository.save_delivery(record)
        path = settings.OUTBOX_DIR / record.meeting_id / f"{record.id}.eml"
        path.write_bytes(b"tampered")
        url = f"/api/v1/deliveries/{record.id}/eml"
        self.assertEqual(client.get(url).status_code, 409)
        path.unlink()
        self.assertEqual(client.get(url).status_code, 404)
        legacy = repository.save_delivery(DeliveryRecord(meeting_id="legacy", status="dispatched"))
        self.assertEqual(client.get(f"/api/v1/deliveries/{legacy.id}/eml").status_code, 404)

    def test_distribution_override_and_cc_are_preserved(self):
        from app.models.delivery import DEFAULT_ROUTING_POLICIES
        fixture = self.fixture(("ru",))
        with patch.dict(os.environ, {"ENABLE_DEFAULT_ROUTING_POLICIES": "true"}):
            record = self.deliver(fixture)
            self.assertEqual(record.cc_recipients, DEFAULT_ROUTING_POLICIES["medical"].cc_recipients)
            fixture[0].distribution_list = ["ARCHIVE@example.invalid", "archive@example.invalid"]
            record = self.deliver(fixture)
            self.assertEqual(record.to_recipients, ["archive@example.invalid"])
            self.assertEqual(record.cc_recipients, [])
            self.assertEqual(record.languages_included, ["ro", "ru"])

    def test_snapshot_attachments_survive_export_overwrite(self):
        from fastapi.testclient import TestClient
        from app.main import app
        fixture = self.fixture()
        record = self.deliver(fixture)
        repository.save_delivery(record)
        fixture[2].write_bytes(b"later revision")
        response = TestClient(app).get(f"/api/v1/deliveries/{record.id}/attachment/pdf")
        self.assertEqual(response.content, b"%PDF-reviewed-revision-1")

    def test_auto_pilot_never_sends_before_human_review(self):
        from types import SimpleNamespace
        from app.services import pipeline_orchestrator as pipeline
        from app.models.transcript import TranscriptSegment
        meeting, minutes, *_ = self.fixture()
        meeting.workflow_mode = WorkflowMode.AUTO_PILOT
        meeting.original_audio_path = str(ROOT / "synthetic.wav")
        repository.save_meeting(meeting)
        segments = [TranscriptSegment(id="seg-1", start=0, end=4, raw_text="Discutăm protocolul.", speaker="Speaker 1", language="ro")]
        engine = SimpleNamespace(device="cpu", transcribe=lambda *args, **kwargs: segments, release_model=lambda: None)
        with patch.object(pipeline.extraction_engine, "preflight", new=AsyncMock(return_value="test")), \
             patch.object(pipeline.extraction_engine, "extract_minutes", new=AsyncMock(return_value=minutes)), \
             patch.object(pipeline.audio_preprocessor, "normalize", return_value=("unused", 4)), \
             patch.object(pipeline, "get_asr_engine", return_value=engine), \
             patch.object(pipeline.diarization_engine, "assign_speakers", return_value=segments), \
             patch("aiosmtplib.send", new=AsyncMock(side_effect=AssertionError("No email before review"))):
            completed = asyncio.run(pipeline.pipeline_orchestrator.run_pipeline(meeting.id))
        self.assertEqual(completed.processing_status, "completed", completed.error_message)
        self.assertEqual(completed.review_status, "pending_review")
        self.assertEqual(repository.list_deliveries(meeting.id), [])

    def test_edit_or_delete_during_send_is_not_overwritten(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        for mutation in ("edit", "delete"):
            fixture = self.fixture()
            meeting = fixture[0]
            approval = client.post(f"/api/v1/meetings/{meeting.id}/review/approve", json={"reviewer_name": "Reviewer"}).json()
            record = approval["delivery_record"]
            async def send(*args, **kwargs):
                if mutation == "delete":
                    repository.delete_meeting(meeting.id)
                else:
                    latest = repository.get_meeting(meeting.id)
                    latest.current_revision = 2
                    latest.review_status = ReviewStatus.PENDING_REVIEW
                    latest.approved_by = None
                    latest.approved_at = None
                    repository.save_meeting(latest)
                return {}, "OK"
            with patch("aiosmtplib.send", new=AsyncMock(side_effect=send)):
                client.post(f'/api/v1/deliveries/{record["id"]}/send')
            current = repository.get_meeting(meeting.id)
            if mutation == "delete":
                self.assertIsNone(current, "Sending resurrected a deleted meeting")
                self.assertEqual(repository.list_deliveries(meeting.id), [])
            else:
                self.assertEqual(current.current_revision, 2)
                self.assertEqual(current.review_status, "pending_review")

    def test_preparation_failure_can_be_corrected_and_approved_again(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        meeting, minutes, pdf, docx = self.fixture()
        pdf.unlink()
        url = f"/api/v1/meetings/{meeting.id}/review/approve"
        first = client.post(url, json={"reviewer_name": "Reviewer"}).json()["delivery_record"]
        self.assertEqual(first["status"], "failed")
        pdf.write_bytes(b"%PDF-restored")
        second = client.post(url, json={"reviewer_name": "Reviewer"}).json()["delivery_record"]
        self.assertEqual(second["status"], "saved_locally")

    def test_resend_dispatched_delivery_when_forced(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        fixture = self.fixture()
        meeting, minutes, pdf, docx = fixture
        approval = client.post(f"/api/v1/meetings/{meeting.id}/review/approve", json={"reviewer_name": "Reviewer"}).json()
        record = approval["delivery_record"]
        send_url = f'/api/v1/deliveries/{record["id"]}/send'
        with patch("aiosmtplib.send", new=AsyncMock(return_value=({}, "OK"))):
            sent = client.post(send_url, params={"force": "true"})
            self.assertEqual(sent.status_code, 200)
            self.assertEqual(sent.json()["status"], "dispatched")
            # Resend the already dispatched delivery
            resent = client.post(f'/api/v1/deliveries/{sent.json()["id"]}/send', params={"force": "true"})
            self.assertEqual(resent.status_code, 200)
            self.assertEqual(resent.json()["status"], "dispatched")
            self.assertNotEqual(resent.json()["id"], sent.json()["id"])
            self.assertEqual(resent.json()["retry_of"], sent.json()["id"])

    def test_resend_delivery_handles_starttls_unsupported_by_server(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from aiosmtplib.errors import SMTPException
        client = TestClient(app)
        fixture = self.fixture()
        meeting, minutes, pdf, docx = fixture
        approval = client.post(f"/api/v1/meetings/{meeting.id}/review/approve", json={"reviewer_name": "Reviewer"}).json()
        record = approval["delivery_record"]
        send_url = f'/api/v1/deliveries/{record["id"]}/send'

        calls = []
        async def mock_send(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise SMTPException("SMTP STARTTLS extension not supported by server.")
            return ({}, "250 OK")

        with patch("aiosmtplib.send", new=AsyncMock(side_effect=mock_send)):
            sent = client.post(send_url, params={"force": "true"})
            self.assertEqual(sent.status_code, 200)
            self.assertEqual(sent.json()["status"], "dispatched")
            self.assertEqual(len(calls), 2)
            # The second attempt should have used start_tls=False and use_tls=False
            self.assertFalse(calls[1]["start_tls"])
            self.assertFalse(calls[1]["use_tls"])


if __name__ == "__main__":
    unittest.main()
