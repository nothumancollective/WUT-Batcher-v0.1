"""Theme design tokens (single source of truth)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class ThemeTokens:
    colors: Dict[str, str]
    spacing: Dict[str, int]
    radii: Dict[str, int]
    typography: Dict[str, object]


DEFAULT_THEME = ThemeTokens(
    colors={
        "bg": "#121212",
        "surface": "#1B1B1B",
        "surface2": "#202020",
        "sidebar": "#0D0D0D",
        "border": "#373737",
        "text": "#F1F1F1",
        "muted": "#B6B6B6",
        "selection": "#EBEBEB",
        "accent": "#8D8D8D",
        "button_bg": "#FFFFFF",
        "button_text": "#1A1A1A",
        "button_border": "#CFCFCF",
        "button_hover": "#F2F2F2",
        "button_pressed": "#E4E4E4",
        "button_disabled": "#CCCCCC",
        "success": "#6CB080",
        "warning": "#D8B868",
        "danger": "#C86A6A",
        "risk_warn": "#D6A84B",
        "risk_fatal": "#C86A6A",
        "risk_ok": "#5F9A74",
    },
    spacing={
        "xs": 4,
        "sm": 8,
        "md": 12,
        "lg": 16,
        "xl": 24,
        "xxl": 32,
    },
    radii={
        "sm": 6,
        "md": 8,
        "lg": 12,
    },
    typography={
        "font_family_primary": "Condor",
        "font_fallback": ("Segoe UI", "Arial"),
        "font_size_base": 13,
    },
)


def font_family_stack(tokens: ThemeTokens = DEFAULT_THEME) -> Tuple[str, ...]:
    primary = str(tokens.typography.get("font_family_primary", "Condor"))
    fallbacks = tuple(tokens.typography.get("font_fallback", ("Segoe UI", "Arial")))  # type: ignore[arg-type]
    return (primary, *fallbacks)

