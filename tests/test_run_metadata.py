import json
from pathlib import Path

import pytest

from app import ui_agent as ui


def test_chat_drafts_do_not_change_run_metadata_until_explicit_save(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs/Demo_exp1"
    run_dir.mkdir(parents=True)
    preview = tmp_path / "runs/_preview"
    original_chat = {"messages": [{"role": "user", "content": "Original request"}]}
    (run_dir / "chat.json").write_text(json.dumps(original_chat))
    state = {"run_folder": "Demo_exp1", "user_prompt": "Updated request",
             "chat_messages": [{"role": "user", "content": "Draft refinement"}]}
    monkeypatch.setattr(ui.st, "session_state", state)
    monkeypatch.setattr(ui, "PREVIEW_DIR", preview)
    monkeypatch.setattr(ui, "RUNS_DIR", tmp_path / "runs")

    ui.save_preview_chat_messages()

    assert json.loads((run_dir / "chat.json").read_text()) == original_chat
    assert json.loads((preview / "chat.json").read_text())["messages"] == state["chat_messages"]
    plan = {"config": {"domain_name": "Demo", "experiment_id": "exp1"}, "steps": ["run_model"]}
    ui.write_run_metadata_files(run_dir, plan, {"domain_name": "Demo"})
    assert json.loads((run_dir / "chat.json").read_text())["messages"] == state["chat_messages"]
    assert json.loads((run_dir / "plan.json").read_text())["config"]["domain_name"] == "Demo"
    assert json.loads((run_dir / "spec.json").read_text()) == {"domain_name": "Demo"}
    assert (run_dir / "prompt.txt").read_text() == "Updated request\n"


@pytest.mark.parametrize("domain,run_name", [("Demo_2", "Demo_exp1_2"), ("Reach_2", "Reach_2_exp1")])
def test_data_domain_load_restores_matching_saved_assistant_run(tmp_path, monkeypatch, domain, run_name):
    data_dir = tmp_path / "data"
    (data_dir / f"domain_{domain}/simulations/exp1").mkdir(parents=True)
    run = tmp_path / "runs" / run_name
    run.mkdir(parents=True)
    config_text = f"DOMAIN_NAME: {domain}\nEXPERIMENT_ID: exp1\nSYMFLUENCE_DATA_DIR: {data_dir}\n"
    (run / "config.yaml").write_text(config_text)
    restored = []
    monkeypatch.setattr(ui, "SYMFLUENCE_DATA_DIR", data_dir)
    monkeypatch.setattr(ui, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(ui, "load_assistant_run", lambda name: restored.append(name))

    assert ui.load_symfluence_data_domain(f"domain_{domain}") is None
    assert restored == [run_name]
    assert (run / "config.yaml").read_text() == config_text
