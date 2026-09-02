"""Shared period-string normalization for HydroAgent UI and plans."""

from __future__ import annotations

import re

_PERIOD_PARSE_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2})(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"
    r"\s*[,/]\s*"
    r"(\d{4}-\d{2}-\d{2})(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\s*$"
)


def normalize_period_text(value: str) -> str:
    """Return canonical 'YYYY-MM-DD, YYYY-MM-DD' or '' when blank."""
    text = (value or "").strip()
    if not text:
        return ""
    match = _PERIOD_PARSE_RE.match(text)
    if match:
        return f"{match.group(1)}, {match.group(2)}"
    return re.sub(r"\s*,\s*", ", ", text)
