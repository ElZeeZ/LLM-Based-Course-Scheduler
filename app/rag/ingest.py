from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

import chromadb

from app.config import DATA_FILE, settings
from app.rag.qwen_embeddings import embed_texts
from app.scheduler.constraints import parse_meeting_time


COURSE_CODE_RE = re.compile(r"\b[A-Z]{2,5}\s*\d{3}[A-Z]?\b")
MAX_DOCUMENT_BYTES = 15 * 1024


def get_chroma_client():
    if settings.chroma_api_key and settings.chroma_tenant and settings.chroma_database:
        return chromadb.CloudClient(
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
            api_key=settings.chroma_api_key,
            cloud_host=settings.chroma_host,
        )
    return chromadb.PersistentClient(path=str(settings.local_chroma_path))


def get_course_collection():
    return get_chroma_client().get_or_create_collection(name=settings.chroma_collection)


def ingest_courses(
    data_file: Path = DATA_FILE,
    *,
    batch_size: int = 64,
    reset: bool = False,
    offset: int = 0,
    limit: int | None = None,
    sleep_seconds: float = 0,
) -> int:
    records = load_course_records(data_file)
    documents = list(iter_course_documents(records))
    documents = documents[offset : offset + limit if limit is not None else None]
    client = get_chroma_client()

    if reset:
        try:
            client.delete_collection(settings.chroma_collection)
        except Exception:
            pass
    collection = client.get_or_create_collection(name=settings.chroma_collection)

    count = 0
    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]
        texts = [item["document"] for item in batch]
        collection.upsert(
            ids=[item["id"] for item in batch],
            documents=texts,
            metadatas=[item["metadata"] for item in batch],
            embeddings=embed_texts(texts),
        )
        count += len(batch)
        print(f"Ingested batch {start // batch_size + 1}: {count}/{len(documents)} documents.")
        if sleep_seconds and start + batch_size < len(documents):
            time.sleep(sleep_seconds)
    return count


def recreate_empty_collection(client: Any) -> None:
    try:
        client.delete_collection(settings.chroma_collection)
    except Exception:
        pass
    client.get_or_create_collection(name=settings.chroma_collection)


