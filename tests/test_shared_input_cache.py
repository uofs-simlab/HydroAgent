from __future__ import annotations

import json
from pathlib import Path

import yaml
import pytest

from server.core.shared_input_cache import (
    apply_shared_input_cache,
    shared_input_cache_has_asset,
    stage_shared_forcing,
)
from server.core.workflow_executor import run_workflow_job


def _write_bundle(data_dir: Path, *, dataset: str = "AORC") -> None:
    bundle = data_dir / "cache" / "input_bundles" / f"logan-{dataset.lower()}"
    forcing = bundle / "forcing"
    forcing.mkdir(parents=True)
    for name in ("dem.tif", "soil.tif", "landcover.tif"):
        (bundle / name).write_bytes(b"cached")
    (forcing / f"{dataset.lower()}.nc").write_bytes(b"cached")
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "bounding_box": [42.15, -111.87, 41.65, -111.42],
                "assets": {
                    "dem": "dem.tif",
                    "soil": "soil.tif",
                    "landcover": "landcover.tif",
                    "forcing": "forcing",
                },
                "forcing": {
                    "dataset": dataset,
                    "time_start": "2003-10-01 00:00",
                    "time_end": "2005-09-30 23:00",
                },
            }
        ),
        encoding="utf-8",
    )


def test_shared_cache_supplies_compatible_new_domain_inputs(tmp_path: Path):
    _write_bundle(tmp_path)
    cfg = apply_shared_input_cache(
        {
            "SYMFLUENCE_DATA_DIR": str(tmp_path),
            "DOMAIN_NAME": "test_domain",
            "BOUNDING_BOX_COORDS": "42.10/-111.85/41.70/-111.45",
            "EXPERIMENT_TIME_START": "2004-01-01 00:00",
            "EXPERIMENT_TIME_END": "2004-12-31 23:00",
            "FORCING_DATASET": "AORC",
            "DATA_ACCESS": "cloud",
        }
    )

    assert cfg["DATA_ACCESS"] == "cloud"
    assert cfg["DOWNLOAD_DEM"] is False
    assert cfg["DOWNLOAD_SOIL"] is False
    assert cfg["DOWNLOAD_LAND_COVER"] is False
    assert cfg["DEM_PATH"] == "default"
    assert cfg["DEM_NAME"] == "default"
    staged_dem = (
        tmp_path
        / "domain_test_domain"
        / "data"
        / "attributes"
        / "elevation"
        / "dem"
        / "domain_test_domain_elv.tif"
    )
    assert staged_dem.is_symlink()
    assert staged_dem.read_bytes() == b"cached"
    assert cfg.get("FORCING_PATH") in {None, "default"}

    staged = stage_shared_forcing(cfg)
    assert len(staged) == 1
    assert staged[0].is_symlink()
    assert staged[0].read_bytes() == b"cached"


def test_force_download_ignores_shared_cache(tmp_path: Path):
    _write_bundle(tmp_path)
    original = {
        "SYMFLUENCE_DATA_DIR": str(tmp_path),
        "BOUNDING_BOX_COORDS": "42.10/-111.85/41.70/-111.45",
        "EXPERIMENT_TIME_START": "2004-01-01 00:00",
        "EXPERIMENT_TIME_END": "2004-12-31 23:00",
        "FORCING_DATASET": "AORC",
        "FORCE_DOWNLOAD": True,
    }

    assert apply_shared_input_cache(original) == original
    assert stage_shared_forcing(original) == []


def test_shared_cache_reports_covered_asset(tmp_path: Path):
    _write_bundle(tmp_path)

    assert shared_input_cache_has_asset(
        tmp_path,
        "42.10/-111.85/41.70/-111.45",
        "dem",
    )
    assert not shared_input_cache_has_asset(
        tmp_path,
        "43.10/-111.85/42.70/-111.45",
        "dem",
    )


def test_shared_forcing_staging_is_not_aorc_specific(tmp_path: Path):
    _write_bundle(tmp_path, dataset="ERA5")
    cfg = {
        "SYMFLUENCE_DATA_DIR": str(tmp_path),
        "DOMAIN_NAME": "era5_domain",
        "BOUNDING_BOX_COORDS": "42.10/-111.85/41.70/-111.45",
        "EXPERIMENT_TIME_START": "2004-01-01 00:00",
        "EXPERIMENT_TIME_END": "2004-12-31 23:00",
        "FORCING_DATASET": "ERA5",
        "FORCING_PATH": "default",
    }

    staged = stage_shared_forcing(cfg)

    assert len(staged) == 1
    assert staged[0].name == "era5.nc"
    assert staged[0].resolve().name == "era5.nc"


