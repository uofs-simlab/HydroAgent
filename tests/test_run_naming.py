from server.core.run_naming import (
    allocate_unique_run_folder,
    duplicate_symfluence_domain,
    run_folder_for_symfluence_domain,
    symfluence_domain_for_run_folder,
    symfluence_domain_mac_suffix,
)


def test_duplicate_symfluence_domain_has_no_spaces():
    assert duplicate_symfluence_domain("BowRiver4", 2) == "BowRiver4_2"
    assert " " not in duplicate_symfluence_domain("BowRiver4", 1)


def test_run_folder_maps_to_space_free_domain():
    assert (
        symfluence_domain_for_run_folder("BowRiver4_exp061 (2)", "BowRiver4", "exp061")
        == "BowRiver4_2"
    )
    assert (
        run_folder_for_symfluence_domain("BowRiver4_2", "exp061")
        == "BowRiver4_exp061 (2)"
    )


def test_legacy_spaced_domain_suffix_still_parses():
    assert symfluence_domain_mac_suffix("BowRiver4 (2)") == ("BowRiver4", 2)
    assert symfluence_domain_mac_suffix("BowRiver4_2") == ("BowRiver4", 2)


def test_allocate_unique_run_folder_uses_space_free_domain(tmp_path):
    runs_dir = tmp_path / "runs"
    data_dir = tmp_path / "data"
    runs_dir.mkdir()
    data_dir.mkdir()
    (runs_dir / "BowRiver4_exp061").mkdir()
    folder = allocate_unique_run_folder("BowRiver4", "exp061", runs_dir, data_dir)
    assert folder == "BowRiver4_exp061 (1)"
    domain = symfluence_domain_for_run_folder(folder, "BowRiver4", "exp061")
    assert domain == "BowRiver4_1"
    assert " " not in domain
