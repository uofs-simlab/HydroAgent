from __future__ import annotations
# Layout note: minor UI spacing tweaks.

import csv
import re
from datetime import datetime
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


def plan_user_required_steps(plan: dict) -> set[str]:
    """Workflow steps the user explicitly asked to keep (chat add/include or step-order edits)."""
    if not isinstance(plan, dict):
        return set()
    allowed = set(WORKFLOW_STEP_NAMES)
    raw = plan.get("user_required_steps") or []
    if not isinstance(raw, list):
        return set()
    return {step for step in raw if step in allowed}


def with_user_required_steps(
    plan: dict,
    steps: set[str] | list[str],
    *,
    remove: set[str] | list[str] | None = None,
) -> dict:
    out = dict(plan)
    current = plan_user_required_steps(out)
    current.update(steps)
    if remove:
        current -= set(remove)
    if current:
        out["user_required_steps"] = sorted(current)
    else:
        out.pop("user_required_steps", None)
    return out


def user_message_requests_workflow_step(user_message: str, step: str) -> bool:
    """True when a chat/prompt message explicitly adds or keeps a workflow step."""
    text = (user_message or "").lower()
    if not text or step not in WORKFLOW_STEP_NAMES:
        return False
    step_pat = re.escape(step)
    if re.search(rf"\b(remove|removed|drop|dropped|skip|skipped|omit|omitted|exclude|excluded|without|delete|deleted)\b.*\b{step_pat}\b", text):
        return False
    if re.search(rf"\b{step_pat}\b.*\b(remove|removed|drop|dropped|skip|skipped|omit|omitted|exclude|excluded|without|delete|deleted)\b", text):
        return False
    if re.search(rf"\b(add|added|include|included|insert|inserted)\s+[\"']?{step_pat}\b", text):
        return True
    if re.search(rf"\b{step_pat}\b.*\bbefore\b", text):
        return True
    return False


def workflow_step_user_required(plan: dict, step: str, user_request: str = "") -> bool:
    if step in plan_user_required_steps(plan):
        return True
    return user_message_requests_workflow_step(user_request, step)


_LOCAL_DATA_REUSE_PHRASES = (
    "data_access local",
    "data access local",
    "existing local data",
    "local-data recovery",
    "local data recovery",
    "local recovery",
    "reuse existing local",
    "reuse existing",
    "reusing existing",
    "existing local domain",
    "existing local artifacts",
    "local artifacts",
    "already copied",
    "already present",
    "already on disk",
    "when available",
    "when possible",
    "regenerate only",
    "case study",
    "do not redefine",
    "do not rediscretize",
    "not a new domain",
    "local data first",
    "use local data first",
    "local-first",
    "before downloading",
    "do not download era5",
    "only run acquire_forcings if",
    "only run `acquire_forcings` if",
)


def request_indicates_local_data_reuse(
    user_request: str = "",
    cfg: dict | None = None,
    *,
    data_dir: str | Path | None = None,
) -> bool:
    """True when the user intends to reuse on-disk domain artifacts instead of cloud fetch."""
    text = (user_request or "").lower()
    if any(p in text for p in _LOCAL_DATA_REUSE_PHRASES):
        return True

    cfg = cfg or {}
    extra_raw = cfg.get("extra_config")
    extra = extra_raw if isinstance(extra_raw, dict) else {}
    if any(_s(cfg.get(key)).upper() == "LOCAL" for key in ("DATA_ACCESS", "data_access")):
        return True
    if any(_s(extra.get(key)).upper() == "LOCAL" for key in ("DATA_ACCESS", "data_access")):
        return True

    domain_name = _s(cfg.get("domain_name"))
    if domain_name and data_dir and domain_has_local_dem(data_dir, domain_name):
        if any(p in text for p in ("reuse", "existing", "recovery", "when available")):
            return True
    return False


def default_symfluence_data_dir() -> Path:
    """Match the Streamlit UI default SYMFLUENCE_data path."""
    settings_path = Path.home() / ".symfluence_assistant" / "config.yaml"
    if settings_path.is_file():
        try:
            import yaml

            data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
            custom = _s(data.get("symfluence_data_dir"))
            if custom:
                return Path(custom).expanduser()
        except Exception:
            pass
    return Path.home() / "installs" / "SYMFLUENCE_data"


def should_reuse_existing_symfluence_domain(
    user_request: str = "",
    cfg: dict | None = None,
    *,
    data_dir: str | Path | None = None,
) -> bool:
    """Keep DOMAIN_NAME on the base basin folder when local artifacts already exist."""
    if not request_indicates_local_data_reuse(user_request, cfg, data_dir=data_dir):
        return False
    cfg = cfg or {}
    domain_name = _s(cfg.get("domain_name"))
    if not domain_name or not data_dir:
        return False
    return domain_root(data_dir, domain_name).is_dir()


