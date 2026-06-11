from __future__ import annotations
# Layout note: minor UI spacing tweaks.

from pathlib import Path
import sys
import os
import subprocess
import yaml
import streamlit as st
import traceback
import json
import html
import hashlib
import datetime as dt
import pandas as pd
import folium
import streamlit.components.v1 as components
from streamlit_folium import st_folium
import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import workflow_extras as wx  # noqa: E402
from input_panel_sync import sync_plan_config_to_session  # noqa: E402
from widget_keys import (  # noqa: E402
    bump_all_input_widget_versions,
    bump_config_preview_version,
    config_preview_widget_key,
    experiment_datetime_widget_key,
    input_panel_widget_key,
    mpi_widget_key,
)
from server.core.ui_config_fields import (  # noqa: E402
    DOMAIN_DEF_OPTIONS,
    FORCING_DATASET_OPTIONS,
    HYDROLOGICAL_MODEL_OPTIONS,
    coerce_selectbox_value,
    lookup_plan_config,
    normalize_forcing_dataset,
    normalize_hydrological_model,
    summarize_plan_changes_for_chat,
)
from server.core.template import (
    FIELD_MAP,
    finalize_symfluence_config,
    render_config_from_spec,
    spec_key_to_yaml_key,
)
from server.core.validate import validate_spec  # noqa: E402

from server.core.parameter_registry import (
    load_template_parameters,
    is_known_symfluence_parameter,
    coerce_scalar_value,
)

from server.capabilities.load_catalog import load_catalog
from server.capabilities.proven_status import PROVEN_STATUS
from server.capabilities.resolve_dependencies import WORKFLOW_PRIORITY, resolve_step_dependencies
from server.core.local_domain import (
    copy_reusable_domain_artifacts,
    infer_reuse_source_domain,
    local_catchment_needs_restore,
    restore_local_domain_artifacts,
    seed_mac_duplicate_domain_from_basin,
    user_request_reuses_local_domain_data,
)
from server.core.run_naming import (
    allocate_unique_run_folder,
    assistant_run_is_established,
    parse_mac_duplicate_suffix,
    preview_run_folder_name,
    resolve_run_workspace,
    run_folder_belongs_to_workspace,
    run_folder_for_symfluence_domain,
    symfluence_domain_for_run_folder,
    symfluence_domain_mac_suffix,
)
from server.core.plan_rules import (
    apply_chat_config_edits,
    apply_chat_step_edits,
    domain_has_local_dem,
    domain_has_local_streamflow,
    domain_has_complete_local_workflow,
    ensure_skip_process_observed_when_local_streamflow,
    extract_station_id_from_request,
    infer_goal_steps_from_request,
    normalize_local_workflow_plan,
    plan_requires_bounding_box,
    plan_uses_local_data,
    strip_user_forbidden_download_steps,
    user_requires_fresh_cloud_workflow,
)

OPENAI_AVAILABLE = True
try:
    from server.llm.openai_provider import OpenAIProvider  # type: ignore
except Exception:
    OPENAI_AVAILABLE = False

GeminiProvider = None  # type: ignore
GEMINI_AVAILABLE = False
GEMINI_IMPORT_ERROR = ""


def ensure_gemini_provider() -> bool:
    """Import Gemini provider lazily (supports install without full app restart)."""
    global GeminiProvider, GEMINI_AVAILABLE, GEMINI_IMPORT_ERROR
    if GEMINI_AVAILABLE and GeminiProvider is not None:
        return True
    try:
        from server.llm.gemini_provider import GeminiProvider as _GeminiProvider  # type: ignore

        GeminiProvider = _GeminiProvider
        GEMINI_AVAILABLE = True
        GEMINI_IMPORT_ERROR = ""
        return True
    except Exception as exc:
        GeminiProvider = None
        GEMINI_AVAILABLE = False
        GEMINI_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        return False


ensure_gemini_provider()

ClaudeProvider = None  # type: ignore
CLAUDE_AVAILABLE = False
CLAUDE_IMPORT_ERROR = ""


def ensure_claude_provider() -> bool:
    """Import Claude provider lazily (supports install without full app restart)."""
    global ClaudeProvider, CLAUDE_AVAILABLE, CLAUDE_IMPORT_ERROR
    if CLAUDE_AVAILABLE and ClaudeProvider is not None:
        return True
    try:
        from server.llm.claude_provider import ClaudeProvider as _ClaudeProvider  # type: ignore

        ClaudeProvider = _ClaudeProvider
        CLAUDE_AVAILABLE = True
        CLAUDE_IMPORT_ERROR = ""
        return True
    except Exception as exc:
        ClaudeProvider = None
        CLAUDE_AVAILABLE = False
        CLAUDE_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        return False


ensure_claude_provider()

FORCINGS_AVAILABLE = True

USER_HOME = Path.home()

CONFIG_DIR = USER_HOME / ".symfluence_assistant"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load_local_settings() -> dict:
    if CONFIG_FILE.exists():
        try:
            return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def save_local_settings(settings: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        yaml.safe_dump(settings, sort_keys=False),
        encoding="utf-8",
    )


def normalize_path_text(value) -> str:
    return str(value).replace("\\", "/")


ASSISTANT_BASE = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ASSISTANT_BASE / "configs" / "symfluence_template.yaml"
RUNS_DIR = ASSISTANT_BASE / "runs"
PREVIEW_DIR = RUNS_DIR / "_preview"
RUN_FOLDER_SKIP = {"_preview"}

DEFAULT_SYMFLUENCE_REPO = USER_HOME / "installs" / "SYMFLUENCE"
DEFAULT_SYMFLUENCE_DATA_DIR = USER_HOME / "installs" / "SYMFLUENCE_data"
DEFAULT_SYMFLUENCE_PYTHON = USER_HOME / "installs" / "SYMFLUENCE" / "venv" / "bin" / "python"

LOCAL_SETTINGS = load_local_settings()

SYMFLUENCE_REPO = Path(
    LOCAL_SETTINGS.get("symfluence_repo", str(DEFAULT_SYMFLUENCE_REPO))
)

SYMFLUENCE_DATA_DIR = Path(
    LOCAL_SETTINGS.get("symfluence_data_dir", str(DEFAULT_SYMFLUENCE_DATA_DIR))
)

SYMFLUENCE_PYTHON = Path(
    LOCAL_SETTINGS.get("symfluence_python", str(DEFAULT_SYMFLUENCE_PYTHON))
)


