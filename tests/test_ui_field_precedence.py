from server.core.ui_field_precedence import (
    clear_explicit_ui_fields,
    explicit_ui_fields,
    mark_ui_fields_explicit,
    select_explicit_ui_values,
    ui_field_is_explicit,
)


def test_untouched_defaults_are_not_explicit_overrides():
    state = {
        "forcing_dataset": "ERA5",
        "streamflow_data_provider": "WSC",
    }

    assert explicit_ui_fields(state) == set()
    assert select_explicit_ui_values(state, state) == {}
    assert not ui_field_is_explicit(state, "forcing_dataset")
    assert not ui_field_is_explicit(state, "streamflow_data_provider")


def test_deliberate_gui_edits_are_tracked_as_overrides():
    state = {
        "forcing_dataset": "ERA5",
        "streamflow_data_provider": "WSC",
    }

    mark_ui_fields_explicit(state, "forcing_dataset")

    assert explicit_ui_fields(state) == {"forcing_dataset"}
    assert select_explicit_ui_values(state, state) == {"forcing_dataset": "ERA5"}
    assert ui_field_is_explicit(state, "forcing_dataset")
    assert not ui_field_is_explicit(state, "streamflow_data_provider")

    clear_explicit_ui_fields(state)
    assert explicit_ui_fields(state) == set()
