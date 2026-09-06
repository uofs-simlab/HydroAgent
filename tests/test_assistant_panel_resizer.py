from pathlib import Path

from app.ui_agent import (
    ASSISTANT_PANEL_WIDTH_STORAGE_KEY,
    assistant_panel_button_css,
    assistant_panel_resizer_html,
    assistant_panel_toggle_css,
    workflow_layout_cleanup_html,
    workflow_panel_dom_hooks_html,
)


def test_assistant_panel_resizer_is_draggable_and_keyboard_accessible():
    markup = assistant_panel_resizer_html(render_version=3)

    assert ASSISTANT_PANEL_WIDTH_STORAGE_KEY in markup
    assert 'handle.setAttribute("role", "separator")' in markup
    assert 'doc.addEventListener("pointermove", trackResize, true)' in markup
    assert 'doc.addEventListener("pointerup", finishResize, true)' in markup
    assert 'handle.addEventListener("lostpointercapture", finishResize)' in markup
    assert 'hostWindow.addEventListener("blur", finishResize)' in markup
    assert "(event.buttons & 1) === 0" in markup
    assert "hostWindow.requestAnimationFrame(applyPendingPointerWidth)" in markup
    assert "dragStartClientX = event.clientX" in markup
    assert "dragStartAssistantWidth = assistantColumn.getBoundingClientRect().width" in markup
    assert "dragMinimumAssistantWidth = Math.min(" in markup
    assert "dragStartAssistantWidth + pointerDelta" in markup
    assert "dragMinimumAssistantWidth," in markup
    assert "rowRight - pendingClientX" not in markup
    assert 'event.key !== "ArrowLeft"' in markup
    assert "sessionStorage.setItem" in markup
    assert "const renderVersion = 3" in markup
    assert "if (handle) handle.remove()" in markup
    assert "handle.dataset.renderVersion = String(renderVersion)" in markup


def test_assistant_toggle_css_keeps_resize_handle_behind_toggle_button():
    css = assistant_panel_toggle_css()

    assert ".sym-assistant-resize-handle" in css
    assert "cursor: col-resize" in css
    assert "div.st-key-assistant_panel_toggle" in css
    assert "width: 1px" in css
    assert "background: var(--sym-divider-color" in css
    assert "div.st-key-assistant_panel_toggle::before" in css
    assert "right: 50% !important" in css
    assert "transform: translateY(-50%) !important" in css


def test_panel_button_styles_do_not_capture_widget_internal_buttons():
    css = assistant_panel_button_css()

    assert ".sym-assistant-styled button," not in css
    assert ".sym-main-styled button," not in css
    assert ".sym-assistant-styled button:hover" not in css
    assert ".sym-main-styled button:hover" not in css
    assert ".sym-assistant-styled [data-testid='stButton'] button" in css
    assert "[data-testid='stTabs'] button" not in css


def test_workflow_panel_styling_does_not_erase_form_control_contrast():
    source = Path("app/ui_agent.py").read_text(encoding="utf-8")

    assert "function panelBg()" not in source
    assert "function paintColumnAncestors" not in source
    assert ".sym-main-styled [data-testid=\"stVerticalBlock\"]" not in source
    assert 'panel.style.removeProperty("background-color")' in source


def test_workflow_nested_scroll_handoff_routes_only_at_boundaries():
    markup = workflow_panel_dom_hooks_html()

    assert 'doc.addEventListener("wheel", handOffNestedScroll' in markup
    assert "nearestNestedScroller" in markup
    assert "if (nested && canScroll(nested, event.deltaY)) return" in markup
    assert "panel.scrollTop += deltaY" in markup
    assert "passive: false" in markup


def test_workflow_panels_fit_remaining_viewport_height():
    markup = workflow_panel_dom_hooks_html()
    source = Path("app/ui_agent.py").read_text(encoding="utf-8")

    assert "const rowRect = row.getBoundingClientRect()" in markup
    assert 'testId === "stVerticalBlock"' in markup
    assert 'testId === "stLayoutWrapper"' in markup
    assert "hostWindow.innerHeight - rowTop - 8" in markup
    assert '"--sym-workflow-panel-height"' in markup
    assert "const sizedElements = new Set([row, ...columns, ...columnBlocks])" in markup
    assert 'hookHost.style.setProperty("position", "absolute", "important")' in markup
    assert 'hostWindow.addEventListener("resize", refreshPanels' in markup
    assert 'element.style.setProperty("height", availableHeight + "px", "important")' in markup
    assert "hostWindow.requestAnimationFrame(refreshPanels)" in markup
    assert "var(--sym-workflow-panel-height, 720px)" in source
    assert "calc(100dvh - 10.5rem)" not in source


def test_workflow_column_sizing_does_not_leak_to_other_pages():
    resizer = assistant_panel_resizer_html()
    css = assistant_panel_toggle_css()
    cleanup = workflow_layout_cleanup_html()
    source = Path("app/ui_agent.py").read_text(encoding="utf-8")

    assert 'mainColumn.classList.add("sym-workflow-main-column")' in resizer
    assert 'row.style.setProperty("--sym-assistant-panel-width"' in resizer
    assert 'mainColumn.style.setProperty("flex"' not in resizer
    assert ':has(.sym-main-panel) > .sym-workflow-main-column' in css
    assert ':has(.sym-main-panel) > .sym-workflow-assistant-column' in css
    assert '["flex", "width", "min-width", "position", "overflow"]' in cleanup
    assert "column.style.removeProperty(property)" in cleanup
    assert 'column.classList.remove(' in cleanup
    assert '.sym-workflow-panels ~ div [data-testid="stHorizontalBlock"]' not in source


def test_non_workflow_pages_render_their_title_only_in_the_shared_shell():
    source = Path("app/workflow_extras.py").read_text(encoding="utf-8")

    for title in ("Dashboard", "Experiments", "Results", "Data", "Logs"):
        assert f'st.subheader("{title}")' not in source


def test_header_and_panel_dividers_share_light_and_dark_theme_color():
    source = Path("app/ui_agent.py").read_text(encoding="utf-8")

    assert "--sym-divider-color: rgba(49, 51, 63, 0.18)" in source
    assert "--sym-divider-color: rgba(250, 250, 250, 0.42)" in source
    assert "border-bottom: 1px solid var(--sym-divider-color)" in source


def test_closed_assistant_layout_removes_empty_third_column():
    source = Path("app/ui_agent.py").read_text(encoding="utf-8")

    assert 'main_col, toggle_col = st.columns([0.98, 0.02], gap="small")' in source
    assert "assistant_col = None" in source
    assert "if assistant_col is not None:" in source
    assert "[0.98, 0.02, 0.001]" not in source
    assert "assistant_panel_resize_version" in source
