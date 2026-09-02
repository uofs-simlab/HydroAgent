from __future__ import annotations

from pathlib import Path

from server.core.calibration_logs import (
    WORK_LOG_BANNER,
    find_symfluence_calibration_work_log,
    persist_calibration_logs,
)
from server.core.plan_rules import domain_forcing_intersection_path, domain_has_forcing_intersection
from server.core.routed_flow import ensure_routed_flow_csv, mizu_history_files


def test_forcing_intersection_accepts_csv(tmp_path: Path):
    folder = (
        tmp_path
        / "domain_Demo"
        / "shapefiles"
        / "catchment_intersection"
        / "with_forcing"
    )
    folder.mkdir(parents=True)
    csv_path = folder / "Demo_ERA5_intersected_shapefile.csv"
    csv_path.write_text("id,area\n1,2\n", encoding="utf-8")
    found = domain_forcing_intersection_path(tmp_path, "Demo")
    assert found == csv_path
    assert domain_has_forcing_intersection(tmp_path, "Demo")


def test_domain_has_remapped_forcing(tmp_path: Path):
    from server.core.plan_rules import domain_has_remapped_forcing

    basin = (
        tmp_path
        / "domain_tv01"
        / "data"
        / "forcing"
        / "basin_averaged_data"
    )
    basin.mkdir(parents=True)
    assert not domain_has_remapped_forcing(tmp_path, "tv01")
    (basin / "tv01_ERA5_remapped_2023-05-01-00-00-00.nc").write_bytes(b"ok")
    assert domain_has_remapped_forcing(tmp_path, "tv01")


def test_ensure_routed_flow_csv_keeps_existing(tmp_path: Path):
    mizu = tmp_path / "mizuRoute"
    mizu.mkdir()
    csv_path = mizu / "routed_flow.csv"
    csv_path.write_text("time,IRFroutedRunoff\n2023-04-02,1.0\n", encoding="utf-8")
    assert ensure_routed_flow_csv(mizu) == csv_path
    assert mizu_history_files(mizu) == []


def test_persist_calibration_work_log(tmp_path: Path):
    domain_root = tmp_path / "domain_Demo"
    work = domain_root / "_workLog_Demo"
    work.mkdir(parents=True)
    source = work / "symfluence_general_Demo_20260818_141629.log"
    source.write_text(
        "Starting individual step execution: calibrate_model\n"
        "Starting DDS optimization for SUMMA\n"
        "DDS 20/20 (100%) | Best: -1.10\n",
        encoding="utf-8",
    )
    opt = domain_root / "optimization" / "SUMMA" / "dds_exp_001"
    opt.mkdir(parents=True)
    (opt / "exp_001_dds_best_params.json").write_text('{"best_score": -1.1}\n', encoding="utf-8")

    run_dir = tmp_path / "run"
    logs = run_dir / "logs"
    logs.mkdir(parents=True)
    exec_log = logs / "execution.log"
    exec_log.write_text("===== STEP: calibrate_model =====\n[STEP calibrate_model] return code: 0\n", encoding="utf-8")

    dest = persist_calibration_logs(run_dir, domain_root, experiment_id="exp_001")
    assert dest is not None and dest.is_file()
    assert "Starting DDS optimization" in dest.read_text(encoding="utf-8")
    copied = logs / "calibration" / "exp_001_dds_best_params.json"
    assert copied.is_file()
    text = exec_log.read_text(encoding="utf-8")
    assert WORK_LOG_BANNER in text
    assert "Starting DDS optimization" in text
    persist_calibration_logs(run_dir, domain_root, experiment_id="exp_001")
    assert text.count(WORK_LOG_BANNER) == exec_log.read_text(encoding="utf-8").count(WORK_LOG_BANNER)


def test_scan_includes_era5_csv_and_calibration(tmp_path: Path):
    from app.workflow_extras import scan_run_artifacts

    data_dir = tmp_path / "data"
    domain_root = data_dir / "domain_Demo"
    forcing = (
        domain_root
        / "shapefiles"
        / "catchment_intersection"
        / "with_forcing"
    )
    forcing.mkdir(parents=True)
    csv_path = forcing / "Demo_ERA5_intersected_shapefile.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")
    mizu = domain_root / "simulations" / "exp_001" / "mizuRoute"
    mizu.mkdir(parents=True)
    routed = mizu / "routed_flow.csv"
    routed.write_text("time,IRFroutedRunoff\n2023-04-02,1\n", encoding="utf-8")
    calib = domain_root / "optimization" / "SUMMA" / "dds_exp_001"
    calib.mkdir(parents=True)
    best = calib / "exp_001_dds_best_params.json"
    best.write_text("{}\n", encoding="utf-8")
    run_dir = tmp_path / "runs" / "Demo_exp_001"
    (run_dir / "logs").mkdir(parents=True)
    (run_dir / "logs" / "calibration.log").write_text("calibrate_model\n", encoding="utf-8")

    rows = scan_run_artifacts(
        {
            "domain_name": "Demo",
            "experiment_id": "exp_001",
            "domain_root": domain_root,
            "sim_dir": domain_root / "simulations" / "exp_001",
            "mizu_dir": mizu,
            "assistant_run": run_dir,
        },
        {"forcing": str(forcing / "Demo_ERA5_intersected_shapefile.shp")},
    )
    by_name = {row["artifact"]: row for row in rows}
    assert by_name["ERA5 intersection"]["status"] == "found"
    assert by_name["ERA5 intersection"]["path"] == str(csv_path)
    assert by_name["routed_flow.csv"]["status"] == "found"
    assert by_name["Best parameters (dds_exp_001)"]["status"] == "found"
    assert by_name["HydroAgent calibration.log"]["status"] == "found"


def test_find_calibration_work_log_skips_simulation_logs(tmp_path: Path):
    domain_root = tmp_path / "domain_Demo"
    work = domain_root / "_workLog_Demo"
    work.mkdir(parents=True)
    sim = work / "symfluence_general_Demo_20260818_141214.log"
    sim.write_text("Starting individual step execution: run_model\nLog File: x\n", encoding="utf-8")
    cal = work / "symfluence_general_Demo_20260818_141629.log"
    cal.write_text("Starting individual step execution: calibrate_model\n", encoding="utf-8")
    stdout = f"Log File: {sim}\nLog File: {cal}\n"
    found = find_symfluence_calibration_work_log(domain_root, stdout=stdout)
    assert found == cal
