# Changelog

## Repository cleanup — 2026-09-17

### Backend scope

- Discarded local SYMFLUENCE demo/config rewrites and notebook execution output.
  Retained the NumPy/PyTorch compatibility fix and the Paradise SNOTEL station
  correction; the cleanup guide now describes only these remaining fixes.

### Fixed

- Results and Data share saved-run path resolution; Data no longer shows draft
  layers as artifacts of another experiment. Evaluation date bounds use UTC.
- Shared caches reject unrelated existing rasters and forcing files instead of
  disabling downloads or mixing incompatible inputs.
- Damaged routed-flow provenance cannot fall back to an unverified standalone CSV.
- Consolidated duplicate workspace allocation logic and removed repeated config keys.
- Preview and chat drafts no longer overwrite saved run metadata on load or edit.
- Explicit domain definitions remain unchanged by lumped routing or parameter settings.
- Routed-flow extraction selects `SIM_REACH_ID`, validates reach identifiers, and
  refreshes CSV caches when the selected reach or source files change. Results and
  artifact scans report unverifiable output instead of using stale CSVs.
- Loading a data domain resolves portable duplicate run names from saved configs,
  retaining the matching plan, logs, and chat without stripping numeric basin names.
- Shared input caches preserve custom raster filenames and compare forcing coverage
  in UTC, including mixed timezone-aware and timezone-free dates.
- Assistant resize controls remove parent-page listeners and pending work on
  rerender, close, and navigation. Removed the unused legacy Results renderer.

### Added

- Portable Logan River water-year 2005 demo plan and guide, plus updated Pixi path
  and duplicate-naming documentation.

## Experiment loading — 2026-09-17

### Fixed

- Loading a saved experiment applies its executed configuration even when
  `plan.json` contains a later draft for another domain.
- Results follows the selected run's saved domain, experiment, and data path,
  so changing workflow drafts cannot redirect its streamflow plots.

## Demo hardening — 2026-09-06

### Added

- Results-page hydrographs, paired daily evaluation metrics, flow-duration
  curves, and CSV downloads from postprocessed experiment outputs or routed flow.
  Evaluation uses the saved run configuration and excludes configured spin-up.
- Reproducible HydroAgent setup with Python 3.12, `uv`, `pyproject.toml`, and
  the committed dependency lock file.
- Frozen-environment application launcher and pinned compatibility requirement
  exports.
- Standalone calibration prompt-field detection when CalibHydroAgent is not
  installed beside HydroAgent.
- Automatic discovery of `OPENAI_API_KEY` without saving another plaintext copy
  in HydroAgent's local configuration.
- Independent controls for using prompt-library examples, enabling legacy
  prompt phrase matching, and saving generated requests to prompt history.
- A confirmed **New workflow** action that clears the active draft and run
  association without deleting saved runs or SYMFLUENCE data.
- A Bow-at-Banff CIROH demo guide with a coarse semi-distributed example and a
  lumped fallback.

### Changed

- Review maps use independent checkboxes for spatial overlays and a single
  color-layer radio group, including a None option for overlays only.
- Prompt-library example enrichment is off by default.
- Automatic prompt-history saving is off by default.
- Deterministic phrase matching over prompt prose is off by default, so the
  planner's structured config and step list remain authoritative. The original
  phrase-matching behavior remains available as an opt-in setting.
- Data-access policy, stream threshold, PET method, and process count are now
  first-class structured planner fields rather than depending on prompt parsing.
- The assistant panel can be resized by dragging its divider; its width is
  retained for the current browser session.
- When stored-prompt examples are disabled, plan generation does not search the
  saved prompts or add them to the LLM context. Manual **Find similar prompts**
  remains available.
- HydroAgent and the SYMFLUENCE submodule use separate locked environments:
  `uv` for HydroAgent and Pixi for SYMFLUENCE.
- The OpenAI model selector now offers GPT-5.6 Sol, Terra, and Luna alongside
  GPT-5 Mini; older OpenAI model choices have been removed.

### Fixed

- Fresh cloud workflows stage compatible domain-neutral cached DEM, soil,
  land-cover, and raw forcing inputs under the new domain's standard paths.
  Cached forcing no longer overrides SYMFLUENCE's standardized forcing path.
