from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router


app = FastAPI(
    title="LLM-Based Course Scheduler",
    description="RAG-powered academic course discovery and deterministic schedule generation.",
    version="1.0.0",
)
app.include_router(router)
