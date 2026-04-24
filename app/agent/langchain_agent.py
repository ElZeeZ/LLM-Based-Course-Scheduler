from __future__ import annotations

import json
import re
from typing import Any

from langchain.agents import create_agent

from app.agent.tools import TOOLS
from app.llm.gemini_client import generate_schedule_explanation, get_gemini_llm
from app.rag.retriever import retrieve_relevant_courses
from app.scheduler.optimizer import generate_optimal_schedules


SCHEDULE_INTENT_RE = re.compile(r"\b(schedule|timetable|plan|semester|credits?)\b", re.IGNORECASE)


class AcademicAgent:
    def __init__(self) -> None:
        self._agent: Any | None = None

    def run(
        self,
        message: str,
        *,
        max_credits: float = 15,
        completed_courses: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            agent = self._get_agent()
            result = agent.invoke({"messages": [{"role": "user", "content": message}]})
            messages = result.get("messages", [])
            content = messages[-1].content if messages else ""
            return {"response": str(content), "data": None}
        except Exception:
            return self._fallback_run(
                message,
                max_credits=max_credits,
                completed_courses=completed_courses or [],
            )

    def _get_agent(self) -> Any:
        if self._agent:
            return self._agent
        self._agent = create_agent(
            model=get_gemini_llm(),
            tools=TOOLS,
            system_prompt=(
                "You are an academic scheduling assistant. Use course_search_tool for discovery, "
                "schedule_generator_tool for schedule requests, and conflict_checker_tool to verify "
                "selected schedules. Deterministic tools enforce constraints; do not invent courses."
            ),
        )
        return self._agent

    def _fallback_run(
        self,
        message: str,
        *,
        max_credits: float,
        completed_courses: list[str],
    ) -> dict[str, Any]:
        if SCHEDULE_INTENT_RE.search(message):
            courses = retrieve_relevant_courses(message, top_k=50, unique_courses=False)
            generated = generate_optimal_schedules(
                courses,
                max_credits=max_credits,
                completed_courses=completed_courses,
            )
            best = generated["best_schedule"]
            best["explanation"] = generate_schedule_explanation(best, message)
            return {"response": best["explanation"], "data": generated}

        courses = retrieve_relevant_courses(message, top_k=10)
        summary = [
            f"{course.get('course_code')} {course.get('course_name')} section {course.get('section')}"
            for course in courses[:5]
        ]
        return {
            "response": "Relevant courses:\n" + "\n".join(summary),
            "data": {"results": json.loads(json.dumps(courses, default=str))},
        }
