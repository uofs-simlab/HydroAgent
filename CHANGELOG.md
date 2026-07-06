# HydroAgent changes — Friday, July 3, 2026

Summary of work done in Cursor on **2026-07-03** (macOS, Python 3.11 venv). Focus: LangPrompt integration, macOS SIGSEGV fix, workflow preflight, type-checker fixes, and UI polish.

---

## 1. LangPrompt integration

Semantic prompt search and a reusable prompt library were wired into the Streamlit assistant.

### New files

| File | Purpose |
|------|---------|
| `server/llm/prompt_finder.py` | Adapted from LangPrompt: embed prompts, vector search, cache on disk |
| `server/llm/prompt_library.py` | Thin wrapper for the UI and planner (`find_similar_prompts`, `enrich_planner_request`, etc.) |
| `prompts/library/prompts.txt` | Numbered prompt library (user queries cached here) |
| `prompts/library/.cache/` | Embedding cache (gitignored) |

### Modified files

- **`requirements.txt`** — Added `langchain-core`, `langchain-openai`, `numpy` for embeddings.
- **`.gitignore`** — Ignore `prompts/library/.cache/`.
- **`app/ui_agent.py`** — Prompt library panel, “Use this prompt”, enrich on Generate plan; `TYPE_CHECKING` import pattern for `PromptMatch` (fixes BasedPyright “Variable not allowed in type expression”).

---

## 2. macOS SIGSEGV fix (PROJ + fork)

Streamlit is multi-threaded. Importing **geopandas/pyproj** loads PROJ’s SQLite cache. Any `subprocess.run` / `Popen` **forks** first; PROJ’s `pthread_atfork` handler could **SIGSEGV** before `exec` (return code **-11**).

### New file

| File | Purpose |
|------|---------|
| `server/core/safe_subprocess.py` | Runs commands in a **`multiprocessing` spawn** worker (fresh Python without PROJ), then forks safely inside that worker |

Exports:

- `run_command()` — captured stdout/stderr
- `run_command_stream()` — streaming output via callback
- `launch_detached()` — detached background process

### Modified files

- **`app/ui_agent.py`**
  - `PROJ_DISABLE_CACHE=ON` at startup (belt-and-suspenders).
  - **Lazy geopandas import** (`_LazyGeoPandas`) so PROJ is not loaded at module import unless map shapefile layers need it.
  - `run_py_tool()` and `run_cmd_stream()` use `run_command` / `run_command_stream` from `safe_subprocess`.
  - Removed direct `subprocess` usage in the UI module.
- **`server/core/workflow_executor.py`**
  - `launch_background_workflow()` uses `launch_detached()` so starting a workflow no longer forks from the Streamlit process.

**Note:** `PROJ_DISABLE_CACHE` alone was not enough when geopandas was imported at top level; spawn workers are the reliable fix.

---

## 3. Workflow preflight (missing prerequisites)

Running **Model-specific preprocessing (MSP)** alone failed when earlier steps had not created the ERA5/catchment intersection (e.g. Bow `domain_Bow (5)` only had through `acquire_attributes`).

### Modified files

- **`server/core/plan_rules.py`**
  - Added `domain_has_forcing_intersection()` — checks for `{domain}_ERA5_intersected_shapefile.shp` / `.csv` under `shapefiles/catchment_intersection/with_forcing/`.
- **`app/ui_agent.py`**
  - Extended `symfluence_step_preflight_error()`:
    - **MAP** — requires discretization + forcing data; lists missing steps (`define_domain`, `discretize_domain`, `acquire_forcings`).
    - **MSP** — requires forcing intersection from MAP; suggests running steps in order or **Execute plan**.

This fails fast in the UI instead of deep inside SYMFLUENCE SUMMA preprocessing.

---

## 4. UI improvements

