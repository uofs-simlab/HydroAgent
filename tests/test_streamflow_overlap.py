from __future__ import annotations

from datetime import datetime
from pathlib import Path

from server.core.plan_rules import (
    domain_has_usable_local_streamflow,
    ensure_skip_process_observed_when_local_streamflow,
    local_streamflow_overlaps_experiment,
)


def _write_streamflow_csv(path: Path, start: str, end: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "datetime,discharge_cms\n"
        f"{start},1.0\n"
        f"{end},2.0\n",
        encoding="utf-8",
    )


def test_local_streamflow_overlaps_experiment(tmp_path):
    domain = "Experiment04"
    csv_path = (
        tmp_path
        / f"domain_{domain}"
        / "data"
        / "observations"
        / "streamflow"
        / "preprocessed"
        / f"{domain}_streamflow_processed.csv"
    )
    _write_streamflow_csv(csv_path, "1973-08-01 00:00:00", "1996-10-31 00:00:00")

    exp_start = datetime(2022, 4, 1)
    exp_end = datetime(2022, 5, 26)
    assert local_streamflow_overlaps_experiment(tmp_path, domain, exp_start, exp_end) is False

    exp_start = datetime(1980, 1, 1)
    exp_end = datetime(1980, 12, 31)
    assert local_streamflow_overlaps_experiment(tmp_path, domain, exp_start, exp_end) is True


def test_domain_has_usable_local_streamflow_requires_overlap(tmp_path):
    domain = "Experiment04"
    csv_path = (
        tmp_path
        / f"domain_{domain}"
        / "data"
        / "observations"
        / "streamflow"
        / "preprocessed"
        / f"{domain}_streamflow_processed.csv"
    )
    _write_streamflow_csv(csv_path, "1973-08-01 00:00:00", "1996-10-31 00:00:00")

    cfg = {
        "EXPERIMENT_TIME_START": "2022-04-01 01:00",
        "EXPERIMENT_TIME_END": "2022-05-26 01:00",
    }
    assert domain_has_usable_local_streamflow(tmp_path, domain, cfg) is False

    cfg["EXPERIMENT_TIME_START"] = "1980-01-01 01:00"
    cfg["EXPERIMENT_TIME_END"] = "1980-12-31 01:00"
    assert domain_has_usable_local_streamflow(tmp_path, domain, cfg) is True


def test_ensure_skip_process_observed_only_when_overlap(tmp_path):
    domain = "Experiment04"
    csv_path = (
        tmp_path
        / f"domain_{domain}"
        / "data"
        / "observations"
        / "streamflow"
        / "preprocessed"
        / f"{domain}_streamflow_processed.csv"
    )
    _write_streamflow_csv(csv_path, "1973-08-01 00:00:00", "1996-10-31 00:00:00")

    plan = {
        "steps": ["process_observed_data", "run_model"],
        "config": {
            "domain_name": domain,
            "experiment_time_start": "2022-04-01 01:00",
            "experiment_time_end": "2022-05-26 01:00",
        },
    }
    out = ensure_skip_process_observed_when_local_streamflow(
        plan,
        "",
        data_dir=tmp_path,
        symfluence_domain=domain,
    )
    assert "process_observed_data" in out["steps"]

    plan["config"]["experiment_time_start"] = "1980-01-01 01:00"
    plan["config"]["experiment_time_end"] = "1980-12-31 01:00"
    out = ensure_skip_process_observed_when_local_streamflow(
        plan,
        "",
        data_dir=tmp_path,
        symfluence_domain=domain,
    )
    assert "process_observed_data" not in out["steps"]
