from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchCoursesRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] | None = None


class GenerateScheduleRequest(BaseModel):
    query: str = Field(description="Academic focus or scheduling request.")
    max_credits: float = Field(default=15, gt=0, le=24)
    completed_courses: list[str] = Field(default_factory=list)
    preferred_days: list[str] = Field(default_factory=list)
    top_k: int = Field(default=40, ge=1, le=150)


class ChatRequest(BaseModel):
    message: str
    max_credits: float = Field(default=15, gt=0, le=24)
    completed_courses: list[str] = Field(default_factory=list)
