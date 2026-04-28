from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from langchain.agents import create_agent

from app.agent.course_resolver import resolve_requested_courses
from app.agent.preferences import DEFAULT_MAX_CREDITS, extract_max_credits
from app.integrations.node_courses import extract_campus, extract_course_codes, extract_search_terms, fetch_exact_schedule_sections
from app.integrations.postgres_courses import fetch_postgres_schedule_sections
from app.agent.tools import TOOLS
from app.llm.gemini_client import extract_schedule_constraints_with_gemini, generate_grounded_response, get_gemini_llm
from app.rag.retriever import retrieve_relevant_courses
from app.scheduler.constraints import normalize_days, parse_time_value
from app.scheduler.optimizer import generate_optimal_schedules


SCHEDULE_INTENT_RE = re.compile(r"\b(schedule|timetable|plan|semester|credits?)\b", re.IGNORECASE)
COURSE_DISCOVERY_ACTION_RE = re.compile(
    r"\b(find|search|show|list|what|which|get|give me|recommend)\b",
    re.IGNORECASE,
)
COURSE_DISCOVERY_TOPIC_RE = re.compile(
    r"\b(courses?|classes?|description|descriptions|topic|topics|similar|related|relevant|about|involve|involves)\b",
    re.IGNORECASE,
)
SCHEDULE_CONSTRAINT_RE = re.compile(
    r"\b(mwf|m/w/f|tr|t/r|tuesday|thursday|monday|wednesday|friday|avoid|without|not with|do not want|don't want|dont want|remove|drop|delete|take out|exclude|different|another|other|change|switch|section|instructor|professor|prof|dr\.?)\b",
    re.IGNORECASE,
)
COURSE_TAKING_RE = re.compile(
    r"\b(take|taking|enroll|register|add|include|put|build|make|create|give me)\b",
    re.IGNORECASE,
)
COURSE_DESCRIPTION_RE = re.compile(
    r"\b(description|describe|details?|what\s+is|tell\s+me\s+about|explain)\b",
    re.IGNORECASE,
)
MAX_MEMORY_MESSAGES = 20
MAX_CONTEXT_USER_MESSAGES = 4


