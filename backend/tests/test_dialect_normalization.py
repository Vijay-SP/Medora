"""
Tests for Dialect Normalization, Safety Guards, and Pattern Miner (Task 7)
"""

import json
import os
from pathlib import Path
import tempfile
import unittest

# Ensure isolation before app imports
test_root = Path(tempfile.mkdtemp(prefix="medora-dialect-test-"))
os.environ["DATA_DIR"] = str(test_root / "data")
os.environ["ADAPTATION_DIR"] = str(test_root / "adaptation")
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
import sys
sys.path.insert(0, "backend")

from app.models.adaptation import CorrectionEvent, NormalizationRule
from app.services.asr.dialect_adapter import load_rules, normalize_dialect, save_local_rule
from app.services.learning.pattern_miner import _extract_single_phrase_diff, mine_candidates
from app.services.learning.store import adaptation_store


class TestDialectNormalization(unittest.TestCase):
    def setUp(self):
        pass

    def test_safe_replacement_and_case_preservation(self):
        text = "Pacientul a fost trimis la Policlinică pentru consult."
        res = normalize_dialect(text, "ro")
        self.assertIn("Ambulatoriu", res.text)
        self.assertEqual(len(res.corrections), 1)
        self.assertEqual(res.corrections[0]["was"], "Policlinică")
        self.assertEqual(res.corrections[0]["now"], "Ambulatoriu")

    def test_negation_safety_guard_blocks_mutation(self):
        # "nu merge la policlinică" has negation "nu" right before
        text = "Pacientul nu merge la policlinică astăzi."
        res = normalize_dialect(text, "ro")
        # Text must NOT be mutated!
        self.assertEqual(res.text, text)
        self.assertEqual(len(res.corrections), 0)
        # Should be captured as suggestion with reason
        self.assertEqual(len(res.suggestions), 1)
        self.assertEqual(res.suggestions[0]["reason"], "blocked_by_adjacent_negation")

    def test_dosage_units_safety_guard_blocks_mutation(self):
        # "10 mg lekarstvo" has dosage units right before
        text = "S-a administrat 10 mg lekarstvo dimineața."
        res = normalize_dialect(text, "ro")
        # Must NOT mutate!
        self.assertEqual(res.text, text)
        self.assertEqual(len(res.corrections), 0)
        self.assertEqual(len(res.suggestions), 1)
        self.assertEqual(res.suggestions[0]["reason"], "blocked_by_dosage_or_units")

    def test_glued_digits_safety_guard(self):
        text = "Codul de trimitere este policlinica23 pentru arhivă."
        res = normalize_dialect(text, "ro")
        self.assertEqual(res.text, text)
        self.assertEqual(len(res.corrections), 0)

    def test_suggest_only_rule_does_not_mutate(self):
        text = "Medicul a dat la analiză probele de sânge."
        res = normalize_dialect(text, "ro")
        self.assertEqual(res.text, text)
        self.assertEqual(len(res.corrections), 0)
        self.assertTrue(any(s["reason"] == "suggest_only_rule" for s in res.suggestions))

    def test_longest_match_precedence_and_no_cascading(self):
        # Define test rules with overlapping and chaining variants
        custom_rules = [
            NormalizationRule(
                id="test_short",
                language="ro",
                variants=["spital vechi"],
                canonical="clinică",
                action="safe_replace",
            ),
            NormalizationRule(
                id="test_long",
                language="ro",
                variants=["spital vechi municipal"],
                canonical="Centrul Municipal Specializat",
                action="safe_replace",
            ),
            NormalizationRule(
                id="test_cascade",
                language="ro",
                variants=["Centrul Municipal Specializat"],
                canonical="SHOULD_NOT_CASCADE",
                action="safe_replace",
            ),
        ]
        text = "Transferăm pacientul la spital vechi municipal pentru evaluare."
        res = normalize_dialect(text, "ro", rules=custom_rules)
        # Longest match wins
        self.assertIn("Centrul Municipal Specializat", res.text)
        # Must not cascade to SHOULD_NOT_CASCADE
        self.assertNotIn("SHOULD_NOT_CASCADE", res.text)

    def test_rolled_back_rules_are_ignored(self):
        custom_rules = [
            NormalizationRule(
                id="test_rolled_back",
                language="ro",
                variants=["bolniță"],
                canonical="spital",
                action="safe_replace",
                approval="rolled_back",
            )
        ]
        text = "A fost internat la bolniță."
        res = normalize_dialect(text, "ro", rules=custom_rules)
        self.assertEqual(res.text, text)
        self.assertEqual(len(res.corrections), 0)

    def test_mixed_language_rules_require_validated_mixed_context(self):
        # cs_obhod_01 has language "mixed"
        text = "Urmează un obhod în secție."
        # In monolingual Romanian ("ro"), mixed rule is suggestion only
        res_ro = normalize_dialect(text, "ro")
        self.assertEqual(res_ro.text, text)
        self.assertTrue(any(s["reason"] == "unvalidated_mixed_language_span" for s in res_ro.suggestions))

        # In confirmed mixed context ("mixed"), safe replace can apply
        res_mixed = normalize_dialect(text, "mixed")
        self.assertIn("vizită medicală", res_mixed.text)
        self.assertEqual(len(res_mixed.corrections), 1)

    def test_local_rule_persistence_and_override(self):
        local_rule = NormalizationRule(
            id="local_override_01",
            language="ro",
            variants=["salvare"],
            canonical="ambulanță",
            action="safe_replace",
            approval="approved",
        )
        save_local_rule(local_rule)

        loaded = load_rules()
        self.assertTrue(any(r.id == "local_override_01" for r in loaded))

        text = "A venit cu salvare la triaj."
        res = normalize_dialect(text, "ro")
        self.assertIn("ambulanță", res.text)


