from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz

from app.agent.preferences import DEFAULT_MAX_CREDITS
from app.scheduler.constraints import (
    check_schedule_conflicts,
    day_overlap,
    normalize_days,
    normalize_course_code,
    parse_time_value,
    prerequisites_satisfied,
    sections_conflict,
    time_conflict,
)
from app.scheduler.scoring import score_course, score_schedule


def generate_optimal_schedules(
    candidate_courses: list[dict[str, Any]],
    *,
    max_credits: float = DEFAULT_MAX_CREDITS,
    completed_courses: list[str] | None = None,
    preferred_days: list[str] | None = None,
    avoided_days: list[str] | None = None,
    avoided_instructors: list[str] | None = None,
    removed_course_identifiers: list[str] | None = None,
    avoided_section_identifiers: list[str] | None = None,
    avoided_time_blocks: list[dict[str, Any]] | None = None,
    enforce_prerequisites: bool = False,
    limit: int = 3,
) -> dict[str, Any]:
    completed = {normalize_course_code(code) for code in (completed_courses or [])}
    rejected: list[dict[str, Any]] = []
    eligible = _eligible_courses(candidate_courses, completed, rejected, enforce_prerequisites)
    eligible = _remove_requested_sections(eligible, avoided_section_identifiers, rejected)
    grouped = _group_by_course(eligible)
    grouped = _remove_requested_courses(grouped, removed_course_identifiers, rejected)
    grouped = {
        code: _apply_section_preferences(
            sections,
            preferred_days=preferred_days,
            avoided_days=avoided_days,
            avoided_instructors=avoided_instructors,
            avoided_time_blocks=avoided_time_blocks,
            rejected=rejected,
        )
        for code, sections in grouped.items()
    }
    grouped = {code: sections for code, sections in grouped.items() if sections}

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

    alternatives = [
        _summarize_schedule(schedule, max_credits, preferred_days, avoided_time_blocks)
        for schedule in ranked[:limit]
    ]
    best = alternatives[0] if alternatives else _summarize_schedule([], max_credits, preferred_days, avoided_time_blocks)
    return {
        "best_schedule": best,
        "alternative_schedules": alternatives[1:],
        "rejected_conflicts": _dedupe_rejections(rejected)[:50],
    }


def _eligible_courses(
    courses: list[dict[str, Any]],
    completed: set[str],
    rejected: list[dict[str, Any]],
    enforce_prerequisites: bool,
) -> list[dict[str, Any]]:
    eligible = []
    for course in courses:
        if enforce_prerequisites:
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


