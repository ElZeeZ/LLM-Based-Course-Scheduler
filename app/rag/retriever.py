from __future__ import annotations

from typing import Any

from app.rag.ingest import get_course_collection
from app.rag.qwen_embeddings import embed_query
from app.rag.qwen_rerank import rerank_courses


MIN_RERANK_CANDIDATES = 30
MAX_RERANK_CANDIDATES = 40


def retrieve_relevant_courses(
    query: str,
    top_k: int = 10,
    filters: dict[str, Any] | None = None,
    unique_courses: bool = True,
) -> list[dict[str, Any]]:
    candidate_count = _candidate_count(top_k)
    collection = get_course_collection()
    result = collection.query(
        query_embeddings=[embed_query(query)],
        n_results=candidate_count,
        where=filters,
        include=["documents", "metadatas", "distances"],
    )
    candidates = _format_query_result(result)
    return rerank_courses(query, candidates, top_n=top_k, unique_courses=unique_courses)


def _candidate_count(top_k: int) -> int:
    return min(max(top_k * 4, MIN_RERANK_CANDIDATES), MAX_RERANK_CANDIDATES)


def _format_query_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    courses = []
    for index, metadata in enumerate(metadatas):
        distance = distances[index] if index < len(distances) else None
        relevance = 1.0 / (1.0 + float(distance)) if distance is not None else 0.0
        course = dict(metadata or {})
        course["id"] = ids[index] if index < len(ids) else None
        course["document"] = documents[index] if index < len(documents) else ""
        course["distance"] = distance
        course["relevance_score"] = relevance
        courses.append(course)
    return courses
