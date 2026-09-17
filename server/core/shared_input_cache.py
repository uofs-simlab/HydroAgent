from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INPUT_BUNDLE_SUBDIR = Path("cache") / "input_bundles"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "on"}


def _parse_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = _text(value).replace(",", "/").split("/")
    if len(parts) != 4:
        return None
    try:
        north, west, south, east = (float(part) for part in parts)
    except (TypeError, ValueError):
        return None
    if north <= south or east <= west:
        return None
    return north, west, south, east


def _bbox_contains(
    coverage: tuple[float, float, float, float],
    requested: tuple[float, float, float, float],
) -> bool:
    north, west, south, east = coverage
    req_north, req_west, req_south, req_east = requested
    tolerance = 1e-6
    return (
        north + tolerance >= req_north
        and west - tolerance <= req_west
        and south - tolerance <= req_south
        and east + tolerance >= req_east
    )


def _parse_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        # SYMFLUENCE's timezone-free experiment dates represent UTC.
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    except ValueError:
        return None


def _time_contains(
    coverage_start: Any,
    coverage_end: Any,
    requested_start: Any,
    requested_end: Any,
) -> bool:
    start = _parse_datetime(coverage_start)
    end = _parse_datetime(coverage_end)
    req_start = _parse_datetime(requested_start)
    req_end = _parse_datetime(requested_end)
    if None in {start, end, req_start, req_end}:
        return False
    return start <= req_start <= req_end <= end


def _manifest_asset(manifest_path: Path, manifest: dict, name: str) -> Path | None:
    assets = manifest.get("assets")
    if not isinstance(assets, dict):
        return None
    relative = _text(assets.get(name))
    if not relative:
        return None
    path = (manifest_path.parent / relative).resolve()
    return path if path.exists() else None


def _stage_domain_raster(cfg: dict, asset: Path, asset_name: str) -> Path | None:
    data_dir_text = _text(cfg.get("SYMFLUENCE_DATA_DIR"))
    domain_name = _text(cfg.get("DOMAIN_NAME"))
    if not data_dir_text or not domain_name or Path(domain_name).name != domain_name:
        return None

    destinations = {
        "dem": Path("elevation") / "dem" / f"domain_{domain_name}_elv.tif",
        "soil": Path("soilclass") / f"domain_{domain_name}_soil_classes.tif",
        "landcover": Path("landclass") / f"domain_{domain_name}_land_classes.tif",
    }
    relative = destinations.get(asset_name)
    if relative is None:
        return None

    destination = (
        Path(data_dir_text).expanduser()
        / f"domain_{domain_name}"
        / "data"
        / "attributes"
        / relative
    )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() and not destination.is_symlink():
            destination.symlink_to(asset)
        if destination.resolve() != asset.resolve():
            return None
    except OSError:
        return None
    return destination if destination.is_file() else None


def _matching_manifests(cfg: dict) -> list[tuple[Path, dict]]:
    data_dir = Path(_text(cfg.get("SYMFLUENCE_DATA_DIR"))).expanduser()
    requested_bbox = _parse_bbox(cfg.get("BOUNDING_BOX_COORDS"))
    if not data_dir.is_dir() or requested_bbox is None:
        return []

    matches: list[tuple[float, Path, dict]] = []
    for manifest_path in sorted((data_dir / INPUT_BUNDLE_SUBDIR).glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict):
            continue
        coverage = _parse_bbox(manifest.get("bounding_box"))
        if coverage is None or not _bbox_contains(coverage, requested_bbox):
            continue
        north, west, south, east = coverage
        matches.append(((north - south) * (east - west), manifest_path, manifest))

    return [(path, manifest) for _area, path, manifest in sorted(matches, key=lambda item: item[0])]


def shared_input_cache_has_asset(
    data_dir: str | Path | None,
    bounding_box: Any,
    asset_name: str,
) -> bool:
    """Return whether a cached source asset covers the requested bounding box."""
    if not data_dir:
        return False
    probe = {
        "SYMFLUENCE_DATA_DIR": str(data_dir),
        "BOUNDING_BOX_COORDS": bounding_box,
    }
    return any(
        _manifest_asset(manifest_path, manifest, asset_name) is not None
        for manifest_path, manifest in _matching_manifests(probe)
    )


