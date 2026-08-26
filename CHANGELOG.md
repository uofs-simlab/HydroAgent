# HydroAgent CHANGELOG

---

## Thursday, July 9, 2026 — Bow / FUSE debugging, TauDEM GDAL fix, workflow preflight

Summary of work during the **Bow River / BbowFuse (FUSE)** and **Bowsumma / BowRiver (SUMMA)** debugging session (macOS, Homebrew GDAL 3.13, SYMFLUENCE venv + pixi env).

### Problems

1. **`define_domain` failed for `domain_BbowFuse`** — TauDEM `pitremove` could not load `libgdal.38.dylib` after Homebrew upgraded GDAL to 3.13 (`libgdal.39.dylib`).
2. **`define_domain` silent failure on `domain_Bbow`** — Pour point outside bounding box; no `river_basins` shapefile produced.
3. **MAP preflight false failure on `domain_BowRiver`** — Single-HRU discretization blocked MAP (required ≥2 HRUs incorrectly).
4. **Missing simulation artifacts in UI** — `routed_flow.csv` and `*_streamflow_processed.csv` flagged missing; user confused about `STATION_ID` vs mizuRoute setup.
5. **FUSE + mizuRoute incomplete** — FUSE MSP does not auto-create `topology.nc` / `param.nml.default` (SUMMA does); mizuRoute failed at `run_model` for `BbowFuse`.

### Root causes

| Issue | Cause |
|-------|--------|
| TauDEM SIGABRT / missing GDAL | Old TauDEM binaries linked to GDAL 3.8; Homebrew now ships GDAL 3.13. Force-rebuild against Homebrew alone also crashed (bus error) or failed compile (`linklib.h` typo on Apple Clang). |
| Pour point / bbox | User bbox did not contain pour point (`51.35/-116.02` vs bbox centered elsewhere). |
| MAP blocked at 1 HRU | `domain_has_local_discretization()` used `min_hrus=2`. |
| No streamflow CSV | `process_observed_data` never run; WSC requires `STATION_ID` (e.g. `05BB001`). Unrelated to mizuRoute. |
| No `routed_flow.csv` | mizuRoute did not produce `*.h.*.nc` history files; CSV is a separate HydroAgent extract step. FUSE missing routing topology files. |
| SUMMA vs FUSE mizuRoute | SYMFLUENCE `routable_models = {'SUMMA'}` — only SUMMA MSP auto-runs mizuRoute preprocessing (`topology.nc`, `param.nml.default`). FUSE MSP prepares FUSE files only. |

### Changes — HydroAgent

| File | Change |
|------|--------|
| `server/core/safe_subprocess.py` | macOS `posix_spawn` path (no parent fork from Streamlit); exec wrapper when `cwd` is set. |
| `app/workflow_extras.py` | `run_py_tool()` routed through `safe_subprocess.run_command`. |
| `server/capabilities/proven_status.py` | `acquire_forcings: True` so forcings appears in single-step UI. |
| `server/core/local_domain.py` | **`ensure_bounding_box_contains_pour_point()`** — auto-expands bbox when pour point is outside. |
| `server/core/plan_rules.py` | **`define_domain` preflight** — pour point must lie inside bbox; **`discretize_domain` preflight** — requires `river_basins` shapefile; **MAP preflight** — accepts **1+ HRU** (`min_hrus=1`); clearer MAP error messages. |
| `app/ui_agent.py` | Wires bbox auto-fix and expanded step preflight checks before SYMFLUENCE runs. |
| `tests/test_safe_subprocess.py` | **New** — darwin vs Linux wrapper behavior; streaming run with `cwd`. |
| `tests/test_bounding_box_pour_point.py` | **New** — bbox auto-fix when pour is outside. |
| `tests/test_domain_discretization_preflight.py` | **New** — discretize / MAP preflight with 1 HRU. |

### Changes — SYMFLUENCE (documented here; fixes live in `Desktop/SYMFLUENCE/`)

These were applied in the SYMFLUENCE repo / data tree during the same session. HydroAgent users depend on them for `define_domain` and TauDEM on macOS.

