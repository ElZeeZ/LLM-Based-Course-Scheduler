from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from rapidfuzz import fuzz, process

from app.config import DATA_FILE
from app.integrations.node_courses import extract_course_codes, extract_search_terms
from app.rag.retriever import retrieve_relevant_courses


MIN_FUZZY_SCORE = 78
ROMAN_TO_NUMBER = {
    " VI": " 6",
    " IV": " 4",
    " III": " 3",
    " II": " 2",
    " V": " 5",
    " I": " 1",
}


def resolve_requested_courses(message: str) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    seen_codes = set()

    for code in extract_course_codes(message):
        course = _catalog_by_code().get(_compact_code(code))
        item = course or {"course_code": _format_course_code(code)}
        _append_once(resolved, seen_codes, item)

    for term in extract_search_terms(message):
        if extract_course_codes(term):
            continue
        item = _resolve_term_from_catalog(term) or _resolve_term_from_rag(term)
        if item:
            _append_once(resolved, seen_codes, item)

    return resolved


def _resolve_term_from_catalog(term: str) -> dict[str, Any] | None:
    normalized_term = _normalize_match_text(term)
    if not normalized_term:
        return None

    exact = _catalog_by_title().get(normalized_term)
    if exact:
        return exact

    match = process.extractOne(
        normalized_term,
        _catalog_match_choices(),
        scorer=fuzz.WRatio,
    )
    if not match:
        return None

    choice, score, _index = match
    if score < MIN_FUZZY_SCORE:
        return None
    return _catalog_by_choice()[choice]


def _resolve_term_from_rag(term: str) -> dict[str, Any] | None:
    try:
        matches = retrieve_relevant_courses(term, top_k=1)
    except Exception:
        return None
    if not matches:
        return None
    match = matches[0]
    code = str(match.get("course_code") or "").strip()
    if not code:
        return None
    return {
        "course_code": code,
        "course_name": match.get("course_name"),
        "description": match.get("description"),
    }


def _append_once(items: list[dict[str, Any]], seen_codes: set[str], item: dict[str, Any]) -> None:
    code = str(item.get("course_code") or "").strip()
    if not code:
        return
    key = _compact_code(code)
    if key in seen_codes:
        return
    seen_codes.add(key)
    items.append(item)


@lru_cache(maxsize=1)
def _catalog_courses() -> list[dict[str, Any]]:
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    courses: list[dict[str, Any]] = []
    for record in payload:
        code = _format_course_code(record.get("course_id"))
        name = str(record.get("course_name") or "").strip()
        if not code or not name:
            continue
        courses.append(
            {
                "course_code": code,
                "course_name": name,
                "description": record.get("course_description"),
                "department": record.get("department_code"),
                "department_name": record.get("department_name"),
            }
        )
    return courses


@lru_cache(maxsize=1)
def _catalog_by_code() -> dict[str, dict[str, Any]]:
    return {_compact_code(course["course_code"]): course for course in _catalog_courses()}


@lru_cache(maxsize=1)
def _catalog_by_title() -> dict[str, dict[str, Any]]:
    titles: dict[str, dict[str, Any]] = {}
    for course in _catalog_courses():
        titles.setdefault(_normalize_match_text(course["course_name"]), course)
    return titles


@lru_cache(maxsize=1)
def _catalog_by_choice() -> dict[str, dict[str, Any]]:
    choices: dict[str, dict[str, Any]] = {}
    for course in _catalog_courses():
        name_choice = _normalize_match_text(course["course_name"])
        code_choice = _normalize_match_text(course["course_code"])
        compact_code_choice = _compact_code(course["course_code"]).lower()
        choices.setdefault(name_choice, course)
        choices.setdefault(code_choice, course)
        choices.setdefault(compact_code_choice, course)
    return choices


@lru_cache(maxsize=1)
def _catalog_match_choices() -> list[str]:
    return list(_catalog_by_choice())


def _normalize_match_text(value: Any) -> str:
    text = str(value or "").upper()
    for roman, number in ROMAN_TO_NUMBER.items():
        text = text.replace(roman, number)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _compact_code(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _format_course_code(value: Any) -> str:
    compact = _compact_code(value)
    match = re.match(r"^([A-Z]+)(\d+[A-Z]?)$", compact)
    if not match:
        return str(value or "").strip().upper()
    return f"{match.group(1)} {match.group(2)}"
