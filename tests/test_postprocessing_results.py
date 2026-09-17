import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml
from streamlit.testing.v1 import AppTest

from app.workflow_extras import compute_quick_metrics
from server.core.postprocessing import (
    configured_period,
    discharge_output_paths,
    load_daily_discharge,
    prepare_daily_comparison,
)


def _write_csv(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(data).to_csv(path, index=False)
    return path


def test_load_daily_discharge_averages_hours_and_ignores_invalid_samples(tmp_path):
    path = _write_csv(tmp_path / "results.csv", {
        "time": ["2004-01-01 00:00", "2004-01-01 12:00", "2004-01-01 12:00", "2004-01-02", "2004-01-03", "invalid"],
        "SUMMA_discharge_cms": [2, 4, 4, -9999, float("inf"), 100],
        "quality_flag": [1] * 6,
    })

    daily = load_daily_discharge(path)

    assert list(daily.columns) == ["SUMMA_discharge_cms"]
    assert daily.loc["2004-01-01", "SUMMA_discharge_cms"] == 3
    assert daily.dropna().shape == (1, 1)


def test_sources_prefer_postprocessed_output_and_exclude_other_experiments(tmp_path):
    expected = tmp_path / "results" / "exp1_results.csv"
    routed = tmp_path / "simulations" / "exp1" / "mizuRoute" / "routed_flow.csv"
    for path in (expected, routed, tmp_path / "results" / "exp2_results.csv"):
        _write_csv(path, {"time": ["2004-01-01"], "discharge_cms": [1]})

    assert discharge_output_paths(tmp_path, "exp1") == [expected, routed]
    assert discharge_output_paths(tmp_path, "missing") == []


def test_comparison_uses_daily_means_and_inclusive_period_without_spinup(tmp_path):
    sim_path = _write_csv(tmp_path / "sim.csv", {
        "time": pd.date_range("2004-01-01", periods=6),
        "SUMMA_discharge_cms": [1000, 2, 3, 4, 5, 6],
    })
    obs_path = _write_csv(tmp_path / "obs.csv", {
        "datetime": pd.date_range("2004-01-01", periods=12, freq="12h"),
        "discharge_cms": [0, 2, 1, 3, 2, 4, 3, 5, 4, 6, 5, 7],
    })
    cfg = {
        "EXPERIMENT_TIME_START": "2004-01-01 00:00",
        "EXPERIMENT_TIME_END": "2004-01-06 23:00",
        "extra_config": {
            "evaluation_period": "2004-01-01 to 2004-01-04",
            "spinup_period": "2004-01-01, 2004-01-01",
        },
    }

    merged = prepare_daily_comparison(
        load_daily_discharge(sim_path).iloc[:, 0],
        load_daily_discharge(obs_path, observed=True), cfg,
    )

    assert list(merged.index.day) == [2, 3, 4]
    metrics = compute_quick_metrics(merged)
    assert metrics == {"n_points": 3, "NSE": 1.0, "KGE": 1.0, "bias_m3s": 0.0, "rmse_m3s": 0.0}


def test_metrics_count_only_finite_paired_days():
    metrics = compute_quick_metrics(pd.DataFrame({
        "observed": [1, 2, None, float("inf")], "simulated": [1, 2, 3, 4],
    }))
    assert metrics["n_points"] == 2
    assert metrics["NSE"] == 1


def test_disjoint_period_is_empty_and_invalid_period_is_rejected():
    simulated = pd.Series([1, 2], index=pd.date_range("2004-01-01", periods=2))
    merged = prepare_daily_comparison(simulated, None, {"evaluation_period": "2005-01-01, 2005-12-31"})
    assert merged.empty
    with pytest.raises(ValueError, match="Invalid evaluation period"):
        configured_period({"EVALUATION_PERIOD": "2005-12-31, 2005-01-01"}, "evaluation_period")


def _results_app(data_dir, runs_dir):
    from pathlib import Path

    from app.workflow_extras import render_results_page

    render_results_page(symfluence_data_dir=Path(data_dir), runs_dir=Path(runs_dir))


@pytest.fixture
def results_app(tmp_path):
    domain_root = tmp_path / "data" / "domain_Demo"
    _write_csv(domain_root / "results" / "exp1_results.csv", {
        "time": pd.date_range("2004-01-01", periods=5),
        "SUMMA_discharge_cms": [100, 2, 3, 4, 5],
    })
    _write_csv(domain_root / "simulations" / "exp1" / "mizuRoute" / "routed_flow.csv", {
        "time": pd.date_range("2004-01-01", periods=5), "IRFroutedRunoff": [9] * 5,
    })
    obs_path = _write_csv(domain_root / "data" / "observations" / "streamflow" / "preprocessed" / "Demo_streamflow_processed.csv", {
        "datetime": pd.date_range("2004-01-01", periods=5), "discharge_cms": [1, 2, 3, 4, 5],
    })
    run_dir = tmp_path / "runs" / "Demo_exp1"
    run_dir.mkdir(parents=True)
    (run_dir / "config.yaml").write_text(yaml.safe_dump({
        "DOMAIN_NAME": "Demo", "EXPERIMENT_ID": "exp1", "HYDROLOGICAL_MODEL": "SUMMA",
        "EVALUATION_PERIOD": "2004-01-01, 2004-01-04", "SPINUP_PERIOD": "2004-01-01, 2004-01-01",
    }))
    app = AppTest.from_function(_results_app, args=(str(tmp_path / "data"), str(tmp_path / "runs")))
    app.session_state["domain_name"] = "Demo"
    app.session_state["experiment_id"] = "exp1"
    # The saved run's evaluation period must win over an edited draft.
    app.session_state["run_plan"] = {"config": {
        "domain_name": "Demo", "experiment_id": "exp1", "evaluation_period": "2000-01-01, 2000-12-31"
    }}
    return app, obs_path


def test_results_page_displays_outputs_metrics_and_downloads(results_app):
    app, _ = results_app
    app.run()

    assert not app.exception
    assert not app.error
    assert [tab.label for tab in app.tabs] == ["Hydrograph", "Metrics", "Flow duration", "Saved plots"]
    assert app.selectbox[0].value.name == "exp1_results.csv"
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics == {"Paired days": "3", "NSE": "1.0000", "KGE": "1.0000", "Bias (m³/s)": "0.0000", "RMSE (m³/s)": "0.0000"}
    assert len(app.get("download_button")) == 2

    app.radio[0].set_value("Full simulation").run()
    assert not app.exception
    assert app.metric[0].value == "5"

    routed = app.selectbox[0].value.parents[1] / "simulations" / "exp1" / "mizuRoute" / "routed_flow.csv"
    app.selectbox[0].set_value(routed).run()
    assert not app.exception
    assert app.selectbox[1].value == "IRFroutedRunoff"
    assert float(next(metric.value for metric in app.metric if metric.label == "NSE")) < 1


def test_results_page_handles_missing_observations_and_invalid_source(results_app):
    app, obs_path = results_app
    obs_path.unlink()
    app.run()
    assert not app.exception
    assert not app.metric
    assert any("simulation statistics" in message.value for message in app.info)
    assert len(app.get("vega_lite_chart")) == 2

    source = app.selectbox[0].value
    source.write_text("time,quality_flag\n2004-01-01,1\n")
    app.run()
    assert not app.exception
    assert any("no recognized discharge column" in message.value for message in app.error)


def test_results_page_has_empty_state_for_experiment_without_outputs(results_app):
    app, _ = results_app
    app.session_state["experiment_id"] = "missing"
    app.run()
    assert not app.exception
    assert any("No postprocessed discharge table" in message.value for message in app.info)
    assert not app.metric


def test_results_page_resolves_numbered_domain_from_active_run(tmp_path):
    domain_root = tmp_path / "data" / "domain_Demo_1"
    expected = _write_csv(domain_root / "results" / "exp1_results.csv", {
        "time": pd.date_range("2004-01-01", periods=2),
        "SUMMA_discharge_cms": [1, 2],
    })
    run_dir = tmp_path / "runs" / "Demo_exp1_1"
    run_dir.mkdir(parents=True)
    (run_dir / "config.yaml").write_text(yaml.safe_dump({
        "DOMAIN_NAME": "Demo_1",
        "EXPERIMENT_ID": "exp1",
        "HYDROLOGICAL_MODEL": "SUMMA",
    }))

    app = AppTest.from_function(
        _results_app,
        args=(str(tmp_path / "data"), str(tmp_path / "runs")),
    )
    app.session_state["domain_name"] = "Demo"
    app.session_state["experiment_id"] = "exp1"
    app.session_state["run_folder"] = "Demo_exp1_1"
    app.run()

    assert not app.exception
    assert app.selectbox[0].value == expected


def test_results_follow_selected_run_despite_stale_draft_and_data_path(results_app, tmp_path):
    app, _ = results_app
    app.session_state["run_folder"] = "Demo_exp1"
    app.run()
    assert not app.exception
    assert app.selectbox[0].value.name == "exp1_results.csv"

    # Switch runs while the workflow draft still names the previous experiment.
    data_dir = tmp_path / "other_data"
    domain_root = data_dir / "domain_Other"
    expected = _write_csv(domain_root / "results" / "exp2_results.csv", {
        "time": pd.date_range("2004-01-01", periods=3),
        "SUMMA_discharge_cms": [2, 3, 4],
    })
    _write_csv(domain_root / "data/observations/streamflow/preprocessed/Other_streamflow_processed.csv", {
        "datetime": pd.date_range("2004-01-01", periods=3), "discharge_cms": [2, 3, 4],
    })
    run_dir = tmp_path / "runs" / "Other_exp2"
    run_dir.mkdir()
    (run_dir / "config.yaml").write_text(yaml.safe_dump({
        "DOMAIN_NAME": "Other", "EXPERIMENT_ID": "exp2",
        "SYMFLUENCE_DATA_DIR": str(data_dir), "HYDROLOGICAL_MODEL": "SUMMA",
    }))
    app.session_state["run_folder"] = run_dir.name
    app.run()

    assert not app.exception
    assert not app.error
    assert app.selectbox[0].value == expected
    assert app.metric[0].value == "3"
    assert any("Domain: Other · Experiment: exp2" in item.value for item in app.caption)


def test_experiments_load_applies_saved_config_before_showing_results(tmp_path, monkeypatch):
    # Run the real UI against an isolated workspace so loading cannot rewrite
    # the developer's run metadata or local settings.
    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(repo / "app", tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(repo / "configs", tmp_path / "configs")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr("server.core.api_keys.load_api_keys_from_environment", lambda keys: {})
    settings = tmp_path / ".symfluence_assistant" / "config.yaml"
    settings.parent.mkdir()
    settings.write_text(yaml.safe_dump({"symfluence_data_dir": str(tmp_path / "data")}))

    run_dir = tmp_path / "runs" / "Demo_exp1"
    run_dir.mkdir(parents=True)
    (run_dir / "config.yaml").write_text(yaml.safe_dump({
        "DOMAIN_NAME": "Demo", "EXPERIMENT_ID": "exp1", "HYDROLOGICAL_MODEL": "SUMMA",
        "DOMAIN_DEFINITION_METHOD": "delineate", "DATA_ACCESS": "CLOUD",
        "SYMFLUENCE_DATA_DIR": str(tmp_path / "data"),
        "EXPERIMENT_TIME_START": "2004-01-01 00:00", "EXPERIMENT_TIME_END": "2004-01-02 23:00",
    }))
    (run_dir / "plan.json").write_text(json.dumps({
        "config": {"domain_name": "Demo_lumped", "experiment_id": "draft", "domain_def": "lumped"},
        "steps": ["run_model", "postprocess_results"], "notes": "Saved workflow steps",
        "workflow_plan_mode": "simulation",
    }))
    (run_dir / "spec.json").write_text('{"domain_name": "Demo"}\n')
    (run_dir / "prompt.txt").write_text("Original simulation request\n")
    (run_dir / "chat.json").write_text(json.dumps({"messages": [
        {"role": "user", "content": "Original simulation request"},
    ]}))
    original_metadata = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    expected = _write_csv(tmp_path / "data/domain_Demo/results/exp1_results.csv", {
        "time": ["2004-01-01", "2004-01-02"], "SUMMA_discharge_cms": [2, 3],
    })
    app = AppTest.from_file(str(tmp_path / "app/ui_agent.py"), default_timeout=20)
    app.session_state["hydroagent_nav_page"] = "Experiments"
    app.run()
    assert not app.exception
    app.button(key="experiments_load_run").click().run()

    assert not app.exception
    assert app.session_state["run_folder"] == "Demo_exp1"
    assert app.session_state["domain_name"] == "Demo"
    assert app.session_state["experiment_id"] == "exp1"
    assert app.session_state["run_plan"]["config"]["domain_def"] == "delineate"
    assert app.session_state["run_plan"]["steps"] == ["run_model", "postprocess_results"]
    assert {path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()} == original_metadata

    # Editing the active draft must not change the executed configuration or metadata.
    plan = dict(app.session_state["run_plan"])
    plan["notes"] = "Unsaved draft change"
    app.session_state["run_plan"] = plan
    app.run()
    assert not app.exception
    assert {path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()} == original_metadata

    app.radio(key="hydroagent_nav_page").set_value("Results").run()
    assert not app.exception
    assert app.selectbox[0].value == expected


def test_comparison_normalizes_all_configured_dates_to_utc():
    simulated = pd.Series([10, 20, 30, 40], index=pd.date_range("2004-01-01", periods=4))
    cfg = {"EXPERIMENT_TIME_START": "2003-12-31T19:00:00-05:00",
           "EXPERIMENT_TIME_END": "2004-01-04T23:00:00Z",
           "EVALUATION_PERIOD": "2003-12-31T19:00:00-05:00, 2004-01-03T23:00:00Z",
           "SPINUP_PERIOD": "2004-01-01, 2004-01-01T23:00:00Z"}
    result = prepare_daily_comparison(simulated, None, cfg)
    assert result.index.tolist() == list(pd.date_range("2004-01-02", periods=2))
    assert result["simulated"].tolist() == [20, 30]


def _data_app(data_dir, runs_dir):
    from pathlib import Path
    from app.workflow_extras import render_data_page

    render_data_page(symfluence_data_dir=Path(data_dir), runs_dir=Path(runs_dir),
                     layer_paths_fn=lambda: {"dem": str(Path(data_dir) / "domain_Draft/wrong.tif")})


def test_data_page_follows_saved_run_and_excludes_draft_layers(tmp_path):
    run = tmp_path / "runs/Saved_exp1"
    run.mkdir(parents=True)
    saved_data = tmp_path / "saved_data"
    (run / "config.yaml").write_text(yaml.safe_dump({
        "DOMAIN_NAME": "Saved", "EXPERIMENT_ID": "exp1", "SYMFLUENCE_DATA_DIR": str(saved_data),
    }))
    app = AppTest.from_function(_data_app, args=(str(tmp_path / "draft_data"), str(tmp_path / "runs")))
    app.session_state["domain_name"] = "Draft"
    app.session_state["experiment_id"] = "draft"
    app.session_state["run_folder"] = run.name
    app.run()
    assert not app.exception
    text = "\n".join(item.value for item in app.markdown)
    assert str(saved_data / "domain_Saved") in text
    assert "domain_Draft" not in text


@pytest.mark.parametrize("config", ["[", "[]", "EXPERIMENT_ID: exp1\n"])
def test_data_page_reports_invalid_saved_config(tmp_path, config):
    run = tmp_path / "runs/Saved_exp1"
    run.mkdir(parents=True)
    (run / "config.yaml").write_text(config)
    app = AppTest.from_function(_data_app, args=(str(tmp_path / "data"), str(tmp_path / "runs")))
    app.session_state["run_folder"] = run.name
    app.run()
    assert not app.exception
    assert len(app.error) == 1