def pour_point_workflow_skips_bbox(
    cfg: dict | None,
    steps: list[str] | None,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> bool:
    """Pour-point / local-recovery workflows do not need bounding_box_coords."""
    cfg = cfg or {}
    steps = steps or []
    if request_indicates_local_data_reuse(user_request, cfg, data_dir=data_dir):
        return True
    domain_def = _s(cfg.get("domain_def")).lower()
    pour_point = _s(cfg.get("pour_point_coords"))
    if domain_def in ("delineate", "lumped", "point", "semidistributed") and pour_point:
        if "acquire_attributes" not in steps:
            return True
    return False


def try_restore_local_recovery_plan(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """Restore explicit local-recovery steps when core config is already complete."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    if not request_indicates_local_data_reuse(user_request, cfg, data_dir=data_dir):
        return out

    ordered = extract_ordered_steps_from_request(user_request)
    if len(ordered) < 3:
        return out

    explicit = extract_explicit_domain_name_from_request(user_request)
    if explicit:
        cfg["domain_name"] = explicit
        cfg = mark_domain_name_confirmed(cfg)
        out["config"] = cfg

    from server.core.ui_config_fields import plan_config_field_present

    core_fields = (
        "domain_name",
        "hydrological_model",
        "pour_point_coords",
        "experiment_time_start",
        "experiment_time_end",
    )
    missing_core = [
        field
        for field in core_fields
        if (
            field == "domain_name"
            and domain_name_needs_user_input(cfg, user_request, data_dir=data_dir)
        )
        or (field != "domain_name" and not plan_config_field_present(cfg, field))
    ]
    if missing_core:
        return out

    out["steps"] = ordered
    required = extract_user_required_steps_from_step_order(user_request)
    if required:
        out = with_user_required_steps(out, required)
    out["needs_user_input"] = [
        key for key in (out.get("needs_user_input") or []) if key != "bounding_box_coords"
    ]
    notes = _s(out.get("notes"))
    if "bounding_box_coords" in notes or set(out.get("steps") or []) <= {"validate_config", "dry_run"}:
        out["notes"] = (
            "Local-data recovery workflow. "
            "Steps restored from user step-order list; bounding box not required."
        )
    return out


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


_GENERIC_DOMAIN_TOKENS = frozenset(
    {
        "bow",
        "river",
        "basin",
        "domain",
        "summa",
        "water",
        "catchment",
        "watershed",
        "study",
        "area",
        "test",
        "demo",
        "experiment",
        "exp",
    }
)


def normalize_domain_name_token(name: str) -> str:
    from server.core.ui_config_fields import normalize_domain_name_value

    return normalize_domain_name_value(_s(name))


def is_weak_domain_name(name: str) -> bool:
    """True for guessed or filesystem-unsafe basin labels (e.g. Bow, 2025)."""
    token = normalize_domain_name_token(name)
    if not token:
        return True
    if re.fullmatch(r"\d{4}", token):
        return True
    if token.lower() in _GENERIC_DOMAIN_TOKENS:
        return True
    if "_" not in token and "-" not in token and len(token) < 10:
        return True
    return False


def domain_name_confirmed_in_plan(cfg: dict) -> bool:
    extra_raw = cfg.get("extra_config")
    extra = extra_raw if isinstance(extra_raw, dict) else {}
    return bool(extra.get("domain_name_confirmed") or extra.get("DOMAIN_NAME_CONFIRMED"))


def mark_domain_name_confirmed(cfg: dict) -> dict:
    out = dict(cfg)
    extra = dict(out.get("extra_config") or {}) if isinstance(out.get("extra_config"), dict) else {}
    extra["domain_name_confirmed"] = True
    out["extra_config"] = extra
    return out


def apply_user_provided_domain_name(cfg: dict, domain_name: str) -> dict:
    """Record an explicit user-supplied domain name (Input tab, fix panel, or editor)."""
    out = dict(cfg or {})
    name = normalize_domain_name_token(_s(domain_name))
    if not name:
        out.pop("domain_name", None)
        return out
    out["domain_name"] = name
    # UI/editor entry counts as explicit confirmation even for short tokens like "Bow".
    out = mark_domain_name_confirmed(out)
    return out


def normalize_committed_plan_config(cfg: dict | None) -> dict:
    """Apply commit-time policies when plan config is saved from the UI or JSON editor."""
    out = dict(cfg or {})
    domain = _s(out.get("domain_name"))
    if domain:
        out = apply_user_provided_domain_name(out, domain)
    return out


def extract_explicit_domain_name_from_request(user_request: str) -> str:
    """Return domain_name only when the user explicitly names it in the prompt."""
    text = _s(user_request)
    if not text:
        return ""

    patterns = (
        r"\buse\s+([A-Za-z0-9_\-]+)\s+as\s+(?:the\s+)?domain(?:\s+name|_name)\b",
        r"\b(?:set|change|update)\s+(?:the\s+)?domain(?:\s+name|_name)\s+(?:to\s+)?([A-Za-z0-9_\-]+)\b",
        r"\bdomain_name\s+to\s+([A-Za-z0-9_\-]+)",
        r"\b(?:set|change|update)\s+domain_name\s+to\s+([A-Za-z0-9_\-]+)",
        r"\bdomain_name\s*[=:]\s*[\"']?([A-Za-z0-9_\-]+)",
        r"\bdomain_name\s+(?!to\b)([A-Za-z0-9_\-]+)",
        r"\bdomain\s+name\s+to\s+([A-Za-z0-9_\-]+)",
        r"\bdomain\s+name\s*[=:]\s*[\"']?([A-Za-z0-9_\-]+)",
        r"\bdomain\s+name\s+(?!to\b)([A-Za-z0-9_\-]+)",
        r"\bDOMAIN_NAME\s*[=:]\s*[\"']?([A-Za-z0-9_\-]+)",
        r"\buse\s+domain_name\s+([A-Za-z0-9_\-]+)",
        r"\breuse\s+(?:the\s+)?(?:existing\s+)?domain[_\s]+([A-Za-z0-9_\-]+)",
        r"\bSYMFLUENCE_data/domain_([A-Za-z0-9_\-]+)",
        r"\bdomain_([A-Za-z0-9_\-]+)/",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return normalize_domain_name_token(match.group(1))
    return ""


def domain_name_needs_user_input(
    cfg: dict | None,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> bool:
    """True when domain_name is missing, weak, or not explicitly confirmed."""
    from server.core.ui_config_fields import plan_config_field_present

    cfg = cfg or {}
    if not plan_config_field_present(cfg, "domain_name"):
        return True

    name = normalize_domain_name_token(_s(cfg.get("domain_name")))
    if not name:
        return True

    if domain_name_confirmed_in_plan(cfg):
        return False

    explicit = extract_explicit_domain_name_from_request(user_request)
    if explicit and explicit.lower() == name.lower():
        return False

    if is_weak_domain_name(name):
        return True

    if data_dir and domain_root(data_dir, name).is_dir():
        return False

    return True


def list_existing_domain_names(data_dir: str | Path | None, *, limit: int = 8) -> list[str]:
    """Return sorted domain folder names under SYMFLUENCE_data/domain_*."""
    if not data_dir:
        return []
    root = Path(data_dir)
    if not root.is_dir():
        return []
    names = sorted(
        p.name[len("domain_") :]
        for p in root.glob("domain_*")
        if p.is_dir() and p.name.startswith("domain_")
    )
    return names[:limit] if limit > 0 else names


def ensure_domain_name_user_input(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """Gate execution until domain_name is explicit, confirmed, or matches on-disk data."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    explicit = extract_explicit_domain_name_from_request(user_request)

    if explicit:
        cfg["domain_name"] = explicit
        cfg = mark_domain_name_confirmed(cfg)
    elif _s(cfg.get("domain_name")) and domain_name_needs_user_input(cfg, user_request, data_dir=data_dir):
        weak = is_weak_domain_name(_s(cfg.get("domain_name")))
        cfg.pop("domain_name", None)
        if weak:
            _append_plan_note(
                out,
                "Removed weak inferred domain_name; provide a filesystem-safe basin name "
                "(e.g. Bow_at_Banff_semi_distributed).",
            )

    out["config"] = cfg
    if not domain_name_needs_user_input(cfg, user_request, data_dir=data_dir):
        needs = [x for x in (out.get("needs_user_input") or []) if x != "domain_name"]
        out["needs_user_input"] = needs
        return out

    needs = list(out.get("needs_user_input") or [])
    if "domain_name" not in needs:
        needs.append("domain_name")
    out["needs_user_input"] = needs
    out["steps"] = ["validate_config", "dry_run"]
    _append_plan_note(
        out,
        "Domain name is required. Set domain_name in the prompt, pick an existing "
        "SYMFLUENCE_data/domain_<name>/ folder, or confirm it in the Input tab.",
    )
    existing = list_existing_domain_names(data_dir)
    if existing:
        more = ""
        root = Path(data_dir) if data_dir else None
        if root and root.is_dir():
            total = sum(1 for p in root.glob("domain_*") if p.is_dir())
            if total > len(existing):
                more = f" ({total} on disk)"
        _append_plan_note(
            out,
            "Existing domains: " + ", ".join(existing) + more,
        )
    return out


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
                    count = len(gdf[col].unique())
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
    min_hrus: int = 1,
) -> bool:
    if not data_dir or not _s(domain_name):
        return False
    return domain_catchment_hru_count(data_dir, domain_name, experiment_id) >= min_hrus


def domain_has_local_river_basins(
    data_dir: str | Path | None,
    domain_name: str,
) -> bool:
    """True when define_domain produced at least one river_basins shapefile."""
    from server.core.local_domain import domain_river_basins_shapefiles

    return bool(domain_river_basins_shapefiles(data_dir, domain_name))


STEPS_REQUIRING_BASIN_POUR_POINT = frozenset(
    {
        "discretize_domain",
        "model_agnostic_preprocessing",
        "model_specific_preprocessing",
        "run_model",
        "calibrate_model",
        "postprocess_results",
    }
)


def basin_pour_point_preflight_error(
    step: str,
    pour_coords: str,
    data_dir: str | Path | None,
    domain_name: str,
) -> str | None:
    """Block post-define_domain steps when pour point lies outside delineated basin."""
    from server.core.local_domain import pour_point_inside_delineated_basin

    if step not in STEPS_REQUIRING_BASIN_POUR_POINT:
        return None
    if not _s(domain_name) or not _s(pour_coords):
        return None
    if not domain_has_local_river_basins(data_dir, domain_name):
        return None
    ok, detail = pour_point_inside_delineated_basin(pour_coords, data_dir, domain_name)
    if ok:
        return None
    return (
        f"{step} blocked: the pour point is outside the delineated basin polygon. "
        "This is a basin delineation issue, not a bounding-box issue. "
        f"{detail}"
    )


def domain_has_local_summa_forcing(data_dir: str | Path | None, domain_name: str) -> bool:
    if not data_dir or not _s(domain_name):
        return False
    forcing_dir = domain_root(data_dir, domain_name) / "data" / "forcing" / "SUMMA_input"
    return any(forcing_dir.glob("*.nc"))


def domain_has_remapped_forcing(data_dir: str | Path | None, domain_name: str) -> bool:
    """True when MAP/MSP forcing NetCDF exists (basin-averaged, SUMMA input, or model-ready)."""
    if not data_dir or not _s(domain_name):
        return False
    root = domain_root(data_dir, domain_name)
    for rel in (
        "data/forcing/basin_averaged_data",
        "data/forcing/SUMMA_input",
        "data/model_ready/forcings",
    ):
        folder = root / rel
        if folder.is_dir() and any(folder.glob("*.nc")):
            return True
    return False


def domain_forcing_intersection_path(
    data_dir: str | Path | None,
    domain_name: str,
    *,
    forcing_dataset: str = "ERA5",
) -> Path:
    """Expected or existing ERA5/forcing–catchment intersection (.shp or .csv)."""
    name = _s(domain_name)
    dataset = _s(forcing_dataset) or "ERA5"
    folder = (
        domain_root(data_dir or "", name)
        / "shapefiles"
        / "catchment_intersection"
        / "with_forcing"
    )
    stem = f"{name}_{dataset}_intersected_shapefile"
    for suffix in (".shp", ".csv", ".gpkg"):
        path = folder / f"{stem}{suffix}"
        if path.is_file():
            return path
    if folder.is_dir():
        matches = sorted(
            p
            for p in folder.iterdir()
            if p.is_file()
            and "intersected" in p.name.lower()
            and p.suffix.lower() in {".shp", ".csv", ".gpkg"}
        )
        if matches:
            return matches[0]
    return folder / f"{stem}.shp"


def domain_has_forcing_intersection(
    data_dir: str | Path | None,
    domain_name: str,
    *,
    forcing_dataset: str = "ERA5",
) -> bool:
    """True when model_agnostic_preprocessing intersect output exists."""
    if not data_dir or not _s(domain_name):
        return False
    path = domain_forcing_intersection_path(
        data_dir, domain_name, forcing_dataset=forcing_dataset
    )
    return path.is_file()


def domain_forcing_raw_data_dir(data_dir: str | Path, domain_name: str) -> Path:
    root = domain_root(data_dir, domain_name)
    for rel in ("data/forcing/raw_data", "forcing/raw_data"):
        path = root / rel
        if path.is_dir():
            return path
    return root / "data" / "forcing" / "raw_data"


def domain_has_local_era5_raw_forcing(data_dir: str | Path | None, domain_name: str) -> bool:
    """True when ERA5/raw forcing files already exist under the domain folder."""
    if not data_dir or not _s(domain_name):
        return False
    raw_dir = domain_forcing_raw_data_dir(Path(data_dir), domain_name)
    if not raw_dir.is_dir():
        return False
    for pattern in ("*.nc", "*.grb", "*.grib", "*.grib2", "ERA5*", "era5*"):
        if any(raw_dir.glob(pattern)):
            return True
    return any(
        path.is_file() and not path.name.startswith(".")
        for path in raw_dir.iterdir()
    )


def ensure_local_data_access_in_plan(plan: dict) -> dict:
    """Set plan config to LOCAL data access (reuse on-disk data, no MAF/gistool).

    SYMFLUENCE treats ``LOCAL`` like ``CLOUD`` for ``acquire_*`` steps, skipping
    files that already exist and downloading only missing artifacts.
    """
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    extra = dict(cfg.get("extra_config") or {}) if isinstance(cfg.get("extra_config"), dict) else {}
    cfg["data_access"] = "local"
    extra["DATA_ACCESS"] = "LOCAL"
    cfg["extra_config"] = extra
    out["config"] = cfg
    return out


def ensure_skip_acquire_forcings_when_local_forcing(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """Keep acquire_forcings in the plan; set local data access when forcing already exists."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    domain_name = _s(cfg.get("domain_name"))
    if user_requires_fresh_cloud_workflow(user_request, cfg):
        return out
    if not domain_name or not data_dir:
        return out
    # Keep acquire_forcings in the plan; Execute plan reuses local forcing at runtime.
    if domain_has_local_summa_forcing(data_dir, domain_name) or domain_has_local_era5_raw_forcing(
        data_dir, domain_name
    ):
        out = ensure_local_data_access_in_plan(out)
    return out


def ensure_skip_model_agnostic_when_local_preprocessing(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """Skip model_agnostic_preprocessing when SUMMA forcing input already exists."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    if user_requires_fresh_cloud_workflow(user_request, cfg):
        return out
    # Keep model_agnostic_preprocessing in the plan; Execute plan reuses local forcing at runtime.
    return out


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


def _parse_experiment_datetime(value: str | None) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value or "").strip(), fmt)
        except ValueError:
            continue
    return None


