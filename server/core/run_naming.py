"""Mac-style duplicate naming for assistant runs and SYMFLUENCE data domains."""
# Layout note: minor UI spacing tweaks.

from __future__ import annotations

import re
import shutil
from pathlib import Path

PLACEHOLDER_BASIN = "domain"
PLACEHOLDER_EXPERIMENT = "exp"

_MAC_DUP_SUFFIX_RE = re.compile(r" \((\d+)\)$")


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
    return basin


def run_folder_for_symfluence_domain(symfluence_domain: str, experiment_id: str) -> str:
    """Map SYMFLUENCE ``DOMAIN_NAME`` back to assistant run folder name."""
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
    """True when ``run_folder`` is the base or Mac-style duplicate for this domain + experiment."""
    run_folder = str(run_folder or "").strip()
    if not run_folder:
        return False
    base_run = preview_run_folder_name(basin_domain, experiment_id)
    if run_folder == base_run:
        return True
    base_part, mac_n = parse_mac_duplicate_suffix(run_folder)
    return mac_n is not None and base_part == base_run


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
    _, mac_n = symfluence_domain_mac_suffix(symfluence_domain)
    if mac_n is not None:
        return symfluence_data_path(data_dir, symfluence_domain).exists()
    return False


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
        candidate = f"{base_run} ({n})"
        sym_domain = f"{basin} ({n})"
        if not is_run_workspace_taken(
            candidate,
            sym_domain,
            runs_dir=runs_dir,
            data_dir=data_dir,
            reuse_existing_domain_data=False,
            exclude_run_folders=exclude_run_folders,
        ):
            return candidate

    raise RuntimeError(
        f"Could not allocate a unique run folder for {basin} / {expid} "
        f"(exhausted 999 Mac-style duplicates)."
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
    Return the first free run folder using Finder-style ``(1)``, ``(2)``, … suffixes.

    When ``reuse_existing_domain_data`` is true, an existing ``domain_<basin>/`` folder
    does not force a Mac-style duplicate; only ``runs/<folder>/`` collisions do.
    """
    basin = sanitize_config_token(basin_domain) or str(basin_domain or "").strip()
    expid = sanitize_config_token(experiment_id) or str(experiment_id or "").strip()
    base_run = preview_run_folder_name(basin, expid)

    if not is_run_workspace_taken(
        base_run,
        basin,
        runs_dir=runs_dir,
        data_dir=data_dir,
        reuse_existing_domain_data=reuse_existing_domain_data,
    ):
        return base_run

    for n in range(1, 1000):
        candidate = f"{base_run} ({n})"
        sym_domain = f"{basin} ({n})"
        if not is_run_workspace_taken(
            candidate,
            sym_domain,
            runs_dir=runs_dir,
            data_dir=data_dir,
            reuse_existing_domain_data=False,
        ):
            return candidate

    raise RuntimeError(
        f"Could not allocate a unique run folder for {basin} / {expid} "
        f"(exhausted 999 Mac-style duplicates)."
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
    - Mac-style ``(n)`` names, once chosen, are never bumped to ``(n+1)``.
    - Only the base ``{domain}_{experiment}`` name is upgraded to ``(1)`` when taken.
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
