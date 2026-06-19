from __future__ import annotations

import json
from pathlib import Path

from server.core.run_naming import (
    is_placeholder_assistant_run_folder,
    placeholder_run_needs_rename,
    rename_placeholder_assistant_run_folder,
    resolve_run_workspace,
)


def test_is_placeholder_assistant_run_folder_detects_domain_experiment_variants() -> None:
    assert is_placeholder_assistant_run_folder("domain_exp001", "exp001")
    assert is_placeholder_assistant_run_folder("domain_exp001 (11)", "exp001")
    assert is_placeholder_assistant_run_folder("domain_exp", "exp001")
    assert not is_placeholder_assistant_run_folder("BowRiver3_exp001", "exp001")


def test_placeholder_run_needs_rename_when_real_domain_arrives() -> None:
    assert placeholder_run_needs_rename("domain_exp001 (11)", "BowRiver3", "exp001")
    assert not placeholder_run_needs_rename("BowRiver3_exp001", "BowRiver3", "exp001")
    assert not placeholder_run_needs_rename("domain_exp001", "domain", "exp001")


def test_rename_placeholder_assistant_run_folder_moves_workspace(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    data_dir = tmp_path / "data"
    old_name = "domain_exp001 (11)"
    old_dir = runs_dir / old_name
    old_dir.mkdir(parents=True)
    (old_dir / "plan.json").write_text(json.dumps({"config": {}}), encoding="utf-8")

    new_name = rename_placeholder_assistant_run_folder(
        old_name,
        "BowRiver3",
        "exp001",
        runs_dir=runs_dir,
        data_dir=data_dir,
    )

    assert new_name == "BowRiver3_exp001"
    assert not old_dir.exists()
    assert (runs_dir / "BowRiver3_exp001" / "plan.json").is_file()


def test_rename_skips_when_target_workspace_already_exists(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    data_dir = tmp_path / "data"
    old_name = "domain_exp001"
    old_dir = runs_dir / old_name
    old_dir.mkdir(parents=True)
    (old_dir / "plan.json").write_text("{}", encoding="utf-8")

    existing = runs_dir / "BowRiver3_exp001"
    existing.mkdir()
    (existing / "plan.json").write_text("{}", encoding="utf-8")

    new_name = rename_placeholder_assistant_run_folder(
        old_name,
        "BowRiver3",
        "exp001",
        runs_dir=runs_dir,
        data_dir=data_dir,
    )

    assert new_name == "BowRiver3_exp001 (1)"
    assert not old_dir.exists()
    assert (runs_dir / "BowRiver3_exp001 (1)" / "plan.json").is_file()
    assert (existing / "plan.json").is_file()


def test_resolve_run_workspace_renames_established_placeholder(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    data_dir = tmp_path / "data"
    old_name = "domain_exp001 (11)"
    old_dir = runs_dir / old_name
    old_dir.mkdir(parents=True)
    (old_dir / "plan.json").write_text("{}", encoding="utf-8")

    run_folder, sym_domain = resolve_run_workspace(
        "BowRiver3",
        "exp001",
        old_name,
        runs_dir=runs_dir,
        data_dir=data_dir,
        workspace_locked=True,
    )

    assert run_folder == "BowRiver3_exp001"
    assert sym_domain == "BowRiver3"
    assert (runs_dir / "BowRiver3_exp001" / "plan.json").is_file()
