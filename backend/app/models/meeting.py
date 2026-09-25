"""
Medpark Meeting Intelligence System - Meeting Domain Models
Defines core meeting entities, statuses, attendee metadata, and workflow modes.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


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
    - AUTO_PILOT: Fully automated zero-click pipeline directly to email (challenge evaluation).
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


class MeetingBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=200, example="Ședință Comitet Medical - Secția Chirurgie")
    meeting_type: MeetingType = Field(default=MeetingType.MEDICAL)
    workflow_mode: WorkflowMode = Field(default=WorkflowMode.SUPERVISED)
    scheduled_at: datetime = Field(default_factory=datetime.now)
    attendees: list[Attendee] = Field(default_factory=list)
    agenda: Optional[str] = Field(None, description="Optional meeting topics or medical agenda")
    distribution_list: list[str] = Field(default_factory=list, description="Custom recipient emails (if overriding policy)")


class MeetingCreate(MeetingBase):
    pass


class Meeting(MeetingBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    # Audio Artifacts
    original_audio_path: Optional[str] = None
    normalized_audio_path: Optional[str] = None
    audio_duration_seconds: float = 0.0
    
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