class AcademicAgent:
    def __init__(self) -> None:
        self._agent: Any | None = None
        self._messages: list[dict[str, str]] = []
        self._last_schedule_courses: list[dict[str, Any]] = []
        self._last_schedule_preferences: dict[str, list[str]] = _empty_schedule_preferences()
        self._schedule_action_history: list[dict[str, Any]] = []

    def run(
        self,
        message: str,
        *,
        max_credits: float = DEFAULT_MAX_CREDITS,
        completed_courses: list[str] | None = None,
    ) -> dict[str, Any]:
        if self._should_handle_as_schedule_course_description(message):
            return self.describe_scheduled_course(message)

        if self._should_handle_as_schedule(message):
            return self.generate_schedule(
                message,
                max_credits=max_credits,
                completed_courses=completed_courses or [],
            )

        if self._should_handle_as_course_search(message):
            return self.search_courses(message)

        result = self._conversation_run(message)
        self._remember(message, result["response"])
        return result

    def _legacy_agent_run(
        self,
        message: str,
        *,
        max_credits: float = DEFAULT_MAX_CREDITS,
        completed_courses: list[str] | None = None,
    ) -> dict[str, Any]:
        if not SCHEDULE_INTENT_RE.search(message):
            return self.search_courses(message)

        try:
            agent = self._get_agent()
            result = agent.invoke({"messages": [*self._messages, {"role": "user", "content": message}]})
            messages = result.get("messages", [])
            content = messages[-1].content if messages else ""
            response = str(content)
            self._remember(message, response)
            return {"response": response, "data": None}
        except Exception:
            result = self._schedule_fallback_run(
                message,
                max_credits=extract_max_credits(message, max_credits),
                completed_courses=completed_courses or [],
            )
            self._remember(message, result["response"])
            return result

    def search_courses(self, message: str) -> dict[str, Any]:
        result = self._course_search_run(message)
        self._remember(message, result["response"])
        return result

    def describe_scheduled_course(self, message: str) -> dict[str, Any]:
        result = self._scheduled_course_description_run(message)
        self._remember(message, result["response"])
        return result

    def generate_schedule(
        self,
        message: str,
        *,
        max_credits: float = DEFAULT_MAX_CREDITS,
        completed_courses: list[str] | None = None,
        preferred_days: list[str] | None = None,
        selected_courses: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        effective_selected_courses = selected_courses or self._last_schedule_courses
        parsed_preferences = _extract_schedule_preferences(
            message,
            current_courses=effective_selected_courses,
            memory=self._messages,
        )
        schedule_preferences = _merge_persistent_preferences(
            self._last_schedule_preferences,
            parsed_preferences,
        )
        effective_preferred_days = (
            schedule_preferences["preferred_days"] or preferred_days or []
        )
        avoided_section_identifiers = _current_sections_for_different_timing(
            message,
            effective_selected_courses,
            schedule_preferences.get("different_timing_targets") or [],
        )
        avoided_section_identifiers = _dedupe_text([
            *avoided_section_identifiers,
            *_current_sections_for_targeted_time_avoidance(message, effective_selected_courses),
        ])
        lookup_query = _query_with_persisted_campus(message, schedule_preferences)
        result = self._schedule_from_database_run(
            message,
            lookup_query=lookup_query,
            max_credits=extract_max_credits(message, max_credits),
            completed_courses=completed_courses or [],
            preferred_days=effective_preferred_days,
            avoided_days=schedule_preferences["avoided_days"],
            avoided_instructors=schedule_preferences["avoided_instructors"],
            removed_course_identifiers=schedule_preferences["removed_course_identifiers"],
            avoided_section_identifiers=avoided_section_identifiers,
            avoided_time_blocks=schedule_preferences["avoided_time_blocks"],
            selected_courses=effective_selected_courses,
        )
        self._remember(message, result["response"])
        self._remember_schedule(result)
        self._remember_schedule_preferences(schedule_preferences)
        self._remember_schedule_action(message, result, schedule_preferences)
        return result

    def _get_agent(self) -> Any:
        if self._agent:
            return self._agent
        self._agent = create_agent(
            model=get_gemini_llm(),
            tools=TOOLS,
            system_prompt=(
                "You are an academic scheduling assistant. Your main task is to output the most optimal schedule while considering the user's preferences and real course details: campus, days, instructors, and time. Use course_search_tool for discovery, "
                "schedule_generator_tool for schedule requests, and conflict_checker_tool to verify "
                "selected schedules. If the student states a credit target, use it; otherwise use "
                f"{DEFAULT_MAX_CREDITS:g} credits. Deterministic tools enforce constraints; do not invent courses."
            ),
        )
        return self._agent

    def reset_memory(self) -> None:
        self._messages.clear()
        self._last_schedule_courses.clear()
        self._last_schedule_preferences = _empty_schedule_preferences()
        self._schedule_action_history.clear()

    def memory_snapshot(self) -> list[dict[str, str]]:
        return list(self._messages)

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "current_schedule": json.loads(json.dumps(self._last_schedule_courses, default=str)),
            "current_preferences": json.loads(json.dumps(self._last_schedule_preferences, default=str)),
            "schedule_actions": json.loads(json.dumps(self._schedule_action_history, default=str)),
            "message_count": len(self._messages),
        }

    def _schedule_fallback_run(
        self,
        message: str,
        *,
        max_credits: float,
        completed_courses: list[str],
    ) -> dict[str, Any]:
        max_credits = extract_max_credits(message, max_credits)
        schedule_preferences = _extract_schedule_preferences(message)
        retrieval_query = self._contextual_query(message)
        courses = retrieve_relevant_courses(retrieval_query, top_k=40, unique_courses=False)
        generated = generate_optimal_schedules(
            courses,
            max_credits=max_credits,
            completed_courses=completed_courses,
            preferred_days=schedule_preferences["preferred_days"],
            avoided_days=schedule_preferences["avoided_days"],
            avoided_instructors=schedule_preferences["avoided_instructors"],
            removed_course_identifiers=schedule_preferences["removed_course_identifiers"],
            avoided_section_identifiers=[],
            avoided_time_blocks=schedule_preferences["avoided_time_blocks"],
            enforce_prerequisites=bool(completed_courses),
        )
        best = generated["best_schedule"]
        best["explanation"] = _format_schedule_response(best, message)
        return {"response": best["explanation"], "data": generated}

    def _schedule_from_database_run(
        self,
        message: str,
        *,
        lookup_query: str | None = None,
        max_credits: float,
        completed_courses: list[str],
        preferred_days: list[str],
        avoided_days: list[str] | None = None,
        avoided_instructors: list[str] | None = None,
        removed_course_identifiers: list[str] | None = None,
        avoided_section_identifiers: list[str] | None = None,
        avoided_time_blocks: list[dict[str, Any]] | None = None,
        selected_courses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        effective_query = lookup_query or message
        resolved_courses = _resolve_course_names_with_rag(effective_query)
        lookup_courses = resolved_courses or selected_courses
        source = "fastapi_postgres"
        try:
            sections = fetch_postgres_schedule_sections(
                query=effective_query,
                selected_courses=lookup_courses,
            )
        except RuntimeError:
            source = "node_postgres"
            try:
                sections = fetch_exact_schedule_sections(
                    query=effective_query,
                    selected_courses=lookup_courses,
                )
            except RuntimeError:
                sections = []
        if not sections:
            return _empty_schedule_response(message)

        generated = generate_optimal_schedules(
            sections,
            max_credits=max_credits,
            completed_courses=completed_courses,
            preferred_days=preferred_days,
            avoided_days=avoided_days,
            avoided_instructors=avoided_instructors,
            removed_course_identifiers=removed_course_identifiers,
            avoided_section_identifiers=avoided_section_identifiers,
            avoided_time_blocks=avoided_time_blocks,
            enforce_prerequisites=bool(completed_courses),
        )
        best = generated["best_schedule"]
        best["explanation"] = (
            _format_schedule_response(best, message, resolved_courses=resolved_courses)
            if best.get("selected_courses")
            else _no_valid_schedule_response(message, generated)
        )
        generated["source"] = source
        generated["resolved_courses"] = resolved_courses
        generated["lookup_mode"] = "exact_postgres_sections"
        if best.get("selected_courses"):
            best["explanation"] = generate_grounded_response(
                user_request=message,
                task="schedule_generation",
                facts={
                    "schedule": best,
                    "resolved_courses": resolved_courses,
                    "source": source,
                    "lookup_mode": "exact_postgres_sections",
                    "applied_constraints": {
                        "max_credits": max_credits,
                        "preferred_days": preferred_days,
                        "avoided_days": avoided_days or [],
                        "avoided_instructors": avoided_instructors or [],
                        "removed_course_identifiers": removed_course_identifiers or [],
                        "avoided_section_identifiers": avoided_section_identifiers or [],
                        "avoided_time_blocks": avoided_time_blocks or [],
                    },
                    "rejected_conflicts": generated.get("rejected_conflicts", [])[:10],
                },
                memory=self._messages,
                fallback=best["explanation"],
            )
        return {"response": best["explanation"], "data": generated}

    def _course_search_run(self, message: str) -> dict[str, Any]:
        courses = retrieve_relevant_courses(self._contextual_query(message), top_k=10)
        summary = [
            _format_course_result(index, course)
            for index, course in enumerate(courses, start=1)
        ]
        fallback = "Relevant courses:\n" + "\n".join(summary)
        response = generate_grounded_response(
            user_request=message,
            task="course_discovery",
            facts={"results": courses},
            memory=self._messages,
            fallback=fallback,
        )
        return {
            "response": response,
            "data": {"results": json.loads(json.dumps(courses, default=str))},
        }

    def _scheduled_course_description_run(self, message: str) -> dict[str, Any]:
        target = _match_scheduled_course_from_message(message, self._last_schedule_courses)
        if not target:
            response = "Which scheduled course do you want the description for?"
            return {"response": response, "data": {"results": []}}

        query = f"{target.get('course_code')} {target.get('course_name')} course description"
        matches = retrieve_relevant_courses(query, top_k=10)
        target_code = _compact_code(target.get("course_code"))
        selected = next(
            (course for course in matches if _compact_code(course.get("course_code")) == target_code),
            None,
        )
        if not selected:
            selected = {
                "course_code": target.get("course_code"),
                "course_name": target.get("course_name"),
                "description": target.get("description"),
                "department": target.get("department"),
                "department_name": target.get("department_name"),
            }

        response = _format_single_course_description(selected)
        return {
            "response": response,
            "data": {"result": json.loads(json.dumps(selected, default=str))},
        }

    def _conversation_run(self, message: str) -> dict[str, Any]:
        facts = {
            "last_schedule_courses": self._last_schedule_courses,
            "last_schedule_preferences": self._last_schedule_preferences,
            "schedule_action_history": self._schedule_action_history,
            "available_actions": [
                "Ask for a schedule with course names, course codes, CRNs, campus, days, instructor constraints, or credit target.",
                "Ask for courses similar to a topic or description to use ChromaDB semantic search with Qwen reranking.",
            ],
        }
        fallback = (
            "I can help you find LAU courses by description or build a schedule from real section data. "
            "Tell me the courses, campus, days, instructors to avoid, or credit target."
        )
        return {
            "response": generate_grounded_response(
                user_request=message,
                task="general_conversation",
                facts=facts,
                memory=self._messages,
                fallback=fallback,
            ),
            "data": facts,
        }

    def _remember(self, user_message: str, assistant_response: str) -> None:
        self._messages.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_response},
            ]
        )
        if len(self._messages) > MAX_MEMORY_MESSAGES:
            self._messages = self._messages[-MAX_MEMORY_MESSAGES:]

    def _contextual_query(self, message: str) -> str:
        previous_user_messages = [
            item["content"]
            for item in self._messages
            if item.get("role") == "user"
        ][-MAX_CONTEXT_USER_MESSAGES:]
        if not previous_user_messages:
            return message
        context = "\n".join(f"- {item}" for item in previous_user_messages)
        return f"Previous user requests in this chat:\n{context}\n\nCurrent request:\n{message}"

    def _remember_schedule(self, result: dict[str, Any]) -> None:
        data = result.get("data") or {}
        best = data.get("best_schedule") or {}
        selected = best.get("selected_courses") or []
        if selected:
            self._last_schedule_courses = json.loads(json.dumps(selected, default=str))

    def _remember_schedule_preferences(self, preferences: dict[str, list[str]]) -> None:
        persistent_keys = (
            "preferred_days",
            "avoided_days",
            "avoided_instructors",
            "removed_course_identifiers",
            "avoided_time_blocks",
            "campus",
        )
        self._last_schedule_preferences = {}
        for key in persistent_keys:
            values = preferences.get(key, [])
            self._last_schedule_preferences[key] = (
                _dedupe_time_blocks(values)
                if key == "avoided_time_blocks"
                else _dedupe_text(values)
            )

    def _remember_schedule_action(
        self,
        message: str,
        result: dict[str, Any],
        preferences: dict[str, list[str]],
    ) -> None:
        data = result.get("data") or {}
        best = data.get("best_schedule") or {}
        selected = best.get("selected_courses") or []
        action = {
            "user_message": message,
            "selected_courses": [
                {
                    "course_code": course.get("course_code"),
                    "course_name": course.get("course_name"),
                    "section": course.get("section"),
                    "crn": course.get("crn"),
                    "campus": course.get("campus"),
                    "days": course.get("days"),
                    "time": course.get("time"),
                    "instructor": course.get("instructor"),
                }
                for course in selected
            ],
            "constraints": {
                "preferred_days": preferences.get("preferred_days", []),
                "avoided_days": preferences.get("avoided_days", []),
                "avoided_instructors": preferences.get("avoided_instructors", []),
                "removed_course_identifiers": preferences.get("removed_course_identifiers", []),
                "avoided_time_blocks": preferences.get("avoided_time_blocks", []),
                "campus": preferences.get("campus", []),
            },
            "total_credits": best.get("total_credits"),
            "conflict_count": len(best.get("conflicts") or []),
        }
        self._schedule_action_history.append(json.loads(json.dumps(action, default=str)))
        if len(self._schedule_action_history) > 20:
            self._schedule_action_history = self._schedule_action_history[-20:]

    def _should_handle_as_schedule(self, message: str) -> bool:
        if SCHEDULE_INTENT_RE.search(message):
            return True
        course_codes = extract_course_codes(message)
        if course_codes and (
            COURSE_TAKING_RE.search(message)
            or SCHEDULE_CONSTRAINT_RE.search(message)
            or extract_campus(message)
            or len(course_codes) >= 2
        ):
            return True
        return bool(self._last_schedule_courses and SCHEDULE_CONSTRAINT_RE.search(message))

    def _should_handle_as_schedule_course_description(self, message: str) -> bool:
        return bool(self._last_schedule_courses and COURSE_DESCRIPTION_RE.search(message))

    def _should_handle_as_course_search(self, message: str) -> bool:
        if self._last_schedule_courses and SCHEDULE_CONSTRAINT_RE.search(message):
            return False
        return bool(
            COURSE_DISCOVERY_TOPIC_RE.search(message)
            and (
                COURSE_DISCOVERY_ACTION_RE.search(message)
                or re.search(r"\b(similar|related|relevant|involve|involves|about)\b", message, re.IGNORECASE)
            )
        )