def stage_shared_forcing(cfg: dict) -> list[Path]:
    """Stage compatible cached raw forcing in the domain's canonical input folder."""
    if _truthy(cfg.get("FORCE_DOWNLOAD")):
        return []
    if _text(cfg.get("FORCING_PATH")) not in {"", "default"}:
        return []

    data_dir_text = _text(cfg.get("SYMFLUENCE_DATA_DIR"))
    domain_name = _text(cfg.get("DOMAIN_NAME"))
    requested_dataset = _text(cfg.get("FORCING_DATASET")).upper()
    if (
        not data_dir_text
        or not domain_name
        or Path(domain_name).name != domain_name
        or not requested_dataset
    ):
        return []

    for manifest_path, manifest in _matching_manifests(cfg):
        forcing = manifest.get("forcing")
        if not isinstance(forcing, dict):
            continue
        if _text(forcing.get("dataset")).upper() != requested_dataset:
            continue
        if not _time_contains(
            forcing.get("time_start"),
            forcing.get("time_end"),
            cfg.get("EXPERIMENT_TIME_START"),
            cfg.get("EXPERIMENT_TIME_END"),
        ):
            continue

        forcing_path = _manifest_asset(manifest_path, manifest, "forcing")
        if forcing_path is None or not forcing_path.is_dir():
            continue
        sources = sorted(
            path
            for pattern in ("*.nc", "*.nc4")
            for path in forcing_path.glob(pattern)
            if path.is_file()
        )
        if not sources:
            continue

        raw_data_dir = (
            Path(data_dir_text).expanduser()
            / f"domain_{domain_name}"
            / "data"
            / "forcing"
            / "raw_data"
        )
        destinations = [raw_data_dir / source.name for source in sources]

        # The backend reads every NetCDF in raw_data, including differently
        # named files. Never mix a cached bundle with unrelated forcing.
        existing = {
            path for pattern in ("*.nc", "*.nc4")
            for path in raw_data_dir.glob(pattern)
        }
        if existing.difference(destinations):
            continue

        # Never overwrite unrelated files in an existing domain.
        conflict = False
        for source, destination in zip(sources, destinations):
            if not destination.exists() and not destination.is_symlink():
                continue
            try:
                if destination.resolve() != source.resolve():
                    conflict = True
                    break
            except OSError:
                conflict = True
                break
        if conflict:
            continue

        created: list[Path] = []
        try:
            raw_data_dir.mkdir(parents=True, exist_ok=True)
            for source, destination in zip(sources, destinations):
                if destination.exists() or destination.is_symlink():
                    continue
                destination.symlink_to(source)
                created.append(destination)
        except OSError:
            for destination in created:
                destination.unlink(missing_ok=True)
            continue

        if all(
            destination.is_file() and destination.resolve() == source.resolve()
            for source, destination in zip(sources, destinations)
        ):
            return destinations

        for destination in created:
            destination.unlink(missing_ok=True)

    return []


def apply_shared_input_cache(cfg: dict) -> dict:
    """Point a new domain at compatible domain-neutral cached source inputs.

    Cache entries never replace explicit custom paths or filenames.
    ``FORCE_DOWNLOAD`` remains the opt-out for users who require fresh source data.
    """
    out = dict(cfg)
    if _truthy(out.get("FORCE_DOWNLOAD")):
        return out

    matches = _matching_manifests(out)
    if not matches:
        return out

    path_fields = {
        "dem": ("DEM_PATH", "DEM_NAME", "DOWNLOAD_DEM"),
        "soil": ("SOIL_CLASS_PATH", "SOIL_CLASS_NAME", "DOWNLOAD_SOIL"),
        "landcover": ("LAND_CLASS_PATH", "LAND_CLASS_NAME", "DOWNLOAD_LAND_COVER"),
    }
    for asset_name, (path_key, name_key, download_key) in path_fields.items():
        if any(_text(out.get(key)) not in {"", "default"} for key in (path_key, name_key)):
            continue
        for manifest_path, manifest in matches:
            asset = _manifest_asset(manifest_path, manifest, asset_name)
            if asset is None or not asset.is_file():
                continue
            staged = _stage_domain_raster(out, asset, asset_name)
            if staged is None:
                continue
            out[path_key] = "default"
            out[name_key] = "default"
            out[download_key] = False
            break

    return out
