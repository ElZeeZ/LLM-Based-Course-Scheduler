from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import settings
from app.rag.http_client import get_http_client


MAX_QWEN_BATCH_SIZE = 10


def embed_texts(
    texts: list[str],
    *,
    max_retries: int = 3,
    retry_sleep_seconds: float = 5,
) -> list[list[float]]:
    if not settings.qwen_api_key:
        raise ValueError("QWEN_API_KEY or DASHSCOPE_API_KEY is required for Qwen embeddings.")

    embeddings: list[list[float]] = []
    for start in range(0, len(texts), MAX_QWEN_BATCH_SIZE):
        batch = texts[start : start + MAX_QWEN_BATCH_SIZE]
        embeddings.extend(
            _embed_batch(
                batch,
                max_retries=max_retries,
                retry_sleep_seconds=retry_sleep_seconds,
            )
        )
    return embeddings


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def _embed_batch(
    texts: list[str],
    *,
    max_retries: int,
    retry_sleep_seconds: float,
) -> list[list[float]]:
    payload = {
        "model": settings.qwen_embedding_model,
        "input": texts,
        "dimensions": settings.qwen_embedding_dimension,
        "encoding_format": "float",
    }
    headers = {
        "Authorization": f"Bearer {settings.qwen_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{settings.qwen_base_url.rstrip('/')}/embeddings"

    for attempt in range(max_retries + 1):
        try:
            response = get_http_client().post(url, headers=headers, json=payload)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep(_retry_delay(response, retry_sleep_seconds, attempt))
                continue
            response.raise_for_status()
            return _parse_embeddings(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            if attempt >= max_retries:
                raise RuntimeError(f"Qwen embedding request failed: {exc}") from exc
            time.sleep(retry_sleep_seconds * (attempt + 1))

    raise RuntimeError("Qwen embedding retry loop exited unexpectedly.")


def _parse_embeddings(payload: dict[str, Any]) -> list[list[float]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Qwen embedding response did not include a data list.")

    ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
    embeddings = [item.get("embedding") for item in ordered]
    if not all(isinstance(embedding, list) for embedding in embeddings):
        raise ValueError("Qwen embedding response included malformed embedding data.")
    return embeddings


def _retry_delay(response: httpx.Response, fallback: float, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return fallback * (attempt + 1)
