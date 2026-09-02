"""HydroAgent ↔ CalibHydroAgent integration."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_CALIB_IMPORT_ERROR: str | None = None


def _ensure_calib_hydro_agent_import(
    calib_repo: Path | None = None,
) -> bool:
    global _CALIB_IMPORT_ERROR
    candidates: list[Path] = []
    if calib_repo:
        candidates.append(Path(calib_repo).expanduser().resolve())
    env = os.environ.get("CALIB_HYDRO_AGENT_REPO")
    if env:
        candidates.append(Path(env).expanduser().resolve())
    candidates.append(Path.home() / "Desktop" / "CalibHydroAgent")

    for root in candidates:
        pkg = root / "calib_hydro_agent"
        if pkg.is_dir() and str(root) not in sys.path:
            sys.path.insert(0, str(root))
            try:
                import calib_hydro_agent  # noqa: F401
                _CALIB_IMPORT_ERROR = None
                return True
            except ImportError as exc:
                _CALIB_IMPORT_ERROR = str(exc)
    try:
        import calib_hydro_agent  # noqa: F401
        _CALIB_IMPORT_ERROR = None
        return True
    except ImportError as exc:
        _CALIB_IMPORT_ERROR = str(exc)
        return False


def calib_agent_available(calib_repo: Path | None = None) -> bool:
    return _ensure_calib_hydro_agent_import(calib_repo)


def calib_agent_import_error() -> str | None:
    return _CALIB_IMPORT_ERROR


def run_calibration_assistant(
    *,
    config_path: Path,
    session_state: dict[str, Any],
    plan: dict[str, Any],
    user_prompt: str = "",
    symfluence_repo: Path,
    symfluence_python: Path,
    symfluence_data_dir: Path | None = None,
    calib_repo: Path | None = None,
    execute: bool = False,
    allow_dangerous: bool = False,
    auto_replan: bool = False,
    skip_prerequisites: bool = False,
    use_python_api: bool = False,
    sensitivity_guided: bool = False,
    top_n_params: int = 4,
    screening_iterations: int = 30,
) -> dict[str, Any]:
    """Run CalibHydroAgent pipeline using HydroAgent session + plan context."""
    if not _ensure_calib_hydro_agent_import(calib_repo):
        return {
            "ok": False,
            "error": f"CalibHydroAgent not importable: {_CALIB_IMPORT_ERROR}",
        }

    from calib_hydro_agent.adapter import SymfluenceAdapter
    from calib_hydro_agent.hydroagent_bridge import (
        apply_spec_to_hydroagent_plan,
        calibration_intent_from_prompt,
        completed_steps_from_execution_log,
        explicit_calibration_fields_in_prompt,
        planned_steps_from_plan,
        spec_from_agent_context,
    )
    from calib_hydro_agent.paths import resolve_runtime_paths
    from calib_hydro_agent.pipeline import CalibrationPipeline

    runtime = resolve_runtime_paths(
        symfluence_repo=symfluence_repo,
        symfluence_python=symfluence_python,
    )
    pipeline = CalibrationPipeline(adapter=SymfluenceAdapter(runtime))

    log_text = str(session_state.get("execution_log_text") or "")
    intent = calibration_intent_from_prompt(
        user_prompt,
        fallback=f"Calibrate {session_state.get('optimization_target', 'streamflow')} "
        f"with {session_state.get('optimization_metric', 'KGE')} "
        f"using {session_state.get('iterative_optimization_algorithm', 'DDS')}",
    )

    base_spec = spec_from_agent_context(session_state, plan, user_prompt=user_prompt)
    explicit_fields = explicit_calibration_fields_in_prompt(user_prompt)
    context: dict[str, Any] = {
        "base_config": session_state.get("_calib_base_config"),
        "initial_spec": base_spec,
        "explicit_calibration_fields": explicit_fields,
        "domain_name": base_spec.domain_name,
        "experiment_id": base_spec.experiment_id,
        "station_id": base_spec.station_id,
        "model": base_spec.model,
    }
    if symfluence_data_dir:
        context["data_dir"] = str(symfluence_data_dir)

    outcome = pipeline.run_once(
        intent,
        config_path=config_path,
        model=base_spec.model,
        base_config=session_state.get("_calib_base_config"),
        planned_steps=planned_steps_from_plan(plan),
        completed_steps=completed_steps_from_execution_log(log_text),
        allow_dangerous=allow_dangerous,
        execute=execute,
        use_python_api=use_python_api,
        auto_replan=auto_replan,
        skip_prerequisites=skip_prerequisites,
        context=context,
        sensitivity_guided=sensitivity_guided,
        top_n_params=top_n_params,
        screening_iterations=screening_iterations,
    )

    updated_plan = apply_spec_to_hydroagent_plan(plan, outcome.spec)
    result = pipeline.outcome_to_dict(outcome)
    result["ok"] = outcome.stopped is None
    result["updated_plan"] = updated_plan
    return result
