"""
Unit and regression tests for ASR training manifest validation and dry-run (Task 9).
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, "backend")
sys.path.insert(0, ".")

from deploy.scripts.fine_tune_whisper import compute_file_sha256, validate_dataset_manifest


class TestTrainingManifestValidation(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="medora-train-test-"))
        self.dataset_dir = self.test_dir / "dataset"
        self.audio_dir = self.dataset_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)

        # Create dummy audio files
        self.audio_file1 = self.audio_dir / "clip1.wav"
        self.audio_file1.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
        self.sha1 = compute_file_sha256(self.audio_file1)

        self.audio_file2 = self.audio_dir / "clip2.wav"
        self.audio_file2.write_bytes(b"RIFF\x04\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x04\x00\x00\x00\x00\x00\x00\x00")
        self.sha2 = compute_file_sha256(self.audio_file2)

        self.valid_manifest = {
            "manifest_version": "1.0.0",
            "dataset_id": "ds_test123",
            "label_policy": "verbatim_human_review",
            "invalidated": False,
            "splits": {
                "train": [
                    {
                        "example_id": "ex1",
                        "meeting_id": "m1",
                        "audio_path": "audio/clip1.wav",
                        "audio_checksum": self.sha1,
                        "text": "Pacientul a fost externat.",
                    }
                ],
                "dev": [
                    {
                        "example_id": "ex2",
                        "meeting_id": "m2",
                        "audio_path": "audio/clip2.wav",
                        "audio_checksum": self.sha2,
                        "text": "Tratamentul a fost revizuit.",
                    }
                ],
                "test": [],
            },
        }

    def _save_manifest(self, data: dict) -> None:
        (self.dataset_dir / "manifest.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_valid_manifest_passes_validation(self):
        self._save_manifest(self.valid_manifest)
        data, errors = validate_dataset_manifest(self.dataset_dir)
        self.assertEqual(len(errors), 0)
        self.assertEqual(data["dataset_id"], "ds_test123")

    def test_invalidated_manifest_rejected(self):
        manifest = dict(self.valid_manifest)
        manifest["invalidated"] = True
        manifest["invalidation_reason"] = "Patient consent revoked"
        self._save_manifest(manifest)

        data, errors = validate_dataset_manifest(self.dataset_dir)
        self.assertTrue(any("INVALIDATED" in err for err in errors))

    def test_unsupported_label_policy_rejected(self):
        manifest = dict(self.valid_manifest)
        manifest["label_policy"] = "machine_generated_unverified"
        self._save_manifest(manifest)

        data, errors = validate_dataset_manifest(self.dataset_dir)
        self.assertTrue(any("Unsupported label policy" in err for err in errors))

    def test_split_leakage_rejected(self):
        # meeting "m1" appears in both train and dev!
        manifest = dict(self.valid_manifest)
        manifest["splits"]["dev"][0]["meeting_id"] = "m1"
        self._save_manifest(manifest)

        data, errors = validate_dataset_manifest(self.dataset_dir)
        self.assertTrue(any("Acoustic leakage" in err for err in errors))

    def test_missing_audio_file_rejected(self):
        manifest = dict(self.valid_manifest)
        manifest["splits"]["train"][0]["audio_path"] = "audio/non_existent.wav"
        self._save_manifest(manifest)

        data, errors = validate_dataset_manifest(self.dataset_dir)
        self.assertTrue(any("Audio file missing" in err for err in errors))

    def test_checksum_mismatch_rejected(self):
        manifest = dict(self.valid_manifest)
        manifest["splits"]["train"][0]["audio_checksum"] = "bad_checksum_hash"
        self._save_manifest(manifest)

        data, errors = validate_dataset_manifest(self.dataset_dir)
        self.assertTrue(any("Checksum mismatch" in err for err in errors))

    def test_cli_dry_run_execution(self):
        self._save_manifest(self.valid_manifest)
        exp_out = self.test_dir / "experiment"

        python_exe = sys.executable
        script_path = Path("deploy/scripts/fine_tune_whisper.py").resolve()

        res = subprocess.run(
            [
                python_exe,
                str(script_path),
                "--dataset", str(self.dataset_dir),
                "--output-dir", str(exp_out),
                "--device", "cpu",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"CLI stderr: {res.stderr}")
        self.assertTrue((exp_out / "experiment_report.json").is_file())
        report = json.loads((exp_out / "experiment_report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["validation_passed"])
        self.assertEqual(report["mode"], "dry_run")


if __name__ == "__main__":
    unittest.main()
