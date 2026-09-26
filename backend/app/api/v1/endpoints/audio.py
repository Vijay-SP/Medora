"""
Medpark Meeting Intelligence System - Audio Upload & Streaming Endpoints
"""

from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from app.core.logging import logger
from app.models.meeting import Meeting, ProcessingStatus, ReviewStatus
from app.storage.repository import repository
from app.storage.file_manager import file_manager
from app.services.pipeline_orchestrator import ACTIVE_PROCESSING_STATUSES

router = APIRouter(prefix="/meetings/{meeting_id}/audio", tags=["Audio"])

# Accurate container MIME types so the browser waveform player can decode every accepted upload
AUDIO_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
    ".flac": "audio/flac"
}


@router.post("/upload", response_model=Meeting)
async def upload_audio(meeting_id: str, file: UploadFile = File(...)) -> Meeting:
    """Uploads recorded or external audio file (WAV, MP3, M4A, MP4, WebM) for a meeting."""
    meeting = await run_in_threadpool(repository.get_meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    if meeting.processing_status in ACTIVE_PROCESSING_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pipeline in progress: the recording cannot be replaced while processing runs"
        )

    # Blocking file copy and JSON persistence run off the event loop (large recordings)
    saved_path = await run_in_threadpool(
        file_manager.save_uploaded_audio, meeting_id, file.filename or "recording.webm", file.file
    )

    # Discard the artifacts of the previous recording so playback and the pipeline never mix sources
    previous_original = Path(meeting.original_audio_path) if meeting.original_audio_path else None
    if previous_original and previous_original != saved_path:
        previous_original.unlink(missing_ok=True)
    if meeting.normalized_audio_path:
        Path(meeting.normalized_audio_path).unlink(missing_ok=True)

    # Cached segment embeddings describe the voices of the replaced recording: a speaker rematch
    # against them would score people who may not be in the new audio at all. The upload itself
    # must not fail on a locked file; the next pipeline run overwrites the cache anyway.
    try:
        purged = await run_in_threadpool(file_manager.purge_meeting_embeddings, meeting_id)
        if purged:
            logger.info(f"Purged {purged} cached segment embedding file(s) of meeting {meeting_id} after a new upload")
    except Exception as exc:
        logger.warning(f"Could not purge cached segment embeddings of meeting {meeting_id}: {exc}")

    meeting.original_audio_path = str(saved_path)
    meeting.normalized_audio_path = None
    meeting.audio_duration_seconds = 0.0
    meeting.processing_status = ProcessingStatus.IDLE
    meeting.processing_progress = 0
    meeting.processing_time_seconds = 0.0
    meeting.error_message = None
    meeting.current_stage_detail = f"Fișier audio încărcat: {saved_path.name}"

    # New audio invalidates any earlier clinical sign-off for this meeting
    meeting.review_status = ReviewStatus.DRAFT
    meeting.approved_by = None
    meeting.approved_at = None

    return await run_in_threadpool(repository.save_meeting, meeting)


@router.get("/stream")
def stream_audio(meeting_id: str):
    """Streams the audio file for the interactive waveform player."""
    meeting = repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    # Prefer normalized 16kHz WAV if available, otherwise original
    audio_path = None
    if meeting.normalized_audio_path and Path(meeting.normalized_audio_path).exists():
        audio_path = Path(meeting.normalized_audio_path)
    elif meeting.original_audio_path and Path(meeting.original_audio_path).exists():
        audio_path = Path(meeting.original_audio_path)

    if not audio_path or not audio_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No audio file exists for this meeting")

    # Return media file labelled with its real container type
    media_type = AUDIO_MEDIA_TYPES.get(audio_path.suffix.lower(), "application/octet-stream")
    return FileResponse(path=audio_path, media_type=media_type, filename=audio_path.name)
