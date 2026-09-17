"""Semi-distributed gate must see plan steps so SUMMA mizuRoute defaults apply."""

from app.ui_agent import apply_semi_distributed_config_defaults, is_semi_distributed_workflow


def test_semi_distributed_gate_requires_steps_in_spec():
    spec = {
        "domain_def": "delineate",
        "discretization": "GRUs",
        "hydrological_model": "SUMMA",
    }
    cfg = {"HYDROLOGICAL_MODEL": "SUMMA", "DOMAIN_DISCRETIZATION": "GRUs"}

    assert is_semi_distributed_workflow(spec, cfg) is False

    spec["steps"] = ["define_domain", "discretize_domain", "run_model"]
    assert is_semi_distributed_workflow(spec, cfg) is True


def test_semi_distributed_gate_summa_mizuroute_without_steps():
    spec = {
        "domain_def": "delineate",
        "hydrological_model": "SUMMA",
        "routing_model": "mizuRoute",
        "steps": ["validate_config", "run_model", "calibrate_model"],
    }
    cfg = {"HYDROLOGICAL_MODEL": "SUMMA", "ROUTING_MODEL": "mizuRoute"}
    assert is_semi_distributed_workflow(spec, cfg) is True


def test_semi_distributed_defaults_set_summa_mizuroute_values():
    spec = {
        "domain_def": "delineate",
        "discretization": "GRUs",
        "steps": ["define_domain", "discretize_domain", "run_model"],
    }
    cfg = {
        "HYDROLOGICAL_MODEL": "SUMMA",
        "ROUTING_MODEL": "mizuRoute",
        "SETTINGS_MIZU_ROUTING_VAR": "q_routed",
        "SETTINGS_MIZU_ROUTING_UNITS": "mm/d",
        "SETTINGS_MIZU_ROUTING_DT": 86400,
    }

    out = apply_semi_distributed_config_defaults(cfg, spec)

    assert out["SETTINGS_MIZU_ROUTING_VAR"] == "averageRoutedRunoff"
    assert out["SETTINGS_MIZU_ROUTING_UNITS"] == "m/s"
    assert out["SETTINGS_MIZU_ROUTING_DT"] == 3600
    assert out["MIZU_FROM_MODEL"] == "SUMMA"
