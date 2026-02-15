"""Guarded cleanup helpers for version-local working directories."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from typing import Iterable, List


@dataclass(frozen=True)
class CleanupResult:
    target: str
    deleted: bool
    reason: str


def _normalize(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_protected_path(path: Path) -> bool:
    drive_root = Path(path.anchor) if path.anchor else None
    if drive_root is not None and path == drive_root:
        return True
    # Refuse suspiciously short absolute paths like C:\foo
    if len(path.parts) <= 2:
        return True
    return False


def guarded_delete_tree(
    target_path: str | Path,
    *,
    allowed_root: str | Path,
    expected_dir_name: str | None = None,
    perform_delete: bool = True,
    deny_paths: Iterable[str | Path] = (),
) -> CleanupResult:
    target = _normalize(target_path)
    allowed = _normalize(allowed_root)
    denied: List[Path] = [_normalize(value) for value in deny_paths]

    if not target.exists():
        return CleanupResult(target=str(target), deleted=False, reason="target_missing")
    if not target.is_dir():
        return CleanupResult(target=str(target), deleted=False, reason="target_not_directory")
    if _is_protected_path(target):
        return CleanupResult(target=str(target), deleted=False, reason="target_protected")
    if target == allowed:
        return CleanupResult(target=str(target), deleted=False, reason="target_equals_allowed_root")
    if not target.is_relative_to(allowed):
        return CleanupResult(target=str(target), deleted=False, reason="outside_allowed_root")
    if len(target.parts) <= len(allowed.parts):
        return CleanupResult(target=str(target), deleted=False, reason="target_too_shallow")
    if expected_dir_name and target.name != expected_dir_name:
        return CleanupResult(target=str(target), deleted=False, reason="unexpected_dir_name")
    if any(target == denied_path for denied_path in denied):
        return CleanupResult(target=str(target), deleted=False, reason="target_in_deny_paths")

    if not perform_delete:
        return CleanupResult(target=str(target), deleted=False, reason="dry_run_no_delete")

    shutil.rmtree(target)
    return CleanupResult(target=str(target), deleted=True, reason="deleted")


def _default_workspace_deny_paths(workspace_root: Path) -> List[Path]:
    paths: List[Path] = []
    env_candidates = (
        os.environ.get("WINDIR"),
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMDATA"),
    )
    for raw in env_candidates:
        if not raw:
            continue
        candidate = Path(raw).expanduser().resolve()
        paths.append(candidate)
    paths.append(Path.home().expanduser().resolve())
    drive_root = Path(workspace_root.anchor) if workspace_root.anchor else None
    if drive_root is not None:
        paths.append(drive_root)
    dedup: List[Path] = []
    for path in paths:
        if path not in dedup:
            dedup.append(path)
    return dedup


def guarded_delete_tree_in_workspace(
    target_path: str | Path,
    *,
    workspace_root: str | Path,
    expected_dir_name: str | None = None,
    expected_parent_name: str | None = None,
    perform_delete: bool = True,
    deny_paths: Iterable[str | Path] = (),
) -> CleanupResult:
    target_raw = Path(target_path).expanduser()
    workspace_raw = Path(workspace_root).expanduser()
    if not target_raw.is_absolute():
        return CleanupResult(target=str(target_raw), deleted=False, reason="target_not_absolute")
    if not workspace_raw.is_absolute():
        return CleanupResult(target=str(workspace_raw), deleted=False, reason="workspace_root_not_absolute")

    target = target_raw.resolve()
    workspace = workspace_raw.resolve()

    if not workspace.exists() or not workspace.is_dir():
        return CleanupResult(target=str(target), deleted=False, reason="workspace_root_missing")
    if not target.exists():
        return CleanupResult(target=str(target), deleted=False, reason="target_missing")
    if not target.is_dir():
        return CleanupResult(target=str(target), deleted=False, reason="target_not_directory")
    if _is_protected_path(target):
        return CleanupResult(target=str(target), deleted=False, reason="target_protected")
    if target == workspace:
        return CleanupResult(target=str(target), deleted=False, reason="target_equals_workspace_root")
    if not target.is_relative_to(workspace):
        return CleanupResult(target=str(target), deleted=False, reason="outside_workspace_root")
    if len(target.parts) <= len(workspace.parts):
        return CleanupResult(target=str(target), deleted=False, reason="target_too_shallow")
    if expected_parent_name and target.parent.name != expected_parent_name:
        return CleanupResult(target=str(target), deleted=False, reason="unexpected_parent_name")
    if expected_dir_name and target.name != expected_dir_name:
        return CleanupResult(target=str(target), deleted=False, reason="unexpected_dir_name")

    denied = _default_workspace_deny_paths(workspace)
    denied.extend(_normalize(value) for value in deny_paths)
    if any(target == denied_path for denied_path in denied):
        return CleanupResult(target=str(target), deleted=False, reason="target_in_deny_paths")

    if not perform_delete:
        return CleanupResult(target=str(target), deleted=False, reason="dry_run_no_delete")

    shutil.rmtree(target)
    return CleanupResult(target=str(target), deleted=True, reason="deleted")


def guarded_delete_file_in_workspace(
    target_path: str | Path,
    *,
    workspace_root: str | Path,
    expected_parent_name: str | None = None,
    perform_delete: bool = True,
    deny_paths: Iterable[str | Path] = (),
) -> CleanupResult:
    target_raw = Path(target_path).expanduser()
    workspace_raw = Path(workspace_root).expanduser()
    if not target_raw.is_absolute():
        return CleanupResult(target=str(target_raw), deleted=False, reason="target_not_absolute")
    if not workspace_raw.is_absolute():
        return CleanupResult(target=str(workspace_raw), deleted=False, reason="workspace_root_not_absolute")

    target = target_raw.resolve()
    workspace = workspace_raw.resolve()
    if not workspace.exists() or not workspace.is_dir():
        return CleanupResult(target=str(target), deleted=False, reason="workspace_root_missing")
    if not target.exists():
        return CleanupResult(target=str(target), deleted=False, reason="target_missing")
    if not target.is_file():
        return CleanupResult(target=str(target), deleted=False, reason="target_not_file")
    if not target.is_relative_to(workspace):
        return CleanupResult(target=str(target), deleted=False, reason="outside_workspace_root")
    if expected_parent_name and target.parent.name != expected_parent_name:
        return CleanupResult(target=str(target), deleted=False, reason="unexpected_parent_name")

    denied = _default_workspace_deny_paths(workspace)
    denied.extend(_normalize(value) for value in deny_paths)
    if any(target == denied_path for denied_path in denied):
        return CleanupResult(target=str(target), deleted=False, reason="target_in_deny_paths")

    if not perform_delete:
        return CleanupResult(target=str(target), deleted=False, reason="dry_run_no_delete")

    target.unlink()
    return CleanupResult(target=str(target), deleted=True, reason="deleted")
