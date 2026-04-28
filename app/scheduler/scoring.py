from __future__ import annotations

from datetime import time
from typing import Any

from app.scheduler.constraints import normalize_days, parse_time_value


def score_course(course: dict[str, Any], preferred_days: list[str] | None = None) -> float:
    score = float(course.get("relevance_score") or 0.0)
    days = set(normalize_days(course.get("days")))
    if preferred_days:
        preferred = set(normalize_days(preferred_days))
        if days == preferred:
            score += 0.5
        elif days and days <= preferred:
            score += 0.25
        elif days & preferred:
            score += 0.1
    start = parse_time_value(course.get("start_time"))
    if start and start >= time(8, 0):
        score += 0.02
    return score


def score_schedule(
    courses: list[dict[str, Any]],
    *,
    max_credits: float,
    preferred_days: list[str] | None = None,
) -> float:
    credits = sum(float(course.get("credits") or 0) for course in courses)
    target_score = 1.0 - abs(max_credits - credits) / max(max_credits, 1)
    relevance = sum(score_course(course, preferred_days) for course in courses)
    return round(target_score + relevance + (0.03 * len(courses)), 4)