| File / action | Change |
|---------------|--------|
| `src/symfluence/cli/external_tools_build_commands.py` | **macOS TauDEM build:** prefer pixi conda GDAL 3.12 (not Homebrew 3.13); embed pixi `rpath`; patch `linklib.h` for-loop typo before compile. |
| `src/symfluence/geospatial/geofabric/processors/taudem_executor.py` | **macOS runtime:** set `DYLD_LIBRARY_PATH` to `SYMFLUENCE/.pixi/envs/default/lib` when `SYMFLUENCE_CODE_DIR` is set (TauDEM links `libgdal.38`). |
| `SYMFLUENCE_data/installs/TauDEM/src/linklib.h` | One-line compile fix: `for(int i=0;i<toRecv->numCoords;i++)` (was invalid chained comparison). |
| `pixi install` + manual rebuild | Rebuilt TauDEM against pixi GDAL 3.12.2; staged binaries to `SYMFLUENCE_data/installs/TauDEM/bin/`. |

**Rebuild TauDEM after a Homebrew GDAL upgrade:**

```bash
cd /Users/hivagheisari/Desktop/SYMFLUENCE
pixi install
symfluence binary install taudem --force
```

### Verified

- TauDEM `pitremove` runs against pixi GDAL (no `libgdal.38` load error).
- **`define_domain` for `domain_BbowFuse`** completed (~1188 GRUs, river basins + network shapefiles).
- **`run_model` for `domain_BbowFuse`** — FUSE output `BbowFuse_61447c_runs_def.nc` created; mizuRoute still needs topology files for routed flow.
- HydroAgent tests: `test_safe_subprocess.py`, `test_bounding_box_pour_point.py`, `test_domain_discretization_preflight.py`.

### Operational notes (Bow workflows)

| Topic | Guidance |
|-------|----------|
| **Reuse domains** | Prefer **`domain_BowRiver`** (SUMMA through calibration) or **`domain_BowRiverFuse`** (FUSE MSP done) instead of new names (`Bbow`, `BbowFuse`, …). |
| **`domain_Bowsumma`** | Only reached `define_domain` — **no** `simulations/` folder yet. |
| **`STATION_ID`** | Required for **`process_observed_data`** with WSC (e.g. `05BB001`). Not required for `run_model` or mizuRoute topology. |
| **`routed_flow.csv`** | Needs successful mizuRoute + **Extract discharge → CSV** in Results tab. |
| **FUSE + mizuRoute** | Set `ROUTING_MODEL: none` for FUSE-only, or ensure mizuRoute topology exists (today auto-only for SUMMA MSP). |
| **FUSE executable** | `installs/fuse/bin/fuse.exe` may be missing if clone never built — run `symfluence binary install fuse --force`. |

### User action

1. **Restart Streamlit** after pulling HydroAgent changes.
2. For new Bow/FUSE domains: confirm bbox contains pour point (or let HydroAgent auto-fix).
3. Run workflow in order: … → `define_domain` → `discretize_domain` → `acquire_forcings` → MAP → MSP → `run_model`.
4. For gauge comparison/calibration: add `STATION_ID: 05BB001` and run **`process_observed_data`**.
5. After Homebrew GDAL updates: rebuild TauDEM via pixi (see above).

---

## Monday, July 7, 2026 — macOS subprocess crash + workflow step UI

Summary of work during the **Bow / SUMMA** debugging session (macOS 26.x, Homebrew Python 3.11, SYMFLUENCE venv).

### Problem

1. **Skipped `acquire_forcings`** — The “Run single step” panel only shows steps marked **proven**. `acquire_forcings` was unproven, so clicking proven buttons in order went HRUs → MAP and skipped forcings. Preflight correctly blocked MAP.
2. **MSP button SIGSEGV** — Clicking **Run MSP** crashed Python with `EXC_BAD_ACCESS` in PROJ/SQLite during `fork` (`multi-threaded process forked`, `crashed on child side of fork pre-exec`). MSP itself runs fine from the CLI.

### Root cause (MSP crash)

The **2026-07-03** `safe_subprocess` fix used `multiprocessing` spawn workers, but on macOS that **still fork()s from Streamlit** when starting the worker. Worse, passing `cwd=` to `subprocess.Popen` **disables** CPython’s `posix_spawn` path and forces fork+exec from the multi-threaded Streamlit process — triggering PROJ’s `pthread_atfork` handler and SIGSEGV.

### Changes

