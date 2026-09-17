from pathlib import Path

from server.core.workflow_session import reset_workflow_session_state


def test_reset_workflow_clears_run_state_and_preserves_preferences():
    state = {
        "run_plan": {"config": {"domain_name": "Old_Basin"}},
        "simulation_plan": {"steps": ["define_domain"]},
        "calibration_plan": {"steps": ["calibrate_model"]},
        "chat_messages": [{"role": "user", "content": "old prompt"}],
        "domain_name": "Old_Basin",
        "experiment_id": "old_run",
        "selected_pour_point": "51/-115",
        "selected_bounding_box": "52/-116/50/-114",
        "run_folder": "Old_Basin_old_run",
        "run_workspace_locked": True,
        "nl_request": "old prompt",
        "user_prompt": "old prompt",
        "execution_log_text": "old log",
        "workflow_executing": True,
        "_loaded_config_yaml": "DOMAIN_NAME: Old_Basin",
        "_pending_chat_refinement": "change it",
        "_explicit_ui_fields": {"forcing_dataset", "streamflow_data_provider"},
        "api_keys": {"openai": "secret"},
        "llm_provider": "claude",
        "llm_model": "claude-sonnet",
        "langprompt_enrich": False,
        "langprompt_save": False,
        "enable_prompt_phrase_matching": False,
        "assistant_panel_open": True,
    }

    reset_workflow_session_state(state)

    assert state["run_plan"] is None
    assert state["simulation_plan"] is None
    assert state["calibration_plan"] is None
    assert state["chat_messages"] == []
    assert state["domain_name"] == ""
    assert state["experiment_id"] == ""
    assert state["selected_pour_point"] == ""
    assert state["selected_bounding_box"] == ""
    assert state["run_folder"] == ""
    assert state["run_workspace_locked"] is False
    assert state["nl_request"] == ""
    assert state["user_prompt"] == ""
    assert state["execution_log_text"] == ""
    assert state["workflow_executing"] is False
    assert "_loaded_config_yaml" not in state
    assert "_pending_chat_refinement" not in state
    assert "_explicit_ui_fields" not in state

    assert state["api_keys"] == {"openai": "secret"}
    assert state["llm_provider"] == "claude"
    assert state["llm_model"] == "claude-sonnet"
    assert state["langprompt_enrich"] is False
    assert state["langprompt_save"] is False
    assert state["enable_prompt_phrase_matching"] is False
    assert state["assistant_panel_open"] is True


def test_reset_workflow_remounts_cached_workflow_widgets():
    state = {
        "input_panel_widget_version": 4,
        "workflow_map_widget_version": 7,
        "spatial_input_widget_version": 2,
        "plan_editor_version": 5,
    }

    reset_workflow_session_state(state)

    assert state["input_panel_widget_version"] == 5
    assert state["workflow_map_widget_version"] == 8
    assert state["spatial_input_widget_version"] == 3
    assert state["plan_editor_version"] == 6


def test_assistant_panel_wires_confirmed_new_workflow_control():
    source = Path("app/ui_agent.py").read_text(encoding="utf-8")

    assert '"New workflow"' in source
    assert '"Start new workflow"' in source
    assert 'key=f"new_workflow_popover_v{control_version}"' in source
    assert 'key=f"confirm_new_workflow_v{control_version}"' in source
    assert 'st.session_state["new_workflow_control_version"] = control_version + 1' in source
    assert "reset_workflow_session_state(st.session_state)" in source
    assert "Saved runs and SYMFLUENCE data will not be deleted." in source


def test_prompt_plan_precedence_tracks_only_deliberate_gui_edits():
    source = Path("app/ui_agent.py").read_text(encoding="utf-8")

    assert "plan = apply_explicit_workflow_ui_overrides(plan)" in source
    assert "if key not in explicit:" in source
    assert 'args=("forcing_dataset",)' in source
    assert "plan_to_save = apply_explicit_workflow_ui_overrides(" in source
    assert 'st.session_state.want_create_pour_point = "create_pour_point" in set(' in source
