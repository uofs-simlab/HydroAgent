from __future__ import annotations
# Layout note: minor UI spacing tweaks.

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


def domain_attributes_root(data_dir: str | Path, domain_name: str) -> Path:
    return Path(data_dir) / f"domain_{_s(domain_name)}" / "data" / "attributes"


def domain_root(data_dir: str | Path, domain_name: str) -> Path:
    return Path(data_dir) / f"domain_{_s(domain_name)}"


def domain_catchment_shapefile_candidates(
    data_dir: str | Path,
    domain_name: str,
    experiment_id: str = "run_1",
) -> list[Path]:
    root = domain_root(data_dir, domain_name)
    name = _s(domain_name)
    exp = _s(experiment_id) or "run_1"
    return [
        root / "shapefiles" / "catchment" / "semidistributed" / "into" / f"{name}_HRUs_GRUs.shp",
        root / "shapefiles" / "catchment" / "semidistributed" / exp / f"{name}_HRUs_GRUs.shp",
        root / "shapefiles" / "catchment" / "delineate" / exp / f"{name}_HRUs_GRUs.shp",
    ]


def _shapefile_record_count(path: Path) -> int:
    """Read feature count from a shapefile DBF header (no geopandas required)."""
    dbf = path.with_suffix(".dbf")
    if not dbf.is_file():
        return 0
    try:
        with dbf.open("rb") as handle:
            handle.seek(4)
            return int.from_bytes(handle.read(4), "little")
    except OSError:
        return 0


def domain_catchment_hru_count(data_dir: str | Path, domain_name: str, experiment_id: str = "run_1") -> int:
    """Return HRU count from the best available catchment shapefile, or 0."""
    best = 0
    for path in domain_catchment_shapefile_candidates(data_dir, domain_name, experiment_id):
        if not path.is_file():
            continue
        count = 0
        try:
            import geopandas as gpd

            gdf = gpd.read_file(path)
            for col in ("HRU_ID", "hru_id", "hruId"):
                if col in gdf.columns:
                    count = int(gdf[col].nunique())
                    break
            if count == 0 and len(gdf) > 0:
                count = len(gdf)
        except Exception:
            count = _shapefile_record_count(path)
        best = max(best, count)
    return best


def domain_has_local_discretization(
    data_dir: str | Path | None,
    domain_name: str,
    experiment_id: str = "run_1",
    *,
    min_hrus: int = 2,
) -> bool:
    if not data_dir or not _s(domain_name):
        return False
    return domain_catchment_hru_count(data_dir, domain_name, experiment_id) >= min_hrus


def domain_has_local_summa_forcing(data_dir: str | Path | None, domain_name: str) -> bool:
    if not data_dir or not _s(domain_name):
        return False
    forcing_dir = domain_root(data_dir, domain_name) / "data" / "forcing" / "SUMMA_input"
    return any(forcing_dir.glob("*.nc"))


def domain_has_complete_local_workflow(
    data_dir: str | Path | None,
    domain_name: str,
    experiment_id: str = "run_1",
) -> bool:
    """True when catchment HRUs and SUMMA forcing already exist and should be reused."""
    return (
        domain_has_local_discretization(data_dir, domain_name, experiment_id)
        and domain_has_local_summa_forcing(data_dir, domain_name)
        and domain_has_local_attributes(data_dir, domain_name)
    )


