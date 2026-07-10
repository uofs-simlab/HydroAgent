from server.core.plan_rules import (
    domain_catchment_hru_count,
    domain_has_local_discretization,
)


def test_single_hru_counts_as_local_discretization(tmp_path):
    domain = "BowRiver"
    root = tmp_path / f"domain_{domain}" / "shapefiles" / "catchment" / "semidistributed" / "exp_001"
    root.mkdir(parents=True)
    shp = root / f"{domain}_HRUs_GRUs.shp"
    shp.write_bytes(b"")
    dbf = shp.with_suffix(".dbf")
    # DBF header: record count at byte offset 4 (little-endian uint32)
    dbf.write_bytes(b"\x00" * 4 + (1).to_bytes(4, "little") + b"\x00" * 24)

    assert domain_catchment_hru_count(tmp_path, domain, "exp_001") == 1
    assert domain_has_local_discretization(tmp_path, domain, "exp_001")


def test_zero_hrus_is_not_discretized(tmp_path):
    domain = "BowRiver"
    root = tmp_path / f"domain_{domain}" / "shapefiles" / "catchment" / "semidistributed" / "exp_001"
    root.mkdir(parents=True)
    shp = root / f"{domain}_HRUs_GRUs.shp"
    shp.write_bytes(b"")

    assert domain_catchment_hru_count(tmp_path, domain, "exp_001") == 0
    assert not domain_has_local_discretization(tmp_path, domain, "exp_001")
