from __future__ import annotations
# Layout note: minor UI spacing tweaks.

import re
import shutil
import subprocess
import sys
from pathlib import Path


_REUSABLE_LUMPED_REL_PATHS = (
    "attributes/elevation",
    "attributes/landclass",
    "attributes/soilclass",
    "forcing/raw_data",
    "observations/streamflow",
)


def copy_with_name_adaptation(src: Path, dst: Path, old_name: str, new_name: str) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, dst)
        return True
    shutil.copytree(src, dst, dirs_exist_ok=True)
    if old_name and new_name and old_name != new_name:
        for file in dst.rglob("*"):
            if file.is_file() and old_name in file.name:
                file.rename(file.parent / file.name.replace(old_name, new_name))
    return True


def _destination_roots(target_root: Path, rel_path: str) -> list[Path]:
    rel_path = rel_path.strip("/")
    roots = [target_root / rel_path]
    if rel_path.split("/", 1)[0] in {"attributes", "forcing", "observations"}:
        roots.append(target_root / "data" / rel_path)
    return roots


def copy_reusable_domain_artifacts(
    data_dir: str | Path,
    source_domain: str,
    target_domain: str,
    *,
    rel_paths: tuple[str, ...] = _REUSABLE_LUMPED_REL_PATHS,
) -> list[str]:
    """Copy tutorial-style reusable trees and adapt filenames from source to target domain."""
    data_dir = Path(data_dir)
    source_root = data_dir / f"domain_{source_domain}"
    target_root = data_dir / f"domain_{target_domain}"
    if not source_root.is_dir():
        return []
    copied: list[str] = []
    for rel_path in rel_paths:
        src = source_root / rel_path
        if not src.exists():
            continue
        for dst_root in _destination_roots(target_root, rel_path):
            if copy_with_name_adaptation(src, dst_root, source_domain, target_domain):
                copied.append(str(dst_root.relative_to(target_root)))
    return copied


def infer_reuse_source_domain(
    user_request: str,
    basin_domain: str,
    data_dir: str | Path,
) -> str:
    text = (user_request or "").lower()
    match = re.search(r"domain_([A-Za-z0-9_]+)", user_request or "")
    if match:
        candidate = match.group(1)
        if (Path(data_dir) / f"domain_{candidate}").is_dir():
            return candidate
    if "bow_at_banff_lumped" in text:
        return "Bow_at_Banff_lumped"
    if any(
        phrase in text
        for phrase in (
            "reuse tutorial 02a",
            "tutorial 02a",
            "from domain_bow_at_banff_lumped",
            "bow_at_banff_lumped",
        )
    ):
        candidate = re.sub(r"_semi_distributed$", "", basin_domain, flags=re.IGNORECASE)
        lumped = f"{candidate}_lumped"
        if (Path(data_dir) / f"domain_{lumped}").is_dir():
            return lumped
    return ""


def user_request_reuses_local_domain_data(user_request: str) -> bool:
    text = (user_request or "").lower()
    return any(
        phrase in text
        for phrase in (
            "reuse tutorial 02a",
            "tutorial 02a",
            "domain_bow_at_banff_lumped",
            "bow_at_banff_lumped",
            "reuse local",
            "existing local data",
            "local data first",
            "local-data recovery",
            "local recovery",
            "not a new domain",
            "reuse existing local",
            "do not re-download",
            "do not download",
            "already on disk",
            "before downloading",
        )
    )


def seed_mac_duplicate_domain_from_basin(
    data_dir: str | Path,
    basin_domain: str,
    symfluence_domain: str,
) -> list[str]:
    """When DOMAIN_NAME is a duplicate (``Basin (2)`` or ``Basin_2``), seed from the base basin."""
    if not basin_domain or not symfluence_domain or basin_domain == symfluence_domain:
        return []
    from server.core.plan_rules import domain_has_complete_local_workflow, domain_has_local_summa_forcing

    if domain_has_local_summa_forcing(data_dir, symfluence_domain):
        return []
    if not domain_has_complete_local_workflow(data_dir, basin_domain):
        return []
    return copy_reusable_domain_artifacts(
        data_dir,
        basin_domain,
        symfluence_domain,
        rel_paths=(
            "attributes/elevation",
            "attributes/landclass",
            "attributes/soilclass",
            "forcing/raw_data",
            "forcing/SUMMA_input",
            "data/forcing/SUMMA_input",
            "observations/streamflow",
            "shapefiles/catchment",
            "shapefiles/river_basins",
            "shapefiles/river_network",
            "settings",
        ),
    )


