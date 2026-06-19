"""Registry of UI/planner config fields and chat-driven config edit helpers."""

from __future__ import annotations

import re
from typing import Any

from server.core.parameter_registry import FIRST_CLASS_FIELD_MAP, coerce_scalar_value
from server.core.symfluence_options import (
    CALIBRATION_ALGORITHMS,
    CALIBRATION_METRICS,
    CALIBRATION_TARGETS,
    CALIBRATION_TIMESTEPS,
    DOMAIN_DEF_OPTIONS,
    FORCING_DATASET_OPTIONS,
    HYDROLOGICAL_MODEL_OPTIONS,
    PET_METHOD_OPTIONS,
    STREAMFLOW_PROVIDER_OPTIONS,
    _LEGACY_FORCING_ALIASES,
    _UNSUPPORTED_HYDRO_MODELS,
)


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


# Canonical planner key -> session_state key (when different)
SESSION_KEY_ALIASES: dict[str, str] = {
    "experiment_time_start": "tstart",
    "experiment_time_end": "tend",
    "pour_point_coords": "selected_pour_point",
    "bounding_box_coords": "selected_bounding_box",
    "NUM_PROCESSES": "mpi",
    "num_processes": "mpi",
    "MPI_PROCESSES": "mpi",
    "mpi_processes": "mpi",
    "POPULATION_SIZE": "population_size",
    "NUMBER_OF_ITERATIONS": "iterations",
}

# All fields exposed in the assistant UI or commonly edited via chat.
CHAT_EDITABLE_FIELDS: list[dict[str, Any]] = [
    {"key": "domain_name", "type": "str"},
    {"key": "experiment_id", "type": "str"},
    {"key": "hydrological_model", "type": "model", "options": HYDROLOGICAL_MODEL_OPTIONS},
    {"key": "domain_def", "type": "str", "options": DOMAIN_DEF_OPTIONS},
    {"key": "forcing_dataset", "type": "str", "options": FORCING_DATASET_OPTIONS},
    {"key": "discretization", "type": "str"},
    {"key": "pour_point_coords", "type": "coords_pp"},
    {"key": "bounding_box_coords", "type": "coords_bbox"},
    {"key": "experiment_time_start", "type": "datetime", "default_hm": "01:00"},
    {"key": "experiment_time_end", "type": "datetime", "default_hm": "23:00"},
    {"key": "NUM_PROCESSES", "type": "int", "mirror": ["num_processes"]},
    {"key": "MPI_PROCESSES", "type": "int", "mirror": ["mpi_processes"]},
    {"key": "streamflow_data_provider", "type": "str", "options": STREAMFLOW_PROVIDER_OPTIONS},
    {"key": "station_id", "type": "str", "aliases": ["STATION_ID"]},
    {"key": "routing_model", "type": "str", "aliases": ["ROUTING_MODEL"]},
    {"key": "pet_method", "type": "str", "options": PET_METHOD_OPTIONS, "aliases": ["PET_METHOD"]},
    {"key": "spinup_period", "type": "period", "aliases": ["SPINUP_PERIOD"]},
    {"key": "calibration_period", "type": "period", "aliases": ["CALIBRATION_PERIOD"]},
    {"key": "evaluation_period", "type": "period", "aliases": ["EVALUATION_PERIOD"]},
    {"key": "iterative_optimization_algorithm", "type": "str", "options": CALIBRATION_ALGORITHMS,
     "aliases": ["ITERATIVE_OPTIMIZATION_ALGORITHM"]},
    {"key": "optimization_metric", "type": "str", "options": CALIBRATION_METRICS,
     "aliases": ["OPTIMIZATION_METRIC"]},
    {"key": "optimization_target", "type": "str", "options": CALIBRATION_TARGETS,
     "aliases": ["OPTIMIZATION_TARGET"]},
    {"key": "calibration_timestep", "type": "str", "options": CALIBRATION_TIMESTEPS,
     "aliases": ["CALIBRATION_TIMESTEP"]},
    {"key": "iterations", "type": "int", "aliases": ["NUMBER_OF_ITERATIONS"]},
    {"key": "population_size", "type": "int", "aliases": ["POPULATION_SIZE"]},
    {"key": "download_snotel", "type": "bool", "aliases": ["DOWNLOAD_SNOTEL"]},
    {"key": "snotel_station", "type": "str", "aliases": ["SNOTEL_STATION"]},
    {"key": "data_access", "type": "str"},
    {"key": "params_to_calibrate", "type": "str", "aliases": ["PARAMS_TO_CALIBRATE"]},
]

CHAT_EDITABLE_KEYS: set[str] = set()
for _field in CHAT_EDITABLE_FIELDS:
    CHAT_EDITABLE_KEYS.add(_field["key"])
    for _alias in _field.get("aliases") or []:
        CHAT_EDITABLE_KEYS.add(_alias)


