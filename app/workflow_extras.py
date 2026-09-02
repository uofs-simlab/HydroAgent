"""Workflow UI helpers: run results, Data/Logs/Dashboard/Experiments pages, advanced config, run shortcuts."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

ASSISTANT_BASE = Path(__file__).resolve().parents[1]

ADVANCED_SESSION_FIELDS = [
    ("streamflow_data_provider", "STREAMFLOW_DATA_PROVIDER", "Streamflow data provider"),
    ("station_id", "STATION_ID", "Gauging station ID"),
    ("routing_model", "ROUTING_MODEL", "Routing model"),
    ("pet_method", "PET_METHOD", "PET method"),
    ("stream_threshold", "STREAM_THRESHOLD", "TauDEM stream threshold (flow accumulation)"),
    ("spinup_period", "SPINUP_PERIOD", "Spinup period (YYYY-MM-DD, YYYY-MM-DD)"),
    ("calibration_period", "CALIBRATION_PERIOD", "Calibration period"),
    ("evaluation_period", "EVALUATION_PERIOD", "Evaluation period"),
]

RUN_STEP_BUNDLES: dict[str, list[str]] = {
    "preprocessing": [
        "validate_config",
        "acquire_attributes",
        "acquire_forcings",
        "model_agnostic_preprocessing",
        "model_specific_preprocessing",
    ],
    "model": ["run_model"],
    "postprocess": ["postprocess_results"],
}

CALIBRATION_SESSION_FIELDS = [
    ("iterative_optimization_algorithm", "ITERATIVE_OPTIMIZATION_ALGORITHM"),
    ("optimization_metric", "OPTIMIZATION_METRIC"),
    ("optimization_target", "OPTIMIZATION_TARGET"),
    ("calibration_timestep", "CALIBRATION_TIMESTEP"),
    ("iterations", "NUMBER_OF_ITERATIONS"),
    ("population_size", "POPULATION_SIZE"),
]

from server.core.symfluence_options import (
    CALIBRATION_ALGORITHMS,
    CALIBRATION_METRICS,
    CALIBRATION_TARGETS,
    CALIBRATION_TIMESTEPS,
)

PLOT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}


def s(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return str(value).lower()
    return str(value).strip()


def workflow_context(
    *,
    runs_dir: Path,
    symfluence_data_dir: Path,
    domain_name: str | None = None,
    experiment_id: str | None = None,
    run_folder: str | None = None,
) -> dict:
    domain_name = s(domain_name or st.session_state.get("domain_name"))
    experiment_id = s(experiment_id or st.session_state.get("experiment_id"))
    run_folder = s(run_folder or st.session_state.get("run_folder"))
    combined = f"{domain_name}_{experiment_id}".strip("_") if domain_name and experiment_id else run_folder
    domain_root = symfluence_data_dir / f"domain_{domain_name}" if domain_name else None
    sim_dir = domain_root / "simulations" / experiment_id if domain_root and experiment_id else None
    mizu_dir = sim_dir / "mizuRoute" if sim_dir else None
    assistant_run = runs_dir / run_folder if run_folder else None
    return {
        "domain_name": domain_name,
        "experiment_id": experiment_id,
        "run_folder": run_folder,
        "combined_name": combined,
        "domain_root": domain_root,
        "sim_dir": sim_dir,
        "mizu_dir": mizu_dir,
        "assistant_run": assistant_run,
    }


def _first_existing_artifact(candidates: list[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def scan_run_artifacts(ctx: dict, layer_paths: dict[str, str] | None = None) -> list[dict]:
    rows: list[dict] = []
    domain_root = ctx.get("domain_root")
    sim_dir = ctx.get("sim_dir")
    mizu_dir = ctx.get("mizu_dir")
    assistant_run = ctx.get("assistant_run")
    combined = ctx.get("combined_name") or ""
    data_dir = domain_root.parent if domain_root else None

    def add(label: str, path: Path | str | None, category: str = "general") -> None:
        if path is None:
            rows.append({"category": category, "artifact": label, "status": "n/a", "path": ""})
            return
        p = Path(path)
        exists = p.exists()
        rows.append(
            {
                "category": category,
                "artifact": label,
                "status": "found" if exists else "missing",
                "path": str(p),
            }
        )

    add("SYMFLUENCE domain folder", domain_root, "domain")
    if layer_paths:
        add("DEM catchment", layer_paths.get("dem"), "geospatial")
        add("Landclass catchment", layer_paths.get("landclass"), "geospatial")
        add("Soilclass catchment", layer_paths.get("soilclass"), "geospatial")
        add("River basins", layer_paths.get("riverbasins"), "geospatial")
        add("HRUs / GRUs", layer_paths.get("hrugru"), "geospatial")
        add("River network", layer_paths.get("rivernetwork"), "geospatial")
        forcing_hint = layer_paths.get("forcing")
        forcing_path = None
        if forcing_hint:
            hinted = Path(forcing_hint)
            forcing_path = _first_existing_artifact(
                [hinted, hinted.with_suffix(".csv"), hinted.with_suffix(".shp")]
            )
        if forcing_path is None and domain_root:
            from server.core.plan_rules import domain_forcing_intersection_path

            forcing_path = domain_forcing_intersection_path(
                domain_root.parent,
                s(ctx.get("domain_name")),
                forcing_dataset=s(ctx.get("forcing_dataset")) or "ERA5",
            )
        add("ERA5 intersection", forcing_path or forcing_hint, "geospatial")

    if domain_root and domain_root.exists():
        file_manager = _first_existing_artifact(
            [
                domain_root / "settings" / "SUMMA" / "fileManager.txt",
                domain_root / "fileManager.txt",
            ]
        )
        add(
            "fileManager.txt",
            file_manager or (domain_root / "settings" / "SUMMA" / "fileManager.txt"),
            "domain",
        )
        forcing_list = _first_existing_artifact(
            [
                domain_root / "settings" / "SUMMA" / "forcingFileList.txt",
                domain_root / "forcing" / "forcingFileList.txt",
            ]
        )
        add(
            "forcingFileList.txt",
            forcing_list or (domain_root / "settings" / "SUMMA" / "forcingFileList.txt"),
            "forcing",
        )
        forcing_raw = _first_existing_artifact(
            [
                domain_root / "data" / "forcing" / "raw_data",
                domain_root / "forcing" / "raw_data",
            ]
        )
        add(
            "forcing / raw_data",
            forcing_raw or (domain_root / "data" / "forcing" / "raw_data"),
            "forcing",
        )

    add("Simulations folder", sim_dir, "simulation")
    add("SUMMA output folder", sim_dir / "SUMMA" if sim_dir else None, "simulation")
    add("mizuRoute folder", mizu_dir, "simulation")
    add("mizuRoute NetCDF (exp_*.nc)", mizu_dir, "simulation")
    if mizu_dir and mizu_dir.exists():
        exp_id = s(ctx.get("experiment_id"))
        history_globs = ["*.h.*.nc", "exp_*.h.*.nc"]
        if exp_id:
            history_globs.insert(0, f"{exp_id}*.h.*.nc")
        history_files: list[Path] = []
        for pattern in history_globs:
            history_files = sorted(mizu_dir.glob(pattern))
            if history_files:
                break
        nc_count = len(history_files)
        rows.append(
            {
                "category": "simulation",
                "artifact": "mizuRoute history files",
                "status": "found" if nc_count else "missing",
                "path": (
                    f"{history_files[0]} (+{nc_count - 1} more)"
                    if nc_count > 1
                    else (str(history_files[0]) if nc_count else str(mizu_dir))
                ),
            }
        )
        from server.core.routed_flow import ensure_routed_flow_csv

        try:
            routed_csv = ensure_routed_flow_csv(mizu_dir)
        except Exception:
            routed_csv = None
        add(
            "routed_flow.csv",
            routed_csv or (mizu_dir / "routed_flow.csv"),
            "simulation",
        )
    else:
        add("routed_flow.csv", mizu_dir / "routed_flow.csv" if mizu_dir else None, "simulation")

    if data_dir and domain_root:
        from server.core.plan_rules import domain_streamflow_processed_path
        from server.core.calibration_logs import (
            calibration_log_path,
            find_symfluence_calibration_work_log,
            iter_calibration_result_dirs,
            worklog_dir,
        )

        domain_name = s(ctx.get("domain_name"))
        exp_id = s(ctx.get("experiment_id"))
        obs_path = domain_streamflow_processed_path(data_dir, domain_name)
        add("Observed streamflow (processed)", obs_path, "evaluation")
        calib_dirs = iter_calibration_result_dirs(domain_root, exp_id)
        for calib_dir in calib_dirs:
            add(f"Calibration results ({calib_dir.name})", calib_dir, "calibration")
            best_params = _first_existing_artifact(sorted(calib_dir.glob("*_best_params.json")))
            add(
                f"Best parameters ({calib_dir.name})",
                best_params or (calib_dir / f"{exp_id}_best_params.json"),
                "calibration",
            )
            iter_csv = _first_existing_artifact(
                sorted(calib_dir.glob("*iteration_results.csv"))
            )
            add(
                f"Iteration results ({calib_dir.name})",
                iter_csv or (calib_dir / f"{exp_id}_parallel_iteration_results.csv"),
                "calibration",
            )
            add(f"Final evaluation ({calib_dir.name})", calib_dir / "final_evaluation", "calibration")
        work_log = find_symfluence_calibration_work_log(domain_root)
        if calib_dirs or work_log:
            add(
                "SYMFLUENCE calibration work log",
                work_log or worklog_dir(domain_root),
                "calibration",
            )
            if assistant_run:
                add(
                    "HydroAgent calibration.log",
                    calibration_log_path(assistant_run),
                    "calibration",
                )

    add("Assistant run folder", assistant_run, "assistant")
    add("Assistant config.yaml", assistant_run / "config.yaml" if assistant_run else None, "assistant")
    add("execution.log", assistant_run / "logs" / "execution.log" if assistant_run else None, "assistant")
    if assistant_run and (assistant_run / "plan.json").exists():
        rows.append(
            {
                "category": "assistant",
                "artifact": "plan.json",
                "status": "found",
                "path": str(assistant_run / "plan.json"),
            }
        )
    return rows


def resolve_observed_streamflow_path(ctx: dict, data_dir: Path) -> Path | None:
    domain_name = s(ctx.get("domain_name"))
    if not domain_name:
        return None
    from server.core.plan_rules import domain_streamflow_processed_path

    path = domain_streamflow_processed_path(data_dir, domain_name)
    return path if path.is_file() else None


def resolve_simulated_flow_path(ctx: dict) -> Path | None:
    mizu_dir = ctx.get("mizu_dir")
    if not mizu_dir:
        return None
    csv_path = mizu_dir / "routed_flow.csv"
    return csv_path if csv_path.exists() else None


def load_aligned_hydrograph_frames(ctx: dict, data_dir: Path) -> tuple[pd.DataFrame | None, str]:
    obs_path = resolve_observed_streamflow_path(ctx, data_dir)
    sim_path = resolve_simulated_flow_path(ctx)
    if obs_path is None and sim_path is None:
        return None, "No observed or simulated streamflow files found."
    frames: dict[str, pd.Series] = {}
    if obs_path:
        obs_df = pd.read_csv(obs_path, parse_dates=["time"] if "time" in pd.read_csv(obs_path, nrows=0).columns else None)
        time_col = "time" if "time" in obs_df.columns else obs_df.columns[0]
        val_cols = [c for c in obs_df.columns if c != time_col]
        if not val_cols:
            return None, f"No value column in {obs_path.name}"
        obs_df[time_col] = pd.to_datetime(obs_df[time_col])
        frames["observed"] = obs_df.set_index(time_col)[val_cols[0]].astype(float)
    if sim_path:
        sim_df = pd.read_csv(sim_path, parse_dates=["time"])
        qcol = "IRFroutedRunoff" if "IRFroutedRunoff" in sim_df.columns else [c for c in sim_df.columns if c.lower() != "time"][0]
        sim_df["time"] = pd.to_datetime(sim_df["time"])
        frames["simulated"] = sim_df.set_index("time")[qcol].astype(float)
    if not frames:
        return None, "Could not load hydrograph data."
    merged = pd.DataFrame(frames).dropna(how="all")
    if merged.empty:
        return None, "No overlapping or available time steps."
    return merged, ""


def nse(obs: pd.Series, sim: pd.Series) -> float:
    aligned = pd.concat([obs, sim], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return float("nan")
    o = aligned.iloc[:, 0].values
    p = aligned.iloc[:, 1].values
    denom = ((o - o.mean()) ** 2).sum()
    if denom == 0:
        return float("nan")
    return float(1 - ((o - p) ** 2).sum() / denom)


def kge(obs: pd.Series, sim: pd.Series) -> float:
    aligned = pd.concat([obs, sim], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return float("nan")
    o = aligned.iloc[:, 0].astype(float)
    p = aligned.iloc[:, 1].astype(float)
    if o.std() == 0 or p.std() == 0 or o.mean() == 0:
        return float("nan")
    r = o.corr(p)
    if pd.isna(r):
        return float("nan")
    alpha = p.std() / o.std()
    beta = p.mean() / o.mean()
    return float(1 - ((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2) ** 0.5)


def compute_quick_metrics(merged: pd.DataFrame) -> dict[str, float | int | str]:
    out: dict[str, float | int | str] = {"n_points": int(len(merged))}
    if "observed" in merged.columns and "simulated" in merged.columns:
        both = merged[["observed", "simulated"]].dropna()
        out["NSE"] = nse(both["observed"], both["simulated"])
        out["KGE"] = kge(both["observed"], both["simulated"])
        out["bias_m3s"] = float((both["simulated"] - both["observed"]).mean())
        out["rmse_m3s"] = float(((both["simulated"] - both["observed"]) ** 2).mean() ** 0.5)
    elif "simulated" in merged.columns:
        q = merged["simulated"].dropna()
        out["sim_mean_m3s"] = float(q.mean())
        out["sim_max_m3s"] = float(q.max())
    return out


def get_calibration_config_values(plan_cfg: dict | None = None) -> dict[str, str]:
    from server.core.ui_config_fields import lookup_plan_config

    plan_cfg = plan_cfg or {}
    values: dict[str, str] = {}
    for session_key, yaml_key in CALIBRATION_SESSION_FIELDS:
        val = s(lookup_plan_config(plan_cfg, session_key, yaml_key))
        if not val:
            raw = st.session_state.get(session_key)
            val = s(str(raw)) if session_key in ("iterations", "population_size") and raw is not None else s(raw)
        if val:
            values[session_key] = val
    return values


def apply_calibration_config_from_plan(cfg: dict) -> None:
    extra = cfg.get("extra_config") if isinstance(cfg.get("extra_config"), dict) else {}
    for session_key, yaml_key in CALIBRATION_SESSION_FIELDS:
        val = s(cfg.get(session_key)) or s(cfg.get(yaml_key)) or s(extra.get(session_key)) or s(extra.get(yaml_key))
        if session_key in ("iterations", "population_size"):
            if val:
                try:
                    st.session_state[session_key] = int(float(val))
                except Exception:
                    st.session_state[session_key] = val
        elif val:
            st.session_state[session_key] = val


def sync_calibration_config_to_plan() -> None:
    if not st.session_state.get("run_plan"):
        return
    plan = st.session_state.run_plan
    plan.setdefault("config", {})
    cfg = plan["config"]
    extra = dict(cfg.get("extra_config") or {}) if isinstance(cfg.get("extra_config"), dict) else {}
    for session_key, yaml_key in CALIBRATION_SESSION_FIELDS:
        raw = st.session_state.get(session_key)
        if raw is None or raw == "":
            continue
        if session_key in ("iterations", "population_size"):
            try:
                numeric = int(raw)
            except (TypeError, ValueError):
                continue
            cfg[session_key] = str(numeric)
            cfg[yaml_key] = numeric
            extra[session_key] = str(numeric)
            extra[yaml_key] = numeric
            continue
        val = s(raw)
        if val:
            cfg[session_key] = val
            cfg[yaml_key] = val
            extra[session_key] = val
            extra[yaml_key] = val
    if extra:
        cfg["extra_config"] = extra
    st.session_state.run_plan = plan


def merge_calibration_into_spec(spec: dict, plan_cfg: dict | None = None) -> dict:
    values = get_calibration_config_values(plan_cfg)
    extra: dict = {}
    if isinstance((plan_cfg or {}).get("extra_config"), dict):
        extra.update((plan_cfg or {}).get("extra_config"))
    for session_key, yaml_key in CALIBRATION_SESSION_FIELDS:
        raw = values.get(session_key) or st.session_state.get(session_key)
        if raw is None or raw == "":
            continue
        if session_key in ("iterations", "population_size"):
            val: str | int = int(raw)
        else:
            val = s(raw)
        spec[session_key] = val
        spec[yaml_key] = val
        extra[session_key] = str(val)
    if extra:
        spec["extra_config"] = {**(spec.get("extra_config") or {}), **extra}
    return spec


def get_advanced_config_values(plan_cfg: dict | None = None) -> dict[str, str]:
    from server.core.ui_config_fields import lookup_plan_config

    plan_cfg = plan_cfg or {}
    values: dict[str, str] = {}
    for session_key, yaml_key, _ in ADVANCED_SESSION_FIELDS:
        val = s(lookup_plan_config(plan_cfg, session_key, yaml_key)) or s(st.session_state.get(session_key))
        if val:
            values[session_key] = val
    return values


def apply_advanced_config_from_plan(cfg: dict) -> None:
    extra = cfg.get("extra_config") if isinstance(cfg.get("extra_config"), dict) else {}
    for session_key, yaml_key, _ in ADVANCED_SESSION_FIELDS:
        val = s(cfg.get(session_key)) or s(cfg.get(yaml_key)) or s(extra.get(session_key)) or s(extra.get(yaml_key))
        if val:
            st.session_state[session_key] = val
    apply_calibration_config_from_plan(cfg)


def merge_advanced_into_spec(spec: dict, plan_cfg: dict | None = None) -> dict:
    values = get_advanced_config_values(plan_cfg)
    extra: dict = {}
    if isinstance((plan_cfg or {}).get("extra_config"), dict):
        extra.update((plan_cfg or {}).get("extra_config"))
    for session_key, yaml_key, _ in ADVANCED_SESSION_FIELDS:
        val = values.get(session_key)
        if val:
            spec[session_key] = val
            spec[yaml_key] = val
            extra[session_key] = val
    if extra:
        spec["extra_config"] = extra
    return merge_calibration_into_spec(spec, plan_cfg)


def sync_advanced_config_to_plan() -> None:
    if not st.session_state.get("run_plan"):
        return
    plan = st.session_state.run_plan
    plan.setdefault("config", {})
    values = get_advanced_config_values()
    extra = {k: v for k, v in values.items() if v}
    if extra:
        plan["config"]["extra_config"] = extra
        for k, v in extra.items():
            plan["config"][k] = v
    st.session_state.run_plan = plan


def render_advanced_config_section() -> None:
    from server.core.ui_config_fields import (
        PET_METHOD_OPTIONS,
        coerce_selectbox_value,
        normalize_pet_method,
    )
    from widget_keys import input_panel_widget_key

    with st.expander("Advanced config", expanded=False):
        st.caption("Optional SYMFLUENCE settings synced to the plan and generated config.yaml.")
        c1, c2 = st.columns(2)
        with c1:
            st.session_state.streamflow_data_provider = st.selectbox(
                "Streamflow data provider",
                options=["WSC", "USGS", "VI", "NIWA"],
                index=["WSC", "USGS", "VI", "NIWA"].index(
                    st.session_state.get("streamflow_data_provider", "WSC")
                )
                if st.session_state.get("streamflow_data_provider", "WSC") in ["WSC", "USGS", "VI", "NIWA"]
                else 0,
                key=input_panel_widget_key("adv_streamflow_data_provider"),
            )
            st.session_state.station_id = st.text_input(
                "Station ID",
                value=s(st.session_state.get("station_id")),
                placeholder="Leave blank to auto-pick nearest gauge from pour point",
                help="Optional. WSC example: 05BB001. Blank + WSC provider auto-selects the nearest Environment Canada gauge.",
                key=input_panel_widget_key("adv_station_id"),
            )
            st.session_state.routing_model = st.text_input(
                "Routing model",
                value=s(st.session_state.get("routing_model")) or "mizuRoute",
                key=input_panel_widget_key("adv_routing_model"),
            )
            stream_threshold_raw = st.session_state.get("stream_threshold")
            stream_threshold_default = 1000
            if stream_threshold_raw not in (None, ""):
                try:
                    stream_threshold_default = int(float(stream_threshold_raw))
                except (TypeError, ValueError):
                    pass
            st.session_state.stream_threshold = st.number_input(
                "Stream threshold",
                min_value=100,
                max_value=50000,
                value=stream_threshold_default,
                step=100,
                help=(
                    "TauDEM flow-accumulation cutoff for stream delineation. "
                    "Use a lower value for small domains (e.g. 1000); 5000 can yield no streams."
                ),
                key=input_panel_widget_key("adv_stream_threshold"),
            )
        with c2:
            pet_value = coerce_selectbox_value(
                st.session_state.get("pet_method", "oudin"),
                PET_METHOD_OPTIONS,
                normalizer=normalize_pet_method,
            )
            st.session_state.pet_method = st.selectbox(
                "PET method",
                options=PET_METHOD_OPTIONS,
                index=PET_METHOD_OPTIONS.index(pet_value),
                key=input_panel_widget_key("adv_pet_method"),
            )
            from server.core.period_utils import normalize_period_text

            st.session_state.spinup_period = normalize_period_text(
                st.text_input(
                    "Spinup period",
                    value=s(st.session_state.get("spinup_period")),
                    placeholder="2004-01-01, 2004-01-04",
                    key=input_panel_widget_key("adv_spinup_period"),
                )
            )
            st.session_state.calibration_period = normalize_period_text(
                st.text_input(
                    "Calibration period",
                    value=s(st.session_state.get("calibration_period")),
                    key=input_panel_widget_key("adv_calibration_period"),
                )
            )
            st.session_state.evaluation_period = normalize_period_text(
                st.text_input(
                    "Evaluation period",
                    value=s(st.session_state.get("evaluation_period")),
                    key=input_panel_widget_key("adv_evaluation_period"),
                )
            )
        sync_advanced_config_to_plan()


def augment_request_with_advanced(lines: list[str]) -> list[str]:
    for session_key, _, label in ADVANCED_SESSION_FIELDS:
        val = s(st.session_state.get(session_key))
        if val:
            lines.append(f"- {session_key}: {val}")
    return lines


def augment_request_with_calibration(lines: list[str], nl_request: str = "") -> list[str]:
    """Only pass calibration widget values that the user named in the main prompt."""
    try:
        from calib_hydro_agent.prompt_fields import explicit_calibration_fields_in_prompt
    except ImportError:
        return lines

    explicit = explicit_calibration_fields_in_prompt(nl_request)
    extra_fields = [
        ("params_to_calibrate", "PARAMS_TO_CALIBRATE"),
        ("basin_params_to_calibrate", "BASIN_PARAMS_TO_CALIBRATE"),
    ]
    all_fields = list(CALIBRATION_SESSION_FIELDS) + extra_fields
    for session_key, yaml_key in all_fields:
        if session_key not in explicit:
            continue
        raw = st.session_state.get(session_key)
        if raw is None or raw == "":
            continue
        val = str(int(raw)) if session_key in ("iterations", "population_size") else s(raw)
        if val:
            lines.append(f"- {session_key}: {val}")
    return lines


def flow_duration_curve(flow: pd.Series) -> pd.DataFrame:
    q = flow.dropna().astype(float).sort_values(ascending=False)
    n = len(q)
    if n == 0:
        return pd.DataFrame(columns=["exceedance_pct", "flow_m3s"])
    ranks = pd.Series(range(1, n + 1), index=q.index)
    exceedance = 100.0 * ranks / (n + 1)
    return pd.DataFrame({"exceedance_pct": exceedance.values, "flow_m3s": q.values})


def discover_saved_plots(ctx: dict, *, max_files: int = 200) -> list[dict]:
    domain_root = ctx.get("domain_root")
    exp_id = ctx.get("experiment_id") or ""
    if not domain_root or not Path(domain_root).exists():
        return []

    search_roots = [
        Path(domain_root) / "plots",
        Path(domain_root) / "summaries",
        Path(domain_root) / "simulations" / exp_id / "SUMMA",
        Path(domain_root) / "simulations" / exp_id / "mizuRoute",
        Path(domain_root) / "simulations" / exp_id,
        Path(domain_root) / "evaluations",
        Path(domain_root),
    ]
    seen: set[str] = set()
    rows: list[dict] = []
    for root in search_roots:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in PLOT_EXTENSIONS:
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                try:
                    rel = path.relative_to(Path(domain_root))
                except ValueError:
                    rel = path.name
                rows.append(
                    {
                        "name": path.name,
                        "relative": str(rel),
                        "path": key,
                        "modified": dt.datetime.fromtimestamp(path.stat().st_mtime).strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                        "size_kb": round(path.stat().st_size / 1024, 1),
                    }
                )
                if len(rows) >= max_files:
                    break
        except Exception:
            continue
        if len(rows) >= max_files:
            break
    rows.sort(key=lambda r: r["modified"], reverse=True)
    return rows


def render_saved_plots_browser(ctx: dict, *, key_prefix: str = "plots") -> None:
    plots = discover_saved_plots(ctx)
    if not plots:
        st.info(
            "No plot images found under the domain folder. "
            "SYMFLUENCE may write to `plots/`, `summaries/`, or simulation subfolders after postprocess."
        )
        return

    st.caption(f"Found {len(plots)} image/PDF file(s).")
    df = pd.DataFrame(plots)
    st.dataframe(df[["name", "relative", "modified", "size_kb"]], width="stretch", hide_index=True)

    names = [p["name"] for p in plots]
    default_idx = 0
    selected_name = st.selectbox("Preview plot", names, index=default_idx, key=f"{key_prefix}_select")
    selected = next(p for p in plots if p["name"] == selected_name)
    path = Path(selected["path"])
    st.caption(f"`{selected['path']}`")
    if path.suffix.lower() == ".pdf":
        st.info("PDF preview is not embedded; open the file path locally.")
        with path.open("rb") as f:
            st.download_button("Download PDF", f, file_name=path.name, key=f"{key_prefix}_dl_pdf")
    else:
        st.image(str(path), width="stretch")


def render_flow_duration_tab(ctx: dict, symfluence_data_dir: Path) -> None:
    st.caption("Flow duration curves (exceedance % vs discharge). Uses observed and/or simulated daily series.")
    merged, err = load_aligned_hydrograph_frames(ctx, symfluence_data_dir)
    sim_path = resolve_simulated_flow_path(ctx)
    if merged is None and sim_path is None:
        st.info(err or "Load routed_flow.csv or observed streamflow first.")
        return

    fdc_frames: dict[str, pd.DataFrame] = {}
    if merged is not None:
        if "observed" in merged.columns:
            fdc_frames["observed"] = flow_duration_curve(merged["observed"])
        if "simulated" in merged.columns:
            fdc_frames["simulated"] = flow_duration_curve(merged["simulated"])
    elif sim_path and sim_path.exists():
        sim_df = pd.read_csv(sim_path, parse_dates=["time"])
        qcol = "IRFroutedRunoff" if "IRFroutedRunoff" in sim_df.columns else [c for c in sim_df.columns if c.lower() != "time"][0]
        fdc_frames["simulated"] = flow_duration_curve(sim_df[qcol])

    if not fdc_frames:
        st.info("No flow series available for FDC.")
        return

    chart_df = pd.DataFrame(
        {
            name: fdc.set_index("exceedance_pct")["flow_m3s"]
            for name, fdc in fdc_frames.items()
        }
    )
    st.line_chart(chart_df)
    for name, fdc in fdc_frames.items():
        with st.expander(f"FDC table — {name}", expanded=False):
            st.dataframe(fdc, width="stretch", hide_index=True)


def render_calibration_agent_section(
    *,
    run_agent_fn,
    location: str = "assistant",
) -> None:
    """Calibration UI wired to CalibHydroAgent (design → validate → run → interpret)."""
    from widget_keys import input_panel_widget_key
    from server.calibration.agent_integration import calib_agent_available, calib_agent_import_error

    prefix = f"calib_agent_{location}"
    with st.expander(
        "Calibration agent (CalibHydroAgent)",
        expanded=False,
        key=f"{prefix}_expander",
    ):
        if not calib_agent_available():
            st.warning(
                "CalibHydroAgent not found. Install sibling repo or set "
                "`CALIB_HYDRO_AGENT_REPO` to `/path/to/CalibHydroAgent`."
            )
            err = calib_agent_import_error()
            if err:
                st.caption(err)
            return

        st.caption(
            "Workflow steps come from the **calibration plan**. Algorithm, metric, parameters, and periods "
            "are chosen by the agent from your **main prompt** (and SUMMA defaults) unless you name them "
            "explicitly there — dropdowns update after **Design & validate**."
        )
        c1, c2 = st.columns(2)
        with c1:
            st.session_state.iterative_optimization_algorithm = st.selectbox(
                "Algorithm",
                CALIBRATION_ALGORITHMS,
                index=CALIBRATION_ALGORITHMS.index(
                    st.session_state.get("iterative_optimization_algorithm", "DE")
                )
                if st.session_state.get("iterative_optimization_algorithm", "DE") in CALIBRATION_ALGORITHMS
                else 0,
                key=input_panel_widget_key(f"{prefix}_algorithm"),
            )
            st.session_state.optimization_metric = st.selectbox(
                "Metric",
                CALIBRATION_METRICS,
                index=CALIBRATION_METRICS.index(st.session_state.get("optimization_metric", "KGE"))
                if st.session_state.get("optimization_metric", "KGE") in CALIBRATION_METRICS
                else 0,
                key=input_panel_widget_key(f"{prefix}_metric"),
            )
            st.session_state.optimization_target = st.selectbox(
                "Target",
                CALIBRATION_TARGETS,
                index=CALIBRATION_TARGETS.index(
                    st.session_state.get("optimization_target", "streamflow")
                )
                if st.session_state.get("optimization_target", "streamflow") in CALIBRATION_TARGETS
                else 0,
                key=input_panel_widget_key(f"{prefix}_target"),
            )
        with c2:
            st.session_state.calibration_timestep = st.selectbox(
                "Calibration timestep",
                CALIBRATION_TIMESTEPS,
                index=CALIBRATION_TIMESTEPS.index(
                    st.session_state.get("calibration_timestep", "daily")
                )
                if st.session_state.get("calibration_timestep", "daily") in CALIBRATION_TIMESTEPS
                else 2,
                key=input_panel_widget_key(f"{prefix}_timestep"),
            )
            st.session_state.iterations = int(
                st.number_input(
                    "Iterations",
                    min_value=1,
                    max_value=5000,
                    value=int(st.session_state.get("iterations", 20) or 20),
                    key=input_panel_widget_key(f"{prefix}_iterations"),
                )
            )
            st.session_state.population_size = int(
                st.number_input(
                    "Population size",
                    min_value=2,
                    max_value=500,
                    value=int(st.session_state.get("population_size", 10) or 10),
                    key=input_panel_widget_key(f"{prefix}_population"),
                )
            )
        from server.core.period_utils import normalize_period_text

        st.session_state.calibration_period = normalize_period_text(
            st.text_input(
                "Calibration period",
                value=s(st.session_state.get("calibration_period")),
                placeholder="2004-01-05, 2004-01-19",
                help="Format: YYYY-MM-DD, YYYY-MM-DD (dates only — no HH:MM).",
                key=input_panel_widget_key(f"{prefix}_calibration_period"),
            )
        )
        sync_calibration_config_to_plan()
        sync_advanced_config_to_plan()

        auto_replan = st.checkbox(
            "Suggest replan after run",
            value=st.session_state.get("calib_agent_auto_replan", False),
            key=input_panel_widget_key(f"{prefix}_auto_replan"),
        )
        st.session_state.calib_agent_auto_replan = auto_replan

        st.markdown("**Sensitivity-guided parameters**")
        sensitivity_guided = st.checkbox(
            "Screen → sensitivity → top N → calibrate",
            value=bool(st.session_state.get("calib_agent_sensitivity_guided", False)),
            help=(
                "Run a short screening calibration on the full default parameter set, "
                "rank parameters with Symfluence sensitivity analysis, keep the top N, "
                "then run the final calibration."
            ),
            key=input_panel_widget_key(f"{prefix}_sensitivity_guided"),
        )
        st.session_state.calib_agent_sensitivity_guided = sensitivity_guided
        s1, s2 = st.columns(2)
        with s1:
            st.session_state.calib_agent_top_n_params = int(
                st.number_input(
                    "Top N parameters",
                    min_value=1,
                    max_value=20,
                    value=int(st.session_state.get("calib_agent_top_n_params", 4) or 4),
                    disabled=not sensitivity_guided,
                    key=input_panel_widget_key(f"{prefix}_top_n"),
                )
            )
        with s2:
            st.session_state.calib_agent_screening_iterations = int(
                st.number_input(
                    "Screening iterations",
                    min_value=10,
                    max_value=500,
                    value=int(st.session_state.get("calib_agent_screening_iterations", 30) or 30),
                    disabled=not sensitivity_guided,
                    help="Short calibration used to sample the parameter space for sensitivity (minimum 10).",
                    key=input_panel_widget_key(f"{prefix}_screening_iters"),
                )
            )

        b1, b2 = st.columns(2)
        disabled = not st.session_state.get("allow_run")
        with b1:
            if st.button(
                "Design & validate config",
                key=f"{prefix}_design",
                width="stretch",
            ):
                run_agent_fn(mode="design")
        with b2:
            if st.button(
                "Run calibration (agent)",
                key=f"{prefix}_run",
                width="stretch",
                disabled=disabled,
            ):
                run_agent_fn(mode="run")
        if disabled:
            st.caption("Enable **Allow dangerous run steps** to execute calibration.")

        last = st.session_state.get("calib_agent_last_outcome")
        if isinstance(last, dict):
            st.markdown("**Last agent outcome**")
            stopped = last.get("stopped")
            if stopped:
                st.info(f"Stopped: `{stopped}`")
            spec = last.get("spec") or {}
            if spec:
                st.caption(
                    f"Model `{spec.get('model')}` · {spec.get('algorithm')} · "
                    f"{spec.get('optimization_metric')} · {spec.get('number_of_iterations')} iter"
                )
            validation = last.get("validation") or {}
            for issue in validation.get("issues") or []:
                if issue.get("severity") == "error":
                    st.error(issue.get("message"))
                elif issue.get("severity") == "warning":
                    st.warning(issue.get("message"))
            prereq = last.get("prerequisites") or {}
            if prereq.get("missing_steps"):
                st.warning("Missing steps: " + ", ".join(prereq["missing_steps"]))
            for note in prereq.get("notes") or []:
                st.caption(note)
            interp = last.get("interpretation")
            if isinstance(interp, dict) and interp.get("summary"):
                st.success(interp["summary"])
                for fm in interp.get("failure_modes") or []:
                    st.error(fm)
            replan = last.get("replan")
            if isinstance(replan, dict) and replan.get("action"):
                st.info(f"Replan: **{replan['action']}** — {replan.get('rationale')}")
            sensitivity = last.get("sensitivity")
            if isinstance(sensitivity, dict) and sensitivity.get("enabled"):
                st.markdown("**Sensitivity guidance**")
                if sensitivity.get("message"):
                    st.caption(sensitivity["message"])
                selected = (sensitivity.get("selected_params") or []) + (
                    sensitivity.get("selected_basin_params") or []
                )
                if selected:
                    st.success("Selected parameters: " + ", ".join(selected))
                elif sensitivity_guided := sensitivity.get("top_n"):
                    st.caption(
                        f"Will pick top {sensitivity_guided} after screening "
                        f"({sensitivity.get('screening_iterations', '?')} iter)."
                    )


def render_results_page(*, symfluence_data_dir: Path, runs_dir: Path) -> None:
    st.subheader("Results")
    st.caption("Saved plots and figures for the active domain/experiment.")
    ctx = workflow_context(runs_dir=runs_dir, symfluence_data_dir=symfluence_data_dir)
    if not ctx.get("domain_name") or not ctx.get("experiment_id"):
        st.info("Set domain and experiment on **Workflows → Input**, or load a run from **Experiments**.")
        return
    render_saved_plots_browser(ctx, key_prefix="results_page")


def run_py_tool(script_path: str, args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    from server.core.safe_subprocess import run_command

    cmd = [sys.executable, script_path] + args
    return run_command(cmd, cwd=cwd)


def render_run_results_section(
    *,
    cfg: dict,
    runs_dir: Path,
    symfluence_data_dir: Path,
    layer_paths_fn,
    default_postprocess_domain_dir_fn,
    run_py_tool_fn=run_py_tool,
) -> None:
    st.subheader("Run results")
    ctx = workflow_context(runs_dir=runs_dir, symfluence_data_dir=symfluence_data_dir)
    layer_paths = layer_paths_fn() if ctx.get("domain_name") and ctx.get("experiment_id") else {}

    hdr1, hdr2 = st.columns([1, 3])
    with hdr1:
        if st.button("Refresh scan", key="run_results_refresh", width="stretch"):
            st.session_state.run_results_scan_at = dt.datetime.now().isoformat(timespec="seconds")
            st.rerun()
    with hdr2:
        scanned = st.session_state.get("run_results_scan_at", "not yet")
        st.caption(f"Last scan: {scanned} — Domain `{ctx.get('domain_name') or '?'}` / Experiment `{ctx.get('experiment_id') or '?'}`")

    if not ctx.get("domain_name") or not ctx.get("experiment_id"):
        st.info("Set **Domain name** and **Experiment ID** on the Input tab to scan run artifacts.")
        return

    artifacts = scan_run_artifacts(ctx, layer_paths)
    found_n = sum(1 for a in artifacts if a["status"] == "found")
    st.caption(f"{found_n} of {len(artifacts)} artifacts found on disk.")

    tab_overview, tab_routed, tab_hydro, tab_metrics, tab_fdc, tab_plots = st.tabs(
        ["Overview", "Routed flow", "Hydrograph", "Metrics", "Flow duration", "Saved plots"]
    )

    with tab_overview:
        df_art = pd.DataFrame(artifacts)
        st.dataframe(
            df_art[["category", "artifact", "status", "path"]],
            width="stretch",
            hide_index=True,
        )

    mizu_dir = ctx.get("mizu_dir")
    domain_dir = default_postprocess_domain_dir_fn(cfg)
    exp_id = ctx.get("experiment_id") or s(st.session_state.experiment_id)
    csv_path = (mizu_dir / "routed_flow.csv") if mizu_dir else Path(domain_dir) / "simulations" / exp_id / "mizuRoute" / "routed_flow.csv"

    with tab_routed:
        st.caption("Extract routed discharge from mizuRoute NetCDF, then inspect `routed_flow.csv`.")
        st.text_input("Domain path", value=domain_dir, disabled=True, key="run_results_domain_dir_display")
        col_e, col_s = st.columns(2)
        with col_e:
            if st.button("Extract discharge → CSV", key="run_results_extract_routed"):
                if not mizu_dir or not mizu_dir.exists():
                    st.error("mizuRoute folder not found. Run the model with routing first.")
                else:
                    tool = str(ASSISTANT_BASE / "tools" / "extract_discharge.py")
                    rc, out, err = run_py_tool_fn(tool, [], cwd=mizu_dir)
                    if rc == 0:
                        st.success("Extract completed.")
                        if out.strip():
                            st.code(out)
                        st.rerun()
                    else:
                        st.error("Extract failed.")
                        if err.strip():
                            st.code(err)
        with col_s:
            if st.button("Summarize routed_flow.csv", key="run_results_summarize_routed"):
                if not csv_path.exists():
                    st.error("routed_flow.csv not found.")
                else:
                    tool = str(ASSISTANT_BASE / "tools" / "summarize_routed_flow.py")
                    rc, out, err = run_py_tool_fn(tool, ["--csv", str(csv_path)])
                    if rc == 0 and out.strip():
                        st.code(out)
                    elif err.strip():
                        st.code(err)
        if csv_path.exists():
            st.write(f"`{csv_path}`")
            df = pd.read_csv(csv_path, parse_dates=["time"])
            st.dataframe(df.head(50), width="stretch")
            qcol = [c for c in df.columns if c.lower() != "time"][0]
            st.line_chart(df.set_index("time")[qcol])
        else:
            st.info("No routed_flow.csv yet.")

    with tab_hydro:
        merged, err = load_aligned_hydrograph_frames(ctx, symfluence_data_dir)
        if merged is None:
            st.info(err)
        else:
            st.line_chart(merged)
            st.caption(f"{len(merged)} time steps loaded.")
            st.dataframe(merged.head(30), width="stretch")

    with tab_metrics:
        merged, err = load_aligned_hydrograph_frames(ctx, symfluence_data_dir)
        if merged is None:
            st.info(err)
        else:
            metrics = compute_quick_metrics(merged)
            mcols = st.columns(min(len(metrics), 4))
            for i, (k, v) in enumerate(metrics.items()):
                with mcols[i % len(mcols)]:
                    if isinstance(v, float):
                        st.metric(k, f"{v:.4f}" if v == v else "n/a")
                    else:
                        st.metric(k, str(v))
            if csv_path.exists():
                tool = str(ASSISTANT_BASE / "tools" / "summarize_routed_flow.py")
                rc, out, err = run_py_tool_fn(tool, ["--csv", str(csv_path)])
                if rc == 0 and out.strip():
                    st.markdown("**Routed-flow summary**")
                    st.code(out)

    with tab_fdc:
        render_flow_duration_tab(ctx, symfluence_data_dir)

    with tab_plots:
        render_saved_plots_browser(ctx, key_prefix="run_results_plots")


def render_data_page(
    *,
    runs_dir: Path,
    symfluence_data_dir: Path,
    layer_paths_fn,
) -> None:
    st.subheader("Data")
    st.caption("Artifact checklist for the current domain and experiment.")
    ctx = workflow_context(runs_dir=runs_dir, symfluence_data_dir=symfluence_data_dir)
    if not ctx.get("domain_name") or not ctx.get("experiment_id"):
        st.info("Configure domain and experiment on **Workflows → Input** first.")
        return
    assistant_run = ctx.get("assistant_run")
    if assistant_run:
        from server.core.calibration_logs import persist_calibration_logs_for_run

        persist_calibration_logs_for_run(assistant_run)
    layer_paths = layer_paths_fn()
    artifacts = scan_run_artifacts(ctx, layer_paths)
    for row in artifacts:
        icon = "✅" if row["status"] == "found" else "❌" if row["status"] == "missing" else "⚪"
        st.markdown(f"{icon} **{row['artifact']}** — `{row['path']}`")


def tail_file(path: Path, n_lines: int = 80) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n_lines:])


def render_logs_page(*, runs_dir: Path, run_folder_skip: set[str]) -> None:
    st.subheader("Logs")
    runs = sorted(
        p
        for p in runs_dir.iterdir()
        if p.is_dir() and p.name not in run_folder_skip
    ) if runs_dir.exists() else []
    if not runs:
        st.info(f"No runs under `{runs_dir}`.")
        return
    names = [p.name for p in runs]
    default = s(st.session_state.get("run_folder"))
    idx = names.index(default) if default in names else 0
    selected = st.selectbox("Run folder", names, index=idx, key="logs_run_select")
    run_dir = runs_dir / selected
    from server.core.calibration_logs import persist_calibration_logs_for_run

    persist_calibration_logs_for_run(run_dir)
    logs_dir = run_dir / "logs"
    log_files = sorted(p for p in logs_dir.glob("*.log") if p.is_file()) if logs_dir.is_dir() else []
    st.markdown(f"**Run directory:** `{run_dir}`")
    if not log_files:
        st.warning("No log files for this run yet.")
    else:
        log_names = [p.name for p in log_files]
        default_log = "calibration.log" if "calibration.log" in log_names else "execution.log"
        log_idx = log_names.index(default_log) if default_log in log_names else 0
        chosen = st.selectbox("Log file", log_names, index=log_idx, key="logs_file_select")
        log_path = logs_dir / chosen
        st.caption(f"Log file: `{log_path}` ({log_path.stat().st_size} bytes)")
        n_tail = st.slider("Lines to show", 20, 5000, 400, key="logs_tail_lines")
        st.code(tail_file(log_path, n_tail) or "(empty log)")
    if (run_dir / "config.yaml").exists():
        with st.expander("config.yaml"):
            st.code((run_dir / "config.yaml").read_text(encoding="utf-8")[:12000])


def render_dashboard_page(
    *,
    runs_dir: Path,
    symfluence_repo: Path,
    symfluence_data_dir: Path,
    symfluence_python: Path,
    render_workflow_progress_fn,
    run_folder_skip: set[str],
) -> None:
    st.subheader("Dashboard")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            '<div class="metric-card"><div class="metric-label">SYMFLUENCE repo</div><div class="metric-value">'
            + ("Found ✅" if symfluence_repo.exists() else "Missing ❌")
            + "</div></div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            '<div class="metric-card"><div class="metric-label">Data folder</div><div class="metric-value">'
            + ("Found ✅" if symfluence_data_dir.exists() else "Missing ⚠️")
            + "</div></div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            '<div class="metric-card"><div class="metric-label">Python</div><div class="metric-value">'
            + ("Found ✅" if symfluence_python.exists() else "Missing ❌")
            + "</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("#### Current workflow")
    ctx = workflow_context(runs_dir=runs_dir, symfluence_data_dir=symfluence_data_dir)
    st.write(
        f"- Domain: `{ctx.get('domain_name') or '(not set)'}`\n"
        f"- Experiment: `{ctx.get('experiment_id') or '(not set)'}`\n"
        f"- Run folder: `{ctx.get('run_folder') or '(not set)'}`"
    )
    plan = st.session_state.get("run_plan")
    if plan:
        st.markdown(render_workflow_progress_fn(plan, st.session_state.get("execution_log_text", "")))
        needs = plan.get("needs_user_input") or []
        if needs:
            st.warning("Missing inputs: " + ", ".join(needs))
        else:
            st.success("Plan ready to execute.")
    else:
        st.info("No active plan. Use **Workflows** to generate one.")

    st.markdown("#### Recent assistant runs")
    rows = []
    for name in list_assistant_run_dirs(runs_dir, run_folder_skip)[:12]:
        run_dir = runs_dir / name
        log_path = run_dir / "logs" / "execution.log"
        mtime = dt.datetime.fromtimestamp(run_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        status = "has log" if log_path.exists() else "no log"
        if log_path.exists() and "[STEP " in log_path.read_text(encoding="utf-8", errors="replace"):
            if "return code: 0" in log_path.read_text(encoding="utf-8", errors="replace"):
                status = "steps run"
        rows.append({"run_folder": name, "updated": mtime, "status": status})
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.caption(f"No runs in `{runs_dir}` yet.")


def list_assistant_run_dirs(runs_dir: Path, skip: set[str]) -> list[str]:
    if not runs_dir.exists():
        return []
    return sorted(p.name for p in runs_dir.iterdir() if p.is_dir() and p.name not in skip)


def render_experiments_page(
    *,
    runs_dir: Path,
    run_folder_skip: set[str],
    load_run_fn=None,
) -> None:
    st.subheader("Experiments")
    st.caption("Past assistant runs under the local `runs/` folder.")
    flash = st.session_state.pop("_experiments_load_flash", None)
    if flash:
        kind, payload = flash
        if kind == "error":
            st.error(payload)
        else:
            st.success(
                f"Loaded `{payload}` into workflow. "
                "Open **Workflows** and select **Output** to view the config preview."
            )
    rows = []
    for name in list_assistant_run_dirs(runs_dir, run_folder_skip):
        run_dir = runs_dir / name
        log_path = run_dir / "logs" / "execution.log"
        plan_path = run_dir / "plan.json"
        cfg_path = run_dir / "config.yaml"
        exp_id = ""
        domain = ""
        steps_n = 0
        if plan_path.exists():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                cfg = plan.get("config") or {}
                exp_id = s(cfg.get("experiment_id"))
                domain = s(cfg.get("domain_name"))
                steps_n = len(plan.get("steps") or [])
            except Exception:
                pass
        if cfg_path.exists() and not exp_id:
            try:
                y = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                exp_id = s(y.get("EXPERIMENT_ID"))
                domain = s(y.get("DOMAIN_NAME"))
            except Exception:
                pass
        log_status = "—"
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            if "return code: 0" in text:
                log_status = "ok"
            elif "return code:" in text:
                log_status = "failed"
            else:
                log_status = "started"
        rows.append(
            {
                "run_folder": name,
                "domain": domain,
                "experiment_id": exp_id,
                "steps": steps_n,
                "log": log_status,
                "updated": dt.datetime.fromtimestamp(run_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "path": str(run_dir),
            }
        )
    if not rows:
        st.info("No experiment runs saved yet.")
        return
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    pick = st.selectbox("Open run", [r["run_folder"] for r in rows], key="experiments_pick_run")
    if st.button("Load run into workflow", key="experiments_load_run"):
        if load_run_fn:
            err = load_run_fn(pick)
            if err:
                st.session_state["_experiments_load_flash"] = ("error", err)
            else:
                st.session_state["_experiments_load_flash"] = ("success", pick)
            st.rerun()

def render_run_shortcuts_section(
    *,
    execute_bundle_fn,
    location: str = "input",
) -> None:
    prefix = f"shortcut_{location}"
    with st.expander("Run shortcuts", expanded=False):
        st.caption("Run common step bundles using the current config. Dangerous bundles require **Allow dangerous run steps**.")
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("Run preprocessing", key=f"{prefix}_preprocessing", width="stretch"):
                execute_bundle_fn("preprocessing")
        with b2:
            disabled = not st.session_state.get("allow_run")
            if st.button(
                "Run model",
                key=f"{prefix}_model",
                width="stretch",
                disabled=disabled,
            ):
                execute_bundle_fn("model")
        with b3:
            if st.button(
                "Run postprocess",
                key=f"{prefix}_postprocess",
                width="stretch",
                disabled=disabled,
            ):
                execute_bundle_fn("postprocess")
        if not st.session_state.get("allow_run"):
            st.caption("Enable **Allow dangerous run steps** in the assistant panel for model and postprocess shortcuts.")
