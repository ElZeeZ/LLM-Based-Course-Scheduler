from __future__ import annotations

from typing import Any


def build_course_context(courses: list[dict[str, Any]]) -> str:
    lines = []
    for course in courses:
        lines.append(
            "\n".join(
                [
                    f"{course.get('course_code')} - {course.get('course_name')}",
                    f"Section: {course.get('section')} | Credits: {course.get('credits')}",
                    f"Time: {course.get('days')} {course.get('start_time')}-{course.get('end_time')}",
                    f"Instructor: {course.get('instructor')}",
                    f"Description: {course.get('description') or course.get('document', '')}",
                ]
            )
        )
    return "\n\n".join(lines)
