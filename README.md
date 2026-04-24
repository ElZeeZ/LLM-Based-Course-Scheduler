# LLM-Based Course Scheduler

## Overview

An LLM-based assistant that helps university students with course scheduling and selection using course data from LAU.

---

## Features

### Schedule Generation

* Input: desired courses + constraints (time, days, preferences)
* Output: optimized, conflict-free schedule

### Course Recommendation

* Input: eligible courses
* Output: balanced and optimized course selection

### Chroma Cloud Search

Course retrieval uses Chroma Cloud collections with hybrid dense + sparse search:

* Dense embeddings: Chroma Cloud Qwen (`Qwen/Qwen3-Embedding-0.6B`)
* Sparse embeddings: Chroma Cloud Splade (`prithivida/Splade_PP_en_v1`)
* Ranking: Reciprocal Rank Fusion (RRF), weighted 70% dense and 30% sparse by default
* Deduplication: `GroupBy` on `source_document_id`, with `chunk_index` metadata for traceability
* Chunking: line-based chunks under Chroma's 16 KiB document limit

---

## Structure

```text
.
|-- src/      # core logic
|-- scripts/  # migration and maintenance commands
|-- ui/       # interface
|-- data/     # datasets
```

---

## Chroma Cloud Setup

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create a `.env` file with:

```env
CHROMA_HOST=api.trychroma.com
CHROMA_API_KEY=YOUR_CHROMA_API_KEY
CHROMA_TENANT=51335609-8555-49e9-8762-830d64e37505
CHROMA_DATABASE=LLM-Based-Course-Scheduler
CHROMA_COLLECTION_PREFIX=course-catalog
```

Migrate existing course data:

```powershell
python scripts/migrate_to_chroma_cloud.py data/courses.json --text-field description --id-field course_code --organization-id lau
```

Supported import formats are `.json`, `.jsonl`, and `.csv`. Collections are sharded by `--organization-id` or `--user-id`, so mutually exclusive data does not share a collection.

Search from Python:

```python
from src.rag.chroma_cloud import ChromaCloudSearch

search = ChromaCloudSearch()
hits = search.search("computer science courses with data structures", organization_id="lau")
```

---

## Notes

* API keys are handled via `.env` (not included in repo)
* Project structure may evolve during development
