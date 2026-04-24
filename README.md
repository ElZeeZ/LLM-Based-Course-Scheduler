# LLM-Based-Course-Scheduler

AI academic assistant for course discovery and schedule planning.

## Current Architecture

The project now separates semantic course discovery from schedule construction.

* **Vector DB / RAG:** `lau_catalog_rag.json` is embedded into Chroma Cloud collection `course_embeddings`. It is used for course-name and course-description search.
* **Embeddings:** Qwen `text-embedding-v4` at 2048 dimensions.
* **Reranking:** Qwen `qwen3-rerank` reranks Chroma candidates and returns the best courses.
* **LLM agent:** Gemini 2.5 Flash is used for LangChain agent reasoning, schedule-request handling, and explanation.
* **Scheduling data:** timings, sections, credits, and prerequisites should come from a relational database later. The vector DB should not be treated as the source of truth for schedule constraints.

## Project Structure

```text
LLM-Based-Course-Scheduler/
|-- app/
|   |-- api/              # FastAPI routes
|   |-- agent/            # LangChain agent and tools
|   |-- llm/              # Gemini client
|   |-- models/           # Pydantic request/response models
|   |-- rag/              # Chroma, Qwen embeddings, rerank, retrieval, ingestion
|   |-- scheduler/        # deterministic schedule constraints and optimizer
|   |-- config.py
|   `-- main.py
|-- scripts/
|   |-- ingest_courses.py
|   |-- chat_terminal.py
|   `-- migrate_to_chroma_cloud.py
|-- tests/
|-- lau_catalog_rag.json  # active catalog source for RAG
|-- .env.example
|-- requirements.txt
`-- README.md
```

The older `src/` directory is legacy scaffold and should not receive new application code.

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create `.env` from `.env.example`:

```env
GEMINI_API_KEY=
QWEN_API_KEY=
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_EMBEDDING_MODEL=text-embedding-v4
QWEN_EMBEDDING_DIMENSION=2048
QWEN_RERANK_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-api/v1
QWEN_RERANK_MODEL=qwen3-rerank
CHROMA_API_KEY=
CHROMA_TENANT=
CHROMA_DATABASE=
CHROMA_HOST=api.trychroma.com
CHROMA_COLLECTION=course_embeddings
```

Keep `.env` private. Do not commit API keys.

## Chroma Ingestion

The active RAG source is:

```text
lau_catalog_rag.json
```

Validate loading without writing:

```powershell
.\.venv\Scripts\python.exe -B scripts\ingest_courses.py --dry-run
```

Reset `course_embeddings` and upload fresh Qwen vectors:

```powershell
.\.venv\Scripts\python.exe -B scripts\ingest_courses.py --reset --batch-size 10
```

The batch size is `10` because Qwen embeddings accept up to 10 texts per request. The current Chroma collection contains 2,442 embedded catalog records.

## Retrieval Pipeline

For course-description search:

```text
User query
-> Qwen query embedding
-> Chroma vector search over course_embeddings
-> retrieve 30-40 candidates
-> Qwen qwen3-rerank
-> return best 10 courses
```

Returned results include `rerank_score`, `vector_relevance_score`, and `vector_rank`.

Simple course-search prompts bypass the Gemini agent for speed and use this direct RAG path.

## Terminal Chat

Run a one-shot prompt:

```powershell
.\.venv\Scripts\python.exe -B scripts\chat_terminal.py "What courses are related to robotics and embedded systems?"
```

Start interactive chat:

```powershell
.\.venv\Scripts\python.exe -B scripts\chat_terminal.py
```

Simple search prompts return a deterministic reranked list. Schedule-like prompts still use the agent path. Interactive terminal sessions keep temporary in-memory chat history until the process exits. Use `/history` to inspect memory and `/reset` to clear it.

## Run FastAPI

```powershell
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

## API Endpoints

### `GET /`

Health/root endpoint.

### `POST /search-courses`

Searches catalog descriptions through Qwen + Chroma + rerank.

```json
{
  "query": "robotics and embedded systems",
  "top_k": 10
}
```

### `POST /chat`

Routes simple search to direct RAG and schedule-like messages to the agent.

```json
{
  "message": "What AI courses involve computer vision?",
  "max_credits": 18,
  "completed_courses": [],
  "session_id": "student-demo",
  "reset_memory": false
}
```

`session_id` stores temporary in-process memory for that chat session. Memory is lost when the API process stops.

If the student states a credit target in the message, for example "I want 15 credits", that value overrides `max_credits`. If no credit target is stated, the default is 18 credits.

### `POST /generate-schedule`

Current deterministic scheduler endpoint. This will need to be adapted once the relational DB is added for sections, timings, credits, and prerequisites.

## LangChain Agent

The agent is in `app/agent/langchain_agent.py`; tools are in `app/agent/tools.py`.

Current tools:

* `course_search_tool`
* `schedule_generator_tool`
* `conflict_checker_tool`

Gemini handles agent reasoning and explanation. Hard scheduling constraints should remain deterministic and should use relational DB data once available.

## Testing and Verification

There is no full test suite yet. Use syntax checks before changes:

```powershell
.\.venv\Scripts\python.exe -B -m py_compile app\rag\retriever.py scripts\chat_terminal.py
```

For RAG changes, verify:

```powershell
.\.venv\Scripts\python.exe -B -c "from app.rag.ingest import get_course_collection; c=get_course_collection(); print(c.name); print(c.count())"
```

Expected collection:

```text
course_embeddings
2442
```
