"""
Medpark Meeting Intelligence System - Delivery & Artifact Downloads Endpoints
"""

from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from app.models.delivery import DeliveryRecord
from app.storage.repository import repository

router = APIRouter(tags=["Delivery & Artifacts"])


@router.get("/deliveries", response_model=list[DeliveryRecord])
def list_all_deliveries() -> list[DeliveryRecord]:
    """Returns all email delivery audit records across the system."""
    return repository.list_deliveries()


@router.get("/meetings/{meeting_id}/deliveries", response_model=list[DeliveryRecord])
def list_meeting_deliveries(meeting_id: str) -> list[DeliveryRecord]:
    """Returns all email delivery records for a specific meeting."""
    return repository.list_deliveries(meeting_id=meeting_id)


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
