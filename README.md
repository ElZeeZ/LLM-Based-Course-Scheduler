# LLM-Based-Course-Scheduler

AI academic assistant for semantic course discovery and deterministic schedule generation.

## What It Does

The project loads `data/university_courses.json` into ChromaDB or Chroma Cloud, stores Qwen `text-embedding-v4` vectors, reranks retrieval candidates with `qwen3-rerank`, and generates academic schedules with deterministic Python constraints.

The LLM is used for reasoning, explanation, and formatting. It does not enforce hard scheduling constraints.

## Stack

* Python
* FastAPI
* LangChain
* ChromaDB / Chroma Cloud
* Gemini 2.5 Flash
* python-dotenv
* JSON data input

## Project Structure

```text
LLM-Based-Course-Scheduler/
|-- app/
|   |-- main.py
|   |-- config.py
|   |-- rag/
|   |-- agent/
|   |-- scheduler/
|   |-- llm/
|   |-- api/
|   `-- models/
|-- data/
|   `-- university_courses.json
|-- scripts/
|   |-- ingest_courses.py
|   `-- migrate_to_chroma_cloud.py
|-- tests/
|-- .env.example
|-- requirements.txt
`-- README.md
```

## Setup

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\Activate
```

Activate it on Mac/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
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
CHROMA_COLLECTION=course_embeddings
```

If Chroma Cloud values are present, the app uses Chroma Cloud. Otherwise it falls back to local persistent ChromaDB in `.chroma/`.

## Ingest Courses

The single source of truth is:

```text
data/university_courses.json
```

Run ingestion:

```bash
python scripts/ingest_courses.py
```

The default ingestion command embeds and upserts 10 documents at a time into `course_embeddings`. Embeddings are generated with Qwen `text-embedding-v4` at 2048 dimensions, then stored explicitly in Chroma.

If you want extra throttling between batches:

```bash
python scripts/ingest_courses.py --sleep-seconds 30
```

Validate the data file without writing:

```bash
python scripts/ingest_courses.py --dry-run
```

Reset and re-ingest the collection:

```bash
python scripts/ingest_courses.py --reset
```

## Run FastAPI

```bash
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

## Terminal Chat

Simple course-search prompts use the fast direct RAG path: Qwen query embedding, Chroma vector search, Qwen rerank, and deterministic terminal formatting. Schedule requests still use the agent path.

Run a one-shot prompt:

```bash
python scripts/chat_terminal.py "What robotics and embedded systems courses are available?"
```

Start an interactive terminal chat:

```bash
python scripts/chat_terminal.py
```

## API Endpoints

### GET /

Health/root endpoint.

### POST /search-courses

Example:

```json
{
  "query": "robotics courses",
  "top_k": 10
}
```

### POST /generate-schedule

Example:

```json
{
  "query": "Create a 15-credit schedule focused on robotics and embedded systems",
  "max_credits": 15,
  "completed_courses": ["MTH 201", "CSC 243"],
  "preferred_days": ["Mon", "Wed"]
}
```

### POST /chat

Example:

```json
{
  "message": "What robotics-related courses are available?",
  "max_credits": 15,
  "completed_courses": []
}
```

## Scheduling Guarantees

The deterministic scheduler enforces:

* No time conflicts
* Day overlap detection
* Max credit limit
* Prerequisite validation when prerequisite data is available
* One section per course

Supported day formats include `MWF`, `TTH`, `TR`, `Mon Wed`, `Tue Thu`, and full day names.

## Expected Behavior

User asks:

```text
What robotics-related courses are available?
```

The system retrieves a 30-40 course candidate pool with Qwen `text-embedding-v4` query embeddings, reranks candidates with `qwen3-rerank`, and returns the best matching courses.

User asks:

```text
Create a 15-credit schedule focused on robotics and embedded systems
```

The system retrieves relevant courses, removes conflicts, respects prerequisites and max credits, and returns the best schedule with alternatives and rejected conflicts.
