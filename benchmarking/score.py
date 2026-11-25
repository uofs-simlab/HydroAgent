"""Score parsed plans against normalized plans and author references."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_PLAN_KEYS = ("config", "steps", "needs_user_input", "notes")
PAPER_MODELS = {
    "openai": "gpt-5-mini",
    "gemini": "gemini-3.6-flash",
    "claude": "claude-sonnet-5",
}
IDENTIFICATION = (
    "Scores follow the paper criteria in section 4.3. "
    "The top-level provider numbers use normalized_plan.json, the plan returned after finalize_run_plan(). "
    "resolved_plan uses resolved_plan.json, the plan after catalog dependency resolution, which is the plan the UI stores. "
    "parsed_plan repeats the same criteria on the JSON extracted from the provider, before correction. "
    "This run is a new evaluation and is not a reconstruction of the published 84–88% table."
)
PAPER_CRITERIA = (
    "schema_validity",
    "configuration_accuracy",
    "step_precision",
    "step_recall",
    "step_order_validity",
    "missing_input_detection",
    "constraint_compliance",
    "data_access_intent",
    "exact_plan_match",
)


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    if _empty(value):
        return None
    return value


def config_of(plan: dict | None) -> dict:
    if not isinstance(plan, dict):
        return {}
    cfg = plan.get("config")
    return dict(cfg) if isinstance(cfg, dict) else {}


def config_value(cfg: dict, key: str) -> Any:
    """Read a requested field from the plan config or from extra_config."""
    if key in cfg:
        return cfg.get(key)
    extra = cfg.get("extra_config")
    if isinstance(extra, dict):
        if key in extra:
            return extra.get(key)
        for extra_key, extra_value in extra.items():
            if str(extra_key).lower() == key.lower():
                return extra_value
    return None


def same_value(actual: Any, expected: Any) -> bool:
    if _norm(actual) == _norm(expected):
        return True
    try:
        actual_number = float(str(actual).strip().split()[0])
        expected_number = float(str(expected).strip().split()[0])
    except (TypeError, ValueError, IndexError):
        return False
    return actual_number == expected_number


def steps_of(plan: dict | None) -> list[str]:
    if not isinstance(plan, dict):
        return []
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, str)]


def schema_valid(plan: dict | None) -> bool:
    if not isinstance(plan, dict):
        return False
    if any(key not in plan for key in REQUIRED_PLAN_KEYS):
        return False
    if not isinstance(plan.get("config"), dict):
        return False
    if not isinstance(plan.get("steps"), list):
        return False
    if not all(isinstance(step, str) for step in plan.get("steps") or []):
        return False
    if not isinstance(plan.get("needs_user_input"), list):
        return False
    if not isinstance(plan.get("notes"), str):
        return False
    return True


def _name_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {item for item in values if isinstance(item, str) and item}


def _required_order_ok(generated: list[str], required: list[str]) -> bool:
    if any(step not in generated for step in required):
        return False
    positions = [generated.index(step) for step in required]
    return positions == sorted(positions)


def configuration_accuracy(plan: dict | None, reference: dict | None) -> float | None:
    """Equation (1): correct requested fields divided by requested fields."""
    requested = (reference or {}).get("requested_config") or {}
    if not isinstance(requested, dict) or not requested:
        return None
    cfg = config_of(plan)
    correct = sum(
        1 for key, expected in requested.items() if same_value(config_value(cfg, key), expected)
    )
    return correct / len(requested)


def step_precision(plan: dict | None, reference: dict | None) -> float:
    """Equation (2), left: fraction of generated steps that are in the reference set."""
    generated = set(steps_of(plan))
    required = _name_set((reference or {}).get("required_steps"))
    if not generated:
        return 0.0 if required else 1.0
    return len(generated & required) / len(generated)


def step_recall(plan: dict | None, reference: dict | None) -> float:
    """Equation (2), right: fraction of reference steps present in the generated plan."""
    generated = set(steps_of(plan))
    required = _name_set((reference or {}).get("required_steps"))
    if not required:
        return 1.0
    return len(generated & required) / len(required)


def step_order_validity(plan: dict | None, reference: dict | None) -> bool:
    required = [step for step in ((reference or {}).get("required_steps") or []) if isinstance(step, str)]
    return _required_order_ok(steps_of(plan), required)


def missing_input_detection(plan: dict | None, reference: dict | None) -> bool:
    """Mandatory omissions are listed, and values the prompt already gave are not listed."""
    expected = _name_set((reference or {}).get("needs_user_input"))
    actual: set[str] = set()
    if isinstance(plan, dict) and isinstance(plan.get("needs_user_input"), list):
        actual = {item for item in plan["needs_user_input"] if isinstance(item, str)}
    return expected == actual


def constraint_compliance(plan: dict | None, reference: dict | None) -> bool:
    generated = set(steps_of(plan))
    if _name_set((reference or {}).get("prohibited_steps")) & generated:
        return False
    prohibited_config = (reference or {}).get("prohibited_config") or {}
    cfg = config_of(plan)
    if isinstance(prohibited_config, dict):
        for key, bad_values in prohibited_config.items():
            if isinstance(bad_values, str):
                bad_values = [bad_values]
            actual = config_value(cfg, key)
            if _empty(actual):
                continue
            actual_text = str(actual).strip().casefold()
            if any(actual_text == str(bad).strip().casefold() for bad in bad_values):
                return False
    return True


def data_access_intent(plan: dict | None, reference: dict | None) -> bool:
    """True when a requested local or cloud choice is reproduced. Unspecified access passes."""
    requested = (reference or {}).get("requested_config") or {}
    if not isinstance(requested, dict) or "data_access" not in requested:
        return True
    return same_value(config_value(config_of(plan), "data_access"), requested["data_access"])


def exact_plan_match(plan: dict | None, reference: dict | None) -> bool | None:
    """All requested fields, required steps in order, no prohibited steps, and correct missing inputs."""
    if not reference:
        return None
    if not isinstance(plan, dict):
        return False
    accuracy = configuration_accuracy(plan, reference)
    if accuracy is None or accuracy < 1.0:
        return False
    if not step_order_validity(plan, reference):
        return False
    if not constraint_compliance(plan, reference):
        return False
    if not missing_input_detection(plan, reference):
        return False
    return True


def score_plan(plan: dict | None, reference: dict | None) -> dict[str, Any]:
    if not reference:
        return {name: None for name in PAPER_CRITERIA}
    return {
        "schema_validity": schema_valid(plan),
        "configuration_accuracy": configuration_accuracy(plan, reference),
        "step_precision": step_precision(plan, reference),
        "step_recall": step_recall(plan, reference),
        "step_order_validity": step_order_validity(plan, reference),
        "missing_input_detection": missing_input_detection(plan, reference),
        "constraint_compliance": constraint_compliance(plan, reference),
        "data_access_intent": data_access_intent(plan, reference),
        "exact_plan_match": exact_plan_match(plan, reference),
    }


def score_prompt(
    *,
    prompt_id: str,
    provider: str,
    model: str,
    parsed: dict | None,
    normalized: dict | None,
    resolved: dict | None,
    reference: dict | None,
) -> dict[str, Any]:
    return {
        "prompt_id": prompt_id,
        "provider": provider,
        "model": model,
        "scored_plan": "normalized",
        **score_plan(normalized, reference),
        "parsed_plan": score_plan(parsed, reference),
        "resolved_plan": score_plan(resolved, reference),
    }


def _macro(rows: list[dict], key: str) -> float | None:
    values = [row.get(key) for row in rows if row.get(key) is not None]
    if not values:
        return None
    if isinstance(values[0], bool):
        return sum(1 for value in values if value) / len(values)
    return sum(float(value) for value in values) / len(values)


def _criteria_summary(rows: list[dict]) -> dict[str, Any]:
    summary = {key: _macro(rows, key) for key in PAPER_CRITERIA}
    summary["exact_plan_match_count"] = sum(1 for row in rows if row.get("exact_plan_match") is True)
    return summary


def summarize_provider(rows: list[dict]) -> dict[str, Any]:
    summary: dict[str, Any] = {"n_prompts": len(rows), "scored_plan": "normalized"}
    summary.update(_criteria_summary(rows))
    summary["resolved_plan"] = _criteria_summary([row.get("resolved_plan") or {} for row in rows])
    return summary


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_prompts(path: Path) -> list[dict]:
    payload = load_json(path)
    prompts = payload.get("prompts") if isinstance(payload, dict) else payload
    if not isinstance(prompts, list):
        raise ValueError(f"{path} must contain a prompts list")
    cleaned = []
    for item in prompts:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        prompt_id = str(item.get("id") or "").strip()
        if not prompt_id or not text:
            continue
        cleaned.append(
            {
                "id": prompt_id,
                "category": str(item.get("category") or "").strip(),
                "text": text,
            }
        )
    return cleaned


def load_references(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    payload = load_json(path)
    if not isinstance(payload, dict):
        return {}
    references = payload.get("references") if isinstance(payload.get("references"), dict) else payload
    out: dict[str, dict] = {}
    for key, value in references.items():
        if str(key).startswith("_") or not isinstance(value, dict):
            continue
        out[str(key)] = value
    return out


def prompt_dirname(prompt_id: str) -> str:
    text = str(prompt_id).strip()
    if text.isdigit():
        return f"prompt_{int(text):03d}"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)
    return safe or "prompt"


def rescore_run(run_dir: Path, references: dict[str, dict] | None = None) -> dict[str, Any]:
    references = references or {}
    rows: list[dict] = []
    for provider_dir in sorted(path for path in run_dir.iterdir() if path.is_dir()):
        provider = provider_dir.name
        if provider not in PAPER_MODELS and provider.startswith("_"):
            continue
        for prompt_dir in sorted(path for path in provider_dir.iterdir() if path.is_dir()):
            parsed_path = prompt_dir / "parsed_plan.json"
            normalized_path = prompt_dir / "normalized_plan.json"
            resolved_path = prompt_dir / "resolved_plan.json"
            if not parsed_path.is_file() or not normalized_path.is_file():
                continue
            parsed = load_json(parsed_path)
            normalized = load_json(normalized_path)
            resolved = load_json(resolved_path) if resolved_path.is_file() else None
            meta_path = prompt_dir / "stage_counts.json"
            meta = load_json(meta_path) if meta_path.is_file() else {}
            prompt_id = str(meta.get("prompt_id") or prompt_dir.name.removeprefix("prompt_"))
            model = str(meta.get("model") or PAPER_MODELS.get(provider, ""))
            reference = references.get(prompt_id) or references.get(prompt_id.lstrip("0"))
            row = score_prompt(
                prompt_id=prompt_id,
                provider=provider,
                model=model,
                parsed=parsed if isinstance(parsed, dict) else None,
                normalized=normalized if isinstance(normalized, dict) else None,
                resolved=resolved if isinstance(resolved, dict) else None,
                reference=reference,
            )
            rows.append(row)
            write_json(prompt_dir / "stage_counts.json", row)

    by_provider: dict[str, list[dict]] = {}
    for row in rows:
        by_provider.setdefault(row["provider"], []).append(row)
    summary = {
        "identification": IDENTIFICATION,
        "run_dir": str(run_dir),
        "providers": {name: summarize_provider(items) for name, items in sorted(by_provider.items())},
        "prompts": rows,
    }
    write_json(run_dir / "summary.json", summary)
    return summary
