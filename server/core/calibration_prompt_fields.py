"""Detect calibration settings explicitly named in a user prompt.

CalibHydroAgent provides the full detector when that optional project is
installed.  The local fallback keeps HydroAgent's planning rules deterministic
and testable from a standalone checkout.
"""

from __future__ import annotations

import re


def _fallback_explicit_calibration_fields(user_request: str) -> set[str]:
    text = user_request or ""
    fields: set[str] = set()

    named_field_patterns = {
        "spinup_period": r"\bspin[-_ ]?up\s+period\b",
        "calibration_period": r"\bcalibration\s+period\b",
        "evaluation_period": r"\bevaluation\s+period\b",
        "calibration_timestep": r"\bcalibration\s+time[-_ ]?step\b",
        "population_size": r"\bpopulation\s+size\b",
        "params_to_calibrate": r"\b(?:parameters?|params?)\s+to\s+calibrate\b",
        "basin_params_to_calibrate": r"\bbasin\s+(?:parameters?|params?)\s+to\s+calibrate\b",
    }
    for field, pattern in named_field_patterns.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            fields.add(field)

    if re.search(r"\b(?:kge|nse|rmse|mae|pbi?as)\b", text, flags=re.IGNORECASE):
        fields.add("optimization_metric")

    algorithm = r"(?:de|dds|pso|nsga-?ii|sce-?ua|adam)"
    if re.search(
        rf"\b(?:use|using|with|algorithm|optimizer|optimiser)\s+(?:the\s+)?{algorithm}\b"
        rf"|\b{algorithm}\s+(?:algorithm|optimizer|optimiser)\b",
        text,
        flags=re.IGNORECASE,
    ):
        fields.add("iterative_optimization_algorithm")

    if re.search(
        r"\b(?:iterations?|number\s+of\s+iterations?)\s*(?:=|:|is|to)?\s*\d+\b"
        r"|\b\d+\s+iterations?\b",
        text,
        flags=re.IGNORECASE,
    ):
        fields.add("iterations")

    calibration_context = re.search(
        r"\b(?:calibrat(?:e|ion|ing)|optimi[sz](?:e|ation|ing))\b",
        text,
        flags=re.IGNORECASE,
    )
    if calibration_context and re.search(
        r"\b(?:streamflow|swe|snow[-_ ]?depth|et|evapotranspiration|groundwater)\b",
        text,
        flags=re.IGNORECASE,
    ):
        fields.add("optimization_target")

    return fields


def explicit_calibration_fields_in_prompt(user_request: str) -> set[str]:
    """Return canonical config fields explicitly requested by the user."""
    try:
        from calib_hydro_agent.prompt_fields import (
            explicit_calibration_fields_in_prompt as external_detector,
        )
    except ImportError:
        return _fallback_explicit_calibration_fields(user_request)
    return set(external_detector(user_request))


__all__ = ["explicit_calibration_fields_in_prompt"]

