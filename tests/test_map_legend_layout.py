from pathlib import Path

import folium
import geopandas as gpd
import pytest
from shapely.geometry import box

from app.ui_agent import (
    _add_choropleth_legend_to_map,
    _add_bounding_box_overlay,
    _add_fit_data_control,
    _choropleth_legend_spec,
    _symfluence_layer_choropleth,
    build_pour_point_map,
)


def _render_map_with_legend(legend_spec, reference_entries=None) -> str:
    map_view = folium.Map(location=[51.18, -115.57])
    _add_choropleth_legend_to_map(
        map_view,
        legend_spec,
        reference_entries=reference_entries,
    )
    return map_view.get_root().render()


def test_swatch_legend_fits_map_and_scrolls_only_class_entries():
    rendered = _render_map_with_legend(
        {
            "title": "GRU units",
            "count": 30,
            "start_color": "#440154",
            "end_color": "#fde725",
            "mode": "swatches",
            "entries": [(str(value), "#440154") for value in range(30)],
            "two_column": True,
            "value_header": "GRU ID",
        },
        reference_entries=[{"label": "Pour point", "icon_html": "pin"}],
    )

    assert "max-height:calc(100% - 118px);box-sizing:border-box;overflow:hidden" in rendered
    assert "display:flex;flex-direction:column" in rendered
    assert "flex:1 1 auto;min-height:0;max-height:240px;overflow-y:auto" in rendered
    assert "flex:0 0 auto;border-top:1px solid #e5e7eb" in rendered
    assert "linear-gradient" not in rendered


def test_compact_legend_fits_map_and_can_scroll_as_a_whole():
    rendered = _render_map_with_legend(
        {
            "title": "Elevation",
            "count": 200,
            "start_color": "#440154",
            "end_color": "#fde725",
            "mode": "gradient",
            "subtitle": "200 classes",
            "start_label": "Low",
            "end_label": "High",
        }
    )

    assert "max-height:calc(100% - 118px);box-sizing:border-box;overflow-y:auto" in rendered


def test_fit_data_control_restores_displayed_extent():
    map_view = folium.Map(location=[51.18, -115.57])
    _add_fit_data_control(
        map_view,
        (51.85, -116.80, 50.80, -115.15),
    )

    rendered = map_view.get_root().render()

    assert 'options: { position: "topright" }' in rendered
    assert 'setAttribute("aria-label", "Fit map view to displayed data")' in rendered
    assert "border:2px dashed #374151" in rendered
    assert '"leaflet-control-layers leaflet-control"' in rendered
    assert '"leaflet-control-layers-toggle"' in rendered
    assert "background-image:none" in rendered
    assert "[[50.8, -116.8], [51.85, -115.15]]" in rendered
    assert "{ padding: [8, 8] }" in rendered
    assert "map.fitBounds" in rendered
    assert "if (event.detail > 0) button.blur()" in rendered


def test_river_basin_layer_is_not_labeled_as_grus():
    gdf = gpd.GeoDataFrame({"GRU_ID": [1]})

    _, styles, legend_spec = _symfluence_layer_choropleth(gdf, "River Basins")

    assert styles is None
    assert legend_spec == {}