def restore_local_domain_artifacts(
    data_dir: str | Path,
    domain_name: str,
    experiment_id: str = "run_1",
) -> bool:
    """Restore catchment/DEM from semidistributed/into when local workflow artifacts exist."""
    if not domain_name:
        return False
    script = Path(__file__).resolve().parents[2] / "tools" / "restore_local_domain_artifacts.py"
    if not script.is_file():
        return False
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--data-dir",
            str(data_dir),
            "--domain-name",
            domain_name,
            "--experiment-id",
            experiment_id,
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def legacy_catchment_path(data_dir: str | Path, domain_name: str) -> Path:
    return (
        Path(data_dir)
        / f"domain_{domain_name}"
        / "shapefiles"
        / "catchment"
        / f"{domain_name}_HRUs_GRUs.shp"
    )


def canonical_catchment_path(
    data_dir: str | Path,
    domain_name: str,
    experiment_id: str = "run_1",
) -> Path:
    return (
        Path(data_dir)
        / f"domain_{domain_name}"
        / "shapefiles"
        / "catchment"
        / "semidistributed"
        / experiment_id
        / f"{domain_name}_HRUs_GRUs.shp"
    )


def lumped_catchment_path(
    data_dir: str | Path,
    domain_name: str,
    experiment_id: str = "run_1",
) -> Path:
    return (
        Path(data_dir)
        / f"domain_{domain_name}"
        / "shapefiles"
        / "catchment"
        / "lumped"
        / experiment_id
        / f"{domain_name}_HRUs_GRUs.shp"
    )


def is_lumped_routing(routing_delineation: str) -> bool:
    return (routing_delineation or "").strip().lower() == "lumped"


def discretized_catchment_path(
    data_dir: str | Path,
    domain_name: str,
    experiment_id: str = "run_1",
    *,
    routing_delineation: str = "",
) -> Path:
    """Best catchment shapefile from the latest discretize_domain output."""
    if is_lumped_routing(routing_delineation):
        lumped = lumped_catchment_path(data_dir, domain_name, experiment_id)
        if lumped.is_file():
            return lumped
    semi = canonical_catchment_path(data_dir, domain_name, experiment_id)
    if semi.is_file():
        return semi
    if is_lumped_routing(routing_delineation):
        return lumped_catchment_path(data_dir, domain_name, experiment_id)
    return semi


def _parse_lat_lon_pair(value: str) -> tuple[float, float] | None:
    text = (value or "").strip()
    if not text or "/" not in text:
        return None
    try:
        lat_str, lon_str = text.split("/", 1)
        return float(lat_str.strip()), float(lon_str.strip())
    except ValueError:
        return None


def _parse_bbox_nwse(value: str) -> tuple[float, float, float, float] | None:
    text = (value or "").strip().replace(",", "/")
    if not text:
        return None
    parts = [part.strip() for part in text.split("/") if part.strip()]
    if len(parts) != 4:
        return None
    try:
        north, west, south, east = (float(parts[i]) for i in range(4))
        if north < south:
            north, south = south, north
        if east < west:
            west, east = east, west
        return north, west, south, east
    except ValueError:
        return None


def pour_point_inside_bounding_box(pour_coords: str, bbox_coords: str) -> tuple[bool, str]:
    """Return (ok, message). Pour point must lie inside north/west/south/east bbox."""
    pour = _parse_lat_lon_pair(pour_coords)
    bbox = _parse_bbox_nwse(bbox_coords)
    if pour is None:
        return True, ""
    if bbox is None:
        return True, ""
    lat, lon = pour
    north, west, south, east = bbox
    if south <= lat <= north and west <= lon <= east:
        return True, ""
    return (
        False,
        f"Pour point {lat}/{lon} is outside bounding box "
        f"{north}/{west}/{south}/{east} (north/west/south/east). "
        "Expand the box to include the pour point before running delineation "
        "(for Bow River near 51.35/-116.02, try 51.76/-116.55/50.95/-115.50).",
    )


