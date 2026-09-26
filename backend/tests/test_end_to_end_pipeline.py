"""
End-to-End Pipeline Integration Test
Verifies complete flow:
1. Truthful no-speech handling: non-speech audio does NOT fabricate transcripts or auto-deliver fake minutes.
2. Complete speech pipeline: Audio Upload -> Normalization -> Diarization -> Extraction -> Documents -> Delivery Outbox.
   2a. Without a local LLM the heuristic fallback produces a DEGRADED draft that is held for review, never emailed.
   2b. With LLM-grounded minutes (engine mocked) the auto-pilot dispatches to the mocked SMTP transport.

Runs OFFLINE: REQUIRE_LOCAL_LLM=false / LLM_FALLBACK_MODE=heuristic are forced and the LLM endpoint is
pointed at a dead port BEFORE any app import (the Ollama client binds its base URL at import), so the
run is deterministic whether or not an Ollama server is up. Whisper is mocked in the speech tests but
the no-speech test loads it for real: never run this while the LLM occupies the GPU.
"""

import os
import tempfile
from pathlib import Path

_ISOLATED_ROOT = Path(os.environ.get("DATA_DIR") or os.path.join(tempfile.mkdtemp(prefix="medpark_test_e2e_"), "data"))
os.environ.setdefault("DATA_DIR", str(_ISOLATED_ROOT))
os.environ.setdefault("UPLOADS_DIR", str(_ISOLATED_ROOT / "uploads"))
os.environ.setdefault("EXPORTS_DIR", str(_ISOLATED_ROOT / "exports"))
os.environ.setdefault("FIXTURES_DIR", str(_ISOLATED_ROOT / "fixtures"))
# VOICEPRINTS_DIR defaults to the class-time DATA_DIR/"voiceprints" (the repository data directory) and the
# diarizer caches segment embeddings there whenever it is given a meeting_id: it must be isolated explicitly.
os.environ.setdefault("VOICEPRINTS_DIR", str(_ISOLATED_ROOT / "voiceprints"))
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"
os.environ["REQUIRE_LOCAL_LLM"] = "false"
os.environ["LLM_FALLBACK_MODE"] = "heuristic"
os.environ["LLM_API_BASE_URL"] = "http://127.0.0.1:9"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("ASR_PROVIDER", "whisper_cpp" if Path("/opt/homebrew/bin/whisper-cli").exists() else "faster_whisper")

import asyncio  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import datetime  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import shutil  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.meeting import Meeting, MeetingType, WorkflowMode, Attendee, ProcessingStatus, ReviewStatus  # noqa: E402
from app.models.transcript import Transcript, TranscriptSegment  # noqa: E402
from app.models.extraction import MinutesOfMeeting, DecisionItem, ActionItem, EvidenceQuote  # noqa: E402
from app.models.delivery import DeliveryStatus  # noqa: E402
from app.storage.repository import repository  # noqa: E402
from app.storage.file_manager import file_manager  # noqa: E402
from app.services.extraction.llm_engine import extraction_engine  # noqa: E402
from app.services.extraction.llm_client import llm_client  # noqa: E402
from app.services.extraction.heuristic_extractor import DEGRADED_MODEL_VERSION  # noqa: E402
from app.services.pipeline_orchestrator import pipeline_orchestrator  # noqa: E402

LLM_PROVENANCE = "ollama 0.34.4 / medpark-extractor / Q4_K_M / ctx4096 (mocked engine)"
# The repository's real biometric store: no test may ever create a meeting row here
_REPO_VOICEPRINTS_DIR = Path(__file__).resolve().parents[2] / "data" / "voiceprints"


