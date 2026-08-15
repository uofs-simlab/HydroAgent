"""Resolve dependencies and gated-step inference for cloud and local plans."""

from __future__ import annotations

import json
from pathlib import Path

from server.capabilities.load_catalog import load_catalog
from server.core.plan_rules import (
    infer_gated_plan_steps,
    mark_domain_name_confirmed,
    normalize_local_workflow_plan,
    resolve_plan_step_dependencies,
)


def _cloud_plan(**overrides):
    cfg = mark_domain_name_confirmed(
        {
            "domain_name": "Cloud_Test_Basin",
            "experiment_id": "exp_001",
            "pour_point_coords": "51.17/-115.57",
            "experiment_time_start": "2004-01-01 01:00",
            "experiment_time_end": "2007-12-31 23:00",
            "hydrological_model": "SUMMA",
            "domain_def": "delineate",
        }
    )
    cfg.update(overrides.get("config") or {})
    return {
        "config": cfg,
        "steps": overrides.get("steps", ["validate_config"]),
        "needs_user_input": overrides.get("needs_user_input", []),
        "notes": "",
    }


def test_infer_gated_plan_steps_for_cloud_summa_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "server.core.plan_rules.default_symfluence_data_dir",
        lambda: tmp_path,
    )
    plan = _cloud_plan()
    user_request = "Create a basin semi-distributed SUMMA workflow for Bow River at Banff."
    out = infer_gated_plan_steps(plan, user_request, data_dir=tmp_path)
    steps = out.get("steps") or []
    assert steps != ["validate_config"]
    assert "run_model" in steps
    assert "define_domain" in steps


def test_normalize_local_workflow_plan_infers_before_cloud_early_return(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "server.core.plan_rules.default_symfluence_data_dir",
        lambda: tmp_path,
    )
    plan = _cloud_plan()
    user_request = "Create a cloud SUMMA workflow from scratch for a new basin."
    out = normalize_local_workflow_plan(plan, user_request, data_dir=tmp_path)
    steps = out.get("steps") or []
    assert "run_model" in steps
    assert steps != ["validate_config", "dry_run"]


def test_resolve_plan_step_dependencies_expands_minimal_cloud_plan(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "server.core.plan_rules.default_symfluence_data_dir",
        lambda: tmp_path,
    )
    catalog_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "capabilities"
        / "symfluence_operation_catalog.json"
    )
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    plan = _cloud_plan()
    user_request = "Create a SUMMA workflow from scratch for a new basin."
    out = resolve_plan_step_dependencies(
        plan,
        user_request,
        catalog=catalog,
        data_dir=tmp_path,
    )
    steps = out.get("steps") or []
    assert "validate_config" in steps
    assert "setup_project" in steps
    assert "run_model" in steps
    assert "create_pour_point" in steps
    assert steps.index("create_pour_point") < steps.index("define_domain")
    assert len(steps) > 3
