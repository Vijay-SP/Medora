"""
Medpark Meeting Intelligence System - Person & Voiceprint Domain Models
Defines enrolled people, biometric consent, voiceprint descriptors, and per-meeting speaker attribution maps.

A voiceprint row never carries the embedding itself: the vector lives as a .npy file under
VOICEPRINTS_DIR (see file_manager) and the JSON store only references it by relative path.
"""

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator
import uuid

from app.models.meeting import _normalize_datetime

EMBEDDING_MODEL_NAME = "campplus-LM"
EMBEDDING_DIM = 512

EnrollmentState = Literal["not_enrolled", "enrolled", "needs_reenrollment"]


def compute_space_id(model_sha256: str, dim: int = EMBEDDING_DIM) -> str:
    """
    Embedding space identifier binding a voiceprint to the exact model that produced it.
    Embeddings from one model are meaningless against another, so a voiceprint from a different
    space is never matched; the person is reported as needs_reenrollment instead.
    The embedder exposes the same value (speaker_embedder.space_id) and must be preferred.
    """
    return f"{EMBEDDING_MODEL_NAME}@{model_sha256[:12]}/d{dim}/p1"


class ConsentRecord(BaseModel):
    """Explicit biometric consent of the enrolled person (Article 9 data)."""
    given: bool = False
    given_at: Optional[datetime] = None
    statement_version: str = "v1"
    retain_audio: bool = Field(default=False, description="Whether the enrollment WAVs may be kept for re-enrollment")
    withdrawn_at: Optional[datetime] = None

    @field_validator("given_at", "withdrawn_at", mode="before")
    @classmethod
    def validate_consent_datetimes(cls, v: Any) -> Any:
        return _normalize_datetime(v)

    @property
    def is_effective(self) -> bool:
        """Consent counts only while given and not withdrawn."""
        return self.given and self.withdrawn_at is None


class Voiceprint(BaseModel):
    """Descriptor of one stored voiceprint artifact; the vector itself is on disk, never here."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    space_id: str = Field(..., description="Embedding space that produced the vector, e.g. campplus-LM@<sha12>/d512/p1")
    model_sha256: str
    dim: int = EMBEDDING_DIM
    artifact_path: str = Field(..., description="Relative to VOICEPRINTS_DIR, e.g. people/<person_id>/<voiceprint_id>.npy")
    sample_count: int = 0
    total_speech_seconds: float = 0.0
    cohesion: Optional[float] = Field(None, description="Mean pairwise cosine across the enrollment samples")
    quality_warnings: list[str] = Field(default_factory=list)
    enrolled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True

    @field_validator("enrolled_at", mode="before")
    @classmethod
    def validate_enrolled_at(cls, v: Any) -> Any:
        return _normalize_datetime(v)


class Person(BaseModel):
    """An enrollable hospital staff member; distinct from the per-meeting Attendee roster entry."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    full_name: str = Field(..., min_length=1, max_length=200)
    role: str = "Member"
    email: str = ""
    department: Optional[str] = Field(None, description="Hospital department, e.g. Cardiology, ICU, Surgery")
    title: Optional[str] = Field(None, description="Medical/academic title, e.g. Dr., Prof.")
    primary_language: Optional[str] = Field("ro", description="Preferred spoken language in meetings (ro, ru, en)")
    specialty: Optional[str] = Field(None, description="Clinical specialty or sub-specialization")
    aliases: list[str] = Field(default_factory=list)
    is_active: bool = True
    consent: Optional[ConsentRecord] = None
    voiceprints: list[Voiceprint] = Field(default_factory=list)
    last_used_at: Optional[datetime] = Field(None, description="Last time a reviewer confirmed this person on a meeting")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("last_used_at", "created_at", "updated_at", mode="before")
    @classmethod
    def validate_person_datetimes(cls, v: Any) -> Any:
        return _normalize_datetime(v)

    @property
    def consent_effective(self) -> bool:
        return self.consent is not None and self.consent.is_effective

    def active_voiceprints(self, space_id: Optional[str] = None) -> list[Voiceprint]:
        """Active voiceprints, optionally restricted to one embedding space."""
        return [vp for vp in self.voiceprints if vp.is_active and (space_id is None or vp.space_id == space_id)]

    def enrollment_state(self, active_space_id: Optional[str]) -> EnrollmentState:
        """
        enrolled: an active voiceprint exists in the active embedder space.
        needs_reenrollment: voiceprints exist but none of them is in the active space.
        not_enrolled: everything else (no voiceprints, or only ones that did not qualify).
        """
        if active_space_id and self.active_voiceprints(active_space_id):
            return "enrolled"
        if self.voiceprints and all(vp.space_id != active_space_id for vp in self.voiceprints):
            return "needs_reenrollment"
        return "not_enrolled"


