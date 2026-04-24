from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any


DAY_ALIASES = {
    "M": "Mon",
    "MON": "Mon",
    "MONDAY": "Mon",
    "T": "Tue",
    "TU": "Tue",
    "TUE": "Tue",
    "TUES": "Tue",
    "TUESDAY": "Tue",
    "W": "Wed",
    "WED": "Wed",
    "WEDNESDAY": "Wed",
    "R": "Thu",
    "TH": "Thu",
    "THU": "Thu",
    "THUR": "Thu",
    "THURS": "Thu",
    "THURSDAY": "Thu",
    "F": "Fri",
    "FRI": "Fri",
    "FRIDAY": "Fri",
    "S": "Sat",
    "SA": "Sat",
    "SAT": "Sat",
    "SATURDAY": "Sat",
    "U": "Sun",
    "SU": "Sun",
    "SUN": "Sun",
    "SUNDAY": "Sun",
}
DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
COURSE_CODE_RE = re.compile(r"\b[A-Z]{2,5}\s*\d{3}[A-Z]?\b")


def normalize_days(value: Any) -> list[str]:
    if value in (None, "", "TBA"):
        return []
    if isinstance(value, list):
        raw = " ".join(str(item) for item in value)
    else:
        raw = str(value)

    cleaned = raw.replace(",", " ").replace("/", " ").replace("-", " ")
    tokens = [token.strip().upper() for token in cleaned.split() if token.strip()]
    days: list[str] = []

    if len(tokens) > 1:
        for token in tokens:
            days.extend(_parse_day_token(token))
    else:
        days.extend(_parse_day_token(tokens[0] if tokens else cleaned.strip().upper()))

    return [day for day in DAY_ORDER if day in set(days)]


def _parse_day_token(token: str) -> list[str]:
    if token in DAY_ALIASES:
        return [DAY_ALIASES[token]]

    compact = re.sub(r"[^A-Z]", "", token)
    days: list[str] = []
    index = 0
    while index < len(compact):
        if compact.startswith("TH", index):
            days.append("Thu")
            index += 2
            continue
        char = compact[index]
        mapped = DAY_ALIASES.get(char)
        if mapped:
            days.append(mapped)
        index += 1
    return days


def parse_time_value(value: Any) -> time | None:
    if value in (None, "", "TBA"):
        return None
    raw = str(value).strip().lower().replace(".", "")
    formats = ("%I:%M %p", "%I %p", "%H:%M", "%H")
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def parse_meeting_time(value: Any) -> tuple[list[str], str | None, str | None]:
    if value in (None, "", "TBA"):
        return [], None, None
    raw = str(value).strip()
    match = re.match(
        r"^(?P<days>[A-Za-z,\s/]+?)\s+"
        r"(?P<start>\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)\s*-\s*"
        r"(?P<end>\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)$",
        raw,
    )
    if not match:
        return normalize_days(raw), None, None

    start_raw = _inherit_meridiem(match.group("start"), match.group("end"))
    end_raw = match.group("end")
    start = parse_time_value(start_raw)
    end = parse_time_value(end_raw)
    return (
        normalize_days(match.group("days")),
        format_time(start),
        format_time(end),
    )


def _inherit_meridiem(start: str, end: str) -> str:
    if re.search(r"\b(am|pm)\b", start, re.IGNORECASE):
        return start
    meridiem = re.search(r"\b(am|pm)\b", end, re.IGNORECASE)
    return f"{start} {meridiem.group(1)}" if meridiem else start


def format_time(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


def day_overlap(left: Any, right: Any) -> bool:
    return bool(set(normalize_days(left)) & set(normalize_days(right)))


def time_conflict(left_start: Any, left_end: Any, right_start: Any, right_end: Any) -> bool:
    ls = parse_time_value(left_start)
    le = parse_time_value(left_end)
    rs = parse_time_value(right_start)
    re = parse_time_value(right_end)
    if not all((ls, le, rs, re)):
        return False
    return ls < re and rs < le


def sections_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if not day_overlap(left.get("days"), right.get("days")):
        return False
    return time_conflict(
        left.get("start_time"),
        left.get("end_time"),
        right.get("start_time"),
        right.get("end_time"),
    )


def check_schedule_conflicts(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for index, left in enumerate(sections):
        for right in sections[index + 1 :]:
            if sections_conflict(left, right):
                conflicts.append(
                    {
                        "course_a": left.get("course_code"),
                        "section_a": left.get("section"),
                        "course_b": right.get("course_code"),
                        "section_b": right.get("section"),
                        "reason": "Overlapping meeting days and times.",
                    }
                )
    return conflicts


def prerequisites_satisfied(course: dict[str, Any], completed_courses: set[str]) -> tuple[bool, list[str]]:
    required = extract_prerequisite_codes(course.get("prerequisites"))
    missing = [code for code in required if normalize_course_code(code) not in completed_courses]
    return not missing, missing


def extract_prerequisite_codes(value: Any) -> list[str]:
    if value in (None, "", [], "None", "none", "N/A", "TBA"):
        return []
    if isinstance(value, list):
        raw = " ".join(str(item) for item in value)
    else:
        raw = str(value)
    return [normalize_course_code(code) for code in COURSE_CODE_RE.findall(raw)]


def normalize_course_code(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").upper()).strip()
