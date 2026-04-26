from __future__ import annotations

from fastapi import APIRouter

from app.agent.preferences import extract_max_credits
from app.agent.langchain_agent import AcademicAgent
from app.llm.gemini_client import generate_schedule_explanation
from app.models.request_models import ChatRequest, GenerateScheduleRequest, SearchCoursesRequest
from app.models.response_models import ChatResponse, CourseResult, ScheduleResponse, SearchCoursesResponse
from app.rag.retriever import retrieve_relevant_courses
from app.scheduler.optimizer import generate_optimal_schedules


router = APIRouter()
agents: dict[str, AcademicAgent] = {}


@router.get("/")
def root() -> dict[str, str]:
    return {"message": "LLM-Based Course Scheduler API"}


@router.post("/search-courses", response_model=SearchCoursesResponse)
def search_courses(request: SearchCoursesRequest) -> SearchCoursesResponse:
    courses = retrieve_relevant_courses(request.query, request.top_k, request.filters)
    return SearchCoursesResponse(
        query=request.query,
        results=[CourseResult(**course) for course in courses],
    )


@router.post("/generate-schedule", response_model=ScheduleResponse)
def generate_schedule(request: GenerateScheduleRequest) -> ScheduleResponse:
    courses = retrieve_relevant_courses(request.query, request.top_k, unique_courses=False)
    generated = generate_optimal_schedules(
        courses,
        max_credits=extract_max_credits(request.query, request.max_credits),
        completed_courses=request.completed_courses,
        preferred_days=request.preferred_days,
    )
    best = generated["best_schedule"]
    explanation = generate_schedule_explanation(best, request.query)
    return ScheduleResponse(
        selected_courses=best["selected_courses"],
        total_credits=best["total_credits"],
        explanation=explanation,
        alternative_schedules=generated["alternative_schedules"],
        rejected_conflicts=generated["rejected_conflicts"],
    )


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    agent = _get_session_agent(request.session_id)
    if request.reset_memory:
        agent.reset_memory()
    result = agent.search_courses(request.message)
    return ChatResponse(response=result["response"], data=result.get("data"))


def _get_session_agent(session_id: str) -> AcademicAgent:
    normalized = session_id.strip() or "default"
    if normalized not in agents:
        agents[normalized] = AcademicAgent()
    return agents[normalized]