def test_executor_satisfies_acquisition_from_shared_cache(tmp_path: Path):
    _write_bundle(tmp_path)
    run_dir = tmp_path / "runs" / "test"
    run_dir.mkdir(parents=True)
    cfg = {
        "SYMFLUENCE_DATA_DIR": str(tmp_path),
        "DOMAIN_NAME": "test_domain",
        "EXPERIMENT_ID": "test",
        "BOUNDING_BOX_COORDS": "42.10/-111.85/41.70/-111.45",
        "EXPERIMENT_TIME_START": "2004-01-01 00:00",
        "EXPERIMENT_TIME_END": "2004-12-31 23:00",
        "FORCING_DATASET": "AORC",
        "FORCING_PATH": "default",
    }
    plan = {
        "config": {"domain_name": "test_domain", "experiment_id": "test"},
        "steps": ["acquire_forcings"],
    }
    (run_dir / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (run_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (run_dir / "workflow_job.json").write_text(
        json.dumps(
            {
                "symfluence_repo": str(tmp_path / "missing-repo"),
                "symfluence_data_dir": str(tmp_path),
                "symfluence_python": str(tmp_path / "missing-python"),
                "enable_prompt_matching": False,
            }
        ),
        encoding="utf-8",
    )

    assert run_workflow_job(run_dir) == 0
    log = (run_dir / "logs" / "execution.log").read_text(encoding="utf-8")
    assert "Satisfied acquire_forcings using compatible shared cached AORC data" in log
    assert "[STEP acquire_forcings] return code: 0" in log


@pytest.mark.parametrize("key", ["DEM_PATH", "DEM_NAME", "SOIL_CLASS_PATH", "SOIL_CLASS_NAME", "LAND_CLASS_PATH", "LAND_CLASS_NAME"])
def test_shared_cache_preserves_custom_raster_settings(tmp_path, key):
    _write_bundle(tmp_path)
    cfg = {"SYMFLUENCE_DATA_DIR": str(tmp_path), "DOMAIN_NAME": "custom",
           "BOUNDING_BOX_COORDS": "42.10/-111.85/41.70/-111.45", key: "custom_input.tif"}
    result = apply_shared_input_cache(cfg)
    assert result[key] == "custom_input.tif"
    download_key = "DOWNLOAD_DEM" if key.startswith("DEM") else "DOWNLOAD_SOIL" if key.startswith("SOIL") else "DOWNLOAD_LAND_COVER"
    assert download_key not in result


@pytest.mark.parametrize("start,end,expected", [
    ("2003-10-01T00:00:00Z", "2005-09-30T23:00:00+00:00", True),
    ("2003-09-30T19:00:00-05:00", "2005-09-30T18:00:00-05:00", True),
    ("2003-10-01T00:00:00+01:00", "2005-09-30T23:00:00Z", False),
    ("2005-09-30", "2003-10-01", False),
    ("invalid", "2005-09-30", False),
])
def test_forcing_cache_compares_dates_in_utc(tmp_path, start, end, expected):
    _write_bundle(tmp_path)
    cfg = {"SYMFLUENCE_DATA_DIR": str(tmp_path), "DOMAIN_NAME": "utc",
           "BOUNDING_BOX_COORDS": "42.10/-111.85/41.70/-111.45", "FORCING_DATASET": "AORC",
           "EXPERIMENT_TIME_START": start, "EXPERIMENT_TIME_END": end}
    assert bool(stage_shared_forcing(cfg)) == expected


@pytest.mark.parametrize("existing", ["file", "different_symlink", "broken_symlink"])
def test_raster_cache_does_not_claim_unrelated_existing_input(tmp_path, existing):
    _write_bundle(tmp_path)
    destination = tmp_path / "domain_custom/data/attributes/elevation/dem/domain_custom_elv.tif"
    destination.parent.mkdir(parents=True)
    if existing == "file":
        destination.write_bytes(b"unrelated")
    else:
        target = tmp_path / "other.tif"
        if existing == "different_symlink":
            target.write_bytes(b"unrelated")
        destination.symlink_to(target)
    cfg = {"SYMFLUENCE_DATA_DIR": str(tmp_path), "DOMAIN_NAME": "custom",
           "BOUNDING_BOX_COORDS": "42.10/-111.85/41.70/-111.45", "DOWNLOAD_DEM": True}
    assert apply_shared_input_cache(cfg)["DOWNLOAD_DEM"] is True
    if existing != "broken_symlink":
        assert destination.read_bytes() == b"unrelated"
    else:
        assert destination.is_symlink()


def test_forcing_cache_does_not_mix_with_differently_named_existing_data(tmp_path):
    _write_bundle(tmp_path)
    raw = tmp_path / "domain_custom/data/forcing/raw_data"
    raw.mkdir(parents=True)
    (raw / "other_dataset.nc").write_bytes(b"unrelated")
    cfg = {"SYMFLUENCE_DATA_DIR": str(tmp_path), "DOMAIN_NAME": "custom",
           "BOUNDING_BOX_COORDS": "42.10/-111.85/41.70/-111.45", "FORCING_DATASET": "AORC",
           "EXPERIMENT_TIME_START": "2004-01-01", "EXPERIMENT_TIME_END": "2004-12-31"}
    assert stage_shared_forcing(cfg) == []
    assert [p.name for p in raw.iterdir()] == ["other_dataset.nc"]