def _format_course_result(index: int, course: dict[str, Any]) -> str:
    credits = course.get("credits")
    credits_text = f" | {credits:g} credits" if isinstance(credits, (int, float)) and credits else ""
    description = str(course.get("description") or "").strip()
    description_text = f"\n   {description[:220]}" if description else ""
    department = course.get("department_name") or course.get("department")
    department_text = f" | {department}" if department else ""
    return (
        f"{index}. {course.get('course_code')} - {course.get('course_name')}"
        f"{credits_text}{department_text}{description_text}"
    )


def _format_single_course_description(course: dict[str, Any]) -> str:
    code = course.get("course_code") or "N/A"
    name = course.get("course_name") or "N/A"
    department = course.get("department_name") or course.get("department")
    department_text = f" | {department}" if department else ""
    description = str(course.get("description") or "No description was found for this course.").strip()
    return f"{code} - {name}{department_text}\n{description}"


def _match_scheduled_course_from_message(
    message: str,
    current_courses: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not current_courses:
        return None

    codes = extract_course_codes(message)
    for code in codes:
        compact = _compact_code(code)
        for course in current_courses:
            if _compact_code(course.get("course_code")) == compact:
                return course

    candidates = [
        course
        for course in current_courses
        if _course_matches_any_text(course, [_strip_description_words(message)])
    ]
    if len(candidates) == 1:
        return candidates[0]

    normalized_message = _normalize_identifier(_strip_description_words(message))
    best_course = None
    best_score = 0
    for course in current_courses:
        values = [
            course.get("course_code"),
            course.get("course_name"),
            course.get("title"),
            course.get("crn"),
        ]
        for value in values:
            normalized_value = _normalize_identifier(value)
            if not normalized_value:
                continue
            score = 100 if normalized_value in normalized_message else 0
            if score == 0 and min(len(normalized_value), len(normalized_message)) >= 5:
                try:
                    from rapidfuzz import fuzz

                    score = fuzz.WRatio(normalized_message, normalized_value)
                except Exception:
                    score = 0
            if score > best_score:
                best_score = score
                best_course = course
    return best_course if best_score >= 78 else None


def _strip_description_words(message: str) -> str:
    return re.sub(
        r"\b(description|describe|details?|what\s+is|tell\s+me\s+about|explain|course|class|the|of|for|in\s+my\s+schedule)\b",
        " ",
        message,
        flags=re.IGNORECASE,
    ).strip()


def _resolve_course_names_with_rag(message: str) -> list[dict[str, Any]]:
    return resolve_requested_courses(message)


def _empty_schedule_preferences() -> dict[str, list[str]]:
    return {
        "preferred_days": [],
        "avoided_days": [],
        "avoided_instructors": [],
        "removed_course_identifiers": [],
        "different_timing_targets": [],
        "avoided_time_blocks": [],
        "campus": [],
    }


def _merge_persistent_preferences(
    previous: dict[str, list[str]],
    current: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged = _empty_schedule_preferences()

    if current.get("preferred_days") or current.get("avoided_days"):
        merged["preferred_days"] = current.get("preferred_days", [])
        merged["avoided_days"] = current.get("avoided_days", [])
    else:
        merged["preferred_days"] = previous.get("preferred_days", [])
        merged["avoided_days"] = previous.get("avoided_days", [])

    if current.get("campus"):
        merged["campus"] = current.get("campus", [])
    else:
        merged["campus"] = previous.get("campus", [])

    for key in ("avoided_instructors", "removed_course_identifiers"):
        merged[key] = _dedupe_text([*previous.get(key, []), *current.get(key, [])])

    merged["avoided_time_blocks"] = _dedupe_time_blocks([
        *previous.get("avoided_time_blocks", []),
        *current.get("avoided_time_blocks", []),
    ])

    merged["different_timing_targets"] = current.get("different_timing_targets", [])
    return merged


def _query_with_persisted_campus(message: str, preferences: dict[str, list[str]]) -> str:
    if extract_campus(message):
        return message
    campus = next((item for item in preferences.get("campus", []) if str(item).strip()), "")
    if not campus:
        return message
    return f"{message} in {campus}"


def _extract_schedule_preferences(
    message: str,
    *,
    current_courses: list[dict[str, Any]] | None = None,
    memory: list[dict[str, str]] | None = None,
) -> dict[str, list[str]]:
    preferred_days: list[str] = []
    avoided_days: list[str] = []
    lowered = message.lower()

    if _has_avoid_day_phrase(lowered, "tr"):
        avoided_days = ["Tue", "Thu"]
        preferred_days = ["Mon", "Wed", "Fri"]
    elif _has_avoid_day_phrase(lowered, "mwf"):
        avoided_days = ["Mon", "Wed", "Fri"]
        preferred_days = ["Tue", "Thu"]
    elif _has_positive_day_phrase(lowered, "tr"):
        preferred_days = ["Tue", "Thu"]
    elif _has_positive_day_phrase(lowered, "mwf"):
        preferred_days = ["Mon", "Wed", "Fri"]

    deterministic = {
        "preferred_days": preferred_days,
        "avoided_days": avoided_days,
        "avoided_instructors": _extract_avoided_instructors(message, current_courses or []),
        "removed_course_identifiers": _extract_removed_course_identifiers(message),
        "different_timing_targets": _extract_timing_change_targets(message),
        "avoided_time_blocks": _extract_avoided_time_blocks(message),
        "targeted_time_avoidance_targets": [
            target["course"]
            for target in _extract_targeted_time_avoidance_targets(message)
            if target.get("course")
        ],
    }
    if _has_actionable_preferences(deterministic):
        return deterministic

    gemini = extract_schedule_constraints_with_gemini(
        user_request=message,
        current_schedule=current_courses or [],
        memory=memory or [],
    )
    return _merge_schedule_preferences(deterministic, gemini)


def _current_sections_for_different_timing(
    message: str,
    current_courses: list[dict[str, Any]],
    explicit_targets: list[str] | None = None,
) -> list[str]:
    if not current_courses or not re.search(r"\b(different|another|other|change|switch)\b[^.?!]*\b(time|timing|section)\b", message, re.IGNORECASE):
        return []

    targets = _dedupe_text([*_extract_timing_change_targets(message), *(explicit_targets or [])])
    matched_courses = [
        course
        for course in current_courses
        if not targets or _course_matches_any_text(course, targets)
    ]
    identifiers: list[str] = []
    for course in matched_courses:
        for key in ("crn", "id"):
            value = course.get(key)
            if value not in (None, ""):
                identifiers.append(str(value))
        course_code = str(course.get("course_code") or "")
        section = str(course.get("section") or "")
        if course_code and section:
            identifiers.append(f"{course_code}{section}")
    return _dedupe_text(identifiers)


def _current_sections_for_targeted_time_avoidance(
    message: str,
    current_courses: list[dict[str, Any]],
) -> list[str]:
    if not current_courses:
        return []

    targets = _extract_targeted_time_avoidance_targets(message)
    if not targets:
        return []

    identifiers: list[str] = []
    for target in targets:
        target_texts = [target["course"]]
        target_time = parse_time_value(target["time"])
        for course in current_courses:
            if not _course_matches_any_text(course, target_texts):
                continue
            if target_time and not _course_matches_time(course, target_time):
                continue
            identifiers.extend(_section_identifiers(course))
    return _dedupe_text(identifiers)


def _extract_targeted_time_avoidance_targets(message: str) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    avoid_prefix = r"(?:do not want|don't want|dont want|avoid|without|no|not)"
    patterns = [
        rf"\b{avoid_prefix}\b\s+(?P<course>[^.?!,]+?)\s+(?:at|around|by)\s+(?P<time>\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)?)\b",
        rf"\b(?P<course>[^.?!,]+?)\s+(?:should\s+)?(?:not|never)\s+(?:be\s+)?(?:at|around|by)\s+(?P<time>\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)?)\b",
        rf"\b(?:move|change|switch)\s+(?P<course>[^.?!,]+?)\s+(?:away\s+from|from)\s+(?P<time>\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)?)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, message, re.IGNORECASE):
            course = _clean_time_avoidance_course(match.group("course"))
            time_text = _infer_bare_time_meridiem(match.group("time"), "unavailable time")
            if course and time_text:
                targets.append({"course": course, "time": time_text})
    return targets


def _clean_time_avoidance_course(value: str) -> str:
    cleaned = re.sub(
        r"^(?:i\s+)?(?:do not want|don't want|dont want|avoid|without|no|not|the|this|course|class)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" ,;")


def _course_matches_time(course: dict[str, Any], target_time: Any) -> bool:
    start = parse_time_value(course.get("start_time"))
    end = parse_time_value(course.get("end_time"))
    if not start:
        return False
    if start == target_time:
        return True
    if end and start <= target_time < end:
        return True
    return False


def _section_identifiers(course: dict[str, Any]) -> list[str]:
    identifiers: list[str] = []
    for key in ("crn", "id"):
        value = course.get(key)
        if value not in (None, ""):
            identifiers.append(str(value))
    course_code = str(course.get("course_code") or "")
    section = str(course.get("section") or "")
    if course_code and section:
        identifiers.append(f"{course_code}{section}")
    return identifiers


def _extract_timing_change_targets(message: str) -> list[str]:
    targets: list[str] = []
    patterns = [
        r"\b(?:need|want|make|change|switch|move)\s+(?P<target>[^.?!]+?)\s+(?:in|to|at)?\s*(?:a\s+)?(?:different|another|other|new)\s+(?:time|timing|section)\b",
        r"\b(?:for|of|in)\s+(?P<target>[^.?!]+?)\s+(?:to\s+)?(?:a\s+)?(?:different|another|other|new)\s+(?:time|timing|section)\b",
        r"\b(?:change|switch)\s+(?P<target>[^.?!]+?)\s+(?:time|timing|section)\b",
        r"\b(?P<target>[^.?!]+?)\s+(?:in\s+)?(?:a\s+)?(?:different|another|other|new)\s+(?:time|timing|section)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, message, re.IGNORECASE):
            target = _trim_target_phrase(match.group("target"))
            target = _clean_timing_target(target)
            if target and not _is_generic_timing_target(target):
                targets.append(target)
    return _dedupe_text(targets)


def _clean_timing_target(target: str) -> str:
    cleaned = re.sub(
        r"^(?:i\s+)?(?:need|want|would like|give me|make|change|switch|move|put|course|class|section|the|this)\s+",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"\s+(?:in|to|at|with)$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.strip(" ,;")


def _is_generic_timing_target(target: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", target.lower()).strip()
    return normalized in {"", "a", "an", "i", "me", "give me", "schedule", "the schedule", "it", "this"}


def _course_matches_any_text(course: dict[str, Any], targets: list[str]) -> bool:
    values = [
        course.get("course_code"),
        course.get("course_id"),
        course.get("course_name"),
        course.get("title"),
        course.get("crn"),
        course.get("id"),
    ]
    normalized_values = [_normalize_identifier(value) for value in values if value not in (None, "")]
    normalized_targets = [_normalize_identifier(target) for target in targets if _normalize_identifier(target)]
    for target in normalized_targets:
        for value in normalized_values:
            if target == value or target in value or value in target:
                return True
            if min(len(target), len(value)) >= 5:
                try:
                    from rapidfuzz import fuzz

                    if fuzz.WRatio(target, value) >= 84:
                        return True
                except Exception:
                    continue
    return False


def _normalize_identifier(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _has_avoid_day_phrase(text: str, pattern: str) -> bool:
    variants = _day_pattern_variants(pattern)
    avoid_prefix = r"(?:do not want|don't want|dont want|do not need|don't need|dont need|avoid|without|no|not)"
    return any(re.search(rf"\b{avoid_prefix}\b[^.?!]*\b{variant}\b", text) for variant in variants)


def _has_positive_day_phrase(text: str, pattern: str) -> bool:
    variants = _day_pattern_variants(pattern)
    positive_prefix = r"(?:want|prefer|give me|schedule|only|all|make|change|switch|move|set|use)"
    return any(re.search(rf"\b{positive_prefix}\b[^.?!]*\b{variant}\b", text) for variant in variants)


def _day_pattern_variants(pattern: str) -> list[str]:
    if pattern == "tr":
        return [
            r"tr",
            r"t/r",
            r"tuesday\s+(?:and\s+)?thursday",
            r"tue(?:sday)?\s+(?:and\s+)?thu(?:rsday)?",
        ]
    return [
        r"mwf",
        r"m/w/f",
        r"monday\s+wednesday\s+friday",
        r"mon(?:day)?\s+wed(?:nesday)?\s+fri(?:day)?",
    ]


def _merge_schedule_preferences(
    deterministic: dict[str, list[str]],
    gemini: dict[str, Any],
) -> dict[str, list[str]]:
    merged = {key: list(value) for key, value in deterministic.items()}

    preferred_days = _normalize_constraint_days(gemini.get("preferred_days"))
    avoided_days = _normalize_constraint_days(gemini.get("avoided_days"))
    if preferred_days:
        merged["preferred_days"] = _dedupe_text([*merged.get("preferred_days", []), *preferred_days])
    if avoided_days:
        merged["avoided_days"] = _dedupe_text([*merged.get("avoided_days", []), *avoided_days])

    for key in ("avoided_instructors", "removed_course_identifiers", "different_timing_targets"):
        values = _normalize_constraint_list(gemini.get(key))
        if values:
            merged[key] = _dedupe_text([*merged.get(key, []), *values])
    time_blocks = _normalize_time_block_constraints(gemini.get("avoided_time_blocks"))
    if time_blocks:
        merged["avoided_time_blocks"] = _dedupe_time_blocks([
            *merged.get("avoided_time_blocks", []),
            *time_blocks,
        ])

    campus = str(gemini.get("campus") or "").strip()
    if campus:
        merged["campus"] = [campus]

    return merged


def _has_actionable_preferences(preferences: dict[str, list[str]]) -> bool:
    return any(
        preferences.get(key)
        for key in (
            "preferred_days",
            "avoided_days",
            "avoided_instructors",
            "removed_course_identifiers",
            "different_timing_targets",
            "avoided_time_blocks",
            "targeted_time_avoidance_targets",
        )
    )


def _normalize_constraint_days(value: Any) -> list[str]:
    days: list[str] = []
    for item in _normalize_constraint_list(value):
        lowered = item.lower()
        if lowered in {"mwf", "m/w/f", "monday wednesday friday"}:
            days.extend(["Mon", "Wed", "Fri"])
        elif lowered in {"tr", "t/r", "tuesday thursday", "tuesday and thursday"}:
            days.extend(["Tue", "Thu"])
        else:
            days.extend(normalize_days(item))
    return _dedupe_text(days)


def _normalize_constraint_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    return [
        re.sub(r"\s+", " ", str(item).strip())
        for item in items
        if str(item or "").strip()
    ]


def _normalize_time_block_constraints(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    blocks: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        days = _normalize_constraint_days(item.get("days")) or ["Mon", "Tue", "Wed", "Thu", "Fri"]
        start = parse_time_value(item.get("start_time"))
        end = parse_time_value(item.get("end_time"))
        if not start or not end or end <= start:
            continue
        blocks.append(
            {
                "label": str(item.get("label") or "unavailable time").strip() or "unavailable time",
                "days": days,
                "start_time": start.strftime("%H:%M"),
                "end_time": end.strftime("%H:%M"),
            }
        )
    return blocks


def _dedupe_time_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen = set()
    for block in _normalize_time_block_constraints(blocks):
        key = (
            tuple(block.get("days") or []),
            block.get("start_time"),
            block.get("end_time"),
            str(block.get("label") or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(block)
    return deduped


def _extract_avoided_time_blocks(message: str) -> list[dict[str, Any]]:
    if not _has_time_constraint_cue(message):
        return []

    blocks: list[dict[str, Any]] = []
    days = _extract_constraint_days_from_text(message)
    label = _extract_time_block_label(message)

    for start_raw, end_raw in _extract_relative_time_ranges(message):
        block = _make_time_block(label, days, start_raw, end_raw)
        if block:
            blocks.append(block)

    for match in re.finditer(
        r"\b(?P<start>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:-|to|until|till)\s*(?P<end>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
        message,
        re.IGNORECASE,
    ):
        start_raw, end_raw = _inherit_meridiem_text(match.group("start"), match.group("end"))
        block = _make_time_block(label, days, start_raw, end_raw)
        if block:
            blocks.append(block)

    if blocks:
        return _dedupe_time_blocks(blocks)

    for match in re.finditer(
        r"\b(?:at|around|by|from)?\s*(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
        message,
        re.IGNORECASE,
    ):
        start = parse_time_value(match.group("time"))
        if not start:
            continue
        end_dt = datetime.combine(datetime.today(), start) + timedelta(hours=1)
        blocks.append(
            {
                "label": label,
                "days": days,
                "start_time": start.strftime("%H:%M"),
                "end_time": end_dt.time().strftime("%H:%M"),
            }
        )

    for match in re.finditer(
        r"\b(?:at|around|by)\s+(?P<time>\d{1,2}(?::\d{2})?)\b",
        message,
        re.IGNORECASE,
    ):
        time_text = _infer_bare_time_meridiem(match.group("time"), label)
        start = parse_time_value(time_text)
        if not start:
            continue
        end_dt = datetime.combine(datetime.today(), start) + timedelta(hours=1)
        blocks.append(
            {
                "label": label,
                "days": days,
                "start_time": start.strftime("%H:%M"),
                "end_time": end_dt.time().strftime("%H:%M"),
            }
        )

    return _dedupe_time_blocks(blocks)


def _has_time_constraint_cue(message: str) -> bool:
    return bool(
        re.search(
            r"\b(avoid|without|no\s+class|no\s+classes|not\s+available|unavailable|busy|breakfast|lunch|dinner|work|job|meeting|commute|gym|appointment|free)\b",
            message,
            re.IGNORECASE,
        )
        and re.search(
            r"\b(?:at|around|by|from)?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b|\bnoon|midnight|morning|afternoon|evening\b",
            message,
            re.IGNORECASE,
        )
    )


def _extract_constraint_days_from_text(message: str) -> list[str]:
    lowered = message.lower()
    if re.search(r"\b(daily|every\s+day|weekdays?|mon(?:day)?\s*(?:to|-)\s*fri(?:day)?)\b", lowered):
        return ["Mon", "Tue", "Wed", "Thu", "Fri"]
    if re.search(r"\btr|t/r|tuesday\s+(?:and\s+)?thursday\b", lowered):
        return ["Tue", "Thu"]
    if re.search(r"\bmwf|m/w/f|monday\s+wednesday\s+friday\b", lowered):
        return ["Mon", "Wed", "Fri"]

    days: list[str] = []
    for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"):
        if re.search(rf"\b{day.lower()}\b", lowered):
            days.extend(normalize_days(day))
    return _dedupe_text(days) or ["Mon", "Tue", "Wed", "Thu", "Fri"]


def _extract_time_block_label(message: str) -> str:
    for label in ("breakfast", "lunch", "dinner", "work", "job", "meeting", "commute", "gym", "appointment"):
        if re.search(rf"\b{label}\b", message, re.IGNORECASE):
            return label
    return "unavailable time"


def _extract_relative_time_ranges(message: str) -> list[tuple[str, str]]:
    ranges: list[tuple[str, str]] = []
    lowered = message.lower()

    if re.search(r"\bbefore\s+noon\b|\bbefore\s+lunch\b", lowered):
        ranges.append(("08:00", "12:00"))
    if re.search(r"\bmorning\b", lowered) and re.search(r"\b(avoid|busy|unavailable|commute|work|no\s+class|no\s+classes|cannot|can't)\b", lowered):
        ranges.append(("08:00", "12:00"))
    if re.search(r"\bafternoon\b", lowered) and re.search(r"\b(avoid|busy|unavailable|work|no\s+class|no\s+classes|cannot|can't)\b", lowered):
        ranges.append(("12:00", "18:00"))
    if re.search(r"\bevening\b", lowered) and re.search(r"\b(avoid|busy|unavailable|work|no\s+class|no\s+classes|cannot|can't)\b", lowered):
        ranges.append(("17:00", "23:00"))

    for match in re.finditer(
        r"\bafter\s+(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
        message,
        re.IGNORECASE,
    ):
        start = parse_time_value(_infer_bare_time_meridiem(match.group("time"), "unavailable time"))
        if start:
            ranges.append((start.strftime("%H:%M"), "23:00"))

    for match in re.finditer(
        r"\bbefore\s+(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
        message,
        re.IGNORECASE,
    ):
        end = parse_time_value(_infer_bare_time_meridiem(match.group("time"), "unavailable time"))
        if end:
            ranges.append(("08:00", end.strftime("%H:%M")))

    return ranges


def _make_time_block(label: str, days: list[str], start_raw: str, end_raw: str) -> dict[str, Any] | None:
    start = parse_time_value(start_raw)
    end = parse_time_value(end_raw)
    if not start or not end or end <= start:
        return None
    return {
        "label": label,
        "days": days,
        "start_time": start.strftime("%H:%M"),
        "end_time": end.strftime("%H:%M"),
    }


def _inherit_meridiem_text(start: str, end: str) -> tuple[str, str]:
    if re.search(r"\b(am|pm)\b", start, re.IGNORECASE):
        return start, end
    meridiem = re.search(r"\b(am|pm)\b", end, re.IGNORECASE)
    if not meridiem:
        return start, end
    return f"{start} {meridiem.group(1)}", end


def _infer_bare_time_meridiem(value: str, label: str) -> str:
    if re.search(r"\b(am|pm)\b", value, re.IGNORECASE):
        return value
    hour_match = re.match(r"\s*(\d{1,2})", value)
    if not hour_match:
        return value
    hour = int(hour_match.group(1))
    normalized_label = label.lower()
    if normalized_label == "breakfast":
        return f"{value} AM"
    if normalized_label in {"lunch", "dinner"} and hour < 12:
        return f"{value} PM"
    return value


def _extract_avoided_instructors(message: str, current_courses: list[dict[str, Any]] | None = None) -> list[str]:
    patterns = [
        r"\b(?:avoid|without|not with|do not want|don't want|dont want|do not give me|don't give me|dont give me|no|not)\b[^.?!]*\b(?:with|by)\s+(?P<names>[^\n?!.,]+)",
        r"\b(?:avoid|without|not with|do not want|don't want|dont want)\s+(?:with\s+)?(?:instructors?|professors?|profs?)\s+(?P<names>[^\n?!]+)",
        r"\b(?:avoid|without|not with|do not want|don't want|dont want)\s+(?:with\s+)?(?P<names>dr\.?\s+[^\n?!]+)",
        r"\b(?:with|by)\s+anyone\s+except\s+(?P<names>[^\n?!]+)",
        r"\b(?:avoid|without|not with|do not want|don't want|dont want|no|not)\s+(?:with\s+)?(?P<names>[A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,4})",
    ]
    names: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, message, re.IGNORECASE):
            raw_names = match.group("names")
            names.extend(_split_instructor_names(raw_names))
    names.extend(_extract_current_instructor_mentions(message, current_courses or []))
    return _dedupe_text([name for name in names if _is_plausible_instructor_name(name)])


def _extract_current_instructor_mentions(
    message: str,
    current_courses: list[dict[str, Any]],
) -> list[str]:
    if not re.search(r"\b(?:avoid|without|not with|do not want|don't want|dont want|no|not)\b", message, re.IGNORECASE):
        return []

    normalized_message = _normalize_identifier(message)
    matched: list[str] = []
    for course in current_courses:
        instructor = str(course.get("instructor") or "").strip()
        if not instructor or instructor == "N/A":
            continue
        normalized_instructor = _normalize_identifier(instructor)
        tokens = [
            token
            for token in re.split(r"[^A-Za-z0-9]+", instructor)
            if len(token) >= 3 and token.lower() not in {"dr", "prof", "professor"}
        ]
        if normalized_instructor and normalized_instructor in normalized_message:
            matched.append(instructor)
            continue
        if any(re.search(rf"\b{re.escape(token)}\b", message, re.IGNORECASE) for token in tokens):
            matched.append(instructor)
    return matched


def _is_plausible_instructor_name(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    if not normalized:
        return False
    if normalized in {"i", "me", "my", "mine", "we", "us", "our", "you", "your"}:
        return False
    if normalized in {
        "mwf",
        "tr",
        "beirut",
        "byblos",
        "jbeil",
        "jbiel",
        "course",
        "courses",
        "section",
        "sections",
        "timing",
        "time",
        "schedule",
    }:
        return False
    if set(normalized.split()) & {
        "any",
        "because",
        "before",
        "after",
        "class",
        "classes",
        "course",
        "courses",
        "give",
        "have",
        "morning",
        "noon",
        "afternoon",
        "evening",
        "then",
        "at",
    }:
        return False
    if _is_day_like_text(normalized):
        return False
    if extract_course_codes(normalized):
        return False
    return any(character.isalpha() for character in normalized)


def _is_day_like_text(value: str) -> bool:
    compact = re.sub(r"[^a-z]+", "", value.lower())
    return compact in {
        "m",
        "t",
        "w",
        "r",
        "f",
        "mwf",
        "tr",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "mondaywednesdayfriday",
        "tuesdaythursday",
    }


def _extract_removed_course_identifiers(message: str) -> list[str]:
    identifiers: list[str] = []
    action_pattern = r"\b(?:remove|drop|delete|take out|exclude)\b"
    for match in re.finditer(rf"{action_pattern}\s+(?:course\s+|class\s+|section\s+)?(?P<target>[^.?!]+)", message, re.IGNORECASE):
        target = _trim_target_phrase(match.group("target"))
        identifiers.extend(extract_course_codes(target))
        identifiers.extend(re.findall(r"\b\d{4,6}\b", target))
        if not identifiers and target:
            identifiers.append(target)
        elif target and not extract_course_codes(target) and not re.search(r"\b\d{4,6}\b", target):
            identifiers.append(target)
    return _dedupe_text(identifiers)


def _trim_target_phrase(value: str) -> str:
    cleaned = re.split(
        r"\b(?:from|and rebuild|and generate|and make|then|please|because)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return cleaned.strip(" ,;")


def _split_instructor_names(raw_names: str) -> list[str]:
    cleaned = re.sub(r"\b(?:please|for|in|on|courses?|sections?)\b.*$", "", raw_names, flags=re.IGNORECASE).strip()
    cleaned = cleaned.rstrip(". ")
    parts = re.split(r"\s*(?:,|;|\band\b|\bor\b)\s*", cleaned, flags=re.IGNORECASE)
    return [
        re.sub(r"\s+", " ", part.replace("Dr.", "").replace("dr.", "").strip())
        for part in parts
        if part.strip()
    ]


def _dedupe_text(items: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for item in items:
        key = item.lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _empty_schedule_response(message: str) -> dict[str, Any]:
    requested = extract_course_codes(message)
    requested_terms = extract_search_terms(message)
    requested_text = ", ".join(requested or requested_terms) if (requested or requested_terms) else "the requested courses"
    explanation = (
        f"No LAU section data was returned for {requested_text}. "
        "I did not generate a schedule because there are no real sections, times, or campuses to use."
    )
    empty_schedule = {
        "selected_courses": [],
        "total_credits": 0.0,
        "score": 0.0,
        "conflicts": [],
        "explanation": explanation,
    }
    return {
        "response": explanation,
        "data": {
            "best_schedule": empty_schedule,
            "alternative_schedules": [],
            "rejected_conflicts": [],
            "source": "node_postgres",
        },
    }


def _no_valid_schedule_response(message: str, generated: dict[str, Any]) -> str:
    requested = extract_course_codes(message)
    requested_text = ", ".join(requested) if requested else "the requested courses"
    rejected = generated.get("rejected_conflicts") or []
    explanation = (
        f"LAU section data was found for {requested_text}, but no valid schedule could be created "
        "with the current constraints."
    )
    if rejected:
        reasons = []
        for item in rejected[:5]:
            code = item.get("course_code") or "Unknown course"
            section = item.get("section") or "N/A"
            reason = item.get("reason") or "Rejected by scheduler constraints."
            reasons.append(f"- {code} section {section}: {reason}")
        explanation += "\n" + "\n".join(reasons)
    return explanation


def _format_schedule_response(
    schedule: dict[str, Any],
    message: str,
    *,
    resolved_courses: list[dict[str, Any]] | None = None,
) -> str:
    selected = schedule.get("selected_courses") or []
    requested = extract_course_codes(message) or [
        str(course.get("course_code"))
        for course in (resolved_courses or [])
        if course.get("course_code")
    ]
    missing = _missing_requested_courses(requested, selected)
    total_credits = float(schedule.get("total_credits") or 0)
    weekly_hours = _weekly_hours(selected)
    conflicts = schedule.get("conflicts") or []

    if not selected:
        return _empty_schedule_response(message)["response"]

    lines = ["Suggested LAU schedule:"]
    lines.extend(_format_section_line(index, course) for index, course in enumerate(selected, start=1))
    lines.append("")
    lines.append("Summary:")
    lines.append(f"- Courses scheduled: {len(selected)}")
    lines.append(f"- Total credits: {total_credits:g}")
    lines.append(f"- Weekly hours: {weekly_hours:g}")
    if conflicts:
        lines.append(f"- Conflicts: {len(conflicts)}")
    if missing:
        lines.append(f"- Not scheduled: {', '.join(missing)}")
    return "\n".join(lines)


def _format_section_line(index: int, course: dict[str, Any]) -> str:
    code = course.get("course_code") or "N/A"
    name = course.get("course_name") or "N/A"
    section = course.get("section") or "N/A"
    campus = course.get("campus") or "N/A"
    days = _display_days(course.get("days"))
    start = course.get("start_time") or "N/A"
    end = course.get("end_time") or "N/A"
    instructor = course.get("instructor") or "N/A"
    room = course.get("room") or "N/A"
    return (
        f"{index}. {code} - {name} | Sec {section} | {campus} | "
        f"{days} {start}-{end} | {instructor} | {room}"
    )


def _missing_requested_courses(requested: list[str], selected: list[dict[str, Any]]) -> list[str]:
    selected_codes = {_compact_code(course.get("course_code")) for course in selected}
    return [code for code in requested if _compact_code(code) not in selected_codes]


def _compact_code(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").upper())


def _display_days(value: Any) -> str:
    if isinstance(value, list):
        return "/".join(str(item) for item in value) if value else "N/A"
    days = normalize_days(value)
    return "/".join(days) if days else str(value or "N/A")


def _weekly_hours(courses: list[dict[str, Any]]) -> float:
    total_minutes = 0
    for course in courses:
        start = parse_time_value(course.get("start_time"))
        end = parse_time_value(course.get("end_time"))
        if not start or not end:
            continue
        day_count = len(normalize_days(course.get("days")))
        start_minutes = start.hour * 60 + start.minute
        end_minutes = end.hour * 60 + end.minute
        if end_minutes > start_minutes:
            total_minutes += (end_minutes - start_minutes) * day_count
    return round(total_minutes / 60, 2)