def normalize_hydrological_model(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    upper = value.upper()
    if upper in _UNSUPPORTED_HYDRO_MODELS:
        return ""
    valid = {m for m in HYDROLOGICAL_MODEL_OPTIONS if m}
    return upper if upper in valid else ""


def normalize_pet_method(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return PET_METHOD_OPTIONS[0]
    legacy = {"hamon": "hargreaves"}
    if value in legacy:
        return legacy[value]
    for option in PET_METHOD_OPTIONS:
        if option == value:
            return option
    return PET_METHOD_OPTIONS[0]


def normalize_forcing_dataset(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return FORCING_DATASET_OPTIONS[3]  # ERA5
    alias = _LEGACY_FORCING_ALIASES.get(value.lower())
    if alias:
        return alias
    for option in FORCING_DATASET_OPTIONS:
        if option.lower() == value.lower():
            return option
    return FORCING_DATASET_OPTIONS[3]


def coerce_selectbox_value(value: str, options: list[str], *, normalizer=None) -> str:
    """Map session/plan values onto a valid selectbox option."""
    if normalizer:
        value = normalizer(value)
    if value in options:
        return value
    return options[0] if options else value


def session_key_for_plan_field(plan_key: str) -> str:
    return SESSION_KEY_ALIASES.get(plan_key, plan_key)


def _extra_config(cfg: dict) -> dict:
    extra = cfg.get("extra_config")
    return extra if isinstance(extra, dict) else {}


def lookup_plan_config(cfg: dict | None, *keys: str) -> Any:
    """Read a config value from plan.config and extra_config using aliases."""
    cfg = cfg or {}
    extra = _extra_config(cfg)
    yaml_aliases = {v: k for k, v in FIRST_CLASS_FIELD_MAP.items()}
    for key in keys:
        if cfg.get(key) is not None:
            return cfg.get(key)
        if extra.get(key) is not None:
            return extra.get(key)
        lower = key.lower()
        if cfg.get(lower) is not None:
            return cfg.get(lower)
        if extra.get(lower) is not None:
            return extra.get(lower)
        mapped = FIRST_CLASS_FIELD_MAP.get(key)
        if mapped and cfg.get(mapped) is not None:
            return cfg.get(mapped)
        if mapped and extra.get(mapped) is not None:
            return extra.get(mapped)
        canonical = yaml_aliases.get(key)
        if canonical and cfg.get(canonical) is not None:
            return cfg.get(canonical)
        if canonical and extra.get(canonical) is not None:
            return extra.get(canonical)
    return None


_SPATIAL_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "pour_point_coords": ("pour_point_coords", "POUR_POINT_COORDS"),
    "bounding_box_coords": ("bounding_box_coords", "BOUNDING_BOX_COORDS"),
}


def plan_config_field_present(cfg: dict | None, key: str) -> bool:
    """True when a first-class plan config field has a non-empty value."""
    aliases = _SPATIAL_FIELD_ALIASES.get(key)
    if aliases:
        value = lookup_plan_config(cfg, *aliases)
    else:
        yaml_key = FIRST_CLASS_FIELD_MAP.get(key)
        keys: list[str] = [key]
        if yaml_key:
            keys.append(yaml_key)
        value = lookup_plan_config(cfg, *keys)
    if value is None:
        return False
    return bool(str(value).strip())


def set_plan_config_value(cfg: dict, key: str, value: Any) -> None:
    """Write a value to plan.config using planner-facing keys only."""
    storage_key = preferred_plan_storage_key(key)
    if value is None or value == "":
        cfg.pop(storage_key, None)
        cfg.pop(key, None)
        yaml_key = FIRST_CLASS_FIELD_MAP.get(storage_key)
        if yaml_key:
            cfg.pop(yaml_key, None)
        meta = next(
            (f for f in CHAT_EDITABLE_FIELDS if preferred_plan_storage_key(f["key"]) == storage_key),
            None,
        )
        if meta:
            for alias in meta.get("aliases") or []:
                cfg.pop(alias, None)
            for mirror in meta.get("mirror") or []:
                cfg.pop(mirror, None)
        return
    cfg[storage_key] = value
    meta = next(
        (f for f in CHAT_EDITABLE_FIELDS if preferred_plan_storage_key(f["key"]) == storage_key),
        None,
    )
    if meta:
        for mirror in meta.get("mirror") or []:
            cfg.pop(mirror, None)
        for alias in meta.get("aliases") or []:
            cfg.pop(alias, None)
    yaml_key = FIRST_CLASS_FIELD_MAP.get(storage_key)
    if yaml_key:
        cfg.pop(yaml_key, None)


def _normalize_chat_datetime(value: str, *, default_hm: str) -> str:
    value = (value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return f"{value} {default_hm}"
    return value


def _extract_hydrological_model(text: str) -> str | None:
    upper = (text or "").upper()
    for model in HYDROLOGICAL_MODEL_OPTIONS:
        if not model:
            continue
        if re.search(rf"\b{re.escape(model)}\b", upper):
            normalized = normalize_hydrological_model(model)
            return normalized or None
    return None


def normalize_domain_name_value(raw: str) -> str:
    """Keep a single domain token; drop trailing 'and experiment_id …' from combined phrases."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    raw = re.split(r"\s+and\s+experiment_id\b", raw, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    match = re.match(r"^([A-Za-z0-9_\-]+)", raw)
    if match:
        return match.group(1)
    cleaned = re.sub(r"\s+", "_", raw)
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "", cleaned)
    return cleaned


_OPTIONAL_QUOTES = r'["\']?'
_PP_COORDS_CAPTURE = (
    rf"{_OPTIONAL_QUOTES}"
    r"(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?)"
    rf"{_OPTIONAL_QUOTES}"
)
_BBOX_COORDS_CAPTURE = (
    rf"{_OPTIONAL_QUOTES}"
    r"(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?)"
    rf"{_OPTIONAL_QUOTES}"
)


def _quoted_field_name(name: str) -> str:
    return rf'["\']?{re.escape(name)}["\']?'


def _normalize_coord_token(raw: str) -> str:
    return raw.replace(",", "/").strip().strip('"').strip("'").rstrip(".,;")


def _extract_bbox_coords_from_text(text: str) -> str | None:
    patterns = [
        rf"\bbounding\s+box(?:\s+coords|\s+coordinates)?\s*{_BBOX_COORDS_CAPTURE}",
        rf"\bbounding[_\s-]?box(?:\s+coords|\s+coordinates)?\s+(?:to\s+)?{_BBOX_COORDS_CAPTURE}",
        rf"\bbounding_box_coords\s*[=:]?\s*(?:to\s+)?{_BBOX_COORDS_CAPTURE}",
        rf"\bBOUNDING_BOX_COORDS\s*[=:]?\s*(?:to\s+)?{_BBOX_COORDS_CAPTURE}",
        rf"{_quoted_field_name('bounding_box_coords')}\s*[=:]\s*{_BBOX_COORDS_CAPTURE}",
        rf"{_quoted_field_name('BOUNDING_BOX_COORDS')}\s*[=:]\s*{_BBOX_COORDS_CAPTURE}",
        rf"\b(?:change|set|update|use)\s+{_quoted_field_name('bounding_box_coords')}\s*[=:]\s*{_BBOX_COORDS_CAPTURE}",
        rf"\b(?:change|set|update|use)\s+{_quoted_field_name('BOUNDING_BOX_COORDS')}\s*[=:]\s*{_BBOX_COORDS_CAPTURE}",
        rf"\b(?:change|set|update|use)\s+(?:the\s+)?(?:bounding\s+box|bbox)\s+(?:to\s+)?{_BBOX_COORDS_CAPTURE}",
        rf"\b(?:bounding\s+box|bbox)\s+(?:to\s+)?{_BBOX_COORDS_CAPTURE}",
        rf"\bbbox\s+(?:to\s+)?{_BBOX_COORDS_CAPTURE}",
    ]
    for pat in patterns:
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            return _normalize_coord_token(match.group(1))
    return None


def _extract_pour_point_coords_from_text(text: str) -> str | None:
    patterns = [
        rf"\bpour\s+point(?:\s+coords|\s+coordinates)?\s+{_PP_COORDS_CAPTURE}",
        rf"\bpour[_\s-]?point(?:\s+coords|\s+coordinates)?\s+(?:to\s+)?{_PP_COORDS_CAPTURE}",
        rf"\bpour_point_coords\s*[=:]?\s*(?:to\s+)?{_PP_COORDS_CAPTURE}",
        rf"{_quoted_field_name('pour_point_coords')}\s*[=:]\s*{_PP_COORDS_CAPTURE}",
        rf"{_quoted_field_name('POUR_POINT_COORDS')}\s*[=:]\s*{_PP_COORDS_CAPTURE}",
        rf"\b(?:change|set|update|use)\s+{_quoted_field_name('pour_point_coords')}\s*[=:]\s*{_PP_COORDS_CAPTURE}",
        rf"\b(?:change|set|update|use)\s+(?:the\s+)?pour\s+point\s+(?:to\s+)?{_PP_COORDS_CAPTURE}",
    ]
    for pat in patterns:
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            return _normalize_coord_token(match.group(1))
    return None


def normalize_discretization_value(raw: str) -> str:
    """Normalize planner/chat discretization tokens (user-facing intent)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    lower = raw.lower()
    if upper in {"G", "GR", "GRU"}:
        return "GRUs"
    if upper.startswith("GRU"):
        return "GRUs"
    if upper in {"H", "HR"}:
        return "HRUs"
    if upper.startswith("HRU"):
        return "HRUs"
    if lower in {"l", "lump"} or lower.startswith("lumped"):
        return "lumped"
    if lower.startswith("lump"):
        return "lumped"
    if lower == "elevation":
        return "elevation"
    return raw


def is_lumped_workflow(plan_cfg: dict | None, user_request: str = "") -> bool:
    """True when the user wants a lumped-basin workflow (not semi-distributed GRU routing)."""
    plan_cfg = plan_cfg or {}
    user_request = (user_request or "").lower()
    domain = _s(plan_cfg.get("domain_name")).lower()
    domain_def = _s(plan_cfg.get("domain_def")).lower()
    disc = normalize_discretization_value(
        _s(lookup_plan_config(plan_cfg, "discretization", "DOMAIN_DISCRETIZATION"))
    ).lower()
    if disc in {"lumped", "l", "lump"}:
        return True
    if domain_def == "lumped":
        return True
    if domain and "lumped" in domain and "semi" not in domain:
        return True
    if re.search(r"\bdiscretiz\w+\s+lumped\b", user_request):
        return True
    if re.search(r"\blumped\s+(?:basin|summa|workflow)\b", user_request):
        return True
    if re.search(r"\brun\s+a\s+lumped\b", user_request):
        return True
    return False


def symfluence_discretization_from_plan(
    plan_cfg: dict | None,
    user_request: str = "",
) -> str:
    """Map planner discretization to a SYMFLUENCE SUB_GRID_DISCRETIZATION value."""
    plan_cfg = plan_cfg or {}
    raw = _s(lookup_plan_config(plan_cfg, "discretization", "DOMAIN_DISCRETIZATION"))
    normalized = normalize_discretization_value(raw)
    if is_lumped_workflow(plan_cfg, user_request):
        return "GRUs"
    if normalized:
        return normalized
    return "GRUs"


def user_forbids_mizuroute(user_request: str) -> bool:
    text = (user_request or "").lower()
    return bool(
        re.search(
            r"do\s+not\s+use\s+mizuRoute|without\s+mizuRoute|no\s+mizuRoute|not\s+use\s+mizuRoute",
            text,
            flags=re.IGNORECASE,
        )
    )


def normalize_routing_model_value(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower in {"m", "miz", "mizu", "mizuroute"}:
        return "mizuRoute"
    return raw


def _field_lookup_patterns(field: dict[str, Any]) -> list[str]:
    key = field["key"]
    names = [key]
    names.extend(field.get("aliases") or [])
    yaml_key = FIRST_CLASS_FIELD_MAP.get(key)
    if yaml_key:
        names.append(yaml_key)
    patterns: list[str] = []
    field_type = field.get("type", "str")
    for name in names:
        esc = re.escape(name)
        if field_type == "int":
            patterns.extend([
                rf"\b{esc}\s*[=:]\s*(\d+)",
                rf"\b{esc}\s+(?:to\s+)?(\d+)",
                rf"\b(?:change|set|update)\s+(?:the\s+)?{esc}\s+(?:to\s+)?(\d+)",
            ])
        elif field_type == "bool":
            patterns.extend([
                rf"\b{esc}\s*[=:]\s*(true|false|yes|no)\b",
                rf"\b{esc}\s+(?:to\s+)?(true|false|yes|no)\b",
            ])
        elif field_type == "period":
            patterns.extend([
                rf"\b{esc}\s*[=:]\s*(\d{{4}}-\d{{2}}-\d{{2}}\s*,\s*\d{{4}}-\d{{2}}-\d{{2}})",
                rf"\b{esc}\s+(?:to\s+)?(\d{{4}}-\d{{2}}-\d{{2}}\s*,\s*\d{{4}}-\d{{2}}-\d{{2}})",
            ])
        elif field_type == "datetime":
            default_hm = field.get("default_hm", "00:00")
            patterns.extend([
                rf"\b{esc}\s*[=:]\s*(\d{{4}}-\d{{2}}-\d{{2}}(?:\s+\d{{1,2}}:\d{{2}})?)",
                rf"\b{esc}\s+(?:to\s+)?(\d{{4}}-\d{{2}}-\d{{2}}(?:\s+\d{{1,2}}:\d{{2}})?)",
            ])
        elif key == "domain_name":
            patterns.extend([
                rf"\b(?:change|set|update)\s+(?:the\s+)?{esc}\s+(?:to\s+)?([A-Za-z0-9_\-]+)",
                rf"\b{esc}\s*[=:]\s*([A-Za-z0-9_\-]+)",
                rf"\b{esc}\s+(?:to\s+)?([A-Za-z0-9_\-]+)",
            ])
        elif key == "experiment_id":
            patterns.extend([
                rf"\b{esc}\s*[=:]\s*([A-Za-z0-9_\-]+)",
                rf"\b{esc}\s+(?:to\s+)?([A-Za-z0-9_\-]+)",
            ])
        elif field_type == "coords_bbox":
            qesc = _quoted_field_name(esc)
            patterns.extend([
                rf"{qesc}\s*[=:]\s*{_OPTIONAL_QUOTES}(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?){_OPTIONAL_QUOTES}",
                rf"\b(?:use|set|update|change)\s+{qesc}\s*[=:]\s*{_OPTIONAL_QUOTES}(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?){_OPTIONAL_QUOTES}",
                rf"\b{esc}\s*[=:]\s*{_OPTIONAL_QUOTES}(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?){_OPTIONAL_QUOTES}",
                rf"\b{esc}\s+(?:to\s+)?{_OPTIONAL_QUOTES}(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?){_OPTIONAL_QUOTES}",
            ])
        elif field_type == "coords_pp":
            qesc = _quoted_field_name(esc)
            patterns.extend([
                rf"{qesc}\s*[=:]\s*{_OPTIONAL_QUOTES}(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?){_OPTIONAL_QUOTES}",
                rf"\b(?:use|set|update|change)\s+{qesc}\s*[=:]\s*{_OPTIONAL_QUOTES}(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?){_OPTIONAL_QUOTES}",
                rf"\b{esc}\s*[=:]\s*{_OPTIONAL_QUOTES}(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?){_OPTIONAL_QUOTES}",
                rf"\b{esc}\s+(?:to\s+)?{_OPTIONAL_QUOTES}(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?){_OPTIONAL_QUOTES}",
            ])
        else:
            value_pat = r"([A-Za-z0-9_\-]+)" if field.get("options") else r"([^\n,;]+?)"
            patterns.extend([
                rf"\b{esc}\s*[=:]\s*{value_pat}",
                rf"\b{esc}\s+(?:to\s+)?{value_pat}",
                rf"\b(?:change|set|update)\s+(?:the\s+)?{esc}\s+(?:to\s+)?{value_pat}",
            ])
    return patterns


def _coerce_field_value(field: dict[str, Any], raw: str) -> Any:
    field_type = field.get("type", "str")
    raw = (raw or "").strip()
    if field_type == "int":
        return int(raw)
    if field_type == "bool":
        return raw.lower() in {"true", "yes", "1"}
    if field_type == "datetime":
        return _normalize_chat_datetime(raw, default_hm=field.get("default_hm", "00:00"))
    if field_type == "model":
        return normalize_hydrological_model(raw)
    if field.get("key") == "forcing_dataset":
        return normalize_forcing_dataset(raw)
    if field.get("key") == "domain_name":
        return normalize_domain_name_value(raw)
    if field.get("key") == "discretization":
        return normalize_discretization_value(raw)
    if field_type == "period":
        return re.sub(r"\s*,\s*", ", ", raw)
    if field_type in {"coords_bbox", "coords_pp"}:
        return _normalize_coord_token(raw)
    options = field.get("options") or []
    if options:
        for opt in options:
            if opt and opt.lower() == raw.lower():
                return opt
    return coerce_scalar_value(raw)


def apply_prompt_literal_config_edits(plan: dict, prompt_text: str) -> dict:
    """
    Extract explicit key=value and common natural-language settings from a planning prompt.
    Safety net when the LLM planner drops or replaces user-specified values.
    """
    if not isinstance(plan, dict) or not prompt_text:
        return plan

    cfg = dict(plan.get("config") or {})
    text = prompt_text
    changed = False

    def set_field(key: str, value: Any) -> None:
        nonlocal changed
        if value is None or (isinstance(value, str) and not value.strip()):
            return
        set_plan_config_value(cfg, key, value)
        changed = True

    patterns_str: list[tuple[str, str]] = [
        ("domain_name", r"\bdomain_name\s+([A-Za-z0-9_\-]+)"),
        ("experiment_id", r"\bexperiment_id\s+([A-Za-z0-9_\-]+)"),
        ("forcing_dataset", r"\bforcing_dataset\s+([A-Za-z0-9_\-]+)"),
        ("domain_def", r"\bdomain_def\s+([A-Za-z0-9_\-]+)"),
        ("discretization", r"\bdiscretization\s+([A-Za-z0-9_\-]+)"),
        ("data_access", r"\bdata_access\s+([A-Za-z0-9_]+)"),
        ("routing_model", r"\brouting\s+model\s+([A-Za-z0-9_\-]+)"),
        ("station_id", r"\b(?:WSC\s+)?station\s+ID\s*[`'\"]?\s*(\d{2}[A-Z]{2}\d{3})[`'\"]?"),
        ("delineation_method", r"\bdelineation\s+method\s+([A-Za-z0-9_]+)"),
        ("DELINEATION_METHOD", r"\bDELINEATION_METHOD\s+([A-Za-z0-9_]+)"),
        ("streamflow_data_provider", r"\b(?:download\s+)?(WSC|USGS|VI|NIWA)\s+streamflow(?:\s+data)?\b"),
        ("domain_def", r"\bdomain\s+definition\s+method\s+(delineate|lumped|point|subset|semidistributed|distributed)"),
        ("discretization", r"\bdiscretization\s+(GRUs?|HRUs?|elevation|landclass|soilclass)"),
    ]
    for key, pat in patterns_str:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1).strip()
        if key == "discretization":
            set_field(key, normalize_discretization_value(raw))
            continue
        if key == "domain_def":
            set_field(key, raw.lower())
            continue
        if key == "domain_name":
            set_field(key, normalize_domain_name_value(raw))
            from server.core.plan_rules import mark_domain_name_confirmed

            cfg = mark_domain_name_confirmed(cfg)
            continue
        if key == "routing_model":
            set_field(key, raw)
            continue
        if key == "streamflow_data_provider":
            set_field(key, raw.upper())
            continue
        set_field(key, raw)

    model_match = re.search(
        r"\bhydrological\s+model\s+(SUMMA|FUSE|VIC|CLM)\b",
        text,
        flags=re.IGNORECASE,
    )
    if model_match:
        set_field("hydrological_model", normalize_hydrological_model(model_match.group(1)))

    if re.search(r"\bcloud\s+data\s+access\b", text, flags=re.IGNORECASE):
        set_field("data_access", "cloud")

    forcing_match = re.search(
        r"\b(?:with\s+)?(ERA5|NLDAS|GLDAS|local)\s+forcing\b",
        text,
        flags=re.IGNORECASE,
    )
    if forcing_match:
        set_field("forcing_dataset", normalize_forcing_dataset(forcing_match.group(1)))

    coord_patterns: list[tuple[str, str]] = [
        ("pour_point_coords", r"\bpour\s+point(?:\s+coords|\s+coordinates)?\s+(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?)"),
        (
            "bounding_box_coords",
            r"\bbounding\s+box(?:\s+coords|\s+coordinates)?\s+"
            r"(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?)",
        ),
        ("pour_point_coords", r"\bpour_point_coords\s+(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?)"),
        (
            "bounding_box_coords",
            r"\bbounding_box_coords\s+(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?)",
        ),
    ]
    for key, pat in coord_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            set_field(key, m.group(1).replace(",", "/").rstrip(".,;"))

    time_patterns: list[tuple[str, str, str]] = [
        ("experiment_time_start", r"\bexperiment\s+time\s+start\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", "01:00"),
        ("experiment_time_end", r"\bexperiment\s+time\s+end\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", "23:00"),
        ("experiment_time_start", r"\bexperiment_time_start\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", "01:00"),
        ("experiment_time_end", r"\bexperiment_time_end\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", "23:00"),
    ]
    for key, pat, default_hm in time_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            set_field(key, _normalize_chat_datetime(m.group(1), default_hm=default_hm))

    period_patterns: list[tuple[str, str]] = [
        ("spinup_period", r"\bspinup\s+period\s+(\d{4}-\d{2}-\d{2}\s*,\s*\d{4}-\d{2}-\d{2})"),
        ("calibration_period", r"\bcalibration\s+period\s+(\d{4}-\d{2}-\d{2}\s*,\s*\d{4}-\d{2}-\d{2})"),
        ("evaluation_period", r"\bevaluation\s+period\s+(\d{4}-\d{2}-\d{2}\s*,\s*\d{4}-\d{2}-\d{2})"),
        ("spinup_period", r"\bspinup_period\s+(\d{4}-\d{2}-\d{2}\s*,\s*\d{4}-\d{2}-\d{2})"),
        ("calibration_period", r"\bcalibration_period\s+(\d{4}-\d{2}-\d{2}\s*,\s*\d{4}-\d{2}-\d{2})"),
        ("evaluation_period", r"\bevaluation_period\s+(\d{4}-\d{2}-\d{2}\s*,\s*\d{4}-\d{2}-\d{2})"),
    ]
    for key, pat in period_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            set_field(key, re.sub(r"\s*,\s*", ", ", m.group(1)))

    int_patterns: list[tuple[str, str]] = [
        ("stream_threshold", r"\bstream\s+threshold\s+([0-9]+(?:\.[0-9]+)?)"),
        ("STREAM_THRESHOLD", r"\bSTREAM_THRESHOLD\s+([0-9]+(?:\.[0-9]+)?)"),
        ("stream_threshold", r"\bstream_threshold\s+([0-9]+(?:\.[0-9]+)?)"),
    ]
    for key, pat in int_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            raw = m.group(1)
            set_field(key, int(float(raw)) if float(raw).is_integer() else float(raw))

    if not changed:
        return plan
    out = dict(plan)
    out["config"] = cfg
    return out


def apply_comprehensive_chat_config_edits(plan: dict, user_message: str) -> dict:
    """Apply config changes from chat using registry patterns and natural-language helpers."""
    if not isinstance(plan, dict) or not user_message:
        return plan
    text = user_message
    cfg = dict(plan.get("config") or {})
    changed = False

    # Natural-language date shortcuts
    date_shortcuts = [
        ("experiment_time_end", [
            r"\b(?:change|set|update)\s+(?:the\s+)?end\s+date\s+to\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)",
            r"\bend\s+date\s+(?:to\s+)?(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)",
            r"\bexperiment\s+end\s+(?:to\s+)?(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)",
        ], "23:00"),
        ("experiment_time_start", [
            r"\b(?:change|set|update)\s+(?:the\s+)?start\s+date\s+to\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)",
            r"\bstart\s+date\s+(?:to\s+)?(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)",
            r"\bexperiment\s+start\s+(?:to\s+)?(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)",
        ], "01:00"),
    ]
    for field_key, patterns, default_hm in date_shortcuts:
        for pat in patterns:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if not m:
                continue
            set_plan_config_value(cfg, field_key, _normalize_chat_datetime(m.group(1), default_hm=default_hm))
            changed = True
            break

    # Natural-language MPI
    mpi_patterns = [
        r"\bnum(?:_)?processes\s+(?:should\s+be\s+)?(\d+)",
        r"\bnumber\s+of\s+process(?:es)?\s+(?:should\s+be|to|=|:)\s*(\d+)",
        r"\buse\s+(\d+)\s+process(?:es)?\b",
    ]
    for pat in mpi_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            set_plan_config_value(cfg, "NUM_PROCESSES", int(m.group(1)))
            changed = True
            break

    # Natural-language hydrological model
    model_names = "|".join(re.escape(m) for m in HYDROLOGICAL_MODEL_OPTIONS if m)
    model_nl = re.search(
        rf"\b(?:use|switch\s+to|change(?:\s+(?:the\s+)?hydrological\s+model)?\s+to|"
        rf"set\s+(?:the\s+)?(?:hydrological\s+)?model\s+to)\s+"
        rf"({model_names})\b",
        text,
        flags=re.IGNORECASE,
    )
    if model_nl:
        set_plan_config_value(cfg, "hydrological_model", normalize_hydrological_model(model_nl.group(1)))
        changed = True
    elif re.search(
        r"\b(?:use|run)\s+(" + "|".join(m for m in HYDROLOGICAL_MODEL_OPTIONS if m) + r")\b",
        text,
        re.I,
    ):
        extracted = _extract_hydrological_model(text)
        if extracted:
            set_plan_config_value(cfg, "hydrological_model", extracted)
            changed = True

    # Natural-language forcing dataset
    forcing_pattern = "|".join(re.escape(option) for option in FORCING_DATASET_OPTIONS)
    forcing_nl = re.search(
        rf"\b(?:use|switch\s+to|set)\s+({forcing_pattern}|local)\s+(?:forcing|forcings)?\b",
        text,
        flags=re.IGNORECASE,
    )
    if forcing_nl:
        set_plan_config_value(cfg, "forcing_dataset", normalize_forcing_dataset(forcing_nl.group(1)))
        changed = True

    # Natural-language domain definition
    domain_nl = re.search(
        r"\b(?:use|switch\s+to|set)\s+(delineate|lumped|point|subset)\s+(?:domain)?\b",
        text,
        flags=re.IGNORECASE,
    )
    if domain_nl:
        set_plan_config_value(cfg, "domain_def", domain_nl.group(1).lower())
        changed = True

    # Natural-language domain name (e.g. "use BOWRiver3 as domain name")
    domain_name_nl = re.search(
        r"\buse\s+([A-Za-z0-9_\-]+)\s+as\s+(?:the\s+)?domain(?:\s+name|_name)\b",
        text,
        flags=re.IGNORECASE,
    )
    if domain_name_nl:
        set_plan_config_value(cfg, "domain_name", normalize_domain_name_value(domain_name_nl.group(1)))
        changed = True

    # Station ID natural language
    station_nl = re.search(
        r"\b(?:station(?:\s+id)?|gauging\s+station)\s+(?:to\s+)?([A-Za-z0-9_\-]+)\b",
        text,
        flags=re.IGNORECASE,
    )
    if station_nl:
        set_plan_config_value(cfg, "station_id", station_nl.group(1).strip())
        changed = True

    # Coordinates
    pp = _extract_pour_point_coords_from_text(text)
    if pp:
        set_plan_config_value(cfg, "pour_point_coords", pp)
        changed = True
    bbox = _extract_bbox_coords_from_text(text)
    if bbox:
        set_plan_config_value(cfg, "bounding_box_coords", bbox)
        changed = True

    # Registry explicit patterns for every field
    for field in CHAT_EDITABLE_FIELDS:
        for pat in _field_lookup_patterns(field):
            m = re.search(pat, text, flags=re.IGNORECASE)
            if not m:
                continue
            try:
                value = _coerce_field_value(field, m.group(1))
            except Exception:
                continue
            set_plan_config_value(cfg, field["key"], value)
            changed = True
            break

    if not changed:
        return plan
    domain = _s(cfg.get("domain_name"))
    if domain:
        from server.core.plan_rules import apply_user_provided_domain_name

        cfg = apply_user_provided_domain_name(cfg, domain)
    out = dict(plan)
    out["config"] = cfg
    return out


def _build_config_alias_to_canonical() -> dict[str, str]:
    mapping: dict[str, str] = {
        "DATA_ACCESS": "data_access",
        "data_access": "data_access",
    }
    for field in CHAT_EDITABLE_FIELDS:
        canonical = field["key"]
        mapping[canonical] = canonical
        for alias in field.get("aliases") or []:
            mapping[alias] = canonical
        for mirror in field.get("mirror") or []:
            mapping[mirror] = canonical
        yaml_key = FIRST_CLASS_FIELD_MAP.get(canonical)
        if yaml_key:
            mapping[yaml_key] = canonical
    for planner_key, yaml_key in FIRST_CLASS_FIELD_MAP.items():
        mapping.setdefault(planner_key, planner_key)
        mapping.setdefault(yaml_key, planner_key)
    return mapping


CONFIG_ALIAS_TO_CANONICAL = _build_config_alias_to_canonical()


def canonical_config_key(key: str) -> str:
    return CONFIG_ALIAS_TO_CANONICAL.get(key) or CONFIG_ALIAS_TO_CANONICAL.get(key.upper()) or key


def normalize_config_compare_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else float(value)
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"true", "yes"}:
        return True
    if text.lower() in {"false", "no"}:
        return False
    try:
        num = float(text)
        return int(num) if num.is_integer() else num
    except Exception:
        return text


def canonical_plan_config(cfg: dict | None) -> dict[str, Any]:
    """Merge plan.config + extra_config into one value per canonical field."""
    cfg = dict(cfg or {})
    extra = cfg.get("extra_config")
    merged: dict[str, Any] = {}
    if isinstance(extra, dict):
        merged.update(extra)
    merged.update({k: v for k, v in cfg.items() if k != "extra_config"})
    canonical: dict[str, Any] = {}
    for key, value in merged.items():
        canon = canonical_config_key(key)
        if normalize_config_compare_value(value) is None:
            continue
        if canon == "discretization" and isinstance(value, str):
            value = normalize_discretization_value(value)
        elif canon == "routing_model" and isinstance(value, str):
            value = normalize_routing_model_value(value)
        canonical[canon] = value
    return canonical


_YAML_TO_PLANNER_KEY = {yaml_key: planner_key for planner_key, yaml_key in FIRST_CLASS_FIELD_MAP.items()}

_CANONICAL_TO_STORAGE_KEY: dict[str, str] = {
    "NUM_PROCESSES": "num_processes",
    "MPI_PROCESSES": "mpi_processes",
    "NUMBER_OF_ITERATIONS": "iterations",
    "POPULATION_SIZE": "population_size",
    "STATION_ID": "station_id",
    "ROUTING_MODEL": "routing_model",
    "DATA_ACCESS": "data_access",
    "DOMAIN_DEFINITION_METHOD": "domain_def",
    "DOMAIN_DISCRETIZATION": "discretization",
    "PET_METHOD": "pet_method",
    "SPINUP_PERIOD": "spinup_period",
    "CALIBRATION_PERIOD": "calibration_period",
    "EVALUATION_PERIOD": "evaluation_period",
    "ITERATIVE_OPTIMIZATION_ALGORITHM": "iterative_optimization_algorithm",
    "OPTIMIZATION_METRIC": "optimization_metric",
    "OPTIMIZATION_TARGET": "optimization_target",
    "CALIBRATION_TIMESTEP": "calibration_timestep",
    "DOWNLOAD_SNOTEL": "download_snotel",
    "SNOTEL_STATION": "snotel_station",
    "PARAMS_TO_CALIBRATE": "params_to_calibrate",
}

PLAN_TOP_LEVEL_CONFIG_KEYS: set[str] = set(CHAT_EDITABLE_KEYS)
PLAN_TOP_LEVEL_CONFIG_KEYS |= set(FIRST_CLASS_FIELD_MAP.keys())
PLAN_TOP_LEVEL_CONFIG_KEYS |= {
    "data_access",
    "delineation_method",
    "stream_threshold",
    "num_processes",
    "mpi_processes",
    "routing_model",
    "station_id",
    "streamflow_data_provider",
    "pet_method",
    "spinup_period",
    "calibration_period",
    "evaluation_period",
    "iterative_optimization_algorithm",
    "optimization_metric",
    "optimization_target",
    "calibration_timestep",
    "iterations",
    "population_size",
    "download_snotel",
    "snotel_station",
    "params_to_calibrate",
}


def preferred_plan_storage_key(key: str) -> str:
    """Planner-facing config key (snake_case); YAML mirrors are not stored in plan JSON."""
    canon = canonical_config_key(key)
    if canon in _CANONICAL_TO_STORAGE_KEY:
        return _CANONICAL_TO_STORAGE_KEY[canon]
    if canon in _YAML_TO_PLANNER_KEY:
        return _YAML_TO_PLANNER_KEY[canon]
    if key in FIRST_CLASS_FIELD_MAP:
        return key
    return canon


def compact_plan_config(cfg: dict | None) -> dict:
    """One planner key per setting; non-standard keys live under extra_config."""
    merged = canonical_plan_config(cfg)
    preferred: dict[str, Any] = {}
    overflow: dict[str, Any] = {}

    for raw_key, value in merged.items():
        if normalize_config_compare_value(value) is None:
            continue
        storage_key = preferred_plan_storage_key(raw_key)
        if storage_key in preferred:
            continue
        if storage_key in PLAN_TOP_LEVEL_CONFIG_KEYS:
            preferred[storage_key] = value
        else:
            overflow[storage_key] = value

    for key in list(overflow.keys()):
        if key in preferred:
            overflow.pop(key, None)

    if overflow:
        preferred["extra_config"] = overflow
    return preferred


def normalize_plan_for_storage(plan: dict | None) -> dict:
    """Compact plan.config for session state, plan.json, and the JSON editor."""
    if not isinstance(plan, dict):
        return {}
    out = dict(plan)
    out["config"] = compact_plan_config(out.get("config"))
    return out


def config_keys_mentioned_in_chat(user_message: str) -> set[str]:
    """Fields the user message explicitly targets (regex / natural-language parsers)."""
    if not user_message.strip():
        return set()
    probe = apply_comprehensive_chat_config_edits({"config": {}}, user_message)
    cfg = probe.get("config") or {}
    mentioned: set[str] = set()
    for field in CHAT_EDITABLE_FIELDS:
        canon = field["key"]
        candidates = {canon}
        candidates.update(field.get("aliases") or [])
        candidates.update(field.get("mirror") or [])
        yaml_key = FIRST_CLASS_FIELD_MAP.get(canon)
        if yaml_key:
            candidates.add(yaml_key)
        if any(candidate in cfg for candidate in candidates):
            mentioned.add(canon)
    return mentioned


def meaningful_config_changes(
    old_cfg: dict | None,
    new_cfg: dict | None,
    *,
    user_message: str = "",
) -> list[tuple[str, Any, Any]]:
    """Return canonical config changes relevant to the user request (skip LLM/normalization noise)."""
    old_canon = canonical_plan_config(old_cfg)
    new_canon = canonical_plan_config(new_cfg)
    requested = config_keys_mentioned_in_chat(user_message)
    changes: list[tuple[str, Any, Any]] = []
    for key in sorted(set(old_canon) | set(new_canon)):
        old_val = normalize_config_compare_value(old_canon.get(key))
        new_val = normalize_config_compare_value(new_canon.get(key))
        if old_val == new_val:
            continue
        in_old = old_val is not None
        in_new = new_val is not None
        if key in requested:
            changes.append((key, old_canon.get(key), new_canon.get(key)))
            continue
        # Ignore keys dropped or newly injected by normalization unless the user asked.
        if in_old and in_new:
            changes.append((key, old_canon.get(key), new_canon.get(key)))
    return changes


def _format_change_value(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "not set"
    return str(value).strip()


def summarize_plan_changes_for_chat(
    before: dict,
    after: dict,
    *,
    user_message: str = "",
) -> str:
    """Human-readable plan diff for chat: steps added/removed and meaningful config edits only."""
    old_steps = list(before.get("steps") or [])
    new_steps = list(after.get("steps") or [])
    added = [step for step in new_steps if step not in old_steps]
    removed = [step for step in old_steps if step not in new_steps]
    lines: list[str] = []
    if added:
        lines.append("Added steps: " + ", ".join(f"`{step}`" for step in added))
    if removed:
        lines.append("Removed steps: " + ", ".join(f"`{step}`" for step in removed))

    cfg_changes = meaningful_config_changes(
        before.get("config") or {},
        after.get("config") or {},
        user_message=user_message,
    )
    if cfg_changes:
        rendered = ", ".join(
            f"`{key}`: {_format_change_value(old)} → {_format_change_value(new)}"
            for key, old, new in cfg_changes
        )
        lines.append("Config changed: " + rendered)
    if not lines:
        return ""
    return "**Plan changes:** " + " | ".join(lines)


def refinement_prompt_field_summary() -> str:
    """Short field list for the plan refinement prompt."""
    lines = [
        "Editable plan.config fields (use exact keys; mirror UI):",
        "- domain_name, experiment_id, hydrological_model "
        f"({', '.join(m for m in HYDROLOGICAL_MODEL_OPTIONS if m)})",
        f"- domain_def ({', '.join(DOMAIN_DEF_OPTIONS)}), forcing_dataset "
        f"({', '.join(FORCING_DATASET_OPTIONS)})",
        "- pour_point_coords (lat/lon), bounding_box_coords (lat/lon/lat/lon)",
        "- experiment_time_start, experiment_time_end (YYYY-MM-DD HH:MM)",
        "- NUM_PROCESSES, MPI_PROCESSES",
        f"- streamflow_data_provider ({', '.join(STREAMFLOW_PROVIDER_OPTIONS)}), station_id",
        f"- routing_model, pet_method ({', '.join(PET_METHOD_OPTIONS)})",
        "- spinup_period, calibration_period, evaluation_period (YYYY-MM-DD, YYYY-MM-DD)",
        f"- iterative_optimization_algorithm ({', '.join(CALIBRATION_ALGORITHMS)})",
        f"- optimization_metric ({', '.join(CALIBRATION_METRICS)}), "
        f"optimization_target ({', '.join(CALIBRATION_TARGETS)})",
        f"- calibration_timestep ({', '.join(CALIBRATION_TIMESTEPS)}), "
        "iterations, population_size",
        "- discretization, download_snotel, snotel_station, data_access, params_to_calibrate",
    ]
    return "\n".join(lines)
