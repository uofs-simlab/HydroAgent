"""Frozen call settings for the repeated-trial evaluation.

These values mirror the provider adapters. The runner records them with every
call so a later reader can see the temperature, sampling, and schema settings
that produced each raw response.
"""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

HYDROAGENT_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_PATH = HYDROAGENT_ROOT / "benchmarking" / "inputs" / "prompts.json"
REFERENCES_PATH = HYDROAGENT_ROOT / "benchmarking" / "inputs" / "references.json"
PLANNER_PROMPT_PATH = HYDROAGENT_ROOT / "prompts" / "planner_prompt.txt"

PAPER_MODELS = {
    "openai": "gpt-5-mini",
    "gemini": "gemini-2.5-flash",
    "claude": "claude-sonnet-4-20250514",
}

# Settings copied from server/llm/*_provider.py generate_run_plan().
CALL_SETTINGS = {
    "openai": {
        "requested_model": "gpt-5-mini",
        "temperature": None,
        "temperature_note": "Temperature is omitted for model names that start with gpt-5. Other OpenAI models in this adapter use 0.2.",
        "sampling": {"reasoning_effort": "low"},
        "max_output_tokens": 2500,
        "structured_output": {
            "first_attempt": "json_schema",
            "schema_name": "symfluence_run_plan",
            "fallback": "A second call without json_schema asks for one JSON object when the first response does not parse.",
        },
    },
    "gemini": {
        "requested_model": "gemini-2.5-flash",
        "temperature": 0.2,
        "sampling": {},
        "max_output_tokens": 8192,
        "structured_output": {
            "first_attempt": "response_mime_type application/json plus response_json_schema",
            "fallback": "A second call keeps application/json and drops response_json_schema. A short budget is retried at 8192 tokens.",
        },
    },
    "claude": {
        "requested_model": "claude-sonnet-4-20250514",
        "temperature": 0.2,
        "sampling": {},
        "max_output_tokens": 8192,
        "structured_output": {
            "first_attempt": "output_config.format json_schema",
            "fallback": "A second call drops json_schema. Temperature 0.2 is sent only when the model accepts it. A short budget is retried at 8192 tokens.",
        },
    },
}


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def sdk_version(provider: str) -> str | None:
    module_name = {"openai": "openai", "gemini": "google.genai", "claude": "anthropic"}.get(provider)
    if not module_name:
        return None
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return None
    return getattr(module, "__version__", None)


def protocol_record() -> dict:
    return {
        "experiment": "repeated_trials",
        "repeats_per_prompt": 3,
        "providers": CALL_SETTINGS,
        "inputs": {
            "prompts": str(PROMPTS_PATH),
            "prompts_sha256": file_sha256(PROMPTS_PATH),
            "references": str(REFERENCES_PATH),
            "references_sha256": file_sha256(REFERENCES_PATH),
            "planner_prompt": str(PLANNER_PROMPT_PATH),
            "planner_prompt_sha256": file_sha256(PLANNER_PROMPT_PATH),
        },
        "sdk_versions": {name: sdk_version(name) for name in PAPER_MODELS},
    }
