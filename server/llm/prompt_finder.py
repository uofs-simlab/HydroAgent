"""LangPrompt - learn a library of prompts and retrieve the most relevant one.

How it works:
  1. Prompts live in ``prompts/``. Two formats are supported:
       - A numbered file (e.g. ``prompts.txt``) where each prompt begins with a
         line like ``1:`` and runs until the next ``2:`` marker.
       - A standalone ``.md``/``.txt`` file with optional ``--- ... ---`` front
         matter, treated as a single prompt.
  2. Each prompt is embedded with an OpenAI embedding model (via LangChain) and
     stored in an in-memory vector store. Embeddings are cached on disk so they
     are only recomputed when the prompt files change.
  3. When you "plug in" a new prompt (a query), we embed it, compare it against
     the library with cosine similarity, and print the closest matches.
  4. Every new user query is appended to ``prompts/prompts.txt`` (next number)
     so all queries are kept in one file like a cache. Exact duplicates are skipped.
  5. YAML config queries (flat ``KEY: value`` files) are normalized to ``Use ...``
     lines for matching; the full config is still cached in ``prompts.txt``.

Usage:
    python prompt_finder.py                       # interactive mode
    python prompt_finder.py -q "run summa preprocessing for bow river"
    python prompt_finder.py -f my_config.yaml
    python prompt_finder.py -f my_config.yaml --base template.yaml --intent "change time period"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings

HYDRO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = HYDRO_ROOT / "prompts" / "library"
PROMPTS_FILE = PROMPTS_DIR / "prompts.txt"
CACHE_DIR = PROMPTS_DIR / ".cache"
CACHE_STORE = CACHE_DIR / "vectorstore.json"
CACHE_META = CACHE_DIR / "meta.json"

DEFAULT_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
PROMPT_GLOBS = ("*.md", "*.txt")

CONFIG_TYPE_MARKER = "[config_yaml]"
NORMALIZED_MARKER = "--- normalized ---"
RAW_MARKER = "--- raw ---"

# Top-level scalar keys used for workflow matching (order preserved for output).
WORKFLOW_KEYS = (
    "DOMAIN_NAME",
    "EXPERIMENT_ID",
    "HYDROLOGICAL_MODEL",
    "DOMAIN_DEFINITION_METHOD",
    "SUB_GRID_DISCRETIZATION",
    "FORCING_DATASET",
    "POUR_POINT_COORDS",
    "BOUNDING_BOX_COORDS",
    "EXPERIMENT_TIME_START",
    "EXPERIMENT_TIME_END",
    "SPINUP_PERIOD",
    "CALIBRATION_PERIOD",
    "EVALUATION_PERIOD",
    "DOWNLOAD_SNOTEL",
    "SNOTEL_STATION",
    "DOWNLOAD_FLUXNET",
    "FLUXNET_STATION",
    "OPTIMIZATION_METRIC",
    "ITERATIVE_OPTIMIZATION_ALGORITHM",
    "NUMBER_OF_ITERATIONS",
    "POPULATION_SIZE",
    "NUM_PROCESSES",
)

YAML_TO_USE_KEY = {
    "DOMAIN_NAME": "domain_name",
    "EXPERIMENT_ID": "experiment_id",
    "EXPERIMENT_TIME_START": "experiment_time_start",
    "EXPERIMENT_TIME_END": "experiment_time_end",
    "CALIBRATION_PERIOD": "calibration_period",
    "EVALUATION_PERIOD": "evaluation_period",
    "SPINUP_PERIOD": "spinup_period",
    "POUR_POINT_COORDS": "pour_point_coords",
    "BOUNDING_BOX_COORDS": "bounding_box_coords",
    "DOMAIN_DEFINITION_METHOD": "domain_def",
    "HYDROLOGICAL_MODEL": "hydrological_model",
    "SUB_GRID_DISCRETIZATION": "discretization",
    "FORCING_DATASET": "forcing_dataset",
}

FLAT_CONFIG_LINE = re.compile(r"^([A-Z][A-Z0-9_]+):\s*(.*)$")
SKIP_CONFIG_VALUES = {"", "null", "default", "n/a"}


@dataclass
class UserQuery:
    """A query ready for search and cache storage."""

    search_text: str
    cache_text: str
    label: str
    query_type: str = "text"


# --------------------------------------------------------------------------- #
# API key handling
# --------------------------------------------------------------------------- #
def load_api_key(api_key: str | None = None) -> str:
    """Resolve the OpenAI API key for LangPrompt embeddings."""
    if api_key and api_key.strip():
        resolved = api_key.strip()
        os.environ["OPENAI_API_KEY"] = resolved
        return resolved

    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]

    # Minimal .env reader (avoids an extra dependency on python-dotenv).
    for env_file in (HYDRO_ROOT / ".env", HYDRO_ROOT.parent / "LangPrompt" / ".env"):
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "OPENAI_API_KEY":
                value = value.strip().strip('"').strip("'")
                if value and value != "sk-...":
                    os.environ["OPENAI_API_KEY"] = value
                    return value

    config_file = Path.home() / ".symfluence_assistant" / "config.yaml"
    if config_file.exists():
        try:
            import yaml

            cfg = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            value = str(cfg.get("openai_api_key", "")).strip()
            if value and value != "sk-your-key-here":
                os.environ["OPENAI_API_KEY"] = value
                return value
        except Exception:
            pass

    # Fallback: the apikey file shipped with the SYMFLUENCE project.
    fallback = HYDRO_ROOT.parent / "SYMFLUENCE" / "apikey"
    if fallback.exists():
        value = fallback.read_text(encoding="utf-8").strip()
        if value:
            os.environ["OPENAI_API_KEY"] = value
            return value

    raise ValueError(
        "No OpenAI API key found for LangPrompt. Save an OpenAI key in the UI, "
        "set OPENAI_API_KEY, or add openai_api_key to ~/.symfluence_assistant/config.yaml."
    )


# --------------------------------------------------------------------------- #
# YAML / flat config queries
# --------------------------------------------------------------------------- #
def _strip_config_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def parse_flat_config(text: str) -> Dict[str, str]:
    """Parse top-level ``KEY: value`` lines from a flat YAML-style config."""
    config: Dict[str, str] = {}
    for line in text.splitlines():
        if not line or line[0] in " \t-" or line.lstrip().startswith("#"):
            continue
        match = FLAT_CONFIG_LINE.match(line)
        if not match:
            continue
        key, value = match.group(1), _strip_config_value(match.group(2))
        if value.lower() in SKIP_CONFIG_VALUES:
            continue
        config[key] = value
    return config


def is_config_query(text: str) -> bool:
    """True when text looks like a flat YAML config (several ``KEY: value`` lines)."""
    flat_lines = sum(
        1
        for line in text.splitlines()
        if line.strip() and FLAT_CONFIG_LINE.match(line)
    )
    return flat_lines >= 3


def diff_config_keys(base: Dict[str, str], updated: Dict[str, str]) -> List[str]:
    changed: List[str] = []
    for key in WORKFLOW_KEYS:
        if key not in updated:
            continue
        if base.get(key) != updated.get(key):
            changed.append(key)
    return changed


def config_to_normalized_text(
    config: Dict[str, str],
    *,
    intent: Optional[str] = None,
    changed_keys: Optional[List[str]] = None,
) -> str:
    """Convert workflow fields to the ``Use key value`` style used in prompts.txt."""
    domain = config.get("DOMAIN_NAME", "unknown")
    lines = [f"Config query for {domain}."]
    if intent:
        lines.append(f"User intent: {intent}")
    if changed_keys:
        lines.append(f"Changed fields: {', '.join(changed_keys)}")
    lines.append("")

    for yaml_key in WORKFLOW_KEYS:
        if yaml_key not in config:
            continue
        use_key = YAML_TO_USE_KEY.get(yaml_key, yaml_key.lower())
        lines.append(f"Use {use_key} {config[yaml_key]}.")

    return "\n".join(lines).strip()


def format_config_cache(
    config: Dict[str, str],
    normalized: str,
    *,
    intent: Optional[str] = None,
) -> str:
    """Dual-format cache entry: metadata + normalized search text + raw workflow keys."""
    lines = [CONFIG_TYPE_MARKER]
    if intent:
        lines.append(f"User intent: {intent}")
    lines.extend(["", NORMALIZED_MARKER, normalized, "", RAW_MARKER])
    for key in WORKFLOW_KEYS:
        if key in config:
            lines.append(f"{key}: {config[key]}")
    return "\n".join(lines).strip()


def _extract_search_text(body: str) -> str:
    """Return the text used for embedding (normalized section when present)."""
    if CONFIG_TYPE_MARKER not in body or NORMALIZED_MARKER not in body:
        return body.strip()
    normalized = body.split(NORMALIZED_MARKER, 1)[1]
    if RAW_MARKER in normalized:
        normalized = normalized.split(RAW_MARKER, 1)[0]
    return normalized.strip()


def prepare_query(
    text: str,
    *,
    intent: Optional[str] = None,
    base_text: Optional[str] = None,
    force_config: bool = False,
) -> UserQuery:
    """Build a text or config query for search and cache storage."""
    text = text.strip()
    if not text:
        raise ValueError("Query text is empty.")

    if force_config or is_config_query(text):
        config = parse_flat_config(text)
        if not config:
            raise ValueError("Config query detected but no KEY: value fields were parsed.")

        changed_keys: Optional[List[str]] = None
        if base_text:
            base_config = parse_flat_config(base_text)
            changed_keys = diff_config_keys(base_config, config)

        normalized = config_to_normalized_text(
            config,
            intent=intent,
            changed_keys=changed_keys,
        )
        cache_text = format_config_cache(config, normalized, intent=intent)
        domain = config.get("DOMAIN_NAME", "config")
        label = f"config:{domain}"
        if intent:
            label = f"{label} ({intent})"
        return UserQuery(
            search_text=normalized,
            cache_text=cache_text,
            label=label,
            query_type="config_yaml",
        )

    return UserQuery(
        search_text=text,
        cache_text=text,
        label=text if len(text) <= 80 else text[:77] + "...",
        query_type="text",
    )


# --------------------------------------------------------------------------- #
# Loading prompts
# --------------------------------------------------------------------------- #
def _parse_front_matter(text: str) -> Tuple[dict, str]:
    """Split optional ``--- ... ---`` YAML-ish front matter from the body."""
    meta: dict = {}
    body = text
    stripped = text.lstrip()

    # Case 1: Front matter is delimited by '---' at the beginning and end
    if stripped.startswith("---"):
        end_delimiter_pos = stripped.find("---", 3) # Find the second '---'
        if end_delimiter_pos != -1:
            header_str = stripped[3:end_delimiter_pos]
            body = stripped[end_delimiter_pos + 3 :].lstrip("\n")
            for line in header_str.splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    meta[key.strip()] = value.strip()
            return meta, body.strip()

    # Case 2: No '---' at the beginning, but header is separated by a double newline
    # This assumes the "header" is at the very beginning and ends with '\n\n'
    double_newline_pos = stripped.find("\n\n")
    if double_newline_pos != -1:
        header_str = stripped[:double_newline_pos]
        body = stripped[double_newline_pos:].lstrip("\n") # Correctly get body after '\n\n'
        for line in header_str.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
        return meta, body.strip()

    # If neither case matches, return empty meta and the original text as body
    return meta, body.strip()


# A line consisting only of a number followed by a colon, e.g. "1:" or "17:".
NUMBERED_MARKER = re.compile(r"^\s*(\d+)\s*:\s*$")


def _parse_numbered_prompts(text: str, source: str) -> List[Document]:
    """Split a file where each prompt starts with a ``N:`` marker line.

    The text after a marker (including blank lines) belongs to that prompt until
    the next marker is reached. Prompts keep their original number.
    """
    docs: List[Document] = []
    current_num: int | None = None
    buffer: List[str] = []

    def flush() -> None:
        if current_num is None:
            return
        body = "\n".join(buffer).strip()
        if not body:
            return
        search_text = _extract_search_text(body)
        query_type = "config_yaml" if CONFIG_TYPE_MARKER in body else "text"
        docs.append(
            Document(
                page_content=search_text,
                metadata={
                    "source": f"{source}#{current_num}",
                    "title": f"Prompt {current_num}",
                    "tags": query_type,
                    "body": body,
                    "number": current_num,
                    "query_type": query_type,
                },
            )
        )

    for line in text.splitlines():
        marker = NUMBERED_MARKER.match(line)
        if marker:
            flush()
            current_num = int(marker.group(1))
            buffer = []
        else:
            buffer.append(line)
    flush()

    docs.sort(key=lambda d: d.metadata["number"])
    return docs


def _is_numbered_file(text: str) -> bool:
    """True if the file uses the ``N:`` numbered-prompt format."""
    return any(NUMBERED_MARKER.match(line) for line in text.splitlines())


def load_prompts() -> List[Document]:
    """Read every prompt file in ``prompts/library/`` into LangChain Documents."""
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(
        {p for pattern in PROMPT_GLOBS for p in PROMPTS_DIR.glob(pattern)}
    )
    if not files:
        return []

    docs: List[Document] = []
    for path in files:
        raw = path.read_text(encoding="utf-8")

        # Numbered file -> one Document per "N:" entry.
        if _is_numbered_file(raw):
            docs.extend(_parse_numbered_prompts(raw, path.name))
            continue

        # Otherwise -> a single prompt (with optional front matter).
        meta, body = _parse_front_matter(raw)
        title = meta.get("title", path.stem.replace("_", " "))
        tags = meta.get("tags", "")
        # Embed title + tags + body together for richer matching.
        searchable = f"Title: {title}\nTags: {tags}\n\n{body}".strip()
        docs.append(
            Document(
                page_content=searchable,
                metadata={
                    "source": path.name,
                    "title": title,
                    "tags": tags,
                    "body": body,
                },
            )
        )

    return docs


def _normalize_text(text: str) -> str:
    """Collapse whitespace for duplicate checks."""
    return " ".join(text.split())


def _make_numbered_document(number: int, user_query: UserQuery, source: str) -> Document:
    return Document(
        page_content=user_query.search_text,
        metadata={
            "source": f"{source}#{number}",
            "title": f"Prompt {number}",
            "tags": user_query.query_type,
            "body": user_query.cache_text,
            "number": number,
            "query_type": user_query.query_type,
        },
    )


def _next_prompt_number(text: str) -> int:
    numbers = [
        int(match.group(1))
        for line in text.splitlines()
        if (match := NUMBERED_MARKER.match(line))
    ]
    return max(numbers, default=0) + 1


def _persist_vector_cache(store: InMemoryVectorStore) -> None:
    docs = load_prompts()
    CACHE_DIR.mkdir(exist_ok=True)
    store.dump(str(CACHE_STORE))
    CACHE_META.write_text(
        json.dumps({"fingerprint": _fingerprint(docs)}),
        encoding="utf-8",
    )


def save_user_query(store: InMemoryVectorStore, user_query: UserQuery) -> Document | None:
    """Append a new user query to ``prompts.txt`` unless it already exists."""
    if not user_query.cache_text.strip():
        return None

    PROMPTS_DIR.mkdir(exist_ok=True)
    if not PROMPTS_FILE.exists():
        PROMPTS_FILE.write_text("", encoding="utf-8")

    raw = PROMPTS_FILE.read_text(encoding="utf-8")
    existing = _parse_numbered_prompts(raw, PROMPTS_FILE.name)
    normalized_cache = _normalize_text(user_query.cache_text)
    for doc in existing:
        if _normalize_text(doc.metadata["body"]) == normalized_cache:
            return None

    next_num = _next_prompt_number(raw)
    entry = f"\n{next_num}:\n{user_query.cache_text}\n"
    if raw and not raw.endswith("\n"):
        raw += "\n"
    PROMPTS_FILE.write_text(raw + entry, encoding="utf-8")

    doc = _make_numbered_document(next_num, user_query, PROMPTS_FILE.name)
    store.add_documents([doc])
    _persist_vector_cache(store)
    kind = "config query" if user_query.query_type == "config_yaml" else "query"
    print(f"Saved new {kind} as Prompt {next_num} in {PROMPTS_FILE.name}.")
    return doc


def _fingerprint(docs: List[Document]) -> str:
    """A stable hash of the library + embedding model, used to validate the cache."""
    hasher = hashlib.sha256()
    hasher.update(DEFAULT_EMBEDDING_MODEL.encode())
    for doc in docs:
        hasher.update(doc.metadata["source"].encode())
        hasher.update(doc.page_content.encode())
    return hasher.hexdigest()


# --------------------------------------------------------------------------- #
# Vector store (build / cache)
# --------------------------------------------------------------------------- #
def build_store(rebuild: bool = False) -> InMemoryVectorStore:
    """Build the vector store, reusing a cached copy when the prompts are unchanged."""
    docs = load_prompts()
    embeddings = OpenAIEmbeddings(model=DEFAULT_EMBEDDING_MODEL)
    if not docs:
        return InMemoryVectorStore(embeddings)

    fingerprint = _fingerprint(docs)

    if not rebuild and CACHE_STORE.exists() and CACHE_META.exists():
        try:
            meta = json.loads(CACHE_META.read_text(encoding="utf-8"))
            if meta.get("fingerprint") == fingerprint:
                print(f"Loaded {len(docs)} prompts from cache.")
                return InMemoryVectorStore.load(str(CACHE_STORE), embeddings)
        except Exception:
            pass  # Corrupt cache -> rebuild below.

    print(f"Embedding {len(docs)} prompts with '{DEFAULT_EMBEDDING_MODEL}'...")
    store = InMemoryVectorStore(embeddings)
    store.add_documents(docs)

    CACHE_DIR.mkdir(exist_ok=True)
    store.dump(str(CACHE_STORE))
    CACHE_META.write_text(json.dumps({"fingerprint": fingerprint}), encoding="utf-8")
    return store


# --------------------------------------------------------------------------- #
# Retrieval + presentation
# --------------------------------------------------------------------------- #
def find_relevant(
    store: InMemoryVectorStore, query: str, k: int = 5
) -> List[Tuple[Document, float]]:
    results = store.similarity_search_with_score(query, k=k)
    # Sort by similarity score, highest (most relevant) first.
    results.sort(key=lambda pair: pair[1], reverse=True)
    return results


def print_match(
    doc: Document,
    score: float,
    rank: int | None = None,
    *,
    show_raw: bool = False,
) -> None:
    header = f"#{rank} " if rank is not None else ""
    query_type = doc.metadata.get("query_type", "text")
    print("=" * 70)
    print(f"{header}{doc.metadata['title']}  ({doc.metadata['source']})")
    print(f"similarity: {score:.3f}   type: {query_type}")
    print("-" * 70)
    body = doc.metadata.get("body", doc.page_content)
    if show_raw or query_type != "config_yaml":
        print(body)
    else:
        print(_extract_search_text(body))
    print("=" * 70)


def run_once(
    store: InMemoryVectorStore,
    user_query: UserQuery,
    top: int,
    *,
    show_raw: bool = False,
) -> None:
    save_user_query(store, user_query)
    results = find_relevant(store, user_query.search_text, k=top)
    if not results:
        print("No matching prompt found.")
        return

    print(f"\nTop {min(top, len(results))} prompts for: {user_query.label}\n")
    for i, (doc, score) in enumerate(results, start=1):
        print_match(doc, score, rank=i, show_raw=show_raw)


def _read_config_file(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    return path.read_text(encoding="utf-8")


def interactive(store: InMemoryVectorStore, top: int, *, show_raw: bool = False) -> None:
    print("\nLangPrompt ready. Type a prompt/idea to find the closest match.")
    print("Commands:")
    print("  :q          quit")
    print("  :k N        show top N matches")
    print("  :file PATH  load a YAML config file")
    print("  :intent TXT optional intent for the next :file query\n")
    pending_intent: Optional[str] = None

    while True:
        try:
            query = input("prompt> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query in (":q", ":quit", "exit"):
            break
        if query.startswith(":k"):
            parts = query.split()
            if len(parts) == 2 and parts[1].isdigit():
                top = max(1, int(parts[1]))
                print(f"Now showing top {top} matches.")
            else:
                print("Usage: :k N")
            continue
        if query.startswith(":intent "):
            pending_intent = query[len(":intent ") :].strip() or None
            print(f"Intent set: {pending_intent!r}")
            continue
        if query.startswith(":file "):
            config_path = Path(query[len(":file ") :].strip()).expanduser()
            config_text = _read_config_file(config_path)
            user_query = prepare_query(
                config_text,
                intent=pending_intent,
                force_config=True,
            )
            pending_intent = None
            run_once(store, user_query, top, show_raw=show_raw)
            continue

        user_query = prepare_query(query, intent=pending_intent)
        pending_intent = None
        run_once(store, user_query, top, show_raw=show_raw)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find the most relevant prompt from your prompt library."
    )
    parser.add_argument("-q", "--query", help="A text prompt to match. Omit for interactive mode.")
    parser.add_argument(
        "-f",
        "--config-file",
        type=Path,
        help="YAML/flat config file to use as the query.",
    )
    parser.add_argument(
        "--base",
        type=Path,
        help="Base config file; changed workflow fields are highlighted in the query.",
    )
    parser.add_argument(
        "--intent",
        help="Optional intent text for config queries (e.g. 'change the time period').",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="How many matches to show, sorted by similarity descending (default: 5).",
    )
    parser.add_argument("--rebuild", action="store_true", help="Force re-embedding (ignore cache).")
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="When printing config matches, show the full cached entry.",
    )
    args = parser.parse_args(argv)

    if args.query and args.config_file:
        parser.error("Use either --query or --config-file, not both.")

    load_api_key()
    store = build_store(rebuild=args.rebuild)
    top = max(1, args.top)

    if args.config_file:
        config_text = _read_config_file(args.config_file)
        base_text = _read_config_file(args.base) if args.base else None
        user_query = prepare_query(
            config_text,
            intent=args.intent,
            base_text=base_text,
            force_config=True,
        )
        run_once(store, user_query, top, show_raw=args.show_raw)
    elif args.query:
        base_text = _read_config_file(args.base) if args.base else None
        user_query = prepare_query(
            args.query,
            intent=args.intent,
            base_text=base_text,
        )
        run_once(store, user_query, top, show_raw=args.show_raw)
    else:
        interactive(store, top, show_raw=args.show_raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
