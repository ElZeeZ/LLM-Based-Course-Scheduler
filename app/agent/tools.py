from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from app.rag.retriever import retrieve_relevant_courses
from app.scheduler.constraints import check_schedule_conflicts
from app.scheduler.optimizer import generate_optimal_schedules


@tool
def course_search_tool(query: str) -> str:
    """Search university courses semantically with RAG."""
    courses = retrieve_relevant_courses(query, top_k=10)
    return json.dumps(courses, ensure_ascii=False)


@tool
def schedule_generator_tool(request: str) -> str:
    """Generate a deterministic non-conflicting schedule for an academic request."""
    courses = retrieve_relevant_courses(request, top_k=50, unique_courses=False)
    schedule = generate_optimal_schedules(courses, max_credits=_extract_max_credits(request))
    return json.dumps(schedule, ensure_ascii=False)


@tool
def conflict_checker_tool(schedule_json: str) -> str:
    """Check selected course sections for day/time conflicts."""
    try:
        payload: Any = json.loads(schedule_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "Input must be JSON."})
    courses = payload.get("selected_courses", payload if isinstance(payload, list) else [])
    return json.dumps({"conflicts": check_schedule_conflicts(courses)}, ensure_ascii=False)


TOOLS = [course_search_tool, schedule_generator_tool, conflict_checker_tool]


def _extract_max_credits(text: str) -> float:
    import re

    match = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?credit", text, re.IGNORECASE)
    return float(match.group(1)) if match else 15.0
