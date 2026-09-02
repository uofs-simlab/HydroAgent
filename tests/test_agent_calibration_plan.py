from server.core.plan_rules import (
    WORKFLOW_PLAN_MODE_CALIBRATION,
    merge_domain_config_from_simulation_plan,
    merge_simulation_steps_into_calibration_plan,
    normalize_local_workflow_plan,
    strip_agent_calibration_config_unless_in_prompt,
)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "CalibHydroAgent"))


def test_strip_agent_calibration_config_when_not_in_prompt():
    plan = {
        "workflow_plan_mode": WORKFLOW_PLAN_MODE_CALIBRATION,
        "config": {
            "domain_name": "Experiment05",
            "station_id": "05BB001",
            "optimization_metric": "KGE",
            "iterative_optimization_algorithm": "DE",
            "iterations": "50",
            "params_to_calibrate": "k_soil",
        },
        "steps": ["process_observed_data", "calibrate_model"],
    }
    out = strip_agent_calibration_config_unless_in_prompt(plan, "run summa for 2023/05/12 to 2023/06/23")
    cfg = out["config"]
    assert cfg.get("station_id") == "05BB001"
    assert "optimization_metric" not in cfg
    assert "iterative_optimization_algorithm" not in cfg
    assert "iterations" not in cfg
    assert "params_to_calibrate" not in cfg


def test_strip_agent_calibration_keeps_prompt_explicit_fields():
    plan = {
        "config": {
            "domain_name": "Experiment05",
            "optimization_metric": "NSE",
            "iterative_optimization_algorithm": "DE",
            "iterations": "25",
        }
    }
    prompt = "Calibrate streamflow with NSE using DE 25 iterations"
    out = strip_agent_calibration_config_unless_in_prompt(plan, prompt)
    cfg = out["config"]
    assert cfg.get("optimization_metric") == "NSE"
    assert cfg.get("iterative_optimization_algorithm") == "DE"
    assert cfg.get("iterations") == "25"


def test_merge_domain_config_from_simulation_plan():
    sim = {
        "config": {
            "domain_name": "Experiment05",
            "experiment_id": "exp_001",
            "pour_point_coords": "51.2/-115.4",
            "experiment_time_start": "2023-05-12 01:00",
        }
    }
    cal = {"config": {"station_id": "05BB001"}}
    out = merge_domain_config_from_simulation_plan(cal, sim)
    cfg = out["config"]
    assert cfg["domain_name"] == "Experiment05"
    assert cfg["experiment_id"] == "exp_001"
    assert cfg["pour_point_coords"] == "51.2/-115.4"
    assert cfg["station_id"] == "05BB001"


def test_merge_simulation_steps_into_calibration_plan():
    sim = {
        "steps": [
            "validate_config",
            "define_domain",
            "discretize_domain",
            "acquire_forcings",
            "model_agnostic_preprocessing",
            "run_model",
        ]
    }
    cal = {"steps": ["validate_config", "run_model", "calibrate_model"]}
    out = merge_simulation_steps_into_calibration_plan(cal, sim)
    assert out["steps"].index("define_domain") < out["steps"].index("run_model")
    assert "discretize_domain" in out["steps"]
    assert "acquire_forcings" in out["steps"]
    assert "model_agnostic_preprocessing" in out["steps"]
    assert "calibrate_model" in out["steps"]


def test_calibration_normalize_keeps_and_restores_simulation_setup_steps():
    from unittest.mock import patch

    plan = {
        "workflow_plan_mode": WORKFLOW_PLAN_MODE_CALIBRATION,
        "steps": ["validate_config", "run_model"],
        "config": {
            "domain_name": "Experiment06",
            "domain_def": "delineate",
            "hydrological_model": "SUMMA",
            "routing_model": "mizuRoute",
        },
    }
    with patch("server.core.plan_rules.domain_has_complete_local_workflow", return_value=True), patch(
        "server.core.plan_rules.domain_has_local_summa_forcing", return_value=True
    ):
        out = normalize_local_workflow_plan(
            plan,
            "",
            data_dir="/tmp",
            workflow_plan_mode=WORKFLOW_PLAN_MODE_CALIBRATION,
            skip_workflow_step_restore=True,
        )
    assert "define_domain" in out["steps"]
    assert "discretize_domain" in out["steps"]
    assert "acquire_forcings" in out["steps"]
    assert "model_agnostic_preprocessing" in out["steps"]
    assert "process_observed_data" in out["steps"]
    assert "calibrate_model" in out["steps"]
