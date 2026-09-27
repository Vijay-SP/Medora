"""
Medora ASR Evaluation Harness - Unit and Contract Tests
Verifies offline ASR scoring math, schema invariants, clinical entity recall,
critical fact checking, and bootstrap confidence intervals.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.eval.asr_metrics import (
    compute_cer,
    compute_edit_counts,
    compute_recording_bootstrap_ci,
    compute_wer,
    normalize_text_for_scoring,
    score_asr,
)
from tools.eval.asr_schema import ASRHypothesisSet, ASRManifest, GoldSegment, RecordingEntry


_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tools" / "eval" / "fixtures" / "asr_synthetic.json"


class TestASREvaluation(unittest.TestCase):
    def test_compute_edit_counts_and_wer(self):
        # Exact match
        s, d, i = compute_edit_counts(["unu", "doi"], ["unu", "doi"])
        self.assertEqual((s, d, i), (0, 0, 0))

        # 1 substitution ("doi" -> "trei")
        s, d, i = compute_edit_counts(["unu", "doi"], ["unu", "trei"])
        self.assertEqual((s, d, i), (1, 0, 0))

        # 1 deletion ("doi" dropped)
        s, d, i = compute_edit_counts(["unu", "doi"], ["unu"])
        self.assertEqual((s, d, i), (0, 1, 0))

        # 1 insertion ("trei" added)
        s, d, i = compute_edit_counts(["unu", "doi"], ["unu", "doi", "trei"])
        self.assertEqual((s, d, i), (0, 0, 1))

        # Empty reference with hypothesis insertions
        wer, s, d, i, n = compute_wer("", "parole hallucination")
        self.assertEqual(wer, 1.0)
        self.assertEqual(i, 2)
        self.assertEqual(n, 0)

    def test_normalization_preserves_diacritics_and_cyrillic(self):
        text_ro = "Ședință medicală: pacientul are febră?"
        norm_ro = normalize_text_for_scoring(text_ro)
        self.assertEqual(norm_ro, "ședință medicală pacientul are febră")

        text_ru = "Пациент, гемодинамически нестабилен!"
        norm_ru = normalize_text_for_scoring(text_ru)
        self.assertEqual(norm_ru, "пациент гемодинамически нестабилен")

    def test_cer_calculation(self):
        cer, s, d, i, n = compute_cer("Medpark", "Metpark")
        # 1 substitution out of 7 characters
        self.assertEqual((s, d, i), (1, 0, 0))
        self.assertAlmostEqual(cer, 1 / 7, places=3)

    def test_manifest_schema_validation(self):
        # 1. Non-monotonic timestamps rejected
        with self.assertRaises(ValueError):
            RecordingEntry(
                recording_id="rec_err",
                checksum_sha256="0123456789abcdef0123456789abcdef",
                duration_seconds=10.0,
                segments=[
                    GoldSegment(segment_id="s1", start=5.0, end=7.0, verbatim_text="A"),
                    GoldSegment(segment_id="s2", start=3.0, end=4.0, verbatim_text="B"),
                ],
            )

        # 2. Duplicate checksums across splits rejected
        with self.assertRaises(ValueError):
            ASRManifest(
                recordings=[
                    RecordingEntry(
                        recording_id="r1",
                        checksum_sha256="same_checksum_1234567890",
                        duration_seconds=10.0,
                        split="train",
                        segments=[],
                    ),
                    RecordingEntry(
                        recording_id="r2",
                        checksum_sha256="same_checksum_1234567890",
                        duration_seconds=10.0,
                        split="test",
                        segments=[],
                    ),
                ]
            )

    def test_synthetic_fixtures_evaluation(self):
        with open(_FIXTURE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        manifest = ASRManifest.model_validate(data["gold_manifest"])
        hyp_good = ASRHypothesisSet.model_validate(data["hypotheses_good"])
        hyp_bad = ASRHypothesisSet.model_validate(data["hypotheses_bad_critical"])

        # Good model
        report_good = score_asr(manifest, hyp_good)
        self.assertEqual(report_good["wer"], 0.0)
        self.assertEqual(report_good["cer"], 0.0)
        self.assertEqual(report_good["critical_fact_errors"], 0)
        self.assertEqual(report_good["silence_insertions"], 0)
        self.assertEqual(report_good["clinical_entity_recall"], 1.0)

        # Bad model with critical errors
        report_bad = score_asr(manifest, hyp_bad)
        self.assertGreater(report_bad["wer"], 0.0)
        # Should flag negation reversal and dosage corruption
        self.assertGreaterEqual(report_bad["critical_fact_errors"], 2)
        # Should detect silence insertion
        self.assertGreater(report_bad["silence_insertions"], 0)

    def test_bootstrap_determinism(self):
        recording_stats = [
            {"recording_id": "r1", "substitutions": 2, "deletions": 1, "insertions": 0, "ref_words": 50},
            {"recording_id": "r2", "substitutions": 5, "deletions": 0, "insertions": 2, "ref_words": 100},
            {"recording_id": "r3", "substitutions": 0, "deletions": 0, "insertions": 0, "ref_words": 30},
        ]
        mean1, low1, high1 = compute_recording_bootstrap_ci(recording_stats, n_resamples=500, seed=42)
        mean2, low2, high2 = compute_recording_bootstrap_ci(recording_stats, n_resamples=500, seed=42)

        self.assertEqual(mean1, mean2)
        self.assertEqual(low1, low2)
        self.assertEqual(high1, high2)
        self.assertLessEqual(low1, mean1)
        self.assertGreaterEqual(high1, mean1)


if __name__ == "__main__":
    unittest.main()