@contextmanager
def isolated_storage(prefix: str):
    """
    Repoints every storage location at a throwaway directory for the duration of a test.
    Derived settings do not follow a DATA_DIR override and the repository singleton binds its
    store directory at import time, so each path (VOICEPRINTS_DIR included: the diarizer caches
    segment embeddings there) is overridden explicitly and the repository is repointed as well.
    Without this the run would write into the production data directory.
    SMTP is also pinned to a dead local port so no test can reach a real mail server.
    """
    test_dir = Path(tempfile.mkdtemp(prefix=prefix))
    previous = {
        "DATA_DIR": settings.DATA_DIR,
        "UPLOADS_DIR": settings.UPLOADS_DIR,
        "EXPORTS_DIR": settings.EXPORTS_DIR,
        "FIXTURES_DIR": settings.FIXTURES_DIR,
        "VOICEPRINTS_DIR": settings.VOICEPRINTS_DIR,
        "SMTP_HOST": settings.SMTP_HOST,
        "SMTP_PORT": settings.SMTP_PORT,
        "ALLOW_SIMULATED_DELIVERY": settings.ALLOW_SIMULATED_DELIVERY,
        "REQUIRE_LOCAL_LLM": settings.REQUIRE_LOCAL_LLM,
        "LLM_FALLBACK_MODE": settings.LLM_FALLBACK_MODE,
    }
    try:
        settings.DATA_DIR = test_dir / "data"
        settings.UPLOADS_DIR = test_dir / "uploads"
        settings.EXPORTS_DIR = test_dir / "exports"
        settings.FIXTURES_DIR = test_dir / "fixtures"
        settings.VOICEPRINTS_DIR = test_dir / "voiceprints"
        for path in [settings.DATA_DIR, settings.UPLOADS_DIR, settings.EXPORTS_DIR, settings.FIXTURES_DIR, settings.VOICEPRINTS_DIR]:
            path.mkdir(parents=True, exist_ok=True)
        settings.SMTP_HOST = "127.0.0.1"
        settings.SMTP_PORT = 9  # discard port: an unmocked send can never reach a mail catcher
        settings.ALLOW_SIMULATED_DELIVERY = False  # a broken transport must fail loudly, not look sent
        settings.REQUIRE_LOCAL_LLM = False          # no LLM in this suite: the degraded heuristic path is exercised
        settings.LLM_FALLBACK_MODE = "heuristic"
        repository.reconfigure(settings.DATA_DIR)

        # Isolation is a precondition of the test, not a side effect: assert it before any write
        assert repository.storage_dir == settings.DATA_DIR / "store"
        assert repository.storage_dir.is_relative_to(test_dir)
        assert Path(settings.VOICEPRINTS_DIR).is_relative_to(test_dir), f"voiceprints not isolated: {settings.VOICEPRINTS_DIR}"
        assert llm_client.base_url == "http://127.0.0.1:9", "the Ollama client must be bound to a dead port by the env"
        yield test_dir
    finally:
        for key, value in previous.items():
            setattr(settings, key, value)
        repository.reconfigure(settings.DATA_DIR)
        shutil.rmtree(test_dir, ignore_errors=True)


def test_end_to_end_no_speech_behavior():
    """Verifies that non-speech audio (pure sine tone/silence) does not fabricate transcripts or deliver emails."""
    with isolated_storage("medpark_test_e2e_nospeech_") as test_dir:
        meeting = Meeting(
            title="Consiliu Urgență - Test Non-Vocal",
            meeting_type=MeetingType.MEDICAL,
            workflow_mode=WorkflowMode.AUTO_PILOT,
            scheduled_at=datetime(2026, 9, 25, 11, 0),
            attendees=[
                Attendee(name="Dr. Elena Ceban", role="Chirurg Șef", email="elena.ceban@medpark.md")
            ]
        )
        repository.save_meeting(meeting)

        # Synthesize a pure sine wave (silence / pure tone, no human speech)
        sr = 16000
        duration = 3.0
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        synthetic_signal = 0.3 * np.sin(2 * np.pi * 440 * t)

        upload_dir = settings.UPLOADS_DIR / meeting.id
        upload_dir.mkdir(parents=True, exist_ok=True)
        raw_audio_path = upload_dir / "original.wav"
        sf.write(str(raw_audio_path), synthetic_signal, sr)

        meeting.original_audio_path = str(raw_audio_path)
        repository.save_meeting(meeting)

        completed_meeting = asyncio.run(pipeline_orchestrator.run_pipeline(meeting.id))

        assert completed_meeting.processing_status == ProcessingStatus.COMPLETED
        assert completed_meeting.processing_progress == 100
        # Truthful behavior: When there is no speech, review_status must NOT be DELIVERED
        assert completed_meeting.review_status == ReviewStatus.PENDING_REVIEW

        # Ensure no deliveries were triggered for non-speech audio
        deliveries = repository.list_deliveries(meeting_id=meeting.id)
        assert len(deliveries) == 0

        # Minutes were generated with truthful empty/no-speech note
        minutes = repository.get_minutes(meeting.id)
        assert minutes is not None
        assert len(minutes.decisions) == 0
        assert len(minutes.action_items) == 0

        # Every artifact of this run stayed inside the isolated directory
        assert Path(minutes.pdf_path).is_relative_to(test_dir)
        assert Path(minutes.docx_path).is_relative_to(test_dir)
        assert repository.get_meeting(meeting.id) is not None
        assert (test_dir / "data" / "store" / "meetings.json").exists()
        _assert_embedding_cache_isolated(meeting.id, test_dir)

        print("PASSED: test_end_to_end_no_speech_behavior verified!")


