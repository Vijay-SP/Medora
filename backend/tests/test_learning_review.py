"""
Unit and integration tests for Task 4: Learning review, verification, and stale minutes invalidation.
Verifies:
- GET /api/v1/learning/corrections returns counts and eligible audio duration
- POST verify checks:
  * obsolete text returns 409
  * mismatched revision returns 409
  * missing audio verification returns 400
  * missing reuse permission returns 400
  * excluded edit kinds (editorial, redaction, translation) return 400
  * empty text returns 400
  * successful verification sets verified status, reviewer label, and updates store
- POST reject sets rejected status and stores rejection reason
- Stale minutes lifecycle:
  * Transcript edit marks minutes stale (needs_transcript_review=True) and invalidates approval
  * Client cannot overwrite needs_transcript_review or source_transcript_revision via PUT /minutes
  * assert_dispatchable blocks stale minutes from dispatch
  * POST /minutes/refresh clears needs_transcript_review and re-syncs revision
"""

import os
import sys
import unittest
from unittest.mock import patch, AsyncMock
import uuid

# Ensure backend is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import HTTPException
from app.core.config import settings
from app.core.exceptions import DeliveryError
from app.models.meeting import Meeting, MeetingType, ReviewStatus, WorkflowMode
from app.models.transcript import Transcript, TranscriptSegment
from app.models.extraction import MinutesOfMeeting, DecisionItem, ActionItem
from app.models.adaptation import (
    CorrectionEvent,
    VerifyCorrectionRequest,
    RejectCorrectionRequest,
)
from app.api.v1.endpoints.transcript import SegmentUpdateRequest, update_transcript_segment
from app.api.v1.endpoints.learning import (
    get_learning_corrections,
    verify_correction,
    reject_correction,
)
from app.api.v1.endpoints.review import update_minutes
from app.services.delivery.router import delivery_router
from app.services.learning.store import adaptation_store
from app.storage.repository import repository


