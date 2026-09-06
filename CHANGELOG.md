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

### Known limitations

- Prompt-history entries are raw inputs rather than approved prompt-config
  pairs; keep history enrichment disabled unless the library has been reviewed.
- Station identifiers are not yet resolved deterministically into both a gauge
  coordinate and a validated watershed bounding box.
- A complete Bow-at-Banff workflow should be pretested before the live demo;
  validation and dry-run behavior are more mature than unattended execution.
