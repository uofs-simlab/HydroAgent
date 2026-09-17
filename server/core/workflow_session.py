"""Session-state reset policy for starting a new HydroAgent workflow."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, MutableMapping


WORKFLOW_RESET_DEFAULTS: dict[str, Any] = {
    "run_plan": None,
    "simulation_plan": None,
    "calibration_plan": None,
    "workflow_plan_mode": "simulation",
    "execute_plan": False,
    "workflow_executing": False,
    "execution_log_text": "",
    "chat_messages": [],
    "domain_name": "",
    "experiment_id": "",
    "domain_def": "",
    "hydrological_model": "",
    "forcing_dataset": "ERA5",
    "tstart": "",
    "tend": "",
    "pour_point_input": "",
    "bounding_box_input": "",
    "selected_pour_point": "",
    "selected_bounding_box": "",
    "map_mode": "pour_point",
    "last_map_click": None,
    "map_lat": None,
    "map_lon": None,
    "map_point_selected": False,
    "bbox_point_1": None,
    "bbox_point_2": None,
    "bbox_selected": False,
    "pour_point_map_hidden": False,
    "bbox_map_hidden": False,
    "refresh_spatial_inputs": True,
    "spatial_inputs_stale": True,
    "show_dem_layer": False,
    "show_landclass_layer": False,
    "show_soilclass_layer": False,
    "show_riverbasins_layer": False,
    "show_rivernetwork_layer": False,
    "show_hrugru_layer": False,
    "show_forcing_layer": False,
    "run_folder": "",
    "run_workspace_locked": False,
    "run_results_scan_at": "",
    "mpi": 1,
    "allow_run": False,
    "danger_phrase": "",
    "want_create_pour_point": True,
    "nl_request": "",
    "user_prompt": "",
    "workflow_section": "Input",
    "assistant_panel_tabs": "Prompt",
    "streamflow_data_provider": "WSC",
    "station_id": "",
    "routing_model": "mizuRoute",
    "stream_threshold": 1000,
    "pet_method": "oudin",
    "spinup_period": "",
    "calibration_period": "",
    "evaluation_period": "",
    "iterative_optimization_algorithm": "DE",
    "optimization_metric": "KGE",
    "optimization_target": "streamflow",
    "calibration_timestep": "daily",
    "iterations": 20,
    "population_size": 10,
    "calib_agent_auto_replan": False,
    "calib_agent_sensitivity_guided": False,
    "calib_agent_top_n_params": 4,
    "calib_agent_screening_iterations": 30,
}


WORKFLOW_WIDGET_VERSION_KEYS = (
    "input_panel_widget_version",
    "mpi_widget_version",
    "experiment_datetime_widget_version",
    "config_preview_version",
    "workflow_map_widget_version",
    "spatial_input_widget_version",
    "workflow_chat_compose_version",
    "plan_editor_version",
)


WORKFLOW_TRANSIENT_KEYS = (
    "_explicit_ui_fields",
    "_calib_base_config",
    "calib_agent_last_outcome",
    "_chat_transcribe_ok",
    "_committed_plan_steps",
    "_focus_assistant_chat_tab",
    "_ignore_map_clicks_once",
    "_langprompt_matches",
    "_langprompt_search_empty",
    "_langprompt_search_error",
    "_langprompt_search_ok",
    "_langprompt_use_ok",
    "_loaded_config_yaml",
    "_nl_transcribe_ok",
    "_pending_apply_plan_to_session",
    "_pending_chat_refinement",
    "_pending_load_run",
    "_pending_nl_transcript",
    "_pending_plan_editor_text",
    "_pending_workflow_chat_draft",
    "_plan_editor_stash",
    "_plan_editor_synced",
    "_skip_input_panel_sync_once",
    "_spatial_just_cleared",
    "_suppressed_map_clicks",
    "_workflow_just_started",
    "_workflow_poll_active",
)


def reset_workflow_session_state(state: MutableMapping[str, Any]) -> None:
    """Reset the active workflow without touching preferences or saved files."""
    for key, value in WORKFLOW_RESET_DEFAULTS.items():
        state[key] = deepcopy(value)

    for key in WORKFLOW_TRANSIENT_KEYS:
        state.pop(key, None)

    # Streamlit widgets retain values by key. Advancing each version remounts
    # workflow widgets from the clean state on the next rerun.
    for key in WORKFLOW_WIDGET_VERSION_KEYS:
        state[key] = int(state.get(key, 0)) + 1
