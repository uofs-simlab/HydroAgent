"""Copy SYMFLUENCE calibration logs into the HydroAgent run folder."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

WORK_LOG_BANNER = "===== SYMFLUENCE CALIBRATION WORK LOG ====="
WORK_LOG_END = "===== END SYMFLUENCE CALIBRATION WORK LOG ====="
LOG_FILE_RE = re.compile(r"Log File:\s+(\S+\.log)")


def calibration_log_path(run_dir: Path) -> Path:
    return Path(run_dir) / "logs" / "calibration.log"


def worklog_dir(domain_root: Path) -> Path:
    name = Path(domain_root).name
    domain = name[len("domain_") :] if name.startswith("domain_") else name
    return Path(domain_root) / f"_workLog_{domain}"


def iter_calibration_result_dirs(domain_root: Path, experiment_id: str) -> list[Path]:
    opt = Path(domain_root) / "optimization"
    if not opt.is_dir():
        return []
    exp = (experiment_id or "").strip()
    found: list[Path] = []
    for model_dir in sorted(p for p in opt.iterdir() if p.is_dir()):
        for run_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
            if exp and (run_dir.name.endswith(f"_{exp}") or f"_{exp}" in run_dir.name):
                found.append(run_dir)
            elif not exp:
                found.append(run_dir)
    return found


def find_symfluence_calibration_work_log(
    domain_root: Path,
    stdout: str = "",
) -> Path | None:
    candidates: list[Path] = []
    if stdout:
        for match in LOG_FILE_RE.finditer(stdout):
            path = Path(match.group(1))
            if path.is_file():
                candidates.append(path)
    work_dir = worklog_dir(domain_root)
    if work_dir.is_dir():
        candidates.extend(work_dir.glob("symfluence_general_*.log"))
    matches: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "calibrate_model" in text or "optimization for" in text:
            matches.append(path)
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def persist_calibration_logs(
    run_dir: Path,
    domain_root: Path,
    experiment_id: str = "",
    stdout: str = "",
    log_path: Path | None = None,
) -> Path | None:
    """Copy the SYMFLUENCE calibration work log into HydroAgent logs/."""
    run_dir = Path(run_dir)
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    dest = calibration_log_path(run_dir)
    source = find_symfluence_calibration_work_log(domain_root, stdout=stdout)
    if source is None or not source.is_file():
        return dest if dest.is_file() else None

    copied: list[str] = [str(source)]
    stale = (not dest.is_file()) or dest.stat().st_mtime < source.stat().st_mtime
    if stale:
        dest.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        workers_dir = logs_dir / "calibration_workers"
        for result_dir in iter_calibration_result_dirs(domain_root, experiment_id):
            for pattern in ("*_best_params.json", "*iteration_results.csv"):
                for src in result_dir.glob(pattern):
                    target = logs_dir / "calibration" / src.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                    copied.append(str(src))
            for log_file in sorted(result_dir.rglob("*.log")):
                rel = log_file.relative_to(result_dir)
                target = workers_dir / result_dir.name / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(log_file, target)
    elif dest.is_file():
        copied.append(str(dest))

    exec_log = Path(log_path) if log_path else logs_dir / "execution.log"
    if exec_log.is_file():
        existing = exec_log.read_text(encoding="utf-8", errors="replace")
        if WORK_LOG_BANNER not in existing:
            work_text = dest.read_text(encoding="utf-8", errors="replace")
            with exec_log.open("a", encoding="utf-8") as handle:
                handle.write("\n")
                handle.write(WORK_LOG_BANNER + "\n")
                handle.write(f"Source: {source}\n")
                handle.write(f"Copied to: {dest}\n")
                if copied:
                    handle.write("Calibration artifacts:\n")
                    for item in copied[:12]:
                        handle.write(f"  - {item}\n")
                handle.write("\n")
                handle.write(work_text.rstrip() + "\n")
                handle.write(WORK_LOG_END + "\n")
    return dest


def persist_calibration_logs_for_run(run_dir: Path, stdout: str = "") -> Path | None:
    """Read the run config.yaml and copy calibration logs if the domain exists."""
    run_dir = Path(run_dir)
    config_path = run_dir / "config.yaml"
    if not config_path.is_file():
        return None
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    data_dir = Path(str(cfg.get("SYMFLUENCE_DATA_DIR") or "")).expanduser()
    domain = str(cfg.get("DOMAIN_NAME") or "").strip()
    experiment_id = str(cfg.get("EXPERIMENT_ID") or "").strip()
    if not data_dir.is_dir() or not domain:
        return None
    domain_root = data_dir / f"domain_{domain}"
    if not domain_root.is_dir():
        return None
    exec_log = run_dir / "logs" / "execution.log"
    exec_text = exec_log.read_text(encoding="utf-8", errors="replace") if exec_log.is_file() else ""
    if "calibrate_model" not in exec_text and "calibrate_model" not in stdout:
        plan_path = run_dir / "plan.json"
        if plan_path.is_file():
            plan_text = plan_path.read_text(encoding="utf-8", errors="replace")
            if "calibrate_model" not in plan_text:
                return None
    return persist_calibration_logs(
        run_dir,
        domain_root,
        experiment_id=experiment_id,
        stdout=stdout or exec_text,
        log_path=exec_log,
    )
