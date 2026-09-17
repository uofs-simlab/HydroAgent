from __future__ import annotations

import json
from pathlib import Path

from server.core.run_naming import (
    allocate_unique_run_folder,
    basin_domain_for_run_folder,
    is_placeholder_assistant_run_folder,
    placeholder_run_needs_rename,
    rename_placeholder_assistant_run_folder,
    resolve_run_workspace,
    run_folder_belongs_to_workspace,
    symfluence_domain_for_run_folder,
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

    assert new_name == "BowRiver3_exp001_1"
    assert not old_dir.exists()
    assert (runs_dir / "BowRiver3_exp001_1" / "plan.json").is_file()
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


def test_new_duplicate_names_are_filesystem_safe(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    data_dir = tmp_path / "data"
    (runs_dir / "BowRiver3_exp001").mkdir(parents=True)

    run_folder = allocate_unique_run_folder(
        "BowRiver3",
        "exp001",
        runs_dir,
        data_dir,
    )
    sym_domain = symfluence_domain_for_run_folder(
        run_folder,
        "BowRiver3",
        "exp001",
    )

    assert run_folder == "BowRiver3_exp001_1"
    assert sym_domain == "BowRiver3_1"
    assert " " not in sym_domain
    assert "(" not in sym_domain
    assert run_folder_belongs_to_workspace(run_folder, "BowRiver3", "exp001")


def test_existing_mac_style_duplicate_still_maps_to_existing_domain() -> None:
    assert symfluence_domain_for_run_folder(
        "BowRiver3_exp001 (2)",
        "BowRiver3",
        "exp001",
    ) == "BowRiver3 (2)"


def test_portable_duplicate_recovers_base_basin_when_reloaded() -> None:
    assert basin_domain_for_run_folder(
        "BowRiver3_exp001_2",
        "BowRiver3_2",
        "exp001",
    ) == "BowRiver3"
    assert basin_domain_for_run_folder(
        "Reach_2_exp001",
        "Reach_2",
        "exp001",
    ) == "Reach_2"


def test_allocation_avoids_orphaned_portable_data_domain(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    data_dir = tmp_path / "data"
    (runs_dir / "BowRiver3_exp001").mkdir(parents=True)
    (data_dir / "domain_BowRiver3_1").mkdir(parents=True)

    assert allocate_unique_run_folder(
        "BowRiver3",
        "exp001",
        runs_dir,
        data_dir,
    ) == "BowRiver3_exp001_2"


def test_legacy_duplicate_occupies_same_numbered_slot(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    data_dir = tmp_path / "data"
    (runs_dir / "BowRiver3_exp001").mkdir(parents=True)
    (runs_dir / "BowRiver3_exp001 (1)").mkdir()

    assert allocate_unique_run_folder(
        "BowRiver3",
        "exp001",
        runs_dir,
        data_dir,
    ) == "BowRiver3_exp001_2"


def test_reverse_mapping_uses_saved_config_for_portable_duplicates(tmp_path):
    from server.core.run_naming import run_folder_for_symfluence_domain

    run = tmp_path / "Demo_exp1_2"
    run.mkdir()
    (run / "config.yaml").write_text("DOMAIN_NAME: Demo_2\nEXPERIMENT_ID: exp1\n")
    assert run_folder_for_symfluence_domain("Demo_2", "exp1", tmp_path) == "Demo_exp1_2"


def test_reverse_mapping_preserves_numeric_basin_names(tmp_path):
    from server.core.run_naming import run_folder_for_symfluence_domain

    assert run_folder_for_symfluence_domain("Reach_2", "exp1", tmp_path) == "Reach_2_exp1"
    assert run_folder_for_symfluence_domain("Demo (2)", "exp1", tmp_path) == "Demo_exp1 (2)"


def test_reverse_mapping_ignores_invalid_or_unrelated_metadata(tmp_path):
    from server.core.run_naming import find_assistant_run_for_domain

    for name, config in [("invalid", "["), ("list", "[]"), ("other", "DOMAIN_NAME: Demo\nEXPERIMENT_ID: exp2\n"),
                         ("other_data", "DOMAIN_NAME: Demo\nEXPERIMENT_ID: exp1\nSYMFLUENCE_DATA_DIR: /elsewhere\n")]:
        folder = tmp_path / name
        folder.mkdir()
        (folder / "config.yaml").write_text(config)
    assert find_assistant_run_for_domain("Demo", "exp1", tmp_path, data_dir=tmp_path / "data") is None


def test_reverse_mapping_reports_ambiguous_runs(tmp_path):
    import pytest
    from server.core.run_naming import find_assistant_run_for_domain

    for name in ["first", "second"]:
        folder = tmp_path / name
        folder.mkdir()
        (folder / "config.yaml").write_text("DOMAIN_NAME: Demo\nEXPERIMENT_ID: exp1\n")
    with pytest.raises(ValueError, match="Multiple saved runs"):
        find_assistant_run_for_domain("Demo", "exp1", tmp_path)
