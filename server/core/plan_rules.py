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
    extra = cfg.get("extra_config") if isinstance(cfg.get("extra_config"), dict) else {}
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
    extra = cfg.get("extra_config") if isinstance(cfg.get("extra_config"), dict) else {}
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


_DOMAIN_META_WORDS = frozenset({
    "name", "called", "named", "the", "a", "an", "is", "for", "my", "our",
    "this", "that", "as", "to", "of", "in", "with", "from",
})


def extract_explicit_domain_name_from_request(user_request: str) -> str:
    """Return domain_name only when the user explicitly names it in the prompt."""
    text = _s(user_request)
    if not text:
        return ""

    patterns = (
        # High-specificity patterns first
        r"\buse\s+([A-Za-z0-9_\-]+)\s+as\s+(?:the\s+)?domain(?:\s+name|_name)\b",
        r"\b(?:set|change|update)\s+(?:the\s+)?domain(?:\s+name|_name)\s+(?:to\s+)?([A-Za-z0-9_\-]+)\b",
        r"\bdomain\s+called\s+([A-Za-z0-9_\-]+)",
        r"\b(?:called|named)\s+([A-Za-z0-9_\-]+)\s+for\s+experiment\b",
        r"\bfor\s+domain\s+([A-Za-z0-9_\-]+)",
        r"\bdomain\s+([A-Za-z0-9_\-]+)\s+with\s+experiment\b",
        r"\bdomain\s+([A-Za-z0-9_\-]+)\s*,\s*experiment\b",
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
            token = match.group(1)
            if token.lower() in _DOMAIN_META_WORDS:
                continue
            return normalize_domain_name_token(token)
    return ""


UI_DEFAULT_EXPERIMENT_START = "2001-01-01 01:00"
UI_DEFAULT_EXPERIMENT_END = "2001-01-10 23:00"


def extract_experiment_dates_from_request(user_request: str) -> tuple[str, str]:
    """Parse common natural-language experiment windows from the user prompt."""
    text = _s(user_request)
    if not text:
        return "", ""

    year_range = re.search(r"\bfrom\s+(\d{4})\s+to\s+(\d{4})\b", text, flags=re.IGNORECASE)
    if year_range:
        start_year, end_year = year_range.group(1), year_range.group(2)
        return f"{start_year}-01-01 01:00", f"{end_year}-12-31 23:00"

    patterns = (
        r"\bfrom\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\b",
        r"\bdates?\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\b",
        r"\b(?:experiment\s+window|run)\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\b",
        r"\b(?:calibration|evaluation)\s+period\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return f"{match.group(1)} 01:00", f"{match.group(2)} 23:00"
    return "", ""


def request_mentions_experiment_dates(user_request: str) -> bool:
    text = _s(user_request)
    if not text:
        return False
    if extract_experiment_dates_from_request(text) != ("", ""):
        return True
    return bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", text))


def sanitize_planner_experiment_dates(cfg: dict, user_request: str) -> dict:
    """Apply prompt dates and drop UI placeholder windows not mentioned by the user."""
    out = dict(cfg or {})
    start, end = extract_experiment_dates_from_request(user_request)
    if start:
        out["experiment_time_start"] = start
    if end:
        out["experiment_time_end"] = end

    prompt_has_dates = request_mentions_experiment_dates(user_request)
    prompt_mentions_2001 = bool(re.search(r"\b2001\b", _s(user_request)))

    for key in ("experiment_time_start", "experiment_time_end"):
        value = _s(out.get(key))
        if not value:
            continue
        is_ui_default = value in {
            UI_DEFAULT_EXPERIMENT_START,
            UI_DEFAULT_EXPERIMENT_END,
            UI_DEFAULT_EXPERIMENT_START[:10],
            UI_DEFAULT_EXPERIMENT_END[:10],
        }
        is_2001 = value.startswith("2001-")
        if is_ui_default and not prompt_has_dates:
            out.pop(key, None)
        elif is_2001 and not prompt_mentions_2001:
            out.pop(key, None)
    return out


def apply_workflow_config_policies(cfg: dict, user_request: str = "") -> dict:
    """Normalize discretization, lumped routing, and elevation extras from the prompt."""
    from server.core.ui_config_fields import (
        is_lumped_workflow,
        normalize_discretization_value,
        symfluence_discretization_from_plan,
    )

    out = dict(cfg or {})
    disc = normalize_discretization_value(_s(out.get("discretization")))
    if disc:
        out["discretization"] = disc

    if re.search(r"\b(?:do\s+not\s+use|without|no)\s+mizu\s*route\b", user_request, flags=re.IGNORECASE):
        out.pop("routing_model", None)

    if is_lumped_workflow(out, user_request):
        extra = dict(out.get("extra_config") or {}) if isinstance(out.get("extra_config"), dict) else {}
        extra.setdefault("ROUTING_DELINEATION", "lumped")
        extra.setdefault("PARAMETER_REGIONALIZATION", "lumped")
        out["extra_config"] = extra
        out["discretization"] = symfluence_discretization_from_plan(out, user_request)

    band_match = re.search(r"\belevation\s+band\s+size\s+(\d+)", user_request, flags=re.IGNORECASE)
    if band_match:
        extra = dict(out.get("extra_config") or {}) if isinstance(out.get("extra_config"), dict) else {}
        extra["ELEVATION_BAND_SIZE"] = int(band_match.group(1))
        out["extra_config"] = extra

    if re.search(r"\bGRUs?\b", user_request, flags=re.IGNORECASE):
        out["discretization"] = "GRUs"

    return out


def domain_name_literal_in_request(domain_name: str, user_request: str) -> bool:
    """True when the prompt names this basin in a domain context (not weak inference)."""
    token = normalize_domain_name_token(domain_name)
    text = _s(user_request)
    if not token or not text:
        return False
    if extract_explicit_domain_name_from_request(text).lower() == token.lower():
        return True
    patterns = (
        rf"\bfor\s+domain\s+{re.escape(token)}\b",
        rf"\bdomain\s+{re.escape(token)}\b",
        rf"\bcalled\s+{re.escape(token)}\b",
        rf"\bdomain\s+called\s+{re.escape(token)}\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


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

    if domain_name_literal_in_request(name, user_request):
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
        if weak and not domain_name_literal_in_request(_s(cfg.get("domain_name")), user_request):
            cfg.pop("domain_name", None)
            _append_plan_note(
                out,
                "Removed weak inferred domain_name; provide a filesystem-safe basin name "
                "(e.g. Bow_at_Banff_semi_distributed).",
            )
        elif weak and domain_name_literal_in_request(_s(cfg.get("domain_name")), user_request):
            cfg = apply_user_provided_domain_name(cfg, _s(cfg.get("domain_name")))

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
    """Set plan config to LOCAL data access (no cloud MAF/gistool fetch)."""
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
    """Drop acquire_forcings when local ERA5/SUMMA forcing is already on disk."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    domain_name = _s(cfg.get("domain_name"))
    steps = list(out.get("steps") or [])
    if user_requires_fresh_cloud_workflow(user_request, cfg):
        return out
    if "acquire_forcings" not in steps:
        return out
    if workflow_step_user_required(out, "acquire_forcings", user_request):
        return out
    if not domain_name or not data_dir:
        return out

    raw_exists = domain_has_local_era5_raw_forcing(data_dir, domain_name)
    summa_exists = domain_has_local_summa_forcing(data_dir, domain_name)
    local_first = request_indicates_local_data_reuse(user_request, cfg, data_dir=data_dir)

    if summa_exists:
        out["steps"] = [step for step in steps if step != "acquire_forcings"]
        out = ensure_local_data_access_in_plan(out)
        _append_plan_note(
            out,
            "Skipped acquire_forcings; reusing existing local SUMMA forcing files.",
        )
        return out

    if raw_exists and local_first:
        out["steps"] = [step for step in steps if step != "acquire_forcings"]
        out = ensure_local_data_access_in_plan(out)
        _append_plan_note(
            out,
            "Skipped acquire_forcings; reusing existing local ERA5/raw forcing files.",
        )
        return out

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
    domain_name = _s(cfg.get("domain_name"))
    steps = list(out.get("steps") or [])
    if user_requires_fresh_cloud_workflow(user_request, cfg):
        return out
    if "model_agnostic_preprocessing" not in steps:
        return out
    if workflow_step_user_required(out, "model_agnostic_preprocessing", user_request):
        return out
    if not domain_name or not data_dir:
        return out
    if not domain_has_local_summa_forcing(data_dir, domain_name):
        return out
    out["steps"] = [step for step in steps if step != "model_agnostic_preprocessing"]
    _append_plan_note(
        out,
        "Skipped model_agnostic_preprocessing; reusing existing local SUMMA forcing input.",
    )
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
) -> str:
    cfg = cfg or {}
    for candidate in (
        _s(cfg.get("station_id")),
        _s(fallback),
        extract_station_id_from_request(user_request),
    ):
        if is_valid_station_id(candidate):
            return candidate
    return ""


def ensure_plan_station_id(plan: dict, user_request: str = "") -> dict:
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    cfg = dict(out.get("config") or {})
    station_id = resolve_station_id_from_plan(cfg, user_request)
    if not station_id:
        out["config"] = cfg
        return out
    if _s(cfg.get("station_id")) != station_id:
        cfg["station_id"] = station_id
        out["config"] = cfg
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

    if is_weak_domain_name(domain_name):
        return out

    if domain_name_needs_user_input(cfg, user_request, data_dir=data_dir):
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

    extra = cfg.get("extra_config") if isinstance(cfg.get("extra_config"), dict) else {}
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
    return not (needs - {"bounding_box_coords", "pour_point_coords"})


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
    ordered = extract_ordered_steps_from_request(user_request)
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


def normalize_local_workflow_plan(
    plan: dict,
    user_request: str = "",
    *,
    data_dir: str | Path | None = None,
    skip_workflow_step_restore: bool = False,
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

    # Honor exclusive validate/dry-run requests before any step expansion.
    if request_requests_validation_dry_run_only(user_request):
        out["steps"] = ["validate_config", "dry_run"]
        out = ensure_domain_name_user_input(out, user_request, data_dir=data_dir)
        out = apply_explicit_step_constraints(out, user_request)
        return _drop_satisfied_needs_user_input(out)

    out = try_restore_local_recovery_plan(out, user_request, data_dir=data_dir)
    cfg = dict(out.get("config") or {})
    out["config"] = cfg
    steps = list(out.get("steps") or [])

    out = strip_user_forbidden_download_steps(out, user_request)
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
    cfg = apply_workflow_config_policies(cfg, user_request)
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

    out = apply_explicit_step_constraints(out, user_request)
    steps = list(out.get("steps") or [])
    cfg = dict(out.get("config") or {})

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


def _user_forbids_step_inference(user_request: str, step_keyword: str) -> bool:
    """True when the prompt explicitly forbids a step (e.g. 'do not run the model')."""
    text = _s(user_request).lower()
    kw = step_keyword.lower()
    neg = (
        rf"\b(?:do\s+not|don'?t|without|skip|omit|exclude|no)\s+(?:\w+\s+){{0,3}}{re.escape(kw)}\b",
        rf"\b(?:do\s+not|don'?t)\s+{re.escape(kw)}\b",
    )
    return any(re.search(p, text) for p in neg)


def request_forbids_run_model(user_request: str) -> bool:
    return (
        _user_forbids_step_inference(user_request, "run the model")
        or _user_forbids_step_inference(user_request, "run model")
        or _user_forbids_step_inference(user_request, "run_model")
        or _user_forbids_step_inference(user_request, "model run")
    )


def request_forbids_calibrate(user_request: str) -> bool:
    return (
        _user_forbids_step_inference(user_request, "calibrat")
        or _user_forbids_step_inference(user_request, "calibration")
    )


def request_forbids_postprocess(user_request: str) -> bool:
    return (
        _user_forbids_step_inference(user_request, "postprocess")
        or _user_forbids_step_inference(user_request, "postprocessing")
        or _user_forbids_step_inference(user_request, "post-process")
    )


def request_requests_validation_dry_run_only(user_request: str) -> bool:
    """True when the user asks only for validate_config / dry_run."""
    text = _s(user_request).lower()
    if not text:
        return False
    patterns = (
        r"\bonly\s+validate_config\s+and\s+dry_run\b",
        r"\bonly\s+validate(?:_config)?\s+and\s+dry[_\s-]?run\b",
        r"\bvalidate_config\s+and\s+dry_run\s+only\b",
        r"\bonly\s+(?:do\s+)?validate(?:_config)?\s+and\s+(?:a\s+)?dry[_\s-]?run\b",
        r"\bvalidate(?:_config)?\s+and\s+(?:run\s+a\s+)?dry[_\s-]?run\b.*\b(?:skip|do\s+not|don'?t|without)\b",
    )
    return any(re.search(p, text) for p in patterns)


def apply_explicit_step_constraints(plan: dict, user_request: str = "") -> dict:
    """Honor exclusive validate/dry-run requests and negative step constraints."""
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    text = _s(user_request)
    if request_requests_validation_dry_run_only(text):
        out["steps"] = ["validate_config", "dry_run"]
        _append_plan_note(out, "Restricted steps to validate_config and dry_run per user request.")
        return out

    steps = list(out.get("steps") or [])
    if not steps:
        return out

    remove: set[str] = set()
    if request_forbids_run_model(text):
        remove.update({"run_model", "calibrate_model"})
    if request_forbids_calibrate(text) or not re.search(r"\bcalibrat", text.lower()):
        remove.add("calibrate_model")
    if request_forbids_postprocess(text):
        remove.add("postprocess_results")

    if remove:
        out["steps"] = [step for step in steps if step not in remove]
    return out


def infer_goal_steps_from_request(user_request: str) -> list[str]:
    """Infer high-level workflow goals from natural-language hydrology prompts."""
    text = _s(user_request).lower()
    if not text:
        return []

    if request_requests_validation_dry_run_only(user_request):
        return ["validate_config", "dry_run"]

    forbids_model = request_forbids_run_model(user_request)
    forbids_calibrate = request_forbids_calibrate(user_request)
    forbids_postprocess = request_forbids_postprocess(user_request)

    goals: list[str] = []

    def add(step: str) -> None:
        if step not in goals:
            goals.append(step)

    if re.search(r"\bprocess_observed\b", text) or re.search(r"\bobserved\s+streamflow\b", text):
        add("process_observed_data")

    if not forbids_model and (
        re.search(r"\bfrom\s+scratch\b", text)
        or re.search(r"\brun\s+(?:the\s+)?model\b", text)
        or re.search(r"\b(?:and|then)\s+(?:the\s+)?model\b", text)
        or re.search(r"\brun\s+summa\b", text)
        or re.search(r"\bsumma\s+workflow\b", text)
        or (re.search(r"\bworkflow\b", text) and re.search(r"\bsumma\b", text))
    ):
        add("run_model")

    if not forbids_calibrate and re.search(r"\bcalibrat(?:e|ion)\s+(?:the\s+)?model\b", text):
        add("calibrate_model")

    # Require an affirmative postprocess mention, not "skip postprocessing".
    if not forbids_postprocess and re.search(
        r"\b(?:include\s+)?postprocess(?:ing|_results)?\b", text
    ) and not re.search(
        r"\b(?:do\s+not|don'?t|without|skip|omit|exclude|no)\b.{0,20}\bpostprocess",
        text,
    ):
        add("postprocess_results")

    if re.search(r"\bpreprocess", text):
        add("model_agnostic_preprocessing")
        add("model_specific_preprocessing")

    if re.search(r"\bsetup\b", text):
        add("setup_project")

    if re.search(r"\bsemi[- ]?distributed\b", text):
        add("define_domain")
        add("discretize_domain")

    if re.search(r"\bprepare\s+.*\binput\b", text) or re.search(r"\bsumma\s+input\b", text):
        add("model_specific_preprocessing")

    if re.search(r"\bforcings?\b", text) or re.search(r"\bdownload\b.*\bforcings?\b", text):
        add("acquire_forcings")

    if (
        re.search(r"\bacquire\s+attribute", text)
        or re.search(r"\bdownload\s+attribute", text)
        or re.search(r"\battributes\s+and\b", text)
    ):
        add("acquire_attributes")

    if (
        re.search(r"\bgenerate\s+the\s+domain\b", text)
        or re.search(r"\bdefine\s+domain\b", text)
        or re.search(r"\bdelineat", text)
    ):
        add("define_domain")

    for step in extract_steps_from_request(user_request, WORKFLOW_STEP_NAMES):
        if step == "run_model" and forbids_model:
            continue
        if step == "calibrate_model" and forbids_calibrate:
            continue
        if step == "postprocess_results" and forbids_postprocess:
            continue
        if step == "dry_run":
            add(step)
            continue
        add(step)

    if forbids_model:
        goals = [g for g in goals if g not in ("run_model", "calibrate_model")]
    if forbids_calibrate:
        goals = [g for g in goals if g != "calibrate_model"]
    if forbids_postprocess:
        goals = [g for g in goals if g != "postprocess_results"]

    return goals
