"""Sync plan.config into Streamlit session state and Input-panel widgets."""

from __future__ import annotations

from typing import Any

import streamlit as st

import workflow_extras as wx
from server.core.ui_config_fields import (
    lookup_plan_config,
    normalize_hydrological_model,
    session_key_for_plan_field,
)
from widget_keys import bump_all_input_widget_versions


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _parse_pour_point(value: str) -> tuple[float, float] | None:
    value = _s(value)
    if not value or "/" not in value:
        return None
    try:
        lat_str, lon_str = value.split("/", 1)
        return float(lat_str.strip()), float(lon_str.strip())
    except Exception:
        return None


def _sync_spatial_field(cfg: dict, plan_key: str, session_key: str, input_key: str) -> None:
    raw = lookup_plan_config(cfg, plan_key)
    if raw is not None and _s(raw):
        val = _s(raw).replace(",", "/")
        st.session_state[session_key] = val
        st.session_state[input_key] = val
        if plan_key == "pour_point_coords":
            parsed = _parse_pour_point(val)
            if parsed:
                lat, lon = parsed
                st.session_state.map_lat = lat
                st.session_state.map_lon = lon
                st.session_state.map_point_selected = True
    elif plan_key in cfg and cfg.get(plan_key) is None:
        st.session_state[session_key] = ""
        st.session_state[input_key] = ""
        if plan_key == "pour_point_coords":
            st.session_state.map_lat = None
            st.session_state.map_lon = None
            st.session_state.map_point_selected = False


def _sync_scalar_field(cfg: dict, plan_key: str, *, normalizer=None) -> None:
    raw = lookup_plan_config(cfg, plan_key)
    if raw is None:
        return
    session_key = session_key_for_plan_field(plan_key)
    if raw == "" or raw is None:
        if plan_key in cfg:
            st.session_state[session_key] = "" if session_key != "mpi" else 1
        return
    value = normalizer(raw) if normalizer else raw
    if session_key == "mpi":
        try:
            st.session_state.mpi = int(value)
        except Exception:
            pass
    elif session_key in ("iterations", "population_size"):
        try:
            st.session_state[session_key] = int(value)
        except Exception:
            st.session_state[session_key] = value
    else:
        st.session_state[session_key] = value


def sync_plan_config_to_session(plan: dict | None) -> None:
    """Push all known plan.config values into session state and bump widget keys."""
    cfg = (plan or {}).get("config", {}) or {}

    for plan_key in (
        "domain_name",
        "experiment_id",
        "domain_def",
        "forcing_dataset",
        "discretization",
        "data_access",
        "params_to_calibrate",
        "download_snotel",
        "snotel_station",
    ):
        _sync_scalar_field(cfg, plan_key)

    _sync_scalar_field(cfg, "hydrological_model", normalizer=normalize_hydrological_model)

    for plan_key in ("NUM_PROCESSES", "num_processes", "MPI_PROCESSES", "mpi_processes"):
        if lookup_plan_config(cfg, plan_key) is not None:
            _sync_scalar_field(cfg, plan_key)
            break

    _sync_scalar_field(cfg, "experiment_time_start")
    _sync_scalar_field(cfg, "experiment_time_end")

    _sync_spatial_field(cfg, "pour_point_coords", "selected_pour_point", "pour_point_input")
    _sync_spatial_field(cfg, "bounding_box_coords", "selected_bounding_box", "bounding_box_input")

    wx.apply_advanced_config_from_plan(cfg)

    bump_all_input_widget_versions()
    st.session_state.refresh_spatial_inputs = True