class TestPatternMiner(unittest.TestCase):
    def setUp(self):
        pass

    def test_single_phrase_diff_extraction(self):
        src = "Pacientul a plecat la bolniță."
        tgt = "Pacientul a plecat la spital."
        diff = _extract_single_phrase_diff(src, tgt)
        self.assertIsNotNone(diff)
        variant, canonical, is_safe, flags = diff
        self.assertEqual(variant, "bolniță")
        self.assertEqual(canonical, "spital")
        self.assertTrue(is_safe)
        self.assertEqual(flags, [])

    def test_multi_edit_sentence_excluded(self):
        src = "Pacientul a plecat la bolniță și a luat lekarstvo."
        tgt = "Pacientul a plecat la spital și a luat medicament."
        # Two replacements in one sentence -> excluded from automated candidate mining!
        diff = _extract_single_phrase_diff(src, tgt)
        self.assertIsNone(diff)

    def test_diff_flagged_for_dosage_and_negation(self):
        src = "A luat 50 mg de lekarstvo."
        tgt = "A luat 50 mg de medicament."
        diff = _extract_single_phrase_diff(src, tgt)
        self.assertIsNotNone(diff)
        variant, canonical, is_safe, flags = diff
        self.assertFalse(is_safe)
        self.assertIn("dosage_or_units_present", flags)

    def test_mine_candidates_from_store(self):
        # Insert 2 matching correction events across 2 meetings
        ev1 = CorrectionEvent(
            meeting_id="m1",
            segment_id="s1",
            transcript_revision=2,
            previous_text="A venit de la felcer.",
            new_text="A venit de la asistent medical.",
            raw_text="A venit de la felcer.",
            reviewer_label="Dr. Popescu",
            verified_against_audio=True,
            training_reuse_allowed=True,
            verification_status="verified",
        )
        ev2 = CorrectionEvent(
            meeting_id="m2",
            segment_id="s2",
            transcript_revision=2,
            previous_text="A trimis biletul la felcer ieri.",
            new_text="A trimis biletul la asistent medical ieri.",
            raw_text="A trimis biletul la felcer ieri.",
            reviewer_label="Dr. Ionescu",
            verified_against_audio=True,
            training_reuse_allowed=True,
            verification_status="verified",
        )
        adaptation_store.upsert_event(ev1)
        adaptation_store.upsert_event(ev2)

        candidates = mine_candidates(min_occurrences=2)
        self.assertTrue(len(candidates) >= 1)
        c = next((item for item in candidates if item.detected_variant == "felcer"), None)
        self.assertIsNotNone(c)
        self.assertEqual(c.suggested_canonical, "asistent medical")
        self.assertEqual(c.occurrences_count, 2)
        self.assertEqual(c.meetings_count, 2)
        self.assertEqual(c.speakers_count, 2)


if __name__ == "__main__":
    unittest.main()
