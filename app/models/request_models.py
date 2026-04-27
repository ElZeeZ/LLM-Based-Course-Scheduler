from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.preferences import DEFAULT_MAX_CREDITS


class SearchCoursesRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] | None = None


class GenerateScheduleRequest(BaseModel):
    query: str = Field(description="Academic focus or scheduling request.")
    max_credits: float = Field(default=DEFAULT_MAX_CREDITS, gt=0, le=24)
    completed_courses: list[str] = Field(default_factory=list)
    preferred_days: list[str] = Field(default_factory=list)
    top_k: int = Field(default=40, ge=1, le=150)


class ChatRequest(BaseModel):
    message: str
    session_id: str = Field(default="default", description="Temporary in-memory chat session identifier.")
    reset_memory: bool = Field(default=False, description="Clear this session's memory before handling the message.")
