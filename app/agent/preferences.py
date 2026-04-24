from __future__ import annotations

import re


DEFAULT_MAX_CREDITS = 18.0
CREDIT_RE = re.compile(
    r"\b(?:take|want|need|limit(?:ed)?(?:\s+to)?|maximum|max|up\s+to|around|about)?\s*"
    r"(\d+(?:\.\d+)?)\s*(?:credits?|crs?|credit\s*hours?)\b",
    re.IGNORECASE,
)


def extract_max_credits(text: str, default: float = DEFAULT_MAX_CREDITS) -> float:
    matches = CREDIT_RE.findall(text)
    if not matches:
        return default
    value = float(matches[-1])
    return max(1.0, min(value, 24.0))
