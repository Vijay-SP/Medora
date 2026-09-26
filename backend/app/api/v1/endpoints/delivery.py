"""
Medpark Meeting Intelligence System - Delivery & Artifact Downloads Endpoints
"""

from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, Response
from app.models.delivery import DeliveryRecord
from app.storage.repository import repository
from app.models.meeting import ReviewStatus, ProcessingStatus
from app.models.delivery import DeliveryStatus
from app.services.delivery.smtp_service import read_message, smtp_service
from app.services.delivery.router import delivery_router
from app.services.delivery.dispatch_lock import dispatch_lock, record_outcome
from app.core.exceptions import DeliveryError, ResourceNotFoundError
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from app.core.config import settings
from app.models.meeting import Meeting
from app.models.extraction import MinutesOfMeeting
from app.services.delivery.smtp_service import build_body, get_email_languages, save_message

router = APIRouter(tags=["Delivery & Artifacts"])


def _get_delivery(delivery_id: str) -> DeliveryRecord:
    record = next((r for r in repository.list_deliveries() if r.id == delivery_id), None)
    if not record:
        raise HTTPException(404, "Delivery record not found")
    return record


def _ensure_delivery_eml(record: DeliveryRecord, meeting: Meeting, minutes: MinutesOfMeeting) -> bytes:
    try:
        return read_message(record)
    except Exception:
        from app.storage.file_manager import file_manager
        pdf_path = Path(record.pdf_attachment_path) if record.pdf_attachment_path and Path(record.pdf_attachment_path).exists() else None
        docx_path = Path(record.docx_attachment_path) if record.docx_attachment_path and Path(record.docx_attachment_path).exists() else None
        if not pdf_path or not docx_path:
            p_pdf, p_docx = file_manager.get_export_paths(meeting.id, revision=record.revision)
            if p_pdf.exists():
                pdf_path = p_pdf
            if p_docx.exists():
                docx_path = p_docx

        body_text = record.body_text or build_body(meeting, minutes, pdf_path, docx_path)
        to_list, cc_list = delivery_router.split_to_cc(meeting, record.recipients)

        msg = EmailMessage()
        msg["Subject"] = record.subject
        msg["From"] = record.from_header or f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["Date"] = format_datetime(record.created_at)
        msg["Message-ID"] = make_msgid(domain="medpark.local")
        msg["To"] = ", ".join(to_list)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        msg.set_content(body_text, cte="quoted-printable")

        if pdf_path and pdf_path.exists():
            msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)
        if docx_path and docx_path.exists():
            msg.add_attachment(docx_path.read_bytes(), maintype="application", subtype="vnd.openxmlformats-officedocument.wordprocessingml.document", filename=docx_path.name)

        raw = msg.as_bytes(policy=policy.SMTP)
        save_message(record, raw)
        record.body_text = body_text
        record.languages_included = get_email_languages(meeting)
        record.from_header = str(msg["From"])
        record.envelope_sender = settings.SMTP_FROM_EMAIL
        record.to_recipients = to_list
        record.cc_recipients = cc_list
        record.retry_allowed = True
        record.eml_available = True
        repository.save_delivery(record)
        return raw


def _email_bytes(record: DeliveryRecord) -> bytes:
    try:
        return read_message(record)
    except (OSError, ResourceNotFoundError):
        raise HTTPException(404, "Saved email is not available")
    except ValueError:
        raise HTTPException(409, "Saved email failed its integrity check")


@router.get("/deliveries/{delivery_id}/eml")
def download_delivery_eml(delivery_id: str):
    return Response(_email_bytes(_get_delivery(delivery_id)), media_type="message/rfc822",
                    headers={"Content-Disposition": 'attachment; filename="meeting-email.eml"'})


@router.post("/deliveries/{delivery_id}/send", response_model=DeliveryRecord)
async def send_saved_delivery(delivery_id: str):
    """Explicit send of a human-approved snapshot. Never regenerates or automatically retries."""
    with dispatch_lock():
        source = _get_delivery(delivery_id)
        # If an attempt for this source or meeting already succeeded, return it rather than resending duplicates
        successful = next((r for r in repository.list_deliveries(source.meeting_id) 
                           if (r.retry_of == source.id or r.id == source.id) and r.status == DeliveryStatus.DISPATCHED), None)
        if successful:
            return successful

        meeting = repository.get_meeting(source.meeting_id)
        minutes = repository.get_minutes(source.meeting_id)
        if (not meeting or not minutes or meeting.processing_status != ProcessingStatus.COMPLETED
                or meeting.review_status not in (ReviewStatus.APPROVED, ReviewStatus.DELIVERED) or not meeting.approved_at
                or meeting.approved_by == "Auto-Pilot Pipeline"
                or source.revision != minutes.revision or source.revision != meeting.current_revision):
            raise HTTPException(409, "The current revision must have human approval before sending this email")
        try:
            delivery_router.assert_dispatchable(minutes)
        except DeliveryError as exc:
            raise HTTPException(409, exc.message)
        if source.status not in (DeliveryStatus.SAVED_LOCALLY, DeliveryStatus.FAILED, DeliveryStatus.SIMULATED):
            raise HTTPException(409, f"This attempt with status '{source.status}' cannot be resent.")

        if not source.eml_available:
            _ensure_delivery_eml(source, meeting, minutes)
        else:
            _email_bytes(source)

        try:
            record = await smtp_service.send_saved(source)
        except (OSError, ValueError, ResourceNotFoundError) as exc:
            raise HTTPException(409, f"Could not prepare the saved email for sending: {exc}")
        record_outcome(record)
        return record


