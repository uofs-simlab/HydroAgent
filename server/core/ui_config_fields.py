"""Registry of UI/planner config fields and chat-driven config edit helpers."""

from __future__ import annotations

import re
from typing import Any

from server.core.parameter_registry import FIRST_CLASS_FIELD_MAP, coerce_scalar_value

HYDROLOGICAL_MODEL_OPTIONS = ["", "SUMMA", "FUSE", "GR", "HBV", "MESH", "HYPE", "ngen", "TOPMODEL"]
DOMAIN_DEF_OPTIONS = ["delineate", "lumped", "point", "subset"]
FORCING_DATASET_OPTIONS = ["ERA5", "RDRS", "MERRA2", "NLDAS", "Custom"]
STREAMFLOW_PROVIDER_OPTIONS = ["WSC", "USGS", "VI", "NIWA"]
PET_METHOD_OPTIONS = ["oudin", "hamon", "hargreaves"]
CALIBRATION_ALGORITHMS = ["DE", "DDS", "PSO", "NSGA-II", "SCE-UA", "ADAM"]
CALIBRATION_METRICS = ["KGE", "NSE", "RMSE", "Bias"]
CALIBRATION_TARGETS = ["streamflow", "swe", "snow_depth", "et", "groundwater"]
CALIBRATION_TIMESTEPS = ["native", "hourly", "daily"]

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
    if value.lower() == "ngen":
        return "ngen"
    return value.upper()


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


def set_plan_config_value(cfg: dict, key: str, value: Any) -> None:
    """Write a value to plan.config using canonical key and mirrors."""
    if value is None or value == "":
        cfg.pop(key, None)
        return
    cfg[key] = value
    meta = next((f for f in CHAT_EDITABLE_FIELDS if f["key"] == key), None)
    if meta:
        for alias in meta.get("aliases") or []:
            cfg[alias] = value
        for mirror in meta.get("mirror") or []:
            cfg[mirror] = value
    yaml_key = FIRST_CLASS_FIELD_MAP.get(key)
    if yaml_key:
        cfg[yaml_key] = value
    if key == "NUM_PROCESSES":
        cfg["num_processes"] = value
    if key == "population_size":
        cfg["POPULATION_SIZE"] = value
    if key == "iterations":
        cfg["NUMBER_OF_ITERATIONS"] = value


def _normalize_chat_datetime(value: str, *, default_hm: str) -> str:
    value = (value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return f"{value} {default_hm}"
    return value


def _extract_hydrological_model(text: str) -> str | None:
    model_map = {
        "SUMMA": "SUMMA",
        "FUSE": "FUSE",
        "GR": "GR",
        "HBV": "HBV",
        "MESH": "MESH",
        "HYPE": "HYPE",
        "NGEN": "ngen",
        "TOPMODEL": "TOPMODEL",
    }
    upper = text.upper()
    for key, value in model_map.items():
        if re.search(rf"\b{re.escape(key)}\b", upper):
            return value
    return None


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
    if field_type == "period":
        return re.sub(r"\s*,\s*", ", ", raw)
    options = field.get("options") or []
    if options:
        for opt in options:
            if opt and opt.lower() == raw.lower():
                return opt
    return coerce_scalar_value(raw)


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
    model_nl = re.search(
        r"\b(?:use|switch\s+to|change(?:\s+(?:the\s+)?hydrological\s+model)?\s+to|"
        r"set\s+(?:the\s+)?(?:hydrological\s+)?model\s+to)\s+"
        r"(SUMMA|FUSE|GR|HBV|MESH|HYPE|ngen|NGEN|TOPMODEL)\b",
        text,
        flags=re.IGNORECASE,
    )
    if model_nl:
        set_plan_config_value(cfg, "hydrological_model", normalize_hydrological_model(model_nl.group(1)))
        changed = True
    elif re.search(r"\b(?:use|run)\s+(SUMMA|FUSE|GR|HBV|MESH|HYPE|ngen|NGEN|TOPMODEL)\b", text, re.I):
        extracted = _extract_hydrological_model(text)
        if extracted:
            set_plan_config_value(cfg, "hydrological_model", extracted)
            changed = True

    # Natural-language forcing dataset
    forcing_nl = re.search(
        r"\b(?:use|switch\s+to|set)\s+(ERA5|RDRS|MERRA2|NLDAS|Custom)\s+(?:forcing|forcings)?\b",
        text,
        flags=re.IGNORECASE,
    )
    if forcing_nl:
        val = forcing_nl.group(1).upper() if forcing_nl.group(1).lower() != "custom" else "Custom"
        set_plan_config_value(cfg, "forcing_dataset", val)
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
    pp = re.search(
        r"\bpour[_\s-]?point(?:\s+coords)?\s+(?:to\s+)?(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if pp:
        set_plan_config_value(cfg, "pour_point_coords", pp.group(1).replace(",", "/"))
        changed = True
    bbox = re.search(
        r"\bbounding[_\s-]?box(?:\s+coords)?\s+(?:to\s+)?"
        r"(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if bbox:
        set_plan_config_value(cfg, "bounding_box_coords", bbox.group(1).replace(",", "/"))
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
        canonical[canon] = value
    return canonical


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
