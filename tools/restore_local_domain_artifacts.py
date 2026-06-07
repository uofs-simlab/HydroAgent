#!/usr/bin/env python3
"""Restore Bow_at_Banff_semi_distributed catchment/DEM from intact into/ copies."""
# Layout note: minor UI spacing tweaks.
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def restore(domain_dir: Path, domain_name: str, experiment_id: str = "run_1") -> None:
    into = domain_dir / "shapefiles" / "catchment" / "semidistributed" / "into"
    run_dir = domain_dir / "shapefiles" / "catchment" / "semidistributed" / experiment_id
    hru_name = f"{domain_name}_HRUs_GRUs"
    dem_name = f"{domain_name}_elv.tif"

    active_dem = domain_dir / "data" / "attributes" / "elevation" / "dem" / dem_name
    dem_candidates = [
        domain_dir / "attributes" / "elevation" / "dem" / dem_name,
        domain_dir / "data" / "attributes" / "elevation" / "dem" / dem_name,
    ]
    source_dem = max(
        (p for p in dem_candidates if p.is_file()),
        key=lambda p: p.stat().st_size,
        default=None,
    )
    if source_dem and (not active_dem.is_file() or source_dem.stat().st_size > active_dem.stat().st_size):
        active_dem.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_dem, active_dem)
        print(f"Restored DEM: {active_dem} ({active_dem.stat().st_size} bytes)")

    catchment_targets = [
        run_dir,
        domain_dir / "shapefiles" / "catchment" / "delineate" / experiment_id,
        domain_dir / "shapefiles" / "catchment",
    ]
    for target_dir in catchment_targets:
        target_dir.mkdir(parents=True, exist_ok=True)
        for ext in ("shp", "shx", "dbf", "prj", "cpg"):
            src = into / f"{hru_name}.{ext}"
            dst = target_dir / f"{hru_name}.{ext}"
            if src.is_file():
                shutil.copy2(src, dst)
                print(f"Restored catchment: {dst}")

    try:
        import geopandas as gpd

        shp = into / f"{hru_name}.shp"
        basins_out = (
            domain_dir
            / "shapefiles"
            / "river_basins"
            / f"{domain_name}_riverBasins_semidistributed.shp"
        )
        gdf = gpd.read_file(shp)
        basins = gdf.dissolve(by="GRU_ID", as_index=False, aggfunc={"GRU_area": "first", "gru_to_seg": "first"})
        basins[["GRU_ID", "GRU_area", "gru_to_seg", "geometry"]].to_file(basins_out)
        print(f"Rebuilt river_basins: {basins_out} ({len(basins)} GRUs)")
    except Exception as exc:
        print(f"Skipped river_basins rebuild ({exc})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / "installs" / "SYMFLUENCE_data",
    )
    parser.add_argument("--domain-name", default="Bow_at_Banff_semi_distributed")
    parser.add_argument("--experiment-id", default="run_1")
    args = parser.parse_args()
    restore(
        args.data_dir / f"domain_{args.domain_name}",
        args.domain_name,
        args.experiment_id,
    )


if __name__ == "__main__":
    main()
