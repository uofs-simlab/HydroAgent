import pytest
from streamlit.testing.v1 import AppTest

from app import ui_agent


def _layer_controls_app():
    import streamlit as st

    from app.ui_agent import render_map_layer_controls, reset_map_layer_ui_state

    if st.button("Reset layers"):
        reset_map_layer_ui_state()
    render_map_layer_controls("out")


@pytest.fixture
def layer_controls(monkeypatch):
    available = {path_key for _, _, path_key in ui_agent.MAP_LAYER_SPECS}
    monkeypatch.setattr(
        ui_agent, "symfluence_domain_shapefile_paths", lambda: {"dem": "dem.shp"}
    )
    monkeypatch.setattr(
        ui_agent, "_review_layer_available", lambda path_key, _paths: path_key in available
    )
    app = AppTest.from_function(_layer_controls_app)
    return app, available


def test_color_layer_is_exclusive_and_overlays_are_independent(layer_controls):
    app, _ = layer_controls
    app.run()

    assert not app.exception
    assert {checkbox.label for checkbox in app.checkbox} == {
        "Pour point", "Bounding box", "River basins", "River network"
    }
    assert len(app.radio) == 1
    assert "None" in app.radio[0].options
    app.checkbox(key="out_show_riverbasins_layer").check().run()
    app.checkbox(key="out_show_rivernetwork_layer").check().run()

    for selected in ("dem", "hrugru", "forcing", "none"):
        app.radio[0].set_value(selected).run()
        assert not app.exception
        enabled = {
            path_key
            for state_key, _, path_key in ui_agent.MAP_FILL_LAYER_SPECS
            if app.session_state[state_key]
        }
        assert enabled == (set() if selected == "none" else {selected})
        assert all(checkbox.value for checkbox in app.checkbox)


def test_missing_color_layer_clears_selection_and_can_reappear(layer_controls):
    app, available = layer_controls
    app.run().radio[0].set_value("dem").run()
    available.remove("dem")
    app.run()

    assert not app.exception
    assert app.radio[0].value == "none"
    assert "DEM" not in app.radio[0].options
    assert not app.session_state["show_dem_layer"]

    available.add("dem")
    app.run().radio[0].set_value("dem").run()
    assert not app.exception
    assert app.session_state["show_dem_layer"]

    available.clear()
    app.run()
    assert not app.exception
    assert app.radio[0].disabled
    assert app.radio[0].value == "none"
    assert all(checkbox.disabled and not checkbox.value for checkbox in app.checkbox)
    assert not any(app.session_state[key] for key, _, _ in ui_agent.MAP_FILL_LAYER_SPECS)


def test_reset_clears_color_and_river_overlay_widgets(layer_controls):
    app, _ = layer_controls
    app.run().radio[0].set_value("dem").run()
    app.checkbox(key="out_show_riverbasins_layer").check().run()
    app.button[0].click().run()

    assert not app.exception
    assert app.radio[0].value == "none"
    assert not app.session_state["show_dem_layer"]
    assert not app.checkbox(key="out_show_riverbasins_layer").value
    assert app.checkbox(key="out_show_pour_point_layer").value
    assert app.checkbox(key="out_show_bounding_box_layer").value


def test_review_domain_uses_active_run_config(tmp_path):
    run_folder = "Logan_River_CIROH_demo_water_year_2005_3"
    run_dir = tmp_path / run_folder
    run_dir.mkdir()
    (run_dir / "config.yaml").write_text(
        "DOMAIN_NAME: Logan_River_CIROH_demo_3\n",
        encoding="utf-8",
    )

    assert ui_agent.review_symfluence_domain_name(
        "Logan_River_CIROH_demo",
        "water_year_2005",
        run_folder=run_folder,
        runs_dir=tmp_path,
    ) == "Logan_River_CIROH_demo_3"


def test_review_layer_signature_detects_new_shapefile(tmp_path):
    hru_path = tmp_path / "domain_HRUs_GRUs.shp"
    paths = {"hrugru": str(hru_path)}

    before = ui_agent.review_layer_artifact_signature(paths)
    hru_path.write_bytes(b"shapefile")
    after = ui_agent.review_layer_artifact_signature(paths)

    assert before != after
