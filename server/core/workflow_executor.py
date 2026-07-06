"""Run SYMFLUENCE workflow steps outside the Streamlit script (survives UI reruns)."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from server.core.safe_subprocess import launch_detached

from server.core.local_domain import (
    copy_reusable_domain_artifacts,
    infer_reuse_source_domain,
    is_lumped_routing,
    local_catchment_needs_restore,
    restore_local_domain_artifacts,
    seed_mac_duplicate_domain_from_basin,
    summa_preprocessing_hru_mismatch,
    sync_canonical_catchment_to_legacy,
    user_request_reuses_local_domain_data,
)
from server.core.plan_rules import (
    domain_has_complete_local_workflow,
    domain_has_local_era5_raw_forcing,
    domain_has_local_streamflow,
    domain_has_local_summa_forcing,
    ensure_skip_process_observed_when_local_streamflow,
    plan_user_required_steps,
    request_indicates_local_data_reuse,
    user_requires_fresh_cloud_workflow,
    workflow_step_user_required,
)
from server.core.validate import validate_spec

STEP_TO_CLI: dict[str, list[str]] = {
    "setup_project": ["workflow", "step", "setup_project"],
    "create_pour_point": ["workflow", "step", "create_pour_point"],
    "acquire_attributes": ["workflow", "step", "acquire_attributes"],
    "define_domain": ["workflow", "step", "define_domain"],
    "discretize_domain": ["workflow", "step", "discretize_domain"],
    "acquire_forcings": ["workflow", "step", "acquire_forcings"],
    "process_observed_data": ["workflow", "step", "process_observed_data"],
    "model_agnostic_preprocessing": ["workflow", "step", "model_agnostic_preprocessing"],
    "model_specific_preprocessing": ["workflow", "step", "model_specific_preprocessing"],
    "run_model": ["workflow", "step", "run_model"],
    "calibrate_model": ["workflow", "step", "calibrate_model"],
    "postprocess_results": ["workflow", "step", "postprocess_results"],
}

SUPPORTED_STEPS = set(STEP_TO_CLI)

STEP_RC_RE = re.compile(r"\[STEP ([^\]]+)\] return code: (\d+)")


def routing_delineation_from_config(cfg: dict, plan_cfg: dict | None = None) -> str:
    plan_cfg = plan_cfg or {}
    extra = plan_cfg.get("extra_config") if isinstance(plan_cfg.get("extra_config"), dict) else {}
    for source in (cfg, plan_cfg, extra):
        val = source.get("ROUTING_DELINEATION")
        if val:
            return str(val)
    domain = str(cfg.get("DOMAIN_NAME") or plan_cfg.get("domain_name") or "")
    if "lumped" in domain.lower() and "semi" not in domain.lower():
        return "lumped"
    return ""


def build_symfluence_step_cmd(step: str, config_path: Path, symfluence_python: Path) -> list[str]:
    cli_parts = STEP_TO_CLI.get(step)
    if not cli_parts:
        raise ValueError(f"Unsupported step for CLI mapping: {step}")
    return [
        str(symfluence_python),
        "-m",
        "symfluence",
        *cli_parts,
        "--config",
        str(config_path),
    ]


def workflow_pid_path(run_dir: Path) -> Path:
    return run_dir / "logs" / "workflow.pid"


def workflow_job_path(run_dir: Path) -> Path:
    return run_dir / "workflow_job.json"


def execution_log_path(run_dir: Path) -> Path:
    return run_dir / "logs" / "execution.log"


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def workflow_is_running(run_dir: Path) -> bool:
    pid_path = workflow_pid_path(run_dir)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid_path.unlink(missing_ok=True)
        return False
    if not is_process_running(pid):
        pid_path.unlink(missing_ok=True)
        return False
    return True


def completed_steps_from_log(log_text: str) -> set[str]:
    completed: set[str] = set()
    for match in STEP_RC_RE.finditer(log_text):
        if match.group(2) == "0":
            completed.add(match.group(1))
    if (
        "===== STEP: validate_config =====" in log_text
        and "Internal validation OK" in log_text
    ):
        completed.add("validate_config")
    return completed


def _load_prompt(run_dir: Path) -> str:
    prompt_path = run_dir / "prompt.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8").strip()
    return ""


def execution_log_preamble_from_disk(run_dir: Path, plan: dict) -> str:
    parts: list[str] = []
    prompt = _load_prompt(run_dir)
    if prompt:
        parts.append("===== USER PROMPT =====\n")
        parts.append(prompt)
        parts.append("\n\n")
    else:
        parts.append("===== USER PROMPT =====\n(no prompt recorded)\n\n")
    parts.append("===== RUN PLAN =====\n")
    parts.append(json.dumps(plan or {}, indent=2))
    parts.append("\n")
    return "".join(parts)


def prepare_execution_log(
    run_dir: Path,
    plan: dict,
    config_path: Path,
    *,
    resume: bool,
) -> Path:
    log_path = execution_log_path(run_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if resume and log_path.exists() and log_path.stat().st_size > 0:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(
                "\n===== RESUMING WORKFLOW =====\n"
                f"Using config: {config_path}\n"
            )
        return log_path
    preamble = execution_log_preamble_from_disk(run_dir, plan)
    text = preamble + f"\nUsing config: {config_path}\n"
    log_path.write_text(text, encoding="utf-8")
    return log_path


def run_cmd_to_log(cmd: list[str], cwd: Path, log_path: Path) -> tuple[int, str]:
    p = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    collected: list[str] = []
    with log_path.open("a", encoding="utf-8") as log_file:
        while True:
            line = p.stdout.readline() if p.stdout else ""
            if not line and p.poll() is not None:
                break
            if line:
                collected.append(line)
                log_file.write(line)
                log_file.flush()
        rc = p.wait()
        log_file.write(f"\n[return code: {rc}]\n")
        log_file.flush()
    return rc, "".join(collected)


def _symfluence_domain_name(domain_name: str, experiment_id: str) -> str:
    domain_name = (domain_name or "domain").strip()
    experiment_id = (experiment_id or "exp").strip()
    safe_domain = "".join(c if c.isalnum() else "_" for c in domain_name).strip("_")
    safe_expid = "".join(c if c.isalnum() else "_" for c in experiment_id).strip("_")
    return f"{safe_domain}_{safe_expid}".strip("_")


def run_workflow_job(run_dir: Path) -> int:
    job_path = workflow_job_path(run_dir)
    if not job_path.exists():
        print(f"Missing workflow job file: {job_path}", file=sys.stderr)
        return 1

    job = json.loads(job_path.read_text(encoding="utf-8"))
    symfluence_repo = Path(job["symfluence_repo"])
    symfluence_data_dir = Path(job["symfluence_data_dir"])
    symfluence_python = Path(job["symfluence_python"])
    user_request = job.get("user_request", "")
    resume = bool(job.get("resume"))

    plan_path = run_dir / "plan.json"
    config_path = run_dir / "config.yaml"
    if not plan_path.exists() or not config_path.exists():
        print("Missing plan.json or config.yaml in run folder", file=sys.stderr)
        return 1

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    steps: list[str] = list(plan.get("steps") or [])
    plan_cfg = plan.get("config") or {}

    log_path = execution_log_path(run_dir)
    completed: set[str] = set()
    if resume and log_path.exists():
        completed = completed_steps_from_log(log_path.read_text(encoding="utf-8"))

    pid_path = workflow_pid_path(run_dir)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    exit_code = 0
    try:
        for step in steps:
            if step in completed:
                continue

            if step == "validate_config":
                with log_path.open("a", encoding="utf-8") as f:
                    f.write("\n===== STEP: validate_config =====\n")
                try:
                    validate_spec(cfg)
                    with log_path.open("a", encoding="utf-8") as f:
                        f.write("Internal validation OK ✅\n")
                except Exception as e:
                    with log_path.open("a", encoding="utf-8") as f:
                        f.write(f"Internal validation FAILED ❌: {e}\n")
                        f.write("Stopping due to failure.\n")
                    return 1
                continue

            if step not in SUPPORTED_STEPS:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(f"\nSKIP unknown step: {step}\n")
                continue

            domain_name = str(plan_cfg.get("domain_name") or cfg.get("DOMAIN_NAME") or "")
            experiment_id = str(plan_cfg.get("experiment_id") or cfg.get("EXPERIMENT_ID") or "run_1")
            basin_domain = _symfluence_domain_name(domain_name, experiment_id)
            symfluence_domain = str(cfg.get("DOMAIN_NAME") or basin_domain)

            routing = routing_delineation_from_config(cfg, plan_cfg)

            if step == "acquire_forcings" and not user_requires_fresh_cloud_workflow(
                user_request, plan_cfg
            ) and "acquire_forcings" not in plan_user_required_steps(plan):
                basin = _symfluence_domain_name(domain_name, experiment_id)
                sym_domain = str(cfg.get("DOMAIN_NAME") or basin)
                local_first = request_indicates_local_data_reuse(
                    user_request, plan_cfg, data_dir=symfluence_data_dir
                )
                check_domains = [sym_domain, basin, domain_name]
                seen_domains: set[str] = set()
                skip_reason = ""
                for check_domain in check_domains:
                    if not check_domain or check_domain in seen_domains:
                        continue
                    seen_domains.add(check_domain)
                    if domain_has_local_summa_forcing(symfluence_data_dir, check_domain):
                        skip_reason = (
                            f"Skipped acquire_forcings; reusing local SUMMA forcing "
                            f"under domain_{check_domain}."
                        )
                        break
                    if local_first and domain_has_local_era5_raw_forcing(
                        symfluence_data_dir, check_domain
                    ):
                        skip_reason = (
                            f"Skipped acquire_forcings; reusing local ERA5/raw forcing "
                            f"under domain_{check_domain}."
                        )
                        break
                if skip_reason:
                    with log_path.open("a", encoding="utf-8") as f:
                        f.write(f"\n===== STEP: {step} =====\n")
                        f.write(skip_reason + "\n")
                        f.write(f"\n[STEP {step}] return code: 0\n")
                    completed.add(step)
                    continue

            if step == "process_observed_data" and not user_requires_fresh_cloud_workflow(
                user_request, plan_cfg
            ) and not workflow_step_user_required(plan, "process_observed_data", user_request):
                basin = _symfluence_domain_name(domain_name, experiment_id)
                sym_domain = str(cfg.get("DOMAIN_NAME") or basin)
                check_domains = [sym_domain, basin, domain_name]
                seen_domains: set[str] = set()
                skip_reason = ""
                for check_domain in check_domains:
                    if not check_domain or check_domain in seen_domains:
                        continue
                    seen_domains.add(check_domain)
                    if domain_has_local_streamflow(symfluence_data_dir, check_domain):
                        skip_reason = (
                            f"Skipped process_observed_data; reusing local preprocessed "
                            f"streamflow under domain_{check_domain}."
                        )
                        break
                if skip_reason:
                    with log_path.open("a", encoding="utf-8") as f:
                        f.write(f"\n===== STEP: {step} =====\n")
                        f.write(skip_reason + "\n")
                        f.write(f"\n[STEP {step}] return code: 0\n")
                    completed.add(step)
                    continue

            if step == "model_specific_preprocessing" and symfluence_domain and (
                domain_has_complete_local_workflow(symfluence_data_dir, symfluence_domain, experiment_id)
                or domain_has_complete_local_workflow(symfluence_data_dir, basin_domain, experiment_id)
                or local_catchment_needs_restore(
                    symfluence_data_dir, symfluence_domain, routing_delineation=routing
                )
                or local_catchment_needs_restore(
                    symfluence_data_dir, basin_domain, routing_delineation=routing
                )
            ):
                restore_domain = symfluence_domain
                if local_catchment_needs_restore(
                    symfluence_data_dir, restore_domain, routing_delineation=routing
                ):
                    if local_catchment_needs_restore(
                        symfluence_data_dir, basin_domain, routing_delineation=routing
                    ):
                        restore_domain = basin_domain
                    with log_path.open("a", encoding="utf-8") as f:
                        if is_lumped_routing(routing):
                            f.write(
                                "\nSyncing lumped catchment shapefile to legacy SUMMA path "
                                "(HRU ID alignment).\n"
                            )
                        else:
                            f.write(
                                "\nRestoring local catchment shapefiles from semidistributed/into "
                                "(legacy catchment path had wrong HRU IDs).\n"
                            )
                    if is_lumped_routing(routing):
                        sync_canonical_catchment_to_legacy(
                            symfluence_data_dir,
                            restore_domain,
                            experiment_id,
                            routing_delineation=routing,
                        )
                    else:
                        restore_local_domain_artifacts(
                            symfluence_data_dir,
                            restore_domain,
                            experiment_id,
                        )

            cmd = build_symfluence_step_cmd(step, config_path, symfluence_python)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n===== STEP: {step} =====\n")
                f.write("$ " + " ".join(cmd) + "\n\n")

            rc, out = run_cmd_to_log(cmd, symfluence_repo, log_path)
            if step == "model_specific_preprocessing" and rc == 0 and summa_preprocessing_hru_mismatch(out):
                rc = 1
                mismatch_msg = (
                    "\nAssistant blocked this step: forcing HRU IDs do not match the catchment shapefile. "
                    "Re-run discretize_domain (after define_domain) or wipe the domain folder and start fresh.\n"
                )
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(mismatch_msg)

            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n[STEP {step}] return code: {rc}\n")

            if rc != 0:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write("Stopping due to failure.\n")
                return rc

            if step == "discretize_domain" and symfluence_domain:
                if sync_canonical_catchment_to_legacy(
                    symfluence_data_dir,
                    symfluence_domain,
                    experiment_id,
                    routing_delineation=routing,
                ):
                    label = "lumped" if is_lumped_routing(routing) else "semidistributed"
                    with log_path.open("a", encoding="utf-8") as f:
                        f.write(
                            f"\nSynced {label} catchment to legacy shapefiles/catchment path "
                            "for SUMMA HRU ID alignment.\n"
                        )

            if step == "setup_project" and not user_requires_fresh_cloud_workflow(
                user_request, plan_cfg
            ):
                copied: list[str] = []
                source_domain = infer_reuse_source_domain(
                    user_request,
                    basin_domain,
                    symfluence_data_dir,
                )
                if source_domain and user_request_reuses_local_domain_data(user_request):
                    copied = copy_reusable_domain_artifacts(
                        symfluence_data_dir,
                        source_domain,
                        symfluence_domain,
                    )
                elif symfluence_domain != basin_domain:
                    copied = seed_mac_duplicate_domain_from_basin(
                        symfluence_data_dir,
                        basin_domain,
                        symfluence_domain,
                    )
                if copied:
                    with log_path.open("a", encoding="utf-8") as f:
                        f.write(
                            "\nSeeded reusable local artifacts into "
                            f"`domain_{symfluence_domain}` from existing on-disk data:\n"
                            + "\n".join(f"  - {item}" for item in copied)
                            + "\n"
                        )
                    plan = ensure_skip_process_observed_when_local_streamflow(
                        plan,
                        user_request,
                        data_dir=symfluence_data_dir,
                        symfluence_domain=symfluence_domain,
                    )
                    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
                    steps = list(plan.get("steps") or [])
    finally:
        pid_path.unlink(missing_ok=True)

    return exit_code


def launch_background_workflow(run_dir: Path, job: dict[str, Any]) -> int:
    """Start workflow execution in a detached subprocess. Returns child PID."""
    if workflow_is_running(run_dir):
        raise RuntimeError("A workflow is already running for this run folder.")

    workflow_job_path(run_dir).write_text(json.dumps(job, indent=2), encoding="utf-8")
    runner = Path(__file__).resolve().parents[2] / "tools" / "run_workflow_plan.py"
    cmd = [sys.executable, str(runner), "--run-dir", str(run_dir)]
    pid = launch_detached(cmd, cwd=runner.parents[1])
    workflow_pid_path(run_dir).write_text(str(pid), encoding="utf-8")
    return pid


def sync_workflow_execution_state(run_dir: Path, session_state: Any) -> bool:
    """Refresh session execution log from disk; return True if workflow still running."""
    log_path = execution_log_path(run_dir)
    if log_path.exists():
        session_state.execution_log_text = log_path.read_text(encoding="utf-8")
    running = workflow_is_running(run_dir)
    session_state.workflow_executing = running
    return running
