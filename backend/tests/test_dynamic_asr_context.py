"""
Tests for Dynamic Meeting ASR Context Biasing (Task 5)
Verifies deterministic ASRContext generation, prioritization, transliteration,
hotword budgeting, and configuration isolation.
"""

import unittest
from unittest.mock import MagicMock

from app.core.config import settings
from app.models.meeting import Attendee, MeetingBase
from app.services.asr.dynamic_context import (
    ASRContext,
    ContextTerm,
    build_context,
    count_tokens,
    cyrillic_to_latin,
    latin_to_cyrillic,
)


class TestDynamicASRContext(unittest.TestCase):
    def test_context_built_from_cardiology_meeting(self):
        """Test context built from meeting with 3 attendees, department='Cardiologie', title='Sedinta clinica'."""
        attendees = [
            Attendee(name="Dr. Elena Ceban", role="Medic Primar", email="ceban@medpark.md", department="Cardiologie"),
            Attendee(name="Dr. Mihail Ivanov", role="Chirurg Cardiovascular", email="ivanov@medpark.md", department="Cardiologie"),
            Attendee(name="Dr. Andrei Popescu", role="Medic Rezident", email="popescu@medpark.md", department="Cardiologie"),
        ]
        meeting = MeetingBase(
            title="Sedinta clinica",
            asr_department="Cardiologie",
            attendees=attendees,
            agenda="Discutare cazuri clinice si stentare coronariana",
        )

        context = build_context(meeting, enabled=True)

        self.assertIsInstance(context, ASRContext)
        self.assertGreater(len(context.terms), 0)
        self.assertGreater(len(context.hotwords), 0)
        self.assertTrue(bool(context.prompt_seed))

        # Check attendee family names are present with high weight
        term_texts = {t.text for t in context.terms}
        self.assertIn("Ceban", term_texts)
        self.assertIn("Ivanov", term_texts)
        self.assertIn("Popescu", term_texts)

        # Check department terms are present
        self.assertTrue(any(t in term_texts for t in ["stent", "angioplastie", "coronarografie"]))

        # Check agenda/title terms (stopwords filtered out)
        self.assertIn("clinica", term_texts)

        # Check hotword and prompt_seed budgets
        self.assertLessEqual(len(context.hotwords), 40)
        self.assertLessEqual(count_tokens(context.prompt_seed), 80)

    def test_deterministic_output(self):
        """Verify deterministic output: same input produces byte-for-byte identical context."""
        attendees = [
            Attendee(name="Dr. Elena Ceban", email="ceban@medpark.md"),
            Attendee(name="Dr. Victor Rusu", email="rusu@medpark.md"),
        ]
        meeting = MeetingBase(
            title="Revizuire Protocol Chirurgical",
            asr_department="Chirurgie",
            attendees=attendees,
            agenda="Hemostaza si sutura laparoscopica",
        )

        first_context = build_context(meeting, enabled=True)
        for _ in range(5):
            repeated_context = build_context(meeting, enabled=True)
            self.assertEqual(first_context.terms, repeated_context.terms)
            self.assertEqual(first_context.prompt_seed, repeated_context.prompt_seed)
            self.assertEqual(first_context.hotwords, repeated_context.hotwords)

    def test_budgeting_with_fifty_attendees(self):
        """Verify budgeting: 50 attendees truncates to budget limit gracefully without throwing."""
        attendees = [
            Attendee(name=f"Dr. Doctor{i:02d} FamilyName{i:02d}", email=f"doc{i}@medpark.md")
            for i in range(50)
        ]
        meeting = MeetingBase(
            title="Adunare Generala Spital",
            asr_department="Cardiologie",
            attendees=attendees,
            agenda="Sedinta anuala de raportare si audit",
        )

        context = build_context(meeting, enabled=True, max_hotwords=40, max_tokens=80)

        # Must not throw and must strictly respect limits
        self.assertLessEqual(len(context.hotwords), 40)
        self.assertLessEqual(count_tokens(context.prompt_seed), 80)
        # All hotwords must be non-empty strings
        for hw in context.hotwords:
            self.assertTrue(len(hw) > 0)

    def test_attendee_transliteration_and_preservation(self):
        """Verify attendee names are properly transliterated/preserved (e.g. Russian attendee Cyrillic + Latin)."""
        # Case A: Cyrillic input
        cyr_attendee = Attendee(name="Др. Михаил Иванов", email="ivanov@medpark.md")
        meeting_cyr = MeetingBase(
            title="Consiliu Medical",
            attendees=[cyr_attendee],
        )
        context_cyr = build_context(meeting_cyr, enabled=True)
        terms_cyr = {t.text for t in context_cyr.terms}

        self.assertIn("Иванов", terms_cyr)
        self.assertIn("Ivanov", terms_cyr)

        # Case B: Latin Russian surname
        lat_attendee = Attendee(name="Dr. Mikhail Ivanov", email="ivanov@medpark.md", primary_language="ru")
        meeting_lat = MeetingBase(
            title="Consiliu Medical",
            attendees=[lat_attendee],
        )
        context_lat = build_context(meeting_lat, enabled=True)
        terms_lat = {t.text for t in context_lat.terms}

        self.assertIn("Ivanov", terms_lat)
        self.assertIn("Иванов", terms_lat)

    def test_empty_meeting_produces_empty_context(self):
        """Verify empty meeting produces empty context, never None, never throws."""
        empty_meeting = MeetingBase(
            title="   ",
            attendees=[],
            agenda="",
        )
        context = build_context(empty_meeting, enabled=True)

        self.assertIsInstance(context, ASRContext)
        self.assertEqual(context.terms, ())
        self.assertEqual(context.prompt_seed, "")
        self.assertEqual(context.hotwords, ())

    def test_disabled_setting_returns_empty_context(self):
        """Verify disabled setting returns empty context."""
        meeting = MeetingBase(
            title="Sedinta de Urgenta",
            asr_department="Cardiologie",
            attendees=[Attendee(name="Dr. Elena Ceban", email="ceban@medpark.md")],
        )

        # When enabled=False explicitly
        context_explicit_off = build_context(meeting, enabled=False)
        self.assertEqual(context_explicit_off, ASRContext())

        # When default config has ASR_DYNAMIC_CONTEXT_ENABLED=False
        original_setting = settings.ASR_DYNAMIC_CONTEXT_ENABLED
        try:
            settings.ASR_DYNAMIC_CONTEXT_ENABLED = False
            context_default_off = build_context(meeting, enabled=None)
            self.assertEqual(context_default_off, ASRContext())
        finally:
            settings.ASR_DYNAMIC_CONTEXT_ENABLED = original_setting


if __name__ == "__main__":
    unittest.main()
