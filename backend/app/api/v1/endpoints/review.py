"""
Medpark Meeting Intelligence System - Review Workspace & Approval Endpoints
"""

from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.models.meeting import Meeting, ReviewStatus
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryRecord
from app.storage.repository import repository
from app.storage.file_manager import file_manager
from app.services.documents.generator import document_generator
from app.services.delivery.smtp_service import smtp_service
from app.services.delivery.n8n_service import n8n_service
from app.core.config import settings

router = APIRouter(prefix="/meetings/{meeting_id}", tags=["Review & Approval"])


class ApprovalRequest(BaseModel):
    reviewer_name: str = "Dr. Elena Ceban"
    reviewer_role: str = "Director Medical / Reviewer"
    comments: str | None = None


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

    updated_minutes.meeting_id = meeting_id
    updated_minutes.revision = meeting.current_revision + 1
    meeting.current_revision = updated_minutes.revision
    
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
    1. Validates meeting state
    2. Marks document as APPROVED
    3. Triggers automated delivery to official distribution lists via local SMTP and n8n
    """
    meeting = repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    minutes = repository.get_minutes(meeting_id)
    if not minutes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot approve meeting without generated minutes")

    now = datetime.now()
    meeting.review_status = ReviewStatus.APPROVED
    meeting.approved_by = f"{payload.reviewer_name} ({payload.reviewer_role})"
    meeting.approved_at = now
    repository.save_meeting(meeting)

    # Deliver via exclusive channel: n8n or direct SMTP
    pdf_path = Path(minutes.pdf_path) if minutes.pdf_path else None
    docx_path = Path(minutes.docx_path) if minutes.docx_path else None
    
    if settings.DELIVERY_CHANNEL == "n8n" and settings.N8N_ENABLED:
        delivery_rec = await n8n_service.trigger_workflow(meeting, minutes, meeting.distribution_list)
    else:
        delivery_rec = await smtp_service.deliver(meeting, minutes, pdf_path, docx_path)

    if delivery_rec:
        repository.save_delivery(delivery_rec)
        if delivery_rec.status == DeliveryStatus.DISPATCHED:
            meeting.review_status = ReviewStatus.DELIVERED
        else:
            meeting.review_status = ReviewStatus.APPROVED
            meeting.error_message = delivery_rec.error_message
    else:
        meeting.review_status = ReviewStatus.APPROVED

    repository.save_meeting(meeting)

    return ApprovalResponse(
        meeting_id=meeting.id,
        status=meeting.review_status,
        approved_by=meeting.approved_by,
        approved_at=now,
        revision=minutes.revision,
        delivery_record=delivery_rec
    )
