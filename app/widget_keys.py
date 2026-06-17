"""Versioned Streamlit widget keys for Input / Advanced / Calibration panels."""

from __future__ import annotations

import streamlit as st


def input_panel_widget_version() -> int:
    return int(st.session_state.get("input_panel_widget_version", 0))


def input_panel_widget_key(name: str) -> str:
    return f"{name}_v{input_panel_widget_version()}"


def bump_input_panel_widget_version() -> None:
    st.session_state.input_panel_widget_version = input_panel_widget_version() + 1


def experiment_datetime_widget_version() -> int:
    return int(st.session_state.get("experiment_datetime_widget_version", 0))


def experiment_datetime_widget_key(name: str) -> str:
    return f"{name}_v{experiment_datetime_widget_version()}"


def bump_experiment_datetime_widget_version() -> None:
    st.session_state.experiment_datetime_widget_version = experiment_datetime_widget_version() + 1


def mpi_widget_version() -> int:
    return int(st.session_state.get("mpi_widget_version", 0))


def mpi_widget_key() -> str:
    return f"mpi_num_processes_v{mpi_widget_version()}"


def bump_mpi_widget_version() -> None:
    st.session_state.mpi_widget_version = mpi_widget_version() + 1


def config_preview_widget_version() -> int:
    return int(st.session_state.get("config_preview_version", 0))


def config_preview_widget_key() -> str:
    return f"generated_config_preview_v{config_preview_widget_version()}"


def bump_config_preview_version() -> None:
    st.session_state.config_preview_version = config_preview_widget_version() + 1


def bump_all_input_widget_versions() -> None:
    """Force Input-tab widgets to pick up plan/chat changes on the next run."""
    bump_input_panel_widget_version()
    bump_experiment_datetime_widget_version()
    bump_mpi_widget_version()
    bump_config_preview_version()


def spatial_input_widget_version() -> int:
    return int(st.session_state.get("spatial_input_widget_version", 0))


def spatial_input_widget_key(name: str) -> str:
    return f"{name}_v{spatial_input_widget_version()}"


def bump_spatial_input_widget_version() -> None:
    """Remount pour-point / bounding-box text inputs (e.g. after clear)."""
    st.session_state.spatial_input_widget_version = spatial_input_widget_version() + 1
    for key in list(st.session_state.keys()):
        key_text = str(key)
        if key_text.startswith("pour_point_input") or key_text.startswith("bounding_box_input"):
            st.session_state.pop(key, None)