def load_course_records(data_file: Path = DATA_FILE) -> list[dict[str, Any]]:
    if not data_file.exists():
        raise FileNotFoundError(f"Course data file not found: {data_file}")

    payload = json.loads(data_file.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in ("courses", "data", "records", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
        if all(isinstance(value, dict) for value in payload.values()):
            return list(payload.values())
    raise ValueError("Unsupported course JSON structure.")


def iter_course_documents(records: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for index, record in enumerate(records):
        course = normalize_course_record(record, index)
        sections = extract_sections(record)
        if sections:
            for section_index, section in enumerate(sections):
                merged = {**course, **normalize_section_record(section, course)}
                yield build_document(merged, f"{index}-{section_index}")
        else:
            yield build_document(course, str(index))


def normalize_course_record(record: dict[str, Any], index: int) -> dict[str, Any]:
    parsed = parse_compact_course_name(first_value(record, "course_name", "name", "title") or "")
    days, start_time, end_time = parse_meeting_time(first_value(record, "time", "meeting_time", "schedule"))

    course_code = first_value(record, "course_code", "code", "id") or parsed.get("course_code") or f"COURSE-{index}"
    course_name = first_value(record, "course_name", "name", "title") or parsed.get("course_name") or course_code
    return {
        "course_code": normalize_code(course_code),
        "course_name": parsed.get("course_title") or strip_section_from_name(str(course_name)),
        "description": first_value(record, "description", "course_description", "desc") or "",
        "credits": parse_credits(first_value(record, "credits", "credit_hours")),
        "department": first_value(record, "department", "subject") or infer_department(course_code),
        "prerequisites": normalize_prerequisites(first_value(record, "prerequisites", "prerequisite", "prereq")),
        "instructor": first_value(record, "instructor", "faculty", "teacher") or "",
        "days": days,
        "start_time": first_value(record, "start_time") or start_time,
        "end_time": first_value(record, "end_time") or end_time,
        "semester": first_value(record, "semester", "term") or "",
        "section": first_value(record, "section") or parsed.get("section") or "",
        "crn": first_value(record, "crn", "class_id") or parsed.get("crn") or "",
        "location": first_value(record, "location", "room") or "",
    }


def normalize_section_record(section: dict[str, Any], course: dict[str, Any]) -> dict[str, Any]:
    days, start_time, end_time = parse_meeting_time(first_value(section, "time", "meeting_time", "schedule"))
    return {
        "section": first_value(section, "section", "class_number", "offering") or course.get("section") or "",
        "instructor": first_value(section, "instructor", "faculty", "teacher") or course.get("instructor") or "",
        "days": first_value(section, "days") or days or course.get("days") or [],
        "start_time": first_value(section, "start_time") or start_time or course.get("start_time"),
        "end_time": first_value(section, "end_time") or end_time or course.get("end_time"),
        "semester": first_value(section, "semester", "term") or course.get("semester") or "",
        "location": first_value(section, "location", "room") or course.get("location") or "",
        "crn": first_value(section, "crn", "class_id") or course.get("crn") or "",
    }


def extract_sections(record: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("sections", "classes", "offerings"):
        value = record.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def build_document(course: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    metadata = normalize_metadata(course)
    document = "\n".join(
        [
            f"Course Code: {metadata['course_code']}",
            f"Course Name: {metadata['course_name']}",
            f"Description: {metadata['description']}",
            f"Credits: {metadata['credits']}",
            f"Department: {metadata['department']}",
            f"Prerequisites: {metadata['prerequisites']}",
            f"Instructor: {metadata['instructor']}",
            f"Days: {metadata['days']}",
            f"Start Time: {metadata['start_time']}",
            f"End Time: {metadata['end_time']}",
            f"Semester: {metadata['semester']}",
            f"Section: {metadata['section']}",
            f"Location: {metadata['location']}",
            f"CRN: {metadata['crn']}",
        ]
    )
    return {
        "id": stable_document_id(metadata, fallback_id),
        "document": truncate_document(document),
        "metadata": metadata,
    }


def normalize_metadata(course: dict[str, Any]) -> dict[str, Any]:
    days = course.get("days") or []
    if isinstance(days, list):
        days_text = " ".join(days)
    else:
        days_text = str(days)
    prerequisites = course.get("prerequisites") or []
    prereq_text = ", ".join(prerequisites) if isinstance(prerequisites, list) else str(prerequisites)
    return {
        "course_code": str(course.get("course_code") or ""),
        "course_name": str(course.get("course_name") or ""),
        "description": str(course.get("description") or ""),
        "credits": float(course.get("credits") or 0),
        "department": str(course.get("department") or ""),
        "semester": str(course.get("semester") or ""),
        "section": str(course.get("section") or ""),
        "instructor": str(course.get("instructor") or ""),
        "days": days_text,
        "start_time": str(course.get("start_time") or ""),
        "end_time": str(course.get("end_time") or ""),
        "prerequisites": prereq_text,
        "location": str(course.get("location") or ""),
        "crn": str(course.get("crn") or ""),
    }


def parse_compact_course_name(value: str) -> dict[str, str]:
    parts = [part.strip() for part in str(value).split(" - ") if part.strip()]
    code = ""
    section = ""
    crn = ""
    title_parts: list[str] = []
    for part in parts:
        match = COURSE_CODE_RE.search(part.upper())
        if match:
            code = normalize_code(match.group(0))
            continue
        if re.fullmatch(r"\d{4,}", part):
            crn = part
            continue
        if code and not section and re.fullmatch(r"[A-Za-z0-9]+", part):
            section = part
            continue
        title_parts.append(part)
    return {
        "course_title": " - ".join(title_parts) if title_parts else str(value),
        "course_code": code,
        "section": section,
        "crn": crn,
    }


def strip_section_from_name(value: str) -> str:
    parsed = parse_compact_course_name(value)
    return parsed.get("course_title") or value


def first_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_credits(value: Any) -> float:
    if value in (None, ""):
        return 3.0
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else 3.0


def normalize_prerequisites(value: Any) -> list[str]:
    if value in (None, "", [], "None", "N/A"):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [item.strip() for item in re.split(r"[,;]", str(value)) if item.strip()]


def infer_department(course_code: Any) -> str:
    match = re.match(r"([A-Za-z]+)", str(course_code or ""))
    return match.group(1).upper() if match else ""


def normalize_code(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").upper()).strip()


def stable_document_id(metadata: dict[str, Any], fallback_id: str) -> str:
    parts = [
        metadata.get("course_code") or fallback_id,
        metadata.get("section") or "course",
        metadata.get("crn") or fallback_id,
        metadata.get("semester") or "term",
        metadata.get("start_time") or "time",
    ]
    return "::".join(str(part).replace(" ", "_") for part in parts)


def truncate_document(document: str) -> str:
    data = document.encode("utf-8")
    if len(data) <= MAX_DOCUMENT_BYTES:
        return document
    return data[:MAX_DOCUMENT_BYTES].decode("utf-8", errors="ignore")
