# Changelog

## Demo hardening — 2026-09-05

### Added

- Reproducible HydroAgent setup with Python 3.12, `uv`, `pyproject.toml`, and
  the committed dependency lock file.
- Frozen-environment application launcher and pinned compatibility requirement
  exports.
- Standalone calibration prompt-field detection when CalibHydroAgent is not
  installed beside HydroAgent.
- Automatic discovery of `OPENAI_API_KEY` without saving another plaintext copy
  in HydroAgent's local configuration.
- Independent controls for using prompt-library examples and saving generated
  requests to prompt history.
- A confirmed **New workflow** action that clears the active draft and run
  association without deleting saved runs or SYMFLUENCE data.

### Changed

- Prompt-library example enrichment is off by default.
- Automatic prompt-history saving is off by default.
- The assistant panel can be resized by dragging its divider; its width is
  retained for the current browser session.
- Disabling example enrichment now skips the automatic embedding search during
  plan generation. Manual **Find similar prompts** remains available.
- HydroAgent and the SYMFLUENCE submodule use separate locked environments:
  `uv` for HydroAgent and Pixi for SYMFLUENCE.

### Fixed

- HydroAgent tests can run from a clean standalone checkout without relying on
  an undeclared sibling repository.
- Test discovery consistently includes the project root.
- Generated run commands use the frozen project environment instead of an
  arbitrary global Python installation.
- Map legends stay within the map viewport, with long class lists scrolling
  independently instead of clipping the legend heading.
- The Assistant resize divider now starts from the exact grab position, releases
  reliably outside the handle or browser window, and batches drag updates for
  smoother resizing.
- Confirming **New workflow** now closes the confirmation popover as the clean
  workflow state loads.
- Basin-definition prompts with an explicit **include only these workflow
  steps** list no longer have the full simulation pipeline added afterward.
- Closed workflow-step lists also recognize wording such as **in this order**.
- Colon-separated core settings such as `domain_name: ...` and spatial
  coordinates are preserved deterministically when generating a plan.
- Maps load fitted to a configured bounding box and include a control for
  restoring that view after panning or zooming.
- Review-map legends distinguish river basins from GRUs and display GRU
  identifiers as discrete categories rather than a numeric color bar.
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
- Workflow panels retain the normal page background so form controls remain
  visually distinct instead of blending into a sidebar-gray surface.
- Output review maps fit the configured bounding box after a collapsed review
  expander becomes visible, and mouse activation no longer leaves the fit
  control focused.
- Dashboard, Experiments, Data, Results, and Logs no longer repeat their page
  titles below the shared page heading.

### Known limitations

- Prompt-history entries are raw inputs rather than approved prompt-config
  pairs; keep history enrichment disabled unless the library has been reviewed.
- Station identifiers are not yet resolved deterministically into both a gauge
  coordinate and a validated watershed bounding box.
- A complete Bow-at-Banff workflow should be pretested before the live demo;
  validation and dry-run behavior are more mature than unattended execution.
