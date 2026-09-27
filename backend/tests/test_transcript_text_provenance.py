"""
Medpark Meeting Intelligence System - Transcript Text Provenance & Evidence Preservation Tests
Verifies the contracts defined in Milestone A (Task 1):
1. raw_text preserves verbatim decoder text.
2. normalized_text captures safe lexicon/dialect normalizations.
3. display_text precedence: corrected_text > normalized_text > raw_text.
4. Intentional empty string deletion (corrected_text="") yields display_text="" and does NOT resurrect raw_text.
5. Legacy transcripts default to raw_text_origin="legacy_unknown".
6. New decoder decodes stamp raw_text_origin="decoder".
7. Serialization round-trips cleanly without data loss.
"""

import json
import unittest

from app.models.transcript import Correction, Transcript, TranscriptSegment


class TestTranscriptTextProvenance(unittest.TestCase):
    def test_legacy_segment_defaults_to_legacy_unknown(self):
        legacy_data = {
            "id": "seg001",
            "start": 0.0,
            "end": 2.5,
            "speaker": "Speaker 1",
            "raw_text": "Pacientul este stabil",
            "language": "ro",
        }
        seg = TranscriptSegment.model_validate(legacy_data)
        self.assertEqual(seg.raw_text_origin, "legacy_unknown")
        self.assertIsNone(seg.normalized_text)
        self.assertIsNone(seg.normalization_version)
        self.assertEqual(seg.display_text, "Pacientul este stabil")

    def test_decoder_origin_and_normalized_text(self):
        seg = TranscriptSegment(
            id="seg002",
            start=1.0,
            end=3.5,
            speaker="Speaker 1",
            raw_text="Pacientul a fost la Med Park",
            normalized_text="Pacientul a fost la Medpark",
            raw_text_origin="decoder",
            normalization_version="lexicon_v1",
            language="ro",
            corrections=[Correction(was="Med Park", now="Medpark", score=1.0, rule_id="lex_medpark", stage="lexicon")],
        )
        self.assertEqual(seg.raw_text, "Pacientul a fost la Med Park")
        self.assertEqual(seg.normalized_text, "Pacientul a fost la Medpark")
        self.assertEqual(seg.raw_text_origin, "decoder")
        self.assertEqual(seg.normalization_version, "lexicon_v1")
        self.assertEqual(seg.display_text, "Pacientul a fost la Medpark")
        self.assertEqual(len(seg.corrections), 1)
        self.assertEqual(seg.corrections[0].rule_id, "lex_medpark")

    def test_display_text_precedence_and_empty_string_deletion(self):
        # 1. raw only
        seg_raw = TranscriptSegment(
            start=0.0,
            end=1.0,
            raw_text="Hello world",
        )
        self.assertEqual(seg_raw.display_text, "Hello world")

        # 2. normalized overrides raw
        seg_norm = TranscriptSegment(
            start=0.0,
            end=1.0,
            raw_text="Hello world",
            normalized_text="Hello World!",
        )
        self.assertEqual(seg_norm.display_text, "Hello World!")

        # 3. reviewer correction overrides normalized and raw
        seg_corrected = TranscriptSegment(
            start=0.0,
            end=1.0,
            raw_text="Hello world",
            normalized_text="Hello World!",
            corrected_text="Hi there",
        )
        self.assertEqual(seg_corrected.display_text, "Hi there")

        # 4. Critical contract: intentional deletion with empty string MUST NOT resurrect raw_text
        seg_deleted = TranscriptSegment(
            start=0.0,
            end=1.0,
            raw_text="Hello world",
            normalized_text="Hello World!",
            corrected_text="",
        )
        self.assertEqual(seg_deleted.display_text, "")
        self.assertEqual(seg_deleted.raw_text, "Hello world")

    def test_speaker_state_remains_unchanged_by_text_provenance(self):
        seg = TranscriptSegment(
            start=0.0,
            end=2.0,
            speaker="Speaker 2",
            raw_text="Test",
            normalized_text="Test.",
            raw_text_origin="decoder",
        )
        self.assertEqual(seg.speaker, "Speaker 2")
        self.assertEqual(seg.attribution_state, "anonymous")
        self.assertIsNone(seg.confirmed_display_name)
        self.assertEqual(seg.display_speaker, "Speaker 2")

    def test_transcript_revision_and_stats(self):
        t = Transcript(
            meeting_id="meet_123",
            segments=[
                TranscriptSegment(start=0.0, end=2.0, raw_text="Unu doi trei", language="ro"),
                TranscriptSegment(start=2.0, end=4.0, raw_text="Patru cinci", language="ro", corrected_text=""),
            ],
        )
        self.assertEqual(t.revision, 1)
        t.compute_stats()
        # "Unu doi trei" = 3 words; seg 2 display_text is "" = 0 words -> total 3 words
        self.assertEqual(t.total_words, 3)
        self.assertEqual(t.duration_seconds, 4.0)

    def test_round_trip_serialization(self):
        seg = TranscriptSegment(
            id="seg_rt",
            start=0.0,
            end=3.0,
            raw_text="Verbatim decoder",
            normalized_text="Verbatim Normalized",
            raw_text_origin="decoder",
            normalization_version="lexicon_v1",
            corrected_text="Final human touch",
            corrections=[
                Correction(
                    was="decoder",
                    now="Normalized",
                    score=0.95,
                    rule_id="r1",
                    source_span=(9, 16),
                    target_span=(9, 19),
                    stage="lexicon",
                    ruleset_version="1.0.0",
                )
            ],
        )
        dumped = seg.model_dump_json()
        loaded = TranscriptSegment.model_validate_json(dumped)

        self.assertEqual(loaded.raw_text, "Verbatim decoder")
        self.assertEqual(loaded.normalized_text, "Verbatim Normalized")
        self.assertEqual(loaded.raw_text_origin, "decoder")
        self.assertEqual(loaded.normalization_version, "lexicon_v1")
        self.assertEqual(loaded.corrected_text, "Final human touch")
        self.assertEqual(loaded.display_text, "Final human touch")
        self.assertEqual(len(loaded.corrections), 1)
        c = loaded.corrections[0]
        self.assertEqual(c.rule_id, "r1")
        self.assertEqual(c.source_span, (9, 16))
        self.assertEqual(c.target_span, (9, 19))
        self.assertEqual(c.stage, "lexicon")
        self.assertEqual(c.ruleset_version, "1.0.0")


if __name__ == "__main__":
    unittest.main()