def experiment_window_from_cfg(cfg: dict | None) -> tuple[datetime, datetime] | None:
    cfg = cfg or {}
    start = _parse_experiment_datetime(
        _s(cfg.get("EXPERIMENT_TIME_START") or cfg.get("experiment_time_start"))
    )
    end = _parse_experiment_datetime(
        _s(cfg.get("EXPERIMENT_TIME_END") or cfg.get("experiment_time_end"))
    )
    if start is None or end is None:
        return None
    return start, end


def _streamflow_csv_datetime_bounds(path: Path) -> tuple[datetime, datetime] | None:
    if not path.is_file():
        return None
    first: datetime | None = None
    last: datetime | None = None
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw = _s(row.get("datetime") or row.get("DATE") or row.get("date"))
            if not raw:
                continue
            dt = _parse_experiment_datetime(raw)
            if dt is None:
                continue
            if first is None:
                first = dt
            last = dt
    if first is None or last is None:
        return None
    return first, last


def local_streamflow_overlaps_experiment(
    data_dir: str | Path | None,
    domain_name: str,
    experiment_start: datetime,
    experiment_end: datetime,
) -> bool:
    """True when a local preprocessed streamflow CSV overlaps the experiment window."""
    if not data_dir or not _s(domain_name):
        return False
    path = domain_streamflow_processed_path(data_dir, domain_name)
    bounds = _streamflow_csv_datetime_bounds(path)
    if bounds is None:
        return False
    obs_start, obs_end = bounds
    return obs_start <= experiment_end and experiment_start <= obs_end


def domain_has_usable_local_streamflow(
    data_dir: str | Path | None,
    domain_name: str,
    cfg: dict | None = None,
) -> bool:
    """
    True when local preprocessed streamflow exists and overlaps the experiment window.

    If experiment dates are missing from cfg, returns False so downloads are not skipped.
    """
    if not domain_has_local_streamflow(data_dir, domain_name):
        return False
    window = experiment_window_from_cfg(cfg or {})
    if window is None:
        return False
    return local_streamflow_overlaps_experiment(data_dir, domain_name, *window)


def is_valid_station_id(value: str) -> bool:
    """Reject placeholder LLM values like 'ID' and accept WSC-style gauge IDs."""
    token = _s(value)
    if not token:
        return False
    if token.lower() in {"id", "station", "station_id", "wsc", "gauge", "stn"}:
        return False
    return bool(re.fullmatch(r"\d{2}[A-Z]{2}\d{3}", token, flags=re.IGNORECASE))


