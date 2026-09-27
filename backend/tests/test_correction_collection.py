"""
Unit and regression tests for durable correction history and collection (Task 3).
Verifies:
- Stale revision returns 409 without writes
- Repeated request_id is idempotent; same-ID/different-body returns 409 conflict
- Multiple successive edits retain full immutable history and increment revision
- No-op saves do not bump revision or record events
- Deletion text records event but is marked ineligible for training
- Collector failure preserves transcript save and can be reconciled later
- ASR_LEARNING_ENABLED controls catalog projection
- Distinct candidate counting
"""

import os
import sys
import unittest
from unittest.mock import patch
import uuid

# Ensure backend is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.models.meeting import Meeting, MeetingType, WorkflowMode
from app.models.transcript import Transcript, TranscriptSegment
from app.models.adaptation import CorrectionEvent, EditKind
from app.api.v1.endpoints.transcript import SegmentUpdateRequest, update_transcript_segment
from app.services.learning.correction_collector import collect_event, reconcile_meeting, reconcile_all
from app.services.learning.store import adaptation_store
from app.storage.repository import repository
from fastapi import HTTPException


class TestCorrectionCollection(unittest.TestCase):

    def setUp(self):
        # Set up a clean test meeting and transcript
        self.meeting_id = f"t_{self._testMethodName[:35]}_{uuid.uuid4().hex[:8]}"
        self.meeting = Meeting(
            id=self.meeting_id,
            title="Medical Staff Meeting",
            meeting_type=MeetingType.MEDICAL,
            workflow_mode=WorkflowMode.SUPERVISED,
        )
        repository.save_meeting(self.meeting)

        self.seg1 = TranscriptSegment(
            id="seg-1",
            start=0.0,
            end=3.5,
            speaker="Speaker 1",
            raw_text="buna dimineata tuturor",
            normalized_text="Bună dimineața tuturor",
            raw_text_origin="decoder",
            language="ro",
        )
        self.seg2 = TranscriptSegment(
            id="seg-2",
            start=3.5,
            end=6.0,
            speaker="Speaker 2",
            raw_text="pacientul a primit 10 miligrame",
            normalized_text="pacientul a primit 10 mg",
            raw_text_origin="decoder",
            language="ro",
        )
        self.transcript = Transcript(
            meeting_id=self.meeting_id,
            revision=1,
            segments=[self.seg1, self.seg2],
        )
        self.transcript.compute_stats()
        repository.save_transcript(self.transcript)

    def test_stale_revision_returns_409_without_writes(self):
        """Passing expected_revision that does not match transcript.revision raises 409 without writes."""
        payload = SegmentUpdateRequest(
            corrected_text="Bună dimineața colegi",
            expected_revision=99,  # Stale revision
        )
        with self.assertRaises(HTTPException) as cm:
            update_transcript_segment(self.meeting_id, "seg-1", payload)

        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("Conflict: expected transcript revision 99", cm.exception.detail)

        # Confirm nothing on disk changed
        saved = repository.get_transcript(self.meeting_id)
        self.assertEqual(saved.revision, 1)
        self.assertIsNone(saved.segments[0].corrected_text)
        self.assertEqual(len(saved.correction_events), 0)

    def test_repeated_request_id_idempotency(self):
        """Repeated request with same request_id and identical body is idempotent without duplicate events."""
        payload1 = SegmentUpdateRequest(
            corrected_text="Bună dimineața colegi",
            request_id="req-unique-123",
            reviewer_label="Dr. Ceban",
        )
        res1 = update_transcript_segment(self.meeting_id, "seg-1", payload1)
        self.assertEqual(res1.corrected_text, "Bună dimineața colegi")

        saved1 = repository.get_transcript(self.meeting_id)
        self.assertEqual(saved1.revision, 2)
        self.assertEqual(len(saved1.correction_events), 1)

        # Resend exact same request
        payload2 = SegmentUpdateRequest(
            corrected_text="Bună dimineața colegi",
            request_id="req-unique-123",
            reviewer_label="Dr. Ceban",
        )
        res2 = update_transcript_segment(self.meeting_id, "seg-1", payload2)
        self.assertEqual(res2.corrected_text, "Bună dimineața colegi")

        saved2 = repository.get_transcript(self.meeting_id)
        self.assertEqual(saved2.revision, 2)  # Revision did NOT bump
        self.assertEqual(len(saved2.correction_events), 1)  # No duplicate event

    def test_same_request_id_different_body_conflict(self):
        """Reusing request_id with different body raises 409 Conflict without writing."""
        payload1 = SegmentUpdateRequest(
            corrected_text="Prima versiune",
            request_id="req-conflict-456",
        )
        update_transcript_segment(self.meeting_id, "seg-1", payload1)

        payload2 = SegmentUpdateRequest(
            corrected_text="A doua versiune diferita",
            request_id="req-conflict-456",
        )
        with self.assertRaises(HTTPException) as cm:
            update_transcript_segment(self.meeting_id, "seg-1", payload2)

        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("has already been processed with different parameters", cm.exception.detail)

        # Saved text remains 'Prima versiune'
        saved = repository.get_transcript(self.meeting_id)
        self.assertEqual(saved.segments[0].corrected_text, "Prima versiune")
        self.assertEqual(len(saved.correction_events), 1)

    def test_multiple_successive_edits_retain_history(self):
        """Successive edits increment revision and append to correction_events preserving previous_text."""
        # Edit 1
        p1 = SegmentUpdateRequest(corrected_text="Edit One", reviewer_label="Reviewer A")
        update_transcript_segment(self.meeting_id, "seg-1", p1)

        # Edit 2
        p2 = SegmentUpdateRequest(corrected_text="Edit Two", reviewer_label="Reviewer B")
        update_transcript_segment(self.meeting_id, "seg-1", p2)

        # Edit 3 on seg-2
        p3 = SegmentUpdateRequest(corrected_text="Edit Three", reviewer_label="Reviewer A")
        update_transcript_segment(self.meeting_id, "seg-2", p3)

        saved = repository.get_transcript(self.meeting_id)
        self.assertEqual(saved.revision, 4)
        self.assertEqual(len(saved.correction_events), 3)

        # Verify event history
        ev1 = saved.correction_events[0]
        self.assertEqual(ev1.segment_id, "seg-1")
        self.assertEqual(ev1.previous_text, "Bună dimineața tuturor")
        self.assertEqual(ev1.new_text, "Edit One")
        self.assertEqual(ev1.transcript_revision, 2)

        ev2 = saved.correction_events[1]
        self.assertEqual(ev2.segment_id, "seg-1")
        self.assertEqual(ev2.previous_text, "Edit One")
        self.assertEqual(ev2.new_text, "Edit Two")
        self.assertEqual(ev2.transcript_revision, 3)

        ev3 = saved.correction_events[2]
        self.assertEqual(ev3.segment_id, "seg-2")
        self.assertEqual(ev3.previous_text, "pacientul a primit 10 mg")
        self.assertEqual(ev3.new_text, "Edit Three")
        self.assertEqual(ev3.transcript_revision, 4)

    def test_no_op_saves_do_not_bump_revision_or_events(self):
        """Saving with identical text and speaker is a no-op that does not bump revision or append events."""
        p_noop = SegmentUpdateRequest(
            corrected_text="Bună dimineața tuturor",  # Exactly matches display_text
        )
        res = update_transcript_segment(self.meeting_id, "seg-1", p_noop)
        self.assertEqual(res.display_text, "Bună dimineața tuturor")

        saved = repository.get_transcript(self.meeting_id)
        self.assertEqual(saved.revision, 1)
        self.assertEqual(len(saved.correction_events), 0)

    def test_deletion_text_records_event_and_is_ineligible_for_training(self):
        """Intentional empty deletion sets empty display_text and is marked ineligible for training."""
        p_del = SegmentUpdateRequest(
            corrected_text="",
            edit_kind="redaction",
        )
        res = update_transcript_segment(self.meeting_id, "seg-1", p_del)
        self.assertEqual(res.corrected_text, "")
        self.assertEqual(res.display_text, "")

        saved = repository.get_transcript(self.meeting_id)
        self.assertEqual(saved.revision, 2)
        self.assertEqual(len(saved.correction_events), 1)
        ev = saved.correction_events[0]
        self.assertEqual(ev.new_text, "")

        # Verify collection marks it ineligible
        res_collect = collect_event(ev.id, self.meeting_id, transcript=saved)
        self.assertEqual(res_collect.status, "ineligible")

    def test_collector_failure_preserves_transcript_and_reconciles_later(self):
        """If SQLite collection fails, the transcript write still succeeds, and reconcile picks it up."""
        with patch("app.api.v1.endpoints.transcript.collect_event", side_effect=RuntimeError("SQLite disk full")):
            p = SegmentUpdateRequest(corrected_text="Durable text survives failure")
            res = update_transcript_segment(self.meeting_id, "seg-1", p)
            self.assertEqual(res.corrected_text, "Durable text survives failure")

        # The transcript was durably saved regardless of collection failure
        saved = repository.get_transcript(self.meeting_id)
        self.assertEqual(saved.revision, 2)
        self.assertEqual(len(saved.correction_events), 1)
        ev = saved.correction_events[0]
        self.assertEqual(ev.new_text, "Durable text survives failure")

        # Now test reconciliation with learning enabled
        with patch.object(settings, "ASR_LEARNING_ENABLED", True):
            rec_result = reconcile_meeting(self.meeting_id)
            self.assertEqual(rec_result["collected"], 1)

            # Confirm event is in SQLite catalog
            record = adaptation_store.get_event(ev.id)
            self.assertIsNotNone(record)
            self.assertEqual(record["new_text"], "Durable text survives failure")
            self.assertEqual(record["collection_status"], "collected")

    def test_learning_disabled_by_default(self):
        """With ASR_LEARNING_ENABLED=False, collect_event reports ineligible (learning_disabled)."""
        ev = CorrectionEvent(
            meeting_id=self.meeting_id,
            segment_id="seg-1",
            transcript_revision=2,
            previous_text="before",
            new_text="after",
        )
        self.transcript.correction_events.append(ev)
        repository.save_transcript(self.transcript)

        with patch.object(settings, "ASR_LEARNING_ENABLED", False):
            result = collect_event(ev.id, self.meeting_id)
            self.assertEqual(result.status, "ineligible")
            self.assertEqual(result.reason, "learning_disabled")

    def test_distinct_accepted_event_counts(self):
        """Candidate counts reflect distinct accepted events, meetings, and speakers."""
        # Insert a couple verified events and an unverified one
        ev1 = CorrectionEvent(
            meeting_id="m1",
            segment_id="s1",
            transcript_revision=2,
            previous_text="a",
            new_text="b",
            verification_status="verified",
            verified_against_audio=True,
            training_reuse_allowed=True,
        )
        ev2 = CorrectionEvent(
            meeting_id="m1",
            segment_id="s2",
            transcript_revision=3,
            previous_text="c",
            new_text="d",
            verification_status="verified",
            verified_against_audio=True,
            training_reuse_allowed=True,
        )
        ev_unverified = CorrectionEvent(
            meeting_id="m2",
            segment_id="s3",
            transcript_revision=2,
            previous_text="e",
            new_text="f",
            verification_status="unverified",
        )

        adaptation_store.upsert_event(ev1, metadata={"speaker_cluster": "Speaker 1"})
        adaptation_store.upsert_event(ev2, metadata={"speaker_cluster": "Speaker 1"})  # Same meeting, same speaker
        adaptation_store.upsert_event(ev_unverified, metadata={"speaker_cluster": "Speaker 2"})

        counts = adaptation_store.count_distinct_accepted_events()
        self.assertEqual(counts["distinct_verified_events"], 2)
        self.assertEqual(counts["distinct_verified_meetings"], 1)
        self.assertEqual(counts["distinct_verified_speakers"], 1)
        self.assertGreaterEqual(counts["unverified_events"], 1)


if __name__ == "__main__":
    unittest.main()
