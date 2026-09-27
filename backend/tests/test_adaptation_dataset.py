"""
Tests for Verified Adaptation Dataset Builder and Retention Lifecycle (Task 8)
"""

import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

test_root = Path(tempfile.mkdtemp(prefix="medora-dataset-test-"))
os.environ["DATA_DIR"] = str(test_root / "data")
os.environ["UPLOADS_DIR"] = str(test_root / "uploads")
os.environ["ADAPTATION_DIR"] = str(test_root / "adaptation")
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"

sys.path.insert(0, "backend")

from app.core.config import settings
from app.models.adaptation import CorrectionEvent
from app.services.learning.dataset_builder import build_dataset
from app.services.learning.retention import invalidate_source
from app.services.learning.store import adaptation_store


def _create_synthetic_wav(path: Path, duration_seconds: float = 10.0, sample_rate: int = 16000, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(duration_seconds * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # 16-bit PCM silence / tone
        samples = [int(1000 * math.sin(2 * math.pi * 440 * i / sample_rate)) for i in range(num_samples)]
        raw_bytes = struct.pack(f"<{num_samples}h", *samples)
        wf.writeframes(raw_bytes)


import math


class TestAdaptationDataset(unittest.TestCase):
    def setUp(self):
        # Create fresh directories
        Path(settings.UPLOADS_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.ADAPTATION_DIR).mkdir(parents=True, exist_ok=True)

    def test_build_dataset_slices_audio_and_groups_splits(self):
        # 1. Setup 3 synthetic meetings with 16kHz mono audio
        for i in range(1, 4):
            m_id = f"meeting_0{i}"
            wav_path = settings.UPLOADS_DIR / m_id / "normalized_16k.wav"
            _create_synthetic_wav(wav_path, duration_seconds=12.0)

            # Insert verified events with audio intervals (4.0s duration each)
            ev = CorrectionEvent(
                meeting_id=m_id,
                segment_id=f"seg_{i}",
                transcript_revision=2,
                previous_text="text vechi",
                new_text=f"Text verificat clinician pentru intalnirea {i}",
                raw_text="text vechi",
                verified_against_audio=True,
                training_reuse_allowed=True,
                verification_status="verified",
                reviewer_label=f"Dr. Medic_{i}",
            )
            adaptation_store.upsert_event(ev, metadata={"audio_start": 2.0, "audio_end": 6.0})

        out_dir = Path(settings.ADAPTATION_DIR) / "datasets" / "test_ds_v1"
        manifest = build_dataset(out_dir, seed=42)

        self.assertEqual(manifest.total_examples, 3)
        self.assertTrue((out_dir / "manifest.json").is_file())
        self.assertTrue(len(list((out_dir / "audio").glob("*.wav"))) == 3)

        # Leakage check: verify no meeting spans across both train and test
        train_meetings = {ex["meeting_id"] for ex in manifest.splits.get("train", [])}
        test_meetings = {ex["meeting_id"] for ex in manifest.splits.get("test", [])}
        dev_meetings = {ex["meeting_id"] for ex in manifest.splits.get("dev", [])}

        self.assertTrue(train_meetings.isdisjoint(test_meetings))
        self.assertTrue(train_meetings.isdisjoint(dev_meetings))
        self.assertTrue(dev_meetings.isdisjoint(test_meetings))

    def test_duration_filtering_and_redaction(self):
        m_id = "meeting_short_and_redacted"
        wav_path = settings.UPLOADS_DIR / m_id / "normalized_16k.wav"
        _create_synthetic_wav(wav_path, duration_seconds=15.0)

        # Too short clip (< 2.0s) -> excluded
        ev_short = CorrectionEvent(
            meeting_id=m_id,
            segment_id="seg_short",
            transcript_revision=2,
            previous_text="scurt",
            new_text="scurt",
            verified_against_audio=True,
            training_reuse_allowed=True,
            verification_status="verified",
        )
        adaptation_store.upsert_event(ev_short, metadata={"audio_start": 1.0, "audio_end": 2.0})

        # Redacted label -> excluded
        ev_redacted = CorrectionEvent(
            meeting_id=m_id,
            segment_id="seg_redacted",
            transcript_revision=2,
            previous_text="secret",
            new_text="[REDACTED]",
            verified_against_audio=True,
            training_reuse_allowed=True,
            verification_status="verified",
        )
        adaptation_store.upsert_event(ev_redacted, metadata={"audio_start": 3.0, "audio_end": 7.0})

        out_dir = Path(settings.ADAPTATION_DIR) / "datasets" / "test_ds_filtered"
        manifest = build_dataset(out_dir, seed=42)
        # None of the short or redacted events should be in the dataset
        for split in manifest.splits.values():
            for ex in split:
                self.assertNotEqual(ex["event_id"], ev_short.id)
                self.assertNotEqual(ex["event_id"], ev_redacted.id)

    def test_refuse_overwrite_and_path_validation(self):
        out_dir = Path(settings.ADAPTATION_DIR) / "datasets" / "test_ds_exist"
        build_dataset(out_dir, seed=42)

        # Second build targeting the same directory must raise FileExistsError
        with self.assertRaises(FileExistsError):
            build_dataset(out_dir, seed=42)

        # Path traversal outside ADAPTATION_DIR must raise ValueError
        outside_dir = Path(tempfile.gettempdir()) / "outside_adaptation"
        with self.assertRaises(ValueError):
            build_dataset(outside_dir, seed=42)

    def test_source_invalidation_lifecycle(self):
        m_id = "meeting_to_invalidate"
        wav_path = settings.UPLOADS_DIR / m_id / "normalized_16k.wav"
        _create_synthetic_wav(wav_path, duration_seconds=10.0)

        ev = CorrectionEvent(
            meeting_id=m_id,
            segment_id="seg_inv",
            transcript_revision=2,
            previous_text="text",
            new_text="Text validat pentru stergere ulterioara",
            verified_against_audio=True,
            training_reuse_allowed=True,
            verification_status="verified",
        )
        adaptation_store.upsert_event(ev, metadata={"audio_start": 1.0, "audio_end": 5.0})

        out_dir = Path(settings.ADAPTATION_DIR) / "datasets" / "test_ds_invalidation"
        manifest = build_dataset(out_dir, seed=42)

        # Audio clip exists
        audio_clips = list((out_dir / "audio").glob("*.wav"))
        self.assertTrue(len(audio_clips) >= 1)

        # Invalidate source meeting
        report = invalidate_source(m_id, reason="patient_consent_revoked")
        self.assertEqual(report.invalidated_events_count, 1)
        self.assertEqual(report.deleted_clips_count, 1)

        # Manifest must be marked invalidated
        manifest_data = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest_data.get("invalidated"))
        self.assertIn("patient_consent_revoked", manifest_data.get("invalidation_reason", ""))

        # The clip belonging to this meeting should be physically deleted
        inv_ex = next(ex for split in manifest.splits.values() for ex in split if ex["meeting_id"] == m_id)
        clip_abs = out_dir / inv_ex["audio_path"]
        self.assertFalse(clip_abs.exists())


if __name__ == "__main__":
    unittest.main()
