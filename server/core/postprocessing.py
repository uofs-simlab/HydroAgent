"""Read experiment discharge outputs and prepare daily evaluation data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from server.core.period_utils import normalize_period_text
from server.core.ui_config_fields import lookup_plan_config


def discharge_output_paths(
    domain_root: Path, experiment_id: str, *, sim_reach_id=None,
    routed_flow_errors: list[str] | None = None,
) -> list[Path]:
    """Prefer standard postprocessing outputs; never fall back to another run."""
    candidates = [
        domain_root / "results" / f"{experiment_id}_results.csv",
        domain_root / "results" / f"{experiment_id}_calibrated_results.csv",
    ]
    from server.core.routed_flow import ensure_routed_flow_csv

    try:
        routed = ensure_routed_flow_csv(
            domain_root / "simulations" / experiment_id / "mizuRoute", sim_reach_id,
        )
    except (OSError, ValueError, ImportError) as exc:
        if routed_flow_errors is not None:
            routed_flow_errors.append(str(exc))
    else:
        if routed is not None:
            candidates.append(routed)
    return [path for path in candidates if path.is_file()]


def load_daily_discharge(path: Path, *, observed: bool = False) -> pd.DataFrame:
    """Load known discharge columns in m³/s, excluding invalid samples."""
    frame = pd.read_csv(path)
    time_col = next(
        (col for col in frame.columns if col.lower() in {"time", "datetime", "date", "unnamed: 0"}),
        None,
    )
    if time_col is None:
        raise ValueError(f"{path.name} has no time or datetime column.")
    names = (
        {"discharge_cms", "discharge_m3s", "observed", "q_obs"}
        if observed
        else {"discharge_cms", "discharge_m3s", "irfroutedrunoff", "kwtroutedrunoff", "averageroutedrunoff", "simulated", "q_sim"}
    )
    flow_cols = [
        col for col in frame.columns
        if col.lower() in names or (not observed and col.lower().endswith("_discharge_cms"))
    ]
    if not flow_cols:
        raise ValueError(f"{path.name} has no recognized discharge column in m³/s.")
    times = pd.to_datetime(frame[time_col], errors="coerce", utc=True, format="mixed")
    values = frame[flow_cols].apply(pd.to_numeric, errors="coerce")
    values = values.replace([float("inf"), float("-inf")], float("nan"))
    values = values.where(values >= 0)
    values.index = pd.DatetimeIndex(times).tz_convert(None)
    values.index.name = "time"
    values = values.loc[values.index.notna()].dropna(how="all")
    if values.empty:
        raise ValueError(f"{path.name} has no valid discharge samples.")
    # Combine repeated timestamps before daily averaging so duplicates carry no extra weight.
    daily = values.groupby(level=0).mean().resample("D").mean()
    if observed:
        if "discharge_cms" in daily:
            daily = daily[["discharge_cms"]]
        elif len(daily.columns) != 1:
            raise ValueError(f"{path.name} has multiple observed discharge columns.")
        daily.columns = ["observed"]
    return daily


def _utc_day(value) -> pd.Timestamp:
    """Use the same UTC day boundaries as load_daily_discharge."""
    stamp = pd.to_datetime(value, utc=True)
    if pd.isna(stamp):
        raise ValueError("Missing date")
    return stamp.tz_convert(None).normalize()


def configured_period(cfg: dict, field: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    raw = lookup_plan_config(cfg, field, field.upper())
    if raw is None or str(raw).strip().lower() in {"", "default", "none"}:
        return None
    text = normalize_period_text(str(raw))
    parts = text.split(",")
    try:
        if len(parts) != 2:
            raise ValueError
        start, end = (_utc_day(part.strip()) for part in parts)
        if start > end:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {field.replace('_', ' ')}: {raw}") from exc
    return start, end


def prepare_daily_comparison(
    simulated: pd.Series,
    observed: pd.DataFrame | None,
    cfg: dict,
    *,
    evaluation: bool = True,
) -> pd.DataFrame:
    """Align daily means, excluding configured spin-up dates only for evaluation."""
    simulated = simulated.rename("simulated")
    available = simulated.dropna()
    if available.empty:
        return pd.DataFrame(columns=["simulated"], index=pd.DatetimeIndex([], name="time"))
    start, end = available.index.min(), available.index.max()
    for field in ("experiment_time_start", "experiment_time_end"):
        raw = lookup_plan_config(cfg, field, field.upper())
        if raw is None or str(raw).strip().lower() in {"", "default", "none"}:
            continue
        try:
            stamp = _utc_day(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid {field.replace('_', ' ')}: {raw}") from exc
        if field.endswith("start"):
            start = max(start, stamp)
        else:
            end = min(end, stamp)
    if evaluation and (period := configured_period(cfg, "evaluation_period")):
        start, end = max(start, period[0]), min(end, period[1])
    frame = pd.concat([observed, simulated], axis=1) if observed is not None else simulated.to_frame()
    frame = frame.loc[(frame.index >= start) & (frame.index <= end)]
    if evaluation and (spinup := configured_period(cfg, "spinup_period")):
        frame = frame.loc[(frame.index < spinup[0]) | (frame.index > spinup[1])]
    frame.index.name = "time"
    return frame.dropna(how="all")
