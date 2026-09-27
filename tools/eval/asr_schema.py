"""
Medora ASR Evaluation Harness - Manifest and Hypothesis Schemas
Defines Pydantic models for gold annotation manifests, ASR hypotheses, and validation rules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


SplitType = Literal["train", "dev", "test"]
AcousticCondition = Literal["clean", "far_field", "reverberant", "noisy", "mixed"]
AnnotationStatus = Literal["draft", "reviewed", "verified"]


class EntityAnnotation(BaseModel):
    """A clinical entity, medication, proper noun, or medical term in the audio span."""
    term: str
    category: str = Field(default="clinical", description="e.g. medication, anatomy, person, procedure, condition")
    start_char: Optional[int] = None
    end_char: Optional[int] = None


class CriticalFact(BaseModel):
    """A critical factual assertion that must not be inverted or corrupted (e.g. negation, dosage)."""
    kind: Literal["negation", "dosage", "vital_sign", "direction"]
    expected_token: str
    numeric_value: Optional[float] = None
    unit: Optional[str] = None


class GoldSegment(BaseModel):
    """An annotated speech interval with verbatim transcription."""
    segment_id: str
    start: float = Field(..., ge=0.0)
    end: float = Field(..., ge=0.0)
    speaker: str = Field(default="Speaker 1")
    language: str = Field(default="ro", description="ro, ru, en, or mixed")
    verbatim_text: str = Field(..., description="Exact spoken words without normalization")
    entities: list[EntityAnnotation] = Field(default_factory=list)
    critical_facts: list[CriticalFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timestamps(self) -> "GoldSegment":
        if self.end < self.start:
            raise ValueError(f"Segment {self.segment_id}: end ({self.end}) must be >= start ({self.start})")
        return self


class RecordingEntry(BaseModel):
    """Gold annotation metadata and segments for one recording."""
    recording_id: str
    audio_path: Optional[str] = None
    checksum_sha256: str = Field(..., min_length=16)
    duration_seconds: float = Field(..., ge=0.0)
    sample_rate: int = Field(default=16000)
    pseudonymous_speaker_group: str = Field(default="group_default")
    split: SplitType = Field(default="test")
    acoustic_condition: AcousticCondition = Field(default="clean")
    annotation_status: AnnotationStatus = Field(default="verified")
    segments: list[GoldSegment] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_monotonic_segments(self) -> "RecordingEntry":
        prev_start = -1.0
        for seg in self.segments:
            if seg.start < prev_start:
                raise ValueError(f"Recording {self.recording_id}: non-monotonic segments detected at {seg.segment_id}")
            prev_start = seg.start
            if seg.end > self.duration_seconds + 0.5:
                raise ValueError(f"Recording {self.recording_id}: segment {seg.segment_id} ends ({seg.end}) past duration ({self.duration_seconds})")
        return self


class ASRManifest(BaseModel):
    """Collection of gold recordings forming an evaluation or training split manifest."""
    schema_version: str = Field(default="1.0.0")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    description: str = Field(default="Medora ASR Gold Manifest")
    recordings: list[RecordingEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest_invariants(self) -> "ASRManifest":
        seen_ids: set[str] = set()
        seen_checksums: dict[str, str] = {}
        split_by_recording: dict[str, str] = {}

        for rec in self.recordings:
            if rec.recording_id in seen_ids:
                raise ValueError(f"Duplicate recording_id in manifest: {rec.recording_id}")
            seen_ids.add(rec.recording_id)

            # A recording or identical audio cannot exist across multiple splits
            if rec.checksum_sha256 in seen_checksums and seen_checksums[rec.checksum_sha256] != rec.split:
                raise ValueError(
                    f"Checksum {rec.checksum_sha256} appears in split '{seen_checksums[rec.checksum_sha256]}' and '{rec.split}'"
                )
            seen_checksums[rec.checksum_sha256] = rec.split

        return self


class HypothesisSegment(BaseModel):
    """An ASR-decoded segment produced by an engine/model under evaluation."""
    start: float = Field(..., ge=0.0)
    end: float = Field(..., ge=0.0)
    text: str = Field(default="")
    language: Optional[str] = None
    confidence: Optional[float] = None


class RecordingHypothesis(BaseModel):
    """Hypothesis segments for a single recording."""
    recording_id: str
    segments: list[HypothesisSegment] = Field(default_factory=list)


class ASRHypothesisSet(BaseModel):
    """Collection of hypotheses produced for an evaluation run."""
    schema_version: str = Field(default="1.0.0")
    model_id: str = Field(default="whisper-base")
    runtime: str = Field(default="faster-whisper")
    parameters: dict[str, Any] = Field(default_factory=dict)
    run_timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    context_hash: Optional[str] = None
    hypotheses: list[RecordingHypothesis] = Field(default_factory=list)
