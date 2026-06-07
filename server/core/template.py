from __future__ import annotations
# Layout note: minor UI spacing tweaks.

from pathlib import Path
from typing import Any, Dict
import yaml


# Map normalized assistant/spec fields -> SYMFLUENCE YAML keys
FIELD_MAP = {
    # Paths
    "symfluence_code_dir": "SYMFLUENCE_CODE_DIR",
    "symfluence_data_dir": "SYMFLUENCE_DATA_DIR",

    # Domain / experiment
    "domain_name": "DOMAIN_NAME",
    "experiment_id": "EXPERIMENT_ID",
    "pour_point_coords": "POUR_POINT_COORDS",
    "bounding_box_coords": "BOUNDING_BOX_COORDS",
    "domain_def": "DOMAIN_DEFINITION_METHOD",
    "discretization": "DOMAIN_DISCRETIZATION",
    "delineation_method": "DELINEATION_METHOD",
    "stream_threshold": "STREAM_THRESHOLD",
    "min_hru_size": "MIN_HRU_SIZE",
    "min_gru_size": "MIN_GRU_SIZE",

    # Time windows
    "experiment_time_start": "EXPERIMENT_TIME_START",
    "experiment_time_end": "EXPERIMENT_TIME_END",
    "spinup_period": "SPINUP_PERIOD",
    "calibration_period": "CALIBRATION_PERIOD",
    "evaluation_period": "EVALUATION_PERIOD",

    # Model / forcing
    "hydrological_model": "HYDROLOGICAL_MODEL",
    "forcing_dataset": "FORCING_DATASET",
    "streamflow_data_provider": "STREAMFLOW_DATA_PROVIDER",
    "station_id": "STATION_ID",
    "routing_model": "ROUTING_MODEL",
    "pet_method": "PET_METHOD",
    "spinup_period": "SPINUP_PERIOD",
    "calibration_period": "CALIBRATION_PERIOD",
    "evaluation_period": "EVALUATION_PERIOD",

    # Processing / data access
    "data_access": "DATA_ACCESS",
    "gistool_dataset_root": "GISTOOL_DATASET_ROOT",
    "tool_cache": "TOOL_CACHE",
    "easymore_cache": "EASYMORE_CACHE",
    "cluster_json": "CLUSTER_JSON",
    "force_rerun": "FORCE_RERUN",

    # Compute / logging
    "mpi_processes": "MPI_PROCESSES",
    "num_processes": "NUM_PROCESSES",
    "log_level": "LOG_LEVEL",
    "log_to_file": "LOG_TO_FILE",
    "log_format": "LOG_FORMAT",

    # Observations / SNOTEL
    "download_snotel": "DOWNLOAD_SNOTEL",
    "snotel_station": "SNOTEL_STATION",
    "observations_path": "OBSERVATIONS_PATH",
    "optimization_target": "OPTIMIZATION_TARGET",
    "optimization_metric": "OPTIMIZATION_METRIC",

    # Calibration
    "calibration_timestep": "CALIBRATION_TIMESTEP",
    "iterative_optimization_algorithm": "ITERATIVE_OPTIMIZATION_ALGORITHM",
    "iterations": "NUMBER_OF_ITERATIONS",
    "population_size": "POPULATION_SIZE",
    "params_to_calibrate": "PARAMS_TO_CALIBRATE",
}


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def dump_yaml(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)


def apply_spec_to_template(template: Dict[str, Any], spec_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply assistant/spec config fields to the SYMFLUENCE YAML template.

    Supports:
    1. normalized assistant keys via FIELD_MAP
       e.g. hydrological_model -> HYDROLOGICAL_MODEL

    2. native SYMFLUENCE uppercase keys passed through directly
       e.g. DOWNLOAD_SNOTEL, SNOTEL_STATION, POPULATION_SIZE
    """
    out = dict(template)

    for spec_key, value in spec_dict.items():
        if value is None:
            continue

        # Case 1: normalized assistant key
        yaml_key = FIELD_MAP.get(spec_key)
        if yaml_key:
            out[yaml_key] = value
            continue

        # Case 2: native SYMFLUENCE uppercase key
        if isinstance(spec_key, str) and spec_key.isupper():
            out[spec_key] = value
            continue

        # Otherwise ignore unknown lowercase/mixed-case helper fields
        # to avoid polluting the SYMFLUENCE config.
        continue

    return out


ROUTING_CALIBRATION_PARAMS = frozenset(
    {
        "routingGammaShape",
        "routingGammaScale",
        "velo",
        "diff",
    }
)


def params_to_calibrate_string(value: Any) -> str:
    """SYMFLUENCE expects comma-separated PARAMS_TO_CALIBRATE, not YAML lists."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = [item.strip() for item in str(value).split(",") if item.strip()]
    return ",".join(items)


def normalize_params_to_calibrate(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Convert list-style calibration params and split routing basin params."""
    raw = cfg.get("PARAMS_TO_CALIBRATE")
    if raw is None:
        return cfg

    if isinstance(raw, (list, tuple)):
        items = [str(item).strip() for item in raw if str(item).strip()]
    elif isinstance(raw, str):
        items = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        return cfg

    summa_params = [item for item in items if item not in ROUTING_CALIBRATION_PARAMS]
    basin_params = [item for item in items if item in ROUTING_CALIBRATION_PARAMS]

    if summa_params:
        cfg["PARAMS_TO_CALIBRATE"] = ",".join(summa_params)
    else:
        cfg.pop("PARAMS_TO_CALIBRATE", None)

    if basin_params:
        cfg["BASIN_PARAMS_TO_CALIBRATE"] = ",".join(basin_params)

    return cfg


def spec_key_to_yaml_key(key: str) -> str | None:
    if not isinstance(key, str) or not key:
        return None
    if key in FIELD_MAP:
        return FIELD_MAP[key]
    if key.isupper():
        return key
    return None


def strip_duplicate_lowercase_keys(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Remove planner lowercase duplicates that should only exist as SYMFLUENCE keys."""
    for key in list(cfg.keys()):
        if not isinstance(key, str) or key == key.upper():
            continue
        yaml_key = spec_key_to_yaml_key(key)
        if yaml_key and yaml_key in cfg:
            cfg.pop(key, None)
    return cfg


def sync_legacy_discretization_key(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Template uses DOMAIN_DISCRETIZATION; SYMFLUENCE requires SUB_GRID_DISCRETIZATION."""
    if cfg.get("SUB_GRID_DISCRETIZATION") in (None, "", "default"):
        discretization = cfg.get("DOMAIN_DISCRETIZATION")
        if discretization not in (None, "", "default"):
            cfg["SUB_GRID_DISCRETIZATION"] = discretization
    return cfg


def finalize_symfluence_config(cfg: Dict[str, Any], spec: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Last-mile cleanup before writing config.yaml for SYMFLUENCE CLI validation."""
    _ = spec
    cfg = normalize_params_to_calibrate(cfg)
    cfg = sync_legacy_discretization_key(cfg)
    cfg = strip_duplicate_lowercase_keys(cfg)
    return cfg


def render_config_from_spec(
    spec_dict: Dict[str, Any],
    template_path: Path,
    out_path: Path,
) -> Path:
    template = load_yaml(template_path)
    cfg = apply_spec_to_template(template, spec_dict)
    dump_yaml(cfg, out_path)
    return out_path