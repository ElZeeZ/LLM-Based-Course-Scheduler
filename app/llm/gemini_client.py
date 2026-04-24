from __future__ import annotations

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