def extract_station_id_from_request(user_request: str) -> str:
    text = user_request or ""
    patterns = (
        r"station_id\s*[:=]\s*['\"`]?(\d{2}[A-Z]{2}\d{3})['\"`]?",
        r"STATION_ID\s*[:=]\s*['\"`]?(\d{2}[A-Z]{2}\d{3})['\"`]?",
        r"(?:WSC\s+)?station\s+ID\s*[`'\"]?\s*(\d{2}[A-Z]{2}\d{3})[`'\"]?",
        r"\bstation\s+['\"`]?(\d{2}[A-Z]{2}\d{3})['\"`]?",
        r"\bWSC\s+['\"`]?(\d{2}[A-Z]{2}\d{3})['\"`]?",
        r"[`'\"](\d{2}[A-Z]{2}\d{3})[`'\"]",
        r"\b(\d{2}BB\d{3})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = _s(match.group(1))
            if is_valid_station_id(candidate):
                return candidate
    return ""


def resolve_station_id_from_plan(
    cfg: dict | None,
    user_request: str = "",
    *,
    fallback: str = "",
    pour_point_coords: str = "",
) -> str:
    cfg = cfg or {}
    for candidate in (
        _s(cfg.get("station_id")),
        _s(cfg.get("STATION_ID")),
        _s(fallback),
        extract_station_id_from_request(user_request),
    ):
        if is_valid_station_id(candidate):
            return candidate

    pour = pour_point_coords or _s(cfg.get("pour_point_coords")) or _s(cfg.get("POUR_POINT_COORDS"))
    provider = _s(cfg.get("streamflow_data_provider")) or _s(cfg.get("STREAMFLOW_DATA_PROVIDER")) or "WSC"
    if pour and provider.upper() in {"WSC", "USGS"}:
        from server.core.station_resolver import resolve_station_near_pour_point

        window = experiment_window_from_cfg(cfg)
        hit = resolve_station_near_pour_point(
            provider,
            pour,
            experiment_start=window[0].strftime("%Y-%m-%d %H:%M") if window else None,
            experiment_end=window[1].strftime("%Y-%m-%d %H:%M") if window else None,
        )
        if hit:
            return hit[0]
    return ""


def resolve_station_id_note_from_plan(
    cfg: dict | None,
    user_request: str = "",
    *,
    fallback: str = "",
    pour_point_coords: str = "",
) -> str:
    """Human-readable note when station_id was auto-selected."""
    station_id = resolve_station_id_from_plan(
        cfg,
        user_request,
        fallback=fallback,
        pour_point_coords=pour_point_coords,
    )
    if not station_id:
        return ""
    if _s((cfg or {}).get("station_id")) or _s((cfg or {}).get("STATION_ID")) or _s(fallback):
        return ""
    if extract_station_id_from_request(user_request):
        return ""
    pour = pour_point_coords or _s((cfg or {}).get("pour_point_coords")) or _s((cfg or {}).get("POUR_POINT_COORDS"))
    provider = _s((cfg or {}).get("streamflow_data_provider")) or _s((cfg or {}).get("STREAMFLOW_DATA_PROVIDER")) or "WSC"
    if not pour:
        return ""
    from server.core.station_resolver import resolve_station_near_pour_point

    window = experiment_window_from_cfg(cfg)
    hit = resolve_station_near_pour_point(
        provider,
        pour,
        experiment_start=window[0].strftime("%Y-%m-%d %H:%M") if window else None,
        experiment_end=window[1].strftime("%Y-%m-%d %H:%M") if window else None,
    )
    return hit[1] if hit and hit[0] == station_id else ""


def ensure_plan_station_id(plan: dict, user_request: str = "") -> dict:
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    previous = _s(cfg.get("station_id"))
    station_id = resolve_station_id_from_plan(cfg, user_request)
    if not station_id:
        out["config"] = cfg
        return out
    auto_note = resolve_station_id_note_from_plan(cfg, user_request) if not previous else ""
    if previous != station_id:
        cfg["station_id"] = station_id
        out["config"] = cfg
        if auto_note:
            _append_plan_note(out, auto_note)
        elif extract_station_id_from_request(user_request):
            _append_plan_note(out, f"Set station_id to {station_id} from user request.")
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
    if is_calibration_workflow_plan(out):
        # Keep process_observed_data in the calibration plan; Execute plan reuses the CSV at runtime.
        return out
    cfg = dict(out.get("config") or {})
    domain_name = _s(symfluence_domain) or _s(cfg.get("domain_name"))
    steps = list(out.get("steps") or [])
    if user_requires_fresh_cloud_workflow(user_request, cfg):
        return out
    if "process_observed_data" not in steps:
        return out
    if workflow_step_user_required(out, "process_observed_data", user_request):
        return out
    if not domain_name or not data_dir:
        return out
    if not domain_has_usable_local_streamflow(data_dir, domain_name, cfg):
        return out
    out["steps"] = [step for step in steps if step != "process_observed_data"]
    _append_plan_note(
        out,
        "Skipped process_observed_data; reusing local preprocessed streamflow that overlaps the experiment window.",
    )
    return out


def domain_has_local_attributes(data_dir: str | Path | None, domain_name: str) -> bool:
    """True when DEM plus at least one land/soil raster already exists on disk."""
    if not data_dir or not _s(domain_name):
        return False
    if not domain_has_local_dem(data_dir, domain_name):
        return False
    root = domain_attributes_root(data_dir, domain_name)
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
        "do not download era5",
        "only run acquire_forcings if",
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
    extra_raw = cfg.get("extra_config")
    extra = extra_raw if isinstance(extra_raw, dict) else {}
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
            "exact step order",
        )
    ):
        return True
    if any(marker in text for marker in ("workflow_steps", "exact step order")) and "define_domain" in text and "acquire_attributes" in text:
        if any(phrase in text for phrase in ("from scratch", "do not reuse", "data_access: cloud", "cloud data access")):
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
    """Keep define_domain/discretize_domain in the plan; Execute plan reuses local catchments."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    if user_requires_fresh_cloud_workflow(user_request, cfg):
        return out
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
    """True when existing on-disk domain data should be used (no online fetch)."""
    cfg = cfg or {}
    steps = steps or []

    if request_indicates_local_data_reuse(user_request, cfg, data_dir=data_dir):
        domain_name = _s(cfg.get("domain_name"))
        if domain_name and data_dir and domain_has_local_dem(data_dir, domain_name):
            return True
        text = (user_request or "").lower()
        if any(p in text for p in _LOCAL_DATA_REUSE_PHRASES):
            return True

    if {"acquire_attributes", "acquire_forcings"} & set(steps):
        return False

    domain_name = _s(cfg.get("domain_name"))
    if domain_name and data_dir and not domain_has_local_dem(data_dir, domain_name):
        if {"define_domain", "discretize_domain", "model_agnostic_preprocessing"} & set(steps):
            return False

    text = (user_request or "").lower()
    if any(p in text for p in _LOCAL_DATA_REUSE_PHRASES):
        return True

    extra_raw = cfg.get("extra_config")
    extra = extra_raw if isinstance(extra_raw, dict) else {}
    data_access_local = any(
        _s(cfg.get(key)).upper() == "LOCAL" or _s(extra.get(key)).upper() == "LOCAL"
        for key in ("DATA_ACCESS", "data_access")
    )
    if data_access_local:
        if domain_name and data_dir and domain_has_local_attributes(data_dir, domain_name):
            return True
        if any(p in text for p in _LOCAL_DATA_REUSE_PHRASES):
            return True

    return False


def plan_requires_bounding_box(
    cfg: dict | None,
    steps: list[str] | None = None,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> bool:
    """Bounding box is only needed for cloud forcing/attribute acquisition."""
    steps = steps or []
    if pour_point_workflow_skips_bbox(cfg, steps, user_request, data_dir=data_dir):
        return False
    if plan_uses_local_data(cfg, steps, user_request, data_dir=data_dir):
        return False
    return bool({"acquire_attributes", "acquire_forcings"} & set(steps))


_PSEUDO_WORKFLOW_STEP_ALIASES: dict[str, str] = {
    "check_local_observations_or_process_observed_data": "process_observed_data",
    "check_local_forcings_or_acquire_forcings": "acquire_forcings",
    "check_local_preprocessing_or_model_agnostic_preprocessing": "model_agnostic_preprocessing",
}


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


def sort_plan_steps_by_workflow_order(steps: list[str]) -> list[str]:
    """Canonical SYMFLUENCE step order (deduped)."""
    seen: set[str] = set()
    for step in steps:
        if step in WORKFLOW_STEP_NAMES and step not in seen:
            seen.add(step)
    return [step for step in WORKFLOW_STEP_NAMES if step in seen]


def apply_chat_step_order_edits(plan: dict, user_message: str) -> dict:
    """Honor chat requests like 'model_agnostic_preprocessing before model_specific_preprocessing'."""
    if not isinstance(plan, dict) or not user_message:
        return plan
    text = user_message.lower()
    steps = list(plan.get("steps") or [])
    changed = False
    required: set[str] = set()

    for before_step in WORKFLOW_STEP_NAMES:
        if before_step == "dry_run":
            continue
        before_pat = re.escape(before_step)
        for after_step in WORKFLOW_STEP_NAMES:
            if after_step in (before_step, "dry_run"):
                continue
            after_pat = re.escape(after_step)
            before_label = rf'["\']?{before_pat}["\']?'
            after_label = rf'["\']?{after_pat}["\']?'
            patterns = (
                rf"{before_label}[^.\n]{{0,80}}\b(?:should\s+)?come\s+before\b[^.\n]{{0,40}}{after_label}",
                rf"{before_label}[^.\n]{{0,80}}\b(?:should\s+be\s+)?before\b[^.\n]{{0,40}}{after_label}",
                rf"\bput\s+{before_label}[^.\n]{{0,40}}\bbefore\b[^.\n]{{0,40}}{after_label}",
                rf"\badd\s+{before_label}[^.\n]{{0,40}}\bbefore\b[^.\n]{{0,40}}{after_label}",
                rf"\binclude\s+{before_label}[^.\n]{{0,40}}\bbefore\b[^.\n]{{0,40}}{after_label}",
            )
            if not any(re.search(pattern, text) for pattern in patterns):
                continue
            if before_step not in steps:
                steps.append(before_step)
            if after_step not in steps:
                steps.append(after_step)
            steps = [step for step in steps if step != before_step]
            if after_step in steps:
                steps.insert(steps.index(after_step), before_step)
            else:
                steps.append(before_step)
            changed = True
            required.add(before_step)

    if not changed:
        return plan
    out = dict(plan)
    out["steps"] = sort_plan_steps_by_workflow_order(steps)
    if required:
        out = with_user_required_steps(out, required)
    return out


def _plan_steps_are_gated(steps: list[str] | None) -> bool:
    return set(steps or []) <= {"validate_config", "dry_run"}


def _plan_ready_for_step_inference(plan: dict) -> bool:
    needs = set(plan.get("needs_user_input") or [])
    return not (needs - {"bounding_box_coords"})


def infer_gated_plan_steps(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """Infer workflow steps when the planner returned only validate_config/dry_run."""
    if not isinstance(plan, dict) or not _plan_steps_are_gated(plan.get("steps")):
        return plan
    extracted = infer_goal_steps_from_request(user_request)
    if not extracted:
        return plan
    out = dict(plan)
    steps = list(extracted)
    if "validate_config" not in steps:
        steps.insert(0, "validate_config")
    out["steps"] = sort_plan_steps_by_workflow_order(steps)
    _append_plan_note(out, "Workflow steps inferred from user prompt.")
    return out


def recompute_plan_needs_from_catalog(
    plan: dict,
    catalog: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """Recompute needs_user_input from resolved steps and the operation catalog."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    resolved_steps = list(out.get("steps") or [])
    required_config_fields: set[str] = set()
    for op in catalog.get("operations", []):
        if op.get("name") not in resolved_steps:
            continue
        for req in op.get("requires", []):
            if req in {
                "pour_point_coords",
                "bounding_box_coords",
                "experiment_time_start",
                "experiment_time_end",
                "domain_name",
                "experiment_id",
                "domain_def",
                "hydrological_model",
            }:
                required_config_fields.add(req)

    missing = [field for field in sorted(required_config_fields) if not _s(cfg.get(field))]
    if plan_uses_local_data(cfg, resolved_steps, user_request, data_dir=data_dir):
        missing = [field for field in missing if field != "bounding_box_coords"]
    out["needs_user_input"] = missing
    return out


