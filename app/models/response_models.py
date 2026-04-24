from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CourseResult(BaseModel):
    id: str | None = None
    course_code: str | None = None
    course_name: str | None = None
    department: str | None = None
    department_name: str | None = None
    credits: float | None = None
    semester: str | None = None
    section: str | None = None
    instructor: str | None = None
    days: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    prerequisites: str | None = None
    description: str | None = None
    relevance_score: float | None = None
    rerank_score: float | None = None
    vector_relevance_score: float | None = None
    vector_rank: int | None = None


class SearchCoursesResponse(BaseModel):
    query: str
    results: list[CourseResult]


class ScheduleResponse(BaseModel):
    selected_courses: list[dict[str, Any]]
    total_credits: float
    explanation: str
    alternative_schedules: list[dict[str, Any]]
    rejected_conflicts: list[dict[str, Any]]


class ChatResponse(BaseModel):
    response: str
    data: dict[str, Any] | None = None
