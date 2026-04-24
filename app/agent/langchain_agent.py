from __future__ import annotations

import json
import re
from typing import Any

from langchain.agents import create_agent

from app.agent.preferences import DEFAULT_MAX_CREDITS, extract_max_credits
from app.agent.tools import TOOLS
from app.llm.gemini_client import generate_schedule_explanation, get_gemini_llm
from app.rag.retriever import retrieve_relevant_courses
from app.scheduler.optimizer import generate_optimal_schedules


SCHEDULE_INTENT_RE = re.compile(r"\b(schedule|timetable|plan|semester|credits?)\b", re.IGNORECASE)
MAX_MEMORY_MESSAGES = 20
MAX_CONTEXT_USER_MESSAGES = 4


class AcademicAgent:
    def __init__(self) -> None:
        self._agent: Any | None = None
        self._messages: list[dict[str, str]] = []

    def run(
        self,
        message: str,
        *,
        max_credits: float = DEFAULT_MAX_CREDITS,
        completed_courses: list[str] | None = None,
    ) -> dict[str, Any]:
        if not SCHEDULE_INTENT_RE.search(message):
            result = self._course_search_run(message)
            self._remember(message, result["response"])
            return result

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

    def _get_agent(self) -> Any:
        if self._agent:
            return self._agent
        self._agent = create_agent(
            model=get_gemini_llm(),
            tools=TOOLS,
            system_prompt=(
                "You are an academic scheduling assistant. Use course_search_tool for discovery, "
                "schedule_generator_tool for schedule requests, and conflict_checker_tool to verify "
                "selected schedules. If the student states a credit target, use it; otherwise use "
                f"{DEFAULT_MAX_CREDITS:g} credits. Deterministic tools enforce constraints; do not invent courses."
            ),
        )
        return self._agent

    def reset_memory(self) -> None:
        self._messages.clear()

    def memory_snapshot(self) -> list[dict[str, str]]:
        return list(self._messages)

    def _schedule_fallback_run(
        self,
        message: str,
        *,
        max_credits: float,
        completed_courses: list[str],
    ) -> dict[str, Any]:
        max_credits = extract_max_credits(message, max_credits)
        retrieval_query = self._contextual_query(message)
        courses = retrieve_relevant_courses(retrieval_query, top_k=40, unique_courses=False)
        generated = generate_optimal_schedules(
            courses,
            max_credits=max_credits,
            completed_courses=completed_courses,
        )
        best = generated["best_schedule"]
        best["explanation"] = generate_schedule_explanation(best, message)
        return {"response": best["explanation"], "data": generated}

    def _course_search_run(self, message: str) -> dict[str, Any]:
        courses = retrieve_relevant_courses(self._contextual_query(message), top_k=10)
        summary = [
            _format_course_result(index, course)
            for index, course in enumerate(courses, start=1)
        ]
        return {
            "response": "Relevant courses:\n" + "\n".join(summary),
            "data": {"results": json.loads(json.dumps(courses, default=str))},
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


def _format_course_result(index: int, course: dict[str, Any]) -> str:
    score = course.get("rerank_score") or course.get("relevance_score")
    score_text = f" score {float(score):.3f}" if score is not None else ""
    section = course.get("section")
    section_text = f" section {section}" if section else ""
    credits = course.get("credits")
    credits_text = f", {credits:g} credits" if isinstance(credits, (int, float)) and credits else ""
    return (
        f"{index}. {course.get('course_code')} {course.get('course_name')}"
        f"{section_text}{credits_text}{score_text}"
    )
