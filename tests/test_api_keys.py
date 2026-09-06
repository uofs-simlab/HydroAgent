from server.core.api_keys import load_api_keys_from_environment


def test_loads_openai_api_key_from_environment():
    api_keys: dict[str, str] = {}

    sources = load_api_keys_from_environment(
        api_keys,
        environ={"OPENAI_API_KEY": "  sk-test-environment  "},
    )

    assert api_keys == {"openai": "sk-test-environment"}
    assert sources == {"openai": "OPENAI_API_KEY"}


def test_environment_does_not_replace_existing_session_key():
    api_keys = {"openai": "sk-session"}

    sources = load_api_keys_from_environment(
        api_keys,
        environ={"OPENAI_API_KEY": "sk-environment"},
    )

    assert api_keys == {"openai": "sk-session"}
    assert sources == {}


def test_blank_environment_key_is_ignored():
    api_keys: dict[str, str] = {}

    sources = load_api_keys_from_environment(
        api_keys,
        environ={"OPENAI_API_KEY": "   "},
    )

    assert api_keys == {}
    assert sources == {}
