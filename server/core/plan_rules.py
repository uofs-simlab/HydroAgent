from __future__ import annotations

import re
from typing import Any


def _s(value: Any) -> str:
    return (value or "").strip()


def plan_uses_local_data(
    cfg: dict | None,
    steps: list[str] | None = None,
    user_request: str = "",
) -> bool:
    """True when the user intends to use existing domain data (no cloud downloads)."""
    cfg = cfg or {}
    steps = steps or []
    text = (user_request or "").lower()

    local_phrases = (
        "data_access local",
        "data access local",
        "local data",
        "do not download",
        "not download",
        "no download",
        "existing local",
        "already copied",
        "already present",
        "symfluence_data/domain_",
    )
    if any(p in text for p in local_phrases):
        if not {"acquire_attributes", "acquire_forcings"} & set(steps):
            return True

    extra = cfg.get("extra_config") if isinstance(cfg.get("extra_config"), dict) else {}
    for key in ("DATA_ACCESS", "data_access"):
        if _s(extra.get(key)).upper() == "LOCAL":
            if not {"acquire_attributes", "acquire_forcings"} & set(steps):
                return True
        if _s(cfg.get(key)).upper() == "LOCAL":
            if not {"acquire_attributes", "acquire_forcings"} & set(steps):
                return True

    return False


def plan_requires_bounding_box(
    cfg: dict | None,
    steps: list[str] | None = None,
    user_request: str = "",
) -> bool:
    """Bounding box is only needed for cloud forcing/attribute acquisition."""
    steps = steps or []
    if plan_uses_local_data(cfg, steps, user_request):
        return False
    return bool({"acquire_attributes", "acquire_forcings"} & set(steps))


WORKFLOW_STEP_NAMES = [
    "validate_config",
    "setup_project",
    "create_pour_point",
    "acquire_attributes",
    "define_domain",
    "discretize_domain",
    "process_observed_data",
    "acquire_forcings",
    "model_agnostic_preprocessing",
    "build_model_ready_store",
    "model_specific_preprocessing",
    "run_model",
    "calibrate_model",
    "run_emulation",
    "run_benchmarking",
    "run_decision_analysis",
    "run_sensitivity_analysis",
    "postprocess_results",
    "dry_run",
]


def normalize_local_workflow_plan(plan: dict, user_request: str = "") -> dict:
    """
    Fix plans for local-data / notebook-style workflows: no bbox gate, restore steps from prompt.
    Safe to call after LLM planning and on every UI refresh of needs_user_input.
    """
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    out["config"] = cfg
    steps = list(out.get("steps") or [])

    if not plan_uses_local_data(cfg, steps, user_request):
        return out

    needs = [x for x in (out.get("needs_user_input") or []) if x != "bounding_box_coords"]
    out["needs_user_input"] = needs

    if set(steps) <= {"validate_config", "dry_run"}:
        extracted = extract_steps_from_request(user_request, WORKFLOW_STEP_NAMES)
        if extracted:
            if "validate_config" not in extracted:
                extracted.insert(0, "validate_config")
            out["steps"] = extracted
            steps = out["steps"]

    if not out.get("needs_user_input"):
        notes = _s(out.get("notes"))
        if "Missing required inputs: bounding_box_coords" in notes:
            out["notes"] = (
                "Local-data workflow (no bounding box required). "
                "Steps restored from prompt where the planner returned only validate_config/dry_run."
            )

    return out


def extract_steps_from_request(user_request: str, allowed_steps: list[str]) -> list[str]:
    """Parse explicit workflow step names listed in the user prompt."""
    if not user_request:
        return []
    found: list[str] = []
    for step in allowed_steps:
        if step == "dry_run":
            continue
        if re.search(rf"\b{re.escape(step)}\b", user_request, flags=re.IGNORECASE):
            found.append(step)
    return found
