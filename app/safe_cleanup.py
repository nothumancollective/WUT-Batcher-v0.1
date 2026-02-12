"""Guarded cleanup helpers for version-local working directories."""

from __future__ import annotations

from dataclasses import dataclass
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
    if any(target == denied_path for denied_path in denied):
        return CleanupResult(target=str(target), deleted=False, reason="target_in_deny_paths")

    shutil.rmtree(target)
    return CleanupResult(target=str(target), deleted=True, reason="deleted")
