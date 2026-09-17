import json
import os

import pandas as pd
import pytest
from netCDF4 import Dataset

from server.core.postprocessing import discharge_output_paths
from server.core.routed_flow import RoutedFlowError, ensure_routed_flow_csv


def write_history(path, *, ids=(21, 99), values=((1, 100), (2, 200)), transpose=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, "w") as ds:
        ds.createDimension("time", 2)
        ds.createDimension("seg", len(ids))
        time = ds.createVariable("time", "f8", ("time",))
        time.units = "hours since 2004-01-01 00:00:00"
        time[:] = [0, 24]
        ds.createVariable("reachID", "i8", ("seg",))[:] = ids
        dims = ("seg", "time") if transpose else ("time", "seg")
        flow = ds.createVariable("IRFroutedRunoff", "f8", dims)
        for time_index, row in enumerate(values):
            for reach_index, value in enumerate(row):
                key = (reach_index, time_index) if transpose else (time_index, reach_index)
                flow[key] = value


@pytest.mark.parametrize("transpose", [False, True])
def test_extracts_configured_reach_instead_of_largest_flow(tmp_path, transpose):
    write_history(tmp_path / "exp.h.1.nc", transpose=transpose)
    csv = ensure_routed_flow_csv(tmp_path, "21")
    assert pd.read_csv(csv)["IRFroutedRunoff"].tolist() == [1, 2]
    metadata = json.loads((tmp_path / "routed_flow.meta.json").read_text())
    assert metadata["sim_reach_id"] == 21
    assert metadata["sources"][0]["name"] == "exp.h.1.nc"
    previous_mtime = csv.stat().st_mtime_ns
    assert ensure_routed_flow_csv(tmp_path, 21) == csv
    assert csv.stat().st_mtime_ns == previous_mtime


def test_refreshes_on_reach_source_and_csv_changes(tmp_path):
    history = tmp_path / "exp.h.1.nc"
    write_history(history)
    csv = ensure_routed_flow_csv(tmp_path, 21)
    ensure_routed_flow_csv(tmp_path, 99)
    assert pd.read_csv(csv)["IRFroutedRunoff"].tolist() == [100, 200]
    old_time = history.stat().st_mtime_ns
    write_history(history, values=((3, 300), (4, 400)))
    os.utime(history, ns=(old_time + 1_000_000, old_time + 1_000_000))
    ensure_routed_flow_csv(tmp_path, 99)
    assert pd.read_csv(csv)["IRFroutedRunoff"].tolist() == [300, 400]
    csv.write_text("stale\n")
    ensure_routed_flow_csv(tmp_path, 99)
    assert pd.read_csv(csv)["IRFroutedRunoff"].tolist() == [300, 400]


@pytest.mark.parametrize("reach", [None, "default", 1234, "21.5"])
def test_rejects_ambiguous_or_missing_reach_even_with_existing_csv(tmp_path, reach):
    write_history(tmp_path / "exp.h.1.nc")
    (tmp_path / "routed_flow.csv").write_text("time,IRFroutedRunoff\n2004-01-01,999\n")
    with pytest.raises(RoutedFlowError):
        ensure_routed_flow_csv(tmp_path, reach)


def test_single_reach_needs_no_selection(tmp_path):
    write_history(tmp_path / "exp.h.1.nc", ids=(21,), values=((1,), (2,)))
    assert pd.read_csv(ensure_routed_flow_csv(tmp_path))["IRFroutedRunoff"].tolist() == [1, 2]


def test_reach_position_is_resolved_in_every_history_file(tmp_path):
    write_history(tmp_path / "exp.h.1.nc")
    write_history(tmp_path / "exp.h.2.nc", ids=(99, 21), values=((300, 3), (400, 4)))
    result = pd.read_csv(ensure_routed_flow_csv(tmp_path, 21))
    assert result["IRFroutedRunoff"].tolist() == [3, 4]
    assert not result["time"].duplicated().any()


def test_csv_without_history_cannot_claim_unverified_reach(tmp_path):
    csv = tmp_path / "routed_flow.csv"
    csv.write_text("time,IRFroutedRunoff\n2004-01-01,1\n")
    assert ensure_routed_flow_csv(tmp_path) == csv
    with pytest.raises(RoutedFlowError, match="without history"):
        ensure_routed_flow_csv(tmp_path, 21)


def test_results_exclude_invalid_routed_cache_but_keep_postprocessed_output(tmp_path):
    mizu = tmp_path / "simulations/exp/mizuRoute"
    write_history(mizu / "exp.h.1.nc")
    ensure_routed_flow_csv(mizu, 99)
    result = tmp_path / "results/exp_results.csv"
    result.parent.mkdir()
    result.write_text("time,SUMMA_discharge_cms\n2004-01-01,1\n")
    errors = []
    assert discharge_output_paths(tmp_path, "exp", sim_reach_id=1234, routed_flow_errors=errors) == [result]
    assert "1234" in errors[0]
    paths = discharge_output_paths(tmp_path, "exp", sim_reach_id=21)
    assert len(paths) == 2
    assert pd.read_csv(paths[-1])["IRFroutedRunoff"].tolist() == [1, 2]


def test_artifact_scan_uses_saved_reach_and_reports_invalid_cache(tmp_path):
    from app.workflow_extras import scan_run_artifacts

    mizu = tmp_path / "domain_Demo/simulations/exp/mizuRoute"
    write_history(mizu / "exp.h.1.nc")
    run = tmp_path / "runs/Demo_exp"
    run.mkdir(parents=True)
    config = run / "config.yaml"
    config.write_text("SIM_REACH_ID: 21\n")
    ctx = {"domain_root": tmp_path / "domain_Demo", "domain_name": "Demo",
           "experiment_id": "exp", "mizu_dir": mizu, "assistant_run": run}
    rows = scan_run_artifacts(ctx)
    assert next(row for row in rows if row["artifact"] == "routed_flow.csv")["status"] == "found"
    assert pd.read_csv(mizu / "routed_flow.csv")["IRFroutedRunoff"].tolist() == [1, 2]
    config.write_text("SIM_REACH_ID: 1234\n")
    rows = scan_run_artifacts(ctx)
    routed = next(row for row in rows if row["artifact"] == "routed_flow.csv")
    assert routed["status"] == "unavailable"
    assert "1234" in routed["detail"]


def test_corrupt_provenance_cannot_be_treated_as_legacy_standalone_csv(tmp_path):
    (tmp_path / "routed_flow.csv").write_text("time,IRFroutedRunoff\n2004-01-01,1\n")
    (tmp_path / "routed_flow.meta.json").write_text("{")
    with pytest.raises(RoutedFlowError, match="without history"):
        ensure_routed_flow_csv(tmp_path)
