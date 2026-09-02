"""Extract mizuRoute history NetCDF into routed_flow.csv for HydroAgent."""

from __future__ import annotations

from pathlib import Path

ROUTING_VARS = ("IRFroutedRunoff", "KWTroutedRunoff", "averageRoutedRunoff")


def mizu_history_files(mizu_dir: Path) -> list[Path]:
    if not mizu_dir.is_dir():
        return []
    found: list[Path] = []
    for pattern in ("*.h.*.nc", "exp_*.h.*.nc", "*.nc"):
        for path in sorted(mizu_dir.glob(pattern)):
            if path.is_file() and path not in found:
                found.append(path)
        if found and pattern != "*.nc":
            break
    return found


def ensure_routed_flow_csv(mizu_dir: Path | None) -> Path | None:
    """Write simulations/.../mizuRoute/routed_flow.csv when history NetCDF exists."""
    if mizu_dir is None:
        return None
    mizu_dir = Path(mizu_dir)
    csv_path = mizu_dir / "routed_flow.csv"
    if csv_path.is_file():
        return csv_path
    files = mizu_history_files(mizu_dir)
    if not files:
        return None
    try:
        from netCDF4 import Dataset, num2date
    except ImportError:
        return None

    import pandas as pd

    rows: list[tuple] = []
    qcol = "IRFroutedRunoff"
    for path in files:
        with Dataset(str(path)) as ds:
            var_name = next((name for name in ROUTING_VARS if name in ds.variables), None)
            if var_name is None:
                continue
            qcol = var_name
            q = ds.variables[var_name][:]
            t = ds.variables["time"]
            times = list(
                num2date(
                    t[:],
                    units=getattr(t, "units", "hours since 1990-01-01 00:00:00"),
                    calendar=getattr(t, "calendar", "standard"),
                )
            )
            if hasattr(q, "filled"):
                q = q.filled(float("nan"))
            while getattr(q, "ndim", 1) > 2:
                q = q[..., 0]
            if getattr(q, "ndim", 1) == 1:
                series = q
            else:
                outlet = int(q[-1].argmax()) if len(q) else 0
                series = q[:, outlet]
            for stamp, value in zip(times, series):
                rows.append((pd.to_datetime(str(stamp)), float(value)))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["time", qcol])
    df["time"] = df["time"].dt.round("s")
    df.sort_values("time", inplace=True)
    df.to_csv(csv_path, index=False)
    return csv_path
