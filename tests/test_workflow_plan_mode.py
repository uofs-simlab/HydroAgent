from unittest.mock import patch

from server.core.plan_rules import (
    WORKFLOW_PLAN_MODE_CALIBRATION,
    WORKFLOW_PLAN_MODE_SIMULATION,
    ensure_calibration_workflow_steps,
    is_calibration_workflow_plan,
    is_simulation_workflow_plan,
    normalize_local_workflow_plan,
    strip_calibration_from_plan,
)


def test_strip_calibration_from_simulation_plan():
    plan = {
        "workflow_plan_mode": WORKFLOW_PLAN_MODE_SIMULATION,
        "steps": ["validate_config", "run_model", "calibrate_model", "process_observed_data"],
        "config": {
            "domain_name": "Experiment04",
            "station_id": "05BB001",
            "calibration_period": "2022-04-01, 2022-05-01",
            "optimization_metric": "KGE",
        },
    }
    out = strip_calibration_from_plan(plan, "")
    assert "calibrate_model" not in out["steps"]
    assert "process_observed_data" not in out["steps"]
    assert "run_model" in out["steps"]
    assert "station_id" not in out["config"]
    assert "calibration_period" not in out["config"]


def test_calibration_plan_adds_steps_and_keeps_station():
    from unittest.mock import patch

    plan = {
        "workflow_plan_mode": WORKFLOW_PLAN_MODE_CALIBRATION,
        "steps": ["validate_config", "run_model"],
        "config": {
            "domain_name": "Experiment04",
            "pour_point_coords": "51.178/-115.579",
            "experiment_time_start": "2022-04-01 01:00",
            "experiment_time_end": "2022-05-26 01:00",
        },
    }

    def fake_resolve(provider, pour, **kwargs):
        return ("05BB001", "note")

    with patch(
        "server.core.station_resolver.resolve_station_near_pour_point",
        side_effect=fake_resolve,
    ):
        out = normalize_local_workflow_plan(
            plan,
            "",
            workflow_plan_mode=WORKFLOW_PLAN_MODE_CALIBRATION,
            skip_workflow_step_restore=True,
        )

    assert is_calibration_workflow_plan(out)
    assert "process_observed_data" in out["steps"]
    assert "calibrate_model" in out["steps"]
    assert out["config"].get("station_id") == "05BB001"


def test_simulation_normalize_strips_calibration_fields():
    plan = {
        "steps": ["validate_config", "run_model", "calibrate_model"],
        "config": {
            "domain_name": "Experiment04",
            "station_id": "05BA006",
            "iterations": 50,
        },
    }
    out = normalize_local_workflow_plan(
        plan,
        "",
        workflow_plan_mode=WORKFLOW_PLAN_MODE_SIMULATION,
        skip_workflow_step_restore=True,
    )
    assert is_simulation_workflow_plan(out)
    assert "calibrate_model" not in out["steps"]
    assert "station_id" not in out["config"]
    assert "iterations" not in out["config"]


def test_ensure_calibration_workflow_steps_inserts_missing():
    plan = {"steps": ["validate_config", "run_model"], "config": {}}
    out = ensure_calibration_workflow_steps(plan, "")
    assert out["steps"].index("process_observed_data") < out["steps"].index("calibrate_model")


def test_simulation_keeps_domain_steps_when_local_artifacts_exist():
    plan = {
        "workflow_plan_mode": WORKFLOW_PLAN_MODE_SIMULATION,
        "steps": [
            "validate_config",
            "define_domain",
            "discretize_domain",
            "acquire_forcings",
            "run_model",
        ],
        "config": {
            "domain_name": "Experiment06",
            "experiment_id": "exp_001",
            "domain_def": "delineate",
            "hydrological_model": "SUMMA",
            "routing_model": "mizuRoute",
        },
    }
    with patch("server.core.plan_rules.domain_has_complete_local_workflow", return_value=True), patch(
        "server.core.plan_rules.domain_has_local_summa_forcing", return_value=True
    ), patch("server.core.plan_rules.domain_name_needs_user_input", return_value=False), patch(
        "server.core.plan_rules.is_weak_domain_name", return_value=False
    ):
        out = normalize_local_workflow_plan(
            plan,
            "",
            data_dir="/tmp",
            workflow_plan_mode=WORKFLOW_PLAN_MODE_SIMULATION,
            skip_workflow_step_restore=True,
        )
    assert "define_domain" in out["steps"]
    assert "discretize_domain" in out["steps"]
    assert "acquire_forcings" in out["steps"]
    assert "run_model" in out["steps"]


def test_simulation_restores_omitted_setup_steps():
    plan = {
        "workflow_plan_mode": WORKFLOW_PLAN_MODE_SIMULATION,
        "steps": ["validate_config", "run_model"],
        "config": {
            "domain_name": "Experiment06",
            "domain_def": "delineate",
            "hydrological_model": "SUMMA",
            "routing_model": "mizuRoute",
        },
    }
    out = normalize_local_workflow_plan(
        plan,
        "",
        workflow_plan_mode=WORKFLOW_PLAN_MODE_SIMULATION,
        skip_workflow_step_restore=True,
    )
    assert out["steps"] == [
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
    ]


def test_simulation_restores_experiment06_short_plan():
    plan = {
        "workflow_plan_mode": WORKFLOW_PLAN_MODE_SIMULATION,
        "steps": [
            "define_domain",
            "discretize_domain",
            "acquire_forcings",
            "model_agnostic_preprocessing",
            "run_model",
            "postprocess_results",
        ],
        "config": {
            "domain_name": "Experiment06",
            "domain_def": "delineate",
            "hydrological_model": "SUMMA",
            "routing_model": "mizuRoute",
        },
        "notes": "Skipped define_domain/discretize_domain; reusing existing local catchment.",
    }
    out = normalize_local_workflow_plan(
        plan,
        "run summa for bow river from 2023/04/02 to 2023/05/15",
        workflow_plan_mode=WORKFLOW_PLAN_MODE_SIMULATION,
        skip_workflow_step_restore=True,
    )
    assert "validate_config" in out["steps"]
    assert "setup_project" in out["steps"]
    assert "create_pour_point" in out["steps"]
    assert "acquire_attributes" in out["steps"]
    assert "build_model_ready_store" in out["steps"]
    assert "model_specific_preprocessing" in out["steps"]
    assert "postprocess_results" not in out["steps"]
    assert "dry_run" not in out["steps"]
    assert "calibrate_model" not in out["steps"]
