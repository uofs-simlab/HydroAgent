"""Portable duplicate naming for assistant runs and SYMFLUENCE data domains."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

PLACEHOLDER_BASIN = "domain"
PLACEHOLDER_EXPERIMENT = "exp"

_MAC_DUP_SUFFIX_RE = re.compile(r" \((\d+)\)$")


def _portable_duplicate_suffix(name: str, base_name: str) -> int | None:
    """Return ``n`` for the new ``<base>_n`` form without guessing the base."""
    text = str(name or "").strip()
    prefix = f"{base_name}_"
    suffix = text[len(prefix) :] if text.startswith(prefix) else ""
    return int(suffix) if suffix.isdigit() else None


def sanitize_config_token(name: str) -> str:
    text = str(name or "").strip()
    return "".join(c if c.isalnum() else "_" for c in text).strip("_")


def preview_run_folder_name(domain_name: str, experiment_id: str) -> str:
    """Base assistant run folder: ``{domain}_{experiment}`` (no Mac suffix)."""
    safe_domain = sanitize_config_token(domain_name)
    safe_expid = sanitize_config_token(experiment_id)
    return f"{safe_domain}_{safe_expid}".strip("_")


def parse_mac_duplicate_suffix(name: str) -> tuple[str, int | None]:
    """Split ``name (2)`` into ``(name, 2)``; plain ``name`` returns ``(name, None)``."""
    text = str(name or "").strip()
    match = _MAC_DUP_SUFFIX_RE.search(text)
    if not match:
        return text, None
    base = text[: match.start()]
    return base, int(match.group(1))


def symfluence_domain_mac_suffix(symfluence_domain: str) -> tuple[str, int | None]:
    return parse_mac_duplicate_suffix(str(symfluence_domain or "").strip())


def symfluence_domain_for_run_folder(
    run_folder: str,
    basin_domain: str,
    experiment_id: str,
) -> str:
    """Map assistant ``runs/`` folder name to SYMFLUENCE ``DOMAIN_NAME``."""
    run_folder = str(run_folder or "").strip()
    basin = sanitize_config_token(basin_domain) or str(basin_domain or "").strip()
    base_run = preview_run_folder_name(basin, experiment_id)
    if run_folder == base_run:
        return basin
    base_part, suffix_n = parse_mac_duplicate_suffix(run_folder)
    if base_part == base_run and suffix_n is not None:
        return f"{basin} ({suffix_n})"
    suffix_n = _portable_duplicate_suffix(run_folder, base_run)
    if suffix_n is not None:
        return f"{basin}_{suffix_n}"
    return basin


def basin_domain_for_run_folder(
    run_folder: str,
    symfluence_domain: str,
    experiment_id: str,
) -> str:
    """Recover the base basin for a duplicate assistant workspace."""
    domain = str(symfluence_domain or "").strip()
    legacy_basin, legacy_n = symfluence_domain_mac_suffix(domain)
    if legacy_n is not None:
        return legacy_basin

    run_text = str(run_folder or "").strip()
    match = re.search(r"_(\d+)$", run_text)
    if not match:
        return domain
    suffix_n = match.group(1)
    domain_suffix = f"_{suffix_n}"
    if not domain.endswith(domain_suffix):
        return domain
    basin = domain[: -len(domain_suffix)]
    expected_run = f"{preview_run_folder_name(basin, experiment_id)}_{suffix_n}"
    return basin if run_text == expected_run else domain


def find_assistant_run_for_domain(
    symfluence_domain: str, experiment_id: str, runs_dir: Path,
    *, data_dir: Path | None = None,
) -> str | None:
    """Resolve portable duplicate names using saved config, never numeric guesses."""
    import yaml

    matches: list[str] = []
    for config_path in sorted(runs_dir.glob("*/config.yaml")):
        if config_path.parent.name.startswith("_"):
            continue
        try:
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(cfg, dict):
            continue
        if (str(cfg.get("DOMAIN_NAME", "")).strip() != symfluence_domain
                or str(cfg.get("EXPERIMENT_ID", "")).strip() != experiment_id):
            continue
        saved_data = str(cfg.get("SYMFLUENCE_DATA_DIR") or "").strip()
        if data_dir is not None and saved_data.lower() not in {"", "default"}:
            if Path(saved_data).expanduser().resolve() != data_dir.resolve():
                continue
        matches.append(config_path.parent.name)
    if len(matches) > 1:
        raise ValueError("Multiple saved runs reference this domain and experiment; select the assistant run explicitly: "
                         + ", ".join(matches))
    return matches[0] if matches else None


def run_folder_for_symfluence_domain(
    symfluence_domain: str, experiment_id: str, runs_dir: Path | None = None,
) -> str:
    """Use saved metadata for duplicates, preserving numeric basin names otherwise."""
    if runs_dir is not None:
        saved = find_assistant_run_for_domain(symfluence_domain, experiment_id, runs_dir)
        if saved is not None:
            return saved
    basin, suffix_n = symfluence_domain_mac_suffix(symfluence_domain)
    base_run = preview_run_folder_name(basin, experiment_id)
    if suffix_n is None:
        return base_run
    return f"{base_run} ({suffix_n})"


def run_folder_belongs_to_workspace(
    run_folder: str,
    basin_domain: str,
    experiment_id: str,
) -> bool:
    """True when ``run_folder`` is the base or a recognized duplicate."""
    run_folder = str(run_folder or "").strip()
    if not run_folder:
        return False
    base_run = preview_run_folder_name(basin_domain, experiment_id)
    if run_folder == base_run:
        return True
    base_part, mac_n = parse_mac_duplicate_suffix(run_folder)
    if mac_n is not None and base_part == base_run:
        return True
    return _portable_duplicate_suffix(run_folder, base_run) is not None


def symfluence_data_dir_name(symfluence_domain: str) -> str:
    return f"domain_{symfluence_domain}"


def symfluence_data_path(data_dir: Path, symfluence_domain: str) -> Path:
    return data_dir / symfluence_data_dir_name(symfluence_domain)


def assistant_run_is_established(run_folder: str, runs_dir: Path) -> bool:
    """True when the user is continuing an existing assistant run folder."""
    run_folder = str(run_folder or "").strip()
    if not run_folder:
        return False
    run_dir = runs_dir / run_folder
    if not run_dir.is_dir():
        return False
    markers = ("config.yaml", "plan.json", "spec.json")
    return any((run_dir / name).is_file() for name in markers)


def is_run_workspace_taken(
    run_folder: str,
    symfluence_domain: str,
    *,
    runs_dir: Path,
    data_dir: Path,
    reuse_existing_domain_data: bool = False,
    exclude_run_folders: frozenset[str] | None = None,
) -> bool:
    run_folder = str(run_folder or "").strip()
    symfluence_domain = str(symfluence_domain or "").strip()
    if not run_folder or not symfluence_domain:
        return False
    if (runs_dir / run_folder).exists():
        if exclude_run_folders and run_folder in exclude_run_folders:
            pass
        else:
            return True
    if reuse_existing_domain_data:
        return False
    return symfluence_data_path(data_dir, symfluence_domain).exists()


def is_placeholder_assistant_run_folder(run_folder: str, experiment_id: str = "") -> bool:
    """True when the assistant run folder was allocated before a real domain was known."""
    run_folder = str(run_folder or "").strip()
    if not run_folder:
        return False
    expid = sanitize_config_token(experiment_id)
    if expid and run_folder_belongs_to_workspace(run_folder, PLACEHOLDER_BASIN, expid):
        return True
    if run_folder_belongs_to_workspace(run_folder, PLACEHOLDER_BASIN, PLACEHOLDER_EXPERIMENT):
        return True
    base_part, _ = parse_mac_duplicate_suffix(run_folder)
    if base_part == PLACEHOLDER_BASIN:
        return True
    prefix = f"{PLACEHOLDER_BASIN}_"
    if base_part.startswith(prefix):
        suffix = base_part[len(prefix) :]
        if suffix in (PLACEHOLDER_EXPERIMENT, expid) or (expid and suffix == expid):
            return True
    return False


def placeholder_run_needs_rename(
    run_folder: str,
    basin_domain: str,
    experiment_id: str,
) -> bool:
    basin = sanitize_config_token(basin_domain) or str(basin_domain or "").strip()
    expid = sanitize_config_token(experiment_id) or str(experiment_id or "").strip()
    run_folder = str(run_folder or "").strip()
    if not run_folder or not basin or not expid:
        return False
    if basin == PLACEHOLDER_BASIN:
        return False
    if run_folder_belongs_to_workspace(run_folder, basin, expid):
        return False
    return is_placeholder_assistant_run_folder(run_folder, expid)


def _allocate_unique_run_folder_excluding(
    basin_domain: str,
    experiment_id: str,
    runs_dir: Path,
    data_dir: Path,
    *,
    reuse_existing_domain_data: bool = False,
    exclude_run_folders: frozenset[str] | None = None,
) -> str:
    basin = sanitize_config_token(basin_domain) or str(basin_domain or "").strip()
    expid = sanitize_config_token(experiment_id) or str(experiment_id or "").strip()
    base_run = preview_run_folder_name(basin, expid)

    if not is_run_workspace_taken(
        base_run,
        basin,
        runs_dir=runs_dir,
        data_dir=data_dir,
        reuse_existing_domain_data=reuse_existing_domain_data,
        exclude_run_folders=exclude_run_folders,
    ):
        return base_run

    for n in range(1, 1000):
        candidate = f"{base_run}_{n}"
        sym_domain = f"{basin}_{n}"
        portable_taken = is_run_workspace_taken(
            candidate,
            sym_domain,
            runs_dir=runs_dir,
            data_dir=data_dir,
            reuse_existing_domain_data=False,
            exclude_run_folders=exclude_run_folders,
        )
        legacy_taken = is_run_workspace_taken(
            f"{base_run} ({n})",
            f"{basin} ({n})",
            runs_dir=runs_dir,
            data_dir=data_dir,
            reuse_existing_domain_data=False,
            exclude_run_folders=exclude_run_folders,
        )
        if not portable_taken and not legacy_taken:
            return candidate

    raise RuntimeError(
        f"Could not allocate a unique run folder for {basin} / {expid} "
        f"(exhausted 999 numbered duplicates)."
    )


def rename_placeholder_assistant_run_folder(
    run_folder: str,
    basin_domain: str,
    experiment_id: str,
    *,
    runs_dir: Path,
    data_dir: Path,
    reuse_existing_domain_data: bool = False,
) -> str:
    """
    Move a placeholder ``domain_<experiment>`` assistant folder to ``{basin}_{experiment}``.

    Returns the new folder name, or the original name when no rename is performed.
    """
    run_folder = str(run_folder or "").strip()
    basin = sanitize_config_token(basin_domain) or str(basin_domain or "").strip()
    expid = sanitize_config_token(experiment_id) or str(experiment_id or "").strip()
    if not placeholder_run_needs_rename(run_folder, basin, expid):
        return run_folder

    old_dir = runs_dir / run_folder
    if not old_dir.is_dir():
        return run_folder

    new_folder = _allocate_unique_run_folder_excluding(
        basin,
        expid,
        runs_dir,
        data_dir,
        reuse_existing_domain_data=reuse_existing_domain_data,
        exclude_run_folders=frozenset({run_folder}),
    )
    if new_folder == run_folder:
        return run_folder

    new_dir = runs_dir / new_folder
    if new_dir.exists():
        raise RuntimeError(
            f"Cannot rename assistant run folder `{run_folder}` to `{new_folder}`: "
            "destination already exists."
        )

    runs_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_dir), str(new_dir))
    return new_folder


def allocate_unique_run_folder(
    basin_domain: str,
    experiment_id: str,
    runs_dir: Path,
    data_dir: Path,
    *,
    reuse_existing_domain_data: bool = False,
) -> str:
    """
    Return the first free run folder using portable ``_1``, ``_2``, … suffixes.

    When ``reuse_existing_domain_data`` is true, an existing ``domain_<basin>/`` folder
    does not force a numbered duplicate; only ``runs/<folder>/`` collisions do.
    """
    return _allocate_unique_run_folder_excluding(
        basin_domain, experiment_id, runs_dir, data_dir,
        reuse_existing_domain_data=reuse_existing_domain_data,
    )


def resolve_run_workspace(
    basin_domain: str,
    experiment_id: str,
    run_folder: str,
    *,
    runs_dir: Path,
    data_dir: Path,
    workspace_locked: bool = False,
    reuse_existing_domain_data: bool = False,
) -> tuple[str, str]:
    """
    Return ``(run_folder, symfluence_domain)`` without clobbering existing workspaces.

    Rules:
    - Locked or already-established folders are kept.
    - Existing legacy ``(n)`` and portable ``_n`` names are kept once chosen.
    - Only the base ``{domain}_{experiment}`` name is upgraded to ``_1`` when taken.
    - Empty session state allocates the first free name once.
    """
    basin = sanitize_config_token(basin_domain) or str(basin_domain or "").strip()
    expid = sanitize_config_token(experiment_id) or str(experiment_id or "").strip()
    run_folder = str(run_folder or "").strip()
    base_run = preview_run_folder_name(basin, expid)

    if basin and expid and basin != PLACEHOLDER_BASIN:
        run_folder = rename_placeholder_assistant_run_folder(
            run_folder,
            basin,
            expid,
            runs_dir=runs_dir,
            data_dir=data_dir,
            reuse_existing_domain_data=reuse_existing_domain_data,
        )

    if workspace_locked and run_folder:
        sym_domain = symfluence_domain_for_run_folder(run_folder, basin, expid)
        return run_folder, sym_domain

    if run_folder and assistant_run_is_established(run_folder, runs_dir):
        sym_domain = symfluence_domain_for_run_folder(run_folder, basin, expid)
        return run_folder, sym_domain

    if run_folder and run_folder_belongs_to_workspace(run_folder, basin, expid):
        sym_domain = symfluence_domain_for_run_folder(run_folder, basin, expid)
        _, mac_n = parse_mac_duplicate_suffix(run_folder)
        if mac_n is not None:
            return run_folder, sym_domain
        if run_folder == base_run and is_run_workspace_taken(
            run_folder,
            sym_domain,
            runs_dir=runs_dir,
            data_dir=data_dir,
            reuse_existing_domain_data=reuse_existing_domain_data,
        ):
            run_folder = allocate_unique_run_folder(
                basin,
                expid,
                runs_dir,
                data_dir,
                reuse_existing_domain_data=reuse_existing_domain_data,
            )
            sym_domain = symfluence_domain_for_run_folder(run_folder, basin, expid)
        return run_folder, sym_domain

    run_folder = allocate_unique_run_folder(
        basin,
        expid,
        runs_dir,
        data_dir,
        reuse_existing_domain_data=reuse_existing_domain_data,
    )
    sym_domain = symfluence_domain_for_run_folder(run_folder, basin, expid)
    return run_folder, sym_domain
