"""
Medpark Meeting Intelligence System - Transcript & Utterances API Endpoints
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from app.core.logging import logger
from app.models.adaptation import CorrectionEvent, EditKind
from app.models.extraction import MinutesOfMeeting
from app.models.meeting import Meeting, ReviewStatus
from app.models.transcript import ANONYMOUS_SPEAKER_PATTERN, Transcript, TranscriptSegment
from app.services.documents.generator import document_generator
from app.services.learning.correction_collector import collect_event
from app.storage.file_manager import file_manager
from app.storage.repository import repository

router = APIRouter(prefix="/meetings/{meeting_id}/transcript", tags=["Transcript"])


class SegmentUpdateRequest(BaseModel):
    corrected_text: str | None = None
    # Only anonymous labels may be assigned here (422 otherwise): free-text renaming is how an
    # unconfirmed name would get laundered into the document. Names go through /speakers confirm.
    speaker: str | None = Field(None, pattern=ANONYMOUS_SPEAKER_PATTERN.pattern)
    is_flagged: bool | None = None
    expected_revision: int | None = None
    request_id: str | None = None
    edit_kind: EditKind = "editorial"
    reviewer_label: str | None = None


def _cluster_for_label(transcript: Transcript, label: str, exclude_id: str) -> Optional[str]:
    """The diarization cluster the other segments carrying this anonymous label belong to (None for a new label)."""
    counts = Counter(
        seg.cluster_id for seg in transcript.segments
        if seg.id != exclude_id and seg.speaker == label and seg.cluster_id
    )
    return counts.most_common(1)[0][0] if counts else None


def _relabel_segment(transcript: Transcript, seg: TranscriptSegment, label: str) -> Optional[str]:
    """
    Moves a segment to another anonymous label. A relabel is the reviewer stating that this turn does NOT
    belong to the speaker it was attributed to, so every identity the old cluster carried is dropped: the
    confirmed snapshot (and its printable flag), a pending suggestion, and the cluster membership itself,
    which would otherwise re-apply the old cluster's name on the next confirm. The segment joins the cluster
    already carrying the target label (a later confirm of that cluster names it explicitly) or none.
    Returns the confirmed name that was removed, if any.
    """
    removed_name = seg.confirmed_display_name if seg.attribution_state in ("confirmed", "corrected") else None
    seg.speaker = label
    seg.cluster_id = _cluster_for_label(transcript, label, exclude_id=seg.id)
    seg.attribution_state = "anonymous"
    seg.speaker_id = None
    seg.confirmed_display_name = None
    seg.confirmed_by = None
    seg.confirmed_at = None
    seg.confirmed_for_revision = None
    seg.suggestion = None
    seg.suggested_identity = None
    seg.printable_name = False
    return removed_name


def _revert_name_in_minutes(minutes: MinutesOfMeeting, seg: TranscriptSegment, previous_label: str, removed_name: str) -> bool:
    """
    Reverses what the confirm handler wrote for this one segment: its evidence quotes become anonymous again and
    an action item owned by the removed name loses that owner if this segment was part of its evidence (the
    owner was granted only because every cited turn was printable). Free text is never touched.
    """
    changed = False
    items = list(minutes.decisions) + list(minutes.action_items) + list(minutes.risks_and_questions)
    for item in items:
        for quote in item.evidence:
            if quote.segment_id != seg.id:
                continue
            if quote.speaker != seg.speaker or quote.speaker_person_id is not None or quote.speaker_is_confirmed:
                quote.speaker = seg.speaker
                quote.speaker_person_id = None
                quote.speaker_is_confirmed = False
                changed = True
    for action in minutes.action_items:
        if action.owner_source != "confirmed_speaker" or action.owner != removed_name:
            continue
        if any(quote.segment_id == seg.id for quote in action.evidence):
            action.owner = previous_label
            action.owner_source = "speaker"
            changed = True
    return changed


def _bump_revision_if_signed_off(meeting: Meeting, minutes: MinutesOfMeeting) -> None:
    """Same rule as the /speakers confirm handler: signed-off or delivered minutes get a new revision, else redraw in place."""
    delivered_current = any(rec.revision == meeting.current_revision for rec in repository.list_deliveries(meeting.id))
    if meeting.review_status in (ReviewStatus.APPROVED, ReviewStatus.DELIVERED) or delivered_current:
        meeting.current_revision += 1
        minutes.revision = meeting.current_revision
        meeting.review_status = ReviewStatus.PENDING_REVIEW
        meeting.approved_by = None
        meeting.approved_at = None


@router.get("/", response_model=Transcript)
def get_transcript(meeting_id: str) -> Transcript:
    """Returns the complete timestamped transcript for a meeting."""
    transcript = repository.get_transcript(meeting_id)
    if not transcript:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found for this meeting")
    return transcript


@router.put("/segments/{segment_id}", response_model=TranscriptSegment)
def update_transcript_segment(meeting_id: str, segment_id: str, payload: SegmentUpdateRequest) -> TranscriptSegment:
    """
    Allows reviewers to correct transcribed words or re-assign speaker labels.

    Re-assigning the label of a confirmed/corrected turn removes its confirmed name (the reviewer just said it
    is another speaker) and reverts that name in the minutes, regenerating the documents at the current
    revision, or at a new one when the minutes were already approved or delivered.
    """
    new_event: Optional[CorrectionEvent] = None
    with repository.lock:
        transcript = repository.get_transcript(meeting_id)
        if not transcript:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found")

        target_seg = None
        for seg in transcript.segments:
            if seg.id == segment_id:
                target_seg = seg
                break

        if not target_seg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment ID not found")

        # 1. Stale revision check (conflict protection)
        if payload.expected_revision is not None and payload.expected_revision != transcript.revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Conflict: expected transcript revision {payload.expected_revision}, but current revision is {transcript.revision}"
            )

        # 2. Repeated request_id / idempotency / conflict check
        if payload.request_id:
            for event in transcript.correction_events:
                if event.request_id == payload.request_id:
                    if event.segment_id == segment_id and event.new_text == (payload.corrected_text or ""):
                        # Idempotent retry: return target_seg immediately
                        return target_seg
                    else:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Conflict: request_id '{payload.request_id}' has already been processed with different parameters"
                        )

        # 3. Detect changes
        previous_displayed_text = target_seg.display_text
        text_changed = False
        if payload.corrected_text is not None:
            if target_seg.corrected_text is not None:
                if payload.corrected_text != target_seg.corrected_text:
                    text_changed = True
            else:
                if payload.corrected_text != previous_displayed_text:
                    text_changed = True

        speaker_changed = (payload.speaker is not None and payload.speaker != target_seg.speaker)
        flag_changed = (payload.is_flagged is not None and payload.is_flagged != target_seg.is_flagged)

        # 4. No-op check: if no fields changed, do not bump revision or create events
        if not text_changed and not speaker_changed and not flag_changed:
            return target_seg

        # 5. Apply changes and record durable correction event
        if text_changed:
            new_revision = transcript.revision + 1
            new_event = CorrectionEvent(
                id=str(uuid.uuid4()),
                meeting_id=meeting_id,
                segment_id=segment_id,
                transcript_revision=new_revision,
                request_id=payload.request_id,
                edit_kind=payload.edit_kind,
                previous_text=previous_displayed_text,
                new_text=payload.corrected_text,
                raw_text=target_seg.raw_text,
                normalized_text=target_seg.normalized_text,
                raw_text_origin=target_seg.raw_text_origin,
                reviewer_label=payload.reviewer_label,
                created_at=datetime.now(timezone.utc),
            )
            target_seg.corrected_text = payload.corrected_text
            transcript.correction_events.append(new_event)
            transcript.revision = new_revision

        removed_name: Optional[str] = None
        previous_label = target_seg.speaker
        if speaker_changed:
            if not text_changed:
                transcript.revision += 1
            removed_name = _relabel_segment(transcript, target_seg, payload.speaker)

        if flag_changed:
            target_seg.is_flagged = payload.is_flagged

        transcript.compute_stats()
        repository.save_transcript(transcript)

        # Invalidate minutes and mark stale whenever transcript text or speaker changes
        if text_changed or speaker_changed:
            meeting = repository.get_meeting(meeting_id)
            minutes = repository.get_minutes(meeting_id)
            if minutes is not None:
                minutes.needs_transcript_review = True
                if meeting is not None and meeting.review_status in (ReviewStatus.APPROVED, ReviewStatus.DELIVERED):
                    meeting.review_status = ReviewStatus.PENDING_REVIEW
                    meeting.approved_by = None
                    meeting.approved_at = None
                    repository.save_meeting(meeting)
                repository.save_minutes(minutes)
                logger.warning(
                    f"Transcript of meeting {meeting_id} changed at revision {transcript.revision}; "
                    f"minutes marked stale (needs_transcript_review=True)"
                )

        if removed_name is not None:
            logger.info(
                f"Segment {segment_id} of meeting {meeting_id} relabelled {previous_label} -> {payload.speaker}; "
                f"confirmed name removed from this turn"
            )
            meeting = repository.get_meeting(meeting_id)
            minutes = repository.get_minutes(meeting_id)
            if meeting is not None and minutes is not None:
                if _revert_name_in_minutes(minutes, target_seg, previous_label, removed_name):
                    _bump_revision_if_signed_off(meeting, minutes)
                    pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=minutes.revision)
                    document_generator.generate_all(meeting, minutes, pdf_path, docx_path, transcript=transcript)
                    minutes.pdf_path = str(pdf_path)
                    minutes.docx_path = str(docx_path)
                    repository.save_minutes(minutes)
                    repository.save_meeting(meeting)
                    logger.info(f"Minutes of meeting {meeting_id} redrawn at Rev.{minutes.revision} after speaker relabel")

    # Post-save projection: durable transcript save must never depend on collection succeeding
    if new_event is not None:
        try:
            collect_event(new_event.id, meeting_id, transcript=transcript)
        except Exception as exc:
            logger.error(f"Failed to collect event {new_event.id} after transcript save: {exc}")

    return target_seg