def _prepare_speech_meeting() -> tuple[Meeting, list[TranscriptSegment]]:
    """Persists an auto-pilot meeting with a synthetic noise upload and returns the mocked ASR segments."""
    meeting = Meeting(
        title="Consiliu Medical - Aprobare Ghid ATI",
        meeting_type=MeetingType.MEDICAL,
        workflow_mode=WorkflowMode.AUTO_PILOT,
        scheduled_at=datetime(2026, 9, 25, 11, 0),
        attendees=[
            Attendee(name="Dr. Elena Ceban", role="Chirurg Șef", email="elena.ceban@medpark.md"),
            Attendee(name="Dr. Mihail Popov", role="Șef Terapie Intensivă", email="mihail.popov@medpark.md")
        ],
        distribution_list=["elena.ceban@medpark.md", "mihail.popov@medpark.md", "director.medical@medpark.md"]
    )
    repository.save_meeting(meeting)

    sr = 16000
    duration = 5.0
    synthetic_signal = np.random.normal(0, 0.05, int(sr * duration)).astype(np.float32)

    upload_dir = settings.UPLOADS_DIR / meeting.id
    upload_dir.mkdir(parents=True, exist_ok=True)
    raw_audio_path = upload_dir / "original.wav"
    sf.write(str(raw_audio_path), synthetic_signal, sr)

    meeting.original_audio_path = str(raw_audio_path)
    repository.save_meeting(meeting)

    mock_segments = [
        TranscriptSegment(
            id="seg_001",
            start=0.5,
            end=2.5,
            speaker="Speaker 1",
            raw_text="Dr. Elena Ceban: Am decis să aprobăm protocolul revizuit de hemostază chirurgicală pentru sălile de operație.",
            language="ro",
            confidence=0.98
        ),
        TranscriptSegment(
            id="seg_002",
            start=2.6,
            end=4.8,
            speaker="Speaker 2",
            raw_text="Dr. Mihail Popov: Voi actualiza ghidul clinic și voi instrui asistenții până mâine.",
            language="ro",
            confidence=0.95
        ),
    ]
    return meeting, mock_segments


def _assert_embedding_cache_isolated(meeting_id: str, test_dir: Path) -> None:
    """
    The diarizer writes segments.npy / segments.json for the meeting under VOICEPRINTS_DIR when it is
    called with a meeting_id (it is, since Stage 3 passes meeting.id). Whether or not the fixture carried
    enough speech to produce a cache, its destination must be the throwaway tree and the repository's
    own data/voiceprints must not have gained a row for this meeting.
    """
    matrix_path, sidecar_path = file_manager.get_segment_embedding_paths(meeting_id)
    assert matrix_path.is_relative_to(test_dir), f"embedding cache would land outside the test tree: {matrix_path}"
    assert sidecar_path.is_relative_to(test_dir), f"embedding sidecar would land outside the test tree: {sidecar_path}"
    repo_row = _REPO_VOICEPRINTS_DIR / "meetings" / meeting_id
    assert not repo_row.exists(), f"the test wrote biometric data into the repository store: {repo_row}"