- Semi-distributed domain requests map to DEM delineation with GRUs; `subset`
  is reserved for explicitly requested existing geofabrics.
- PET method names are normalized to SYMFLUENCE's lowercase enum values when
  the final run configuration is written.
- Untouched Input-panel defaults no longer overwrite prompt-generated plan
  fields; deliberate GUI edits still take precedence.
- HydroAgent tests can run from a clean standalone checkout without relying on
  an undeclared sibling repository.
- Test discovery consistently includes the project root.
- Generated run commands use the frozen project environment instead of an
  arbitrary global Python installation.
- SYMFLUENCE steps run with their Pixi environment first and without inherited
  Conda activation state, preventing incompatible Miniconda libraries from
  being loaded by model executables on macOS.
- Map legends stay within the map viewport and clear the zoom controls, with
  long class lists scrolling independently instead of clipping the heading.
- The Assistant resize divider now starts from the exact grab position, releases
  reliably outside the handle or browser window, and batches drag updates for
  smoother resizing.
- Confirming **New workflow** now closes the confirmation popover as the clean
  workflow state loads.
- Simulation workflows can retain explicitly requested observed-streamflow
  processing, station identifiers, and provider settings without treating them
  as calibration-only configuration.
- Simulation workflows can retain an explicitly requested evaluation period so
  postprocessing metrics can exclude model spin-up.
- LLM-generated spin-up, calibration, and evaluation periods using natural
  "to" or "through" wording are normalized to SYMFLUENCE's comma format.
- Before routed postprocessing, HydroAgent uses SYMFLUENCE's nearest-segment
  routine to infer the outlet reach when `SIM_REACH_ID` was not supplied.
- Pour-point coordinates are required only for workflows that create a pour
  point, not for downstream runs of an existing domain.
- Colon-separated core settings such as `domain_name: ...` and spatial
  coordinates are preserved deterministically when generating a plan.
- Maps load fitted to the displayed review data and include a control for
  restoring that view after panning or zooming.
- Review-map legends use concise labels for GRUs and sub-basin boundaries and
  display GRU identifiers as discrete categories rather than a numeric color bar.
- Enabling river basins preserves the active color legend, including DEM elevation.
- Review layers retain a fixed stacking order regardless of toggle order, and
  the bounding-box overlay no longer blocks interaction with underlying layers.
- The Input map no longer displays an empty Layers control; the control remains
  available on the Output review map.
- Mouse-wheel input scrolls the workflow column over maps and hands off from
  nested text panes when they reach their scroll boundaries.
- The workflow and Assistant panels have a shared one-pixel divider that remains
  visible with the matching header rule in both light and dark themes.
- Hiding the Assistant removes its column entirely so the workflow expands into
  the available space; the toggle sits on the workflow side of the divider, and
  reopening the Assistant restores a freshly bound resize handle.
- Closing the Assistant removes the injected resize handle and stale column
  sizing state instead of leaving a divider in the middle of the page.
- Workflow panels now fit the remaining browser height and update when the
  window is resized, without adding an overall page scrollbar.
- Assistant column widths are scoped to the Workflows page and are cleared when
  navigating elsewhere, preventing reused Streamlit columns from being squeezed.
- Newly allocated duplicate run folders and SYMFLUENCE domains use portable
  `_n` suffixes; existing Finder-style ` (n)` workspaces remain loadable.
- Results and artifact views resolve the active numbered SYMFLUENCE domain
  instead of searching the unsuffixed base domain.
- Panel button styling no longer captures select arrows, date controls, help
  icons, or other internal widget buttons.
- Output review maps fit the displayed data after a collapsed review expander
  becomes visible, and mouse activation no longer leaves the fit control
  focused.
- Output review maps discover prepared-domain pour-point shapefiles; pour-point
  and bounding-box overlays have their own default-on controls when available,
  and forcing-layer labels reflect the configured dataset.
- Output review maps follow the active run's actual SYMFLUENCE domain and
  refresh when running workflow steps create new displayable layers.
- Dashboard, Experiments, Data, Results, and Logs no longer repeat their page
  titles below the shared page heading.