def _remove_requested_courses(
    grouped: dict[str, list[dict[str, Any]]],
    removed_course_identifiers: list[str] | None,
    rejected: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    identifiers = [_normalize_identifier(item) for item in (removed_course_identifiers or []) if _normalize_identifier(item)]
    if not identifiers:
        return grouped

    kept: dict[str, list[dict[str, Any]]] = {}
    for code, sections in grouped.items():
        if any(_course_matches_identifier(section, identifiers) for section in sections):
            for section in sections:
                rejected.append(_rejection(section, "Removed by user request."))
            continue
        kept[code] = sections
    return kept


def _remove_requested_sections(
    courses: list[dict[str, Any]],
    avoided_section_identifiers: list[str] | None,
    rejected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    identifiers = [_normalize_identifier(item) for item in (avoided_section_identifiers or []) if _normalize_identifier(item)]
    if not identifiers:
        return courses

    kept = []
    for course in courses:
        if _section_matches_identifier(course, identifiers):
            rejected.append(_rejection(course, "Avoided current section/timing by user request."))
            continue
        kept.append(course)
    return kept


def _apply_section_preferences(
    sections: list[dict[str, Any]],
    *,
    preferred_days: list[str] | None,
    avoided_days: list[str] | None,
    avoided_instructors: list[str] | None,
    avoided_time_blocks: list[dict[str, Any]] | None,
    rejected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    filtered = sections

    avoided_names = [_normalize_name(name) for name in (avoided_instructors or []) if _normalize_name(name)]
    if avoided_names:
        allowed = [
            section
            for section in filtered
            if not _instructor_matches(section.get("instructor"), avoided_names)
        ]
        if allowed:
            for section in filtered:
                if section not in allowed:
                    rejected.append(_rejection(section, "Avoided instructor preference."))
            filtered = allowed

    preferred = set(normalize_days(preferred_days))
    if preferred:
        exact_matches = [section for section in filtered if set(normalize_days(section.get("days"))) == preferred]
        if exact_matches:
            filtered = exact_matches

    avoided = set(normalize_days(avoided_days))
    if avoided:
        allowed = [section for section in filtered if not (set(normalize_days(section.get("days"))) & avoided)]
        if allowed:
            for section in filtered:
                if section not in allowed:
                    rejected.append(_rejection(section, "Avoided day preference."))
            filtered = allowed

    time_blocks = _normalize_time_blocks(avoided_time_blocks)
    if time_blocks:
        allowed = [
            section
            for section in filtered
            if not _section_conflicts_time_blocks(section, time_blocks)
        ]
        if allowed:
            for section in filtered:
                if section not in allowed:
                    rejected.append(_rejection(section, "Avoided unavailable time preference."))
            filtered = allowed

    return filtered


def _instructor_matches(instructor: Any, avoided_names: list[str]) -> bool:
    normalized = _normalize_name(instructor)
    normalized_tokens = set(normalized.split())
    for name in avoided_names:
        name_tokens = set(name.split())
        if name in normalized or normalized in name:
            return True
        if name_tokens and name_tokens <= normalized_tokens:
            return True
        if len(name_tokens) == 1 and next(iter(name_tokens)) in normalized_tokens:
            return True
    return False


def _normalize_name(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    return re.sub(r"^(?:dr|prof|professor)\s+", "", normalized).strip()


def _course_matches_identifier(course: dict[str, Any], identifiers: list[str]) -> bool:
    values = [
        course.get("course_code"),
        course.get("course_id"),
        course.get("course_name"),
        course.get("title"),
        course.get("crn"),
        course.get("id"),
    ]
    normalized_values = [_normalize_identifier(value) for value in values if value not in (None, "")]
    return any(
        _identifier_matches(identifier, value)
        for identifier in identifiers
        for value in normalized_values
    )


def _section_matches_identifier(course: dict[str, Any], identifiers: list[str]) -> bool:
    values = [
        course.get("crn"),
        course.get("id"),
        f"{course.get('course_code', '')}{course.get('section', '')}",
        f"{course.get('course_code', '')}{course.get('crn', '')}",
    ]
    normalized_values = [_normalize_identifier(value) for value in values if value not in (None, "")]
    return any(
        _identifier_matches(identifier, value)
        for identifier in identifiers
        for value in normalized_values
    )


def _identifier_matches(identifier: str, value: str) -> bool:
    if not identifier or not value:
        return False
    if identifier == value or identifier in value or value in identifier:
        return True
    if min(len(identifier), len(value)) >= 5:
        return fuzz.WRatio(identifier, value) >= 84
    return False


def _normalize_identifier(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _summarize_schedule(
    courses: list[dict[str, Any]],
    max_credits: float,
    preferred_days: list[str] | None,
    avoided_time_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    total_credits = sum(float(course.get("credits") or 0) for course in courses)
    return {
        "selected_courses": courses,
        "total_credits": total_credits,
        "score": score_schedule(courses, max_credits=max_credits, preferred_days=preferred_days),
        "conflicts": [
            *check_schedule_conflicts(courses),
            *_check_time_block_conflicts(courses, avoided_time_blocks),
        ],
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


def _normalize_time_blocks(blocks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        days = normalize_days(block.get("days") or ["Mon", "Tue", "Wed", "Thu", "Fri"])
        start = parse_time_value(block.get("start_time"))
        end = parse_time_value(block.get("end_time"))
        if not days or not start or not end:
            continue
        if not end > start:
            continue
        normalized.append(
            {
                "label": str(block.get("label") or "unavailable time").strip() or "unavailable time",
                "days": days,
                "start_time": start.strftime("%H:%M"),
                "end_time": end.strftime("%H:%M"),
            }
        )
    return normalized


def _section_conflicts_time_blocks(section: dict[str, Any], blocks: list[dict[str, Any]]) -> bool:
    return any(_section_conflicts_time_block(section, block) for block in blocks)


def _section_conflicts_time_block(section: dict[str, Any], block: dict[str, Any]) -> bool:
    return day_overlap(section.get("days"), block.get("days")) and time_conflict(
        section.get("start_time"),
        section.get("end_time"),
        block.get("start_time"),
        block.get("end_time"),
    )


def _check_time_block_conflicts(
    courses: list[dict[str, Any]],
    avoided_time_blocks: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    blocks = _normalize_time_blocks(avoided_time_blocks)
    conflicts: list[dict[str, Any]] = []
    for course in courses:
        for block in blocks:
            if not _section_conflicts_time_block(course, block):
                continue
            conflicts.append(
                {
                    "course_a": course.get("course_code"),
                    "section_a": course.get("section"),
                    "course_b": block.get("label"),
                    "section_b": "N/A",
                    "reason": (
                        f"Overlaps unavailable time: {block.get('label')} "
                        f"{'/'.join(block.get('days') or [])} {block.get('start_time')}-{block.get('end_time')}."
                    ),
                }
            )
    return conflicts
