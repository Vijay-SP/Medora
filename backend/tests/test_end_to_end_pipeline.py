"""
End-to-End Pipeline Integration Test
Verifies complete flow:
1. Truthful no-speech handling: non-speech audio does NOT fabricate transcripts or auto-deliver fake minutes.
2. Complete speech pipeline: Audio Upload -> Normalization -> Diarization -> Extraction -> Documents -> Delivery Outbox.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import numpy as np
import soundfile as sf
import tempfile
import shutil

from app.core.config import settings
from app.models.meeting import Meeting, MeetingType, WorkflowMode, Attendee, ProcessingStatus, ReviewStatus
from app.models.transcript import TranscriptSegment
from app.models.delivery import DeliveryStatus
from app.storage.repository import repository
from app.storage.file_manager import file_manager
from app.services.pipeline_orchestrator import pipeline_orchestrator


def test_end_to_end_no_speech_behavior():
    """Verifies that non-speech audio (pure sine tone/silence) does not fabricate transcripts or deliver emails."""
    test_dir = Path(tempfile.mkdtemp(prefix="medpark_test_e2e_nospeech_"))
    try:
        old_data_dir = settings.DATA_DIR
        old_uploads_dir = settings.UPLOADS_DIR
        old_exports_dir = settings.EXPORTS_DIR
        settings.DATA_DIR = test_dir / "data"
        settings.UPLOADS_DIR = test_dir / "uploads"
        settings.EXPORTS_DIR = test_dir / "exports"
        settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        settings.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

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

        print("PASSED: test_end_to_end_no_speech_behavior verified!")
    finally:
        settings.DATA_DIR = old_data_dir
        settings.UPLOADS_DIR = old_uploads_dir
        settings.EXPORTS_DIR = old_exports_dir
        shutil.rmtree(test_dir, ignore_errors=True)


def test_end_to_end_speech_pipeline():
    """Verifies complete pipeline with speech: ASR, Diarization, Evidence Extraction, Document Generation, and Delivery."""
    test_dir = Path(tempfile.mkdtemp(prefix="medpark_test_e2e_speech_"))
    try:
        old_data_dir = settings.DATA_DIR
        old_uploads_dir = settings.UPLOADS_DIR
        old_exports_dir = settings.EXPORTS_DIR
        old_sim_deliv = settings.ALLOW_SIMULATED_DELIVERY
        settings.DATA_DIR = test_dir / "data"
        settings.UPLOADS_DIR = test_dir / "uploads"
        settings.EXPORTS_DIR = test_dir / "exports"
        settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        settings.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        settings.ALLOW_SIMULATED_DELIVERY = True

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

        from unittest.mock import AsyncMock

        with patch("app.services.asr.whisper_engine.whisper_engine.transcribe", return_value=mock_segments), \
             patch("aiosmtplib.send", new_callable=AsyncMock):
            completed_meeting = asyncio.run(pipeline_orchestrator.run_pipeline(meeting.id))

        assert completed_meeting.processing_status == ProcessingStatus.COMPLETED
        assert completed_meeting.processing_progress == 100
        assert completed_meeting.audio_duration_seconds > 0.0

        # In Auto-Pilot mode with successful delivery dispatch
        assert completed_meeting.review_status == ReviewStatus.DELIVERED

        # Verify Minutes and Documents
        minutes = repository.get_minutes(meeting.id)
        assert minutes is not None
        assert len(minutes.decisions) >= 1
        assert len(minutes.action_items) >= 1
        assert minutes.pdf_path is not None
        assert Path(minutes.pdf_path).exists()
        assert minutes.docx_path is not None
        assert Path(minutes.docx_path).exists()

        # Verify Evidence Quotes
        assert len(minutes.decisions[0].evidence) >= 1
        assert minutes.decisions[0].evidence[0].segment_id == "seg_001"

        # Verify Delivery Outbox Record
        deliveries = repository.list_deliveries(meeting_id=meeting.id)
        assert len(deliveries) >= 1
        assert "elena.ceban@medpark.md" in deliveries[0].recipients
        assert "director.medical@medpark.md" in deliveries[0].recipients
        assert deliveries[0].status == DeliveryStatus.DISPATCHED

        print("PASSED: test_end_to_end_speech_pipeline verified!")
    finally:
        settings.DATA_DIR = old_data_dir
        settings.UPLOADS_DIR = old_uploads_dir
        settings.EXPORTS_DIR = old_exports_dir
        settings.ALLOW_SIMULATED_DELIVERY = old_sim_deliv
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    test_end_to_end_no_speech_behavior()
    test_end_to_end_speech_pipeline()
    print("All end-to-end integration tests passed successfully!")
