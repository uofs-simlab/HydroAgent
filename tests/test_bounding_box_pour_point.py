from server.core.local_domain import (
    bounding_box_around_pour_point,
    ensure_bounding_box_contains_pour_point,
    pour_point_inside_bounding_box,
)


def test_pour_point_inside_bounding_box():
    pour = "51.35/-116.02"
    bbox = "51.4223329/-116.2350239/51.1397248/-115.6851760"
    ok, msg = pour_point_inside_bounding_box(pour, bbox)
    assert ok
    assert msg == ""


def test_pour_point_outside_bounding_box():
    pour = "51.35/-116.02"
    bbox = "51.2619149/-114.6807861/50.7851017/-113.5437012"
    ok, msg = pour_point_inside_bounding_box(pour, bbox)
    assert not ok
    assert "outside bounding box" in msg


def test_ensure_bounding_box_contains_pour_point_replaces_invalid_bbox():
    pour = "51.35/-116.02"
    bbox = "51.2619149/-114.6807861/50.7851017/-113.5437012"
    fixed, changed, note = ensure_bounding_box_contains_pour_point(pour, bbox)
    assert changed
    assert note
    ok, _ = pour_point_inside_bounding_box(pour, fixed)
    assert ok


def test_bounding_box_around_pour_point():
    bbox = bounding_box_around_pour_point("51.35/-116.02")
    assert bbox == "51.7000000/-116.5700000/51.0000000/-115.4700000"