def resolve_plan_step_dependencies(
    plan: dict,
    user_request: str,
    *,
    catalog: dict,
    data_dir: str | Path | None = None,
) -> dict:
    """Infer goals from the prompt, expand catalog dependencies, and refresh needs_user_input."""
    from server.capabilities.resolve_dependencies import resolve_step_dependencies

    user_request = _s(user_request)
    new_plan = dict(plan)

    new_plan = normalize_local_workflow_plan(
        new_plan,
        user_request,
        data_dir=data_dir,
        skip_workflow_step_restore=False,
    )

    steps = list(new_plan.get("steps") or [])
    goal_steps = [step for step in steps if step not in ("validate_config", "dry_run")]
    if not goal_steps:
        goal_steps = infer_goal_steps_from_request(user_request)
        if not goal_steps and re.search(r"\bsumma\b", user_request, flags=re.IGNORECASE):
            goal_steps = ["run_model"]

    if goal_steps:
        resolved_steps: list[str] = []
        for goal in goal_steps:
            try:
                chain = resolve_step_dependencies(goal, catalog, include_validate=False)
            except Exception:
                chain = [goal]
            for item in chain:
                if item not in resolved_steps:
                    resolved_steps.append(item)
        if "validate_config" not in resolved_steps:
            resolved_steps.insert(0, "validate_config")
        if "dry_run" not in (plan.get("steps") or []):
            resolved_steps = [step for step in resolved_steps if step != "dry_run"]
        resolved_steps = sort_plan_steps_by_workflow_order(resolved_steps)
    else:
        resolved_steps = merge_step_dependencies_preserving_order(steps, catalog)
        if "dry_run" not in (plan.get("steps") or []):
            resolved_steps = [step for step in resolved_steps if step != "dry_run"]

    new_plan["steps"] = resolved_steps
    new_plan = recompute_plan_needs_from_catalog(
        new_plan,
        catalog,
        user_request,
        data_dir=data_dir,
    )

    notes = _s(new_plan.get("notes"))
    if not (new_plan.get("needs_user_input") or []) and "Missing required inputs:" in notes:
        notes = re.sub(
            r"Missing required inputs:.*?(?=\s*\||$)",
            "",
            notes,
            flags=re.IGNORECASE,
        ).strip(" |")
    new_plan["notes"] = (
        f"{notes} | Dependencies resolved from SYMFLUENCE operation catalog."
        if notes
        else "Dependencies resolved from SYMFLUENCE operation catalog."
    ).strip(" |")

    new_plan = strip_user_forbidden_download_steps(new_plan, user_request)
    new_plan = normalize_local_workflow_plan(
        new_plan,
        user_request,
        data_dir=data_dir,
        skip_workflow_step_restore=True,
    )
    return new_plan


def merge_step_dependencies_preserving_order(steps: list[str], catalog: dict) -> list[str]:
    """Insert missing catalog dependencies, then return canonical workflow order."""
    from server.capabilities.resolve_dependencies import resolve_step_dependencies

    base_steps = [step for step in steps if step != "dry_run"]
    extras: list[str] = []
    for step in base_steps:
        try:
            chain = resolve_step_dependencies(step, catalog, include_validate=False)
        except Exception:
            chain = [step]
        for item in chain:
            if item not in base_steps and item not in extras:
                extras.append(item)

    merged = sort_plan_steps_by_workflow_order(extras + base_steps)
    if "validate_config" not in merged:
        merged.insert(0, "validate_config")
    return merged


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


