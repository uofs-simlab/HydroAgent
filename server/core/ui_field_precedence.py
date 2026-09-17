"""Track which workflow fields were deliberately edited in the GUI."""

from __future__ import annotations

from typing import Any, MutableMapping


EXPLICIT_UI_FIELDS_KEY = "_explicit_ui_fields"


def explicit_ui_fields(state: MutableMapping[str, Any]) -> set[str]:
    """Return the workflow fields explicitly changed by the user."""
    return set(state.get(EXPLICIT_UI_FIELDS_KEY) or ())


def mark_ui_fields_explicit(
    state: MutableMapping[str, Any],
    *fields: str,
) -> None:
    """Record a user edit without treating programmatic widget updates as edits."""
    explicit = explicit_ui_fields(state)
    explicit.update(field for field in fields if field)
    state[EXPLICIT_UI_FIELDS_KEY] = explicit


def clear_explicit_ui_fields(state: MutableMapping[str, Any]) -> None:
    """Forget edits from the previous workflow or loaded run."""
    state.pop(EXPLICIT_UI_FIELDS_KEY, None)


def ui_field_is_explicit(state: MutableMapping[str, Any], field: str) -> bool:
    return field in explicit_ui_fields(state)


def select_explicit_ui_values(
    state: MutableMapping[str, Any],
    values: MutableMapping[str, Any],
) -> dict[str, Any]:
    """Filter current widget values down to deliberate user edits."""
    explicit = explicit_ui_fields(state)
    return {key: value for key, value in values.items() if key in explicit}
