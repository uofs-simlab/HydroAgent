import folium

from app.ui_agent import _add_choropleth_legend_to_map


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

    assert "max-height:calc(100% - 40px);box-sizing:border-box;overflow:hidden" in rendered
    assert "display:flex;flex-direction:column" in rendered
    assert "flex:1 1 auto;min-height:0;max-height:240px;overflow-y:auto" in rendered
    assert "flex:0 0 auto;border-top:1px solid #e5e7eb" in rendered


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

    assert "max-height:calc(100% - 40px);box-sizing:border-box;overflow-y:auto" in rendered
