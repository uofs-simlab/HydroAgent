"""Optional sink for benchmark stage snapshots.

Normal planning leaves this unset. A benchmark run sets a capture for the
duration of one generate_run_plan() call, and the provider adapters record
the raw API payload and the parsed plan before finalize_run_plan() rewrites it.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterator


def payload_to_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        try:
            return json.dumps(dump(), indent=2, default=str)
        except Exception:
            pass
    if isinstance(payload, (dict, list)):
        try:
            return json.dumps(payload, indent=2, default=str)
        except Exception:
            return str(payload)
    return str(payload)


@dataclass
class StageCapture:
    raw_sections: list[tuple[str, str]] = field(default_factory=list)
    parsed_plan: dict[str, Any] | None = None

    def add_raw(self, label: str, payload: Any) -> None:
        self.raw_sections.append((label, payload_to_text(payload)))

    def set_parsed(self, plan: dict[str, Any]) -> None:
        self.parsed_plan = deepcopy(plan)

    def raw_text(self) -> str:
        parts = []
        for label, text in self.raw_sections:
            parts.append(f"===== {label} =====\n{text.rstrip()}\n")
        return "\n".join(parts)


_current: ContextVar[StageCapture | None] = ContextVar(
    "hydroagent_stage_capture",
    default=None,
)


def record_raw(label: str, payload: Any) -> None:
    capture = _current.get()
    if capture is not None:
        capture.add_raw(label, payload)


def record_parsed_plan(plan: dict[str, Any] | None) -> None:
    capture = _current.get()
    if capture is not None and isinstance(plan, dict):
        capture.set_parsed(plan)


@contextmanager
def capture_stages() -> Iterator[StageCapture]:
    capture = StageCapture()
    token = _current.set(capture)
    try:
        yield capture
    finally:
        _current.reset(token)
