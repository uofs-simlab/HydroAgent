from app.ui_agent import (
    ASSISTANT_PANEL_WIDTH_STORAGE_KEY,
    assistant_panel_resizer_html,
    assistant_panel_toggle_css,
)


def test_assistant_panel_resizer_is_draggable_and_keyboard_accessible():
    markup = assistant_panel_resizer_html()

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


def test_assistant_toggle_css_keeps_resize_handle_behind_toggle_button():
    css = assistant_panel_toggle_css()

    assert ".sym-assistant-resize-handle" in css
    assert "cursor: col-resize" in css
    assert "div.st-key-assistant_panel_toggle" in css
