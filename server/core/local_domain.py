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
    if match and "lumped" in match.group(1).lower():
        return match.group(1)
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
            "do not re-download",
            "do not download",
            "already on disk",
        )
    )


def seed_mac_duplicate_domain_from_basin(
    data_dir: str | Path,
    basin_domain: str,
    symfluence_domain: str,
) -> list[str]:
    """When DOMAIN_NAME has a Mac-style (n) suffix, seed artifacts from the base basin domain."""
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
    min_hrus: int = 2,
) -> bool:
    legacy = legacy_catchment_path(data_dir, domain_name)
    if not legacy.is_file():
        return True
    return catchment_hru_count(legacy) < min_hrus
