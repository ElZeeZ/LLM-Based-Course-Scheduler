from __future__ import annotations

import json
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


GEMINI_FLASH_MODEL = "gemini-2.5-flash"


def get_gemini_llm() -> ChatGoogleGenerativeAI:
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is required for Gemini 2.5 Flash.")
    return ChatGoogleGenerativeAI(
        model=GEMINI_FLASH_MODEL,
        google_api_key=settings.gemini_api_key,
        temperature=0.2,
    )


def generate_schedule_explanation(schedule: dict[str, Any], user_request: str) -> str:
    try:
        llm = get_gemini_llm()
        response = llm.invoke(
            "Explain this deterministic course schedule clearly. "
            "Do not invent courses or alter constraints.\n\n"
            f"User request: {user_request}\n"
            f"Schedule data: {schedule}"
        )
        return str(response.content)
    except Exception:
        selected = schedule.get("selected_courses", [])
        credits = schedule.get("total_credits", 0)
        return f"Selected {len(selected)} non-conflicting course section(s), totaling {credits} credits."


def generate_grounded_response(
    *,
    user_request: str,
    task: str,
    facts: dict[str, Any],
    memory: list[dict[str, str]] | None = None,
    fallback: str,
) -> str:
    try:
        llm = get_gemini_llm()
        response = llm.invoke(
            "You are a conversational LAU course scheduling assistant. "
            "Use the chat memory to understand follow-up requests and constraints. "
            "Use only the grounded facts provided below for course names, sections, instructors, "
            "campuses, days, times, credits, conflicts, and search results. "
            "Do not invent courses, sections, database records, scores, prerequisites, or policies. "
            "If facts are missing, say exactly what is missing and ask for the next useful input. "
            "For schedule answers, mention the applied constraints and give a concise schedule list. "
            "Only mention a conflict if the grounded schedule conflicts list is non-empty. "
            "For course discovery answers, list the relevant courses in ranked order without scores. "
            "Put each course on its own line using this exact shape: "
            "1. CODE - COURSE NAME | Department\n   One concise description sentence. "
            "For normal conversation, answer naturally but stay within the project context.\n\n"
            f"Task: {task}\n"
            f"User request: {user_request}\n"
            f"Chat memory: {json.dumps((memory or [])[-10:], ensure_ascii=False, default=str)}\n"
            f"Grounded facts: {json.dumps(facts, ensure_ascii=False, default=str)}"
        )
        text = str(response.content).strip()
        return text or fallback
    except Exception:
        return fallback


def extract_schedule_constraints_with_gemini(
    *,
    user_request: str,
    current_schedule: list[dict[str, Any]] | None = None,
    memory: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    try:
        llm = get_gemini_llm()
        response = llm.invoke(
            "Extract schedule constraints from the user's latest message. "
            "Return only valid JSON, no markdown. "
            "You may reason over the wording and recent chat context to infer constraints a human advisor would understand, "
            "but do not invent actual course sections, instructors, or database records. "
            "Use current_schedule only to resolve vague references like 'this course', 'that instructor', "
            "'circuits', misspelled course titles, or partial instructor names already present in the schedule.\n\n"
            "JSON schema:\n"
            "{"
            "\"preferred_days\": string[], "
            "\"avoided_days\": string[], "
            "\"avoided_instructors\": string[], "
            "\"removed_course_identifiers\": string[], "
            "\"different_timing_targets\": string[], "
            "\"avoided_time_blocks\": {\"label\": string, \"days\": string[], \"start_time\": string, \"end_time\": string}[], "
            "\"campus\": string|null"
            "}\n\n"
            "Use day names or common groups exactly as stated: MWF, TR, Monday, Tuesday, etc. "
            "Use instructor names exactly as written or as present in current_schedule. "
            "Phrases like 'not with X', 'avoid X', 'do not give me any course with X', "
            "'not by X', or 'without professor X' mean avoided_instructors contains X. "
            "Use course code, CRN, course title, or user wording for removed_course_identifiers and different_timing_targets. "
            "For avoided_time_blocks, extract any outside commitment or unavailable time: breakfast, lunch, dinner, work, commute, meetings, gym, appointments, study blocks, prayer, sleep, family obligations, or any phrase where the user says they are busy, unavailable, occupied, free only after/before, cannot attend, or wants no class at a time. "
            "Infer reasonable AM/PM from context when the user omits it, for example breakfast is morning, lunch is midday, dinner is evening, 'morning' means AM, and 'afternoon/evening' means PM. "
            "If a single time is given, use a one-hour unavailable block unless the user specified a duration. "
            "If the user says daily/every day/weekdays, use Monday through Friday. "
            "If the user gives a range like 'after 3', 'before noon', 'before lunch', "
            "'after 2 PM', or 'between 10 and 12', convert it to concrete avoided_time_blocks when possible. "
            "Use noon as 12:00 and midnight as 00:00.\n\n"
            f"User request: {user_request}\n"
            f"Recent chat memory: {json.dumps((memory or [])[-8:], ensure_ascii=False, default=str)}\n"
            f"Current schedule: {json.dumps(current_schedule or [], ensure_ascii=False, default=str)}"
        )
        content = str(response.content).strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}
