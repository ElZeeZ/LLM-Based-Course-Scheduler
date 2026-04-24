from __future__ import annotations

from typing import Any

from app.agent.preferences import DEFAULT_MAX_CREDITS
from app.scheduler.constraints import (
    check_schedule_conflicts,
    normalize_course_code,
    prerequisites_satisfied,
    sections_conflict,
)
from app.scheduler.scoring import score_course, score_schedule


def generate_optimal_schedules(
    candidate_courses: list[dict[str, Any]],
    *,
    max_credits: float = DEFAULT_MAX_CREDITS,
    completed_courses: list[str] | None = None,
    preferred_days: list[str] | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    completed = {normalize_course_code(code) for code in (completed_courses or [])}
    rejected: list[dict[str, Any]] = []
    eligible = _eligible_courses(candidate_courses, completed, rejected)
    grouped = _group_by_course(eligible)

    groups = sorted(
        grouped.values(),
        key=lambda items: max(score_course(item, preferred_days) for item in items),
        reverse=True,
    )
    groups = groups[:18]

    schedules: list[list[dict[str, Any]]] = []

    def backtrack(index: int, selected: list[dict[str, Any]], credits: float) -> None:
        if index >= len(groups):
            if selected:
                schedules.append(list(selected))
            return

        backtrack(index + 1, selected, credits)

        for section in sorted(groups[index], key=lambda item: score_course(item, preferred_days), reverse=True):
            section_credits = float(section.get("credits") or 0)
            if credits + section_credits > max_credits:
                rejected.append(_rejection(section, "Credit limit would be exceeded."))
                continue
            conflict = next((chosen for chosen in selected if sections_conflict(chosen, section)), None)
            if conflict:
                rejected.append(
                    _rejection(
                        section,
                        f"Time conflict with {conflict.get('course_code')} section {conflict.get('section')}.",
                    )
                )
                continue
            selected.append(section)
            backtrack(index + 1, selected, credits + section_credits)
            selected.pop()

    backtrack(0, [], 0)
    ranked = sorted(
        schedules,
        key=lambda items: score_schedule(items, max_credits=max_credits, preferred_days=preferred_days),
        reverse=True,
    )

    alternatives = [_summarize_schedule(schedule, max_credits, preferred_days) for schedule in ranked[:limit]]
    best = alternatives[0] if alternatives else _summarize_schedule([], max_credits, preferred_days)
    return {
        "best_schedule": best,
        "alternative_schedules": alternatives[1:],
        "rejected_conflicts": _dedupe_rejections(rejected)[:50],
    }


def _eligible_courses(
    courses: list[dict[str, Any]],
    completed: set[str],
    rejected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    eligible = []
    for course in courses:
        ok, missing = prerequisites_satisfied(course, completed)
        if not ok:
            rejected.append(_rejection(course, f"Missing prerequisite(s): {', '.join(missing)}."))
            continue
        eligible.append(course)
    return eligible


def _group_by_course(courses: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for course in courses:
        code = normalize_course_code(course.get("course_code")) or str(course.get("id"))
        grouped.setdefault(code, []).append(course)
    return grouped


def _summarize_schedule(
    courses: list[dict[str, Any]],
    max_credits: float,
    preferred_days: list[str] | None,
) -> dict[str, Any]:
    total_credits = sum(float(course.get("credits") or 0) for course in courses)
    return {
        "selected_courses": courses,
        "total_credits": total_credits,
        "score": score_schedule(courses, max_credits=max_credits, preferred_days=preferred_days),
        "conflicts": check_schedule_conflicts(courses),
    }


def _rejection(course: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "course_code": course.get("course_code"),
        "course_name": course.get("course_name"),
        "section": course.get("section"),
        "reason": reason,
    }


def _dedupe_rejections(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for item in items:
        key = (item.get("course_code"), item.get("section"), item.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
