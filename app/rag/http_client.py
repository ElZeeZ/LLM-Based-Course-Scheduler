from __future__ import annotations

import atexit

import httpx


_client: httpx.Client | None = None


def get_http_client() -> httpx.Client:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.Client(timeout=120)
    return _client


def close_http_client() -> None:
    if _client is not None and not _client.is_closed:
        _client.close()


atexit.register(close_http_client)
