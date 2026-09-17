"""Prompt parsing and plan preservation for experiment time window."""

from __future__ import annotations

from server.core.ui_config_fields import (
    apply_comprehensive_chat_config_edits,
    apply_prompt_literal_config_edits,
)


def test_prompt_from_to_range_sets_start_and_end():
    plan = apply_prompt_literal_config_edits(
        {"config": {"hydrological_model": "SUMMA"}, "steps": ["run_model"]},
        "run summa for Bow river from 2025/01/10 to 2025/02/15",
    )
    cfg = plan["config"]
    assert cfg["experiment_time_start"] == "2025-01-10 01:00"
    assert cfg["experiment_time_end"] == "2025-02-15 23:00"


def test_chat_end_date_shortcut():
    plan = apply_comprehensive_chat_config_edits(
        {"config": {}, "steps": ["run_model"]},
        "set the end date to 2025-12-31",
    )
    cfg = plan["config"]
    assert cfg["experiment_time_end"] == "2025-12-31 23:00"


def test_prompt_literal_config_accepts_colon_separated_core_fields():
    out = apply_prompt_literal_config_edits(
        {"config": {"data_access": "local"}},
        """domain_name: Bow_at_Banff_CIROH_lumped
experiment_id: basin_setup_cloud_01
pour_point_coords: 51.1722/-115.5717
bounding_box_coords: 51.85/-116.80/50.80/-115.15
domain_def: lumped
discretization: lumped
data_access: cloud
""",
    )

    cfg = out["config"]
    assert cfg["domain_name"] == "Bow_at_Banff_CIROH_lumped"
    assert cfg["experiment_id"] == "basin_setup_cloud_01"
    assert cfg["pour_point_coords"] == "51.1722/-115.5717"
    assert cfg["bounding_box_coords"] == "51.85/-116.80/50.80/-115.15"
    assert cfg["domain_def"] == "lumped"
    assert cfg["discretization"] == "lumped"
    assert cfg["data_access"] == "cloud"
