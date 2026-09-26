"""
Medpark Meeting Intelligence System - Review Workspace & Approval Endpoints
"""

from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.models.meeting import ProcessingStatus, ReviewStatus
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryRecord, DeliveryStatus
from app.storage.repository import repository
from app.storage.file_manager import file_manager
from app.services.documents.generator import document_generator
from app.services.delivery.router import delivery_router
from app.services.delivery.smtp_service import smtp_service
from app.services.delivery.n8n_service import n8n_service
from app.core.config import settings
from app.core.exceptions import DeliveryError

router = APIRouter(prefix="/meetings/{meeting_id}", tags=["Review & Approval"])


class ApprovalRequest(BaseModel):
    reviewer_name: str = "Dr. Elena Ceban"
    reviewer_role: str = "Director Medical / Reviewer"
    comments: str | None = None
    expected_revision: int | None = None  # Revision the reviewer actually read and signed off


class ApprovalResponse(BaseModel):
    meeting_id: str
    status: ReviewStatus
    approved_by: str
    approved_at: datetime
    revision: int
    delivery_record: DeliveryRecord | None


@router.get("/minutes", response_model=MinutesOfMeeting)
def get_minutes(meeting_id: str) -> MinutesOfMeeting:
    """Retrieves the extracted Minutes of Meeting with decisions and actions."""
    minutes = repository.get_minutes(meeting_id)
    if not minutes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Minutes not generated for this meeting")
    return minutes


@router.put("/minutes", response_model=MinutesOfMeeting)
def update_minutes(meeting_id: str, updated_minutes: MinutesOfMeeting) -> MinutesOfMeeting:
    """Allows clinical reviewer to edit summary, decisions, or action items before sign-off."""
    meeting = repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    # An edit is always a new revision of a document the pipeline produced: with nothing stored there
    # is no server-owned provenance to inherit, and the caller could otherwise mint one from scratch.
    stored_minutes = repository.get_minutes(meeting_id)
    if not stored_minutes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Minutes not generated for this meeting")

    # Lost-update guard: refuse edits written against an outdated revision
    if updated_minutes.revision < stored_minutes.revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Revision conflict: minutes were updated to Rev.{stored_minutes.revision} while you were editing Rev.{updated_minutes.revision}. Reload before saving."
        )

    updated_minutes.meeting_id = meeting_id
    updated_minutes.revision = meeting.current_revision + 1
    meeting.current_revision = updated_minutes.revision

    # Extraction provenance is server-owned and survives every edit: the payload's defaults
    # (is_degraded=False, a generic model_version, empty stats) must never launder a degraded
    # draft past assert_dispatchable() or erase the audit trail. Only needs_name_review stays
    # editable, because confirming non-roster names is exactly the reviewer's job.
    updated_minutes.is_degraded = stored_minutes.is_degraded
    updated_minutes.model_version = stored_minutes.model_version
    updated_minutes.failed_chunks = list(stored_minutes.failed_chunks)
    updated_minutes.extraction_stats = dict(stored_minutes.extraction_stats)
    
    # Invalidate prior approval for the new revision
    if meeting.review_status in (ReviewStatus.APPROVED, ReviewStatus.DELIVERED):
        meeting.review_status = ReviewStatus.PENDING_REVIEW
        meeting.approved_by = None
        meeting.approved_at = None
    
    # Re-generate PDF and DOCX with the new revision
    pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=updated_minutes.revision)
    document_generator.generate_all(meeting, updated_minutes, pdf_path, docx_path)
    
    updated_minutes.pdf_path = str(pdf_path)
    updated_minutes.docx_path = str(docx_path)
    
    repository.save_meeting(meeting)
    return repository.save_minutes(updated_minutes)


@router.post("/review/approve", response_model=ApprovalResponse)
async def approve_and_dispatch(meeting_id: str, payload: ApprovalRequest) -> ApprovalResponse:
    """
    Formal human sign-off gate:
    1. Validates meeting state, prior delivery, and the revision the reviewer signed off
    2. Marks document as APPROVED
    3. Triggers automated delivery to official distribution lists via local SMTP and n8n
    """
    meeting = repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    minutes = repository.get_minutes(meeting_id)
    if not minutes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot approve meeting without generated minutes")

    if meeting.processing_status != ProcessingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve meeting while processing is '{meeting.processing_status.value}'"
        )

    if meeting.review_status == ReviewStatus.DELIVERED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Minutes Rev.{minutes.revision} were already delivered. Edit the minutes to create a new revision before dispatching again."
        )

    if payload.expected_revision is not None and payload.expected_revision != minutes.revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Revision conflict: you reviewed Rev.{payload.expected_revision} but the stored minutes are at Rev.{minutes.revision}. Reload before approving."
        )

    # A degraded draft can neither be approved nor sent: checked before any state is mutated
    try:
        delivery_router.assert_dispatchable(minutes)
    except DeliveryError as guard:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=guard.message)

    now = datetime.now(timezone.utc)
    meeting.review_status = ReviewStatus.APPROVED
    meeting.approved_by = f"{payload.reviewer_name} ({payload.reviewer_role})"
    meeting.approved_at = now
    meeting.error_message = None  # Clear any delivery error left by a previous attempt
    repository.save_meeting(meeting)

    # Deliver via exclusive channel: n8n or direct SMTP, both addressing the same resolved list
    pdf_path = Path(minutes.pdf_path) if minutes.pdf_path else None
    docx_path = Path(minutes.docx_path) if minutes.docx_path else None
    recipients = delivery_router.resolve_recipients(meeting)

    if settings.DELIVERY_CHANNEL == "n8n" and settings.N8N_ENABLED:
        delivery_rec = await n8n_service.trigger_workflow(meeting, minutes, recipients)
    else:
        delivery_rec = await smtp_service.deliver(meeting, minutes, pdf_path, docx_path, recipients)

    repository.save_delivery(delivery_rec)
    if delivery_rec.status == DeliveryStatus.DISPATCHED:
        meeting.review_status = ReviewStatus.DELIVERED
    else:
        meeting.review_status = ReviewStatus.APPROVED
        meeting.error_message = delivery_rec.error_message

    repository.save_meeting(meeting)

    return ApprovalResponse(
        meeting_id=meeting.id,
        status=meeting.review_status,
        approved_by=meeting.approved_by,
        approved_at=now,
        revision=minutes.revision,
        delivery_record=delivery_rec
    )