def ensure_cloud_data_access_for_acquire_steps(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """Online fetch when acquire_* steps need cloud data (skip when local forcing exists)."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    steps = list(out.get("steps") or [])
    if not {"acquire_attributes", "acquire_forcings"} & set(steps):
        return out

    cfg = dict(out.get("config") or {})
    domain_name = _s(cfg.get("domain_name"))
    if request_indicates_local_data_reuse(user_request, cfg, data_dir=data_dir):
        if domain_name and data_dir and domain_has_local_era5_raw_forcing(data_dir, domain_name):
            return ensure_local_data_access_in_plan(out)
        if plan_uses_local_data(cfg, steps, user_request, data_dir=data_dir):
            return ensure_local_data_access_in_plan(out)

    if (
        domain_name
        and data_dir
        and "acquire_forcings" in steps
        and domain_has_local_era5_raw_forcing(data_dir, domain_name)
    ):
        return ensure_local_data_access_in_plan(out)

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
        out = ensure_cloud_data_access_for_acquire_steps(out, user_request, data_dir=data_dir)
        cfg = dict(out.get("config") or {})
        if "acquire_attributes" not in steps:
            idx = steps.index("define_domain") if "define_domain" in steps else len(steps)
            steps.insert(idx, "acquire_attributes")
            out["steps"] = steps
            out = ensure_cloud_data_access_for_acquire_steps(out, user_request, data_dir=data_dir)

        if plan_requires_bounding_box(
            cfg, out.get("steps") or [], user_request, data_dir=data_dir
        ):
            from server.core.ui_config_fields import plan_config_field_present

            if not plan_config_field_present(cfg, "bounding_box_coords"):
                needs = list(out.get("needs_user_input") or [])
                if "bounding_box_coords" not in needs:
                    needs.append("bounding_box_coords")
                out["needs_user_input"] = needs
        _append_plan_note(
            out,
            f"Local DEM missing for {domain_name}; using online acquisition (DATA_ACCESS cloud).",
        )

    return out


def _resolve_workflow_step_token(token: str, step_lookup: dict[str, str]) -> str:
    token = _s(token)
    if not token:
        return ""
    bare = step_lookup.get(token.lower())
    if bare:
        return bare
    pseudo = _PSEUDO_WORKFLOW_STEP_ALIASES.get(token.lower())
    if pseudo:
        return pseudo
    return step_lookup.get(token.lower(), "")


def extract_ordered_workflow_steps(user_request: str) -> list[str]:
    """Parse workflow_steps listed in the user prompt, preserving order."""
    if not user_request:
        return []
    allowed = set(WORKFLOW_STEP_NAMES)
    step_lookup = {name.lower(): name for name in WORKFLOW_STEP_NAMES}
    step_lookup.update({k.lower(): v for k, v in _PSEUDO_WORKFLOW_STEP_ALIASES.items()})
    block_patterns = [
        r"workflow_steps\s*:\s*\n(.*?)(?=\n\S|\Z)",
        r"(?:use\s+)?this\s+(?:local[- ]first\s+)?step\s+order\s*:?\s*\n(.*?)(?=\n(?:Do not|Generate\b)|\Z)",
        r"(?:use\s+)?this\s+exact\s+step\s+order\s*:?\s*\n(.*?)(?=\nGenerate\b|\Z)",
    ]
    block_text = ""
    for pattern in block_patterns:
        block = re.search(pattern, user_request, flags=re.IGNORECASE | re.DOTALL)
        if block:
            block_text = block.group(1)
            break
    if not block_text:
        return []

    ordered: list[str] = []
    seen: set[str] = set()
    for line in block_text.splitlines():
        line = line.strip()
        if not line:
            continue
        step = ""
        bare = _resolve_workflow_step_token(line, step_lookup)
        if bare:
            step = bare
        else:
            match = re.search(r"^-\s*[\"']?([A-Za-z_]+)[\"']?", line)
            if not match:
                match = re.search(r"[\"']([A-Za-z_]+)[\"']", line)
            if match:
                step = _resolve_workflow_step_token(match.group(1), step_lookup)
        if step in allowed and step not in seen:
            ordered.append(step)
            seen.add(step)
    return ordered


def extract_user_required_steps_from_step_order(user_request: str) -> set[str]:
    """Canonical steps listed on their own line in a step-order block (not pseudo check_* aliases)."""
    if not user_request:
        return set()
    step_lookup = {name.lower(): name for name in WORKFLOW_STEP_NAMES}
    block_patterns = (
        r"workflow_steps\s*:\s*\n(.*?)(?=\n\S|\Z)",
        r"(?:use\s+)?this\s+(?:local[- ]first\s+)?step\s+order\s*:?\s*\n(.*?)(?=\n(?:Do not|Generate\b)|\Z)",
        r"(?:use\s+)?this\s+exact\s+step\s+order\s*:?\s*\n(.*?)(?=\nGenerate\b|\Z)",
    )
    block_text = ""
    for pattern in block_patterns:
        block = re.search(pattern, user_request, flags=re.IGNORECASE | re.DOTALL)
        if block:
            block_text = block.group(1)
            break
    if not block_text:
        return set()

    required: set[str] = set()
    for line in block_text.splitlines():
        token = _s(line)
        if not token:
            continue
        if token.lower() in _PSEUDO_WORKFLOW_STEP_ALIASES:
            continue
        bare = step_lookup.get(token.lower())
        if bare:
            required.add(bare)
    return required


def extract_ordered_steps_from_request(user_request: str) -> list[str]:
    """Parse explicit workflow steps from the prompt, preserving listed order."""
    ordered_block = extract_ordered_workflow_steps(user_request)
    if len(ordered_block) >= 3:
        return ordered_block
    if not user_request:
        return []

    step_lookup = {name.lower(): name for name in WORKFLOW_STEP_NAMES}
    found: list[str] = []
    seen: set[str] = set()
    for line in user_request.splitlines():
        line = line.strip()
        if not line:
            continue
        bare = step_lookup.get(line.lower())
        if bare and bare not in seen:
            found.append(bare)
            seen.add(bare)
            continue
        for step in WORKFLOW_STEP_NAMES:
            if step == "dry_run":
                continue
            if re.search(rf"\b{re.escape(step)}\b", line, flags=re.IGNORECASE) and step not in seen:
                found.append(step)
                seen.add(step)
                break
    return found


def restore_workflow_steps_from_user_request(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
) -> dict:
    """When the user supplies an explicit step list, honor that order."""
    if not isinstance(plan, dict):
        return plan
    ordered = extract_ordered_workflow_steps(user_request)
    if len(ordered) < 3:
        return plan
    cfg = dict(plan.get("config") or {})
    local_recovery = request_indicates_local_data_reuse(user_request, cfg, data_dir=data_dir)
    if not (
        local_recovery
        or user_requires_fresh_cloud_workflow(user_request, cfg)
        or {"define_domain", "discretize_domain"} <= set(ordered)
    ):
        return plan
    out = dict(plan)
    out["steps"] = ordered
    required = extract_user_required_steps_from_step_order(user_request)
    if required:
        out = with_user_required_steps(out, required)
    note = (
        "Workflow steps restored from user step-order list (local recovery)."
        if local_recovery
        else "Workflow steps restored from user workflow_steps list."
    )
    _append_plan_note(out, note)
    return out


def _normalize_chat_datetime(value: str, *, default_hm: str) -> str:
    value = _s(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return f"{value} {default_hm}"
    return value


def apply_chat_config_edits(plan: dict, user_message: str) -> dict:
    """Apply config changes from natural-language chat messages."""
    from server.core.ui_config_fields import apply_comprehensive_chat_config_edits

    return apply_comprehensive_chat_config_edits(plan, user_message)


def apply_chat_step_edits(plan: dict, user_message: str) -> dict:
    """Apply explicit add/remove step instructions from a chat message."""
    if not isinstance(plan, dict) or not user_message:
        return plan
    text = user_message.lower()
    steps = list(plan.get("steps") or [])
    changed = False
    added: set[str] = set()
    removed: set[str] = set()
    remove_verbs = r"(remove|removed|drop|dropped|skip|skipped|omit|omitted|exclude|excluded|without|delete|deleted)"
    for step in WORKFLOW_STEP_NAMES:
        if step == "dry_run":
            continue
        step_pat = re.escape(step)
        if re.search(rf"{remove_verbs}.*\b{step_pat}\b", text) or re.search(
            rf"\b{step_pat}\b.*{remove_verbs}", text
        ):
            if step in steps:
                steps = [s for s in steps if s != step]
                changed = True
            removed.add(step)
            continue
        if re.search(
            rf"\b(add|added|include|included|insert|inserted)\s+[\"']?{step_pat}\b",
            text,
        ):
            if step not in steps:
                if (
                    step == "model_agnostic_preprocessing"
                    and "model_specific_preprocessing" in steps
                ):
                    steps.insert(steps.index("model_specific_preprocessing"), step)
                else:
                    steps.append(step)
                changed = True
            added.add(step)
    if not changed:
        return plan
    out = dict(plan)
    out["steps"] = sort_plan_steps_by_workflow_order(steps)
    out = with_user_required_steps(out, added, remove=removed)
    return out


def _drop_satisfied_needs_user_input(plan: dict) -> dict:
    """Remove needs_user_input entries that already have values in plan.config."""
    if not isinstance(plan, dict):
        return plan
    from server.core.ui_config_fields import plan_config_field_present

    out = dict(plan)
    cfg = dict(out.get("config") or {})
    needs = [
        key
        for key in (out.get("needs_user_input") or [])
        if not plan_config_field_present(cfg, key)
    ]
    out["needs_user_input"] = needs
    return out


WORKFLOW_PLAN_MODE_SIMULATION = "simulation"
WORKFLOW_PLAN_MODE_CALIBRATION = "calibration"

_CALIBRATION_PLAN_CONFIG_KEYS = (
    "station_id",
    "STATION_ID",
    "calibration_period",
    "CALIBRATION_PERIOD",
    "evaluation_period",
    "EVALUATION_PERIOD",
    "optimization_metric",
    "OPTIMIZATION_METRIC",
    "optimization_target",
    "OPTIMIZATION_TARGET",
    "calibration_timestep",
    "CALIBRATION_TIMESTEP",
    "iterative_optimization_algorithm",
    "ITERATIVE_OPTIMIZATION_ALGORITHM",
    "iterations",
    "NUMBER_OF_ITERATIONS",
    "population_size",
    "POPULATION_SIZE",
    "params_to_calibrate",
    "PARAMS_TO_CALIBRATE",
    "basin_params_to_calibrate",
    "BASIN_PARAMS_TO_CALIBRATE",
    "streamflow_data_provider",
    "STREAMFLOW_DATA_PROVIDER",
)

_SIMULATION_STRIP_STEPS = frozenset({"calibrate_model", "process_observed_data"})

# Filled by CalibHydroAgent at design time unless the user names them in the main prompt.
_AGENT_OWNED_CALIBRATION_CONFIG_KEYS = (
    "calibration_period",
    "CALIBRATION_PERIOD",
    "evaluation_period",
    "EVALUATION_PERIOD",
    "spinup_period",
    "SPINUP_PERIOD",
    "optimization_metric",
    "OPTIMIZATION_METRIC",
    "optimization_target",
    "OPTIMIZATION_TARGET",
    "calibration_timestep",
    "CALIBRATION_TIMESTEP",
    "iterative_optimization_algorithm",
    "ITERATIVE_OPTIMIZATION_ALGORITHM",
    "iterations",
    "NUMBER_OF_ITERATIONS",
    "population_size",
    "POPULATION_SIZE",
    "params_to_calibrate",
    "PARAMS_TO_CALIBRATE",
    "basin_params_to_calibrate",
    "BASIN_PARAMS_TO_CALIBRATE",
)

_DOMAIN_CONFIG_KEYS = (
    "domain_name",
    "DOMAIN_NAME",
    "experiment_id",
    "EXPERIMENT_ID",
    "pour_point_coords",
    "POUR_POINT_COORDS",
    "bounding_box_coords",
    "BOUNDING_BOX_COORDS",
    "hydrological_model",
    "HYDROLOGICAL_MODEL",
    "domain_def",
    "DOMAIN_DEFINITION_METHOD",
    "experiment_time_start",
    "EXPERIMENT_TIME_START",
    "experiment_time_end",
    "EXPERIMENT_TIME_END",
    "forcing_dataset",
    "FORCING_DATASET",
    "routing_model",
    "ROUTING_MODEL",
    "num_processes",
    "NUM_PROCESSES",
    "data_access",
    "DATA_ACCESS",
)


def plan_workflow_mode(plan: dict | None) -> str:
    return _s((plan or {}).get("workflow_plan_mode")).lower()


def is_calibration_workflow_plan(plan: dict | None) -> bool:
    return plan_workflow_mode(plan) == WORKFLOW_PLAN_MODE_CALIBRATION


def is_simulation_workflow_plan(plan: dict | None) -> bool:
    return plan_workflow_mode(plan) == WORKFLOW_PLAN_MODE_SIMULATION


def planner_mode_instructions(mode: str) -> str:
    mode = _s(mode).lower()
    if mode == WORKFLOW_PLAN_MODE_SIMULATION:
        return (
            "\n\nWORKFLOW MODE: simulation only.\n"
            "- Keep the full SUMMA pipeline: validate_config, setup_project, create_pour_point, "
            "acquire_attributes, define_domain, discretize_domain, acquire_forcings, "
            "model_agnostic_preprocessing, build_model_ready_store, model_specific_preprocessing, "
            "and run_model.\n"
            "- Do not omit those steps when local files already exist; Execute plan reuses artifacts at run time.\n"
            "- Add postprocess_results only when the user asked for evaluation, metrics, or plots.\n"
            "- Do NOT include calibrate_model or process_observed_data unless the user explicitly requests them above.\n"
            "- Do NOT set station_id, calibration_period, evaluation_period, optimization fields, "
            "params_to_calibrate, or streamflow_data_provider in config.\n"
        )
    if mode == WORKFLOW_PLAN_MODE_CALIBRATION:
        return (
            "\n\nWORKFLOW MODE: calibration.\n"
            "- Keep the same full SUMMA pipeline as a simulation workflow "
            "(validate_config through run_model, including define_domain, discretize_domain, "
            "acquire_forcings, and model_agnostic_preprocessing).\n"
            "- Do not omit those steps just because local artifacts exist; Execute plan reuses them at run time.\n"
            "- Add process_observed_data and calibrate_model for streamflow calibration (unless the user forbids them).\n"
            "- Set station_id and streamflow_data_provider=WSC when a pour point is available.\n"
            "- Leave calibration_period, optimization_metric, iterative_optimization_algorithm, "
            "iterations, population_size, params_to_calibrate, and related optimization fields NULL "
            "unless the user explicitly requests them above — CalibHydroAgent designs these at calibration time.\n"
            "- Do NOT include postprocess_results unless the user explicitly asks for it.\n"
        )
    return ""


def _explicit_agent_calibration_fields(user_request: str) -> set[str]:
    try:
        from calib_hydro_agent.prompt_fields import explicit_calibration_fields_in_prompt

        return explicit_calibration_fields_in_prompt(user_request)
    except ImportError:
        return set()


def strip_agent_calibration_config_unless_in_prompt(plan: dict, user_request: str = "") -> dict:
    """Remove agent-owned calibration knobs unless the user named them in the prompt."""
    if not isinstance(plan, dict):
        return plan
    explicit = _explicit_agent_calibration_fields(user_request)
    if not explicit:
        out = dict(plan)
        cfg = dict(out.get("config") or {})
        extra = dict(cfg.get("extra_config") or {}) if isinstance(cfg.get("extra_config"), dict) else {}
        for key in _AGENT_OWNED_CALIBRATION_CONFIG_KEYS:
            cfg.pop(key, None)
            extra.pop(key, None)
        if extra:
            cfg["extra_config"] = extra
        else:
            cfg.pop("extra_config", None)
        out["config"] = cfg
        return out

    out = dict(plan)
    cfg = dict(out.get("config") or {})
    extra = dict(cfg.get("extra_config") or {}) if isinstance(cfg.get("extra_config"), dict) else {}
    session_aliases = {
        "iterative_optimization_algorithm": "iterative_optimization_algorithm",
        "optimization_metric": "optimization_metric",
        "optimization_target": "optimization_target",
        "calibration_timestep": "calibration_timestep",
        "iterations": "iterations",
        "population_size": "population_size",
        "calibration_period": "calibration_period",
        "evaluation_period": "evaluation_period",
        "spinup_period": "spinup_period",
        "params_to_calibrate": "params_to_calibrate",
        "basin_params_to_calibrate": "basin_params_to_calibrate",
    }
    for field in session_aliases:
        if field not in explicit:
            for key in list(cfg.keys()):
                if key.lower() == field.lower() or key.upper().replace("_", "") == field.upper().replace("_", ""):
                    cfg.pop(key, None)
            extra.pop(field, None)
    if extra:
        cfg["extra_config"] = extra
    else:
        cfg.pop("extra_config", None)
    out["config"] = cfg
    return out


def merge_domain_config_from_simulation_plan(cal_plan: dict, sim_plan: dict | None) -> dict:
    """Carry domain/experiment settings from a simulation plan into a calibration plan."""
    if not isinstance(cal_plan, dict) or not isinstance(sim_plan, dict):
        return cal_plan
    out = dict(cal_plan)
    cfg = dict(out.get("config") or {})
    sim_cfg = dict(sim_plan.get("config") or {})
    sim_extra = sim_cfg.get("extra_config") if isinstance(sim_cfg.get("extra_config"), dict) else {}
    if isinstance(sim_extra, dict):
        sim_cfg = {**sim_extra, **sim_cfg}
    for key in _DOMAIN_CONFIG_KEYS:
        if _s(cfg.get(key)):
            continue
        val = sim_cfg.get(key)
        if val not in (None, ""):
            cfg[key] = val
    out["config"] = cfg
    return out


def merge_simulation_steps_into_calibration_plan(cal_plan: dict, sim_plan: dict | None) -> dict:
    """Keep simulation workflow steps and add calibration steps on top."""
    if not isinstance(cal_plan, dict):
        return cal_plan
    out = dict(cal_plan)
    cal_steps = list(out.get("steps") or [])
    sim_steps = list((sim_plan or {}).get("steps") or []) if isinstance(sim_plan, dict) else []
    if not sim_steps:
        return out
    merged: list[str] = []
    for step in sim_steps + cal_steps:
        if step and step not in merged:
            merged.append(step)
    out["steps"] = sort_plan_steps_by_workflow_order(merged)
    return out


_SUMMA_DELINEATE_CORE_STEPS = (
    "validate_config",
    "setup_project",
    "create_pour_point",
    "acquire_attributes",
    "define_domain",
    "discretize_domain",
    "acquire_forcings",
    "model_agnostic_preprocessing",
    "build_model_ready_store",
    "model_specific_preprocessing",
    "run_model",
)
_LUMPED_CORE_STEPS = (
    "validate_config",
    "setup_project",
    "create_pour_point",
    "acquire_attributes",
    "acquire_forcings",
    "model_agnostic_preprocessing",
    "build_model_ready_store",
    "model_specific_preprocessing",
    "run_model",
)


def _user_requested_postprocess_results(user_request: str) -> bool:
    text = _s(user_request)
    if not text:
        return False
    if re.search(r"\bdo not (?:run|include) postprocess_results\b", text, re.I):
        return False
    stripped = re.sub(r"workflow mode:.*", "", text, flags=re.I | re.S)
    return bool(
        re.search(r"\bpostprocess_results\b", stripped, re.I)
        or re.search(r"\b(evaluate results|plot results|compute metrics)\b", stripped, re.I)
    )


def restore_simulation_setup_steps_for_calibration(
    plan: dict,
    user_request: str = "",
    sim_plan: dict | None = None,
) -> dict:
    """Keep the full SUMMA pipeline in simulation and calibration plans."""
    if not isinstance(plan, dict):
        return plan
    mode = plan_workflow_mode(plan)
    if mode not in {WORKFLOW_PLAN_MODE_SIMULATION, WORKFLOW_PLAN_MODE_CALIBRATION}:
        return plan

    from server.core.ui_config_fields import is_lumped_workflow

    cfg = dict(plan.get("config") or {})
    steps = list(plan.get("steps") or [])
    sim_steps = list((sim_plan or {}).get("steps") or []) if isinstance(sim_plan, dict) else []
    lumped = is_lumped_workflow(cfg, user_request)
    domain_def = _s(cfg.get("domain_def")).lower()
    model = _s(cfg.get("hydrological_model")).upper()
    routing = _s(cfg.get("routing_model")).lower()
    wants_delineate = not lumped and (
        domain_def in ("delineate", "semidistributed", "semi_distributed")
        or (model == "SUMMA" and "mizu" in routing)
        or "define_domain" in sim_steps
        or "discretize_domain" in sim_steps
    )
    core = list(_SUMMA_DELINEATE_CORE_STEPS if wants_delineate else _LUMPED_CORE_STEPS)
    if mode == WORKFLOW_PLAN_MODE_CALIBRATION:
        for step in ("process_observed_data", "calibrate_model"):
            if step not in core:
                core.append(step)

    to_add: list[str] = []
    for step in core:
        if step in steps:
            continue
        if user_forbids_download_step(user_request, step):
            continue
        if re.search(rf"\bdo not (?:run|include) {re.escape(step)}\b", user_request or "", re.I):
            continue
        to_add.append(step)

    out = dict(plan)
    merged = list(steps) + to_add
    if not _user_requested_postprocess_results(user_request):
        merged = [step for step in merged if step != "postprocess_results"]
    merged = [step for step in merged if step != "dry_run"]
    out["steps"] = sort_plan_steps_by_workflow_order(merged)
    if to_add:
        _append_plan_note(
            out,
            "Kept full simulation workflow steps: " + ", ".join(to_add) + ".",
        )
    return out


def strip_calibration_from_plan(plan: dict, user_request: str = "") -> dict:
    """Remove calibration-only steps and config keys from a simulation plan."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    steps = list(out.get("steps") or [])
    kept_steps: list[str] = []
    for step in steps:
        if step in _SIMULATION_STRIP_STEPS and workflow_step_user_required(out, step, user_request):
            kept_steps.append(step)
        elif step not in _SIMULATION_STRIP_STEPS:
            kept_steps.append(step)
    out["steps"] = kept_steps

    for key in _CALIBRATION_PLAN_CONFIG_KEYS:
        cfg.pop(key, None)
    extra = cfg.get("extra_config")
    if isinstance(extra, dict):
        extra = dict(extra)
        for key in _CALIBRATION_PLAN_CONFIG_KEYS:
            extra.pop(key, None)
        if extra:
            cfg["extra_config"] = extra
        else:
            cfg.pop("extra_config", None)
    out["config"] = cfg
    return out


def ensure_calibration_workflow_steps(plan: dict, user_request: str = "") -> dict:
    """Ensure calibration plans include obs download and calibrate steps when allowed."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    steps = list(out.get("steps") or [])
    to_add: list[str] = []
    for step in ("process_observed_data", "calibrate_model"):
        if step in steps:
            continue
        if workflow_step_user_required(out, step, user_request):
            continue
        forbidden = _DOWNLOAD_STEP_FORBID_PHRASES.get(step)
        if forbidden and any(phrase in (user_request or "").lower() for phrase in forbidden):
            continue
        if re.search(rf"\bdo not (?:run|include) {re.escape(step)}\b", user_request or "", re.I):
            continue
        to_add.append(step)
    if to_add:
        out["steps"] = sort_plan_steps_by_workflow_order(steps + to_add)
        _append_plan_note(out, f"Added calibration steps: {', '.join(to_add)}.")
    return out


def normalize_local_workflow_plan(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
    skip_workflow_step_restore: bool = False,
    workflow_plan_mode: str | None = None,
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

    out = try_restore_local_recovery_plan(out, user_request, data_dir=data_dir)
    cfg = dict(out.get("config") or {})
    out["config"] = cfg
    steps = list(out.get("steps") or [])

    mode = _s(workflow_plan_mode) or plan_workflow_mode(out)
    if mode in {WORKFLOW_PLAN_MODE_SIMULATION, WORKFLOW_PLAN_MODE_CALIBRATION}:
        out["workflow_plan_mode"] = mode

    out = strip_user_forbidden_download_steps(out, user_request)
    if mode == WORKFLOW_PLAN_MODE_SIMULATION:
        pass
    elif mode == WORKFLOW_PLAN_MODE_CALIBRATION:
        pass
    else:
        out = ensure_plan_station_id(out, user_request)
    out = ensure_domain_name_user_input(out, user_request, data_dir=data_dir)
    if not skip_workflow_step_restore:
        out = restore_workflow_steps_from_user_request(out, user_request, data_dir=data_dir)
    out = ensure_skip_domain_rerun_when_local_artifacts_exist(out, user_request, data_dir=data_dir)
    out = ensure_skip_acquire_forcings_when_local_forcing(out, user_request, data_dir=data_dir)
    out = ensure_skip_model_agnostic_when_local_preprocessing(out, user_request, data_dir=data_dir)
    if request_indicates_local_data_reuse(user_request, cfg, data_dir=data_dir):
        out = ensure_local_data_access_in_plan(out)
    out = ensure_online_data_when_missing(out, user_request, data_dir=data_dir)
    cfg = dict(out.get("config") or {})
    out["config"] = cfg
    steps = list(out.get("steps") or [])

    if (
        not skip_workflow_step_restore
        and _plan_steps_are_gated(steps)
        and _plan_ready_for_step_inference(out)
    ):
        out = restore_workflow_steps_from_user_request(out, user_request, data_dir=data_dir)
        steps = list(out.get("steps") or [])
        if _plan_steps_are_gated(steps):
            out = infer_gated_plan_steps(out, user_request, data_dir=data_dir)
            steps = list(out.get("steps") or [])

    if mode == WORKFLOW_PLAN_MODE_SIMULATION:
        out = strip_calibration_from_plan(out, user_request)
        out = restore_simulation_setup_steps_for_calibration(out, user_request)
    elif mode == WORKFLOW_PLAN_MODE_CALIBRATION:
        out = restore_simulation_setup_steps_for_calibration(out, user_request)
        out = ensure_calibration_workflow_steps(out, user_request)
        out = ensure_plan_station_id(out, user_request)

    if not plan_uses_local_data(cfg, steps, user_request, data_dir=data_dir):
        return _drop_satisfied_needs_user_input(out)

    needs = [x for x in (out.get("needs_user_input") or []) if x != "bounding_box_coords"]
    out["needs_user_input"] = needs

    if not out.get("needs_user_input"):
        notes = _s(out.get("notes"))
        if "Missing required inputs: bounding_box_coords" in notes:
            out["notes"] = (
                "Local-data workflow (no bounding box required). "
                "Steps restored from prompt where the planner returned only validate_config/dry_run."
            )

    return _drop_satisfied_needs_user_input(out)


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


def infer_goal_steps_from_request(user_request: str) -> list[str]:
    """Infer high-level workflow goals from natural-language hydrology prompts."""
    text = _s(user_request).lower()
    if not text:
        return []

    goals: list[str] = []

    def add(step: str) -> None:
        if step not in goals:
            goals.append(step)

    if re.search(r"\bprocess_observed\b", text) or re.search(r"\bobserved\s+streamflow\b", text):
        add("process_observed_data")

    if (
        re.search(r"\bfrom\s+scratch\b", text)
        or re.search(r"\brun\s+(?:the\s+)?model\b", text)
        or re.search(r"\brun\s+summa\b", text)
        or re.search(r"\bsumma\s+workflow\b", text)
        or (re.search(r"\bworkflow\b", text) and re.search(r"\bsumma\b", text))
    ):
        add("run_model")

    if re.search(r"\bsemi[- ]?distributed\b", text):
        add("define_domain")
        add("discretize_domain")

    if re.search(r"\bprepare\s+.*\binput\b", text) or re.search(r"\bsumma\s+input\b", text):
        add("model_specific_preprocessing")

    if re.search(r"\bforcing\b", text):
        add("acquire_forcings")

    if re.search(r"\bacquire\s+attribute", text) or re.search(r"\battributes\s+and\b", text):
        add("acquire_attributes")

    if (
        re.search(r"\bgenerate\s+the\s+domain\b", text)
        or re.search(r"\bdefine\s+domain\b", text)
        or re.search(r"\bdelineat", text)
    ):
        add("define_domain")

    for step in extract_steps_from_request(user_request, WORKFLOW_STEP_NAMES):
        add(step)

    return goals
