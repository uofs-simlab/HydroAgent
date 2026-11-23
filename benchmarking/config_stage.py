"""Write config.yaml from a resolved plan using the app template."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from server.core.template import render_config_from_spec

HYDROAGENT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = HYDROAGENT_ROOT / "configs" / "symfluence_template.yaml"


def spec_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    cfg = plan.get("config") if isinstance(plan, dict) else None
    if not isinstance(cfg, dict):
        return {}
    spec = dict(cfg)
    extra = spec.pop("extra_config", None)
    if isinstance(extra, dict):
        for key, value in extra.items():
            spec.setdefault(key, value)
    return spec


def write_executable_config(plan: dict[str, Any], out_path: Path) -> Path:
    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f"Missing SYMFLUENCE template: {TEMPLATE_PATH}")
    return render_config_from_spec(spec_from_plan(plan), TEMPLATE_PATH, out_path)
