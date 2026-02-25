"""Text helpers for robust UI rendering."""

from __future__ import annotations

from typing import Any


def safe_text(value: Any) -> str:
    """Return a display-safe text value for Qt widgets."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)

