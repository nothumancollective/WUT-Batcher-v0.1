"""Shared constants for runner compatibility and constraint evaluation."""

from __future__ import annotations

from typing import Final, Tuple


DEFAULT_RUNNER_MODE: Final[str] = "AkabakImportFixedSource"
SUPPORTED_RUNNER_MODES: Final[Tuple[str, ...]] = (
    DEFAULT_RUNNER_MODE,
    "AthGuidePreview",
)

# Required in every generated CFG for AKABAK import compatibility.
MANDATORY_SOURCE_BLOCK: Final[Tuple[tuple[str, object], ...]] = (
    ("ABEC.AkabakMode", 1),
    ("LE", "generic25"),
    ("LE.Voltage", 1.0),
)

# Keys that must be hidden/locked when runner compatibility mode is active.
RUNNER_LOCKED_OR_HIDDEN_KEYS: Final[Tuple[str, ...]] = (
    "ABEC.AkabakMode",
    "LE",
    "LE.Voltage",
    "Source.Shape",
    "Source.Radius",
    "Source.Curv",
    "Source.Contours",
    "Source.Velocity",
)

# Preview pipeline hard paths / retention policy.
ATH_PREVIEW_CFG_DIR: Final[str] = r"C:\Tools\ATH"
ATH_PREVIEW_EXPORT_ROOT: Final[str] = r"C:\Horns"
ATH_PREVIEW_CFG_NAME: Final[str] = "preview_current.cfg"
PREVIEW_CACHE_APPDIR: Final[Tuple[str, ...]] = ("WUTBatcher", "preview_cache")
PREVIEW_CACHE_KEEP_FILES: Final[int] = 10
PREVIEW_CACHE_MAX_AGE_DAYS: Final[int] = 7

# Batch planning guardrails. Compatibility previews must stay responsive even
# when combined sweeps describe a very large Cartesian product. The full
# resolver keeps a higher hard limit to prevent accidental memory/disk
# exhaustion during materialization.
MAX_PREVIEW_VALIDATED_VERSIONS: Final[int] = 250
MAX_BATCH_VERSIONS: Final[int] = 10_000