def domain_streamflow_processed_path(data_dir: str | Path, domain_name: str) -> Path:
    name = _s(domain_name)
    root = domain_root(data_dir, name)
    candidates = [
        root
        / "data"
        / "observations"
        / "streamflow"
        / "preprocessed"
        / f"{name}_streamflow_processed.csv",
        root
        / "observations"
        / "streamflow"
        / "preprocessed"
        / f"{name}_streamflow_processed.csv",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def domain_has_local_streamflow(data_dir: str | Path | None, domain_name: str) -> bool:
    if not data_dir or not _s(domain_name):
        return False
    return domain_streamflow_processed_path(data_dir, domain_name).is_file()


def extract_station_id_from_request(user_request: str) -> str:
    text = user_request or ""
    patterns = (
        r"station_id\s*[:=]\s*['\"]?([A-Za-z0-9]+)",
        r"STATION_ID\s*[:=]\s*['\"]?([A-Za-z0-9]+)",
        r"\bstation\s+['\"]?(\d{2}[A-Z]{2}\d{3})['\"]?",
        r"\bWSC\s+['\"]?(\d{2}[A-Z]{2}\d{3})['\"]?",
        r"\b(\d{2}BB\d{3})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _s(match.group(1))
    return ""


def ensure_plan_station_id(plan: dict, user_request: str = "") -> dict:
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    if _s(cfg.get("station_id")):
        out["config"] = cfg
        return out
    station_id = extract_station_id_from_request(user_request)
    if not station_id:
        out["config"] = cfg
        return out
    cfg["station_id"] = station_id
    out["config"] = cfg
    _append_plan_note(out, f"Extracted station_id {station_id} from user request.")
    return out


def ensure_skip_process_observed_when_local_streamflow(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
    symfluence_domain: str = "",
) -> dict:
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    domain_name = _s(symfluence_domain) or _s(cfg.get("domain_name"))
    steps = list(out.get("steps") or [])
    if user_requires_fresh_cloud_workflow(user_request, cfg):
        return out
    if "process_observed_data" not in steps:
        return out
    if not domain_name or not data_dir:
        return out
    if not domain_has_local_streamflow(data_dir, domain_name):
        return out
    out["steps"] = [step for step in steps if step != "process_observed_data"]
    _append_plan_note(
        out,
        "Skipped process_observed_data; reusing existing local preprocessed streamflow.",
    )
    return out


def domain_has_local_attributes(data_dir: str | Path | None, domain_name: str) -> bool:
    """True when DEM plus at least one land/soil raster already exists on disk."""
    if not domain_has_local_dem(data_dir, domain_name):
        return False
    root = domain_attributes_root(Path(data_dir), domain_name)
    patterns = (
        "elevation/dem/*.tif",
        "landclass/**/*.tif",
        "landclass/*.tif",
        "soilclass/**/*.tif",
        "soilclass/*.tif",
    )
    land_or_soil = False
    for pattern in patterns:
        if "landclass" in pattern or "soilclass" in pattern:
            if list(root.glob(pattern)):
                land_or_soil = True
                break
    return land_or_soil


_DOWNLOAD_STEP_FORBID_PHRASES: dict[str, tuple[str, ...]] = {
    "acquire_attributes": (
        "do not include acquire_attributes",
        "do not run acquire_attributes",
        "don't include acquire_attributes",
        "don't run acquire_attributes",
        "skip acquire_attributes",
        "without acquire_attributes",
        "omit acquire_attributes",
        "do not download new attributes",
        "do not download attributes",
        "no acquire_attributes",
    ),
    "acquire_forcings": (
        "do not include acquire_forcings",
        "do not run acquire_forcings",
        "don't include acquire_forcings",
        "don't run acquire_forcings",
        "skip acquire_forcings",
        "without acquire_forcings",
        "omit acquire_forcings",
        "do not download new forcing",
        "do not download forcing",
        "do not download forcings",
        "no acquire_forcings",
    ),
    "process_observed_data": (
        "do not include process_observed_data",
        "do not run process_observed_data",
        "do not download new observations",
        "do not download observations",
    ),
}


_FRESH_CLOUD_WORKFLOW_PHRASES = (
    "from scratch",
    "run from scratch",
    "do not reuse local",
    "do not reuse local artifacts",
    "do not reuse old",
    "do not seed",
    "do not seed copied",
    "do not seed reusable",
    "do not skip domain",
    "must include define_domain",
    "must not skip define_domain",
    "must not skip discretize_domain",
    "do not skip define_domain",
    "do not skip discretize_domain",
    "workflow_steps must include acquire_attributes",
    "workflow_steps must not skip define_domain",
    "cloud/data-service acquisition",
    "using cloud/data-service",
    "using cloud acquisition",
)


def user_requires_fresh_cloud_workflow(user_request: str, cfg: dict | None = None) -> bool:
    """True when the user wants a full cloud acquisition + delineation run, not local reuse."""
    text = (user_request or "").lower()
    if any(phrase in text for phrase in _FRESH_CLOUD_WORKFLOW_PHRASES):
        return True
    cfg = cfg or {}
    extra = cfg.get("extra_config") if isinstance(cfg.get("extra_config"), dict) else {}
    data_access = ""
    for key in ("data_access", "DATA_ACCESS"):
        data_access = _s(cfg.get(key) or extra.get(key)).upper()
        if data_access:
            break
    if data_access == "CLOUD" and any(
        phrase in text
        for phrase in (
            "from scratch",
            "do not reuse",
            "acquire_attributes",
            "define_domain",
            "workflow_steps",
        )
    ):
        return True
    if "workflow_steps" in text and "define_domain" in text and "acquire_attributes" in text:
        if any(phrase in text for phrase in ("from scratch", "do not reuse", "data_access: cloud")):
            return True
    return False


def user_forbids_download_step(user_request: str, step: str) -> bool:
    text = (user_request or "").lower()
    for phrase in _DOWNLOAD_STEP_FORBID_PHRASES.get(step, ()):
        if phrase in text:
            return True
    if step in ("acquire_attributes", "acquire_forcings") and (
        "do not add data-download steps" in text
        or "do not add data download steps" in text
    ):
        return True
    return False


def ensure_skip_domain_rerun_when_local_artifacts_exist(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """
    Re-running define_domain/discretize_domain overwrites catchment shapefiles and
    breaks alignment with pre-existing SUMMA forcing HRU IDs.
    """
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    domain_name = _s(cfg.get("domain_name"))
    experiment_id = _s(cfg.get("experiment_id")) or "run_1"
    steps = list(out.get("steps") or [])

    if user_requires_fresh_cloud_workflow(user_request, cfg):
        return out

    if not domain_has_complete_local_workflow(data_dir, domain_name, experiment_id):
        return out

    removed = [step for step in ("define_domain", "discretize_domain") if step in steps]
    if not removed:
        return out

    out["steps"] = [step for step in steps if step not in removed]
    _append_plan_note(
        out,
        "Skipped define_domain/discretize_domain; reusing existing local catchment and forcing "
        "(re-delineation would break HRU ID alignment).",
    )
    return out


def strip_user_forbidden_download_steps(plan: dict, user_request: str = "") -> dict:
    """Remove download steps the user explicitly excluded from the plan."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    steps = list(out.get("steps") or [])
    removed = [step for step in steps if user_forbids_download_step(user_request, step)]
    if not removed:
        return out
    out["steps"] = [step for step in steps if step not in removed]
    _append_plan_note(
        out,
        f"Removed download steps per user request: {', '.join(removed)}.",
    )
    return out


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
        "existing local data",
        "already copied",
        "already present",
        "already on disk",
        "data already in symfluence_data",
        "do not download new attributes",
        "do not download new forcing",
        "do not download new observations",
        "do not add data-download steps",
        "do not add data download steps",
    )
    if any(p in text for p in local_only_phrases):
        return True

    extra = cfg.get("extra_config") if isinstance(cfg.get("extra_config"), dict) else {}
    data_access_local = any(
        _s(cfg.get(key)).upper() == "LOCAL" or _s(extra.get(key)).upper() == "LOCAL"
        for key in ("DATA_ACCESS", "data_access")
    )
    if data_access_local:
        if domain_name and data_dir and domain_has_local_attributes(data_dir, domain_name):
            return True
        if any(p in text for p in local_only_phrases):
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
    "do not include acquire_attributes",
    "do not run acquire_attributes",
    "don't include acquire_attributes",
    "don't run acquire_attributes",
    "skip acquire_attributes",
    "without acquire_attributes",
    "omit acquire_attributes",
    "reuse existing attributes",
    "attributes already",
    "attributes present",
    "do not download attributes",
    "do not download new attributes",
)


def ensure_acquire_attributes_before_define_domain(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """define_domain (delineate) needs DEM; insert acquire_attributes when omitted."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    steps = list(out.get("steps") or [])
    if "define_domain" not in steps or "acquire_attributes" in steps:
        return out

    if user_forbids_download_step(user_request, "acquire_attributes"):
        return out

    text = (user_request or "").lower()
    if any(p in text for p in _SKIP_ACQUIRE_ATTRIBUTES_PHRASES):
        return out

    cfg = dict(out.get("config") or {})
    domain_name = _s(cfg.get("domain_name"))
    if domain_name and data_dir and domain_has_local_dem(data_dir, domain_name):
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

    if user_forbids_download_step(user_request, "acquire_attributes"):
        return out

    out = ensure_acquire_attributes_before_define_domain(out, user_request, data_dir=data_dir)
    steps = list(out.get("steps") or [])

    needs_dem = bool({"define_domain", "discretize_domain"} & set(steps))
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


def extract_ordered_workflow_steps(user_request: str) -> list[str]:
    """Parse workflow_steps listed in the user prompt, preserving order."""
    if not user_request:
        return []
    allowed = set(WORKFLOW_STEP_NAMES)
    block = re.search(
        r"workflow_steps\s*:\s*\n(.*?)(?=\n\S|\Z)",
        user_request,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not block:
        return []
    ordered: list[str] = []
    for line in block.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.search(r"^-\s*[\"']?([A-Za-z_]+)[\"']?", line)
        if not match:
            match = re.search(r"[\"']([A-Za-z_]+)[\"']", line)
        if not match:
            continue
        step = match.group(1)
        if step in allowed:
            ordered.append(step)
    return ordered


def restore_workflow_steps_from_user_request(plan: dict, user_request: str = "") -> dict:
    """When the user supplies an explicit workflow_steps block, honor that order."""
    if not isinstance(plan, dict):
        return plan
    ordered = extract_ordered_workflow_steps(user_request)
    if len(ordered) < 3:
        return plan
    cfg = dict(plan.get("config") or {})
    if not (
        user_requires_fresh_cloud_workflow(user_request, cfg)
        or {"define_domain", "discretize_domain"} <= set(ordered)
    ):
        return plan
    out = dict(plan)
    out["steps"] = ordered
    _append_plan_note(out, "Workflow steps restored from user workflow_steps list.")
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

    out = strip_user_forbidden_download_steps(out, user_request)
    out = ensure_plan_station_id(out, user_request)
    out = restore_workflow_steps_from_user_request(out, user_request)
    out = ensure_skip_domain_rerun_when_local_artifacts_exist(out, user_request, data_dir=data_dir)
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
