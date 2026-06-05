from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _s(value: Any) -> str:
    return (value or "").strip()


def _append_plan_note(out: dict, note: str) -> None:
    note = _s(note)
    if not note:
        return
    notes = _s(out.get("notes"))
    if note in notes:
        return
    out["notes"] = f"{notes} | {note}" if notes else note


def domain_dem_path(data_dir: str | Path, domain_name: str) -> Path:
    domain_name = _s(domain_name)
    base = Path(data_dir)
    return (
        base
        / f"domain_{domain_name}"
        / "data"
        / "attributes"
        / "elevation"
        / "dem"
        / f"domain_{domain_name}_elv.tif"
    )


def domain_has_local_dem(data_dir: str | Path | None, domain_name: str) -> bool:
    if not data_dir or not _s(domain_name):
        return False
    return domain_dem_path(data_dir, domain_name).is_file()


def plan_uses_local_data(
    cfg: dict | None,
    steps: list[str] | None = None,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> bool:
    """True only when existing on-disk domain data should be used (no online fetch)."""
    cfg = cfg or {}
    steps = steps or []
    if {"acquire_attributes", "acquire_forcings"} & set(steps):
        return False

    domain_name = _s(cfg.get("domain_name"))
    if domain_name and data_dir and not domain_has_local_dem(data_dir, domain_name):
        if {"define_domain", "discretize_domain", "model_agnostic_preprocessing"} & set(steps):
            return False

    text = (user_request or "").lower()
    local_only_phrases = (
        "data_access local",
        "data access local",
        "do not download",
        "not download",
        "no download",
        "existing local",
        "already copied",
        "already present",
        "already on disk",
        "data already in symfluence_data",
        "attributes already",
        "forcings already",
    )
    if any(p in text for p in local_only_phrases):
        return True

    extra = cfg.get("extra_config") if isinstance(cfg.get("extra_config"), dict) else {}
    for key in ("DATA_ACCESS", "data_access"):
        if _s(extra.get(key)).upper() == "LOCAL":
            if domain_name and data_dir and domain_has_local_dem(data_dir, domain_name):
                return True
        if _s(cfg.get(key)).upper() == "LOCAL":
            if domain_name and data_dir and domain_has_local_dem(data_dir, domain_name):
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


_SKIP_ACQUIRE_ATTRIBUTES_PHRASES = (
    "do not run acquire_attributes",
    "don't run acquire_attributes",
    "skip acquire_attributes",
    "without acquire_attributes",
    "omit acquire_attributes",
    "reuse existing attributes",
    "attributes already",
    "attributes present",
    "do not download attributes",
)


def ensure_acquire_attributes_before_define_domain(
    plan: dict,
    user_request: str = "",
) -> dict:
    """define_domain (delineate) needs DEM; insert acquire_attributes when omitted."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    steps = list(out.get("steps") or [])
    if "define_domain" not in steps or "acquire_attributes" in steps:
        return out

    text = (user_request or "").lower()
    if any(p in text for p in _SKIP_ACQUIRE_ATTRIBUTES_PHRASES):
        return out

    idx = steps.index("define_domain")
    steps.insert(idx, "acquire_attributes")
    out["steps"] = steps

    _append_plan_note(
        out,
        "Inserted acquire_attributes before define_domain (DEM/attributes required for delineation).",
    )
    return out


def ensure_cloud_data_access_for_acquire_steps(plan: dict) -> dict:
    """Online fetch when acquire_* steps are in the plan (results still land under SYMFLUENCE_data)."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    steps = list(out.get("steps") or [])
    if not {"acquire_attributes", "acquire_forcings"} & set(steps):
        return out

    cfg = dict(out.get("config") or {})
    extra = dict(cfg.get("extra_config") or {}) if isinstance(cfg.get("extra_config"), dict) else {}
    already_cloud = (
        _s(cfg.get("data_access")).lower() == "cloud"
        or _s(extra.get("DATA_ACCESS")).lower() == "cloud"
    )
    extra["DATA_ACCESS"] = "cloud"
    cfg["data_access"] = "cloud"
    cfg["extra_config"] = extra
    out["config"] = cfg

    if not already_cloud:
        _append_plan_note(out, "DATA_ACCESS set to cloud for online attribute/forcing acquisition.")
    return out


def ensure_online_data_when_missing(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """If domain DEM is not on disk, use cloud acquisition and require bbox when needed."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    domain_name = _s(cfg.get("domain_name"))
    steps = list(out.get("steps") or [])

    out = ensure_acquire_attributes_before_define_domain(out, user_request)
    steps = list(out.get("steps") or [])

    needs_dem = bool({"define_domain", "discretize_domain", "acquire_attributes"} & set(steps))
    if needs_dem and domain_name and data_dir and not domain_has_local_dem(data_dir, domain_name):
        out = ensure_cloud_data_access_for_acquire_steps(out)
        cfg = dict(out.get("config") or {})
        if "acquire_attributes" not in steps:
            idx = steps.index("define_domain") if "define_domain" in steps else len(steps)
            steps.insert(idx, "acquire_attributes")
            out["steps"] = steps
            out = ensure_cloud_data_access_for_acquire_steps(out)

        if plan_requires_bounding_box(cfg, out.get("steps") or [], user_request):
            if not _s(cfg.get("bounding_box_coords")):
                needs = list(out.get("needs_user_input") or [])
                if "bounding_box_coords" not in needs:
                    needs.append("bounding_box_coords")
                out["needs_user_input"] = needs
        _append_plan_note(
            out,
            f"Local DEM missing for {domain_name}; using online acquisition (DATA_ACCESS cloud).",
        )

    return out


def normalize_local_workflow_plan(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
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

    out = ensure_online_data_when_missing(out, user_request, data_dir=data_dir)
    cfg = dict(out.get("config") or {})
    out["config"] = cfg
    steps = list(out.get("steps") or [])

    if not plan_uses_local_data(cfg, steps, user_request, data_dir=data_dir):
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
