"""
Medpark Meeting Intelligence System - Transcript & Utterances API Endpoints
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.models.transcript import Transcript, TranscriptSegment
from app.storage.repository import repository

router = APIRouter(prefix="/meetings/{meeting_id}/transcript", tags=["Transcript"])


class SegmentUpdateRequest(BaseModel):
    corrected_text: str | None = None
    speaker: str | None = None
    is_flagged: bool | None = None


@router.get("/", response_model=Transcript)
def get_transcript(meeting_id: str) -> Transcript:
    """Returns the complete timestamped transcript for a meeting."""
    transcript = repository.get_transcript(meeting_id)
    if not transcript:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found for this meeting")
    return transcript


@router.put("/segments/{segment_id}", response_model=TranscriptSegment)
def update_transcript_segment(meeting_id: str, segment_id: str, payload: SegmentUpdateRequest) -> TranscriptSegment:
    """Allows reviewers to correct transcribed words or re-assign speaker labels."""
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

    if payload.corrected_text is not None:
        target_seg.corrected_text = payload.corrected_text
    if payload.speaker is not None:
        target_seg.speaker = payload.speaker
    if payload.is_flagged is not None:
        target_seg.is_flagged = payload.is_flagged

    transcript.compute_stats()
    repository.save_transcript(transcript)
    return target_seg
