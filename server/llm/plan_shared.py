from __future__ import annotations
# Layout note: minor UI spacing tweaks.

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from server.core.plan_rules import (
    domain_name_needs_user_input,
    ensure_domain_name_user_input,
    extract_explicit_domain_name_from_request,
    mark_domain_name_confirmed,
    normalize_local_workflow_plan,
    plan_requires_bounding_box,
)

PLANNER_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "planner_prompt.txt"
PLAN_REFINEMENT_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "plan_refinement_prompt.txt"


def _normalize_domain_name_for_config(name: str | None):
    from server.core.ui_config_fields import normalize_domain_name_value

    if not name:
        return None
    cleaned = normalize_domain_name_value(str(name))
    return cleaned or None


def _extract_domain_name(text: str):
    """Deprecated loose extractor — use extract_explicit_domain_name_from_request."""
    return extract_explicit_domain_name_from_request(text) or None


def _compact_plan_config(cfg: dict) -> dict:
    core_keys = {
        "domain_name",
        "experiment_id",
        "pour_point_coords",
        "bounding_box_coords",
        "hydrological_model",
        "domain_def",
        "experiment_time_start",
        "experiment_time_end",
    }

    compact = {}
    for k, v in cfg.items():
        if k in core_keys:
            compact[k] = v
        elif v is not None:
            compact[k] = v
    return compact


def _extract_hydrological_model(text: str) -> str | None:
    if not text:
        return None

    from server.core.ui_config_fields import HYDROLOGICAL_MODEL_OPTIONS, normalize_hydrological_model

    upper = text.upper()
    for model in HYDROLOGICAL_MODEL_OPTIONS:
        if not model:
            continue
        if re.search(rf"\b{re.escape(model)}\b", upper):
            normalized = normalize_hydrological_model(model)
            return normalized or None

    return None


def _extract_bounding_box(text: str) -> str | None:
    from server.core.ui_config_fields import _extract_bbox_coords_from_text

    return _extract_bbox_coords_from_text(text)


def build_run_plan_schema() -> Dict[str, Any]:
    allowed_steps: List[str] = [
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

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "config": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "domain_name": {"type": ["string", "null"]},
                    "experiment_id": {"type": ["string", "null"]},
                    "pour_point_coords": {"type": ["string", "null"]},
                    "bounding_box_coords": {"type": ["string", "null"]},
                    "hydrological_model": {
                        "type": ["string", "null"],
                    },
                    "domain_def": {
                        "type": ["string", "null"],
                        "enum": ["lumped", "point", "subset", "delineate", None],
                    },
                    "experiment_time_start": {"type": ["string", "null"]},
                    "experiment_time_end": {"type": ["string", "null"]},
                    "spinup_period": {"type": ["string", "null"]},
                    "calibration_period": {"type": ["string", "null"]},
                    "evaluation_period": {"type": ["string", "null"]},
                    "forcing_dataset": {"type": ["string", "null"]},
                    "discretization": {"type": ["string", "null"]},
                    "routing_model": {"type": ["string", "null"]},
                    "DOWNLOAD_SNOTEL": {"type": ["boolean", "null"]},
                    "SNOTEL_STATION": {"type": ["string", "null"]},
                    "observations_path": {"type": ["string", "null"]},
                    "optimization_target": {"type": ["string", "null"]},
                    "optimization_metric": {"type": ["string", "null"]},
                    "calibration_timestep": {"type": ["string", "null"]},
                    "iterative_optimization_algorithm": {"type": ["string", "null"]},
                    "iterations": {"type": ["integer", "null"]},
                    "POPULATION_SIZE": {"type": ["integer", "null"]},
                    "params_to_calibrate": {"type": ["string", "null"]},
                    "NUM_PROCESSES": {"type": ["integer", "null"]},
                    "MPI_PROCESSES": {"type": ["integer", "null"]},
                    "extra_config": {
                        "type": ["object", "null"],
                        "additionalProperties": {
                            "type": ["string", "number", "integer", "boolean", "null"]
                        },
                        "description": "Explicit SYMFLUENCE YAML parameters from the user that are not first-class config fields.",
                    },
                },
                "required": [
                    "domain_name",
                    "experiment_id",
                    "pour_point_coords",
                    "bounding_box_coords",
                    "hydrological_model",
                    "domain_def",
                    "experiment_time_start",
                    "experiment_time_end",
                    "spinup_period",
                    "calibration_period",
                    "evaluation_period",
                    "forcing_dataset",
                    "discretization",
                    "routing_model",
                    "DOWNLOAD_SNOTEL",
                    "SNOTEL_STATION",
                    "observations_path",
                    "optimization_target",
                    "optimization_metric",
                    "calibration_timestep",
                    "iterative_optimization_algorithm",
                    "iterations",
                    "POPULATION_SIZE",
                    "params_to_calibrate",
                    "NUM_PROCESSES",
                    "MPI_PROCESSES",
                    "extra_config",
                ],
            },
            "steps": {
                "type": "array",
                "items": {"type": "string", "enum": allowed_steps},
                "minItems": 1,
            },
            "needs_user_input": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "domain_name",
                        "experiment_id",
                        "pour_point_coords",
                        "bounding_box_coords",
                        "hydrological_model",
                        "domain_def",
                        "forcing_dataset",
                        "discretization",
                        "experiment_time_start",
                        "experiment_time_end",
                        "spinup_period",
                        "calibration_period",
                        "evaluation_period",
                        "SNOTEL_STATION",
                    ],
                },
            },
            "notes": {"type": "string"},
        },
        "required": ["config", "steps", "needs_user_input", "notes"],
    }


