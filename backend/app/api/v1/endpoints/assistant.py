"""
Medpark Meeting Intelligence System - Executive Assistant Chat Endpoints
"""

from typing import Any, Literal, Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field
from app.services.assistant.analytics_service import assistant_analytics_service

router = APIRouter(prefix="/assistant", tags=["Executive Assistant"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AssistantChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list)
    current_meeting_id: Optional[str] = None


class ReferencedMeeting(BaseModel):
    id: str
    title: str
    date: str


class AssistantChatResponse(BaseModel):
    answer: str
    referenced_meetings: list[ReferencedMeeting] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(payload: AssistantChatRequest) -> AssistantChatResponse:
    """Answers user queries across all hospital meetings, decisions, and action items."""
    hist = [{"role": m.role, "content": m.content} for m in payload.history]
    result = await assistant_analytics_service.answer_query(
        query=payload.query,
        history=hist,
        current_meeting_id=payload.current_meeting_id,
    )
    return AssistantChatResponse(
        answer=result["answer"],
        referenced_meetings=[ReferencedMeeting(**rm) for rm in result.get("referenced_meetings", [])],
        metrics=result.get("metrics", {}),
    )
