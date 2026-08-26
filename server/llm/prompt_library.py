"""LangPrompt integration for HydroAgent semantic prompt library."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import import_module
from typing import Any

DEFAULT_TOP_K = 5
SIMILARITY_ENRICH_THRESHOLD = 0.75

_store_cache: dict[tuple[str, str], Any] = {}
_PROMPT_FINDER: Any | None = None
_PROMPT_FINDER_ERROR: str | None = None


@dataclass(frozen=True)
class PromptMatch:
    title: str
    body: str
    score: float
    query_type: str
    source: str

    @classmethod
    def from_document(cls, doc: Any, score: float) -> PromptMatch:
        return cls(
            title=str(doc.metadata.get("title", "Prompt")),
            body=str(doc.metadata.get("body", doc.page_content)),
            score=float(score),
            query_type=str(doc.metadata.get("query_type", "text")),
            source=str(doc.metadata.get("source", "")),
        )


def _prompt_finder() -> Any:
    global _PROMPT_FINDER, _PROMPT_FINDER_ERROR
    if _PROMPT_FINDER is not None:
        return _PROMPT_FINDER
    if _PROMPT_FINDER_ERROR is not None:
        raise ImportError(_PROMPT_FINDER_ERROR)
    try:
        _PROMPT_FINDER = import_module("server.llm.prompt_finder")
        return _PROMPT_FINDER
    except ImportError as exc:
        _PROMPT_FINDER_ERROR = str(exc)
        raise


def langprompt_available() -> bool:
    try:
        _prompt_finder()
        return True
    except ImportError:
        return False


def langprompt_import_error() -> str | None:
    try:
        _prompt_finder()
        return None
    except ImportError as exc:
        return str(exc)


def _store_cache_key(api_key: str) -> tuple[str, str]:
    pf = _prompt_finder()
    docs = pf.load_prompts()
    fingerprint = pf._fingerprint(docs) if docs else "empty"
    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return key_hash, fingerprint


def get_vector_store(*, api_key: str, rebuild: bool = False) -> Any:
    """Return a cached LangPrompt vector store for the current library fingerprint."""
    pf = _prompt_finder()
    pf.load_api_key(api_key)
    cache_key = _store_cache_key(api_key)
    if not rebuild and cache_key in _store_cache:
        return _store_cache[cache_key]
    store = pf.build_store(rebuild=rebuild)
    _store_cache[cache_key] = store
    return store


def find_similar_prompts(
    query: str,
    *,
    api_key: str,
    top: int = DEFAULT_TOP_K,
    rebuild: bool = False,
) -> list[PromptMatch]:
    pf = _prompt_finder()
    store = get_vector_store(api_key=api_key, rebuild=rebuild)
    user_query = pf.prepare_query(query)
    results = pf.find_relevant(store, user_query.search_text, k=max(1, top))
    return [PromptMatch.from_document(doc, score) for doc, score in results]


def save_prompt_to_library(
    query: str,
    *,
    api_key: str,
    rebuild: bool = False,
) -> bool:
    """Append a user prompt to the library unless it already exists."""
    pf = _prompt_finder()
    store = get_vector_store(api_key=api_key, rebuild=rebuild)
    user_query = pf.prepare_query(query)
    saved = pf.save_user_query(store, user_query)
    if saved is not None:
        _store_cache.pop(_store_cache_key(api_key), None)
    return saved is not None


def display_body(match: PromptMatch, *, show_raw: bool = False) -> str:
    pf = _prompt_finder()
    if show_raw or match.query_type != "config_yaml":
        return match.body
    return pf._extract_search_text(match.body)


def enrich_planner_request(
    base_request: str,
    matches: list[PromptMatch],
    *,
    max_examples: int = 2,
    min_score: float = SIMILARITY_ENRICH_THRESHOLD,
) -> str:
    """Prepend similar past prompts as reference examples for the planner."""
    good = [match for match in matches if match.score >= min_score][:max_examples]
    if not good:
        return base_request

    lines = [
        "Similar past workflow requests from the prompt library (reference only; follow the user request below):",
        "",
    ]
    for index, match in enumerate(good, start=1):
        preview = display_body(match).strip()
        if len(preview) > 800:
            preview = preview[:797] + "..."
        lines.extend(
            [
                f"Example {index} (similarity {match.score:.2f}):",
                preview,
                "",
            ]
        )
    lines.extend(["---", "User request:", base_request.strip()])
    return "\n".join(lines).strip() + "\n"
