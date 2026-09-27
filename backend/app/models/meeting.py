"""
Medpark Meeting Intelligence System - Meeting Domain Models
Defines core meeting entities, statuses, attendee metadata, and workflow modes.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator
import uuid


def _normalize_datetime(v: Any) -> Any:
    """Normalizes naive/aware datetimes and ISO strings to timezone-aware UTC."""
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if isinstance(v, datetime):
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    return v



class MeetingType(str, Enum):
    """Classification determining extraction focus and distribution routing."""
    MEDICAL = "medical"            # Medical Board / Case Discussions / Clinical Protocols
    EXECUTIVE = "executive"        # Hospital Executive Committee / Strategic & Budget
    ADMINISTRATIVE = "administrative"  # Operations, Procurement, Infrastructure


class ProcessingStatus(str, Enum):
    """Pipeline progression states."""
    IDLE = "idle"
    UPLOADING = "uploading"
    PREPROCESSING = "preprocessing"
    TRANSCRIBING = "transcribing"
    DIARIZING = "diarizing"
    EXTRACTING = "extracting"
    GENERATING_DOCS = "generating_docs"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowMode(str, Enum):
    """
    Execution Mode:
    - SUPERVISED: Requires human clinical/administrative sign-off before email dispatch.
    - AUTO_PILOT: Automated processing; email still requires human sign-off.
    """
    SUPERVISED = "supervised"
    AUTO_PILOT = "auto_pilot"


class ReviewStatus(str, Enum):
    """Review and delivery sign-off lifecycle."""
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    DELIVERED = "delivered"


class Attendee(BaseModel):
    """Participant metadata for identity suggestion and email distribution."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="Full name, e.g., 'Dr. Elena Ceban'")
    role: str = Field(default="Member", description="Department / Clinical Role")
    email: str = Field(..., description="Internal hospital email address")
    department: Optional[str] = Field(None, description="Hospital department, e.g. Cardiology, Surgery")
    person_id: Optional[str] = Field(None, description="Linked registered Person ID if selected from roster")
    primary_language: Literal["ro", "ru", "en"] | None = None


class MeetingBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=200, example="Ședință Comitet Medical - Secția Chirurgie")
    meeting_type: MeetingType = Field(default=MeetingType.MEDICAL)
    workflow_mode: WorkflowMode = Field(default=WorkflowMode.SUPERVISED)
    scheduled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attendees: list[Attendee] = Field(default_factory=list)
    agenda: Optional[str] = Field(None, description="Optional meeting topics or medical agenda")
    asr_department: Optional[str] = Field(None, description="Hospital department to bias ASR vocabulary, e.g. Cardiologie, Chirurgie")
    distribution_list: list[str] = Field(default_factory=list, description="Custom recipient emails (if overriding policy)")

    @field_validator("scheduled_at", mode="before")
    @classmethod
    def validate_scheduled_at(cls, v: Any) -> Any:
        return _normalize_datetime(v)


class MeetingCreate(MeetingBase):
    pass


class Meeting(MeetingBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Audio Artifacts
    original_audio_path: Optional[str] = None
    normalized_audio_path: Optional[str] = None
    audio_duration_seconds: float = 0.0
    asr_device_used: Optional[str] = None  # "cuda" / "cpu" actually used by the ASR stage of the last run
    # Free-form ASR telemetry copied from whisper_engine.last_run_stats after Stage 2 (strategy, windows,
    # window_languages, rtf, ...); empty on records processed before per-window LID existed.
    asr_stats: dict[str, Any] = Field(default_factory=dict)

    # State tracking
    processing_status: ProcessingStatus = ProcessingStatus.IDLE
    processing_progress: int = 0  # 0 to 100 percentage
    current_stage_detail: Optional[str] = None
    review_status: ReviewStatus = ReviewStatus.DRAFT
    
    # Versioning & Audit
    current_revision: int = 1
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    
    # Timing benchmarks for scoring evaluation
    processing_time_seconds: float = 0.0
    error_message: Optional[str] = None

    @field_validator("created_at", "updated_at", "approved_at", mode="before")
    @classmethod
    def validate_meeting_datetimes(cls, v: Any) -> Any:
        return _normalize_datetime(v)
