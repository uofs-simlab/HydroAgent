from __future__ import annotations


DEFAULT_USE_PROMPT_LIBRARY_EXAMPLES = False
DEFAULT_SAVE_PROMPT_HISTORY = False


def prompt_library_action_enabled(setting: object, api_key: str | None) -> bool:
    """Return whether an API-backed prompt-library action may run."""
    return bool(setting) and bool(str(api_key or "").strip())
