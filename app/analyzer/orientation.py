"""Analyzer-side orientation canonicalization and query alias helpers."""

from __future__ import annotations

from typing import Any, List, Optional, Set


def _parse_x3_numeric(token: str) -> Optional[float]:
    text = str(token or "").strip()
    if not text:
        return None
    upper = text.upper()
    if upper.startswith("X3_"):
        text = text[3:]
    try:
        return float(text)
    except Exception:
        return None


def _is_close(value: float, target: float, tol: float = 1.0e-6) -> bool:
    return abs(float(value) - float(target)) <= float(tol)


def canonical_orientation_token(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    upper = token.upper()
    if upper in {"H", "V", "D"}:
        return upper

    numeric = _parse_x3_numeric(upper)
    if numeric is None:
        return upper
    if _is_close(numeric, 0.0):
        return "H"
    if _is_close(numeric, 90.0):
        return "V"
    # VACS diagonal exports can appear as either 42deg or 45deg markers.
    if _is_close(numeric, 42.0) or _is_close(numeric, 45.0):
        return "D"

    if upper.startswith("X3_"):
        return upper
    if _is_close(numeric, round(numeric)):
        return f"X3_{int(round(numeric))}"
    compact = f"{numeric:.6f}".rstrip("0").rstrip(".")
    return f"X3_{compact}"


def orientation_query_aliases(plane: str) -> List[str]:
    canonical = canonical_orientation_token(plane)
    if canonical == "H":
        return ["H", "X3_0", "X3_0.0"]
    if canonical == "V":
        return ["V", "X3_90", "X3_90.0"]
    if canonical == "D":
        return ["D", "X3_42", "X3_42.0", "X3_45", "X3_45.0"]
    return [canonical] if canonical else []


def dedupe_orientations(values: List[str]) -> List[str]:
    order = {"H": 0, "V": 1, "D": 2}
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        token = canonical_orientation_token(value)
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return sorted(result, key=lambda token: (order.get(token, 99), token))
