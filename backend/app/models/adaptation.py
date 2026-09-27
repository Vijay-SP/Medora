"""
Medpark Meeting Intelligence System - ASR Adaptation and Learning Domain Models
Defines correction events, edit classifications, verification metadata, and collection results.
"""

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator
import uuid

from app.models.meeting import _normalize_datetime

EditKind = Literal["transcription", "normalization", "translation", "redaction", "editorial"]
VerificationStatus = Literal["unverified", "verified", "rejected"]
CollectionStatus = Literal["collected", "ineligible", "retry_required"]
RuleAction = Literal["safe_replace", "suggest_only"]
RuleApproval = Literal["approved", "pending", "rejected", "rolled_back"]


class CorrectionEvent(BaseModel):
    """
    Immutable audit record of a human reviewer correction to a transcript segment.
    Retains full provenance and original decodes before any human edit.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meeting_id: str = Field(..., description="ID of the meeting containing the segment")
    segment_id: str = Field(..., description="ID of the edited segment")
    transcript_revision: int = Field(..., description="Transcript revision after this edit was accepted")
    request_id: Optional[str] = Field(None, description="Client-supplied idempotency key")
    edit_kind: EditKind = Field(default="editorial", description="Classification of the edit performed")
    previous_text: str = Field(..., description="The visible text immediately prior to this edit")
    new_text: str = Field(..., description="The new text set by the reviewer (can be empty string for deletion)")
    raw_text: Optional[str] = Field(None, description="Untouched decoder text from segment")
    normalized_text: Optional[str] = Field(None, description="Conservative normalized text from segment prior to edit")
    raw_text_origin: Optional[str] = Field(None, description="'decoder' vs 'legacy_unknown'")
    reviewer_label: Optional[str] = Field(None, description="Display name / label of the reviewer")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Verification status for model adaptation / training reuse
    verified_against_audio: bool = Field(
        default=False,
        description="Whether the edit has been explicitly verified by listening to the audio interval"
    )
    training_reuse_allowed: bool = Field(
        default=False,
        description="Whether explicit consent was granted to include this clip in training datasets"
    )
    verification_status: VerificationStatus = Field(
        default="unverified",
        description="Current training-eligibility verification status"
    )
    verified_by: Optional[str] = Field(None, description="Reviewer who verified the segment against audio")
    verified_at: Optional[datetime] = None
    rejection_reason: Optional[str] = Field(None, description="Reason if marked rejected for dataset reuse")

    @field_validator("created_at", "verified_at", mode="before")
    @classmethod
    def validate_event_datetimes(cls, v: Any) -> Any:
        return _normalize_datetime(v)


class CollectionResult(BaseModel):
    """Result of attempting to project a correction event into the adaptation catalog."""
    status: CollectionStatus
    event_id: str
    meeting_id: str
    reason: Optional[str] = None


class VerifyCorrectionRequest(BaseModel):
    """Payload to verify a correction event against audio coordinates for dataset reuse."""
    expected_revision: int = Field(..., description="Exact transcript revision this verification targets")
    audio_start: float = Field(..., description="Start timestamp of the audio segment")
    audio_end: float = Field(..., description="End timestamp of the audio segment")
    edit_kind: EditKind = Field(..., description="Verified classification: must be 'transcription'")
    reviewer_label: str = Field(..., description="Reviewer name / label performing verification")
    verified_against_audio: bool = Field(..., description="Explicit confirmation that audio was listened to")
    training_reuse_allowed: bool = Field(..., description="Explicit consent to include in training datasets")


class RejectCorrectionRequest(BaseModel):
    """Payload to reject a correction event from training reuse."""
    reason: str = Field(..., min_length=2, description="Reason for rejecting dataset reuse")
    reviewer_label: Optional[str] = Field(None, description="Reviewer name / label performing rejection")


class LearningInboxResponse(BaseModel):
    """Summary and listings for reviewer learning inbox."""
    counts: dict[str, int]
    eligible_audio_duration_seconds: float
    corrections: list[dict[str, Any]]


class NormalizationRule(BaseModel):
    """Conservative, clinician-reviewed dialect/code-switch normalization rule."""
    id: str
    language: str
    variants: list[str]
    canonical: str
    scope: str = "clinical"
    action: RuleAction = "safe_replace"
    version: str = "1.0.0"
    approval: RuleApproval = "approved"


class NormalizationResult(BaseModel):
    """Result of applying dialect rules to text."""
    text: str
    corrections: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class RuleCandidate(BaseModel):
    """Mined rule candidate from verified human corrections requiring human review."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    language: str
    detected_variant: str
    suggested_canonical: str
    occurrences_count: int
    speakers_count: int
    meetings_count: int
    example_contexts: list[str] = Field(default_factory=list)
    is_safe_candidate: bool = True
    flag_reasons: list[str] = Field(default_factory=list)


class ApproveRuleRequest(BaseModel):
    """Request to approve or update a dialect normalization rule."""
    reviewer_label: str = Field(..., description="Reviewer name / label performing approval")
    action: Optional[RuleAction] = Field(None, description="Optional action override (safe_replace vs suggest_only)")
    canonical: Optional[str] = Field(None, description="Optional canonical text override")


class RollbackRuleRequest(BaseModel):
    """Request to rollback / disable a dialect normalization rule."""
    reviewer_label: str = Field(..., description="Reviewer name / label performing rollback")
    reason: str = Field(..., min_length=2, description="Reason for rollback")