def _snapshot_attachment(record: DeliveryRecord, extension: str) -> Response:
    message = BytesParser(policy=policy.default).parsebytes(_email_bytes(record))
    for part in message.iter_attachments():
        if (part.get_filename() or "").lower().endswith(f".{extension}"):
            return Response(part.get_payload(decode=True), media_type=part.get_content_type(),
                            headers={"Content-Disposition": f'attachment; filename="minutes-rev-{record.revision}.{extension}"'})
    raise HTTPException(404, "Attachment is missing from the saved email")


def collapse_deliveries(records: list[DeliveryRecord]) -> list[DeliveryRecord]:
    """
    Collapses delivery history for user presentation:
    1. If a revision was dispatched, hides prior failed/saved attempts for that revision.
    2. If a higher revision of a meeting was dispatched, hides older failed attempts.
    3. If multiple attempts exist for the same revision without dispatch, shows only the latest attempt.
    """
    by_meeting: dict[str, list[DeliveryRecord]] = {}
    for r in records:
        by_meeting.setdefault(r.meeting_id, []).append(r)

    collapsed: list[DeliveryRecord] = []
    for meeting_id, m_records in by_meeting.items():
        dispatched_revs = {r.revision for r in m_records if r.status == DeliveryStatus.DISPATCHED}
        max_dispatched_rev = max(dispatched_revs) if dispatched_revs else -1

        by_rev: dict[int, list[DeliveryRecord]] = {}
        for r in m_records:
            by_rev.setdefault(r.revision, []).append(r)

        for rev, rev_records in by_rev.items():
            dispatched = [r for r in rev_records if r.status == DeliveryStatus.DISPATCHED]
            if dispatched:
                dispatched.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                collapsed.append(dispatched[0])
            elif rev < max_dispatched_rev:
                continue
            else:
                rev_records.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                collapsed.append(rev_records[0])

    collapsed.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return collapsed


@router.get("/deliveries", response_model=list[DeliveryRecord])
def list_all_deliveries(include_history: bool = False) -> list[DeliveryRecord]:
    """Returns all email delivery audit records across the system."""
    records = repository.list_deliveries()
    return records if include_history else collapse_deliveries(records)


@router.get("/meetings/{meeting_id}/deliveries", response_model=list[DeliveryRecord])
def list_meeting_deliveries(meeting_id: str, include_history: bool = False) -> list[DeliveryRecord]:
    """Returns all email delivery records for a specific meeting."""
    records = repository.list_deliveries(meeting_id=meeting_id)
    return records if include_history else collapse_deliveries(records)


from app.storage.file_manager import file_manager


@router.get("/meetings/{meeting_id}/export/pdf")
def download_pdf(meeting_id: str, revision: int | None = None):
    """Downloads the generated PDF Minutes of Meeting (optional specific revision)."""
    minutes = repository.get_minutes(meeting_id)
    if not minutes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF document not yet generated")

    rev = revision if revision is not None else minutes.revision
    pdf_path, _ = file_manager.get_export_paths(meeting_id, revision=rev)
    if not pdf_path.exists():
        if minutes.pdf_path and Path(minutes.pdf_path).exists() and revision is None:
            pdf_path = Path(minutes.pdf_path)
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"PDF file for Rev.{rev} missing on disk")

    return FileResponse(path=pdf_path, media_type="application/pdf", filename=pdf_path.name)


@router.get("/meetings/{meeting_id}/export/docx")
def download_docx(meeting_id: str, revision: int | None = None):
    """Downloads the generated Word DOCX Minutes of Meeting (optional specific revision)."""
    minutes = repository.get_minutes(meeting_id)
    if not minutes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DOCX document not yet generated")

    rev = revision if revision is not None else minutes.revision
    _, docx_path = file_manager.get_export_paths(meeting_id, revision=rev)
    if not docx_path.exists():
        if minutes.docx_path and Path(minutes.docx_path).exists() and revision is None:
            docx_path = Path(minutes.docx_path)
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"DOCX file for Rev.{rev} missing on disk")

    return FileResponse(
        path=docx_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=docx_path.name
    )


@router.get("/deliveries/{delivery_id}/attachment/pdf")
def download_delivery_pdf(delivery_id: str):
    """Downloads the exact historical PDF revision dispatched with this delivery."""
    snapshot = _get_delivery(delivery_id)
    if snapshot.eml_available:
        return _snapshot_attachment(snapshot, "pdf")
    deliveries = repository.list_deliveries()
    record = next((d for d in deliveries if d.id == delivery_id), None)
    if not record or not record.pdf_attachment_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery record or attachment not found")

    path = Path(record.pdf_attachment_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Historical PDF attachment missing on disk")

    return FileResponse(path=path, media_type="application/pdf", filename=path.name)


@router.get("/deliveries/{delivery_id}/attachment/docx")
def download_delivery_docx(delivery_id: str):
    """Downloads the exact historical DOCX revision dispatched with this delivery."""
    snapshot = _get_delivery(delivery_id)
    if snapshot.eml_available:
        return _snapshot_attachment(snapshot, "docx")
    deliveries = repository.list_deliveries()
    record = next((d for d in deliveries if d.id == delivery_id), None)
    if not record or not record.docx_attachment_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery record or attachment not found")

    path = Path(record.docx_attachment_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Historical DOCX attachment missing on disk")

    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name
    )
