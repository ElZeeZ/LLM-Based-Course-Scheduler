from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import settings


DEFAULT_RERANK_INSTRUCTION = (
    "Given an academic course search query, rank the candidate courses by semantic relevance. "
    "Prefer courses that directly match the topic, skills, discipline, prerequisites, and scheduling intent."
)


def rerank_courses(
    query: str,
    courses: list[dict[str, Any]],
    *,
    top_n: int = 10,
    unique_courses: bool = True,
    max_retries: int = 3,
    retry_sleep_seconds: float = 5,
) -> list[dict[str, Any]]:
    if not courses:
        return []
    documents = [str(course.get("document") or "") for course in courses]
    rerank_limit = _rerank_limit(len(documents), top_n, unique_courses)
    results = rerank_documents(
        query,
        documents,
        top_n=rerank_limit,
        max_retries=max_retries,
        retry_sleep_seconds=retry_sleep_seconds,
    )

    reranked: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for result in results:
        index = result["index"]
        if index >= len(courses):
            continue
        course = dict(courses[index])
        course_code = str(course.get("course_code") or course.get("id") or "").strip().upper()
        if unique_courses and course_code in seen_codes:
            continue
        if course_code:
            seen_codes.add(course_code)
        course["vector_relevance_score"] = course.get("relevance_score")
        course["relevance_score"] = result["relevance_score"]
        course["rerank_score"] = result["relevance_score"]
        course["vector_rank"] = index + 1
        reranked.append(course)
        if len(reranked) >= top_n:
            break
    return reranked


def _rerank_limit(candidate_count: int, top_n: int, unique_courses: bool) -> int:
    if not unique_courses:
        return min(top_n, candidate_count)
    return min(max(top_n * 3, top_n + 20), candidate_count)


def rerank_documents(
    query: str,
    documents: list[str],
    *,
    top_n: int,
    max_retries: int,
    retry_sleep_seconds: float,
) -> list[dict[str, Any]]:
    if not settings.qwen_api_key:
        raise ValueError("QWEN_API_KEY or DASHSCOPE_API_KEY is required for Qwen reranking.")

    payload = {
        "model": settings.qwen_rerank_model,
        "query": query,
        "documents": documents,
        "top_n": top_n,
        "instruct": DEFAULT_RERANK_INSTRUCTION,
    }
    headers = {
        "Authorization": f"Bearer {settings.qwen_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{settings.qwen_rerank_base_url.rstrip('/')}/reranks"

    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(url, headers=headers, json=payload)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep(_retry_delay(response, retry_sleep_seconds, attempt))
                continue
            response.raise_for_status()
            return _parse_rerank_results(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            if attempt >= max_retries:
                raise RuntimeError(f"Qwen rerank request failed: {exc}") from exc
            time.sleep(retry_sleep_seconds * (attempt + 1))

    raise RuntimeError("Qwen rerank retry loop exited unexpectedly.")


def _parse_rerank_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    if results is None and isinstance(payload.get("output"), dict):
        results = payload["output"].get("results")
    if not isinstance(results, list):
        raise ValueError("Qwen rerank response did not include a results list.")

    parsed: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("relevance_score", item.get("score"))
        if index is None or score is None:
            continue
        parsed.append({"index": int(index), "relevance_score": float(score)})
    if not parsed:
        raise ValueError("Qwen rerank response did not include usable scores.")
    return parsed


def _retry_delay(response: httpx.Response, fallback: float, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return fallback * (attempt + 1)