- **`NL_REQUEST_PLACEHOLDER`** — Short placeholder text when the natural-language prompt box is empty.
- **Prompt library panel** — Shows heading + hint when prompt is empty (instead of rendering nothing).
- **BasedPyright / typing** — `TYPE_CHECKING` blocks for `PromptMatch` and lazy `gpd`; fixed `_s` → `s()` typo where applicable.

---

## 5. Type checker configuration (Pyright / BasedPyright)

LangChain imports showed “could not be resolved” because the Desktop workspace root did not point Pyright at `HydroAgent/.venv`.

### Files (workspace + project)

| File | Change |
|------|--------|
| `Desktop/pyrightconfig.json` | Moved `venvPath` / `venv` to **top level** (invalid inside `executionEnvironments`); set `pythonVersion: "3.11"` |
| `HydroAgent/pyrightconfig.json` | **New** — `include`, `venvPath: "."`, `venv: ".venv"`, `pythonVersion: "3.11"` |
| `Desktop/.vscode/settings.json` | Added `basedpyright.analysis.venvPath` / `venv` for `HydroAgent/.venv` |

---

## 6. `plan_rules.py` type fixes (BasedPyright)

Several `"get" is not a known attribute of "None"` and related errors were fixed:

| Location | Fix |
|----------|-----|
| `request_indicates_local_data_reuse()` | `extra_raw` + `isinstance` narrowing for `extra_config` |
| `domain_name_confirmed_in_plan()` | Same pattern |
| `user_requires_fresh_cloud_workflow()` | Same pattern |
| `plan_uses_local_data()` (data_access LOCAL check) | Same pattern |
| `domain_has_local_attributes()` | Early `if not data_dir` guard before `domain_attributes_root()` |
| `domain_catchment_hru_count()` | `len(gdf[col].unique())` instead of `int(gdf[col].nunique())` (pandas stub typing) |

After these edits, **`plan_rules.py` had zero BasedPyright errors**.

---

## 7. Environment notes (Friday session)

- Venv migrated to **Python 3.11.15** under `HydroAgent/.venv` (Homebrew).
- SYMFLUENCE continues to use its own venv at `Desktop/SYMFLUENCE/venv/bin/python`.
- JAX warning from `jhbv` during SYMFLUENCE runs is harmless unless HBV autodiff is needed.
- Deprecated config keys (`MPI_PROCESSES`, `INSTALL_PATH_MIZUROUTE`, etc.) are SYMFLUENCE warnings only.

---

## 8. Files touched (checklist)

### New

- `server/core/safe_subprocess.py`
- `server/llm/prompt_finder.py`
- `server/llm/prompt_library.py`
- `prompts/library/prompts.txt`
- `pyrightconfig.json`
- `CHANGELOG-2026-07-03.md` (this file)

### Modified

- `app/ui_agent.py`
- `server/core/plan_rules.py`
- `server/core/workflow_executor.py`
- `requirements.txt`
- `.gitignore`

### Workspace (outside `HydroAgent/`, same session)

- `Desktop/pyrightconfig.json`
- `Desktop/.vscode/settings.json`

---

## 9. Recommended workflow order (Bow / SUMMA)

When running from scratch, do not skip to MSP alone. Minimum path before **model_specific_preprocessing**:

1. `validate_config`
2. `setup_project`
3. `create_pour_point`
4. `acquire_attributes`
5. `define_domain`
6. `discretize_domain`
7. `acquire_forcings`
8. `model_agnostic_preprocessing`
9. `model_specific_preprocessing`
10. `run_model`

Use **Execute plan** on the Workflows tab to run remaining steps in order.

---

## 10. Not done / follow-ups

- Wire `langprompt_dir` from `~/.symfluence_assistant/config.yaml` into code (if desired).
- Move Prompt library panel above voice / Generate plan (optional UX).
- Remaining BasedPyright issues in other files (if any) beyond `plan_rules.py`.
- Git commit on branch `LangPrompt` — changes were implemented but not necessarily committed/pushed unless you did so separately.