def finalize_run_plan(
    plan: Dict[str, Any],
    user_request: str,
    *,
    skip_workflow_step_restore: bool = False,
) -> Dict[str, Any]:
    cfg = plan.get("config", {}) or {}

    if cfg.get("extra_config") is not None and not isinstance(cfg.get("extra_config"), dict):
        cfg["extra_config"] = None

    p = cfg.get("pour_point_coords")
    if isinstance(p, str):
        cfg["pour_point_coords"] = p.replace(",", "/").strip()

    bbox = cfg.get("bounding_box_coords")
    if isinstance(bbox, str):
        cfg["bounding_box_coords"] = bbox.replace(",", "/").strip()

    if not cfg.get("bounding_box_coords"):
        cfg["bounding_box_coords"] = _extract_bounding_box(user_request)

    if not cfg.get("hydrological_model"):
        cfg["hydrological_model"] = _extract_hydrological_model(user_request) or "SUMMA"
    else:
        from server.core.ui_config_fields import normalize_hydrological_model

        cfg["hydrological_model"] = normalize_hydrological_model(str(cfg["hydrological_model"]))

    start = cfg.get("experiment_time_start")
    if isinstance(start, str) and len(start.strip()) == 10:
        cfg["experiment_time_start"] = start.strip() + " 01:00"

    end = cfg.get("experiment_time_end")
    if isinstance(end, str) and len(end.strip()) == 10:
        cfg["experiment_time_end"] = end.strip() + " 23:00"

    if not cfg.get("experiment_id"):
        cfg["experiment_id"] = "exp_001"

    if not cfg.get("domain_def"):
        cfg["domain_def"] = "delineate"

    explicit_domain = extract_explicit_domain_name_from_request(user_request)
    if explicit_domain:
        cfg["domain_name"] = explicit_domain
        cfg = mark_domain_name_confirmed(cfg)
    elif cfg.get("domain_name"):
        cfg["domain_name"] = _normalize_domain_name_for_config(cfg["domain_name"])

    plan["config"] = cfg

    required_user_fields = [
        "domain_name",
        "hydrological_model",
        "pour_point_coords",
        "experiment_time_start",
        "experiment_time_end",
    ]

    steps_now = plan.get("steps", []) or []
    if plan_requires_bounding_box(cfg, steps_now, user_request):
        required_user_fields.append("bounding_box_coords")

    data_dir = Path.home() / "installs" / "SYMFLUENCE_data"
    missing = [
        f
        for f in required_user_fields
        if (
            f == "domain_name"
            and domain_name_needs_user_input(cfg, user_request, data_dir=data_dir)
        )
        or (f != "domain_name" and not cfg.get(f))
    ]

    if missing:
        plan["needs_user_input"] = missing
        plan["steps"] = ["validate_config", "dry_run"]
        plan["notes"] = (
            f"Missing required inputs: {', '.join(missing)}. "
            "Returning a safe validation/dry-run plan until those values are provided."
        )

    plan = ensure_domain_name_user_input(plan, user_request, data_dir=data_dir)
    plan = normalize_local_workflow_plan(
        plan,
        user_request,
        data_dir=data_dir,
        skip_workflow_step_restore=skip_workflow_step_restore,
    )
    cfg = dict(plan.get("config") or {})

    preferred_order = [
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

    current_steps = plan.get("steps", []) or []
    ordered_steps = [step for step in preferred_order if step in current_steps]
    if ordered_steps:
        plan["steps"] = ordered_steps

    extracted_fields = []
    for k in [
        "domain_name",
        "experiment_id",
        "hydrological_model",
        "pour_point_coords",
        "bounding_box_coords",
        "experiment_time_start",
        "experiment_time_end",
    ]:
        if cfg.get(k):
            extracted_fields.append(k)

    if extracted_fields:
        base_notes = plan.get("notes", "").strip()
        extra = f"Extracted fields: {', '.join(extracted_fields)}"
        plan["notes"] = f"{base_notes} | {extra}" if base_notes else extra

    plan["config"] = _compact_plan_config(cfg)
    return plan


def build_plan_refinement_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reply": {
                "type": "string",
                "description": "Short natural-language reply to the user.",
            },
            "update_plan": {
                "type": "boolean",
                "description": "True when the workflow plan should change.",
            },
            "plan": build_run_plan_schema(),
        },
        "required": ["reply", "update_plan", "plan"],
    }


