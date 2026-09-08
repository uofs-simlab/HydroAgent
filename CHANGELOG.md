# Changelog

## Demo hardening — 2026-09-06

### Added

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

- HydroAgent tests can run from a clean standalone checkout without relying on
  an undeclared sibling repository.
- Test discovery consistently includes the project root.
- Generated run commands use the frozen project environment instead of an
  arbitrary global Python installation.
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
- Pour-point coordinates are required only for workflows that create a pour
  point, not for downstream runs of an existing domain.
- Colon-separated core settings such as `domain_name: ...` and spatial
  coordinates are preserved deterministically when generating a plan.
- Maps load fitted to a configured bounding box and include a control for
  restoring that view after panning or zooming.
- Review-map legends use concise labels for GRUs and sub-basin boundaries and
  display GRU identifiers as discrete categories rather than a numeric color bar.
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
- Workflow panels now fit the remaining browser height and update when the
  window is resized, without adding an overall page scrollbar.
- Assistant column widths are scoped to the Workflows page and are cleared when
  navigating elsewhere, preventing reused Streamlit columns from being squeezed.
- Panel button styling no longer captures select arrows, date controls, help
  icons, or other internal widget buttons.
- Output review maps fit the configured bounding box after a collapsed review
  expander becomes visible, and mouse activation no longer leaves the fit
  control focused.
- Dashboard, Experiments, Data, Results, and Logs no longer repeat their page
  titles below the shared page heading.
