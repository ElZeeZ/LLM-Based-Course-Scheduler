from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import settings
from app.rag.http_client import get_http_client


COURSE_CODE_RE = re.compile(r"\b[A-Z]{2,5}\s*\d{3}[A-Z]?\b", re.IGNORECASE)
CRN_RE = re.compile(r"\b\d{4,6}\b")
CAMPUS_RE = re.compile(r"\b(beirut|byblos|jbeil|jbiel)\b", re.IGNORECASE)


def extract_course_codes(text: str) -> list[str]:
    seen = set()
    codes: list[str] = []
    for match in COURSE_CODE_RE.findall(text or ""):
        code = re.sub(r"\s+", " ", match.upper()).strip()
        key = re.sub(r"\s+", "", code)
        if key not in seen:
            seen.add(key)
            codes.append(code)
    return codes


def extract_campus(text: str) -> str | None:
    match = CAMPUS_RE.search(text or "")
    if not match:
        return None
    campus = match.group(1).lower()
    return "Jbeil" if campus in {"byblos", "jbeil", "jbiel"} else "Beirut"


def extract_crns(text: str) -> list[str]:
    seen = set()
    crns: list[str] = []
    for match in CRN_RE.findall(text or ""):
        if match not in seen:
            seen.add(match)
            crns.append(match)
    return crns


def fetch_exact_schedule_sections(
    *,
    query: str,
    selected_courses: list[dict[str, Any]] | None = None,
    limit_per_course: int = 20,
) -> list[dict[str, Any]]:
    campus = extract_campus(query) or _common_selected_campus(selected_courses or [])
    selections = _normalize_selected_courses(selected_courses or [], campus)
    course_codes = _dedupe_terms([
        *extract_course_codes(query),
        *[selection["course_code"] for selection in selections],
    ])
    crns = _dedupe_terms([
        *extract_crns(query),
        *_extract_selected_crns(selected_courses or []),
    ])

    if not course_codes and not crns:
        return []

    payload = {
        "query": query,
        "campus": campus or "",
        "course_codes": course_codes,
        "crns": crns,
        "courses": selections,
        "limit_per_course": limit_per_course,
    }
    return _post_sections("/api/courses/sections/exact", payload)


def fetch_schedule_sections(
    *,
    query: str,
    selected_courses: list[dict[str, Any]] | None = None,
    include_search_terms: bool = True,
    limit_per_course: int = 20,
) -> list[dict[str, Any]]:
    campus = extract_campus(query) or _common_selected_campus(selected_courses or [])
    selections = _normalize_selected_courses(selected_courses or [], campus)
    course_codes = extract_course_codes(query)
    search_terms = extract_search_terms(query) if include_search_terms else []

    if not selections and not course_codes and not search_terms:
        return []

    payload = {
        "query": query,
        "campus": campus or "",
        "course_codes": course_codes,
        "search_terms": search_terms,
        "courses": selections,
        "limit_per_course": limit_per_course,
    }
    return _post_sections("/api/courses/sections/batch", payload)


def _post_sections(path: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if settings.node_internal_api_key:
        headers["Authorization"] = f"Bearer {settings.node_internal_api_key}"

    url = f"{settings.node_api_base_url.rstrip('/')}{path}"
    try:
        response = get_http_client().post(url, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Node course API request failed: {exc}") from exc

    data = response.json()
    if isinstance(data, dict):
        sections = data.get("sections")
    else:
        sections = data
    if not isinstance(sections, list):
        raise RuntimeError("Node course API returned an invalid sections payload.")
    return sections


def extract_search_terms(query: str) -> list[str]:
    terms = re.findall(r"\b\d{5,6}\b", query or "")
    quoted = re.findall(r"['\"]([^'\"]{3,})['\"]", query or "")
    terms.extend(quoted)

    for match in re.finditer(
        r"\b(?:for|of|including|with)\s+(?P<targets>[^.?!]+)",
        query or "",
        re.IGNORECASE,
    ):
        targets = _clean_search_targets(match.group("targets"))
        for target in re.split(r"\s*(?:,|;)\s*", targets, flags=re.IGNORECASE):
            cleaned = re.sub(r"^\s*(?:and|or)\s+", "", target, flags=re.IGNORECASE).strip(" ,;")
            if cleaned and not extract_course_codes(cleaned):
                terms.append(cleaned)
    return _dedupe_terms(terms)


def _clean_search_targets(value: str) -> str:
    return re.split(
        r"\b(?:in beirut|in byblos|in jbeil|in jbiel|mwf|tr|avoid|without|do not want|don't want|dont want)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]


def _dedupe_terms(items: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for item in items:
        normalized = re.sub(r"\s+", " ", str(item).strip())
        key = normalized.lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(normalized)
    return deduped


def _normalize_selected_courses(
    selected_courses: list[dict[str, Any]],
    campus_override: str | None,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen = set()
    for course in selected_courses:
        code = _format_course_code(course.get("course_code") or course.get("code") or course.get("course_id"))
        if not code:
            continue
        campus = campus_override or str(course.get("campus") or "").strip()
        key = (re.sub(r"\s+", "", code).upper(), campus.lower())
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"course_code": code, "campus": campus})
    return normalized


def _common_selected_campus(selected_courses: list[dict[str, Any]]) -> str | None:
    campuses = {
        str(course.get("campus") or "").strip()
        for course in selected_courses
        if str(course.get("campus") or "").strip()
    }
    return next(iter(campuses)) if len(campuses) == 1 else None


def _extract_selected_crns(selected_courses: list[dict[str, Any]]) -> list[str]:
    crns: list[str] = []
    for course in selected_courses:
        for key in ("crn", "id"):
            value = str(course.get(key) or "").strip()
            if CRN_RE.fullmatch(value):
                crns.append(value)
    return crns


def _format_course_code(value: Any) -> str:
    compact = re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())
    match = re.match(r"^([A-Z]{2,5})(\d{3}[A-Z]?)$", compact)
    if not match:
        return str(value or "").strip().upper()
    return f"{match.group(1)} {match.group(2)}"