def build_plan_refinement_user_prompt(
    *,
    current_plan: Dict[str, Any],
    user_message: str,
    conversation_excerpt: str = "",
    context_excerpt: str = "",
) -> str:
    lines = [
        "Current workflow plan (JSON):",
        json.dumps(current_plan, indent=2),
        "",
        f"Latest user message:\n{user_message.strip()}",
    ]
    if conversation_excerpt.strip():
        lines.extend(["", "Conversation so far:", conversation_excerpt.strip()])
    if context_excerpt.strip():
        lines.extend(["", "Runtime context:", context_excerpt.strip()])
    return "\n".join(lines).strip() + "\n"


def finalize_plan_refinement(
    result: Dict[str, Any],
    *,
    current_plan: Dict[str, Any],
    conversation_text: str,
    data_dir: Path | None = None,
) -> tuple[str, Dict[str, Any], bool]:
    reply = s(result.get("reply")) or "Done."
    update_plan = bool(result.get("update_plan"))
    if not update_plan:
        return reply, dict(current_plan), False

    new_plan = result.get("plan")
    if not isinstance(new_plan, dict):
        raise RuntimeError("Planner refinement returned invalid 'plan' (must be object).")

    required_top = {"config", "steps", "needs_user_input", "notes"}
    missing_top = [k for k in required_top if k not in new_plan]
    if missing_top:
        raise RuntimeError(f"Refined plan missing keys: {missing_top}")

    new_plan = finalize_run_plan(
        new_plan,
        conversation_text,
        skip_workflow_step_restore=True,
    )
    return reply, new_plan, True


def s(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
