# Repository Guidelines

## Project Purpose

This repository implements an academic course chatbot. Its current production-ready capability is semantic course discovery over `lau_catalog_rag.json`. The catalog is embedded into Chroma Cloud collection `course_embeddings` with Qwen `text-embedding-v4`, then reranked with `qwen3-rerank`. Gemini 2.5 Flash is reserved for LangChain agent reasoning, schedule-request handling, and natural-language explanations.

Scheduling is being redesigned: course descriptions come from the vector DB, but sections, timings, credits, and prerequisites should come from a future relational database. Do not treat Chroma as the source of truth for schedule constraints.

## Project Structure & Module Organization

Application code lives in `app/`:

* `app/api/`: FastAPI endpoints.
* `app/agent/`: LangChain agent and tool definitions.
* `app/llm/`: Gemini client and explanation helper.
* `app/models/`: Pydantic request and response models.
* `app/rag/`: Chroma client, ingestion, Qwen embeddings, rerank, and retrieval.
* `app/scheduler/`: deterministic scheduling constraints and optimizer.

Scripts live in `scripts/`. Use `scripts/ingest_courses.py` for Chroma ingestion and `scripts/chat_terminal.py` for terminal chatbot testing. The legacy `src/` scaffold is obsolete; add new code under `app/`.

## Chatbot Behavior

Simple course-search prompts bypass the Gemini agent for speed:

```text
user query -> Qwen query embedding -> Chroma top 30-40 -> Qwen rerank -> best 10 courses
```

Schedule-like prompts are routed through the LangChain agent in `app/agent/langchain_agent.py`. Current tools are in `app/agent/tools.py`:

* `course_search_tool`
* `schedule_generator_tool`
* `conflict_checker_tool`

When adding new tools, keep them deterministic and narrow. LLMs may interpret preferences, but Python/DB logic must enforce constraints.

Credit handling is centralized in `app/agent/preferences.py`. If the student states a target such as "15 credits", use that value. Otherwise, default to 18 credits. Do not hard-code alternate defaults in tools, routes, scripts, or scheduler code.

Chat sessions have temporary in-memory history stored on `AcademicAgent`. Terminal memory lasts until `scripts/chat_terminal.py` exits. API memory is keyed by `ChatRequest.session_id` and lasts until the FastAPI process restarts. Use this memory for conversational continuity only; do not persist it or store secrets in it.

## Build, Run, and Ingestion Commands

```powershell
python -m venv .venv
.\.venv\Scripts\Activate
pip install -r requirements.txt
```

Run API:

```powershell
uvicorn app.main:app --reload
```

Validate and rebuild vectors:

```powershell
.\.venv\Scripts\python.exe -B scripts\ingest_courses.py --dry-run
.\.venv\Scripts\python.exe -B scripts\ingest_courses.py --reset --batch-size 10
```

Run terminal chat:

```powershell
.\.venv\Scripts\python.exe -B scripts\chat_terminal.py
```

## Coding Style & Naming Conventions

Use Python type hints, four-space indentation, `snake_case` for functions/modules, and `PascalCase` for classes and Pydantic models. Keep RAG changes in `app/rag`, agent/tool changes in `app/agent`, and scheduling constraints in `app/scheduler`.

Prefer explicit structured data over prompt-only behavior. Avoid mixing schedule constraint logic into retrieval code.

## Testing and Verification

No full test suite exists yet. Add tests under `tests/` using `pytest` naming: `test_*.py` and `test_*`.

Before handoff, run targeted syntax checks:

```powershell
.\.venv\Scripts\python.exe -B -m py_compile app\rag\retriever.py scripts\chat_terminal.py
```

For RAG changes, verify Chroma count and a real query:

```powershell
.\.venv\Scripts\python.exe -B -c "from app.rag.ingest import get_course_collection; c=get_course_collection(); print(c.name); print(c.count())"
.\.venv\Scripts\python.exe -B scripts\chat_terminal.py "What courses are related to robotics?"
```

Expected collection count is currently `2442`.

## Commit, PR, and Security Guidelines

Use short descriptive commit messages, e.g. `RAG and reranker updates`. PRs should summarize changed modules, verification commands, and environment changes.

Never commit `.env`, API keys, `__pycache__`, `.venv`, or generated local artifacts. Keep `.env.example` updated with variable names only. Required services are Qwen, Chroma Cloud, and Gemini for agent reasoning.
