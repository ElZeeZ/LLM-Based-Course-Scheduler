# Repository Guidelines

## Project Purpose

This repository implements an academic course chatbot. The stable capability is semantic course discovery over `lau_catalog_rag.json`. The file is embedded into Chroma Cloud collection `course_embeddings` using Qwen `text-embedding-v4` at 2048 dimensions, then reranked with Qwen `qwen3-rerank`.

Gemini 2.5 Flash is reserved for LangChain agent reasoning, schedule-request handling, and natural-language explanations. Do not use Gemini for embeddings or rerank in the current architecture.

Scheduling is being redesigned. Course descriptions come from the vector DB, but sections, timings, credits, and prerequisites should come from a future relational database. Chroma is not the source of truth for hard schedule constraints.

## Project Structure

Application code lives in `app/`:

* `app/api/`: FastAPI endpoints.
* `app/agent/`: LangChain agent, chatbot memory, preferences, and tools.
* `app/llm/`: Gemini client and explanation helper.
* `app/models/`: Pydantic request and response models.
* `app/rag/`: Chroma access, catalog ingestion, Qwen embeddings, Qwen rerank, and retrieval.
* `app/scheduler/`: deterministic scheduling constraints and optimizer.

Scripts live in `scripts/`. Use `scripts/ingest_courses.py` for vector ingestion and `scripts/chat_terminal.py` for terminal chatbot testing. The legacy `src/` scaffold is obsolete; add new code under `app/`.

## RAG Pipeline

The active vector source is `lau_catalog_rag.json`. Each record is normalized in `app/rag/ingest.py` into text containing course code, course name, course description, department code, and department name. Empty schedule fields are omitted from the embedded text.

Ingestion workflow:

```text
lau_catalog_rag.json
-> normalize records
-> Qwen text-embedding-v4 vectors
-> Chroma Cloud course_embeddings
```

Runtime retrieval workflow:

```text
user query
-> Qwen query embedding
-> Chroma vector search, 30-40 candidates
-> Qwen qwen3-rerank
-> best 10 courses
```

Rerank is mandatory. Returned courses may include `rerank_score`, `vector_relevance_score`, and `vector_rank`. Keep search focused on catalog semantics; do not add scheduling logic to RAG retrieval.

## Chatbot and Memory

`POST /chat` is only for course discovery by name/description. It bypasses Gemini for speed and uses direct RAG plus deterministic formatting. Do not add schedule-only fields such as `max_credits` or `completed_courses` to `ChatRequest`.

Schedule-like prompts are detected in `app/agent/langchain_agent.py` and routed through LangChain. Current tools are in `app/agent/tools.py`:

* `course_search_tool`
* `schedule_generator_tool`
* `conflict_checker_tool`

Session memory is temporary and in-process. `AcademicAgent` keeps recent turns for conversational continuity. Terminal memory lasts until `scripts/chat_terminal.py` exits. API memory is keyed by `ChatRequest.session_id` and is lost when FastAPI restarts. Use `/history` and `/reset` in terminal chat.

## LangChain Workflow

LangChain uses Gemini 2.5 Flash with the tool list above. The LLM may interpret user intent and choose tools, but deterministic Python must enforce constraints. If the agent fails, schedule requests fall back to direct retrieval plus deterministic scheduling.

Schedule generation belongs in `POST /generate-schedule` and the schedule agent/tools. Credit handling is centralized in `app/agent/preferences.py`. If the student states a target such as `15 credits`, use that value. Otherwise default to 18 credits. Do not hard-code credit defaults elsewhere.

## Scheduling Constraints

Current deterministic scheduling code is in `app/scheduler/`. It enforces max credits, no time conflicts, day overlap detection, one section per course, and prerequisite checks when prerequisite data is available. This module must eventually consume relational DB records for sections, timings, credits, and prerequisites.

## Commands

```powershell
python -m venv .venv
.\.venv\Scripts\Activate
pip install -r requirements.txt
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

## Coding, PR, and Security Rules

Use Python type hints, four-space indentation, `snake_case` for functions/modules, and `PascalCase` for classes and Pydantic models. Keep RAG changes in `app/rag`, agent/tool changes in `app/agent`, and scheduling constraints in `app/scheduler`.

Use short descriptive commit messages, e.g. `RAG and reranker updates`. PRs should summarize changed modules, verification commands, and environment changes.

Never commit `.env`, API keys, `__pycache__`, `.venv`, or generated local artifacts. Keep `.env.example` updated with variable names only.
