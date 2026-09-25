"""
Medpark Meeting Intelligence System - Information Extraction Models
Defines decisions, action items, evidence citations, deadlines, and minutes schemas.
"""

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


class EvidenceQuote(BaseModel):
    """Verbatim citation linking an extracted claim to exact audio coordinates."""
    segment_id: str = Field(..., description="ID of the matching transcript segment")
    start: float = Field(..., description="Start timestamp in seconds")
    end: float = Field(..., description="End timestamp in seconds")
    quote: str = Field(..., description="Exact spoken sentence supporting this item")
    speaker: Optional[str] = Field(None, description="Spoken by whom")


class DecisionItem(BaseModel):
    """A formal agreement or medical/operational decision reached in the meeting."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    topic: str = Field(..., description="Topic area, e.g., 'Protocoale ATI' or 'Achiziție Echipamente'")
    decision: str = Field(..., description="Statement of what was decided (Romanian)")
    category: Literal["clinical", "budget", "operations", "protocol"] = "clinical"
    evidence: list[EvidenceQuote] = Field(default_factory=list, description="Grounding audio evidence")
    is_reviewed: bool = Field(default=False, description="Whether confirmed by human reviewer")


class ActionItem(BaseModel):
    """An assigned task with responsible owner, deadline, and audio verification."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    task: str = Field(..., description="Actionable task description")
    owner: str = Field(default="Unassigned", description="Name of the responsible person")
    deadline_phrase: Optional[str] = Field(None, description="Original spoken phrase, e.g., 'până vineri'")
    deadline_date: Optional[str] = Field(None, description="Resolved ISO date YYYY-MM-DD")
    priority: Literal["high", "medium", "low"] = "medium"
    status: Literal["open", "in_progress", "completed", "cancelled"] = "open"
    evidence: list[EvidenceQuote] = Field(default_factory=list, description="Grounding audio evidence")
    is_reviewed: bool = Field(default=False, description="Whether confirmed by human reviewer")


class RiskOrQuestionItem(BaseModel):
    """Identified operational risk, clinical ambiguity, or unresolved question."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    item_type: Literal["risk", "unresolved_question"] = "risk"
    description: str = Field(..., description="Description of the risk or pending question")
    severity: Literal["high", "medium", "low"] = "medium"
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class MinutesOfMeeting(BaseModel):
    """Structured, evidence-backed Minutes of Meeting (MoM) entity."""
    meeting_id: str
    title: str
    meeting_type: str = "medical"
    summary_ro: str = Field(..., description="Comprehensive executive summary in Romanian")
    summary_en: Optional[str] = Field(None, description="Secondary summary in English")
    agenda_topics: list[str] = Field(default_factory=list)
    decisions: list[DecisionItem] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    risks_and_questions: list[RiskOrQuestionItem] = Field(default_factory=list)
    
    generated_at: datetime = Field(default_factory=datetime.now)
    model_version: str = Field(default="medpark-qwen-local")
    revision: int = 1
    
    # Document artifact references
    pdf_path: Optional[str] = None
    docx_path: Optional[str] = None
