"""Backward-compatible wrappers around the new ui.theme modules."""

from __future__ import annotations

from ui.theme import build_palette, build_stylesheet
from ui.theme_tokens import DEFAULT_THEME, ThemeTokens

TOKENS = DEFAULT_THEME.colors

__all__ = ["TOKENS", "ThemeTokens", "build_palette", "build_stylesheet"]

