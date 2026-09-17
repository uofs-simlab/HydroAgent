"""Extract the configured mizuRoute reach, retaining cache provenance."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

ROUTING_VARS = ("IRFroutedRunoff", "KWTroutedRunoff", "averageRoutedRunoff")
REACH_ID_VARS = ("reachID", "segId", "segID", "reach_id", "seg_id")


class RoutedFlowError(ValueError):
    """The requested routed discharge cannot be selected or verified."""


def mizu_history_files(mizu_dir: Path) -> list[Path]:
    if not mizu_dir.is_dir():
        return []
    history = sorted(mizu_dir.glob("*.h.*.nc"))
    return [path for path in (history or sorted(mizu_dir.glob("*.nc"))) if path.is_file()]


def _file_signature(path: Path) -> dict:
    stat = path.stat()
    return {"name": path.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _reach_id(value) -> int | None:
    if value is None or str(value).strip().lower() in {"", "default", "none"}:
        return None
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise RoutedFlowError(f"SIM_REACH_ID must be an integer reach ID, got {value!r}.") from exc


def _reach_series(ds, variable, reach_id: int | None):
    import numpy as np

    time_dims = ds.variables["time"].dimensions
    if len(time_dims) != 1 or time_dims[0] not in variable.dimensions:
        raise RoutedFlowError("Routed discharge must have a time dimension.")
    time_dim = time_dims[0]
    selectors = {dim: slice(None) for dim in variable.dimensions}
    ids_var = next((ds.variables[name] for name in REACH_ID_VARS
                    if name in ds.variables and ds.variables[name].ndim == 1
                    and ds.variables[name].dimensions[0] in variable.dimensions
                    and ds.variables[name].dimensions[0] != time_dim), None)
    if ids_var is not None:
        ids = np.ma.asarray(ids_var[:])
        if reach_id is None:
            if ids.size != 1:
                raise RoutedFlowError("Set SIM_REACH_ID to select an outlet from multi-reach mizuRoute output.")
            index = 0
        else:
            matches = np.flatnonzero(np.ma.filled(ids == reach_id, False))
            if len(matches) != 1:
                raise RoutedFlowError(f"SIM_REACH_ID {reach_id} does not uniquely identify a reach in the history file.")
            index = int(matches[0])
        selectors[ids_var.dimensions[0]] = index
    elif reach_id is not None:
        raise RoutedFlowError("History file has no reach IDs to verify SIM_REACH_ID.")

    for dim in variable.dimensions:
        if dim != time_dim and isinstance(selectors[dim], slice):
            if len(ds.dimensions[dim]) != 1:
                raise RoutedFlowError(f"Cannot select routed discharge along dimension {dim!r}; reach IDs are required.")
            selectors[dim] = 0
    return np.ma.asarray(variable[tuple(selectors[dim] for dim in variable.dimensions)], dtype=float).filled(float("nan"))


def ensure_routed_flow_csv(mizu_dir: Path | None, sim_reach_id=None) -> Path | None:
    """Refresh routed_flow.csv when its reach or history files change.

    A legacy standalone CSV is readable without a requested reach. With history
    files, an explicit reach (or an unambiguous single reach) is always required.
    A sidecar records the selection and source signatures; unverified CSVs are
    never returned as a fallback when extraction fails.
    """
    if mizu_dir is None:
        return None
    mizu_dir = Path(mizu_dir)
    reach_id = _reach_id(sim_reach_id)
    csv_path = mizu_dir / "routed_flow.csv"
    metadata_path = mizu_dir / "routed_flow.meta.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metadata = None
    if not isinstance(metadata, dict):
        metadata = None
    files = mizu_history_files(mizu_dir)
    request = {"version": 1, "sim_reach_id": reach_id,
               "sources": [_file_signature(path) for path in files]}
    if csv_path.is_file():
        verified = (metadata is not None and metadata.get("version") == 1
                    and metadata.get("sim_reach_id") == reach_id
                    and metadata.get("csv") == _file_signature(csv_path))
        if verified and (not files or metadata.get("sources") == request["sources"]):
            return csv_path
        if not files:
            if not metadata_path.exists() and reach_id is None:
                return csv_path
            raise RoutedFlowError("Cannot verify routed_flow.csv for this SIM_REACH_ID without history files.")
    if not files:
        return None

    from netCDF4 import Dataset, num2date
    import pandas as pd

    rows: list[tuple] = []
    qcol = None
    for path in files:
        with Dataset(str(path)) as ds:
            var_name = next((name for name in ROUTING_VARS if name in ds.variables), None)
            if var_name is None:
                continue
            if "time" not in ds.variables:
                raise RoutedFlowError(f"{path.name} has no time coordinate.")
            if qcol is not None and var_name != qcol:
                raise RoutedFlowError("History files use different routed discharge variables.")
            qcol = var_name
            t = ds.variables["time"]
            if not getattr(t, "units", None):
                raise RoutedFlowError(f"{path.name} has no time units.")
            times = num2date(t[:], units=t.units, calendar=getattr(t, "calendar", "standard"))
            series = _reach_series(ds, ds.variables[var_name], reach_id)
            rows.extend((pd.to_datetime(str(stamp)), float(value)) for stamp, value in zip(times, series))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["time", qcol])
    df["time"] = df["time"].dt.round("s")
    df = df.drop_duplicates("time", keep="last").sort_values("time")
    # Replace complete files only; an interrupted write fails provenance checks.
    with tempfile.NamedTemporaryFile(dir=mizu_dir, suffix=".csv", delete=False) as handle:
        temp_csv = Path(handle.name)
    try:
        df.to_csv(temp_csv, index=False)
        # Capture this extraction's signature before replacement: another caller
        # may subsequently replace the destination with a different reach.
        request["csv"] = {**_file_signature(temp_csv), "name": csv_path.name}
        temp_csv.replace(csv_path)
        metadata_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    finally:
        temp_csv.unlink(missing_ok=True)
    return csv_path
