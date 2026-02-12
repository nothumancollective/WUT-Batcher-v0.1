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
