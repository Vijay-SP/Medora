"""
Medpark Meeting Intelligence System - Meetings API Endpoints
"""

from fastapi import APIRouter, HTTPException, status
from app.models.meeting import Meeting, MeetingCreate
from app.storage.repository import repository

router = APIRouter(prefix="/meetings", tags=["Meetings"])


@router.post("/", response_model=Meeting, status_code=status.HTTP_201_CREATED)
def create_meeting(payload: MeetingCreate) -> Meeting:
    """Creates a new meeting record with metadata and workflow settings."""
    meeting = Meeting(**payload.model_dump())
    return repository.save_meeting(meeting)


@router.get("/", response_model=list[Meeting])
def list_meetings() -> list[Meeting]:
    """Retrieves all meetings ordered by schedule date."""
    return repository.list_meetings()


@router.get("/{meeting_id}", response_model=Meeting)
def get_meeting(meeting_id: str) -> Meeting:
    """Retrieves a specific meeting by ID."""
    meeting = repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return meeting


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: str):
    """Deletes a meeting record."""
    success = repository.delete_meeting(meeting_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
