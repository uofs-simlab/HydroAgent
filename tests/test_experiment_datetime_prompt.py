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
