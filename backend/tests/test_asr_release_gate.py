"""
Tests for ASR Release Gate Evaluation and Model Registry Lifecycle (Task 10).
"""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

test_root = Path(tempfile.mkdtemp(prefix="medora-registry-test-"))
os.environ["DATA_DIR"] = str(test_root / "data")
os.environ["ADAPTATION_DIR"] = str(test_root / "adaptation")
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"

sys.path.insert(0, "backend")
sys.path.insert(0, ".")

from deploy.scripts.evaluate_asr import evaluate_release_gates
from app.services.learning.model_registry import ModelRegistry


class TestASRReleaseGate(unittest.TestCase):
    def setUp(self):
        self.baseline_eval = {
            "corpus_wer": 0.120,
            "language_wer": {"ro": 0.110, "ru": 0.125, "en": 0.100},
            "critical_fact_errors": 1,
            "silence_hallucinations": 0,
            "entity_precision": 0.95,
            "entity_recall": 0.92,
            "rtf": 0.040,
        }
        self.good_candidate_eval = {
            "corpus_wer": 0.110,  # 8.3% relative improvement
            "paired_bootstrap_wer_diff_upper": -0.004,  # statistically significant
            "language_wer": {"ro": 0.105, "ru": 0.118, "en": 0.098},
            "critical_fact_errors": 1,
            "silence_hallucinations": 0,
            "entity_precision": 0.96,
            "entity_recall": 0.94,
            "rtf": 0.044,  # 10% slower, within 20% limit
        }

    def test_passing_candidate_meets_all_release_gates(self):
        report = evaluate_release_gates(self.baseline_eval, self.good_candidate_eval)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(len(report["rejection_reasons"]), 0)
        self.assertIsNotNone(report.get("report_hash"))

    def test_insufficient_wer_gain_rejected(self):
        bad_cand = dict(self.good_candidate_eval)
        bad_cand["corpus_wer"] = 0.118  # Only 1.6% improvement (< 5.0%)
        report = evaluate_release_gates(self.baseline_eval, bad_cand)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("Insufficient WER improvement" in r for r in report["rejection_reasons"]))

    def test_insignificant_bootstrap_difference_rejected(self):
        bad_cand = dict(self.good_candidate_eval)
        bad_cand["paired_bootstrap_wer_diff_upper"] = 0.002  # CI includes zero
        report = evaluate_release_gates(self.baseline_eval, bad_cand)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("Paired bootstrap upper bound" in r for r in report["rejection_reasons"]))

    def test_language_regression_rejected(self):
        bad_cand = dict(self.good_candidate_eval)
        bad_cand["language_wer"] = {"ro": 0.130, "ru": 0.110, "en": 0.095}  # RO regressed from 0.110 to 0.130!
        report = evaluate_release_gates(self.baseline_eval, bad_cand)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("WER regressed in language strata" in r for r in report["rejection_reasons"]))

    def test_critical_fact_error_increase_rejected(self):
        bad_cand = dict(self.good_candidate_eval)
        bad_cand["critical_fact_errors"] = 3  # Regressed from 1 to 3
        report = evaluate_release_gates(self.baseline_eval, bad_cand)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("Critical fact errors increased" in r for r in report["rejection_reasons"]))

    def test_missing_bootstrap_measurement_yields_insufficient_evidence(self):
        missing_cand = dict(self.good_candidate_eval)
        del missing_cand["paired_bootstrap_wer_diff_upper"]
        report = evaluate_release_gates(self.baseline_eval, missing_cand)
        self.assertEqual(report["status"], "insufficient_evidence")


class TestModelRegistryLifecycle(unittest.TestCase):
    def setUp(self):
        self.db_path = test_root / "adaptation" / "test_registry.sqlite3"
        self.registry = ModelRegistry(db_path=self.db_path)
        self.dummy_model_dir1 = test_root / "models" / "cand1"
        self.dummy_model_dir1.mkdir(parents=True, exist_ok=True)
        (self.dummy_model_dir1 / "model.bin").write_bytes(b"MODEL_V1")

        self.dummy_model_dir2 = test_root / "models" / "cand2"
        self.dummy_model_dir2.mkdir(parents=True, exist_ok=True)
        (self.dummy_model_dir2 / "model.bin").write_bytes(b"MODEL_V2")

    def test_registry_full_lifecycle_and_rollback(self):
        # 1. Register candidate 1
        art1 = self.registry.register_artifact(
            name="whisper-turbo-medora",
            version="1.0.0",
            target_runtime="ctranslate2",
            quantization="float16",
            base_model="openai/whisper-large-v3-turbo",
            model_path=self.dummy_model_dir1,
            checksum="hash1",
        )
        self.assertEqual(art1.status, "candidate")

        # 2. Attach evaluation
        eval_hash1 = "sha256_eval_hash_1"
        art1 = self.registry.attach_evaluation(art1.artifact_id, report_hash=eval_hash1, evaluation_passed=True)
        self.assertEqual(art1.status, "evaluated")

        # 3. Approve
        art1 = self.registry.approve_artifact(art1.artifact_id, reviewer_label="Dr. Medic", evaluation_report_hash=eval_hash1)
        self.assertEqual(art1.status, "approved")

        # 4. Activate
        art1 = self.registry.activate_artifact(art1.artifact_id, operator_label="admin")
        self.assertEqual(art1.status, "active")

        # Check active model
        active = self.registry.get_active_artifact("ctranslate2")
        self.assertIsNotNone(active)
        self.assertEqual(active.artifact_id, art1.artifact_id)

        # 5. Register and activate Candidate 2
        art2 = self.registry.register_artifact(
            name="whisper-turbo-medora",
            version="1.1.0",
            target_runtime="ctranslate2",
            quantization="float16",
            base_model="openai/whisper-large-v3-turbo",
            model_path=self.dummy_model_dir2,
            checksum="hash2",
        )
        eval_hash2 = "sha256_eval_hash_2"
        art2 = self.registry.attach_evaluation(art2.artifact_id, report_hash=eval_hash2, evaluation_passed=True)
        art2 = self.registry.approve_artifact(art2.artifact_id, reviewer_label="Dr. Medic", evaluation_report_hash=eval_hash2)
        art2 = self.registry.activate_artifact(art2.artifact_id, operator_label="admin")

        self.assertEqual(art2.status, "active")
        self.assertEqual(art2.previous_active_artifact_id, art1.artifact_id)

        # Previous active art1 should now be retired
        art1_updated = self.registry.get_artifact(art1.artifact_id)
        self.assertEqual(art1_updated.status, "retired")

        # 6. Rollback runtime
        restored = self.registry.rollback_runtime("ctranslate2", operator_label="admin", reason="Simulated runtime failure")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.artifact_id, art1.artifact_id)
        self.assertEqual(restored.status, "active")

        # Current active is now art1 again
        active_now = self.registry.get_active_artifact("ctranslate2")
        self.assertEqual(active_now.artifact_id, art1.artifact_id)


if __name__ == "__main__":
    unittest.main()