def s(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return str(value).lower()
    return str(value).strip()


def parse_datetime_value(value: str, fallback: dt.datetime) -> dt.datetime:
    value = s(value)
    if not value:
        return fallback
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            parsed = dt.datetime.strptime(value, fmt)
            if fmt == "%Y-%m-%d":
                return parsed.replace(hour=fallback.hour, minute=fallback.minute)
            return parsed
        except Exception:
            pass
    return fallback


def format_datetime_value(date_value, time_value) -> str:
    return f"{date_value:%Y-%m-%d} {time_value:%H:%M}"


def bump_input_panel_widget_versions() -> None:
    """Refresh Input-tab widgets that cache values by Streamlit widget key."""
    bump_all_input_widget_versions()


def plan_cfg_lookup(cfg: dict, *keys: str):
    return lookup_plan_config(cfg, *keys)


def sync_mpi_to_run_plan() -> None:
    if not st.session_state.get("run_plan"):
        return
    plan = st.session_state.run_plan
    plan.setdefault("config", {})
    mpi_val = int(st.session_state.mpi)
    plan["config"]["NUM_PROCESSES"] = mpi_val
    plan["config"]["num_processes"] = mpi_val


def resolve_num_processes_from_plan_cfg(plan_cfg: dict | None) -> int | None:
    plan_cfg = plan_cfg or {}
    raw = plan_cfg_lookup(
        plan_cfg,
        "NUM_PROCESSES",
        "num_processes",
        "MPI_PROCESSES",
        "mpi_processes",
    )
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


_COPY_ICON_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
     aria-hidden="true">
  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
</svg>
"""

_COPY_CHECK_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
     aria-hidden="true">
  <polyline points="20 6 9 17 4 12"></polyline>
</svg>
"""

SIDEBAR_GREY_BUTTON_KEYS = ("save_local_paths",)

MAIN_PANEL_GREY_BUTTON_KEYS = (
    "start_new_assistant_run",
    "load_assistant_run_btn",
    "load_data_domain_btn",
    "input_single_validate",
    "input_single_dry_run",
    "input_single_run_model",
    "input_single_calibrate_model",
    "clear_selected_pour_point",
    "clear_selected_bbox",
    "manual_validate",
    "manual_dryrun",
    "manual_setup",
    "manual_run_model",
    "run_results_refresh",
    "run_results_extract_routed",
    "run_results_summarize_routed",
    "shortcut_input_preprocessing",
    "shortcut_input_model",
    "shortcut_input_postprocess",
)

MAIN_PANEL_GREY_BUTTON_KEY_PREFIXES = (
    "input_single_",
    "shortcut_input_",
)

ASSISTANT_PANEL_BUTTON_KEYS = (
    "save_openai_key",
    "transcribe_voice_to_prompt",
    "transcribe_voice_to_chat",
    "generate_plan_gpt",
    "resolve_dependencies",
    "execute_plan_button",
    "clear_plan_button",
    "clear_chat_button",
    "clear_chat_and_plan_button",
    "apply_fix_pour_point",
    "apply_fix_bounding_box",
    "apply_fix_hydrological_model",
    "apply_fix_domain_def",
    "apply_fix_forcing_dataset",
    "shortcut_assistant_preprocessing",
    "shortcut_assistant_model",
    "shortcut_assistant_postprocess",
    "calibration_assistant_run_calibrate",
)


def assistant_panel_button_css() -> str:
    """CSS for slate workflow/sidebar buttons: st-key-* selectors + panel scope classes."""
    grey_button_keys = (
        ASSISTANT_PANEL_BUTTON_KEYS
        + SIDEBAR_GREY_BUTTON_KEYS
        + MAIN_PANEL_GREY_BUTTON_KEYS
    )
    key_btns = ",\n".join(f"div.st-key-{key} button" for key in grey_button_keys)
    prefix_btns = ",\n".join(
        f'div[class*="st-key-{prefix}"] button' for prefix in MAIN_PANEL_GREY_BUTTON_KEY_PREFIXES
    )
    key_btns_hover = ",\n".join(
        f"div.st-key-{key} button:hover:not(:disabled)" for key in grey_button_keys
    )
    prefix_btns_hover = ",\n".join(
        f'div[class*="st-key-{prefix}"] button:hover:not(:disabled)'
        for prefix in MAIN_PANEL_GREY_BUTTON_KEY_PREFIXES
    )
    key_btns_disabled = ",\n".join(
        f"div.st-key-{key} button:disabled" for key in grey_button_keys
    )
    prefix_btns_disabled = ",\n".join(
        f'div[class*="st-key-{prefix}"] button:disabled'
        for prefix in MAIN_PANEL_GREY_BUTTON_KEY_PREFIXES
    )
    panel_scoped = (
        ".sym-assistant-styled button",
        ".sym-assistant-styled [data-testid='stButton'] button",
        ".sym-assistant-styled [data-testid='stTabs'] button",
        ".sym-main-styled button",
        ".sym-main-styled [data-testid='stButton'] button",
        ".sym-main-styled [data-testid='stTabs'] button",
    )
    scoped = panel_scoped + (key_btns, prefix_btns)
    scoped_hover = (
        ".sym-assistant-styled button:hover:not(:disabled)",
        ".sym-assistant-styled [data-testid='stButton'] button:hover:not(:disabled)",
        ".sym-assistant-styled [data-testid='stTabs'] button:hover:not(:disabled)",
        ".sym-main-styled button:hover:not(:disabled)",
        ".sym-main-styled [data-testid='stButton'] button:hover:not(:disabled)",
        ".sym-main-styled [data-testid='stTabs'] button:hover:not(:disabled)",
        key_btns_hover,
        prefix_btns_hover,
    )
    scoped_disabled = (
        ".sym-assistant-styled button:disabled",
        ".sym-assistant-styled [data-testid='stButton'] button:disabled",
        ".sym-main-styled button:disabled",
        ".sym-main-styled [data-testid='stButton'] button:disabled",
        key_btns_disabled,
        prefix_btns_disabled,
    )
    label_scoped = (
        ".sym-assistant-styled [data-testid='stButton'] button p",
        ".sym-assistant-styled [data-testid='stTabs'] button p",
        ".sym-main-styled [data-testid='stButton'] button p",
        ".sym-main-styled [data-testid='stTabs'] button p",
    )
    return f"""
    {", ".join(scoped)} {{
        background-color: #475569 !important;
        background: #475569 !important;
        border: 1px solid #334155 !important;
        color: #f8fafc !important;
        box-shadow: none !important;
    }}
    {", ".join(scoped_hover)} {{
        background-color: #64748b !important;
        background: #64748b !important;
        border-color: #475569 !important;
        color: #ffffff !important;
    }}
    {", ".join(scoped_disabled)} {{
        background-color: #94a3b8 !important;
        background: #94a3b8 !important;
        border-color: #64748b !important;
        color: #e2e8f0 !important;
        opacity: 0.9 !important;
    }}
    {", ".join(label_scoped)},
    {", ".join(f"div.st-key-{key} button p" for key in grey_button_keys)},
    {", ".join(f'div[class*="st-key-{prefix}"] button p' for prefix in MAIN_PANEL_GREY_BUTTON_KEY_PREFIXES)} {{
        color: inherit !important;
    }}
    """


def workflow_panel_surface_css() -> str:
    """Grey workflow column surfaces (match Streamlit sidebar tone)."""
    return """
    .sym-assistant-styled,
    .sym-main-styled,
    .sym-assistant-styled [data-testid="stVerticalBlock"],
    .sym-main-styled [data-testid="stVerticalBlock"] {
        background-color: #f0f2f6 !important;
    }
    @media (prefers-color-scheme: dark) {
        .sym-assistant-styled,
        .sym-main-styled,
        .sym-assistant-styled [data-testid="stVerticalBlock"],
        .sym-main-styled [data-testid="stVerticalBlock"] {
            background-color: #262730 !important;
        }
    }
    .right-panel {
        border: none;
        border-radius: 0;
        padding: 0;
        background: transparent !important;
        box-shadow: none;
    }
    """


def render_workflow_panel_dom_hooks() -> None:
    """Tag workflow scroll panels for button styling and grey backgrounds."""
    components.html(
        """
        <script>
        (function () {
            const doc = window.parent.document;
            function panelBg() {
                const sidebar = doc.querySelector('[data-testid="stSidebar"]');
                return sidebar
                    ? getComputedStyle(sidebar).backgroundColor
                    : "rgb(240, 242, 246)";
            }
            function paintColumnAncestors(node, bg) {
                let parent = node ? node.parentElement : null;
                for (let i = 0; i < 12 && parent; i += 1) {
                    const testId = parent.getAttribute && parent.getAttribute("data-testid");
                    if (testId === "column" || testId === "stColumn") {
                        parent.style.setProperty("background-color", bg, "important");
                        return;
                    }
                    parent = parent.parentElement;
                }
            }
            function markPanel(markerClass, styledClass) {
                const marker = doc.querySelector("." + markerClass);
                if (!marker) return;
                const bg = panelBg();
                let el = marker.parentElement;
                for (let i = 0; i < 40 && el; i += 1) {
                    if (el.getAttribute && el.getAttribute("data-testid") === "stVerticalBlockBorderWrapper") {
                        el.classList.add(styledClass);
                        el.style.setProperty("background-color", bg, "important");
                        paintColumnAncestors(el, bg);
                        return;
                    }
                    el = el.parentElement;
                }
            }
            function refreshPanels() {
                markPanel("sym-main-panel", "sym-main-styled");
                markPanel("sym-assistant-panel", "sym-assistant-styled");
            }
            refreshPanels();
            window.setInterval(refreshPanels, 800);
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def render_copy_anchor(anchor_id: str) -> None:
    st.markdown(
        f'<span id="{html.escape(anchor_id, quote=True)}" class="sym-copy-anchor"></span>',
        unsafe_allow_html=True,
    )


def render_inline_copy_button(
    *,
    anchor_id: str,
    fallback_text: str,
    key: str,
) -> None:
    """Self-contained copy control (iframe button + iframe timer); does not touch parent DOM."""
    btn_id = f"sym_copy_{hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()[:10]}"
    payload = s(fallback_text)
    components.html(
        f"""
        <div style="display:flex;justify-content:flex-end;align-items:center;width:100%;">
          <button id="{btn_id}" type="button" title="Copy to clipboard" aria-label="Copy to clipboard"
            style="display:inline-flex;align-items:center;justify-content:center;width:2rem;height:2rem;
            padding:0;border:none;border-radius:0.35rem;background:transparent;color:inherit;
            cursor:pointer;opacity:0.9;">
            {_COPY_ICON_SVG}
          </button>
        </div>
        <script>
        (function () {{
            const btn = document.getElementById({json.dumps(btn_id)});
            if (!btn) return;
            const anchorId = {json.dumps(anchor_id)};
            const fallback = {json.dumps(payload)};
            const copyIcon = {json.dumps(_COPY_ICON_SVG.strip())};
            const checkIcon = {json.dumps(_COPY_CHECK_SVG.strip())};
            let revertTimer = null;

            function readLiveText() {{
                try {{
                    const doc = window.parent.document;
                    const anchor = doc.getElementById(anchorId);
                    if (!anchor) return fallback;
                    let el = anchor.parentElement;
                    while (el) {{
                        if (el.matches && el.matches('[data-testid="stVerticalBlockBorderWrapper"]')) {{
                            const tas = el.querySelectorAll('textarea');
                            for (let i = 0; i < tas.length; i += 1) {{
                                const ta = tas[i];
                                const after = anchor.compareDocumentPosition(ta) & Node.DOCUMENT_POSITION_FOLLOWING;
                                if (after && ta.value && ta.value.trim()) return ta.value;
                            }}
                            if (tas.length) {{
                                const last = tas[tas.length - 1];
                                if (last.value && last.value.trim()) return last.value;
                            }}
                            return fallback;
                        }}
                        el = el.parentElement;
                    }}
                }} catch (e) {{}}
                return fallback;
            }}

            function copyNow(text) {{
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.setAttribute('readonly', '');
                ta.style.position = 'fixed';
                ta.style.top = '0';
                ta.style.left = '0';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                let ok = false;
                try {{
                    ok = document.execCommand('copy');
                }} catch (e) {{
                    ok = false;
                }}
                document.body.removeChild(ta);
                return ok;
            }}

            function resetIcon() {{
                btn.innerHTML = copyIcon;
                btn.style.color = 'inherit';
                btn.title = 'Copy to clipboard';
                btn.setAttribute('aria-label', 'Copy to clipboard');
            }}

            function showCheck() {{
                btn.innerHTML = checkIcon;
                btn.style.color = '#059669';
                btn.title = 'Copied!';
                btn.setAttribute('aria-label', 'Copied!');
                if (revertTimer) window.clearTimeout(revertTimer);
                revertTimer = window.setTimeout(function () {{
                    resetIcon();
                    revertTimer = null;
                }}, 1500);
            }}

            btn.addEventListener('mouseenter', function () {{
                btn.style.background = 'rgba(128,128,128,0.18)';
            }});
            btn.addEventListener('mouseleave', function () {{
                btn.style.background = 'transparent';
            }});
            btn.addEventListener('click', function (ev) {{
                ev.preventDefault();
                ev.stopPropagation();
                const text = readLiveText();
                if (!text || !String(text).trim()) {{
                    btn.title = 'Nothing to copy';
                    btn.setAttribute('aria-label', 'Nothing to copy');
                    if (revertTimer) window.clearTimeout(revertTimer);
                    revertTimer = window.setTimeout(function () {{
                        resetIcon();
                        revertTimer = null;
                    }}, 1200);
                    return;
                }}
                if (copyNow(text)) {{
                    showCheck();
                    return;
                }}
                if (navigator.clipboard && navigator.clipboard.writeText) {{
                    navigator.clipboard.writeText(text).then(showCheck).catch(function () {{
                        btn.title = 'Copy failed';
                    }});
                    return;
                }}
                btn.title = 'Copy failed';
            }});
        }})();
        </script>
        """,
        height=44,
    )


def render_editable_block_with_copy(
    title: str,
    *,
    anchor_id: str,
    copy_key: str,
    fallback_text: str,
    render_body,
) -> None:
    """Bordered editable block with an independent copy button in the header row."""
    with st.container(border=True):
        title_col, copy_col = st.columns([0.86, 0.14], vertical_alignment="center")
        with title_col:
            st.markdown(f"**{title}**")
        with copy_col:
            render_inline_copy_button(
                anchor_id=anchor_id,
                fallback_text=fallback_text,
                key=copy_key,
            )
        render_copy_anchor(anchor_id)
        render_body()


def sanitize_config_token(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s(name)).strip("_")


def symfluence_domain_name(domain_name: str, experiment_id: str = "") -> str:
    """Basin identifier for SYMFLUENCE DOMAIN_NAME (never includes experiment_id)."""
    domain_name = sanitize_config_token(domain_name)
    experiment_id = sanitize_config_token(experiment_id)
    return split_domain_name_from_combined(domain_name, experiment_id) or domain_name


def symfluence_data_domain_dir(
    domain_name: str,
    experiment_id: str = "",
    *,
    run_folder: str = "",
) -> Path:
    basin = symfluence_domain_name(domain_name, experiment_id)
    if run_folder:
        sym_domain = symfluence_domain_for_run_folder(run_folder, basin, experiment_id)
    else:
        sym_domain = basin
    return SYMFLUENCE_DATA_DIR / f"domain_{sym_domain}"


def sync_run_folder_from_session(*, unlock: bool = False) -> None:
    """Keep or allocate a non-colliding run folder for the current domain + experiment."""
    domain_name = s(st.session_state.domain_name)
    experiment_id = s(st.session_state.experiment_id)
    if not domain_name or not experiment_id:
        return
    if unlock:
        st.session_state.run_workspace_locked = False
    current = s(st.session_state.get("run_folder"))
    if st.session_state.get("run_workspace_locked") and current:
        return
    basin = symfluence_domain_name(domain_name, experiment_id)
    if current and not unlock and assistant_run_is_established(current, RUNS_DIR):
        return
    _, mac_n = parse_mac_duplicate_suffix(current)
    if (
        current
        and not unlock
        and mac_n is not None
        and run_folder_belongs_to_workspace(current, basin, experiment_id)
    ):
        return
    run_folder, _sym_domain = resolve_run_workspace(
        basin,
        experiment_id,
        current,
        runs_dir=RUNS_DIR,
        data_dir=SYMFLUENCE_DATA_DIR,
        workspace_locked=bool(st.session_state.get("run_workspace_locked")),
    )
    st.session_state.run_folder = run_folder


def finalize_spec_for_symfluence(spec_dict: dict) -> dict:
    """Write DOMAIN_NAME and EXPERIMENT_ID separately; set assistant runs/ folder."""
    raw_domain = spec_dict.get("domain_name") or "domain"
    raw_expid = spec_dict.get("experiment_id") or "exp"
    basin = symfluence_domain_name(str(raw_domain), str(raw_expid))
    expid = sanitize_config_token(str(raw_expid)) or str(raw_expid)
    user_request = user_prompt_for_metadata() or s(st.session_state.get("nl_request", ""))
    run_folder, sym_domain = resolve_run_workspace(
        basin,
        expid,
        s(st.session_state.get("run_folder")),
        runs_dir=RUNS_DIR,
        data_dir=SYMFLUENCE_DATA_DIR,
        workspace_locked=bool(st.session_state.get("run_workspace_locked")),
    )
    if user_requires_fresh_cloud_workflow(user_request, spec_dict):
        sym_domain = basin
    spec_dict["domain_name"] = sym_domain
    spec_dict["experiment_id"] = expid
    st.session_state.run_folder = run_folder
    return spec_dict


def default_postprocess_domain_dir(cfg: dict) -> str:
    """SYMFLUENCE data folder for simulations (avoids domain_domain_* double prefix)."""
    data_dir = Path(normalize_path_text(cfg.get("SYMFLUENCE_DATA_DIR", SYMFLUENCE_DATA_DIR)))
    domain = symfluence_domain_name(
        s(cfg.get("DOMAIN_NAME")) or s(st.session_state.domain_name),
        s(cfg.get("EXPERIMENT_ID")) or s(st.session_state.experiment_id),
    )
    if not domain:
        domain = symfluence_domain_name(
            s(st.session_state.get("run_folder")),
            s(st.session_state.experiment_id),
        )
    return str(data_dir / f"domain_{domain}")


def mark_spatial_inputs_stale() -> None:
    """Map/plan updates should reset spatial text widgets on the next render."""
    st.session_state.spatial_inputs_stale = True


def refresh_spatial_input_widgets() -> None:
    """Clear cached text-input widget state so map/plan values appear in the boxes."""
    if not st.session_state.pop("spatial_inputs_stale", False):
        return
    for widget_key in ("pour_point_input", "bounding_box_input"):
        if widget_key in st.session_state:
            del st.session_state[widget_key]
    if s(st.session_state.selected_pour_point):
        st.session_state.pour_point_input = s(st.session_state.selected_pour_point)
    if s(st.session_state.selected_bounding_box):
        st.session_state.bounding_box_input = s(st.session_state.selected_bounding_box)


def effective_plan_config_for_preview() -> dict:
    """Plan config merged with live map/UI spatial selections for preview generation."""
    plan_cfg = dict((st.session_state.run_plan or {}).get("config") or {})
    pour = s(st.session_state.selected_pour_point) or s(st.session_state.pour_point_input)
    bbox = (
        s(st.session_state.selected_bounding_box)
        or s(st.session_state.bounding_box_input)
    )
    if pour:
        plan_cfg["pour_point_coords"] = pour
    if bbox:
        plan_cfg["bounding_box_coords"] = bbox
    return plan_cfg


def current_hydrological_model(plan_cfg: dict | None = None) -> str:
    plan_cfg = plan_cfg or {}
    return normalize_hydrological_model(
        s(lookup_plan_config(plan_cfg, "hydrological_model", "HYDROLOGICAL_MODEL"))
        or s(st.session_state.get("hydrological_model"))
    )


def resolve_requested_plan_dependencies(plan: dict, user_request: str = "") -> dict:
    catalog = load_catalog()
    steps = list(plan.get("steps", []) or [])
    user_request = user_request or conversation_text_for_plan_rules()

    goal_steps = [step for step in steps if step not in ("validate_config", "dry_run")]
    if not goal_steps:
        goal_steps = infer_goal_steps_from_request(user_request)
        if not goal_steps and re.search(r"\bsumma\b", user_request, flags=re.IGNORECASE):
            goal_steps = ["run_model"]

    resolved_steps: list[str] = []
    for goal in goal_steps:
        try:
            chain = resolve_step_dependencies(goal, catalog, include_validate=False)
        except Exception:
            chain = [goal]
        for item in chain:
            if item not in resolved_steps:
                resolved_steps.append(item)

    if "validate_config" not in resolved_steps:
        resolved_steps.insert(0, "validate_config")

    if "dry_run" not in steps:
        resolved_steps = [step for step in resolved_steps if step != "dry_run"]

    resolved_steps = sorted(
        resolved_steps,
        key=lambda step: WORKFLOW_PRIORITY.get(step, 999),
    )

    new_plan = json.loads(json.dumps(plan))
    new_plan["steps"] = resolved_steps

    cfg = new_plan.setdefault("config", {})

    required_config_fields = set()

    for op in catalog.get("operations", []):
        if op.get("name") in resolved_steps:
            for req in op.get("requires", []):
                if req in {
                    "pour_point_coords",
                    "bounding_box_coords",
                    "experiment_time_start",
                    "experiment_time_end",
                    "domain_name",
                    "experiment_id",
                    "domain_def",
                    "hydrological_model",
                }:
                    required_config_fields.add(req)

    missing = []
    for field in sorted(required_config_fields):
        if not s(cfg.get(field)):
            missing.append(field)

    if plan_uses_local_data(cfg, resolved_steps, data_dir=SYMFLUENCE_DATA_DIR):
        missing = [f for f in missing if f != "bounding_box_coords"]

    new_plan["needs_user_input"] = missing

    notes = str(new_plan.get("notes", "")).strip()
    if not missing and "Missing required inputs:" in notes:
        notes = re.sub(
            r"Missing required inputs:.*?(?=\s*\||$)",
            "",
            notes,
            flags=re.IGNORECASE,
        ).strip(" |")
    new_plan["notes"] = (
        notes + " | Dependencies resolved from SYMFLUENCE operation catalog."
    ).strip(" |")

    new_plan = strip_user_forbidden_download_steps(new_plan, user_request)
    new_plan = normalize_local_workflow_plan(
        new_plan,
        user_request,
        data_dir=SYMFLUENCE_DATA_DIR,
    )
    return new_plan

def run_py_tool(script_path: str, args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    cmd = [sys.executable, script_path] + args
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    return p.returncode, p.stdout, p.stderr

def apply_edited_plan_to_session(plan: dict) -> None:
    """Push plan.config values into Input-tab session state, advanced settings, and widgets."""
    sync_plan_config_to_session(plan)
    sync_run_folder_from_session()
    sync_mpi_to_run_plan()

def load_persistent_config() -> dict:
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("r") as f:
            return yaml.safe_load(f) or {}
    return {}

def parse_pour_point(value: str) -> tuple[float, float] | None:
    value = s(value)
    if not value or "/" not in value:
        return None

    try:
        lat_str, lon_str = value.split("/", 1)
        return float(lat_str.strip()), float(lon_str.strip())
    except Exception:
        return None

def sync_manual_pour_point_to_map() -> None:
    """Sync pour-point text input to map marker state (manual entry only)."""
    value = s(st.session_state.pour_point_input)
    parsed = parse_pour_point(value)

    if parsed is None:
        if not value:
            # Map click may have set selected_pour_point before the text widget updates.
            if st.session_state.get("map_point_selected") and s(st.session_state.get("selected_pour_point")):
                return
            st.session_state.map_lat = None
            st.session_state.map_lon = None
            st.session_state.map_point_selected = False
            st.session_state.selected_pour_point = ""
        return

    lat, lon = parsed
    st.session_state.selected_pour_point = format_pour_point(lat, lon)
    st.session_state.map_lat = lat
    st.session_state.map_lon = lon
    st.session_state.map_point_selected = True

def save_persistent_config(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w") as f:
        yaml.safe_dump(data, f)


SUPPORTED_STEPS = {
    "setup_project",
    "create_pour_point",
    "acquire_attributes",
    "define_domain",
    "discretize_domain",
    "process_observed_data",
    "acquire_forcings",
    "model_agnostic_preprocessing",
    "model_specific_preprocessing",
    "run_model",
    "calibrate_model",
    "postprocess_results",
    "dry_run",
}

STEP_TO_CLI = {
    "setup_project": ["workflow", "step", "setup_project"],
    "create_pour_point": ["workflow", "step", "create_pour_point"],
    "acquire_attributes": ["workflow", "step", "acquire_attributes"],
    "define_domain": ["workflow", "step", "define_domain"],
    "discretize_domain": ["workflow", "step", "discretize_domain"],
    "process_observed_data": ["workflow", "step", "process_observed_data"],
    "acquire_forcings": ["workflow", "step", "acquire_forcings"],
    "model_agnostic_preprocessing": ["workflow", "step", "model_agnostic_preprocessing"],
    "model_specific_preprocessing": ["workflow", "step", "model_specific_preprocessing"],
    "run_model": ["workflow", "step", "run_model"],
    "calibrate_model": ["workflow", "step", "calibrate_model"],
    "postprocess_results": ["workflow", "step", "postprocess_results"],
}


def build_symfluence_step_cmd(step: str, config_path: Path) -> list[str]:
    if step == "dry_run":
        return [
            str(SYMFLUENCE_PYTHON),
            "-m",
            "symfluence",
            "--dry-run",
            "workflow",
            "step",
            "setup_project",
            "--config",
            str(config_path),
        ]

    cli_parts = STEP_TO_CLI.get(step)
    if not cli_parts:
        raise ValueError(f"Unsupported step for CLI mapping: {step}")

    return [
        str(SYMFLUENCE_PYTHON),
        "-m",
        "symfluence",
        *cli_parts,
        "--config",
        str(config_path),
    ]


DANGER_STEPS = {"run_model", "calibrate_model"}

GPT_MODELS = {
    "GPT-5 (Recommended)": ["gpt-5-mini", "gpt-5.2", "gpt-5.2-pro"],
    "GPT-4.x (Legacy / Compatibility)": ["gpt-4.1", "gpt-4o", "gpt-4o-mini"],
}
ALL_GPT_MODELS = [m for group in GPT_MODELS.values() for m in group]

GEMINI_MODELS = {
    "Gemini 2.5 (Recommended)": ["gemini-2.5-flash", "gemini-2.5-pro"],
    "Gemini 2.0": ["gemini-2.0-flash", "gemini-2.0-flash-lite"],
    "Gemini 1.5 (Legacy)": ["gemini-1.5-pro", "gemini-1.5-flash"],
}
ALL_GEMINI_MODELS = [m for group in GEMINI_MODELS.values() for m in group]

CLAUDE_MODELS = {
    "Claude 4.x (Recommended)": [
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
    ],
    "Claude 3.7": ["claude-3-7-sonnet-latest"],
    "Claude 3.5 (Legacy)": [
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
    ],
}
ALL_CLAUDE_MODELS = [m for group in CLAUDE_MODELS.values() for m in group]

CLAUDE_MODEL_LABELS = {
    "claude-sonnet-4-20250514": "Sonnet 4",
    "claude-opus-4-20250514": "Opus 4",
    "claude-3-7-sonnet-latest": "Sonnet 3.7",
    "claude-3-5-sonnet-latest": "Sonnet 3.5",
    "claude-3-5-haiku-latest": "Haiku 3.5",
}


def llm_model_label(model_id: str, provider: str) -> str:
    if provider == "claude":
        return CLAUDE_MODEL_LABELS.get(model_id, model_id)
    return model_id


VOICE_PROVIDER_LABELS = {
    "openai": "OpenAI Whisper",
    "gemini": "Gemini audio",
}


LLM_PROVIDER_LABELS = {
    "openai": "OpenAI (GPT)",
    "gemini": "Google (Gemini)",
    "claude": "Anthropic (Claude)",
}
LLM_PROVIDER_BY_LABEL = {label: key for key, label in LLM_PROVIDER_LABELS.items()}
LLM_PROVIDER_PACKAGES = {
    "gemini": "google-genai",
    "claude": "anthropic",
}
DEFAULT_LLM_MODEL = {
    "openai": "gpt-5-mini",
    "gemini": "gemini-2.5-flash",
    "claude": "claude-sonnet-4-20250514",
}


def llm_models_for_provider(provider: str) -> list[str]:
    if provider == "gemini":
        return ALL_GEMINI_MODELS
    if provider == "claude":
        return ALL_CLAUDE_MODELS
    return ALL_GPT_MODELS


def llm_provider_available(provider: str) -> bool:
    if provider == "gemini":
        return ensure_gemini_provider()
    if provider == "claude":
        return ensure_claude_provider()
    return OPENAI_AVAILABLE


def llm_provider_import_error(provider: str) -> str:
    if provider == "gemini":
        return GEMINI_IMPORT_ERROR
    if provider == "claude":
        return CLAUDE_IMPORT_ERROR
    return ""


def llm_provider_install_hint(provider: str) -> str:
    package = LLM_PROVIDER_PACKAGES.get(provider)
    if not package:
        return ""
    return (
        f"Python: `{sys.executable}`\n\n"
        f"Install with:\n"
        f"```\n{sys.executable} -m pip install {package}\n```\n"
        f"Then restart Streamlit."
    )


if "api_keys" not in st.session_state:
    st.session_state.api_keys = {}

persistent_cfg = load_persistent_config()
for _provider in ("openai", "gemini", "claude"):
    _saved_key = (persistent_cfg or {}).get(f"{_provider}_api_key")
    if _saved_key and not st.session_state.api_keys.get(_provider):
        st.session_state.api_keys[_provider] = _saved_key

st.session_state.setdefault("run_plan", None)
st.session_state.setdefault("execute_plan", False)
st.session_state.setdefault("execution_log_text", "")
st.session_state.setdefault("chat_messages", [])

defaults = {
    "domain_name": "",
    "experiment_id": "",
    "domain_def": "",
    "hydrological_model": "",
    "forcing_dataset": "ERA5",
    "tstart": "",
    "tend": "",
    "pour_point_input": "",
    "bounding_box_input": "",
    "selected_pour_point": "",
    "selected_bounding_box": "",
    "map_mode": "pour_point",
    "last_map_click": None,
    "map_lat": None,
    "map_lon": None,
    "map_point_selected": False,
    "bbox_point_1": None,
    "bbox_point_2": None,
    "bbox_selected": False,
    "show_dem_layer": False,
    "show_landclass_layer": False,
    "show_soilclass_layer": False,
    "show_catchment_layer": True,
    "show_riverbasins_layer": False,
    "show_rivernetwork_layer": False,
    "show_hrugru_layer": False,
    "show_forcing_layer": False,
    "refresh_spatial_inputs": False,
    "run_folder": "",
    "run_workspace_locked": False,
    "mpi": 1,
    "allow_run": False,
    "want_create_pour_point": True,
    "llm_provider": "openai",
    "llm_model": "gpt-5-mini",
    "gpt_model": "gpt-5-mini",
    "nl_request": "",
    "user_prompt": "",
    "chat_messages": [],
    "workflow_chat_compose_version": 0,
    "plan_editor_version": 0,
    "assistant_panel_tabs": "Prompt",
    "input_panel_widget_version": 0,
    "mpi_widget_version": 0,
    "experiment_datetime_widget_version": 0,
    "config_preview_version": 0,
    "spatial_inputs_stale": False,
    "streamflow_data_provider": "WSC",
    "station_id": "",
    "routing_model": "mizuRoute",
    "pet_method": "oudin",
    "spinup_period": "",
    "calibration_period": "",
    "evaluation_period": "",
    "run_results_scan_at": "",
    "iterative_optimization_algorithm": "DE",
    "optimization_metric": "KGE",
    "optimization_target": "streamflow",
    "calibration_timestep": "daily",
    "iterations": 50,
    "population_size": 10,
}

for k, v in defaults.items():
    st.session_state.setdefault(k, v)


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


WORKFLOW_DISPLAY_ORDER = [
    ("setup_project", "setup"),
    ("create_pour_point", "pour point"),
    ("acquire_attributes", "attributes"),
    ("define_domain", "domain"),
    ("discretize_domain", "HRUs"),
    ("process_observed_data", "observed"),
    ("acquire_forcings", "forcings"),
    ("model_agnostic_preprocessing", "MAP"),
    ("model_specific_preprocessing", "MSP"),
    ("run_model", "model"),
    ("postprocess_results", "postprocess"),
]


def get_workflow_status_map(plan: dict | None, log_text: str) -> dict[str, str]:
    steps = (plan or {}).get("steps", []) or []
    log_text = log_text or ""
    status_map: dict[str, str] = {}

    for step, _label in WORKFLOW_DISPLAY_ORDER:
        if step not in steps:
            status_map[step] = "not_requested"
            continue

        if f"[STEP {step}] return code: 0" in log_text:
            status_map[step] = "done"
        elif f"[STEP {step}] return code:" in log_text and f"[STEP {step}] return code: 0" not in log_text:
            status_map[step] = "failed"
        elif f"===== STEP: {step} =====" in log_text:
            status_map[step] = "pending"
        else:
            status_map[step] = "pending"

    return status_map


def render_workflow_progress(plan: dict | None, log_text: str) -> str:
    status_map = get_workflow_status_map(plan, log_text)
    requested_steps = (plan or {}).get("steps", []) or []
    pieces = []

    for step, label in WORKFLOW_DISPLAY_ORDER:
        if step not in requested_steps:
            continue
        status = status_map[step]
        icon = "✅" if status == "done" else "❌" if status == "failed" else "⏳" if status == "pending" else "⚪"
        pieces.append(f"{icon} {label}")

    return " → ".join(pieces)


def clean_cfg_for_safe_run(cfg: dict) -> dict:
    for k in [
        "EVALUATION_DATA", "ANALYSES", "SIM_REACH_ID", "STREAMFLOW_DATA_PROVIDER", 
        "DOWNLOAD_USGS_DATA", "DOWNLOAD_WSC_DATA", "STATION_ID", "DOWNLOAD_FLUXNET",
        "FLUXNET_STATION", "FLUXNET_PATH", "DOWNLOAD_USGS_GW", "USGS_STATION", "DOWNLOAD_SMAP",
        "SMAP_PRODUCT", "SMAP_PATH", "DOWNLOAD_GRACE", "GRACE_PRODUCT", "GRACE_PATH",
        "DOWNLOAD_MODIS_SNOW", "MODIS_SNOW_PRODUCT", "MODIS_SNOW_PATH", "ATTRIBUTES_DATA_DIR",
        "ATTRIBUTES_SOILGRIDS_PATH", "ATTRIBUTES_PELLETIER_PATH", "ATTRIBUTES_MERIT_PATH",
        "ATTRIBUTES_MODIS_PATH", "ATTRIBUTES_GLCLU_PATH", "ATTRIBUTES_FOREST_HEIGHT_PATH",
        "ATTRIBUTES_WORLDCLIM_PATH", "ATTRIBUTES_GLIM_PATH", "ATTRIBUTES_GROUNDWATER_PATH",
        "ATTRIBUTES_STREAMFLOW_PATH", "HRU_GAUGE_MAPPING", "ATTRIBUTES_GLWD_PATH",
        "ATTRIBUTES_HYDROLAKES_PATH", "ATTRIBUTES_OUTPUT_DIR",
    ]:
        cfg.pop(k, None)

    for k in [
        "DE_SCALING_FACTOR", "DE_CROSSOVER_RATE", "DDS_R",
        "ASYNC_DDS_POOL_SIZE", "ASYNC_DDS_BATCH_SIZE", "MAX_STAGNATION_BATCHES",
        "NUMBER_OF_COMPLEXES", "POINTS_PER_SUBCOMPLEX", "NUMBER_OF_EVOLUTION_STEPS",
        "EVOLUTION_STAGNATION", "PERCENT_CHANGE_THRESHOLD", "SWRMSIZE", "PSO_COGNITIVE_PARAM",
        "PSO_SOCIAL_PARAM", "PSO_INERTIA_WEIGHT", "PSO_INERTIA_REDUCTION_RATE", "INERTIA_SCHEDULE",
        "NSGA2_CROSSOVER_RATE", "NSGA2_MUTATION_RATE", "NSGA2_ETA_C", "NSGA2_ETA_M",
        "DPE_TRAINING_CACHE", "DPE_HIDDEN_DIMS", "DPE_TRAINING_SAMPLES", "DPE_VALIDATION_SAMPLES",
        "DPE_EPOCHS", "DPE_LEARNING_RATE", "DPE_OPTIMIZATION_LR", "DPE_OPTIMIZATION_STEPS",
        "DPE_OPTIMIZER", "DPE_OBJECTIVE_WEIGHTS", "DPE_EMULATOR_ITERATE",
        "DPE_ITERATE_MAX_ITERATIONS", "DPE_ITERATE_SAMPLES_PER_CYCLE", "DPE_ITERATE_SAMPLING_RADIUS",
        "DPE_ITERATE_CONVERGENCE_TOL", "DPE_ITERATE_MIN_IMPROVEMENT", "DPE_ITERATE_SAMPLING_METHOD",
        "DPE_USE_NN_HEAD", "DPE_PRETRAIN_NN_HEAD", "DPE_USE_SUNDIALS", "DPE_AUTODIFF_STEPS",
        "DPE_AUTODIFF_LR", "DPE_FD_STEP", "DPE_GD_STEP_SIZE", "LARGE_DOMAIN_EMULATION_ENABLED",
        "EMULATOR_SETTING", "LARGE_DOMAIN_EMULATOR_MODE", "LARGE_DOMAIN_EMULATOR_OPTIMIZER",
        "LARGE_DOMAIN_TRAINING_EPOCHS", "LARGE_DOMAIN_PARAMETER_ENSEMBLE_SIZE", "LARGE_DOMAIN_BATCH_SIZE",
        "LARGE_DOMAIN_VALIDATION_SPLIT", "LARGE_DOMAIN_EMULATOR_PRETRAIN_NN_HEAD",
        "LARGE_DOMAIN_EMULATOR_USE_NN_HEAD", "LARGE_DOMAIN_EMULATOR_TRAINING_SAMPLES",
        "LARGE_DOMAIN_EMULATOR_EPOCHS", "LARGE_DOMAIN_EMULATOR_AUTODIFF_STEPS",
        "LARGE_DOMAIN_EMULATOR_STREAMFLOW_WEIGHT", "LARGE_DOMAIN_EMULATOR_SMAP_WEIGHT",
        "LARGE_DOMAIN_EMULATOR_GRACE_WEIGHT", "LARGE_DOMAIN_EMULATOR_MODIS_WEIGHT",
        "EMULATION_NUM_SAMPLES", "EMULATION_SEED", "EMULATION_SAMPLING_METHOD",
        "EMULATION_PARALLEL_ENSEMBLE", "EMULATION_MAX_PARALLEL_JOBS", "EMULATION_SKIP_MIZUROUTE",
        "EMULATION_USE_ATTRIBUTES", "EMULATION_MAX_ITERATIONS",
    ]:
        cfg.pop(k, None)
    
    # Remove stale template period defaults.
    # These must come from the plan/spec. If they remain from the template,
    # they can conflict with the experiment time window.
    for k in [
        "SPINUP_PERIOD",
        "CALIBRATION_PERIOD",
        "EVALUATION_PERIOD",
    ]:
        cfg.pop(k, None)

    # Remove stale template optimization defaults.
    # Valid values will be restored by reapply_spec_overrides() if provided.
    for k in [
        "OPTIMIZATION_TARGET",
        "OPTIMIZATION_METRIC",
        "CALIBRATION_TIMESTEP",
        "ITERATIVE_OPTIMIZATION_ALGORITHM",
        "NUMBER_OF_ITERATIONS",
        "POPULATION_SIZE",
    ]:
        cfg.pop(k, None)

    cfg.pop("evaluation", None)
    return cfg

def is_elevation_distributed_workflow(spec: dict, cfg: dict | None = None) -> bool:
    """True for 02c-style elevation-band workflows (e.g. Bow_at_Banff_elevation)."""
    spec = spec or {}
    cfg = cfg or {}
    domain = s(spec.get("domain_name") or cfg.get("DOMAIN_NAME")).lower()
    if "_elevation" in domain or "elevation_distributed" in domain:
        return True
    discretization = s(spec.get("discretization") or cfg.get("DOMAIN_DISCRETIZATION")).lower()
    if discretization == "elevation":
        return True
    return False


def is_semi_distributed_workflow(spec: dict, cfg: dict | None = None) -> bool:
    """True for 02b-style semi-distributed Bow / delineate + GRUs workflows."""
    if is_elevation_distributed_workflow(spec, cfg):
        return False
    spec = spec or {}
    cfg = cfg or {}
    domain = s(spec.get("domain_name") or cfg.get("DOMAIN_NAME")).lower()
    if "semi_distributed" in domain or "semi-distributed" in domain:
        return True
    domain_def = s(spec.get("domain_def") or cfg.get("DOMAIN_DEFINITION_METHOD")).lower()
    discretization = s(spec.get("discretization") or cfg.get("DOMAIN_DISCRETIZATION")).upper()
    steps = spec.get("steps") or []
    if isinstance(steps, list) and {"define_domain", "discretize_domain"} <= set(steps):
        if domain_def in ("delineate", "semidistributed", "semi_distributed"):
            return True
        if discretization == "GRUS":
            return True
    return False


def apply_semi_distributed_config_defaults(cfg: dict, spec: dict) -> dict:
    """Align delineation/discretization with 02b_basin_semi_distributed.ipynb when template defaults differ."""
    if not is_semi_distributed_workflow(spec, cfg):
        return cfg
    defaults = {
        "DELINEATION_METHOD": "stream_threshold",
        "STREAM_THRESHOLD": 5000.0,
        "MIN_HRU_SIZE": 0.0,
        "MIN_GRU_SIZE": 0.0,
        "RADIATION_CLASS_NUMBER": 1,
        "ASPECT_CLASS_NUMBER": 1,
        "USE_DROP_ANALYSIS": False,
        "DOMAIN_DISCRETIZATION": "GRUs",
        "SUB_GRID_DISCRETIZATION": "GRUs",
        "SETTINGS_MIZU_ROUTING_VAR": "averageRoutedRunoff",
        "SETTINGS_MIZU_ROUTING_UNITS": "m/s",
        "SETTINGS_MIZU_ROUTING_DT": 3600,
        "MIZU_FROM_MODEL": "SUMMA",
    }
    extra = spec.get("extra_config") if isinstance(spec.get("extra_config"), dict) else {}
    for key, value in defaults.items():
        if extra.get(key) is not None:
            continue
        if spec.get(key) is not None:
            continue
        cfg[key] = value
    return cfg


def apply_elevation_distributed_config_defaults(cfg: dict, spec: dict) -> dict:
    """Align discretization with 02c_basin_elevation_distributed.ipynb when template/plan differ."""
    if not is_elevation_distributed_workflow(spec, cfg):
        return cfg
    domain_name = s(spec.get("domain_name") or cfg.get("DOMAIN_NAME"))
    defaults = {
        "DELINEATION_METHOD": "stream_threshold",
        "STREAM_THRESHOLD": 5000.0,
        "MIN_HRU_SIZE": 0.0,
        "MIN_GRU_SIZE": 0.0,
        "RADIATION_CLASS_NUMBER": 1,
        "ASPECT_CLASS_NUMBER": 1,
        "USE_DROP_ANALYSIS": False,
        "DOMAIN_DISCRETIZATION": "elevation",
        "ELEVATION_BAND_SIZE": 400.0,
    }
    if domain_name:
        defaults["CATCHMENT_SHP_NAME"] = f"{domain_name}_HRUs_elevation.shp"
    extra = spec.get("extra_config") if isinstance(spec.get("extra_config"), dict) else {}
    for key, value in defaults.items():
        if extra.get(key) is not None:
            continue
        if spec.get(key) is not None:
            continue
        cfg[key] = value
    return cfg


def reapply_spec_overrides(cfg: dict, spec: dict) -> dict:
    """
    Re-apply planner/spec values after template cleanup.
    This prevents old template defaults from surviving in final config.yaml.
    """
    mapping = {
        "domain_name": "DOMAIN_NAME",
        "experiment_id": "EXPERIMENT_ID",
        "pour_point_coords": "POUR_POINT_COORDS",
        "bounding_box_coords": "BOUNDING_BOX_COORDS",
        "domain_def": "DOMAIN_DEFINITION_METHOD",
        "hydrological_model": "HYDROLOGICAL_MODEL",
        "experiment_time_start": "EXPERIMENT_TIME_START",
        "experiment_time_end": "EXPERIMENT_TIME_END",
        "spinup_period": "SPINUP_PERIOD",
        "calibration_period": "CALIBRATION_PERIOD",
        "evaluation_period": "EVALUATION_PERIOD",
        "forcing_dataset": "FORCING_DATASET",
        "streamflow_data_provider": "STREAMFLOW_DATA_PROVIDER",
        "station_id": "STATION_ID",
        "routing_model": "ROUTING_MODEL",
        "pet_method": "PET_METHOD",
        "spinup_period": "SPINUP_PERIOD",
        "calibration_period": "CALIBRATION_PERIOD",
        "evaluation_period": "EVALUATION_PERIOD",
        "discretization": "DOMAIN_DISCRETIZATION",
        "optimization_target": "OPTIMIZATION_TARGET",
        "optimization_metric": "OPTIMIZATION_METRIC",
        "calibration_timestep": "CALIBRATION_TIMESTEP",
        "iterative_optimization_algorithm": "ITERATIVE_OPTIMIZATION_ALGORITHM",
        "iterations": "NUMBER_OF_ITERATIONS",
        "population_size": "POPULATION_SIZE",
        "download_snotel": "DOWNLOAD_SNOTEL",
        "snotel_station": "SNOTEL_STATION",
        "num_processes": "NUM_PROCESSES",
        "mpi_processes": "MPI_PROCESSES",
        "data_access": "DATA_ACCESS",
    }

    for spec_key, yaml_key in mapping.items():
        if spec.get(spec_key) is not None:
            cfg[yaml_key] = spec[spec_key]

    # Preserve uppercase native SYMFLUENCE keys from the plan/spec
    for key, value in spec.items():
        if value is not None and isinstance(key, str) and key.isupper():
            cfg[key] = value

    # Reapply advanced explicit SYMFLUENCE parameters after cleanup.
    # These come from plan.config.extra_config and must override template defaults.
    extra_config = spec.get("extra_config") or {}
    if isinstance(extra_config, dict):
        for key, value in extra_config.items():
            if value is None:
                continue
            yaml_key = spec_key_to_yaml_key(key)
            if yaml_key:
                cfg[yaml_key] = value

    cfg = apply_semi_distributed_config_defaults(cfg, spec)
    cfg = apply_elevation_distributed_config_defaults(cfg, spec)
    return finalize_symfluence_config(cfg, spec)

def preserve_explicit_config_fields_from_prompt(plan: dict, prompt_text: str) -> dict:
    """
    Safety net: preserve explicit key-value settings from the user's prompt.
    This prevents the LLM planner from replacing explicit prompt values with old/default values.
    """
    import re

    plan.setdefault("config", {})
    cfg = plan["config"]
    text = prompt_text or ""

    patterns_str = {
        "domain_name": r"\bdomain_name\s+([A-Za-z0-9_\- ]+?)(?:\.|\n|$)",
        "experiment_id": r"\bexperiment_id\s+([A-Za-z0-9_\-]+)",
        "forcing_dataset": r"\bforcing_dataset\s+([A-Za-z0-9_\-]+)",
        "domain_def": r"\bdomain_def\s+([A-Za-z0-9_\-]+)",
        "discretization": r"\bdiscretization\s+([A-Za-z0-9_\-]+)",
        "data_access": r"\bdata_access\s+([A-Za-z0-9_]+)",
        "DATA_ACCESS": r"\bDATA_ACCESS\s+([A-Za-z0-9_]+)",
        "SNOTEL_STATION": r"\bSNOTEL_STATION\s+(?:to\s+)?([0-9]+)",
        "optimization_target": r"\boptimization_target\s+([A-Za-z0-9_\-]+)",
        "optimization_metric": r"\boptimization_metric\s+([A-Za-z0-9_\-]+)",
        "calibration_timestep": r"\bcalibration_timestep\s+([A-Za-z0-9_\-]+)",
        "iterative_optimization_algorithm": r"\biterative_optimization_algorithm\s+([A-Za-z0-9_\-]+)",
        "DELINEATION_METHOD": r"\bDELINEATION_METHOD\s+([A-Za-z0-9_]+)",
        "delineation_method": r"\bdelineation_method\s+([A-Za-z0-9_]+)",
    }

    patterns_coords_time = {
        "pour_point_coords": r"\bpour_point_coords\s+(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?)",
        "bounding_box_coords": r"\bbounding_box_coords\s+(-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?)",
        "experiment_time_start": r"\bexperiment_time_start\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})",
        "experiment_time_end": r"\bexperiment_time_end\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})",
    }

    patterns_period = {
        "spinup_period": r"\bspinup_period\s+(\d{4}-\d{2}-\d{2}\s*,\s*\d{4}-\d{2}-\d{2})",
        "calibration_period": r"\bcalibration_period\s+(\d{4}-\d{2}-\d{2}\s*,\s*\d{4}-\d{2}-\d{2})",
        "evaluation_period": r"\bevaluation_period\s+(\d{4}-\d{2}-\d{2}\s*,\s*\d{4}-\d{2}-\d{2})",
    }

    patterns_int = {
        "iterations": r"\biterations\s+([0-9]+)",
        "POPULATION_SIZE": r"\bPOPULATION_SIZE\s+([0-9]+)",
        "NUM_PROCESSES": r"\bNUM_PROCESSES\s+([0-9]+)",
        "MPI_PROCESSES": r"\bMPI_PROCESSES\s+([0-9]+)",
        "STREAM_THRESHOLD": r"\bSTREAM_THRESHOLD\s+([0-9]+(?:\.[0-9]+)?)",
        "stream_threshold": r"\bstream_threshold\s+([0-9]+(?:\.[0-9]+)?)",
        "ELEVATION_BAND_SIZE": r"\bELEVATION_BAND_SIZE\s+([0-9]+(?:\.[0-9]+)?)",
        "elevation_band_size": r"\belevation_band_size\s+([0-9]+(?:\.[0-9]+)?)",
    }

    patterns_bool = {
        "DOWNLOAD_SNOTEL": r"\bDOWNLOAD_SNOTEL\s+(?:to\s+)?(true|false)",
    }

    for key, pat in {**patterns_str, **patterns_coords_time, **patterns_period}.items():
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            cfg[key] = m.group(1).strip()

    for key, pat in patterns_int.items():
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            cfg[key] = int(m.group(1))

    for key, pat in patterns_bool.items():
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            cfg[key] = m.group(1).lower() == "true"

    return plan

def is_new_map_click(lat: float, lon: float) -> bool:
    current = (round(lat, 7), round(lon, 7))
    previous = st.session_state.last_map_click
    if previous == current:
        return False
    st.session_state.last_map_click = current
    return True


def format_pour_point(lat: float, lon: float) -> str:
    return f"{lat:.7f}/{lon:.7f}"


def format_bounding_box(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    north = max(lat1, lat2)
    south = min(lat1, lat2)
    east = max(lon1, lon2)
    west = min(lon1, lon2)
    return f"{north:.7f}/{west:.7f}/{south:.7f}/{east:.7f}"


def sync_manual_inputs_to_selected() -> None:
    """Copy non-empty manual text fields into selected_* without erasing map picks."""
    pour_from_input = s(st.session_state.pour_point_input)
    if pour_from_input:
        st.session_state.selected_pour_point = pour_from_input
    bbox_from_input = s(st.session_state.bounding_box_input)
    if bbox_from_input:
        st.session_state.selected_bounding_box = bbox_from_input


def on_pour_point_input_change() -> None:
    sync_manual_pour_point_to_map()
    sync_all_ui_fields_to_plan(refresh_editor=True, force_editor=True)
    bump_config_preview_version()


def on_bounding_box_input_change() -> None:
    sync_all_ui_fields_to_plan(refresh_editor=True, force_editor=True)
    bump_config_preview_version()


def resolve_data_access_from_plan(plan_cfg: dict | None) -> str:
    """Read data_access / DATA_ACCESS from plan config or extra_config."""
    plan_cfg = plan_cfg or {}
    extra = plan_cfg.get("extra_config") if isinstance(plan_cfg.get("extra_config"), dict) else {}
    for key in ("data_access", "DATA_ACCESS"):
        val = s(plan_cfg.get(key)) or s(extra.get(key))
        if val:
            return val.lower()
    return ""


def hoist_plan_extra_config_to_spec(spec: dict) -> dict:
    """Promote extra_config keys onto spec so template rendering picks them up."""
    extra = spec.get("extra_config")
    if not isinstance(extra, dict):
        return spec
    for key, value in extra.items():
        if value is None:
            continue
        if key in FIELD_MAP:
            spec[key] = value
        elif isinstance(key, str) and key.isupper():
            spec[key] = value
    return spec


def build_spec_dict(plan_cfg: dict | None = None) -> dict:
    plan_cfg = plan_cfg or {}
    run_steps = (st.session_state.get("run_plan") or {}).get("steps") or []
    domain_name = s(plan_cfg.get("domain_name")) or s(st.session_state.domain_name)
    data_access = resolve_data_access_from_plan(plan_cfg) or "cloud"
    if {"acquire_attributes", "acquire_forcings"} & set(run_steps):
        data_access = "cloud"
    elif domain_name and not domain_has_local_dem(SYMFLUENCE_DATA_DIR, domain_name):
        if {"define_domain", "discretize_domain", "acquire_attributes"} & set(run_steps):
            data_access = "cloud"

    spec = {
        "symfluence_code_dir": normalize_path_text(SYMFLUENCE_REPO),
        "symfluence_data_dir": normalize_path_text(SYMFLUENCE_DATA_DIR) + "/",
        "data_access": data_access,
        "gistool_dataset_root": normalize_path_text(SYMFLUENCE_DATA_DIR / "geospatial-data") + "/",
        "tool_cache": normalize_path_text(SYMFLUENCE_DATA_DIR / "cache" / "gistool"),
        "easymore_cache": normalize_path_text(SYMFLUENCE_DATA_DIR / "cache" / "easymore"),
        "cluster_json": normalize_path_text(SYMFLUENCE_DATA_DIR / "cluster.local.json"),

        # Always trust plan first
        "domain_name": s(lookup_plan_config(plan_cfg, "domain_name", "DOMAIN_NAME")) or s(st.session_state.domain_name),
        "experiment_id": s(lookup_plan_config(plan_cfg, "experiment_id", "EXPERIMENT_ID")) or s(st.session_state.experiment_id),

        "pour_point_coords": s(lookup_plan_config(plan_cfg, "pour_point_coords", "POUR_POINT_COORDS"))
        or s(st.session_state.selected_pour_point),
        "bounding_box_coords": (
            s(lookup_plan_config(plan_cfg, "bounding_box_coords", "BOUNDING_BOX_COORDS"))
            or s(st.session_state.selected_bounding_box)
            or None
        ),

        "experiment_time_start": s(lookup_plan_config(plan_cfg, "experiment_time_start", "EXPERIMENT_TIME_START"))
        or s(st.session_state.tstart),
        "experiment_time_end": s(lookup_plan_config(plan_cfg, "experiment_time_end", "EXPERIMENT_TIME_END"))
        or s(st.session_state.tend),

        "domain_def": s(lookup_plan_config(plan_cfg, "domain_def", "DOMAIN_DEFINITION_METHOD"))
        or s(st.session_state.domain_def),
        "hydrological_model": current_hydrological_model(plan_cfg),
        "forcing_dataset": s(lookup_plan_config(plan_cfg, "forcing_dataset", "FORCING_DATASET"))
        or s(st.session_state.forcing_dataset) or None,
        "station_id": (
            s(lookup_plan_config(plan_cfg, "station_id", "STATION_ID"))
            or s(st.session_state.station_id)
            or extract_station_id_from_request(s(st.session_state.get("nl_request", "")))
            or None
        ),

        # Prefer plan/chat NUM_PROCESSES, then Input tab mpi widget
        "num_processes": resolve_num_processes_from_plan_cfg(plan_cfg) or int(st.session_state.mpi),
        "mpi_processes": resolve_num_processes_from_plan_cfg(plan_cfg) or int(st.session_state.mpi),

        "log_level": "INFO",
        "log_to_file": True,
        "log_format": "detailed",
        "force_rerun": True,
    }

    # Preserve extra planner-provided config keys.
    # Important for notebook-specific options such as:
    # forcing_dataset, spinup_period, DOWNLOAD_SNOTEL, SNOTEL_STATION, POPULATION_SIZE, etc.
    for k, v in plan_cfg.items():
        if v is not None and k not in spec:
            spec[k] = v

    spec = wx.merge_advanced_into_spec(spec, plan_cfg)

    sym_domain = s(spec.get("domain_name"))
    if plan_uses_local_data(plan_cfg, run_steps, conversation_text_for_plan_rules(), data_dir=SYMFLUENCE_DATA_DIR):
        spec["DOWNLOAD_WSC_DATA"] = False
    elif sym_domain and domain_has_local_streamflow(SYMFLUENCE_DATA_DIR, sym_domain):
        spec["DOWNLOAD_WSC_DATA"] = False

    return hoist_plan_extra_config_to_spec(spec)

def plan_editor_text_from_run_plan() -> str:
    if st.session_state.get("run_plan") is None:
        return ""
    return json.dumps(st.session_state.run_plan, indent=2)


def plan_editor_widget_key() -> str:
    version = int(st.session_state.get("plan_editor_version", 0))
    return f"editable_plan_box_v{version}"


def workflow_chat_compose_key() -> str:
    version = int(st.session_state.get("workflow_chat_compose_version", 0))
    return f"workflow_chat_compose_v{version}"


def bump_workflow_chat_compose_version() -> None:
    st.session_state.workflow_chat_compose_version = int(
        st.session_state.get("workflow_chat_compose_version", 0)
    ) + 1


def sync_spatial_fields_to_run_plan(*, refresh_editor: bool = False) -> None:
    """Push map picks and spatial text inputs into run_plan.config."""
    if st.session_state.get("run_plan") is None:
        return
    pour = s(st.session_state.selected_pour_point) or s(st.session_state.pour_point_input)
    bbox = s(st.session_state.selected_bounding_box) or s(st.session_state.bounding_box_input)
    plan = st.session_state.run_plan
    plan.setdefault("config", {})
    cfg = plan["config"]
    if pour:
        cfg["pour_point_coords"] = pour
    else:
        cfg.pop("pour_point_coords", None)
    if bbox:
        cfg["bounding_box_coords"] = bbox
    else:
        cfg.pop("bounding_box_coords", None)
    update_run_plan_needs_user_input()
    if refresh_editor:
        refresh_plan_editor_from_state(force=True)
    else:
        st.session_state["_plan_editor_stash"] = plan_editor_text_from_run_plan()


def capture_plan_editor_draft() -> None:
    """Persist in-flight plan JSON before the assistant panel rerenders another tab."""
    if st.session_state.get("run_plan") is None:
        return
    widget_key = plan_editor_widget_key()
    editor_text = s(st.session_state.get(widget_key))
    synced_text = s(st.session_state.get("_plan_editor_synced"))
    if editor_text and editor_text.strip() != synced_text:
        try:
            parsed = json.loads(editor_text)
            if isinstance(parsed, dict) and {"config", "steps"}.issubset(parsed.keys()):
                st.session_state.run_plan = parsed
                update_run_plan_needs_user_input()
        except Exception:
            pass
    sync_spatial_fields_to_run_plan(refresh_editor=False)
    st.session_state["_plan_editor_stash"] = plan_editor_text_from_run_plan()
    st.session_state["_plan_editor_synced"] = s(st.session_state["_plan_editor_stash"])


def refresh_plan_editor_from_state(force: bool = False, *, remount: bool = False) -> None:
    """Sync the JSON editor from run_plan. Skips when the user has unsaved edits."""
    if st.session_state.get("run_plan") is None:
        return
    source = plan_editor_text_from_run_plan()
    widget_key = plan_editor_widget_key()
    editor_text = s(st.session_state.get(widget_key))
    if not force and editor_text and editor_text != source:
        try:
            edited = json.loads(editor_text)
            if isinstance(edited, dict) and edited != st.session_state.run_plan:
                return
        except Exception:
            return
    if remount:
        st.session_state.plan_editor_version = int(st.session_state.get("plan_editor_version", 0)) + 1
        widget_key = plan_editor_widget_key()
    st.session_state["_plan_editor_stash"] = source
    st.session_state["_pending_plan_editor_text"] = source
    st.session_state["_plan_editor_synced"] = source.strip()
    st.session_state[widget_key] = source


def render_persistent_plan_editor(*, visible: bool) -> str:
    """Mount the plan JSON editor on every rerun so Prompt/Chat switches keep widget state."""
    prepare_plan_editor_before_render()
    plan_key = plan_editor_widget_key()
    if visible:
        holder = {"text": ""}

        def _render_plan_body() -> None:
            raw = st.text_area(
                "Edit plan JSON",
                height=260,
                key=plan_key,
                help="Must be valid JSON. Changes are applied when you click Execute plan or Resolve dependencies.",
                label_visibility="collapsed",
            )
            holder["text"] = s(raw)

        render_editable_block_with_copy(
            "Proposed run plan",
            anchor_id="sym_copy_anchor_plan_json",
            copy_key="copy_plan_json",
            fallback_text=current_plan_editor_text(),
            render_body=_render_plan_body,
        )
        return holder["text"] or current_plan_editor_text()

    st.text_area(
        "Edit plan JSON",
        height=68,
        key=plan_key,
        label_visibility="collapsed",
    )
    st.markdown(
        f'<style>div.st-key-{plan_key} {{ display: none !important; }}</style>',
        unsafe_allow_html=True,
    )
    return current_plan_editor_text()


def apply_pending_plan_editor_sync() -> None:
    """Apply queued plan JSON to the editor. Must run before the plan text_area is rendered."""
    pending = st.session_state.pop("_pending_plan_editor_text", None)
    if pending is not None:
        st.session_state[plan_editor_widget_key()] = pending


def prepare_plan_editor_before_render() -> None:
    """Ensure the plan JSON editor has content before Streamlit draws the text_area."""
    if st.session_state.get("run_plan") is None:
        return
    source = plan_editor_text_from_run_plan()
    widget_key = plan_editor_widget_key()
    apply_pending_plan_editor_sync()
    if not s(st.session_state.get(widget_key)):
        st.session_state[widget_key] = source
        st.session_state["_plan_editor_synced"] = source.strip()


def current_plan_editor_text() -> str:
    widget_key = plan_editor_widget_key()
    text = s(st.session_state.get(widget_key))
    if text:
        return text
    return plan_editor_text_from_run_plan()


def request_plan_editor_sync_from_run_plan() -> None:
    """Queue run_plan JSON for the editor on the next pre-widget render."""
    if not st.session_state.get("run_plan"):
        return
    source = plan_editor_text_from_run_plan().strip()
    if s(st.session_state.get("_plan_editor_synced")) == source:
        return
    st.session_state["_pending_plan_editor_text"] = plan_editor_text_from_run_plan()
    st.session_state["_plan_editor_synced"] = source


def commit_plan_editor_to_session(
    *,
    plan_text: str | None = None,
    apply_ui: bool = True,
) -> tuple[bool, str]:
    """Apply the JSON editor contents to st.session_state.run_plan."""
    plan_text = s(
        plan_text
        if plan_text is not None
        else current_plan_editor_text()
    )
    if not plan_text:
        return True, ""
    try:
        edited_plan = json.loads(plan_text)
    except Exception as e:
        return False, f"Plan JSON is invalid: {e}"
    if not isinstance(edited_plan, dict):
        return False, "Plan JSON must be an object."
    st.session_state.run_plan = edited_plan
    st.session_state["_plan_editor_synced"] = plan_text.strip()
    steps = edited_plan.get("steps")
    if isinstance(steps, list):
        st.session_state["_committed_plan_steps"] = list(steps)
    if apply_ui:
        apply_edited_plan_to_session(edited_plan)
    return True, ""


def get_required_config_fields_for_steps(
    steps: list[str],
    plan_cfg: dict | None = None,
    user_request: str = "",
) -> list[str]:
    """Return config fields required by the requested/resolved steps."""
    plan_cfg = plan_cfg or {}
    user_request = s(user_request)
    required = {
        "domain_name",
        "experiment_id",
        "pour_point_coords",
        "experiment_time_start",
        "experiment_time_end",
    }

    config_fields = {
        "domain_name",
        "experiment_id",
        "pour_point_coords",
        "bounding_box_coords",
        "domain_def",
        "hydrological_model",
        "experiment_time_start",
        "experiment_time_end",
    }

    if {"model_specific_preprocessing", "run_model", "calibrate_model"} & set(steps):
        required.add("hydrological_model")

    try:
        catalog = load_catalog()
        for op in catalog.get("operations", []):
            if op.get("name") in steps:
                for req in op.get("requires", []):
                    if req in config_fields:
                        required.add(req)
    except Exception:
        if plan_requires_bounding_box(plan_cfg, steps, user_request):
            required.add("bounding_box_coords")

    if not plan_requires_bounding_box(plan_cfg, steps, user_request):
        required.discard("bounding_box_coords")

    return sorted(required)


def sync_input_panel_to_run_plan() -> None:
    """Push Input tab workflow settings into run_plan and refresh the plan JSON editor."""
    if not st.session_state.get("run_plan"):
        return
    sync_mpi_to_run_plan()
    sync_all_ui_fields_to_plan(refresh_editor=True, force_editor=True)
    bump_config_preview_version()


def sync_all_ui_fields_to_plan(*, refresh_editor: bool = False, force_editor: bool = False) -> None:
    values = {
        "domain_name": s(st.session_state.domain_name),
        "experiment_id": s(st.session_state.experiment_id),
        "pour_point_coords": s(st.session_state.pour_point_input) or s(st.session_state.selected_pour_point),
        "bounding_box_coords": s(st.session_state.bounding_box_input) or s(st.session_state.selected_bounding_box),
        "domain_def": s(st.session_state.domain_def),
        "hydrological_model": current_hydrological_model(),
        "forcing_dataset": s(st.session_state.forcing_dataset),
        "experiment_time_start": s(st.session_state.tstart),
        "experiment_time_end": s(st.session_state.tend),
    }

    st.session_state.selected_pour_point = values["pour_point_coords"]
    st.session_state.selected_bounding_box = values["bounding_box_coords"]

    if not st.session_state.get("run_plan"):
        return

    plan = st.session_state.run_plan
    plan.setdefault("config", {})
    cfg = plan["config"]

    for key, value in values.items():
        if value:
            cfg[key] = value
        else:
            cfg.pop(key, None)

    steps = plan.get("steps", []) or []
    convo = conversation_text_for_plan_rules()
    required = get_required_config_fields_for_steps(steps, cfg, convo)
    missing = [k for k in required if not s(cfg.get(k))]
    if plan_uses_local_data(cfg, steps, convo, data_dir=SYMFLUENCE_DATA_DIR):
        missing = [k for k in missing if k != "bounding_box_coords"]
    plan["needs_user_input"] = missing

    st.session_state.run_plan = plan
    wx.sync_advanced_config_to_plan()

    if refresh_editor:
        refresh_plan_editor_from_state(force=force_editor)


def update_run_plan_needs_user_input() -> None:
    """Refresh needs_user_input only — never rewrite steps or normalize the plan in place."""
    if not st.session_state.get("run_plan"):
        return
    plan = dict(st.session_state.run_plan)
    cfg = dict(plan.get("config") or {})
    plan["config"] = cfg
    steps = plan.get("steps", []) or []
    convo = conversation_text_for_plan_rules()
    required = get_required_config_fields_for_steps(steps, cfg, convo)
    missing = [k for k in required if not s(cfg.get(k))]
    if plan_uses_local_data(cfg, steps, convo, data_dir=SYMFLUENCE_DATA_DIR):
        missing = [k for k in missing if k != "bounding_box_coords"]
    plan["needs_user_input"] = missing
    st.session_state.run_plan = plan


MISSING_INPUT_GUIDANCE: dict[str, dict[str, str]] = {
    "domain_name": {
        "label": "Domain name",
        "hint": "Short name for the watershed or study area.",
        "where": "Input → Workflow Settings (or fix below).",
    },
    "experiment_id": {
        "label": "Experiment ID",
        "hint": "Label for this run (e.g. run_1, baseline).",
        "where": "Input → Workflow Settings (or fix below).",
    },
    "pour_point_coords": {
        "label": "Pour point",
        "hint": "Set coordinates as lat/lon (e.g. 51.17/-115.57) or click the map in Pour point mode.",
        "where": "Input → Map & Spatial Inputs.",
    },
    "bounding_box_coords": {
        "label": "Bounding box",
        "hint": "north/west/south/east (e.g. 51.76/-116.55/50.95/-115.5) or draw on the map in Bounding box mode.",
        "where": "Input → Map & Spatial Inputs.",
    },
    "experiment_time_start": {
        "label": "Experiment start time",
        "hint": "Format: YYYY-MM-DD HH:MM",
        "where": "Input → Workflow Settings → Start date/time (or fix below).",
    },
    "experiment_time_end": {
        "label": "Experiment end time",
        "hint": "Format: YYYY-MM-DD HH:MM (must be after start).",
        "where": "Input → Workflow Settings → End date/time (or fix below).",
    },
    "hydrological_model": {
        "label": "Hydrological model",
        "hint": "Choose the model used for preprocessing and simulation steps.",
        "where": "Input → Workflow Settings (or fix below).",
    },
    "domain_def": {
        "label": "Domain definition",
        "hint": "How the domain is defined (delineate, lumped, point, subset).",
        "where": "Input → Workflow Settings.",
    },
    "forcing_dataset": {
        "label": "Forcing dataset",
        "hint": "Meteorological forcing source (ERA5, RDRS, etc.).",
        "where": "Input → Workflow Settings.",
    },
}

MISSING_INPUT_FIX_ORDER = [
    "domain_name",
    "experiment_id",
    "pour_point_coords",
    "bounding_box_coords",
    "experiment_time_start",
    "experiment_time_end",
    "hydrological_model",
    "domain_def",
    "forcing_dataset",
]


def set_plan_config_field(field: str, value: str) -> None:
    """Write one plan config field to session state and refresh needs_user_input."""
    if not st.session_state.get("run_plan"):
        return

    value = s(value)
    plan = st.session_state.run_plan
    plan.setdefault("config", {})
    cfg = plan["config"]

    if value:
        cfg[field] = value
    else:
        cfg.pop(field, None)

    if field == "domain_name":
        st.session_state.domain_name = value
        if value and s(st.session_state.experiment_id):
            sync_run_folder_from_session(unlock=True)
    elif field == "experiment_id":
        st.session_state.experiment_id = value
        if value and s(st.session_state.domain_name):
            sync_run_folder_from_session(unlock=True)
    elif field == "pour_point_coords":
        st.session_state.selected_pour_point = value
        parsed = parse_pour_point(value)
        if parsed:
            lat, lon = parsed
            st.session_state.map_lat = lat
            st.session_state.map_lon = lon
            st.session_state.map_point_selected = True
        elif not value:
            st.session_state.map_lat = None
            st.session_state.map_lon = None
            st.session_state.map_point_selected = False
        mark_spatial_inputs_stale()
    elif field == "bounding_box_coords":
        st.session_state.selected_bounding_box = value
        mark_spatial_inputs_stale()
    elif field == "experiment_time_start":
        st.session_state.tstart = value
    elif field == "experiment_time_end":
        st.session_state.tend = value
    elif field == "hydrological_model":
        st.session_state.hydrological_model = normalize_hydrological_model(value) if value else ""
    elif field == "domain_def":
        st.session_state.domain_def = value
    elif field == "forcing_dataset":
        st.session_state.forcing_dataset = value
    elif field in {
        "streamflow_data_provider",
        "station_id",
        "routing_model",
        "pet_method",
        "spinup_period",
        "calibration_period",
        "evaluation_period",
        "iterative_optimization_algorithm",
        "optimization_metric",
        "optimization_target",
        "calibration_timestep",
    }:
        st.session_state[field] = value
    elif field in {"iterations", "population_size", "NUM_PROCESSES", "num_processes"}:
        try:
            st.session_state["mpi" if field in {"NUM_PROCESSES", "num_processes"} else field] = int(value)
        except Exception:
            st.session_state[field] = value

    update_run_plan_needs_user_input()
    bump_all_input_widget_versions()
    refresh_plan_editor_from_state()


def render_fix_missing_inputs_section(needs: list[str]) -> None:
    """Actionable hints and quick fixes for plan needs_user_input fields."""
    needs = [n for n in needs if isinstance(n, str) and s(n)]
    if not needs:
        return

    ordered = [f for f in MISSING_INPUT_FIX_ORDER if f in needs]
    ordered += [f for f in needs if f not in ordered]

    with st.expander(f"Fix missing inputs ({len(ordered)})", expanded=True):
        st.caption(
            "Complete these before **Execute plan**. Quick fixes update the plan, Input tab, and config preview."
        )

        for i, field in enumerate(ordered):
            meta = MISSING_INPUT_GUIDANCE.get(
                field,
                {
                    "label": field.replace("_", " ").title(),
                    "hint": f"Provide `{field}` in the plan config.",
                    "where": "Input tab or edit the plan JSON above.",
                },
            )
            plan_cfg = (st.session_state.run_plan or {}).get("config", {}) or {}
            current = s(plan_cfg.get(field))

            st.markdown(f"**{meta['label']}** (`{field}`)")
            st.caption(meta["hint"])
            st.caption(f"→ {meta['where']}")

            if field == "domain_name":
                val = st.text_input(
                    "Domain name",
                    value=current or s(st.session_state.domain_name),
                    key="fix_missing_domain_name",
                    label_visibility="collapsed",
                )
                if s(val) != current:
                    set_plan_config_field("domain_name", val)
            elif field == "experiment_id":
                val = st.text_input(
                    "Experiment ID",
                    value=current or s(st.session_state.experiment_id),
                    key="fix_missing_experiment_id",
                    label_visibility="collapsed",
                )
                if s(val) != current:
                    set_plan_config_field("experiment_id", val)
            elif field == "pour_point_coords":
                val = st.text_input(
                    "Pour point (lat/lon)",
                    value=current or s(st.session_state.selected_pour_point),
                    placeholder="51.1722/-115.5717",
                    key="fix_missing_pour_point_coords",
                    label_visibility="collapsed",
                )
                if st.button("Apply pour point", key="apply_fix_pour_point", width="stretch"):
                    set_plan_config_field("pour_point_coords", val)
                    st.rerun()
                st.caption("Tip: switch to the **Input** tab and click the map in **Pour point** mode.")
            elif field == "bounding_box_coords":
                val = st.text_input(
                    "Bounding box (north/west/south/east)",
                    value=current or s(st.session_state.selected_bounding_box),
                    placeholder="51.76/-116.55/50.95/-115.5",
                    key="fix_missing_bounding_box_coords",
                    label_visibility="collapsed",
                )
                if st.button("Apply bounding box", key="apply_fix_bounding_box", width="stretch"):
                    set_plan_config_field("bounding_box_coords", val)
                    st.rerun()
            elif field == "experiment_time_start":
                val = st.text_input(
                    "Start time",
                    value=current or s(st.session_state.tstart),
                    placeholder="2001-01-01 01:00",
                    key="fix_missing_experiment_time_start",
                    label_visibility="collapsed",
                )
                if s(val) != current:
                    set_plan_config_field("experiment_time_start", val)
            elif field == "experiment_time_end":
                val = st.text_input(
                    "End time",
                    value=current or s(st.session_state.tend),
                    placeholder="2001-01-10 23:00",
                    key="fix_missing_experiment_time_end",
                    label_visibility="collapsed",
                )
                if s(val) != current:
                    set_plan_config_field("experiment_time_end", val)
            elif field == "hydrological_model":
                options = [m for m in HYDROLOGICAL_MODEL_OPTIONS if m]
                idx = options.index(current) if current in options else 0
                val = st.selectbox(
                    "Hydrological model",
                    options=options,
                    index=idx,
                    key="fix_missing_hydrological_model",
                    label_visibility="collapsed",
                )
                if st.button("Apply model", key="apply_fix_hydrological_model", width="stretch"):
                    set_plan_config_field("hydrological_model", val)
                    st.rerun()
            elif field == "domain_def":
                options = ["delineate", "lumped", "point", "subset"]
                idx = options.index(current) if current in options else 0
                val = st.selectbox(
                    "Domain definition",
                    options=options,
                    index=idx,
                    key="fix_missing_domain_def",
                    label_visibility="collapsed",
                )
                if st.button("Apply domain definition", key="apply_fix_domain_def", width="stretch"):
                    set_plan_config_field("domain_def", val)
                    st.rerun()
            elif field == "forcing_dataset":
                options = FORCING_DATASET_OPTIONS
                idx = options.index(current) if current in options else 0
                val = st.selectbox(
                    "Forcing dataset",
                    options=options,
                    index=idx,
                    key="fix_missing_forcing_dataset",
                    label_visibility="collapsed",
                )
                if st.button("Apply forcing dataset", key="apply_fix_forcing_dataset", width="stretch"):
                    set_plan_config_field("forcing_dataset", val)
                    st.rerun()
            else:
                val = st.text_input(
                    meta["label"],
                    value=current,
                    key=f"fix_missing_{field}",
                    label_visibility="collapsed",
                )
                if s(val) != current:
                    set_plan_config_field(field, val)

            if i < len(ordered) - 1:
                st.divider()

        remaining = (st.session_state.run_plan or {}).get("needs_user_input", []) or []
        if remaining:
            st.warning(f"Still missing: {', '.join(remaining)}")
        else:
            st.success("All required inputs are set. You can execute the plan.")


def set_pour_point_from_map(lat: float, lon: float) -> None:
    value = format_pour_point(lat, lon)

    st.session_state.map_lat = lat
    st.session_state.map_lon = lon
    st.session_state.map_point_selected = True

    st.session_state.selected_pour_point = value

    st.session_state.selected_bounding_box = ""
    st.session_state.bbox_point_1 = None
    st.session_state.bbox_point_2 = None
    st.session_state.bbox_selected = False

    sync_spatial_fields_to_run_plan(refresh_editor=True)

    mark_spatial_inputs_stale()
    bump_config_preview_version()


def set_bounding_box_from_points(lat1: float, lon1: float, lat2: float, lon2: float) -> None:
    value = format_bounding_box(lat1, lon1, lat2, lon2)

    st.session_state.bbox_point_1 = (lat1, lon1)
    st.session_state.bbox_point_2 = (lat2, lon2)
    st.session_state.bbox_selected = True

    st.session_state.selected_bounding_box = value

    sync_spatial_fields_to_run_plan(refresh_editor=True)

    mark_spatial_inputs_stale()
    bump_config_preview_version()


def first_existing_gdf(paths: list[str]):
    for p in paths:
        if os.path.exists(p):
            try:
                gdf = gpd.read_file(p)
                if not gdf.empty:
                    return gdf
            except Exception:
                pass
    return None


MAP_LAYER_CHECKBOX_SPECS = [
    ("show_riverbasins_layer", "River basins", "riverbasins"),
    ("show_hrugru_layer", "HRUs / GRUs", "hrugru"),
    ("show_rivernetwork_layer", "River network", "rivernetwork"),
    ("show_dem_layer", "DEM", "dem"),
    ("show_landclass_layer", "Landclass", "landclass"),
    ("show_soilclass_layer", "Soilclass", "soilclass"),
    ("show_forcing_layer", "ERA5 intersected", "forcing"),
]


def symfluence_domain_shapefile_paths(
    domain_name: str | None = None,
    experiment_id: str | None = None,
) -> dict[str, str]:
    """Expected SYMFLUENCE shapefile paths for the current domain and experiment."""
    domain_name = s(domain_name or st.session_state.domain_name)
    experiment_id = s(experiment_id or st.session_state.experiment_id)
    if not domain_name or not experiment_id:
        return {}

    domain_name = symfluence_domain_name(domain_name, experiment_id)
    domain_root = symfluence_data_domain_dir(domain_name)
    domain_def = s(st.session_state.domain_def) or "lumped"
    catchment_base = domain_root / "shapefiles" / "catchment_intersection"
    return {
        "domain_root": str(domain_root),
        "dem": str(catchment_base / "with_dem" / "catchment_with_dem.shp"),
        "landclass": str(catchment_base / "with_landclass" / "catchment_with_landclass.shp"),
        "soilclass": str(catchment_base / "with_soilgrids" / "catchment_with_soilclass.shp"),
        "forcing": str(
            catchment_base
            / "with_forcing"
            / f"{domain_name}_ERA5_intersected_shapefile.shp"
        ),
        "riverbasins": str(
            domain_root
            / "shapefiles"
            / "river_basins"
            / f"{domain_name}_riverBasins_{domain_def}.shp"
        ),
        "hrugru": str(
            domain_root
            / "shapefiles"
            / "catchment"
            / domain_def
            / experiment_id
            / f"{domain_name}_HRUs_GRUs.shp"
        ),
        "rivernetwork": str(
            domain_root
            / "shapefiles"
            / "river_network"
            / f"{domain_name}_riverNetwork_{domain_def}.shp"
        ),
    }


def shapefile_layer_available(path: str) -> bool:
    return bool(path) and os.path.exists(path)


def render_map_layer_checkboxes(key_prefix: str) -> int:
    """Layer toggles shared by Input and Output maps. Returns count of layers on disk."""
    paths = symfluence_domain_shapefile_paths()
    if not paths:
        st.info("Set **Domain name** and **Experiment ID** to check for review layers.")
        return 0

    available_count = 0
    cols = st.columns(3)
    for i, (state_key, label, path_key) in enumerate(MAP_LAYER_CHECKBOX_SPECS):
        shp_path = paths.get(path_key, "")
        available = shapefile_layer_available(shp_path)
        if available:
            available_count += 1
        current = bool(st.session_state.get(state_key, False))
        if not available and current:
            st.session_state[state_key] = False
            current = False
        with cols[i % 3]:
            st.session_state[state_key] = st.checkbox(
                label,
                value=current if available else False,
                disabled=not available,
                key=f"{key_prefix}_{state_key}",
                help=shp_path if available else f"Not found yet:\n{shp_path}",
            )
    return available_count


def build_pour_point_map(
    center_lat: float = 52.10,
    center_lon: float = -106.66,
    zoom: int = 7,
    show_dem_layer: bool = True,
    show_landclass_layer: bool = False,
    show_soilclass_layer: bool = False,
    show_riverbasins_layer: bool = False,
    show_hrugru_layer: bool = False,
    show_forcing_layer: bool = False,
    show_rivernetwork_layer: bool = False,
):
    # Keep map centered on selected pour point unless a completed bbox exists
    if (
        st.session_state.map_point_selected
        and st.session_state.map_lat is not None
        and st.session_state.map_lon is not None
    ):
        center_lat = st.session_state.map_lat
        center_lon = st.session_state.map_lon
        zoom = 8

    # If bbox is completed, center on the bbox
    if (
        st.session_state.map_mode == "bounding_box"
        and st.session_state.bbox_selected
        and st.session_state.bbox_point_1 is not None
        and st.session_state.bbox_point_2 is not None
    ):
        lat1, lon1 = st.session_state.bbox_point_1
        lat2, lon2 = st.session_state.bbox_point_2
        center_lat = (lat1 + lat2) / 2.0
        center_lon = (lon1 + lon2) / 2.0

    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom)

    if (
        st.session_state.map_point_selected
        and st.session_state.map_lat is not None
        and st.session_state.map_lon is not None
    ):
        folium.Marker(
            [st.session_state.map_lat, st.session_state.map_lon],
            tooltip="Selected pour point",
        ).add_to(m)

    if st.session_state.bbox_point_1 is not None and not st.session_state.bbox_selected:
        lat1, lon1 = st.session_state.bbox_point_1
        folium.Marker(
            [lat1, lon1],
            tooltip="Bounding box corner 1",
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(m)

    if st.session_state.bbox_selected and st.session_state.bbox_point_1 and st.session_state.bbox_point_2:
        lat1, lon1 = st.session_state.bbox_point_1
        lat2, lon2 = st.session_state.bbox_point_2
        north = max(lat1, lat2)
        south = min(lat1, lat2)
        east = max(lon1, lon2)
        west = min(lon1, lon2)

        m.fit_bounds([[south, west], [north, east]])

        folium.Rectangle(
            bounds=[[south, west], [north, east]],
            tooltip="Selected bounding box",
            color="red",
            weight=1,
            fill=True,
            fill_opacity=0.15,
        ).add_to(m)

        folium.Marker([lat1, lon1], tooltip="Bounding box corner 1", icon=folium.Icon(color="red", icon="flag")).add_to(m)
        folium.Marker([lat2, lon2], tooltip="Bounding box corner 2", icon=folium.Icon(color="red", icon="flag")).add_to(m)

    try:
        layer_paths = symfluence_domain_shapefile_paths()
        if layer_paths:
            dem_path = layer_paths["dem"]
            landclass_path = layer_paths["landclass"]
            soilclass_path = layer_paths["soilclass"]
            forcing_path = layer_paths["forcing"]
            riverbasins_path = layer_paths["riverbasins"]
            hrugru_path = layer_paths["hrugru"]
            rivernetwork_path = layer_paths["rivernetwork"]

            if not st.session_state.map_point_selected:
                review_gdf = first_existing_gdf([riverbasins_path, hrugru_path, rivernetwork_path])
                if review_gdf is not None and not review_gdf.empty:
                    minx, miny, maxx, maxy = review_gdf.total_bounds
                    m.fit_bounds([[miny, minx], [maxy, maxx]])

            def add_layer_if_exists(shp_path: str, layer_name: str, color: str, tooltip_fields: list[str] | None = None):
                if not os.path.exists(shp_path):
                    return None

                gdf = gpd.read_file(shp_path)
                if gdf.empty:
                    return None

                if layer_name == "River Basins":
                    style_fn = lambda x: {"color": color, "weight": 2, "fillOpacity": 0.05}
                    highlight_fn = lambda x: {"weight": 2, "fillOpacity": 0.03}
                elif layer_name == "HRUs / GRUs":
                    style_fn = lambda x: {"color": color, "weight": 2, "fillOpacity": 0.00}
                    highlight_fn = lambda x: {"weight": 3, "fillOpacity": 0.05}
                elif layer_name == "River Network":
                    style_fn = lambda x: {"color": color, "weight": 4, "fillOpacity": 0.00}
                    highlight_fn = lambda x: {"weight": 6, "fillOpacity": 0.00}
                else:
                    style_fn = lambda x: {"color": color, "weight": 4, "fillOpacity": 0.10}
                    highlight_fn = lambda x: {"weight": 6, "fillOpacity": 0.20}

                geojson_kwargs = {
                    "data": gdf.__geo_interface__,
                    "name": layer_name,
                    "style_function": style_fn,
                    "highlight_function": highlight_fn,
                }

                if tooltip_fields:
                    existing_fields = [f for f in tooltip_fields if f in gdf.columns]
                    if existing_fields:
                        geojson_kwargs["tooltip"] = folium.GeoJsonTooltip(
                            fields=existing_fields,
                            aliases=[f"{f}: " for f in existing_fields],
                            localize=True,
                            sticky=False,
                            labels=True,
                            style=(
                                "background-color: white; color: black; font-family: Arial; font-size: 11px; "
                                "padding: 6px 8px; border-radius: 6px; box-shadow: 2px 2px 6px rgba(0,0,0,0.3);"
                            ),
                        )

                folium.GeoJson(**geojson_kwargs).add_to(m)
                return gdf

            active_gdfs = []

            if show_dem_layer:
                gdf = add_layer_if_exists(dem_path, "DEM Catchment", "red")
                if gdf is not None:
                    active_gdfs.append(gdf)

            if show_landclass_layer:
                gdf = add_layer_if_exists(landclass_path, "Landclass Catchment", "green")
                if gdf is not None:
                    active_gdfs.append(gdf)

            if show_soilclass_layer:
                gdf = add_layer_if_exists(soilclass_path, "Soilclass Catchment", "orange")
                if gdf is not None:
                    active_gdfs.append(gdf)

            if show_forcing_layer:
                gdf = add_layer_if_exists(forcing_path, "ERA5 Intersected", "gray")
                if gdf is not None:
                    active_gdfs.append(gdf)

            if show_riverbasins_layer:
                gdf = add_layer_if_exists(riverbasins_path, "River Basins", "purple", tooltip_fields=["GRU_ID", "GRU_area"])
                if gdf is not None:
                    active_gdfs.append(gdf)

            if show_hrugru_layer:
                gdf = add_layer_if_exists(hrugru_path, "HRUs / GRUs", "brown", tooltip_fields=["HRU_ID", "GRU_ID", "HRU_area"])
                if gdf is not None:
                    active_gdfs.append(gdf)

            if show_rivernetwork_layer:
                gdf = add_layer_if_exists(rivernetwork_path, "River Network", "blue")
                if gdf is not None:
                    active_gdfs.append(gdf)

            if active_gdfs and not st.session_state.map_point_selected:
                combined = active_gdfs[0]
                for gdf in active_gdfs[1:]:
                    combined = pd.concat([combined, gdf], ignore_index=True)
                combined = gpd.GeoDataFrame(combined, geometry="geometry", crs=active_gdfs[0].crs)
                if not combined.empty:
                    minx, miny, maxx, maxy = combined.total_bounds
                    m.fit_bounds([[miny, minx], [maxy, maxx]])

    except Exception as e:
        st.warning(f"Shapefile layer load failed: {e}")

    folium.LayerControl().add_to(m)
    return m


def dump_yaml(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)


def run_cmd_stream(cmd: list[str], cwd: Path, output_box, log_path: Path | None = None):
    p = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    collected: list[str] = []
    log_file = None

    try:
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("a", encoding="utf-8")

        while True:
            line = p.stdout.readline() if p.stdout else ""
            if not line and p.poll() is not None:
                break
            if line:
                collected.append(line)
                output_box.code("".join(collected))
                if log_file is not None:
                    log_file.write(line)
                    log_file.flush()

        rc = p.wait()
        if log_file is not None:
            log_file.write(f"\n[return code: {rc}]\n")
            log_file.flush()
        return rc, "".join(collected)
    finally:
        if log_file is not None:
            log_file.close()


def augment_request_with_ui(nl: str) -> str:
    lines = [s(nl), "", "Optional UI inputs (use ONLY if non-empty):"]

    if s(st.session_state.domain_name):
        lines.append(f"- domain_name: {s(st.session_state.domain_name)}")
    if s(st.session_state.experiment_id):
        lines.append(f"- experiment_id: {s(st.session_state.experiment_id)}")
    if current_hydrological_model():
        lines.append(f"- hydrological_model: {current_hydrological_model()}")

    effective_pour = s(st.session_state.selected_pour_point) or s(st.session_state.pour_point_input)
    if effective_pour:
        lines.append(f"- pour_point_coords: {effective_pour}")

    effective_bbox = s(st.session_state.selected_bounding_box) or s(st.session_state.bounding_box_input)
    if effective_bbox:
        lines.append(f"- bounding_box_coords: {effective_bbox}")

    if s(st.session_state.domain_def):
        lines.append(f"- domain_def: {s(st.session_state.domain_def)}")
    if s(st.session_state.tstart):
        lines.append(f"- experiment_time_start: {s(st.session_state.tstart)}")
    if s(st.session_state.tend):
        lines.append(f"- experiment_time_end: {s(st.session_state.tend)}")

    lines = wx.augment_request_with_advanced(lines)
    lines = wx.augment_request_with_calibration(lines)
    return "\n".join(lines).strip() + "\n"


def run_generate_plan_from_nl_request() -> None:
    """NL prompt -> full SYMFLUENCE run plan (config, steps, needs_user_input)."""
    provider = s(st.session_state.get("llm_provider")) or "openai"
    provider_label = LLM_PROVIDER_LABELS.get(provider, provider)
    key = st.session_state.api_keys.get(provider)
    if not key:
        st.error(f"Please save your {provider_label} API key first.")
        return
    if not llm_provider_available(provider):
        st.error(f"{provider_label} provider is not available in this environment.")
        return
    if not s(st.session_state.nl_request) or is_plan_json_text(st.session_state.nl_request):
        st.error("Describe your workflow first (text or voice).")
        return
    try:
        capture_user_prompt_from_session()
        planner_request = augment_request_with_ui(st.session_state.nl_request)
        model = s(st.session_state.get("llm_model")) or DEFAULT_LLM_MODEL.get(provider, "gpt-5-mini")
        if provider == "gemini":
            plan = GeminiProvider(api_key=key).generate_run_plan(
                model=model,
                user_request=planner_request,
            )
        elif provider == "claude":
            plan = ClaudeProvider(api_key=key).generate_run_plan(
                model=model,
                user_request=planner_request,
            )
        else:
            plan = OpenAIProvider(api_key=key).generate_run_plan(
                model=model,
                user_request=planner_request,
            )
        plan = preserve_explicit_config_fields_from_prompt(plan, st.session_state.nl_request)
        convo = conversation_text_for_plan_rules() or s(st.session_state.nl_request)
        plan = normalize_local_workflow_plan(
            plan,
            convo,
            data_dir=SYMFLUENCE_DATA_DIR,
        )

        if not isinstance(plan, dict):
            raise RuntimeError(f"Planner returned non-dict: {type(plan)}")
        required_top = {"config", "steps", "needs_user_input", "notes"}
        missing_top = [k for k in required_top if k not in plan]
        if missing_top:
            raise RuntimeError(f"Planner plan missing keys: {missing_top}. Got keys={list(plan.keys())}")
        if not isinstance(plan["steps"], list) or not all(isinstance(x, str) for x in plan["steps"]):
            raise RuntimeError("Planner returned invalid 'steps' (must be list[str]).")
        if not isinstance(plan["config"], dict):
            raise RuntimeError("Planner returned invalid 'config' (must be object).")
        if not isinstance(plan["needs_user_input"], list) or not all(isinstance(x, str) for x in plan["needs_user_input"]):
            raise RuntimeError("Planner returned invalid 'needs_user_input' (must be list[str]).")

        st.session_state.run_plan = plan
        st.session_state.pop("_committed_plan_steps", None)
        apply_plan_config_to_ui(plan)
        if s(st.session_state.get("run_folder")):
            st.session_state.run_workspace_locked = True
        refresh_plan_editor_from_state(force=True, remount=True)
        seed_chat_from_generate_plan(user_prompt_for_metadata(), plan)
        save_chat_messages_to_run_folder()
        st.success("Run plan generated.")
        st.rerun()
    except Exception as e:
        st.error(f"Planning error: {e}")
        st.code(traceback.format_exc())


def resolve_voice_transcription_provider() -> tuple[str | None, str | None]:
    """Return (provider_id, api_key) for speech-to-text, with OpenAI fallback."""
    active = s(st.session_state.get("llm_provider")) or "openai"
    candidates: list[str] = []
    if active in ("openai", "gemini"):
        candidates.append(active)
    for fallback in ("openai", "gemini"):
        if fallback not in candidates:
            candidates.append(fallback)

    for provider in candidates:
        if provider == "claude":
            continue
        key = st.session_state.api_keys.get(provider)
        if key and llm_provider_available(provider):
            return provider, key
    return None, None


def apply_pending_nl_request_transcript() -> None:
    """Apply a voice transcript before the nl_request widget is drawn."""
    pending = st.session_state.pop("_pending_nl_transcript", None)
    if pending is not None:
        st.session_state.nl_request = pending


def apply_pending_workflow_chat_draft() -> None:
    """Apply a voice transcript before the chat compose widget is drawn."""
    pending = st.session_state.pop("_pending_workflow_chat_draft", None)
    if pending is not None:
        bump_workflow_chat_compose_version()
        st.session_state[workflow_chat_compose_key()] = pending


def clear_workflow_chat_compose() -> None:
    """Clear the compose box (button callback)."""
    bump_workflow_chat_compose_version()


def transcribe_voice_to_nl_request(audio_bytes: bytes, filename: str) -> str | None:
    provider, key = resolve_voice_transcription_provider()
    if not provider or not key:
        st.error(
            "Save an OpenAI or Gemini API key to use voice transcription. "
            "OpenAI Whisper works with an OpenAI key only."
        )
        return None

    try:
        if provider == "gemini":
            model = s(st.session_state.get("llm_model")) or DEFAULT_LLM_MODEL["gemini"]
            return GeminiProvider(api_key=key).transcribe_audio(
                audio_bytes=audio_bytes,
                filename=filename,
                model=model,
            )
        return OpenAIProvider(api_key=key).transcribe_audio(
            audio_bytes=audio_bytes,
            filename=filename,
        )
    except Exception as e:
        st.error(f"Voice transcription failed: {e}")
        st.code(traceback.format_exc())
        return None


def apply_plan_config_to_ui(plan: dict):
    """Apply non-empty plan config values to UI state without erasing manual UI values.

    Important: GPT may omit fields such as bounding_box_coords even when the
    user typed them in the UI. Therefore, only overwrite UI fields when the
    plan provides a non-empty value.
    """
    cfgp = (plan or {}).get("config", {}) or {}

    domain_name = s(cfgp.get("domain_name"))
    experiment_id = s(cfgp.get("experiment_id"))
    pour_point = s(cfgp.get("pour_point_coords"))
    bbox = s(cfgp.get("bounding_box_coords"))
    hydrological_model = s(cfgp.get("hydrological_model"))
    domain_def = s(cfgp.get("domain_def"))
    forcing_dataset = s(cfgp.get("forcing_dataset"))
    tstart = s(cfgp.get("experiment_time_start"))
    tend = s(cfgp.get("experiment_time_end"))

    if domain_name:
        st.session_state.domain_name = domain_name

    if experiment_id:
        st.session_state.experiment_id = experiment_id

    if pour_point:
        st.session_state.selected_pour_point = pour_point

    if bbox:
        st.session_state.selected_bounding_box = bbox

    if hydrological_model:
        st.session_state.hydrological_model = normalize_hydrological_model(hydrological_model)

    st.session_state.refresh_spatial_inputs = True

    if domain_def:
        st.session_state.domain_def = domain_def

    if forcing_dataset:
        st.session_state.forcing_dataset = forcing_dataset

    if tstart:
        st.session_state.tstart = tstart

    if tend:
        st.session_state.tend = tend

    mpi_val = resolve_num_processes_from_plan_cfg(cfgp)
    if mpi_val is not None:
        st.session_state.mpi = mpi_val

    bump_input_panel_widget_versions()
    mark_spatial_inputs_stale()

    sync_run_folder_from_session()

    wx.apply_advanced_config_from_plan(cfgp)
    st.session_state.refresh_spatial_inputs = True


def force_steps(plan: dict, want_create_pour_point: bool) -> dict:
    steps = list(plan.get("steps", []) or [])
    seen = set()
    ordered = []

    for s0 in steps:
        if isinstance(s0, str) and s0 not in seen:
            ordered.append(s0)
            seen.add(s0)

    PRIORITY = {
        "validate_config": 0,
        "setup_project": 10,
        "create_pour_point": 20,
        "acquire_attributes": 30,
        "define_domain": 40,
        "discretize_domain": 50,
        "process_observed_data": 60,
        "acquire_forcings": 70,
        "model_agnostic_preprocessing": 80,
        "model_specific_preprocessing": 90,
        "run_model": 100,
        "postprocess_results": 110,
        "calibrate_model": 120,
        "run_emulation": 130,
        "run_benchmarking": 140,
        "run_sensitivity_analysis": 150,
        "run_decision_analysis": 160,
    }

    if "validate_config" not in seen:
        ordered.insert(0, "validate_config")
        seen.add("validate_config")

    if "setup_project" not in seen:
        i = ordered.index("validate_config") + 1
        ordered.insert(i, "setup_project")
        seen.add("setup_project")

    if want_create_pour_point and "create_pour_point" not in seen:
        i = ordered.index("setup_project") + 1
        ordered.insert(i, "create_pour_point")
        seen.add("create_pour_point")

    index_map = {s1: i for i, s1 in enumerate(ordered)}
    ordered = sorted(ordered, key=lambda s2: (PRIORITY.get(s2, 500), index_map.get(s2, 999999)))
    ordered = [s3 for s3 in ordered if s3 != "dry_run"]

    plan["steps"] = ordered
    return plan


st.set_page_config(page_title="HydroAgent: SYMFLUENCE Workflow Assistant Agent", layout="wide")

st.markdown(
    """
<style>
    /* Slightly compact typography for the whole app (CSS only, not config.toml). */
    html {
        font-size: 14px;
    }
    .stApp {
        font-size: 14px;
    }
    .block-container {
        padding-top: 2.75rem;
        padding-bottom: 0.5rem;
        max-width: 100%;
    }
    .sym-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        padding: 0.25rem 0 0.85rem 0;
        border-bottom: 1px solid rgba(49, 51, 63, 0.12);
        margin-bottom: 0.85rem;
    }
    .sym-title-wrap {
        display: flex;
        align-items: baseline;
        gap: 1rem;
    }
    .sym-title {
        font-size: 1.45rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        margin: 0;
    }
    .sym-subtitle {
        color: #6b7280;
        font-size: 0.85rem;
        font-weight: 500;
    }
    .sym-status {
        border: 1px solid #bbf7d0;
        color: #166534;
        background: #f0fdf4;
        padding: 0.35rem 0.75rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 700;
        white-space: nowrap;
    }
    .card {
        border: 1px solid rgba(49, 51, 63, 0.12);
        border-radius: 14px;
        padding: 1rem 1rem 0.9rem 1rem;
        background: #ffffff;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        margin-bottom: 0.85rem;
    }
    .card-title {
        font-weight: 750;
        font-size: 0.9rem;
        margin-bottom: 0.2rem;
    }
    .card-subtitle {
        color: #6b7280;
        font-size: 0.75rem;
        margin-bottom: 0.7rem;
    }
    .right-panel {
        border: none;
        border-radius: 0;
        padding: 0;
        background: transparent;
        box-shadow: none;
    }
    .metric-card {
        border: 1px solid rgba(49, 51, 63, 0.12);
        border-radius: 12px;
        padding: 0.7rem 0.8rem;
        background: #f8fafc;
        min-height: 78px;
    }
    .metric-label {
        color: #64748b;
        font-size: 0.68rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .metric-value {
        color: #0f172a;
        font-size: 0.9rem;
        font-weight: 800;
        margin-top: 0.25rem;
    }
    section[data-testid="stSidebar"] .stRadio label {
        font-size: 0.85rem;
        font-weight: 650;
    }
    /* Workflows page: trim page chrome; each panel scrolls inside its border wrapper. */
    footer[data-testid="stFooter"] {
        display: none !important;
    }
    .block-container:has(.sym-header) {
        padding-bottom: 0 !important;
        margin-bottom: 0 !important;
    }
    .sym-workflow-panels ~ div [data-testid="stHorizontalBlock"] {
        align-items: stretch !important;
        margin-bottom: 0 !important;
    }
    .sym-workflow-panels ~ div [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        display: flex !important;
        flex-direction: column !important;
        min-height: 0 !important;
    }
    .sym-workflow-panels ~ div [data-testid="stHorizontalBlock"] > [data-testid="column"] [data-testid="stVerticalBlockBorderWrapper"] {
        height: calc(100dvh - 10.5rem) !important;
        max-height: calc(100dvh - 10.5rem) !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        flex: 1 1 auto !important;
    }
    .assistant-plan-divider {
        text-align: center;
        color: #475569;
        font-size: 0.8rem;
        font-weight: 1000;
        letter-spacing: 0.08em;
        margin: 0.55rem 0 0.7rem 0;
        user-select: none;
        line-height: 1;
    }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"<style>{assistant_panel_button_css()}{workflow_panel_surface_css()}</style>",
    unsafe_allow_html=True,
)

# Safe defaults for button values used later in the script.
validate_btn = False
dryrun_btn = False
setup_btn = False
run_btn = False
confirm_danger_run = False
output_box = None
progress_box = None

st.markdown(
    """
<div class="sym-header">
  <div class="sym-title-wrap">
    <div class="sym-title">HydroAgent</div>
    <div class="sym-subtitle">SYMFLUENCE Workflow Assistant Agent</div>
  </div>
  <div class="sym-status">✓ System status</div>
</div>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Left navigation and global settings
# -----------------------------------------------------------------------------
st.sidebar.markdown("## HydroAgent")
current_page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Workflows", "Experiments", "Data", "Templates", "Results", "Logs", "Settings"],
    index=1,
)

with st.sidebar.expander("Local SYMFLUENCE paths", expanded=current_page == "Settings"):
    symfluence_repo_input = st.text_input(
        "SYMFLUENCE repo path",
        value=str(SYMFLUENCE_REPO),
        key="local_symfluence_repo_path",
    )
    symfluence_data_input = st.text_input(
        "SYMFLUENCE data path",
        value=str(SYMFLUENCE_DATA_DIR),
        key="local_symfluence_data_path",
    )
    symfluence_python_input = st.text_input(
        "SYMFLUENCE Python path",
        value=str(SYMFLUENCE_PYTHON),
        key="local_symfluence_python_path",
    )

    if st.button("Save local paths", key="save_local_paths", type="secondary"):
        new_settings = load_local_settings()
        new_settings["symfluence_repo"] = symfluence_repo_input
        new_settings["symfluence_data_dir"] = symfluence_data_input
        new_settings["symfluence_python"] = symfluence_python_input
        save_local_settings(new_settings)
        st.success("Local paths saved. Refresh/restart the app if needed.")

    SYMFLUENCE_REPO = Path(symfluence_repo_input)
    SYMFLUENCE_DATA_DIR = Path(symfluence_data_input)
    SYMFLUENCE_PYTHON = Path(symfluence_python_input)

    st.caption("Path status")
    if SYMFLUENCE_REPO.exists():
        st.success("Repo found")
    else:
        st.error("Repo not found")
    if SYMFLUENCE_DATA_DIR.exists():
        st.success("Data folder found")
    else:
        st.warning("Data folder not found")
    if SYMFLUENCE_PYTHON.exists():
        st.success("Python found")
    else:
        st.error("Python not found")

YAML_TO_PLAN_KEYS = {
    "DOMAIN_NAME": "domain_name",
    "EXPERIMENT_ID": "experiment_id",
    "POUR_POINT_COORDS": "pour_point_coords",
    "BOUNDING_BOX_COORDS": "bounding_box_coords",
    "DOMAIN_DEFINITION_METHOD": "domain_def",
    "HYDROLOGICAL_MODEL": "hydrological_model",
    "EXPERIMENT_TIME_START": "experiment_time_start",
    "EXPERIMENT_TIME_END": "experiment_time_end",
    "FORCING_DATASET": "forcing_dataset",
    "MPI_PROCESSES": "mpi_processes",
    "NUM_PROCESSES": "num_processes",
}


def list_assistant_run_folders() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted(
        p.name
        for p in RUNS_DIR.iterdir()
        if p.is_dir() and p.name not in RUN_FOLDER_SKIP
    )


def list_symfluence_data_domains() -> list[str]:
    if not SYMFLUENCE_DATA_DIR.exists():
        return []
    return sorted(
        p.name
        for p in SYMFLUENCE_DATA_DIR.iterdir()
        if p.is_dir() and p.name.startswith("domain_")
    )


def split_domain_name_from_combined(combined: str, experiment_id: str) -> str:
    combined = s(combined)
    experiment_id = s(experiment_id)
    if not combined or not experiment_id:
        return combined
    suffix = f"_{experiment_id}"
    if combined.endswith(suffix) and len(combined) > len(suffix):
        return combined[: -len(suffix)]
    return combined


def parse_symfluence_data_folder(folder_name: str) -> tuple[str, str]:
    """Infer domain_name and experiment_id from a SYMFLUENCE_data/domain_* folder."""
    folder_name = s(folder_name)
    if not folder_name.startswith("domain_"):
        return "", ""

    domain_path = SYMFLUENCE_DATA_DIR / folder_name
    cfg_path = domain_path / "config.yaml"
    if cfg_path.exists():
        cfg = load_yaml(cfg_path)
        exp = s(cfg.get("EXPERIMENT_ID"))
        domain = split_domain_name_from_combined(s(cfg.get("DOMAIN_NAME")), exp)
        if domain and exp:
            return domain, exp

    rest = folder_name[len("domain_") :]
    sim_root = domain_path / "simulations"
    if sim_root.is_dir():
        experiments = sorted(p.name for p in sim_root.iterdir() if p.is_dir())
        if len(experiments) == 1:
            exp = experiments[0]
            suffix = f"_{exp}"
            if rest.endswith(suffix) and len(rest) > len(suffix):
                return rest[: -len(suffix)], exp
            return rest, exp

    return rest, ""


def yaml_cfg_to_plan_config(cfg: dict) -> dict:
    plan_cfg: dict = {}
    for yaml_key, plan_key in YAML_TO_PLAN_KEYS.items():
        value = cfg.get(yaml_key)
        if value is not None and s(str(value)):
            plan_cfg[plan_key] = value

    for spec_key, yaml_key in FIELD_MAP.items():
        if spec_key in plan_cfg:
            continue
        value = cfg.get(yaml_key)
        if value is not None and s(str(value)):
            plan_cfg[spec_key] = value

    exp = s(plan_cfg.get("experiment_id"))
    if plan_cfg.get("domain_name") and exp:
        plan_cfg["domain_name"] = split_domain_name_from_combined(
            str(plan_cfg["domain_name"]),
            exp,
        )

    if plan_cfg.get("hydrological_model"):
        plan_cfg["hydrological_model"] = normalize_hydrological_model(
            str(plan_cfg["hydrological_model"])
        )

    return plan_cfg


def apply_loaded_run_to_session(
    run_folder: str,
    plan_cfg: dict,
    plan: dict | None = None,
    *,
    execution_log: str | None = None,
) -> None:
    st.session_state.run_folder = run_folder
    st.session_state.run_workspace_locked = True

    if plan:
        st.session_state.run_plan = plan
        steps = plan.get("steps")
        if isinstance(steps, list):
            st.session_state["_committed_plan_steps"] = list(steps)
    else:
        st.session_state.run_plan = {
            "config": plan_cfg,
            "steps": [],
            "needs_user_input": [],
            "notes": "Loaded from saved run.",
        }

    apply_plan_config_to_ui(st.session_state.run_plan)

    pour = s(plan_cfg.get("pour_point_coords"))
    bbox = s(plan_cfg.get("bounding_box_coords"))
    if pour:
        st.session_state.pour_point_input = pour
        parsed = parse_pour_point(pour)
        if parsed:
            lat, lon = parsed
            st.session_state.map_lat = lat
            st.session_state.map_lon = lon
            st.session_state.map_point_selected = True
    if bbox:
        st.session_state.bounding_box_input = bbox

    mpi_val = plan_cfg.get("num_processes") or plan_cfg.get("mpi_processes")
    if mpi_val is not None:
        try:
            st.session_state.mpi = int(mpi_val)
        except Exception:
            pass

    if execution_log is not None:
        st.session_state.execution_log_text = execution_log

    refresh_plan_editor_from_state()
    bump_config_preview_version()
    mark_spatial_inputs_stale()

def load_assistant_run(run_folder: str) -> str | None:
    run_folder = s(run_folder)
    if not run_folder:
        return "Select an assistant run folder."

    run_dir = RUNS_DIR / run_folder
    if not run_dir.is_dir():
        return f"Run folder not found: {run_dir}"

    plan_cfg: dict = {}
    plan: dict | None = None

    plan_path = run_dir / "plan.json"
    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan_cfg = (plan or {}).get("config", {}) or {}
        except Exception as e:
            return f"Could not read plan.json: {e}"

    cfg_path = run_dir / "config.yaml"
    if cfg_path.exists():
        yaml_plan = yaml_cfg_to_plan_config(load_yaml(cfg_path))
        plan_cfg = {**plan_cfg, **yaml_plan}

    spec_path = run_dir / "spec.json"
    if spec_path.exists() and not plan_cfg:
        try:
            spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
            if isinstance(spec_data, dict):
                plan_cfg = spec_data
        except Exception:
            pass

    if not plan_cfg:
        return f"No config.yaml or plan.json found in {run_dir}"

    exp = s(plan_cfg.get("experiment_id"))
    domain_raw = s(plan_cfg.get("domain_name"))
    if domain_raw and exp:
        basin, mac_suffix = symfluence_domain_mac_suffix(domain_raw)
        if mac_suffix is None:
            basin = split_domain_name_from_combined(domain_raw, exp) or domain_raw
        plan_cfg["domain_name"] = basin

    log_path = run_dir / "logs" / "execution.log"
    execution_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    recovered_prompt = load_user_prompt_from_run_dir(run_dir, execution_log)
    if recovered_prompt:
        st.session_state.user_prompt = recovered_prompt
        st.session_state.nl_request = recovered_prompt

    apply_loaded_run_to_session(
        run_folder,
        plan_cfg,
        plan,
        execution_log=execution_log,
    )
    loaded_chat = load_chat_messages_from_run_dir(run_dir)
    if loaded_chat:
        st.session_state.chat_messages = loaded_chat
    elif isinstance(st.session_state.get("run_plan"), dict):
        seed_chat_from_generate_plan(recovered_prompt, st.session_state.run_plan)
    return None


def load_symfluence_data_domain(folder_name: str) -> str | None:
    folder_name = s(folder_name)
    if not folder_name:
        return "Select a SYMFLUENCE data domain folder."

    domain_path = SYMFLUENCE_DATA_DIR / folder_name
    if not domain_path.is_dir():
        return f"Domain folder not found: {domain_path}"

    domain_name, experiment_id = parse_symfluence_data_folder(folder_name)
    if not domain_name or not experiment_id:
        return (
            f"Could not infer domain_name and experiment_id from {folder_name}. "
            "Ensure the folder matches domain_<name>_<experiment> or has simulations/<experiment_id>."
        )

    plan_cfg = {"domain_name": domain_name, "experiment_id": experiment_id}
    cfg_path = domain_path / "config.yaml"
    if cfg_path.exists():
        yaml_plan = yaml_cfg_to_plan_config(load_yaml(cfg_path))
        yaml_plan["domain_name"] = domain_name
        yaml_plan["experiment_id"] = experiment_id
        plan_cfg = yaml_plan

    basin, _suffix = symfluence_domain_mac_suffix(domain_name)
    plan_cfg["domain_name"] = basin
    plan_cfg["experiment_id"] = experiment_id
    run_folder = run_folder_for_symfluence_domain(domain_name, experiment_id)
    apply_loaded_run_to_session(run_folder, plan_cfg, plan=None, execution_log="")
    return None


def start_new_assistant_run_from_session() -> str | None:
    domain_name = s(st.session_state.domain_name)
    experiment_id = s(st.session_state.experiment_id)
    if not domain_name or not experiment_id:
        return "Set Domain name and Experiment ID before starting a new run."

    basin = symfluence_domain_name(domain_name, experiment_id)
    st.session_state.run_workspace_locked = False
    run_folder = allocate_unique_run_folder(
        basin,
        experiment_id,
        RUNS_DIR,
        SYMFLUENCE_DATA_DIR,
    )
    st.session_state.run_folder = run_folder
    build_real_run_files_from_state()
    st.session_state.run_workspace_locked = True
    return None


def render_start_load_run_section() -> None:
    with st.expander("Start / load run", expanded=False):
        st.caption(
            "Create or select a run under "
            f"`{RUNS_DIR}` "
            f"or load an existing SYMFLUENCE domain under `{SYMFLUENCE_DATA_DIR}`."
        )

        active_folder = s(st.session_state.run_folder)
        if active_folder:
            run_path = RUNS_DIR / active_folder
            data_path = symfluence_data_domain_dir(
                s(st.session_state.domain_name),
                s(st.session_state.experiment_id),
                run_folder=active_folder,
            )
            if run_path.is_dir():
                lock_note = " (loaded — will resume in place)" if st.session_state.get("run_workspace_locked") else ""
                st.info(f"Active assistant run: `{run_path}`{lock_note}")
            elif data_path.is_dir():
                st.info(f"Active SYMFLUENCE domain: `{data_path}`")
            else:
                st.info(f"Active run folder name: `{active_folder}` (not created on disk yet)")
            if not st.session_state.get("run_workspace_locked") and " (" in active_folder:
                st.caption(
                    "Mac-style duplicate active — SYMFLUENCE data will go to a new "
                    f"`domain_*` folder, not the original workspace."
                )
        else:
            st.caption("No active run folder yet.")

        source = st.radio(
            "Run source",
            options=["new", "assistant", "data"],
            format_func=lambda x: {
                "new": "Start new run",
                "assistant": "Load assistant run",
                "data": "Load SYMFLUENCE data domain",
            }[x],
            horizontal=True,
            key="run_load_source",
        )

        if source == "new":
            st.caption(
                "Uses Domain name and Experiment ID to create "
                f"`runs/<domain>_<experiment>/` (config.yaml, plan.json, spec.json). "
                "If that workspace already exists, a Mac-style duplicate is created, e.g. "
                "`Bow_at_Banff_semi_distributed_run_1 (1)` with data under "
                "`domain_Bow_at_Banff_semi_distributed (1)/`."
            )
            if st.button("Create new run folder", key="start_new_assistant_run", width="stretch"):
                err = start_new_assistant_run_from_session()
                if err:
                    st.error(err)
                else:
                    sym_domain = symfluence_domain_for_run_folder(
                        st.session_state.run_folder,
                        symfluence_domain_name(
                            st.session_state.domain_name,
                            st.session_state.experiment_id,
                        ),
                        st.session_state.experiment_id,
                    )
                    st.success(
                        f"Run folder ready: `{st.session_state.run_folder}` "
                        f"(SYMFLUENCE data: `domain_{sym_domain}`)"
                    )
                    st.rerun()

        elif source == "assistant":
            runs = list_assistant_run_folders()
            if not runs:
                st.warning(f"No saved runs found under `{RUNS_DIR}`.")
            else:
                default_idx = runs.index(active_folder) if active_folder in runs else 0
                selected = st.selectbox(
                    "Assistant run folder",
                    options=runs,
                    index=default_idx,
                    key="select_assistant_run_folder",
                )
                if st.button("Load assistant run", key="load_assistant_run_btn", width="stretch"):
                    err = load_assistant_run(selected)
                    if err:
                        st.error(err)
                    else:
                        st.success(f"Loaded run `{selected}`")
                        st.rerun()

        else:
            domains = list_symfluence_data_domains()
            if not domains:
                st.warning(f"No domain_* folders found under `{SYMFLUENCE_DATA_DIR}`.")
            else:
                guess = f"domain_{active_folder}" if active_folder else ""
                default_idx = domains.index(guess) if guess in domains else 0
                selected_domain = st.selectbox(
                    "SYMFLUENCE data domain",
                    options=domains,
                    index=default_idx,
                    key="select_symfluence_data_domain",
                )
                if st.button("Load data domain", key="load_data_domain_btn", width="stretch"):
                    err = load_symfluence_data_domain(selected_domain)
                    if err:
                        st.error(err)
                    else:
                        st.success(f"Loaded `{selected_domain}`")
                        st.rerun()


def is_plan_json_text(text: str) -> bool:
    """True when text looks like a run plan object (not a natural-language prompt)."""
    text = s(text)
    if not text.startswith("{"):
        return False
    try:
        obj = json.loads(text)
    except Exception:
        return False
    return isinstance(obj, dict) and "steps" in obj


def user_prompt_for_metadata() -> str:
    """Return the original NL user prompt, never the JSON plan editor contents."""
    explicit = s(st.session_state.get("user_prompt"))
    if explicit and not is_plan_json_text(explicit):
        return explicit
    nl = s(st.session_state.get("nl_request"))
    if nl and not is_plan_json_text(nl):
        return nl
    return ""


def capture_user_prompt_from_session() -> None:
    """Snapshot the prompt box when generating a plan (before plan JSON can leak in)."""
    nl = s(st.session_state.get("nl_request"))
    if nl and not is_plan_json_text(nl):
        st.session_state.user_prompt = nl


def get_chat_messages() -> list[dict]:
    messages = st.session_state.get("chat_messages")
    return messages if isinstance(messages, list) else []


def conversation_text_for_plan_rules() -> str:
    """Full user intent across the initial prompt and chat follow-ups."""
    parts: list[str] = []
    seen: set[str] = set()
    initial = user_prompt_for_metadata()
    if initial and initial not in seen:
        parts.append(initial)
        seen.add(initial)
    for msg in get_chat_messages():
        if msg.get("role") != "user":
            continue
        text = s(msg.get("content"))
        if text and text not in seen:
            parts.append(text)
            seen.add(text)
    nl = s(st.session_state.get("nl_request"))
    if nl and not is_plan_json_text(nl) and nl not in seen:
        parts.append(nl)
    return "\n\n".join(parts)


def format_chat_history_for_llm(messages: list[dict] | None = None, *, max_turns: int = 12) -> str:
    rows: list[str] = []
    for msg in (messages or get_chat_messages())[-max_turns:]:
        role = msg.get("role", "assistant")
        content = s(msg.get("content"))
        if not content:
            continue
        label = "User" if role == "user" else "Assistant"
        rows.append(f"{label}: {content}")
    return "\n".join(rows)


def build_chat_refinement_context() -> str:
    lines: list[str] = []
    ctx = wx.workflow_context(runs_dir=RUNS_DIR, symfluence_data_dir=SYMFLUENCE_DATA_DIR)
    artifacts = wx.scan_run_artifacts(ctx, symfluence_domain_shapefile_paths())
    if artifacts:
        lines.append("Artifact readiness:")
        for row in artifacts:
            status = row.get("status", "")
            if status == "n/a":
                continue
            label = row.get("artifact", "")
            path = row.get("path", "")
            lines.append(f"  [{status}] {label}: {path}")
    plan = st.session_state.get("run_plan") or {}
    missing = plan.get("needs_user_input") or []
    if missing:
        lines.append("Plan needs_user_input: " + ", ".join(missing))
    log_text = s(st.session_state.get("execution_log_text", ""))
    if log_text:
        tail = log_text[-2500:] if len(log_text) > 2500 else log_text
        lines.extend(["", "Execution log (tail):", tail])
    ui_context = augment_request_with_ui("").strip()
    if ui_context:
        lines.extend(["", "Current UI values:", ui_context])
    return "\n".join(lines).strip()


def summarize_plan_changes(before: dict, after: dict, *, user_message: str = "") -> str:
    return summarize_plan_changes_for_chat(before, after, user_message=user_message)


def save_chat_messages_to_run_folder() -> None:
    run_folder = s(st.session_state.get("run_folder"))
    if not run_folder or run_folder in RUN_FOLDER_SKIP:
        return
    outdir = RUNS_DIR / run_folder
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "chat.json").write_text(
        json.dumps({"messages": get_chat_messages()}, indent=2),
        encoding="utf-8",
    )


def load_chat_messages_from_run_dir(run_dir: Path) -> list[dict]:
    chat_path = run_dir / "chat.json"
    if not chat_path.exists():
        return []
    try:
        data = json.loads(chat_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    messages = data.get("messages") if isinstance(data, dict) else data
    if not isinstance(messages, list):
        return []
    cleaned: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "assistant")
        content = s(msg.get("content"))
        if not content:
            continue
        cleaned.append(
            {
                "role": role if role in ("user", "assistant") else "assistant",
                "content": content,
                "kind": msg.get("kind", "text"),
            }
        )
    return cleaned


def call_llm_refine_run_plan(
    *,
    provider_id: str,
    api_key: str,
    model: str,
    user_message: str,
    current_plan: dict,
    conversation_text: str,
    context_text: str,
) -> tuple[str, dict, bool]:
    if provider_id == "gemini":
        return GeminiProvider(api_key=api_key).refine_run_plan(
            model=model,
            user_message=user_message,
            current_plan=current_plan,
            conversation_text=conversation_text,
            context_text=context_text,
            data_dir=SYMFLUENCE_DATA_DIR,
        )
    if provider_id == "claude":
        return ClaudeProvider(api_key=api_key).refine_run_plan(
            model=model,
            user_message=user_message,
            current_plan=current_plan,
            conversation_text=conversation_text,
            context_text=context_text,
            data_dir=SYMFLUENCE_DATA_DIR,
        )
    return OpenAIProvider(api_key=api_key).refine_run_plan(
        model=model,
        user_message=user_message,
        current_plan=current_plan,
        conversation_text=conversation_text,
        context_text=context_text,
        data_dir=SYMFLUENCE_DATA_DIR,
    )


def refine_plan_from_chat_message(user_text: str) -> None:
    text = s(user_text)
    if not text:
        return
    append_chat_message("user", text)
    if not st.session_state.get("run_plan"):
        append_chat_message(
            "assistant",
            "No plan yet. Open the **Prompt** tab, describe your workflow, and click **Generate plan**.",
            kind="info",
        )
        return

    provider = s(st.session_state.get("llm_provider")) or "openai"
    provider_label = LLM_PROVIDER_LABELS.get(provider, provider)
    key = st.session_state.api_keys.get(provider)
    if not key:
        append_chat_message(
            "assistant",
            f"Save your {provider_label} API key on the **Prompt** tab before refining the plan from chat.",
            kind="info",
        )
        return
    if not llm_provider_available(provider):
        append_chat_message(
            "assistant",
            f"{provider_label} is not available in this Python environment.",
            kind="info",
        )
        return

    current_plan = dict(st.session_state.run_plan)
    conversation_text = conversation_text_for_plan_rules()
    context_text = build_chat_refinement_context()
    model = s(st.session_state.get("llm_model")) or DEFAULT_LLM_MODEL.get(provider, "gpt-5-mini")

    try:
        reply, new_plan, updated = call_llm_refine_run_plan(
            provider_id=provider,
            api_key=key,
            model=model,
            user_message=text,
            current_plan=current_plan,
            conversation_text=conversation_text,
            context_text=context_text,
        )
        if not updated:
            patched = apply_chat_config_edits(dict(current_plan), text)
            patched = apply_chat_step_edits(patched, text)
            plan_cfg_before = (current_plan.get("config") or {})
            plan_cfg_after = (patched.get("config") or {})
            if (
                list(patched.get("steps") or []) != list(current_plan.get("steps") or [])
                or plan_cfg_after != plan_cfg_before
            ):
                new_plan = patched
                updated = True

        if updated:
            new_plan = apply_chat_config_edits(new_plan, text)
            new_plan = apply_chat_step_edits(new_plan, text)
            new_plan = preserve_explicit_config_fields_from_prompt(new_plan, text)
            new_plan = normalize_local_workflow_plan(
                new_plan,
                conversation_text,
                data_dir=SYMFLUENCE_DATA_DIR,
                skip_workflow_step_restore=True,
            )
            diff = summarize_plan_changes(current_plan, new_plan, user_message=text)
            st.session_state.run_plan = new_plan
            st.session_state.pop("_committed_plan_steps", None)
            apply_edited_plan_to_session(new_plan)
            refresh_plan_editor_from_state(force=True, remount=True)
            update_run_plan_needs_user_input()
            sync_mpi_to_run_plan()
            if diff:
                append_chat_message("assistant", diff, kind="diff")
            elif list(new_plan.get("steps") or []) != list(current_plan.get("steps") or []):
                append_chat_message(
                    "assistant",
                    summarize_plan_changes(current_plan, new_plan, user_message=text) or "Plan steps updated.",
                    kind="diff",
                )
        append_chat_message("assistant", reply)
        missing = (st.session_state.run_plan or {}).get("needs_user_input") or []
        if missing:
            append_chat_message(
                "assistant",
                "Still missing before execution: " + ", ".join(missing),
                kind="warning",
            )
        save_chat_messages_to_run_folder()
    except Exception as e:
        append_chat_message(
            "assistant",
            f"I could not update the plan: {e}",
            kind="info",
        )


def append_chat_message(role: str, content: str, *, kind: str = "text") -> None:
    text = s(content)
    if not text:
        return
    messages = get_chat_messages()
    messages.append({"role": role, "content": text, "kind": kind})
    st.session_state.chat_messages = messages


def format_plan_assistant_messages(plan: dict) -> list[dict]:
    steps = plan.get("steps", []) or []
    lines = ["I generated a workflow plan with these steps:", ""]
    lines.extend(f"{i + 1}. `{step}`" for i, step in enumerate(steps))
    notes = s(plan.get("notes"))
    if notes:
        lines.extend(["", f"**Notes:** {notes}"])
    messages = [{"role": "assistant", "content": "\n".join(lines), "kind": "text"}]
    missing = plan.get("needs_user_input", []) or []
    if missing:
        messages.append(
            {
                "role": "assistant",
                "content": (
                    "Some required inputs are still missing: "
                    + ", ".join(missing)
                    + ". Open **Fix missing inputs** under the plan in the Prompt tab."
                ),
                "kind": "warning",
            }
        )
    return messages


def seed_chat_from_generate_plan(user_prompt: str, plan: dict) -> None:
    """Replace chat history when a new plan is generated from the Prompt tab."""
    messages: list[dict] = []
    prompt_text = s(user_prompt)
    if prompt_text:
        messages.append({"role": "user", "content": prompt_text, "kind": "text"})
    messages.extend(format_plan_assistant_messages(plan))
    st.session_state.chat_messages = messages


def clear_chat_messages(*, clear_plan: bool = False) -> None:
    st.session_state.chat_messages = []
    if not clear_plan:
        return
    st.session_state.run_plan = None
    st.session_state.execute_plan = False
    st.session_state.plan_editor_version = int(st.session_state.get("plan_editor_version", 0)) + 1
    st.session_state.pop("_plan_editor_synced", None)
    st.session_state.pop("_pending_plan_editor_text", None)
    st.session_state.pop("_committed_plan_steps", None)


ASSISTANT_PANEL_TABS_KEY = "assistant_panel_tabs"
ASSISTANT_TAB_PROMPT = "Prompt"
ASSISTANT_TAB_CHAT = "Chat"


def request_assistant_chat_tab() -> None:
    """Defer Chat tab focus until before the panel radio renders (widget key is read-only after)."""
    st.session_state["_focus_assistant_chat_tab"] = True


def apply_pending_assistant_panel_tab_focus() -> None:
    if st.session_state.pop("_focus_assistant_chat_tab", False):
        st.session_state[ASSISTANT_PANEL_TABS_KEY] = ASSISTANT_TAB_CHAT


def queue_chat_refinement(message: str) -> None:
    st.session_state["_pending_chat_refinement"] = message
    request_assistant_chat_tab()


def process_pending_chat_refinement() -> None:
    """Run chat plan updates before the Input tab renders so middle-panel widgets stay in sync."""
    pending = st.session_state.pop("_pending_chat_refinement", None)
    if not pending:
        return
    with st.spinner("Updating plan from chat…"):
        refine_plan_from_chat_message(pending)


def render_workflow_chat_tab() -> None:
    chat_count = len(get_chat_messages())
    conv_title = "#### Conversation"
    if chat_count:
        conv_title = f"#### Conversation ({chat_count})"
    st.markdown(conv_title)

    clear_chat_col, clear_all_col = st.columns(2)
    with clear_chat_col:
        if st.button("Clear chat", key="clear_chat_button", width="stretch", type="secondary"):
            clear_chat_messages(clear_plan=False)
            save_chat_messages_to_run_folder()
            st.rerun()
    with clear_all_col:
        if st.button("Clear chat & plan", key="clear_chat_and_plan_button", width="stretch", type="secondary"):
            clear_chat_messages(clear_plan=True)
            save_chat_messages_to_run_folder()
            st.rerun()
    st.caption(
        "**Clear chat** removes message history only. **Clear chat & plan** also removes the run plan on the Prompt tab."
    )

    provider = s(st.session_state.get("llm_provider")) or "openai"
    provider_label = LLM_PROVIDER_LABELS.get(provider, provider)
    if not st.session_state.api_keys.get(provider):
        st.warning(f"Save your {provider_label} API key on the **Prompt** tab to refine the plan from chat.")

    messages = get_chat_messages()
    if not messages:
        st.info(
            "Start on the **Prompt** tab: describe your workflow and click **Generate plan**. "
            "Then ask follow-up questions or request plan changes here."
        )

    for msg in messages:
        role = msg.get("role", "assistant")
        if role not in ("user", "assistant"):
            role = "assistant"
        with st.chat_message(role):
            kind = msg.get("kind", "text")
            content = s(msg.get("content"))
            if kind == "warning":
                st.warning(content)
            elif kind == "info":
                st.info(content)
            elif kind == "diff":
                with st.expander("Plan changes", expanded=False):
                    st.write(content)
            else:
                st.write(content)

    apply_pending_workflow_chat_draft()
    if st.session_state.pop("_chat_transcribe_ok", False):
        st.success("Transcription added to the message box below. Edit if needed, then click **Send**.")
    if st.session_state.pop("_chat_send_empty", False):
        st.warning("Message is empty.")

    chat_disabled = not st.session_state.api_keys.get(provider)
    compose_key = workflow_chat_compose_key()
    compose_value = s(st.session_state.get(compose_key))

    voice_provider, _voice_key = resolve_voice_transcription_provider()
    if voice_provider and st.session_state.get("run_plan"):
        voice_label = VOICE_PROVIDER_LABELS.get(voice_provider, "Voice")
        st.caption(f"**Voice to chat** ({voice_label})")
        if hasattr(st, "audio_input"):
            chat_voice = st.audio_input("Record a chat message", key="voice_chat_message")
        else:
            chat_voice = st.file_uploader(
                "Upload audio for chat",
                type=["wav", "mp3", "m4a", "webm", "mpeg", "mpga"],
                key="voice_chat_upload",
            )
        if st.button(
            "Transcribe to chat",
            key="transcribe_voice_to_chat",
            width="stretch",
            type="secondary",
        ):
            if chat_voice is None:
                st.warning("Record or upload audio first.")
            else:
                transcript = transcribe_voice_to_nl_request(
                    chat_voice.getvalue(),
                    getattr(chat_voice, "name", None) or "recording.webm",
                )
                if transcript:
                    st.session_state["_pending_workflow_chat_draft"] = transcript
                    st.session_state["_chat_transcribe_ok"] = True
                    st.rerun()

    if compose_value:
        with st.form("workflow_chat_compose_form", clear_on_submit=False, border=False):
            compose_text = st.text_area(
                "Message",
                height=88,
                key=compose_key,
                disabled=chat_disabled,
                placeholder="Ask about the plan or request changes…",
            )
            send_col, clear_col = st.columns(2)
            with send_col:
                send_clicked = st.form_submit_button(
                    "Send",
                    disabled=chat_disabled,
                    use_container_width=True,
                )
            with clear_col:
                clear_clicked = st.form_submit_button(
                    "Clear message",
                    disabled=chat_disabled,
                    use_container_width=True,
                )

        if clear_clicked:
            clear_workflow_chat_compose()
            st.rerun()
        elif send_clicked:
            draft_text = s(compose_text)
            if draft_text:
                queue_chat_refinement(draft_text)
                bump_workflow_chat_compose_version()
                st.rerun()
            else:
                st.warning("Message is empty.")
    elif chat_input := st.chat_input(
        "Ask about the plan or request changes…",
        key="workflow_chat_input",
        disabled=chat_disabled,
    ):
        queue_chat_refinement(chat_input)
        st.rerun()


def load_user_prompt_from_run_dir(run_dir: Path, execution_log: str = "") -> str:
    """Load prompt.txt from a run folder, recovering from execution.log if corrupted."""
    prompt_path = run_dir / "prompt.txt"
    if prompt_path.exists():
        raw = prompt_path.read_text(encoding="utf-8").strip()
        if raw and not is_plan_json_text(raw):
            return raw

    marker_start = "===== USER PROMPT ====="
    marker_end = "===== RUN PLAN ====="
    if marker_start in execution_log:
        chunk = execution_log.split(marker_start, 1)[1]
        if marker_end in chunk:
            chunk = chunk.split(marker_end, 1)[0]
        recovered = chunk.strip()
        if recovered and recovered != "(no prompt recorded)" and not is_plan_json_text(recovered):
            return recovered
    return ""


def write_run_metadata_files(outdir: Path, plan: dict, spec_dict: dict | None = None) -> None:
    """Persist plan.json (and optional spec.json) under runs/<domain>_<experiment>/."""
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "plan.json").write_text(
        json.dumps(plan or {}, indent=2),
        encoding="utf-8",
    )
    prompt = user_prompt_for_metadata()
    if prompt:
        (outdir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    chat_messages = get_chat_messages()
    if chat_messages:
        (outdir / "chat.json").write_text(
            json.dumps({"messages": chat_messages}, indent=2),
            encoding="utf-8",
        )
    if spec_dict is not None:
        (outdir / "spec.json").write_text(
            json.dumps(spec_dict, indent=2),
            encoding="utf-8",
        )


def mirror_preview_plan_to_run_folder(plan: dict, spec_dict: dict | None = None) -> None:
    """Copy the current plan into the active run folder when domain + experiment are set."""
    run_folder = s(st.session_state.get("run_folder"))
    if not run_folder or run_folder in RUN_FOLDER_SKIP:
        return
    write_run_metadata_files(RUNS_DIR / run_folder, plan, spec_dict)


def build_real_run_files_from_state() -> tuple[Path, Path, dict, dict]:
    plan_cfg_local = (st.session_state.run_plan or {}).get("config", {}) or {}
    real_spec_dict = build_spec_dict(plan_cfg_local)

    current_pour_local = (
        s(st.session_state.selected_pour_point)
        or s(plan_cfg_local.get("pour_point_coords"))
    )

    current_bbox_local = (
        s(st.session_state.selected_bounding_box)
        or s(st.session_state.bounding_box_input)
        or s(plan_cfg_local.get("bounding_box_coords"))
    )

    if current_pour_local:
        real_spec_dict["pour_point_coords"] = current_pour_local
    else:
        real_spec_dict.pop("pour_point_coords", None)

    if current_bbox_local:
        real_spec_dict["bounding_box_coords"] = current_bbox_local
    else:
        real_spec_dict.pop("bounding_box_coords", None)

    finalize_spec_for_symfluence(real_spec_dict)
    real_spec_dict["force_rerun"] = True

    real_outdir = RUNS_DIR / st.session_state.run_folder
    real_outdir.mkdir(parents=True, exist_ok=True)
    real_out_yaml = real_outdir / "config.yaml"
    render_config_from_spec(real_spec_dict, TEMPLATE_PATH, real_out_yaml)

    real_cfg = load_yaml(real_out_yaml)
    real_cfg = clean_cfg_for_safe_run(real_cfg)
    real_cfg = reapply_spec_overrides(real_cfg, real_spec_dict)

    current_model_local = current_hydrological_model(plan_cfg_local)
    if current_model_local:
        real_cfg["HYDROLOGICAL_MODEL"] = current_model_local
    else:
        real_cfg.pop("HYDROLOGICAL_MODEL", None)

    if current_pour_local:
        real_cfg["POUR_POINT_COORDS"] = current_pour_local
    else:
        real_cfg.pop("POUR_POINT_COORDS", None)

    if current_bbox_local:
        real_cfg["BOUNDING_BOX_COORDS"] = current_bbox_local
    else:
        real_cfg.pop("BOUNDING_BOX_COORDS", None)

    dump_yaml(real_cfg, real_out_yaml)

    write_run_metadata_files(
        real_outdir,
        st.session_state.run_plan or {},
        real_spec_dict,
    )

    return real_outdir, real_out_yaml, real_cfg, real_spec_dict


def append_session_execution_log(chunk: str) -> None:
    prev = st.session_state.get("execution_log_text", "") or ""
    st.session_state.execution_log_text = prev + chunk


def manual_execution_log_path(outdir: Path) -> Path:
    logs_dir = outdir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "execution.log"


def execution_log_preamble(plan: dict | None = None) -> str:
    """Header for execution.log: user prompt first, then resolved run plan."""
    parts: list[str] = []
    prompt = user_prompt_for_metadata()
    if prompt:
        parts.append("===== USER PROMPT =====\n")
        parts.append(prompt)
        parts.append("\n\n")
    else:
        parts.append("===== USER PROMPT =====\n(no prompt recorded)\n\n")

    parts.append("===== RUN PLAN =====\n")
    parts.append(json.dumps(plan or st.session_state.run_plan or {}, indent=2))
    parts.append("\n")
    return "".join(parts)


def ensure_execution_log_preamble(log_path: Path, plan: dict | None = None) -> None:
    """Write prompt + plan header when starting a new log (manual steps, validate-only)."""
    if log_path.exists() and log_path.stat().st_size > 0:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    text = execution_log_preamble(plan)
    log_path.write_text(text, encoding="utf-8")
    st.session_state.execution_log_text = text


def execute_validate_config_step(output_box) -> tuple[int, str]:
    outdir, out_yaml, manual_cfg, _ = build_real_run_files_from_state()
    log_path = manual_execution_log_path(outdir)
    ensure_execution_log_preamble(log_path)
    header = "\n===== STEP: validate_config =====\n"
    append_session_execution_log(header)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(header)
    try:
        validate_spec(manual_cfg)
        msg = f"Internal validation OK ✅\nValidated config: {out_yaml}\n"
        rc = 0
    except Exception as e:
        msg = f"Internal validation FAILED ❌: {e}\n"
        rc = 1
    append_session_execution_log(msg)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(msg)
    if output_box is not None:
        output_box.code(st.session_state.execution_log_text)
    return rc, msg


def execute_single_symfluence_step(step: str, output_box) -> tuple[int, str]:
    if step in DANGER_STEPS and not st.session_state.allow_run:
        return 1, "Enable **Allow dangerous run steps** in the assistant panel first."

    if step not in SUPPORTED_STEPS:
        return 1, f"Unsupported step: {step}"

    if step not in DANGER_STEPS and step != "dry_run" and not PROVEN_STATUS.get(step, False):
        return 1, f"Step '{step}' is not marked proven in the assistant yet."

    outdir, out_yaml, _, _ = build_real_run_files_from_state()
    log_path = manual_execution_log_path(outdir)
    ensure_execution_log_preamble(log_path)
    cmd = build_symfluence_step_cmd(step, out_yaml)
    header = f"\n===== STEP: {step} =====\n$ {' '.join(cmd)}\n\n"
    append_session_execution_log(header)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"\n===== STEP: {step} =====\n")
        f.write("$ " + " ".join(cmd) + "\n\n")

    rc, out = run_cmd_stream(cmd, SYMFLUENCE_REPO, output_box, log_path=log_path)
    footer = f"\n[STEP {step}] return code: {rc}\n"
    append_session_execution_log(out + footer)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(footer)
    return rc, out + footer


def execute_step_bundle(bundle_key: str, output_box) -> bool:
    """Run a named step bundle; returns True if all steps succeeded."""
    steps = wx.RUN_STEP_BUNDLES.get(bundle_key, [])
    if not steps:
        st.error(f"Unknown shortcut bundle: {bundle_key}")
        return False
    if bundle_key in ("model", "postprocess") and not st.session_state.allow_run:
        st.error("Enable **Allow dangerous run steps** in the assistant panel first.")
        return False

    ok = True
    for step in steps:
        with st.spinner(f"Running {step}…"):
            if step == "validate_config":
                rc, _ = execute_validate_config_step(output_box)
            else:
                rc, _ = execute_single_symfluence_step(step, output_box)
        if rc != 0:
            ok = False
            st.error(f"Bundle stopped at {step} (return code {rc}).")
            break
    if ok:
        st.success(f"Shortcut bundle '{bundle_key}' completed.")
    return ok


def render_run_single_steps_section() -> None:
    with st.expander("Run single step", expanded=False):
        st.caption(
            "Run one workflow step with the current Input fields and plan. "
            "Command output is shown here and on the **Output** tab."
        )
        step_output = st.empty()

        quick1, quick2 = st.columns(2)
        with quick1:
            if st.button("Validate config", key="input_single_validate", width="stretch"):
                with st.spinner("Validating…"):
                    rc, msg = execute_validate_config_step(step_output)
                if rc == 0:
                    st.success("Validation passed.")
                else:
                    st.error("Validation failed.")
        with quick2:
            if st.button("Dry run (setup)", key="input_single_dry_run", width="stretch"):
                with st.spinner("Dry run…"):
                    rc, msg = execute_single_symfluence_step("dry_run", step_output)
                if rc == 0:
                    st.success("Dry run completed.")
                else:
                    st.error(f"Dry run failed (return code {rc}).")

        proven_steps = [
            (step, label)
            for step, label in WORKFLOW_DISPLAY_ORDER
            if PROVEN_STATUS.get(step, False)
        ]
        if proven_steps:
            st.markdown("**Proven workflow steps**")
            cols = st.columns(3)
            for i, (step, label) in enumerate(proven_steps):
                with cols[i % 3]:
                    if st.button(
                        f"Run {label}",
                        key=f"input_single_{step}",
                        width="stretch",
                    ):
                        with st.spinner(f"Running {label}…"):
                            rc, _ = execute_single_symfluence_step(step, step_output)
                        if rc == 0:
                            st.success(f"{label} completed.")
                        else:
                            st.error(f"{label} failed (return code {rc}).")

        st.markdown("**Dangerous steps**")
        if not st.session_state.allow_run:
            st.caption("Enable **Allow dangerous run steps** in the assistant panel to run model or calibration.")
        danger_cols = st.columns(2)
        with danger_cols[0]:
            if st.button(
                "Run model",
                key="input_single_run_model",
                width="stretch",
                disabled=not st.session_state.allow_run,
            ):
                with st.spinner("Running model…"):
                    rc, _ = execute_single_symfluence_step("run_model", step_output)
                if rc == 0:
                    st.success("Model run completed.")
                else:
                    st.error(f"Model run failed (return code {rc}).")
        with danger_cols[1]:
            if st.button(
                "Calibrate model",
                key="input_single_calibrate_model",
                width="stretch",
                disabled=not st.session_state.allow_run,
            ):
                with st.spinner("Calibrating…"):
                    rc, _ = execute_single_symfluence_step("calibrate_model", step_output)
                if rc == 0:
                    st.success("Calibration completed.")
                else:
                    st.error(f"Calibration failed (return code {rc}).")

        unproven_labels = [
            label
            for step, label in WORKFLOW_DISPLAY_ORDER
            if step in SUPPORTED_STEPS
            and not PROVEN_STATUS.get(step, False)
            and step not in DANGER_STEPS
        ]
        if unproven_labels:
            st.caption(
                "Not available here yet: "
                + ", ".join(unproven_labels)
                + ". Use **Plan steps** or **Execute plan** when those steps are in your plan."
            )


def render_workflow_input_tab() -> None:
    st.markdown('<div class="card"><div class="card-title">Workflow Settings</div><div class="card-subtitle">Configure parameters for your hydrology workflow.</div>', unsafe_allow_html=True)

    render_start_load_run_section()
    
    start_dt = parse_datetime_value(st.session_state.tstart, dt.datetime(2001, 1, 1, 1, 0))
    end_dt = parse_datetime_value(st.session_state.tend, dt.datetime(2001, 1, 10, 23, 0))
    
    ws1, ws2, ws3 = st.columns(3)
    with ws1:
        st.session_state.domain_name = st.text_input(
            "Domain name",
            st.session_state.domain_name,
            key=input_panel_widget_key("input_domain_name"),
        )
    with ws2:
        st.session_state.experiment_id = st.text_input(
            "Experiment ID",
            st.session_state.experiment_id,
            key=input_panel_widget_key("input_experiment_id"),
        )
    with ws3:
        st.session_state.run_folder = st.text_input(
            "Run folder name",
            st.session_state.run_folder,
            help="Usually domain_experiment. Updated when you start or load a run above.",
            key=input_panel_widget_key("input_run_folder"),
        )
            
    
    ws4, ws5, ws6 = st.columns(3)
    with ws4:
        hydro_value = coerce_selectbox_value(
            st.session_state.hydrological_model,
            HYDROLOGICAL_MODEL_OPTIONS,
            normalizer=normalize_hydrological_model,
        )
        st.session_state.hydrological_model = st.selectbox(
            "Hydrological model",
            options=HYDROLOGICAL_MODEL_OPTIONS,
            index=HYDROLOGICAL_MODEL_OPTIONS.index(hydro_value),
            help="Leave blank if the model should come only from the prompt/plan.",
            key=input_panel_widget_key("input_hydrological_model"),
        )
    with ws5:
        domain_value = coerce_selectbox_value(st.session_state.domain_def, DOMAIN_DEF_OPTIONS)
        st.session_state.domain_def = st.selectbox(
            "Domain definition",
            options=DOMAIN_DEF_OPTIONS,
            index=DOMAIN_DEF_OPTIONS.index(domain_value),
            help="How the spatial domain should be defined.",
            key=input_panel_widget_key("input_domain_def"),
        )
    with ws6:
        forcing_value = coerce_selectbox_value(
            st.session_state.forcing_dataset,
            FORCING_DATASET_OPTIONS,
            normalizer=normalize_forcing_dataset,
        )
        st.session_state.forcing_dataset = st.selectbox(
            "Forcing dataset",
            options=FORCING_DATASET_OPTIONS,
            index=FORCING_DATASET_OPTIONS.index(forcing_value),
            help="Must match a SYMFLUENCE FORCING_DATASET value.",
            key=input_panel_widget_key("input_forcing_dataset"),
        )
    
    ws7, ws8, ws9 = st.columns(3)
    with ws7:
        st.session_state.mpi = st.number_input(
            "NUM_PROCESSES",
            1,
            128,
            int(st.session_state.mpi),
            key=mpi_widget_key(),
        )
        sync_mpi_to_run_plan()
    with ws8:
        start_date = st.date_input(
            "Start date",
            value=start_dt.date(),
            key=experiment_datetime_widget_key("experiment_start_date"),
        )
        start_time = st.time_input(
            "Start time",
            value=start_dt.time().replace(second=0, microsecond=0),
            key=experiment_datetime_widget_key("experiment_start_time"),
        )
        st.session_state.tstart = format_datetime_value(start_date, start_time)
    with ws9:
        end_date = st.date_input(
            "End date",
            value=end_dt.date(),
            key=experiment_datetime_widget_key("experiment_end_date"),
        )
        end_time = st.time_input(
            "End time",
            value=end_dt.time().replace(second=0, microsecond=0),
            key=experiment_datetime_widget_key("experiment_end_time"),
        )
        st.session_state.tend = format_datetime_value(end_date, end_time)
    
    st.caption(f"Experiment time window: `{st.session_state.tstart}` → `{st.session_state.tend}`")
    wx.render_advanced_config_section()
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown(
        '<div class="card"><div class="card-title">Map & Spatial Inputs</div>'
        '<div class="card-subtitle">Select a pour point or bounding box; overlay review layers when shapefiles exist.</div>',
        unsafe_allow_html=True,
    )
    
    st.session_state.map_mode = st.radio(
        "Map click mode",
        options=["pour_point", "bounding_box"],
        format_func=lambda x: "Pour point" if x == "pour_point" else "Bounding box",
        horizontal=True,
    )

    with st.expander("Review layers", expanded=False):
        st.caption(
            "Inspect delineation outputs on this map. Layers are enabled only when the shapefile exists under "
            f"`{SYMFLUENCE_DATA_DIR}/domain_<name>_<experiment>/`."
        )
        available = render_map_layer_checkboxes("in")
        if available == 0 and symfluence_domain_shapefile_paths():
            st.caption("No review shapefiles found yet. Run workflow steps such as define_domain or discretize_domain first.")

    map_obj = build_pour_point_map(
        show_dem_layer=st.session_state.show_dem_layer,
        show_landclass_layer=st.session_state.show_landclass_layer,
        show_soilclass_layer=st.session_state.show_soilclass_layer,
        show_riverbasins_layer=st.session_state.show_riverbasins_layer,
        show_hrugru_layer=st.session_state.show_hrugru_layer,
        show_forcing_layer=st.session_state.show_forcing_layer,
        show_rivernetwork_layer=st.session_state.show_rivernetwork_layer,
    )
    map_data = st_folium(map_obj, width=900, height=430, key="input_selection_map")
    
    if map_data and map_data.get("last_clicked"):
        clicked = map_data["last_clicked"]
        lat = clicked["lat"]
        lon = clicked["lng"]
    
        if is_new_map_click(lat, lon):
            if st.session_state.map_mode == "pour_point":
                current = format_pour_point(lat, lon)
                if s(st.session_state.selected_pour_point) != current:
                    set_pour_point_from_map(lat, lon)
                    st.rerun()
            elif st.session_state.map_mode == "bounding_box":
                p1 = st.session_state.bbox_point_1
                if p1 is None:
                    st.session_state.bbox_point_1 = (lat, lon)
                    st.session_state.bbox_point_2 = None
                    st.session_state.bbox_selected = False
                    sync_spatial_fields_to_run_plan(refresh_editor=True)
                    st.rerun()
                elif not st.session_state.bbox_selected:
                    lat1, lon1 = st.session_state.bbox_point_1
                    set_bounding_box_from_points(lat1, lon1, lat, lon)
                    st.rerun()
                else:
                    st.session_state.bbox_point_1 = (lat, lon)
                    st.session_state.bbox_point_2 = None
                    st.session_state.bbox_selected = False
                    st.session_state.selected_bounding_box = ""
                    mark_spatial_inputs_stale()
                    st.rerun()

    clear_a, clear_b = st.columns(2)
    with clear_a:
        if st.button("Clear pour point", key="clear_selected_pour_point"):
            st.session_state.map_lat = None
            st.session_state.map_lon = None
            st.session_state.map_point_selected = False
            st.session_state.selected_pour_point = ""
            st.session_state.last_map_click = None
            mark_spatial_inputs_stale()
            sync_spatial_fields_to_run_plan(refresh_editor=True)
            st.rerun()
    with clear_b:
        if st.button("Clear bounding box", key="clear_selected_bbox"):
            st.session_state.bbox_point_1 = None
            st.session_state.bbox_point_2 = None
            st.session_state.bbox_selected = False
            st.session_state.selected_bounding_box = ""
            st.session_state.last_map_click = None
            mark_spatial_inputs_stale()
            sync_spatial_fields_to_run_plan(refresh_editor=True)
            st.rerun()

    status_col1, status_col2 = st.columns(2)
    with status_col1:
        if st.session_state.map_point_selected:
            st.success(f"Selected pour point: {s(st.session_state.selected_pour_point)}")
            st.caption(f"Latitude: {st.session_state.map_lat:.7f} | Longitude: {st.session_state.map_lon:.7f}")
        elif st.session_state.bbox_point_1 and not st.session_state.bbox_selected:
            lat1, lon1 = st.session_state.bbox_point_1
            st.info(f"Bounding box corner 1: {lat1:.7f}, {lon1:.7f}")
    with status_col2:
        if st.session_state.bbox_selected:
            st.success(f"Selected bounding box: {s(st.session_state.selected_bounding_box)}")
        elif st.session_state.map_mode == "bounding_box":
            st.caption("Bounding box mode: click first corner, then opposite corner.")
    
    if st.session_state.refresh_spatial_inputs:
        mark_spatial_inputs_stale()
        st.session_state.refresh_spatial_inputs = False
    refresh_spatial_input_widgets()

    st.text_input(
        "Pour point (lat/lon)",
        key="pour_point_input",
        on_change=on_pour_point_input_change,
    )
    st.text_input(
        "Bounding box (north/west/south/east)",
        key="bounding_box_input",
        on_change=on_bounding_box_input_change,
    )

    sync_input_panel_to_run_plan()
    render_run_single_steps_section()
    shortcut_output = st.empty()
    wx.render_run_shortcuts_section(
        execute_bundle_fn=lambda key: execute_step_bundle(key, shortcut_output),
        location="input",
    )
    st.markdown('</div>', unsafe_allow_html=True)


def sync_preview_artifacts() -> None:
    global cfg, preview_yaml, spec_dict

    plan_cfg = effective_plan_config_for_preview()
    spec_dict = build_spec_dict(plan_cfg)
    
    current_pour = (
        s(st.session_state.selected_pour_point)
        or s(plan_cfg.get("pour_point_coords"))
    )
    
    current_bbox = (
        s(st.session_state.selected_bounding_box)
        or s(st.session_state.bounding_box_input)
        or s(plan_cfg.get("bounding_box_coords"))
    )
    
    if current_pour:
        spec_dict["pour_point_coords"] = current_pour
    else:
        spec_dict.pop("pour_point_coords", None)
    
    if current_bbox:
        spec_dict["bounding_box_coords"] = current_bbox
    else:
        spec_dict.pop("bounding_box_coords", None)
    
    finalize_spec_for_symfluence(spec_dict)
    spec_dict["force_rerun"] = True
    
    preview_dir = PREVIEW_DIR
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_yaml = preview_dir / "config_preview.yaml"
    render_config_from_spec(spec_dict, TEMPLATE_PATH, preview_yaml)
    
    cfg = load_yaml(preview_yaml)
    cfg = clean_cfg_for_safe_run(cfg)
    cfg = reapply_spec_overrides(cfg, spec_dict)
    
    current_model = current_hydrological_model(plan_cfg)
    if current_model:
        cfg["HYDROLOGICAL_MODEL"] = current_model
    else:
        cfg.pop("HYDROLOGICAL_MODEL", None)
    
    current_pour = (
        s(st.session_state.selected_pour_point)
        or s(plan_cfg.get("pour_point_coords"))
    )
    
    current_bbox = (
        s(st.session_state.selected_bounding_box)
        or s(st.session_state.bounding_box_input)
        or s(plan_cfg.get("bounding_box_coords"))
    )
    
    if current_pour:
        cfg["POUR_POINT_COORDS"] = current_pour
    else:
        cfg.pop("POUR_POINT_COORDS", None)
    
    if current_bbox:
        cfg["BOUNDING_BOX_COORDS"] = current_bbox
    else:
        cfg.pop("BOUNDING_BOX_COORDS", None)
    
    dump_yaml(cfg, preview_yaml)

    update_run_plan_needs_user_input()

    preview_plan_json = preview_dir / "plan_preview.json"
    plan_to_save = json.loads(json.dumps(st.session_state.run_plan or {}))
    plan_to_save.setdefault("config", {})
    
    if s(st.session_state.domain_name):
        plan_to_save["config"]["domain_name"] = s(st.session_state.domain_name)
    if s(st.session_state.experiment_id):
        plan_to_save["config"]["experiment_id"] = s(st.session_state.experiment_id)
    
    effective_model = current_hydrological_model((st.session_state.run_plan or {}).get("config", {}) or {})
    if effective_model:
        plan_to_save["config"]["hydrological_model"] = effective_model
    elif "hydrological_model" in plan_to_save["config"]:
        plan_to_save["config"].pop("hydrological_model", None)
    
    effective_pour = (
        s(st.session_state.selected_pour_point)
        or s((st.session_state.run_plan or {}).get("config", {}).get("pour_point_coords"))
        or ""
    )
    if effective_pour:
        plan_to_save["config"]["pour_point_coords"] = effective_pour
    elif "pour_point_coords" in plan_to_save["config"]:
        plan_to_save["config"].pop("pour_point_coords", None)
    
    if s(st.session_state.domain_def):
        plan_to_save["config"]["domain_def"] = s(st.session_state.domain_def)
    if s(st.session_state.forcing_dataset):
        plan_to_save["config"]["forcing_dataset"] = s(st.session_state.forcing_dataset)
    if s(st.session_state.tstart):
        plan_to_save["config"]["experiment_time_start"] = s(st.session_state.tstart)
    if s(st.session_state.tend):
        plan_to_save["config"]["experiment_time_end"] = s(st.session_state.tend)

    mpi_val = resolve_num_processes_from_plan_cfg(plan_to_save.get("config") or {}) or int(
        st.session_state.mpi
    )
    plan_to_save["config"]["NUM_PROCESSES"] = mpi_val
    plan_to_save["config"]["num_processes"] = mpi_val
    
    effective_bbox = (
        s(st.session_state.selected_bounding_box)
        or s(st.session_state.bounding_box_input)
        or s((st.session_state.run_plan or {}).get("config", {}).get("bounding_box_coords"))
    )
    
    if effective_bbox:
        plan_to_save["config"]["bounding_box_coords"] = effective_bbox
    elif "bounding_box_coords" in plan_to_save["config"]:
        plan_to_save["config"].pop("bounding_box_coords", None)
    
    with open(preview_plan_json, "w", encoding="utf-8") as f:
        json.dump(plan_to_save, f, indent=2)

    if st.session_state.get("run_plan"):
        mirror_preview_plan_to_run_folder(plan_to_save, spec_dict)


def render_workflow_output_tab() -> None:
    global output_box, progress_box, validate_btn, dryrun_btn, setup_btn, run_btn

    st.subheader("Generated config.yaml")
    st.text_area(
        "Generated config preview",
        value=yaml.safe_dump(cfg, sort_keys=False),
        height=320,
        disabled=True,
        label_visibility="collapsed",
        key=config_preview_widget_key(),
    )
    st.caption(f"Preview only: {preview_yaml}")

    wx.render_run_results_section(
        cfg=cfg,
        runs_dir=RUNS_DIR,
        symfluence_data_dir=SYMFLUENCE_DATA_DIR,
        layer_paths_fn=symfluence_domain_shapefile_paths,
        default_postprocess_domain_dir_fn=default_postprocess_domain_dir,
        run_py_tool_fn=run_py_tool,
    )
    
    with st.expander("Output map layers", expanded=False):
        st.caption("Same review layers as the Input tab. Toggles stay in sync between tabs.")
        render_map_layer_checkboxes("out")

        output_map = build_pour_point_map(
            show_dem_layer=st.session_state.show_dem_layer,
            show_landclass_layer=st.session_state.show_landclass_layer,
            show_soilclass_layer=st.session_state.show_soilclass_layer,
            show_riverbasins_layer=st.session_state.show_riverbasins_layer,
            show_hrugru_layer=st.session_state.show_hrugru_layer,
            show_forcing_layer=st.session_state.show_forcing_layer,
            show_rivernetwork_layer=st.session_state.show_rivernetwork_layer,
        )
        st_folium(output_map, width=900, height=360, key="output_layers_map")

    with st.expander("Advanced", expanded=False):
        st.markdown("**Manual SYMFLUENCE steps**")
        st.caption(
            "Run individual steps without executing the full plan from the assistant panel. "
            "Results appear in Command output below. For normal use, prefer **Execute plan**."
        )
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            validate_btn = st.button("Internal Validate", key="manual_validate", width="stretch")
        with m2:
            dryrun_btn = st.button("Dry Run setup", key="manual_dryrun", width="stretch")
        with m3:
            setup_btn = st.button("Setup Project", key="manual_setup", width="stretch")
        with m4:
            run_btn = st.button(
                "Run Model Only",
                disabled=not st.session_state.allow_run,
                key="manual_run_model",
                width="stretch",
            )
        if not st.session_state.allow_run:
            st.caption("Enable **Allow dangerous run steps** in the assistant panel to use Run Model Only.")

        st.caption("Routed discharge extract/summarize and hydrograph metrics are in **Run results** above.")

    st.subheader("Workflow progress")
    progress_box = st.empty()
    if st.session_state.get("run_plan"):
        progress_box.markdown(render_workflow_progress(st.session_state.run_plan, st.session_state.get("execution_log_text", "")))
    
    st.subheader("Command output")
    output_box = st.empty()
    if st.session_state.get("execution_log_text"):
        output_box.code(st.session_state.execution_log_text)


# -----------------------------------------------------------------------------
# Workflows layout: main Input/Output tabs + right Prompt/Chat panel
# -----------------------------------------------------------------------------
# Integer height enables Streamlit scroll regions; CSS sizes them to the viewport.
WORKFLOW_PANEL_HEIGHT = 720

# Sidebar pages (non-Workflows) — after helper definitions so callbacks exist.
if current_page != "Workflows":
    st.subheader(current_page)
    if current_page == "Dashboard":
        wx.render_dashboard_page(
            runs_dir=RUNS_DIR,
            symfluence_repo=SYMFLUENCE_REPO,
            symfluence_data_dir=SYMFLUENCE_DATA_DIR,
            symfluence_python=SYMFLUENCE_PYTHON,
            render_workflow_progress_fn=render_workflow_progress,
            run_folder_skip=RUN_FOLDER_SKIP,
        )
    elif current_page == "Data":
        wx.render_data_page(
            runs_dir=RUNS_DIR,
            symfluence_data_dir=SYMFLUENCE_DATA_DIR,
            layer_paths_fn=symfluence_domain_shapefile_paths,
        )
    elif current_page == "Logs":
        wx.render_logs_page(runs_dir=RUNS_DIR, run_folder_skip=RUN_FOLDER_SKIP)
    elif current_page == "Experiments":
        exp_cal_out = st.empty()

        def _experiments_run_calibrate(output_box=exp_cal_out):
            if not st.session_state.allow_run:
                st.error("Enable **Allow dangerous run steps** first.")
                return
            with st.spinner("Running calibration…"):
                rc, _ = execute_single_symfluence_step("calibrate_model", output_box)
            if rc == 0:
                st.success("Calibration step finished.")
            else:
                st.error(f"Calibration failed (return code {rc}).")

        wx.render_experiments_page(
            runs_dir=RUNS_DIR,
            run_folder_skip=RUN_FOLDER_SKIP,
            load_run_fn=load_assistant_run,
            execute_calibrate_fn=_experiments_run_calibrate,
        )
    elif current_page == "Results":
        wx.render_results_page(
            symfluence_data_dir=SYMFLUENCE_DATA_DIR,
            runs_dir=RUNS_DIR,
        )
    elif current_page == "Settings":
        st.info("Local path settings are available in the left sidebar. API-key settings are on the Workflows page.")
    else:
        st.info(f"The {current_page} page is reserved for the next UI iteration.")
    st.stop()

st.markdown('<div class="sym-workflow-panels" aria-hidden="true"></div>', unsafe_allow_html=True)
process_pending_chat_refinement()
main_col, assistant_col = st.columns([0.72, 0.28], gap="large")

with main_col.container(height=WORKFLOW_PANEL_HEIGHT, border=False):
    st.markdown('<span class="sym-main-panel" aria-hidden="true"></span>', unsafe_allow_html=True)
    pending_load = st.session_state.pop("_pending_load_run", None)
    if pending_load:
        load_err = load_assistant_run(pending_load)
        if load_err:
            st.error(load_err)
        else:
            st.success(f"Loaded run `{pending_load}` from Experiments page.")

    input_tab, output_tab = st.tabs(["✎ Input", "▣ Output"])
    with input_tab:
        render_workflow_input_tab()
    sync_preview_artifacts()
    with output_tab:
        render_workflow_output_tab()

with assistant_col.container(height=WORKFLOW_PANEL_HEIGHT, border=False):
    st.markdown(
        '<span class="sym-assistant-panel" aria-hidden="true"></span><div class="right-panel">',
        unsafe_allow_html=True,
    )
    render_workflow_panel_dom_hooks()
    apply_pending_assistant_panel_tab_focus()
    capture_plan_editor_draft()
    st.radio(
        "Assistant panel",
        options=[ASSISTANT_TAB_PROMPT, ASSISTANT_TAB_CHAT],
        key=ASSISTANT_PANEL_TABS_KEY,
        horizontal=True,
        label_visibility="collapsed",
    )
    on_prompt_tab = st.session_state.get(ASSISTANT_PANEL_TABS_KEY, ASSISTANT_TAB_PROMPT) != ASSISTANT_TAB_CHAT
    plan_text_holder = ""

    if not on_prompt_tab:
        if st.session_state.get("run_plan") is not None:
            plan_text_holder = render_persistent_plan_editor(visible=False)
        render_workflow_chat_tab()
    else:
        st.markdown("#### LLM Assistant")

        if not FORCINGS_AVAILABLE:
            st.warning("Local install: acquire_forcings is disabled. Use HPC/MAF or provide external forcings.")

        persistent_cfg = load_persistent_config()
        for _provider in ("openai", "gemini", "claude"):
            _cfg_key = persistent_cfg.get(f"{_provider}_api_key")
            if _cfg_key and not st.session_state.api_keys.get(_provider):
                st.session_state.api_keys[_provider] = _cfg_key

        provider_labels = list(LLM_PROVIDER_BY_LABEL.keys())
        current_provider = s(st.session_state.get("llm_provider")) or "openai"
        if current_provider not in LLM_PROVIDER_LABELS:
            current_provider = "openai"
            st.session_state.llm_provider = current_provider
        current_provider_label = LLM_PROVIDER_LABELS[current_provider]
        selected_provider_label = st.selectbox(
            "Provider",
            provider_labels,
            index=provider_labels.index(current_provider_label),
            key="provider_select",
        )
        st.session_state.llm_provider = LLM_PROVIDER_BY_LABEL[selected_provider_label]
        active_provider = st.session_state.llm_provider
        active_provider_label = LLM_PROVIDER_LABELS[active_provider]

        if st.session_state.api_keys.get(active_provider):
            st.success(f"{active_provider_label} API key loaded ✔")
        else:
            st.warning(f"No {active_provider_label} API key loaded")

        api_key_help = {
            "openai": "OpenAI API key.",
            "gemini": "Google AI Studio / Gemini API key.",
            "claude": "Anthropic API key from console.anthropic.com.",
        }.get(active_provider, "LLM API key.")
        api_key = st.text_input(
            "Your API key",
            type="password",
            help=f"Stored only if you click Save key. {api_key_help}",
        )

        if st.button("Save key", key="save_openai_key", width="stretch", type="secondary"):
            if api_key.strip():
                st.session_state.api_keys[active_provider] = api_key.strip()
                cfg_local = load_local_settings()
                cfg_local[f"{active_provider}_api_key"] = api_key.strip()
                save_local_settings(cfg_local)
                st.success("API key saved on this machine.")
            else:
                st.error("API key is empty.")

        if not llm_provider_available(active_provider):
            st.error(
                f"{active_provider_label} provider not available. "
                "Install the required SDK package in the same Python that runs Streamlit."
            )
            import_error = llm_provider_import_error(active_provider)
            if import_error:
                st.code(import_error)
            st.markdown(llm_provider_install_hint(active_provider))
        else:
            available_models = llm_models_for_provider(active_provider)
            current_model = (
                s(st.session_state.get("llm_model"))
                or s(st.session_state.get("gpt_model"))
                or DEFAULT_LLM_MODEL.get(active_provider, available_models[0])
            )
            if current_model not in available_models:
                current_model = DEFAULT_LLM_MODEL.get(active_provider, available_models[0])
            st.session_state.llm_model = st.selectbox(
                "Model",
                available_models,
                index=available_models.index(current_model),
                format_func=lambda model_id: llm_model_label(model_id, active_provider),
            )
            st.session_state.gpt_model = st.session_state.llm_model

            apply_pending_nl_request_transcript()
            if st.session_state.pop("_nl_transcribe_ok", False):
                st.success("Transcription added. Review the prompt, then click Generate plan.")
            def _render_prompt_body() -> None:
                st.text_area(
                    "Describe what you want",
                    height=210,
                    key="nl_request",
                    placeholder="Example: Create a safe point-domain SUMMA workflow for Paradise SNOTEL...",
                    label_visibility="collapsed",
                )

            render_editable_block_with_copy(
                "Describe what you want",
                anchor_id="sym_copy_anchor_nl_request",
                copy_key="copy_nl_prompt",
                fallback_text=s(st.session_state.get("nl_request", "")),
                render_body=_render_prompt_body,
            )

            voice_provider, _voice_key = resolve_voice_transcription_provider()
            if voice_provider:
                voice_label = VOICE_PROVIDER_LABELS.get(voice_provider, "Voice")
                st.markdown(f"**Voice input** ({voice_label} → prompt box)")
                if voice_provider != active_provider:
                    st.caption(
                        f"Speech-to-text uses **{LLM_PROVIDER_LABELS[voice_provider]}** "
                        f"(planner is **{active_provider_label}**)."
                    )
                if hasattr(st, "audio_input"):
                    voice_audio = st.audio_input(
                        "Record your request",
                        key="voice_nl_request",
                        help="Record audio, then click Transcribe to prompt.",
                    )
                else:
                    voice_audio = st.file_uploader(
                        "Upload audio (wav, mp3, m4a, webm)",
                        type=["wav", "mp3", "m4a", "webm", "mpeg", "mpga"],
                        key="voice_nl_upload",
                    )

                if st.button(
                    "Transcribe to prompt",
                    key="transcribe_voice_to_prompt",
                    width="stretch",
                    type="secondary",
                ):
                    if voice_audio is None:
                        st.warning("Record or upload audio first.")
                    else:
                        audio_bytes = voice_audio.getvalue()
                        filename = getattr(voice_audio, "name", None) or "recording.webm"
                        transcript = transcribe_voice_to_nl_request(audio_bytes, filename)
                        if transcript:
                            if st.session_state.get("run_plan"):
                                st.session_state["_pending_workflow_chat_draft"] = transcript
                                st.session_state["_chat_transcribe_ok"] = True
                                request_assistant_chat_tab()
                            else:
                                st.session_state["_pending_nl_transcript"] = transcript
                                st.session_state["_nl_transcribe_ok"] = True
                            st.rerun()
            else:
                st.caption(
                    "Save an **OpenAI** API key to transcribe voice (Whisper). "
                    "Claude has no speech-to-text API."
                )

            st.markdown(
                '<div class="assistant-plan-divider">------------------</div>',
                unsafe_allow_html=True,
            )
            if st.button(
                "Generate plan",
                key="generate_plan_gpt",
                width="stretch",
                type="secondary",
            ):
                run_generate_plan_from_nl_request()

        if st.session_state.get("run_plan") is not None:
            plan_text_holder = render_persistent_plan_editor(visible=True)
            update_run_plan_needs_user_input()

            if st.button(
                "Resolve dependencies",
                key="resolve_dependencies",
                width="stretch",
                type="secondary",
            ):
                ok, err = commit_plan_editor_to_session(
                    plan_text=plan_text_holder or current_plan_editor_text()
                )
                if not ok:
                    st.error(err)
                    st.stop()
                resolved_plan = resolve_requested_plan_dependencies(st.session_state.run_plan)
                st.session_state.run_plan = resolved_plan
                steps = resolved_plan.get("steps")
                if isinstance(steps, list):
                    st.session_state["_committed_plan_steps"] = list(steps)
                refresh_plan_editor_from_state(force=True, remount=True)
                st.success("Dependencies resolved from operation catalog.")
                st.rerun()

            st.session_state.want_create_pour_point = st.checkbox(
                "Also run create_pour_point",
                value=st.session_state.want_create_pour_point,
            )
            st.session_state.allow_run = st.checkbox(
                "Allow dangerous run steps",
                value=st.session_state.get("allow_run", False),
            )
            st.text_input(
                "Type RUN to allow dangerous execution",
                key="danger_phrase",
                help="Required for run_model or calibrate_model.",
            )
            confirm_danger_run = s(st.session_state.get("danger_phrase", "")) == "RUN"

            needs = st.session_state.run_plan.get("needs_user_input", []) or []
            if needs:
                st.warning(
                    f"{len(needs)} required field(s) missing before execution. "
                    "Use the section below or the Input tab."
                )
                render_fix_missing_inputs_section(needs)

            assistant_shortcut_out = st.empty()
            wx.render_run_shortcuts_section(
                execute_bundle_fn=lambda key: execute_step_bundle(key, assistant_shortcut_out),
                location="assistant",
            )

            assistant_cal_out = st.empty()

            def _assistant_run_calibrate() -> None:
                if not st.session_state.allow_run:
                    st.error("Enable **Allow dangerous run steps** first.")
                    return
                with st.spinner("Running calibration…"):
                    rc, _ = execute_single_symfluence_step("calibrate_model", assistant_cal_out)
                if rc == 0:
                    st.success("Calibration step finished.")
                else:
                    st.error(f"Calibration failed (return code {rc}).")

            wx.render_calibration_section(
                execute_calibrate_fn=_assistant_run_calibrate,
                location="assistant",
            )
            steps_set = set(st.session_state.run_plan.get("steps", []) or [])
            needs_confirm = bool(steps_set & DANGER_STEPS)
            can_execute = len(needs) == 0
            confirm_ok = True

            if needs_confirm:
                confirm_ok = st.checkbox("Confirm: this may take a long time / download data", value=False)

            exec_col, clear_col = st.columns(2)
            with exec_col:
                exec_btn = st.button(
                    "Execute plan",
                    disabled=(not can_execute) or (not confirm_ok),
                    key="execute_plan_button",
                    width="stretch",
                    type="secondary",
                )
            with clear_col:
                clear_plan = st.button(
                    "Clear plan",
                    key="clear_plan_button",
                    width="stretch",
                    type="secondary",
                )

            if clear_plan:
                clear_chat_messages(clear_plan=True)
                st.success("Plan cleared.")
                st.rerun()

            if exec_btn:
                ok, err = commit_plan_editor_to_session(
                    plan_text=plan_text_holder or current_plan_editor_text()
                )
                if not ok:
                    st.error(err)
                    st.stop()
                update_run_plan_needs_user_input()
                try:
                    plan_cfg = (st.session_state.run_plan or {}).get("config", {}) or {}
                    validation_cfg = {
                        "SYMFLUENCE_CODE_DIR": normalize_path_text(SYMFLUENCE_REPO),
                        "SYMFLUENCE_DATA_DIR": normalize_path_text(SYMFLUENCE_DATA_DIR) + "/",
                        "DOMAIN_NAME": s(plan_cfg.get("domain_name")) or s(st.session_state.domain_name),
                        "EXPERIMENT_ID": s(plan_cfg.get("experiment_id")) or s(st.session_state.experiment_id),
                        "POUR_POINT_COORDS": s(plan_cfg.get("pour_point_coords")) or s(st.session_state.selected_pour_point),
                        "BOUNDING_BOX_COORDS": s(plan_cfg.get("bounding_box_coords")) or s(st.session_state.selected_bounding_box),
                        "HYDROLOGICAL_MODEL": current_hydrological_model(plan_cfg),
                        "DOMAIN_DEFINITION_METHOD": s(plan_cfg.get("domain_def")) or s(st.session_state.domain_def),
                        "EXPERIMENT_TIME_START": s(plan_cfg.get("experiment_time_start")) or s(st.session_state.tstart),
                        "EXPERIMENT_TIME_END": s(plan_cfg.get("experiment_time_end")) or s(st.session_state.tend),
                    }
                    validate_spec(validation_cfg)
                    st.session_state.execute_plan = True
                    st.success("Execution started. See the Output tab.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Validation failed before execution: {e}")

    st.markdown('</div>', unsafe_allow_html=True)


def show_text(text: str):
    if output_box is not None:
        output_box.code(text)


if st.session_state.execute_plan and st.session_state.run_plan:
    st.session_state.execute_plan = False
    capture_user_prompt_from_session()
    committed_steps = st.session_state.get("_committed_plan_steps")
    plan = normalize_local_workflow_plan(
        force_steps(
            st.session_state.run_plan,
            want_create_pour_point=st.session_state.want_create_pour_point,
        ),
        conversation_text_for_plan_rules()
        or user_prompt_for_metadata()
        or s(st.session_state.get("nl_request", "")),
        data_dir=SYMFLUENCE_DATA_DIR,
    )
    if isinstance(committed_steps, list) and committed_steps:
        plan["steps"] = list(committed_steps)
    st.session_state.run_plan = plan
    plan_cfg = (plan or {}).get("config", {}) or {}
    spec_dict = build_spec_dict(plan_cfg)

    current_pour = (
        s(st.session_state.selected_pour_point)
        or s(plan_cfg.get("pour_point_coords"))
    )

    current_bbox = (
        s(st.session_state.selected_bounding_box)
        or s(st.session_state.bounding_box_input)
        or s(plan_cfg.get("bounding_box_coords"))
    )

    if current_pour:
        spec_dict["pour_point_coords"] = current_pour
    else:
        spec_dict.pop("pour_point_coords", None)

    if current_bbox:
        spec_dict["bounding_box_coords"] = current_bbox
    else:
        spec_dict.pop("bounding_box_coords", None)

    finalize_spec_for_symfluence(spec_dict)
    spec_dict["force_rerun"] = True

    outdir = RUNS_DIR / st.session_state.run_folder
    outdir.mkdir(parents=True, exist_ok=True)
    out_yaml = outdir / "config.yaml"
    render_config_from_spec(spec_dict, TEMPLATE_PATH, out_yaml)
    cfg = load_yaml(out_yaml)
    cfg = clean_cfg_for_safe_run(cfg)

    current_model = current_hydrological_model(plan_cfg)

    if current_model:
        cfg["HYDROLOGICAL_MODEL"] = current_model
    else:
        cfg.pop("HYDROLOGICAL_MODEL", None)

    if current_pour:
        cfg["POUR_POINT_COORDS"] = current_pour
    else:
        cfg.pop("POUR_POINT_COORDS", None)

    if current_bbox:
        cfg["BOUNDING_BOX_COORDS"] = current_bbox
    else:
        cfg.pop("BOUNDING_BOX_COORDS", None)

    # Reapply all explicit planner/spec values after cleanup.
    # This restores first-class fields and extra_config values,
    # and lets user-provided values override stale template defaults.
    cfg = reapply_spec_overrides(cfg, spec_dict)

    # Keep current UI/manual selections authoritative after reapplying spec overrides.
    # This prevents stale plan/spec values from overriding map-selected values.
    if current_model:
        cfg["HYDROLOGICAL_MODEL"] = current_model
    else:
        cfg.pop("HYDROLOGICAL_MODEL", None)

    if current_pour:
        cfg["POUR_POINT_COORDS"] = current_pour
    else:
        cfg.pop("POUR_POINT_COORDS", None)

    if current_bbox:
        cfg["BOUNDING_BOX_COORDS"] = current_bbox
    else:
        cfg.pop("BOUNDING_BOX_COORDS", None)

    dump_yaml(cfg, out_yaml)

    write_run_metadata_files(outdir, plan, spec_dict)

    user_request = user_prompt_for_metadata() or s(st.session_state.get("nl_request", ""))
    basin_domain = symfluence_domain_name(
        s(plan_cfg.get("domain_name")) or s(st.session_state.domain_name),
        s(plan_cfg.get("experiment_id")) or s(st.session_state.experiment_id),
    )
    symfluence_domain = s(cfg.get("DOMAIN_NAME")) or basin_domain
    plan = ensure_skip_process_observed_when_local_streamflow(
        plan,
        user_request,
        data_dir=SYMFLUENCE_DATA_DIR,
        symfluence_domain=symfluence_domain,
    )
    st.session_state.run_plan = plan

    steps = plan.get("steps", []) or []

    danger_found = [step for step in steps if step in DANGER_STEPS]
    has_danger = len(danger_found) > 0
    if has_danger:
        st.warning(f"Dangerous steps detected: {', '.join(danger_found)}")
        if not st.session_state.allow_run:
            st.error("Check the allow-run box before executing dangerous steps.")
            st.stop()
        if not confirm_danger_run:
            st.error("Type RUN exactly to allow dangerous execution.")
            st.stop()

    log: list[str] = []
    st.session_state.execution_log_text = ""
    logs_dir = outdir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "execution.log"
    log_path.write_text("", encoding="utf-8")
    st.info(f"Execution log path: {log_path}")

    preamble = execution_log_preamble(plan)
    log.append(preamble)
    log.append(f"\nUsing config: {out_yaml}\n")
    show_text("".join(log))
    st.session_state.execution_log_text = "".join(log)
    progress_box.markdown(render_workflow_progress(plan, "".join(log)))

    with log_path.open("a", encoding="utf-8") as f:
        f.write(preamble)
        f.write(f"\nUsing config: {out_yaml}\n")

    for step in steps:
        if step == "validate_config":
            with log_path.open("a", encoding="utf-8") as f:
                f.write("\n===== STEP: validate_config =====\n")
            try:
                validate_spec(cfg)
                log.append("\nInternal validation OK ✅\n")
                show_text("".join(log))
                st.session_state.execution_log_text = "".join(log)
                progress_box.markdown(render_workflow_progress(plan, "".join(log)))
                with log_path.open("a", encoding="utf-8") as f:
                    f.write("Internal validation OK ✅\n")
            except Exception as e:
                log.append(f"\nInternal validation FAILED ❌: {e}\n")
                log.append("\nStopping due to failure.\n")
                show_text("".join(log))
                st.session_state.execution_log_text = "".join(log)
                progress_box.markdown(render_workflow_progress(plan, "".join(log)))
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(f"Internal validation FAILED ❌: {e}\n")
                    f.write("Stopping due to failure.\n")
                break
            continue

        if step not in SUPPORTED_STEPS:
            log.append(f"\nSKIP unknown step: {step}\n")
            show_text("".join(log))
            continue

        basin_domain = symfluence_domain_name(
            s(plan_cfg.get("domain_name")) or s(st.session_state.domain_name),
            s(plan_cfg.get("experiment_id")) or s(st.session_state.experiment_id),
        )
        symfluence_domain = s(cfg.get("DOMAIN_NAME")) or basin_domain
        experiment_id = s(plan_cfg.get("experiment_id")) or "run_1"

        if step == "model_specific_preprocessing" and symfluence_domain and (
            domain_has_complete_local_workflow(
                SYMFLUENCE_DATA_DIR, symfluence_domain, experiment_id
            )
            or domain_has_complete_local_workflow(
                SYMFLUENCE_DATA_DIR, basin_domain, experiment_id
            )
            or local_catchment_needs_restore(SYMFLUENCE_DATA_DIR, symfluence_domain)
            or local_catchment_needs_restore(SYMFLUENCE_DATA_DIR, basin_domain)
        ):
            restore_domain = symfluence_domain
            if local_catchment_needs_restore(SYMFLUENCE_DATA_DIR, restore_domain):
                if local_catchment_needs_restore(SYMFLUENCE_DATA_DIR, basin_domain):
                    restore_domain = basin_domain
                log.append(
                    "\nRestoring local catchment shapefiles from semidistributed/into "
                    "(legacy catchment path had wrong HRU IDs).\n"
                )
                restore_local_domain_artifacts(
                    SYMFLUENCE_DATA_DIR,
                    restore_domain,
                    experiment_id,
                )

        cmd = build_symfluence_step_cmd(step, out_yaml)
        log.append(f"\n===== STEP: {step} =====\n$ {' '.join(cmd)}\n\n")
        show_text("".join(log))
        st.session_state.execution_log_text = "".join(log)
        progress_box.markdown(render_workflow_progress(plan, "".join(log)))

        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n===== STEP: {step} =====\n")
            f.write("$ " + " ".join(cmd) + "\n\n")

        rc, out = run_cmd_stream(cmd, SYMFLUENCE_REPO, output_box, log_path=log_path)
        log.append(out)
        log.append(f"\n[STEP {step}] return code: {rc}\n")

        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n[STEP {step}] return code: {rc}\n")

        if rc != 0:
            log.append("\nStopping due to failure.\n")
            show_text("".join(log))
            st.session_state.execution_log_text = "".join(log)
            progress_box.markdown(render_workflow_progress(plan, "".join(log)))
            break

        if step == "setup_project" and not user_requires_fresh_cloud_workflow(
            user_request, plan_cfg
        ):
            copied: list[str] = []
            source_domain = infer_reuse_source_domain(
                user_request,
                basin_domain,
                SYMFLUENCE_DATA_DIR,
            )
            if source_domain and user_request_reuses_local_domain_data(user_request):
                copied = copy_reusable_domain_artifacts(
                    SYMFLUENCE_DATA_DIR,
                    source_domain,
                    symfluence_domain,
                )
            elif symfluence_domain != basin_domain:
                copied = seed_mac_duplicate_domain_from_basin(
                    SYMFLUENCE_DATA_DIR,
                    basin_domain,
                    symfluence_domain,
                )
            if copied:
                seed_msg = (
                    "\nSeeded reusable local artifacts into "
                    f"`domain_{symfluence_domain}` from existing on-disk data:\n"
                    + "\n".join(f"  - {item}" for item in copied)
                    + "\n"
                )
                log.append(seed_msg)
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(seed_msg)
                plan = ensure_skip_process_observed_when_local_streamflow(
                    plan,
                    user_request,
                    data_dir=SYMFLUENCE_DATA_DIR,
                    symfluence_domain=symfluence_domain,
                )
                st.session_state.run_plan = plan
                steps = plan.get("steps", []) or []

        show_text("".join(log))
        st.session_state.execution_log_text = "".join(log)
        progress_box.markdown(render_workflow_progress(plan, "".join(log)))

if validate_btn:
    rc, msg = execute_validate_config_step(output_box)
    show_text(msg if rc == 0 else f"Internal validation FAILED ❌\n{msg}")

if dryrun_btn:
    rc, out = execute_single_symfluence_step("dry_run", output_box)
    show_text(f"{'✅ success' if rc == 0 else '❌ failed'} (return code {rc})\n\n{out}")

if setup_btn:
    rc, out = execute_single_symfluence_step("setup_project", output_box)
    show_text(f"{'✅ success' if rc == 0 else '❌ failed'} (return code {rc})\n\n{out}")

if run_btn and st.session_state.allow_run:
    rc, out = execute_single_symfluence_step("run_model", output_box)
    show_text(f"{'✅ success' if rc == 0 else '❌ failed'} (return code {rc})\n\n{out}")