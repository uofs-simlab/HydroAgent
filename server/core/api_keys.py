from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping


API_KEY_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
}


def load_api_keys_from_environment(
    api_keys: MutableMapping[str, str],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Load supported provider keys without replacing an existing session key.

    The returned mapping contains provider IDs and environment-variable names so
    the UI can identify the credential source without exposing key values.
    """
    environment = os.environ if environ is None else environ
    loaded_sources: dict[str, str] = {}

    for provider, variable_name in API_KEY_ENV_VARS.items():
        if str(api_keys.get(provider) or "").strip():
            continue
        value = str(environment.get(variable_name) or "").strip()
        if not value:
            continue
        api_keys[provider] = value
        loaded_sources[provider] = variable_name

    return loaded_sources
