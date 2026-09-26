"""
Medpark Meeting Intelligence System - Information Extraction Models
Defines decisions, action items, evidence citations, deadlines, and minutes schemas.
"""

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator
import uuid


class EvidenceQuote(BaseModel):
    """Verbatim citation linking an extracted claim to exact audio coordinates."""
    segment_id: str = Field(..., description="ID of the matching transcript segment")
    start: float = Field(..., description="Start timestamp in seconds")
    end: float = Field(..., description="End timestamp in seconds")
    quote: str = Field(..., description="Exact spoken sentence supporting this item")
    speaker: Optional[str] = Field(None, description="Spoken by whom: the anonymous label, or a name only once confirmed and printable")
    speaker_person_id: Optional[str] = Field(None, description="Confirmed Person.id of the cited segment's speaker")
    speaker_is_confirmed: bool = Field(default=False, description="True only after a reviewer confirmed the cited segment's speaker")


class DecisionItem(BaseModel):
    """A formal agreement or medical/operational decision reached in the meeting."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    topic: str = Field(..., description="Topic area, e.g., 'Protocoale ATI' or 'Achiziție Echipamente'")
    decision: str = Field(..., description="Statement of what was decided (Romanian)")
    topic_ru: Optional[str] = Field(None, description="Topic area in Russian")
    decision_ru: Optional[str] = Field(None, description="Statement of what was decided in Russian")
    topic_en: Optional[str] = Field(None, description="Topic area in English")
    decision_en: Optional[str] = Field(None, description="Statement of what was decided in English")
    category: Literal["clinical", "budget", "operations", "protocol"] = "clinical"
    evidence: list[EvidenceQuote] = Field(default_factory=list, description="Grounding audio evidence")
    is_reviewed: bool = Field(default=False, description="Whether confirmed by human reviewer")


class ActionItem(BaseModel):
    """An assigned task with responsible owner, deadline, and audio verification."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    task: str = Field(..., description="Actionable task description (Romanian)")
    task_ru: Optional[str] = Field(None, description="Actionable task description in Russian")
    task_en: Optional[str] = Field(None, description="Actionable task description in English")
    owner: str = Field(default="Unassigned", description="Name of the responsible person")
    deadline_phrase: Optional[str] = Field(None, description="Original spoken phrase, e.g., 'până vineri'")
    deadline_phrase_ru: Optional[str] = Field(None, description="Deadline phrase in Russian")
    deadline_phrase_en: Optional[str] = Field(None, description="Deadline phrase in English")
    deadline_date: Optional[str] = Field(None, description="Resolved ISO date YYYY-MM-DD")
    priority: Literal["high", "medium", "low"] = "medium"
    status: Literal["open", "in_progress", "completed", "cancelled"] = "open"
    evidence: list[EvidenceQuote] = Field(default_factory=list, description="Grounding audio evidence")
    is_reviewed: bool = Field(default=False, description="Whether confirmed by human reviewer")
    owner_source: Literal["roster", "mention", "speaker", "confirmed_speaker", "unassigned"] = Field(
        default="unassigned",
        description="How the owner was resolved: attendee roster, verbatim mention, anonymous speaker label, reviewer-confirmed speaker, or none"
    )


class RiskOrQuestionItem(BaseModel):
    """Identified operational risk, clinical ambiguity, or unresolved question."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    item_type: Literal["risk", "unresolved_question"] = "risk"
    description: str = Field(..., description="Description of the risk or pending question (Romanian)")
    description_ru: Optional[str] = Field(None, description="Description in Russian")
    description_en: Optional[str] = Field(None, description="Description in English")
    severity: Literal["high", "medium", "low"] = "medium"
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class MinutesOfMeeting(BaseModel):
    """Structured, evidence-backed Minutes of Meeting (MoM) entity."""
    meeting_id: str
    title: str
    meeting_type: str = "medical"
    summary_ro: str = Field(..., description="Comprehensive executive summary in Romanian")
    summary_ru: Optional[str] = Field(None, description="Executive summary in Russian")
    summary_en: Optional[str] = Field(None, description="Secondary summary in English")
    agenda_topics: list[str] = Field(default_factory=list, description="Agenda topics in Romanian")
    agenda_topics_ru: Optional[list[str]] = Field(default=None, description="Agenda topics in Russian")
    agenda_topics_en: Optional[list[str]] = Field(default=None, description="Agenda topics in English")
    decisions: list[DecisionItem] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    risks_and_questions: list[RiskOrQuestionItem] = Field(default_factory=list)
    
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_version: str = Field(default="medpark-qwen-local")
    revision: int = 1

    # Extraction provenance and audit flags (all defaulted so persisted JSON keeps loading)
    is_degraded: bool = Field(default=False, description="Heuristic fallback produced this document; not dispatchable")
    needs_name_review: bool = Field(default=False, description="A non-roster owner or a suspect proper noun exists")
    failed_chunks: list[int] = Field(default_factory=list, description="Transcript chunk ordinals that failed extraction twice")
    extraction_stats: dict[str, Any] = Field(
        default_factory=dict,
        description="engine, model, chunks, calls, prompt_tokens, completion_tokens, seconds, json_first_pass_rate"
    )

    # Document artifact references
    pdf_path: Optional[str] = None
    docx_path: Optional[str] = None

    @field_validator("generated_at", mode="before")
    @classmethod
    def validate_generated_at(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if isinstance(v, datetime):
            if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
                return v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc)
        return v