class PersonSummary(BaseModel):
    """API projection of a Person: exactly the frontend VoiceProfile shape, never an embedding."""
    id: str
    person_name: str
    role: str
    email: str
    department: Optional[str] = None
    title: Optional[str] = None
    primary_language: Optional[str] = None
    specialty: Optional[str] = None
    state: EnrollmentState
    sample_count: int
    total_sample_seconds: float
    embedding_model: str
    embedding_model_version: str
    consent_given_at: Optional[datetime] = None
    enrolled_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    quality_warnings: list[str] = Field(default_factory=list, description="Why the person is not (yet) enrolled")


def summarize_person(person: Person, active_space_id: Optional[str]) -> PersonSummary:
    """Projects a Person onto the API summary using the active embedder space to derive its state."""
    state = person.enrollment_state(active_space_id)
    # Progress is reported from the newest voiceprint even when it did not qualify, so the UI can
    # show how much speech is still missing.
    latest = max(person.voiceprints, key=lambda vp: vp.enrolled_at) if person.voiceprints else None
    active = person.active_voiceprints(active_space_id)
    reference = active[0] if active else latest
    warnings: list[str] = list(reference.quality_warnings) if reference and state != "enrolled" else []
    if state == "needs_reenrollment":
        if active_space_id is None:
            warnings.append("Speaker embedder is unavailable; the enrollment cannot be verified against the active model.")
        else:
            warnings.append("Voiceprint was produced by a previous embedding model; record new samples to re-enroll.")
    return PersonSummary(
        id=person.id,
        person_name=person.full_name,
        role=person.role,
        email=person.email,
        department=person.department,
        title=person.title,
        primary_language=person.primary_language,
        specialty=person.specialty,
        state=state,
        sample_count=reference.sample_count if reference else 0,
        total_sample_seconds=round(reference.total_speech_seconds, 2) if reference else 0.0,
        embedding_model=EMBEDDING_MODEL_NAME,
        embedding_model_version=(reference.space_id if reference else active_space_id) or "unavailable",
        consent_given_at=person.consent.given_at if person.consent and person.consent.is_effective else None,
        enrolled_at=reference.enrolled_at if reference and state == "enrolled" else None,
        last_used_at=person.last_used_at,
        quality_warnings=warnings,
    )


class SampleQuality(BaseModel):
    """Verdict on one enrollment sample; rendered verbatim to the person enrolling."""
    duration_seconds: float
    speech_seconds: float
    mean_dbfs: float
    clipped_fraction: float
    verdict: Literal["good", "usable", "reject"]
    reasons: list[str] = Field(default_factory=list)


class SpeakerAttributionEvent(BaseModel):
    """Append-only audit entry: one reviewer decision about one cluster of one meeting."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meeting_id: str
    cluster_id: str
    action: Literal["confirm", "correct", "reject", "unknown", "label"]
    person_id: Optional[str] = None
    person_name_snapshot: Optional[str] = None
    score_at_decision: Optional[float] = None
    margin_at_decision: Optional[float] = None
    space_id: Optional[str] = None
    reviewer: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    segment_ids: list[str] = Field(default_factory=list)

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, v: Any) -> Any:
        return _normalize_datetime(v)


class SpeakerMap(BaseModel):
    """Per-meeting history of speaker attribution decisions (the latest event per cluster wins)."""
    meeting_id: str
    space_id: Optional[str] = None
    events: list[SpeakerAttributionEvent] = Field(default_factory=list)