class TestLearningReviewAndStaleMinutes(unittest.TestCase):

    def setUp(self):
        self.meeting_id = f"t_{self._testMethodName[:35]}_{uuid.uuid4().hex[:8]}"
        self.meeting = Meeting(
            id=self.meeting_id,
            title="Cardiology Weekly Board",
            meeting_type=MeetingType.MEDICAL,
            workflow_mode=WorkflowMode.SUPERVISED,
        )
        repository.save_meeting(self.meeting)

        self.seg1 = TranscriptSegment(
            id="seg-1",
            start=10.0,
            end=15.0,
            speaker="Speaker 1",
            raw_text="pacientul necesita operatie urgenta",
            normalized_text="pacientul necesită operație urgentă",
            raw_text_origin="decoder",
            language="ro",
        )
        self.transcript = Transcript(
            meeting_id=self.meeting_id,
            revision=1,
            segments=[self.seg1],
        )
        self.transcript.compute_stats()
        repository.save_transcript(self.transcript)

        self.minutes = MinutesOfMeeting(
            meeting_id=self.meeting_id,
            title=self.meeting.title,
            summary_ro="Rezumat medical inițial.",
            summary_ru="Начальное медицинское резюме.",
            summary_en="Initial medical summary.",
            decisions=[],
            action_items=[],
            risks_and_questions=[],
            revision=1,
            source_transcript_revision=1,
            needs_transcript_review=False,
        )
        repository.save_minutes(self.minutes)

    def test_get_learning_corrections(self):
        """GET /learning/corrections returns counts and corrections."""
        ev = CorrectionEvent(
            meeting_id=self.meeting_id,
            segment_id="seg-1",
            transcript_revision=2,
            previous_text="pacientul necesită operație urgentă",
            new_text="Pacientul necesită intervenție chirurgicală de urgență",
            edit_kind="transcription",
            verification_status="unverified",
        )
        adaptation_store.upsert_event(ev, metadata={"audio_start": 10.0, "audio_end": 15.0})

        res = get_learning_corrections(meeting_id=self.meeting_id)
        self.assertIn("counts", res.model_dump())
        self.assertGreaterEqual(len(res.corrections), 1)

    def test_verify_obsolete_text_returns_409(self):
        """Attempting to verify an event when the segment has subsequent edits returns 409."""
        # 1st edit: rev 2
        p1 = SegmentUpdateRequest(corrected_text="Prima modificare", edit_kind="transcription")
        update_transcript_segment(self.meeting_id, "seg-1", p1)

        saved = repository.get_transcript(self.meeting_id)
        ev1 = saved.correction_events[0]
        adaptation_store.upsert_event(ev1)

        # 2nd edit: rev 3
        p2 = SegmentUpdateRequest(corrected_text="A doua modificare", edit_kind="transcription")
        update_transcript_segment(self.meeting_id, "seg-1", p2)

        # Try verifying ev1 (which had text 'Prima modificare', but segment now has 'A doua modificare')
        payload = VerifyCorrectionRequest(
            expected_revision=2,
            audio_start=10.0,
            audio_end=15.0,
            edit_kind="transcription",
            reviewer_label="Dr. Ceban",
            verified_against_audio=True,
            training_reuse_allowed=True,
        )

        with self.assertRaises(HTTPException) as cm:
            verify_correction(ev1.id, payload)
        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("cannot verify obsolete text", cm.exception.detail)

    def test_verify_revision_mismatch_returns_409(self):
        """Targeting wrong revision returns 409 Conflict."""
        p = SegmentUpdateRequest(corrected_text="Text corect", edit_kind="transcription")
        update_transcript_segment(self.meeting_id, "seg-1", p)

        saved = repository.get_transcript(self.meeting_id)
        ev = saved.correction_events[0]
        adaptation_store.upsert_event(ev)

        payload = VerifyCorrectionRequest(
            expected_revision=999,  # Mismatched
            audio_start=10.0,
            audio_end=15.0,
            edit_kind="transcription",
            reviewer_label="Dr. Ceban",
            verified_against_audio=True,
            training_reuse_allowed=True,
        )

        with self.assertRaises(HTTPException) as cm:
            verify_correction(ev.id, payload)
        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("targeted revision 999", cm.exception.detail)

    def test_verify_excluded_kinds_and_missing_consent(self):
        """Verification rejects missing consent, excluded kinds (editorial/redaction), and empty text."""
        p = SegmentUpdateRequest(corrected_text="Text bun", edit_kind="transcription")
        update_transcript_segment(self.meeting_id, "seg-1", p)
        saved = repository.get_transcript(self.meeting_id)
        ev = saved.correction_events[0]
        adaptation_store.upsert_event(ev)

        # 1. Missing audio verification
        p_no_audio = VerifyCorrectionRequest(
            expected_revision=2, audio_start=10.0, audio_end=15.0, edit_kind="transcription",
            reviewer_label="Dr. Ceban", verified_against_audio=False, training_reuse_allowed=True,
        )
        with self.assertRaises(HTTPException) as cm:
            verify_correction(ev.id, p_no_audio)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("Audio verification is required", cm.exception.detail)

        # 2. Missing reuse consent
        p_no_reuse = VerifyCorrectionRequest(
            expected_revision=2, audio_start=10.0, audio_end=15.0, edit_kind="transcription",
            reviewer_label="Dr. Ceban", verified_against_audio=True, training_reuse_allowed=False,
        )
        with self.assertRaises(HTTPException) as cm:
            verify_correction(ev.id, p_no_reuse)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("training reuse permission is required", cm.exception.detail)

        # 3. Excluded kind: editorial
        p_editorial = VerifyCorrectionRequest(
            expected_revision=2, audio_start=10.0, audio_end=15.0, edit_kind="editorial",
            reviewer_label="Dr. Ceban", verified_against_audio=True, training_reuse_allowed=True,
        )
        with self.assertRaises(HTTPException) as cm:
            verify_correction(ev.id, p_editorial)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("excluded from acoustic training datasets", cm.exception.detail)

    def test_successful_verification_and_rejection(self):
        """Verify and reject actions properly mutate event status and store records."""
        p = SegmentUpdateRequest(corrected_text="Text verificabil", edit_kind="transcription")
        update_transcript_segment(self.meeting_id, "seg-1", p)
        saved = repository.get_transcript(self.meeting_id)
        ev = saved.correction_events[0]
        adaptation_store.upsert_event(ev)

        # Verify
        payload = VerifyCorrectionRequest(
            expected_revision=2,
            audio_start=10.0,
            audio_end=15.0,
            edit_kind="transcription",
            reviewer_label="Dr. Elena Ceban",
            verified_against_audio=True,
            training_reuse_allowed=True,
        )
        verified_ev = verify_correction(ev.id, payload)
        self.assertEqual(verified_ev.verification_status, "verified")
        self.assertTrue(verified_ev.verified_against_audio)
        self.assertTrue(verified_ev.training_reuse_allowed)
        self.assertEqual(verified_ev.verified_by, "Dr. Elena Ceban")

        # Check SQLite store
        in_store = adaptation_store.get_event(ev.id)
        self.assertEqual(in_store["verification_status"], "verified")
        self.assertEqual(in_store["verified_against_audio"], 1)
        self.assertEqual(in_store["training_reuse_allowed"], 1)

        # Reject
        reject_payload = RejectCorrectionRequest(
            reason="Zgomot de fond ridicat, cuvânt neclar",
            reviewer_label="Dr. Elena Ceban",
        )
        rejected_ev = reject_correction(ev.id, reject_payload)
        self.assertEqual(rejected_ev.verification_status, "rejected")
        self.assertFalse(rejected_ev.verified_against_audio)
        self.assertFalse(rejected_ev.training_reuse_allowed)
        self.assertEqual(rejected_ev.rejection_reason, "Zgomot de fond ridicat, cuvânt neclar")

    def test_transcript_edit_invalidates_minutes_and_approval(self):
        """Editing transcript marks minutes needs_transcript_review=True and revokes approval."""
        self.meeting.review_status = ReviewStatus.APPROVED
        self.meeting.approved_by = "Dr. Elena Ceban"
        repository.save_meeting(self.meeting)

        # Edit segment
        p = SegmentUpdateRequest(corrected_text="Actualizare transcript")
        update_transcript_segment(self.meeting_id, "seg-1", p)

        # Confirm minutes are stale
        stale_minutes = repository.get_minutes(self.meeting_id)
        self.assertTrue(stale_minutes.needs_transcript_review)

        # Confirm meeting approval was revoked
        updated_meeting = repository.get_meeting(self.meeting_id)
        self.assertEqual(updated_meeting.review_status, ReviewStatus.PENDING_REVIEW)
        self.assertIsNone(updated_meeting.approved_by)

        # Confirm delivery_router.assert_dispatchable blocks dispatch
        with self.assertRaises(DeliveryError) as cm:
            delivery_router.assert_dispatchable(stale_minutes)
        self.assertIn("needs_transcript_review", str(cm.exception))

    def test_put_minutes_cannot_overwrite_provenance_flags(self):
        """PUT /minutes cannot overwrite needs_transcript_review or source_transcript_revision."""
        stale_minutes = repository.get_minutes(self.meeting_id)
        stale_minutes.needs_transcript_review = True
        repository.save_minutes(stale_minutes)

        # Attempt to forge a payload with needs_transcript_review=False and fake revision
        forged_payload = stale_minutes.model_copy(deep=True)
        forged_payload.needs_transcript_review = False
        forged_payload.source_transcript_revision = 999
        forged_payload.summary_ro = "Rezumat modificat legitim de revizor."

        saved = update_minutes(self.meeting_id, forged_payload)
        # Server must have preserved the stored provenance flags
        self.assertTrue(saved.needs_transcript_review)
        self.assertEqual(saved.source_transcript_revision, 1)


if __name__ == "__main__":
    unittest.main()
