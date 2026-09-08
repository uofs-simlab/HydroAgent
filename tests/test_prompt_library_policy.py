from pathlib import Path

from server.core.prompt_library_policy import (
    DEFAULT_SAVE_PROMPT_HISTORY,
    DEFAULT_USE_PROMPT_LIBRARY_EXAMPLES,
    prompt_library_action_enabled,
)
from server.llm.plan_shared import build_run_plan_schema


def test_prompt_library_actions_are_off_by_default():
    assert DEFAULT_USE_PROMPT_LIBRARY_EXAMPLES is False
    assert DEFAULT_SAVE_PROMPT_HISTORY is False


def test_disabled_prompt_library_action_stays_off_with_api_key():
    assert not prompt_library_action_enabled(False, "sk-test")


def test_enabled_prompt_library_action_requires_api_key():
    assert not prompt_library_action_enabled(True, None)
    assert not prompt_library_action_enabled(True, "   ")
    assert prompt_library_action_enabled(True, "sk-test")


def test_prompt_controls_default_to_unchecked():
    source = Path("app/ui_agent.py").read_text(encoding="utf-8")

    assert '"langprompt_enrich": DEFAULT_USE_PROMPT_LIBRARY_EXAMPLES' in source
    assert '"enable_prompt_phrase_matching": False' in source
    assert '"Use stored-prompt library"' in source
    assert '"Enable phrase matching in prompts"' in source


def test_structured_plan_schema_includes_prompt_matching_replacement_fields():
    config_properties = build_run_plan_schema()["properties"]["config"]["properties"]

    for field in ("data_access", "stream_threshold", "pet_method", "num_processes"):
        assert field in config_properties
