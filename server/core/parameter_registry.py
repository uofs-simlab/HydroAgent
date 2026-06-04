from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml


ASSISTANT_BASE = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ASSISTANT_BASE / "configs" / "config_template.yaml"


FIRST_CLASS_FIELD_MAP = {
    "domain_name": "DOMAIN_NAME",
    "experiment_id": "EXPERIMENT_ID",
    "pour_point_coords": "POUR_POINT_COORDS",
    "bounding_box_coords": "BOUNDING_BOX_COORDS",
    "domain_def": "DOMAIN_DEFINITION_METHOD",
    "discretization": "DOMAIN_DISCRETIZATION",
    "hydrological_model": "HYDROLOGICAL_MODEL",
    "forcing_dataset": "FORCING_DATASET",
    "routing_model": "ROUTING_MODEL",
    "experiment_time_start": "EXPERIMENT_TIME_START",
    "experiment_time_end": "EXPERIMENT_TIME_END",
    "spinup_period": "SPINUP_PERIOD",
    "calibration_period": "CALIBRATION_PERIOD",
    "evaluation_period": "EVALUATION_PERIOD",
    "optimization_target": "OPTIMIZATION_TARGET",
    "optimization_metric": "OPTIMIZATION_METRIC",
    "calibration_timestep": "CALIBRATION_TIMESTEP",
    "iterative_optimization_algorithm": "ITERATIVE_OPTIMIZATION_ALGORITHM",
    "iterations": "NUMBER_OF_ITERATIONS",
    "population_size": "POPULATION_SIZE",
    "num_processes": "NUM_PROCESSES",
    "mpi_processes": "MPI_PROCESSES",
    "download_snotel": "DOWNLOAD_SNOTEL",
    "snotel_station": "SNOTEL_STATION",
    "observations_path": "OBSERVATIONS_PATH",
    "params_to_calibrate": "PARAMS_TO_CALIBRATE",
}


def load_template_parameters(template_path: Path = TEMPLATE_PATH) -> set[str]:
    cfg = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        return set()
    return set(str(k) for k in cfg.keys())


def canonical_yaml_key(key: str) -> str:
    """
    Convert first-class planner keys to SYMFLUENCE YAML keys.
    Keep native uppercase SYMFLUENCE keys unchanged.
    """
    return FIRST_CLASS_FIELD_MAP.get(key, key)


def is_known_symfluence_parameter(key: str, template_keys: set[str] | None = None) -> bool:
    template_keys = template_keys or load_template_parameters()
    return canonical_yaml_key(key) in template_keys


def coerce_scalar_value(raw: str) -> Any:
    raw = raw.strip().strip("'\"").rstrip(".")

    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if raw.lower() in {"none", "null"}:
        return None

    try:
        if "." not in raw and "e" not in raw.lower():
            return int(raw)
    except Exception:
        pass

    try:
        return float(raw)
    except Exception:
        pass

    return raw