def _assert_documents_isolated(minutes: MinutesOfMeeting, test_dir: Path) -> None:
    assert minutes.pdf_path is not None
    assert Path(minutes.pdf_path).exists()
    assert minutes.docx_path is not None
    assert Path(minutes.docx_path).exists()
    # Documents were exported into the isolated tree, never into the production exports
    assert Path(minutes.pdf_path).is_relative_to(test_dir)
    assert Path(minutes.docx_path).is_relative_to(test_dir)


class _MockEngine:
    def __init__(self, segments):
        self.segments = segments
        self.device = "metal" if settings.ASR_PROVIDER == "whisper_cpp" else "cpu"
    def transcribe(self, *args, **kwargs):
        return self.segments
    def release_model(self):
        pass


def test_end_to_end_speech_pipeline_degraded_draft_is_held():
    """
    Without a local LLM (policy allows the heuristic fallback) the pipeline completes with a DEGRADED
    draft: documents are generated, but the auto-pilot dispatch is refused and the meeting is held for
    human review. No mail is ever attempted.
    """
    with isolated_storage("medpark_test_e2e_speech_") as test_dir:
        meeting, mock_segments = _prepare_speech_meeting()

        with patch("app.services.pipeline_orchestrator.get_asr_engine", return_value=_MockEngine(mock_segments)), \
             patch("app.services.asr.whisper_engine.whisper_engine.transcribe", return_value=mock_segments), \
             patch("aiosmtplib.send", new_callable=AsyncMock) as smtp_send:
            completed_meeting = asyncio.run(pipeline_orchestrator.run_pipeline(meeting.id))

        assert completed_meeting.processing_status == ProcessingStatus.COMPLETED
        assert completed_meeting.processing_progress == 100
        assert completed_meeting.audio_duration_seconds > 0.0
        assert completed_meeting.asr_device_used in ("cuda", "cpu", "metal")

        # A degraded draft never leaves the building: held for review, dispatch guard message surfaced
        assert completed_meeting.review_status == ReviewStatus.PENDING_REVIEW
        assert completed_meeting.error_message and "DRAFT degradat" in completed_meeting.error_message
        smtp_send.assert_not_called()
        assert repository.list_deliveries(meeting_id=meeting.id) == []

        minutes = repository.get_minutes(meeting.id)
        assert minutes is not None
        assert minutes.is_degraded is True
        assert minutes.model_version == DEGRADED_MODEL_VERSION
        assert len(minutes.decisions) >= 1
        assert len(minutes.action_items) >= 1
        assert minutes.decisions[0].evidence[0].segment_id == "seg_001"
        _assert_documents_isolated(minutes, test_dir)
        _assert_embedding_cache_isolated(meeting.id, test_dir)

        print("PASSED: test_end_to_end_speech_pipeline_degraded_draft_is_held verified!")


