from server.core.local_domain import (
    domain_river_basins_shapefiles,
    pour_point_inside_delineated_basin,
)
from server.core.plan_rules import basin_pour_point_preflight_error


def _write_test_basin(tmp_path, domain: str, polygon_coords: list[tuple[float, float]]):
    import geopandas as gpd
    from shapely.geometry import Polygon

    basins_dir = tmp_path / f"domain_{domain}" / "shapefiles" / "river_basins"
    basins_dir.mkdir(parents=True)
    poly = Polygon(polygon_coords)
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs="EPSG:4326")
    shp = basins_dir / f"{domain}_riverBasins_lumped.shp"
    gdf.to_file(shp)
    return shp


def test_domain_river_basins_shapefiles(tmp_path):
    domain = "TestBasin"
    shp = _write_test_basin(
        tmp_path,
        domain,
        [(-116.0, 51.0), (-115.5, 51.0), (-115.5, 51.5), (-116.0, 51.5), (-116.0, 51.0)],
    )
    found = domain_river_basins_shapefiles(tmp_path, domain)
    assert found == [shp]


def test_pour_point_inside_delineated_basin(tmp_path):
    domain = "TestBasin"
    _write_test_basin(
        tmp_path,
        domain,
        [(-116.0, 51.0), (-115.5, 51.0), (-115.5, 51.5), (-116.0, 51.5), (-116.0, 51.0)],
    )
    ok, msg = pour_point_inside_delineated_basin("51.178/-115.579", tmp_path, domain)
    assert ok
    assert msg == ""


def test_pour_point_outside_delineated_basin(tmp_path):
    domain = "TestBasin"
    _write_test_basin(
        tmp_path,
        domain,
        [(-116.0, 51.0), (-115.5, 51.0), (-115.5, 51.5), (-116.0, 51.5), (-116.0, 51.0)],
    )
    ok, msg = pour_point_inside_delineated_basin("50.0/-114.0", tmp_path, domain)
    assert not ok
    assert "outside the watershed polygon" in msg


def test_basin_pour_point_preflight_error(tmp_path):
    domain = "TestBasin"
    _write_test_basin(
        tmp_path,
        domain,
        [(-116.0, 51.0), (-115.5, 51.0), (-115.5, 51.5), (-116.0, 51.5), (-116.0, 51.0)],
    )
    err = basin_pour_point_preflight_error(
        "discretize_domain",
        "50.0/-114.0",
        tmp_path,
        domain,
    )
    assert err
    assert "basin delineation issue" in err
    assert "not a bounding-box issue" in err


def test_basin_pour_point_preflight_skips_without_shapefile(tmp_path):
    err = basin_pour_point_preflight_error(
        "discretize_domain",
        "51.178/-115.579",
        tmp_path,
        "MissingBasin",
    )
    assert err is None
