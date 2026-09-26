"""
Medpark Meeting Intelligence System - Pipeline Processing Endpoints
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel
from app.models.meeting import ProcessingStatus
from app.storage.repository import repository
from app.services.pipeline_orchestrator import ACTIVE_PROCESSING_STATUSES, pipeline_orchestrator

router = APIRouter(prefix="/meetings/{meeting_id}/pipeline", tags=["Pipeline"])


class PipelineStatusResponse(BaseModel):
    meeting_id: str
    status: ProcessingStatus
    progress: int
    current_stage: str | None
    processing_time_seconds: float
    error_message: str | None


@router.post("/start", response_model=PipelineStatusResponse)
async def start_pipeline(meeting_id: str, background_tasks: BackgroundTasks):
    """Triggers the full offline pipeline from audio to minutes and routing."""
    meeting = repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    if not meeting.original_audio_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No audio uploaded for this meeting")

    if meeting.processing_status in ACTIVE_PROCESSING_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pipeline already in progress")

    # Persist the queued state before launching, so an immediate /status poll cannot report the
    # previous run's result and a second /start is rejected by the guard above.
    meeting.processing_status = ProcessingStatus.PREPROCESSING
    meeting.processing_progress = 5
    meeting.current_stage_detail = "Inițializare pipeline offline..."
    meeting.processing_time_seconds = 0.0
    meeting.error_message = None
    repository.save_meeting(meeting)

    # Launch background task
    background_tasks.add_task(pipeline_orchestrator.run_pipeline, meeting_id)

    return PipelineStatusResponse(
        meeting_id=meeting.id,
        status=meeting.processing_status,
        progress=meeting.processing_progress,
        current_stage=meeting.current_stage_detail,
        processing_time_seconds=meeting.processing_time_seconds,
        error_message=meeting.error_message
    )


@router.get("/status", response_model=PipelineStatusResponse)
def get_pipeline_status(meeting_id: str) -> PipelineStatusResponse:
    """Returns real-time processing progress and status."""
    meeting = repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    return PipelineStatusResponse(
        meeting_id=meeting.id,
        status=meeting.processing_status,
        progress=meeting.processing_progress,
        current_stage=meeting.current_stage_detail,
        processing_time_seconds=meeting.processing_time_seconds,
        error_message=meeting.error_message
    )
