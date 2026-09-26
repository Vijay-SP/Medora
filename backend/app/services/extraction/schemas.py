"""
Medpark Meeting Intelligence System - LLM Output Schemas
JSON Schemas passed to Ollama's constrained decoding ("format") plus the pydantic models that re-validate the answers.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# Only the JSON Schema subset verified against Ollama 0.34.4 is used here:
# type, properties, required, enum, items, minItems, maxItems and ["string", "null"].
_EVIDENCE_IDX = {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 3}

MAP_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "decision": {"type": "string"},
                    "category": {"type": "string", "enum": ["clinical", "budget", "operations", "protocol"]},
                    "evidence_idx": _EVIDENCE_IDX,
                },
                "required": ["topic", "decision", "category", "evidence_idx"],
            },
        },
        "action_items": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "owner_mention": {"type": ["string", "null"]},
                    "owner_speaker": {"type": ["string", "null"]},
                    "deadline_phrase": {"type": ["string", "null"]},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "evidence_idx": _EVIDENCE_IDX,
                },
                "required": ["task", "owner_mention", "owner_speaker", "deadline_phrase", "priority", "evidence_idx"],
            },
        },
        "risks_and_questions": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "item_type": {"type": "string", "enum": ["risk", "unresolved_question"]},
                    "description": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "evidence_idx": _EVIDENCE_IDX,
                },
                "required": ["item_type", "description", "severity", "evidence_idx"],
            },
        },
    },
    "required": ["decisions", "action_items", "risks_and_questions"],
}

SYNTHESIS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary_ro": {"type": "string"},
        "summary_en": {"type": "string"},
        "agenda_topics": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    },
    "required": ["summary_ro", "summary_en", "agenda_topics"],
}


class MapDecision(BaseModel):
    """One decision as emitted by a map call; evidence is a list of transcript line indices."""
    topic: str
    decision: str
    category: Literal["clinical", "budget", "operations", "protocol"]
    evidence_idx: list[int] = Field(..., min_length=1, max_length=3)


class MapAction(BaseModel):
    """One action item as emitted by a map call; owner and deadline are verbatim spoken phrases."""
    task: str
    owner_mention: Optional[str] = None
    owner_speaker: Optional[str] = None
    deadline_phrase: Optional[str] = None
    priority: Literal["high", "medium", "low"]
    evidence_idx: list[int] = Field(..., min_length=1, max_length=3)


class MapRisk(BaseModel):
    """One risk or unresolved question as emitted by a map call."""
    item_type: Literal["risk", "unresolved_question"]
    description: str
    severity: Literal["high", "medium", "low"]
    evidence_idx: list[int] = Field(..., min_length=1, max_length=3)


class MapResult(BaseModel):
    """Complete answer of one map call over a transcript chunk."""
    decisions: list[MapDecision] = Field(default_factory=list, max_length=8)
    action_items: list[MapAction] = Field(default_factory=list, max_length=12)
    risks_and_questions: list[MapRisk] = Field(default_factory=list, max_length=8)


class SynthesisResult(BaseModel):
    """Answer of the single synthesis call over the merged item list."""
    summary_ro: str
    summary_en: str
    agenda_topics: list[str] = Field(default_factory=list, max_length=6)
