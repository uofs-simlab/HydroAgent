"""Domain name confirmation policy for run plans."""

from __future__ import annotations

from pathlib import Path

from server.core.plan_rules import (
    apply_user_provided_domain_name,
    domain_name_needs_user_input,
    ensure_domain_name_user_input,
    extract_explicit_domain_name_from_request,
    is_weak_domain_name,
    mark_domain_name_confirmed,
    normalize_committed_plan_config,
)
from server.llm.plan_shared import finalize_run_plan


def test_weak_domain_names():
    assert is_weak_domain_name("Bow")
    assert is_weak_domain_name("2025")
    assert is_weak_domain_name("river")
    assert not is_weak_domain_name("Bow_at_Banff_semi_distributed")


def test_explicit_domain_name_from_prompt():
    prompt = "Use domain_name Bow_at_Banff_semi_distributed and experiment_id run_1"
    assert extract_explicit_domain_name_from_request(prompt) == "Bow_at_Banff_semi_distributed"


def test_finalize_run_plan_rejects_inferred_bow():
    plan = finalize_run_plan(
        {
            "config": {
                "domain_name": "Bow",
                "pour_point_coords": "51.17/-115.57",
                "experiment_time_start": "2025-01-10 01:00",
                "experiment_time_end": "2025-02-15 23:00",
                "hydrological_model": "SUMMA",
                "experiment_id": "exp_001",
            },
            "steps": ["validate_config", "setup_project", "run_model"],
            "needs_user_input": [],
            "notes": "",
        },
        "run summa for Bow river from 2025/01/10 to 2025/02/15",
    )
    assert "domain_name" in (plan.get("needs_user_input") or [])
    assert plan.get("steps") == ["validate_config", "dry_run"]
    assert not (plan.get("config") or {}).get("domain_name")


def test_finalize_run_plan_preserves_steps_when_only_bbox_missing(tmp_path, monkeypatch):
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
    plan = finalize_run_plan(
        {
            "config": cfg,
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
        "add run model to the workflow",
    )
    assert plan.get("steps") != ["validate_config", "dry_run"]
    assert "run_model" in (plan.get("steps") or [])
    assert plan.get("needs_user_input") == ["bounding_box_coords"]


def test_existing_domain_folder_accepted(tmp_path: Path):
    domain_dir = tmp_path / "domain_Bow_at_Banff_semi_distributed"
    domain_dir.mkdir()
    cfg = {"domain_name": "Bow_at_Banff_semi_distributed"}
    assert not domain_name_needs_user_input(cfg, "run summa", data_dir=tmp_path)


def test_confirmed_domain_accepted():
    cfg = mark_domain_name_confirmed({"domain_name": "My_Custom_Basin_v2"})
    assert not domain_name_needs_user_input(cfg, "run summa")


def test_apply_user_provided_domain_name_marks_confirmed():
    cfg = apply_user_provided_domain_name({}, "Bow_at_Banff_semi_distributed")
    assert cfg["domain_name"] == "Bow_at_Banff_semi_distributed"
    assert not domain_name_needs_user_input(cfg, "run summa for the basin")


def test_apply_user_provided_domain_name_confirms_weak_ui_entry():
    cfg = apply_user_provided_domain_name({}, "Bow")
    assert cfg["domain_name"] == "Bow"
    assert not domain_name_needs_user_input(cfg, "run summa for Bow")


def test_normalize_committed_plan_config_confirms_editor_domain():
    cfg = normalize_committed_plan_config({"domain_name": "Bow_at_Banff_semi_distributed"})
    assert not domain_name_needs_user_input(cfg, "run summa")


def test_explicit_domain_name_from_chat_set_to():
    prompt = "set domain_name to BOWRiver2"
    assert extract_explicit_domain_name_from_request(prompt) == "BOWRiver2"


def test_chat_config_edit_confirms_weak_domain_name():
    from server.core.ui_config_fields import apply_comprehensive_chat_config_edits

    plan = apply_comprehensive_chat_config_edits(
        {"config": {}, "steps": ["validate_config"], "needs_user_input": ["domain_name"], "notes": ""},
        "set domain_name to BOWRiver2",
    )
    cfg = plan.get("config") or {}
    assert cfg.get("domain_name") == "BOWRiver2"
    assert not domain_name_needs_user_input(cfg, "set domain_name to BOWRiver2")


def test_confirm_domain_from_chat_message_helper():
    from app.ui_agent import _confirm_domain_from_chat_message

    plan = _confirm_domain_from_chat_message(
        {"config": {"domain_name": "BOWRiver2"}, "steps": ["validate_config"], "needs_user_input": [], "notes": ""},
        "I set domain_name to BOWRiver2",
    )
    assert not domain_name_needs_user_input(plan.get("config") or {}, "I set domain_name to BOWRiver2")


def test_explicit_domain_name_use_as_domain_name():
    assert extract_explicit_domain_name_from_request("use BOWRiver3 as domain name") == "BOWRiver3"


def test_chat_config_edit_use_as_domain_name():
    from server.core.ui_config_fields import apply_comprehensive_chat_config_edits

    plan = apply_comprehensive_chat_config_edits(
        {"config": {}, "steps": ["validate_config", "dry_run"], "needs_user_input": ["domain_name"], "notes": ""},
        "use BOWRiver3 as domain name",
    )
    cfg = plan.get("config") or {}
    assert cfg.get("domain_name") == "BOWRiver3"
    assert not domain_name_needs_user_input(cfg, "use BOWRiver3 as domain name")


def test_ensure_domain_name_user_input_keeps_explicit():
    plan = ensure_domain_name_user_input(
        {"config": {}, "steps": ["validate_config"], "needs_user_input": [], "notes": ""},
        "domain_name Bow_at_Banff_lumped",
        data_dir=Path("/nonexistent"),
    )
    assert plan["config"]["domain_name"] == "Bow_at_Banff_lumped"
    assert "domain_name" not in (plan.get("needs_user_input") or [])
