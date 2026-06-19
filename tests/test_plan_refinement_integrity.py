"""Chat refinement must not collapse workflow steps when only bbox is missing."""

from __future__ import annotations

from server.core.plan_rules import mark_domain_name_confirmed
from server.llm.plan_shared import finalize_plan_refinement


def test_finalize_plan_refinement_preserves_steps_when_bbox_only(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "server.llm.plan_shared.default_symfluence_data_dir",
        lambda: tmp_path,
    )
    cfg = mark_domain_name_confirmed(
        {
            "domain_name": "Remote_Cloud_Basin",
            "pour_point_coords": "51.17/-115.57",
            "experiment_time_start": "2025-01-10 01:00",
            "experiment_time_end": "2025-02-15 23:00",
            "hydrological_model": "SUMMA",
            "experiment_id": "exp_001",
            "domain_def": "delineate",
        }
    )
    current_plan = {
        "config": dict(cfg),
        "steps": ["validate_config", "setup_project", "acquire_attributes"],
        "needs_user_input": [],
        "notes": "",
    }
    llm_result = {
        "reply": "Added run_model to your workflow.",
        "update_plan": True,
        "plan": {
            "config": dict(cfg),
            "steps": [
                "validate_config",
                "setup_project",
                "acquire_attributes",
                "acquire_forcings",
                "run_model",
            ],
            "needs_user_input": [],
            "notes": "",
        },
    }
    reply, plan, updated = finalize_plan_refinement(
        llm_result,
        current_plan=current_plan,
        conversation_text="add run model",
        data_dir=tmp_path,
        preserve_workflow_steps=True,
    )
    assert updated
    assert "run_model" in (plan.get("steps") or [])
    assert plan.get("steps") != ["validate_config", "dry_run"]
    assert plan.get("needs_user_input") == ["bounding_box_coords"]
    assert reply == "Added run_model to your workflow."
