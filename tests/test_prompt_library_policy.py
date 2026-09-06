from server.core.prompt_library_policy import (
    DEFAULT_SAVE_PROMPT_HISTORY,
    DEFAULT_USE_PROMPT_LIBRARY_EXAMPLES,
    prompt_library_action_enabled,
)


def test_prompt_library_actions_are_off_by_default():
    assert DEFAULT_USE_PROMPT_LIBRARY_EXAMPLES is False
    assert DEFAULT_SAVE_PROMPT_HISTORY is False


def test_disabled_prompt_library_action_stays_off_with_api_key():
    assert not prompt_library_action_enabled(False, "sk-test")


def test_enabled_prompt_library_action_requires_api_key():
    assert not prompt_library_action_enabled(True, None)
    assert not prompt_library_action_enabled(True, "   ")
    assert prompt_library_action_enabled(True, "sk-test")
