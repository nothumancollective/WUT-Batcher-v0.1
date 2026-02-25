"""Runtime feature flag helpers."""

from __future__ import annotations

import os


_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = str(os.environ.get(name, "")).strip().lower()
    if not value:
        return bool(default)
    return value in _TRUE_VALUES


def use_project_library_storage() -> bool:
    """Enable new Project Library layout and identifiers.

    Default is off for safe rollout.
    """

    return _env_flag("USE_PROJECT_LIBRARY_STORAGE", default=False)