def test_end_to_end_speech_pipeline_llm_minutes_require_human_approval():
    """
    With LLM-grounded minutes (extraction engine mocked at the orchestrator boundary, no Ollama needed)
    auto-pilot generates documents but waits for human approval before mocked SMTP dispatch.
    """
    with isolated_storage("medpark_test_e2e_delivery_") as test_dir:
        meeting, mock_segments = _prepare_speech_meeting()

        async def grounded_extract(meeting_arg: Meeting, transcript: Transcript) -> MinutesOfMeeting:
            seg1, seg2 = transcript.segments[0], transcript.segments[1]
            ev1 = EvidenceQuote(segment_id=seg1.id, start=seg1.start, end=seg1.end, quote=seg1.display_text, speaker=seg1.speaker)
            ev2 = EvidenceQuote(segment_id=seg2.id, start=seg2.start, end=seg2.end, quote=seg2.display_text, speaker=seg2.speaker)
            return MinutesOfMeeting(
                meeting_id=meeting_arg.id,
                title=meeting_arg.title,
                meeting_type=meeting_arg.meeting_type.value,
                summary_ro="Consiliul a aprobat protocolul revizuit de hemostază chirurgicală.",
                summary_en="The board approved the revised surgical haemostasis protocol.",
                agenda_topics=["Protocol hemostază"],
                decisions=[DecisionItem(topic="Protocol hemostază", decision="Se aprobă protocolul revizuit de hemostază chirurgicală.", category="protocol", evidence=[ev1])],
                action_items=[ActionItem(task="Actualizarea ghidului clinic și instruirea asistenților.", owner="Dr. Mihail Popov", owner_source="roster", deadline_phrase="până mâine", deadline_date="2026-09-26", evidence=[ev2])],
                model_version=LLM_PROVENANCE,
                extraction_stats={"engine": "ollama", "model": settings.LLM_MODEL_NAME, "chunks": 1, "calls": 2},
            )

        with patch("app.services.pipeline_orchestrator.get_asr_engine", return_value=_MockEngine(mock_segments)), \
             patch("app.services.asr.whisper_engine.whisper_engine.transcribe", return_value=mock_segments), \
             patch.object(extraction_engine, "preflight", new=AsyncMock(return_value=LLM_PROVENANCE)), \
             patch.object(extraction_engine, "extract_minutes", new=AsyncMock(side_effect=grounded_extract)), \
             patch("aiosmtplib.send", new=AsyncMock(return_value=({}, "OK"))) as smtp_send:
            completed_meeting = asyncio.run(pipeline_orchestrator.run_pipeline(meeting.id))

        assert completed_meeting.processing_status == ProcessingStatus.COMPLETED
        assert completed_meeting.processing_progress == 100
        assert completed_meeting.audio_duration_seconds > 0.0

        assert completed_meeting.review_status == ReviewStatus.PENDING_REVIEW
        assert smtp_send.await_count == 0
        assert repository.list_deliveries(meeting_id=meeting.id) == []

        from app.api.v1.endpoints.review import approve_and_dispatch, ApprovalRequest
        with patch("aiosmtplib.send", new=AsyncMock(return_value=({}, "OK"))):
            approved = asyncio.run(approve_and_dispatch(meeting.id, ApprovalRequest(reviewer_name="Reviewer", expected_revision=1)))
        assert approved.status == ReviewStatus.DELIVERED

        # Verify Minutes and Documents
        minutes = repository.get_minutes(meeting.id)
        assert minutes is not None
        assert minutes.is_degraded is False
        assert minutes.model_version == LLM_PROVENANCE
        assert len(minutes.decisions) >= 1
        assert len(minutes.action_items) >= 1
        _assert_documents_isolated(minutes, test_dir)
        _assert_embedding_cache_isolated(meeting.id, test_dir)

        # Verify Evidence Quotes
        assert len(minutes.decisions[0].evidence) >= 1
        assert minutes.decisions[0].evidence[0].segment_id == "seg_001"

        # Verify Delivery Outbox Record
        deliveries = repository.list_deliveries(meeting_id=meeting.id)
        assert len(deliveries) == 1
        record = deliveries[0]
        assert record.status == DeliveryStatus.DISPATCHED
        assert record.meeting_id == meeting.id
        assert record.revision == minutes.revision

        # The custom distribution list is an exclusive override: exactly those addresses, deduped,
        # lowercased and sorted - no department policy default and no CC entry may leak in.
        assert record.recipients == sorted(a.lower() for a in meeting.distribution_list)
        assert "comitet.calitate@medpark.md" not in record.recipients
        assert "sefi.sectii@medpark.md" not in record.recipients
        assert "arhiva.medicala@medpark.md" not in record.recipients

        # The dispatched mail carries both generated attachments
        assert record.pdf_attachment_path == minutes.pdf_path
        assert record.docx_attachment_path == minutes.docx_path

        print("PASSED: test_end_to_end_speech_pipeline_llm_minutes_require_human_approval verified!")


if __name__ == "__main__":
    test_end_to_end_no_speech_behavior()
    test_end_to_end_speech_pipeline_degraded_draft_is_held()
    test_end_to_end_speech_pipeline_llm_minutes_require_human_approval()
    print("All end-to-end integration tests passed successfully!")