| File | Change |
|------|--------|
| `server/core/safe_subprocess.py` | **Rewritten for macOS:** call `os.posix_spawn` directly (no parent `fork`) because `subprocess.Popen(..., stdout=PIPE)` sets `close_fds=True`, which disables CPython’s posix_spawn path and still fork+execs from Streamlit threads. When a working directory is needed, wrap with a tiny `python -c` helper that `chdir` + `execvp` in the child. `launch_detached()` uses `os.posix_spawn(..., setsid=True)`. |
| `app/workflow_extras.py` | `run_py_tool()` routed through `safe_subprocess.run_command` (was raw `subprocess.run`). |
| `server/capabilities/proven_status.py` | Set `acquire_forcings: True` so **Run forcings** appears between HRUs and MAP in the single-step panel. |
| `tests/test_safe_subprocess.py` | **New** — wrapper behavior on darwin vs Linux; streaming run with `cwd=/tmp`. |

### Verified

- `acquire_forcings` and `model_agnostic_preprocessing` completed for `domain_Bow` (ERA5 via ARCO).
- `model_specific_preprocessing` completed via CLI (SUMMA `fileManager.txt`, attributes, mizuRoute topology).
- `tests/test_safe_subprocess.py` — 3 passed.

### User action

**Restart the Streamlit app** after pulling these changes so `safe_subprocess` and proven-status updates load. Then use **Run forcings** → **Run MAP** → **Run MSP**, or **Execute plan** for the full ordered run.

---

## Friday, July 3, 2026

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

> **Update (2026-07-07):** The spawn-worker approach below was **not sufficient** on macOS when `cwd=` was passed to subprocess (see **Monday, July 7, 2026** section above). `safe_subprocess.py` now uses `posix_spawn` + exec wrapper instead.

Streamlit is multi-threaded. Importing **geopandas/pyproj** loads PROJ’s SQLite cache. Any `subprocess.run` / `Popen` **forks** first; PROJ’s `pthread_atfork` handler could **SIGSEGV** before `exec` (return code **-11**).

### New file

| File | Purpose |
|------|---------|
| `server/core/safe_subprocess.py` | *(Initial)* Runs commands in a **`multiprocessing` spawn** worker (fresh Python without PROJ), then forks safely inside that worker — **superseded 2026-07-07** |

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

### New (2026-07-09)

- `tests/test_bounding_box_pour_point.py`
- `tests/test_domain_discretization_preflight.py`

### Modified (2026-07-09)

- `app/ui_agent.py` — bbox auto-fix, expanded preflight
- `server/core/local_domain.py` — `ensure_bounding_box_contains_pour_point()`
- `server/core/plan_rules.py` — define_domain / discretize / MAP preflight (1+ HRU)

### SYMFLUENCE (same session, outside `HydroAgent/`)

- `SYMFLUENCE/src/symfluence/cli/external_tools_build_commands.py` — macOS TauDEM + pixi GDAL
- `SYMFLUENCE/src/symfluence/geospatial/geofabric/processors/taudem_executor.py` — macOS `DYLD_LIBRARY_PATH`
- `SYMFLUENCE_data/installs/TauDEM/` — rebuilt binaries + `linklib.h` patch

### New (2026-07-07)

- `tests/test_safe_subprocess.py`

### New (2026-07-03)

- `server/core/safe_subprocess.py`
- `server/llm/prompt_finder.py`
- `server/llm/prompt_library.py`
- `prompts/library/prompts.txt`
- `pyrightconfig.json`
- `CHANGELOG-2026-07-03.md` (this file)

### Modified (2026-07-07)

- `server/core/safe_subprocess.py` — posix_spawn + exec wrapper (replaces spawn workers)
- `server/capabilities/proven_status.py` — `acquire_forcings` marked proven

### Modified (2026-07-03)

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

- **FUSE + mizuRoute:** SYMFLUENCE only auto-preprocesses mizuRoute for SUMMA (`routable_models = {'SUMMA'}`). FUSE domains need topology/param files copied or preprocessor extended.
- **FUSE binary:** `symfluence binary install fuse --force` if `installs/fuse/bin/fuse.exe` is missing.
- **mizuRoute success detection:** SYMFLUENCE may log “completed successfully” when mizuRoute log shows `FATAL ERROR` — worth hardening subprocess exit checks.
- Wire `langprompt_dir` from `~/.symfluence_assistant/config.yaml` into code (if desired).
- Move Prompt library panel above voice / Generate plan (optional UX).
- Remaining BasedPyright issues in other files (if any) beyond `plan_rules.py`.
- Git commit on branch `LangPrompt` — changes were implemented but not necessarily committed/pushed unless you did so separately.
