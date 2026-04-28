from __future__ import annotations

import re
from typing import Any

from app.config import settings
from app.integrations.node_courses import extract_campus, extract_course_codes, extract_crns


DAY_LABELS = {
    "Monday": "MON",
    "Tuesday": "TUE",
    "Wednesday": "WED",
    "Thursday": "THU",
    "Friday": "FRI",
}


def fetch_postgres_schedule_sections(
    *,
    query: str,
    selected_courses: list[dict[str, Any]] | None = None,
    limit_per_course: int = 20,
) -> list[dict[str, Any]]:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured for FastAPI PostgreSQL lookup.")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Install psycopg[binary] to use FastAPI PostgreSQL lookup.") from exc

    course_codes = _exact_course_codes(query, selected_courses or [])
    crns = _exact_crns(query, selected_courses or [])
    campus = extract_campus(query) or _common_selected_campus(selected_courses or [])
    database_campus = _campus_to_database_value(campus)

    if not course_codes and not crns:
        return []

    filters: list[str] = []
    params: list[Any] = []
    if course_codes:
        filters.append("REPLACE(LOWER(cs.course_code), ' ', '') = ANY(%s)")
        params.append(course_codes)
    if crns:
        filters.append("CAST(cs.crn AS TEXT) = ANY(%s)")
        params.append(crns)

    where_parts = [f"({' OR '.join(filters)})"]
    if database_campus:
        where_parts.append("cs.campus = %s")
        params.append(database_campus)

    per_course_limit = min(max(int(limit_per_course or 20), 1), 50)
    result_limit = min(max((len(course_codes) + len(crns) or 1) * per_course_limit, 1), 500)
    params.append(result_limit)

    connect_kwargs: dict[str, Any] = {}
    if settings.pgsslmode:
        connect_kwargs["sslmode"] = settings.pgsslmode

    with psycopg.connect(settings.database_url, **connect_kwargs) as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT
                  cs.crn,
                  cs.course_code,
                  cs.semester,
                  cs.section_number,
                  cs.instructor_name,
                  cs.days,
                  cs.room,
                  cs.start_time,
                  cs.end_time,
                  cs.building,
                  cs.campus,
                  c.title,
                  c.credits,
                  c.prerequisite,
                  c.description
                FROM course_sections cs
                LEFT JOIN courses c ON c.course_code = cs.course_code
                WHERE {' AND '.join(where_parts)}
                ORDER BY cs.course_code ASC, cs.section_number ASC, cs.crn ASC
                LIMIT %s;
                """,
                params,
            )
            rows = cursor.fetchall()

    return [_normalize_section(row) for row in rows]


def _exact_course_codes(query: str, selected_courses: list[dict[str, Any]]) -> list[str]:
    seen = set()
    codes: list[str] = []

    def add_code(value: Any) -> None:
        compact = re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())
        if not re.fullmatch(r"[A-Z]{2,5}\d{3}[A-Z]?", compact):
            return
        key = compact.lower()
        if key in seen:
            return
        seen.add(key)
        codes.append(key)

    for code in extract_course_codes(query):
        add_code(code)
    for course in selected_courses:
        add_code(course.get("course_code") or course.get("code") or course.get("course_id"))
    return codes


def _exact_crns(query: str, selected_courses: list[dict[str, Any]]) -> list[str]:
    seen = set()
    crns: list[str] = []

    def add_crn(value: Any) -> None:
        crn = str(value or "").strip()
        if not re.fullmatch(r"\d{4,6}", crn) or crn in seen:
            return
        seen.add(crn)
        crns.append(crn)

    for crn in extract_crns(query):
        add_crn(crn)
    for course in selected_courses:
        add_crn(course.get("crn") or course.get("id"))
    return crns


def _normalize_section(row: dict[str, Any]) -> dict[str, Any]:
    course_code = _value_or_na(row.get("course_code"))
    start_time = _format_time(row.get("start_time"))
    end_time = _format_time(row.get("end_time"))
    campus = _normalize_campus(row.get("campus"))
    day_names = _normalize_days(row.get("days"))

    return {
        "id": str(row.get("crn")),
        "course_id": re.sub(r"\s+", "", course_code).lower(),
        "course_code": course_code,
        "course_name": _value_or_na(row.get("title")),
        "credits": row.get("credits") if row.get("credits") is not None else "N/A",
        "crn": _value_or_na(row.get("crn")),
        "section": _value_or_na(row.get("section_number")),
        "semester": _value_or_na(row.get("semester")),
        "instructor": _value_or_na(row.get("instructor_name")),
        "capacity": "N/A",
        "enrolled": "N/A",
        "campus": campus,
        "campuses": [] if campus == "N/A" else [campus],
        "prerequisites": _normalize_prerequisites(row.get("prerequisite")),
        "description": _value_or_na(row.get("description")),
        "days": _format_days_for_display(day_names),
        "day_names": day_names,
        "start_time": start_time,
        "end_time": end_time,
        "start_time_value": _format_time_value(row.get("start_time")),
        "end_time_value": _format_time_value(row.get("end_time")),
        "time": "N/A" if start_time == "N/A" or end_time == "N/A" else f"{start_time} - {end_time}",
        "room": _build_room(row.get("building"), row.get("room")),
        "color": "slate",
    }


def _common_selected_campus(selected_courses: list[dict[str, Any]]) -> str | None:
    campuses = {
        str(course.get("campus") or "").strip()
        for course in selected_courses
        if str(course.get("campus") or "").strip()
    }
    return next(iter(campuses)) if len(campuses) == 1 else None


def _campus_to_database_value(campus: str | None) -> str:
    normalized = _normalize_campus(campus)
    if normalized == "Beirut":
        return "1"
    if normalized == "Jbeil":
        return "2"
    return ""


def _normalize_campus(campus: Any) -> str:
    value = str(campus or "").strip().lower()
    if value in {"1", "beirut"}:
        return "Beirut"
    if value in {"2", "jbeil", "jbiel", "byblos"}:
        return "Jbeil"
    return "N/A"


def _value_or_na(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "N/A"
    return str(value).strip()


def _normalize_day_token(token: str) -> str:
    value = str(token or "").strip().upper()
    if value.startswith("MON") or value == "M":
        return "Monday"
    if value.startswith("TUE") or value in {"TU", "T"}:
        return "Tuesday"
    if value.startswith("WED") or value == "W":
        return "Wednesday"
    if value.startswith("THU") or value in {"TH", "R"}:
        return "Thursday"
    if value.startswith("FRI") or value == "F":
        return "Friday"
    return ""


def _normalize_days(days: Any) -> list[str]:
    raw_days = str(days or "").strip()
    if not raw_days:
        return []
    if re.search(r"[/,;]", raw_days):
        return list(dict.fromkeys(_normalize_day_token(token) for token in re.split(r"[/,;]", raw_days) if _normalize_day_token(token)))

    compact = re.sub(r"[^A-Z]", "", raw_days.upper())
    if compact in {"TBA", "TBD", "ARR", "ONLINE"}:
        return []

    normalized: list[str] = []
    index = 0
    while index < len(compact):
        remaining = compact[index:]
        if remaining.startswith("MON"):
            normalized.append("Monday")
            index += 3
        elif remaining.startswith("TUE"):
            normalized.append("Tuesday")
            index += 3
        elif remaining.startswith("WED"):
            normalized.append("Wednesday")
            index += 3
        elif remaining.startswith("THU"):
            normalized.append("Thursday")
            index += 3
        elif remaining.startswith("TH"):
            normalized.append("Thursday")
            index += 2
        elif remaining.startswith("FRI"):
            normalized.append("Friday")
            index += 3
        else:
            day = _normalize_day_token(compact[index])
            if day:
                normalized.append(day)
            index += 1
    return list(dict.fromkeys(normalized))


def _format_days_for_display(day_names: list[str]) -> str:
    return " / ".join(DAY_LABELS[day] for day in day_names if day in DAY_LABELS) or "N/A"


def _format_time(time_value: Any) -> str:
    value = str(time_value or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})", value)
    if not match:
        return "N/A"
    hours = int(match.group(1))
    minutes = int(match.group(2))
    suffix = "PM" if hours >= 12 else "AM"
    display_hours = hours % 12 or 12
    return f"{display_hours}:{minutes:02d} {suffix}"


def _format_time_value(time_value: Any) -> str:
    value = str(time_value or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})", value)
    if not match:
        return ""
    return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"


def _build_room(building: Any, room: Any) -> str:
    building_value = _value_or_na(building)
    room_value = _value_or_na(room)
    if building_value == "N/A" and room_value == "N/A":
        return "N/A"
    return f"{building_value} {room_value}".strip()


def _normalize_prerequisites(prerequisite: Any) -> list[str]:
    value = _value_or_na(prerequisite)
    if value == "N/A":
        return ["N/A"]
    return [item.strip() for item in value.split(",") if item.strip()]