def bounding_box_around_pour_point(
    pour_coords: str,
    *,
    lat_margin: float = 0.35,
    lon_margin: float = 0.55,
) -> str | None:
    """Build a north/west/south/east bbox centered on the pour point."""
    pour = _parse_lat_lon_pair(pour_coords)
    if pour is None:
        return None
    lat, lon = pour
    north = lat + lat_margin
    south = lat - lat_margin
    west = lon - lon_margin
    east = lon + lon_margin
    return f"{north:.7f}/{west:.7f}/{south:.7f}/{east:.7f}"


def ensure_bounding_box_contains_pour_point(
    pour_coords: str,
    bbox_coords: str,
    *,
    lat_margin: float = 0.35,
    lon_margin: float = 0.55,
) -> tuple[str, bool, str]:
    """Return (bbox, changed, message). Replace bbox when pour point lies outside."""
    ok, msg = pour_point_inside_bounding_box(pour_coords, bbox_coords)
    if ok:
        return bbox_coords, False, ""
    replacement = bounding_box_around_pour_point(
        pour_coords,
        lat_margin=lat_margin,
        lon_margin=lon_margin,
    )
    if replacement is None:
        return bbox_coords, False, msg
    return (
        replacement,
        True,
        f"Bounding box adjusted to include pour point {pour_coords}: {replacement}",
    )


def _read_hru_ids(shapefile: Path) -> set[int]:
    if not shapefile.is_file():
        return set()
    try:
        import geopandas as gpd

        gdf = gpd.read_file(shapefile)
        for col in ("HRU_ID", "hru_id", "HRU_id"):
            if col in gdf.columns:
                return {int(v) for v in gdf[col].dropna().unique()}
    except Exception:
        return set()
    return set()


def catchment_hru_ids_mismatch(
    data_dir: str | Path,
    domain_name: str,
    experiment_id: str = "run_1",
    *,
    min_overlap_ratio: float = 0.9,
    routing_delineation: str = "",
) -> bool:
    """True when legacy and discretized catchments disagree on HRU IDs."""
    legacy = legacy_catchment_path(data_dir, domain_name)
    canonical = discretized_catchment_path(
        data_dir, domain_name, experiment_id, routing_delineation=routing_delineation
    )
    legacy_ids = _read_hru_ids(legacy)
    canonical_ids = _read_hru_ids(canonical)
    if not legacy_ids or not canonical_ids:
        return False
    overlap = len(legacy_ids & canonical_ids)
    denom = max(len(legacy_ids), len(canonical_ids))
    return overlap / denom < min_overlap_ratio


def sync_canonical_catchment_to_legacy(
    data_dir: str | Path,
    domain_name: str,
    experiment_id: str = "run_1",
    *,
    routing_delineation: str = "",
) -> bool:
    """Copy discretized catchment (lumped or semidistributed) to legacy SUMMA path."""
    src_base = discretized_catchment_path(
        data_dir, domain_name, experiment_id, routing_delineation=routing_delineation
    )
    if not src_base.is_file():
        return False
    dst_base = legacy_catchment_path(data_dir, domain_name)
    dst_base.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("shp", "shx", "dbf", "prj", "cpg"):
        src = src_base.with_suffix(f".{ext}")
        if src.is_file():
            shutil.copy2(src, dst_base.with_suffix(f".{ext}"))
    return True


def summa_preprocessing_hru_mismatch(step_output: str) -> bool:
    return "Forcing HRU IDs not found in catchment shapefile" in (step_output or "")


def catchment_hru_count(shapefile: Path) -> int:
    dbf = shapefile.with_suffix(".dbf")
    if not dbf.is_file():
        return 0
    try:
        with dbf.open("rb") as handle:
            handle.seek(4)
            return int.from_bytes(handle.read(4), "little")
    except OSError:
        return 0


def local_catchment_needs_restore(
    data_dir: str | Path,
    domain_name: str,
    *,
    experiment_id: str = "run_1",
    min_hrus: int = 2,
    routing_delineation: str = "",
) -> bool:
    legacy = legacy_catchment_path(data_dir, domain_name)
    lumped = is_lumped_routing(routing_delineation)
    effective_min = 1 if lumped else min_hrus
    if not legacy.is_file():
        return True
    if catchment_hru_count(legacy) < effective_min:
        return True
    return catchment_hru_ids_mismatch(
        data_dir, domain_name, experiment_id, routing_delineation=routing_delineation
    )