@pytest.mark.parametrize(
    ("show_dem", "show_hrugru", "expected_title", "expected_label"),
    [
        (True, False, "Elevation", "1500 m"),
        (False, True, "GRUs (2)", "GRU 1"),
        (True, True, "GRUs (2)", "GRU 1"),
    ],
)
def test_river_basins_preserve_active_color_legend(
    monkeypatch, tmp_path, show_dem, show_hrugru, expected_title, expected_label
):
    gdf = gpd.GeoDataFrame(
        {"GRU_ID": [1, 2], "elevClass": [1, 2], "elev_mean": [1500, 2500]},
        geometry=[box(-116, 51, -115.5, 51.5), box(-115.5, 51, -115, 51.5)],
        crs="EPSG:4326",
    )
    layer_path = tmp_path / "layer.shp"
    layer_path.touch()
    layer_paths = dict.fromkeys(
        ("dem", "landclass", "soilclass", "forcing", "riverbasins", "hrugru", "rivernetwork"),
        str(layer_path),
    )
    monkeypatch.setattr("app.ui_agent.symfluence_domain_shapefile_paths", lambda: layer_paths)
    monkeypatch.setattr("app.ui_agent.gpd.read_file", lambda _path: gdf.copy())
    monkeypatch.setattr("app.ui_agent._resolve_bounding_box_bounds", lambda **_kwargs: None)
    monkeypatch.setattr("app.ui_agent._resolve_pour_point_lat_lon", lambda: None)

    rendered = build_pour_point_map(
        show_dem_layer=show_dem,
        show_hrugru_layer=show_hrugru,
        show_riverbasins_layer=True,
        show_pour_point_layer=False,
        show_bounding_box_layer=False,
    ).get_root().render()

    assert f">{expected_title}</span>" in rendered
    assert expected_label in rendered
    assert "Sub-basin boundaries" in rendered


def test_large_gru_legend_remains_categorical():
    entries = [(f"GRU {index}", "#440154") for index in range(150)]

    legend_spec = _choropleth_legend_spec("GRU units", entries, profile="grus")

    assert legend_spec["mode"] == "swatches"
    assert legend_spec["entries"] == entries
    assert legend_spec["title"] == "GRUs (150)"
    assert legend_spec["count"] == ""
    assert legend_spec["value_header"] == ""


def test_workflow_map_loads_fitted_to_configured_bounding_box(monkeypatch):
    bounds = (51.85, -116.80, 50.80, -115.15)
    monkeypatch.setattr(
        "app.ui_agent._resolve_bounding_box_bounds",
        lambda **_kwargs: bounds,
    )
    monkeypatch.setattr("app.ui_agent._resolve_pour_point_lat_lon", lambda: None)
    monkeypatch.setattr("app.ui_agent.symfluence_domain_shapefile_paths", lambda: {})
    monkeypatch.setattr("app.ui_agent._build_map_reference_legend_entries", lambda **_kwargs: [])

    rendered = build_pour_point_map(show_layer_control=False).get_root().render()

    assert "[[50.8, -116.8], [51.85, -115.15]]" in rendered
    assert 'options: { position: "topright" }' in rendered
    assert '"scrollWheelZoom": false' in rendered
    assert "L.control.layers(" not in rendered
    assert 'createPane("sym-river-network")' in rendered
    assert 'addEventListener("wheel"' in rendered
    assert "panel.scrollTop += deltaY" in rendered

    overlay_map = folium.Map(location=[51.18, -115.57])
    _add_bounding_box_overlay(overlay_map, *bounds)
    overlay = overlay_map.get_root().render()
    assert '"interactive": false' in overlay
    assert '"pane": "sym-spatial-overlay"' in overlay


def test_output_review_map_fits_after_collapsed_expander_becomes_visible(monkeypatch):
    bounds = (51.85, -116.80, 50.80, -115.15)
    monkeypatch.setattr(
        "app.ui_agent._resolve_bounding_box_bounds",
        lambda **_kwargs: bounds,
    )
    monkeypatch.setattr("app.ui_agent._resolve_pour_point_lat_lon", lambda: None)
    monkeypatch.setattr("app.ui_agent.symfluence_domain_shapefile_paths", lambda: {})
    monkeypatch.setattr("app.ui_agent._build_map_reference_legend_entries", lambda **_kwargs: [])

    rendered = build_pour_point_map(fit_data_when_visible=True).get_root().render()

    assert "L.control.layers(" in rendered
    assert "new ResizeObserver(fitWhenVisible)" in rendered
    assert "map.invalidateSize({ pan: false })" in rendered
    assert "target.getClientRects().length === 0" in rendered
    assert "animate: false" in rendered
    assert "fit_data_when_visible=True" in Path("app/ui_agent.py").read_text(encoding="utf-8")
