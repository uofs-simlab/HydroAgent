from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Tuple
import re
from datetime import datetime

_LATLON_RE = re.compile(r"^-?\d+(\.\d+)?/-?\d+(\.\d+)?$")

def _parse_dt(s: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(f"Invalid datetime format: {s!r} (expected 'YYYY-MM-DD HH:MM' or with seconds)")

def validate_cfg(cfg: Dict[str, Any]) -> Tuple[bool, list[str]]:
    errs: list[str] = []

    for k in ["SYMFLUENCE_CODE_DIR", "SYMFLUENCE_DATA_DIR", "DOMAIN_NAME", "EXPERIMENT_ID"]:
        if not cfg.get(k):
            errs.append(f"Missing required key: {k}")

    for k in ["SYMFLUENCE_CODE_DIR", "SYMFLUENCE_DATA_DIR"]:
        p = cfg.get(k)
        if p and not Path(str(p)).exists():
            errs.append(f"{k} path does not exist: {p}")

    pp = cfg.get("POUR_POINT_COORDS") or cfg.get("POUR_POINT")
    if pp:
        if not isinstance(pp, str) or not _LATLON_RE.match(pp.strip()):
            errs.append(f"Pour point must be like 'lat/lon' (e.g., 51.1722/-115.5717). Got: {pp!r}")

    ts = cfg.get("EXPERIMENT_TIME_START")
    te = cfg.get("EXPERIMENT_TIME_END")
    if ts and te:
        try:
            dts = _parse_dt(str(ts))
            dte = _parse_dt(str(te))
            if dte <= dts:
                errs.append("EXPERIMENT_TIME_END must be after EXPERIMENT_TIME_START")
        except Exception as e:
            errs.append(str(e))

    return (len(errs) == 0), errs

class ValidationError(Exception):
    pass

def validate_spec(spec: Dict[str, Any]) -> None:
    """
    Backward-compatible validator used by the Streamlit runner.
    Raises ValidationError on failure (instead of returning (ok, errs)).
    """
    ok, errs = validate_cfg(spec)
    if not ok:
        raise ValidationError("; ".join(errs))
