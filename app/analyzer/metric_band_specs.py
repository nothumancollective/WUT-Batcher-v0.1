"""Canonical KPI metric-band specs and spec-to-region mapping helpers."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

LOWER_IS_BETTER = "LOWER_IS_BETTER"
HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
TARGET_IS_BEST = "TARGET_IS_BEST"
RANGE_IS_BEST = "RANGE_IS_BEST"


# Source of truth:
# - docs/analyzer/03_kpi_scoring_model.md (direction + soft caps)
# - existing analyzer thresholds in app/gui.py stage styles
KPI_BAND_SPECS: Dict[str, Dict[str, Any]] = {
    "b_pc_oct": {
        "kpi_key": "b_pc_oct",
        "direction": HIGHER_IS_BETTER,
        "target_value": 3.0,
        "units": "oct",
    },
    "e_bw": {
        "kpi_key": "e_bw",
        "direction": TARGET_IS_BEST,
        "target_value": 0.0,
        "warn_range": (0.0, 20.0),
        "units": "deg",
    },
    "e_cov": {
        "kpi_key": "e_cov",
        "direction": LOWER_IS_BETTER,
        "target_value": 0.0,
        "warn_range": (0.0, 6.0),
        "units": "dB",
    },
    "r_spill": {
        "kpi_key": "r_spill",
        "direction": LOWER_IS_BETTER,
        "units": "ratio",
    },
    "di_proxy": {
        "kpi_key": "di_proxy",
        "direction": HIGHER_IS_BETTER,
        "target_value": 6.0,
        "good_range": (4.0, None),
        "warn_range": (2.0, 4.0),
        "thresholds": [2.0, 4.0],
        "units": "dB",
    },
    "s_theta": {
        "kpi_key": "s_theta",
        "direction": LOWER_IS_BETTER,
        "target_value": 0.0,
        "good_range": (0.0, 0.20),
        "warn_range": (0.20, 0.40),
        "thresholds": [0.20, 0.40],
        "units": "RMS",
    },
    "e_sym_shape": {
        "kpi_key": "e_sym_shape",
        "direction": LOWER_IS_BETTER,
        "target_value": 0.0,
        "good_range": (0.0, 0.35),
        "warn_range": (0.35, 0.75),
        "thresholds": [0.35, 0.75],
        "units": "spread",
    },
    "r_off": {
        "kpi_key": "r_off",
        "direction": LOWER_IS_BETTER,
        "target_value": 0.0,
        "good_range": (0.0, 2.0),
        "warn_range": (2.0, 4.0),
        "bad_range": (4.0, 6.0),
        "thresholds": [2.0, 4.0, 6.0],
        "hotspot_threshold": 6.0,
        "units": "dB",
    },
}


def metric_band_spec_for_key(metric_key: str) -> Optional[Dict[str, Any]]:
    token = str(metric_key or "").strip().lower()
    spec = KPI_BAND_SPECS.get(token)
    if not isinstance(spec, Mapping):
        return None
    return dict(spec)


def metric_band_help_sentence(spec: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(spec, Mapping):
        return ""
    direction = str(spec.get("direction") or "").strip().upper()
    if direction == LOWER_IS_BETTER:
        return "Metric band shows KPI spec zones; lower values are better."
    if direction == HIGHER_IS_BETTER:
        return "Metric band shows KPI spec zones; higher values are better."
    if direction == TARGET_IS_BEST:
        return "Metric band shows the target-centered spec zone; values near target are better."
    if direction == RANGE_IS_BEST:
        return "Metric band marks the preferred spec window; values inside the range are better."
    return ""


def metric_band_thresholds_from_spec(spec: Optional[Mapping[str, Any]]) -> List[float]:
    if not isinstance(spec, Mapping):
        return []
    explicit = list(spec.get("thresholds", []) or [])
    values: List[float] = []
    for item in explicit:
        try:
            value = float(item)
        except Exception:
            continue
        if math.isfinite(value):
            values.append(float(value))
    if values:
        return sorted(set(values))
    for key in ("good_range", "warn_range", "bad_range"):
        parsed = _coerce_band_range(spec.get(key))
        if parsed is None:
            continue
        low, high = parsed
        if low is not None:
            values.append(float(low))
        if high is not None:
            values.append(float(high))
    return sorted(set(values))


def metric_band_anchor_values(spec: Optional[Mapping[str, Any]]) -> List[float]:
    if not isinstance(spec, Mapping):
        return []
    values: List[float] = []
    target = _coerce_finite(spec.get("target_value"))
    if target is not None:
        values.append(float(target))
    for key in ("good_range", "warn_range", "bad_range"):
        parsed = _coerce_band_range(spec.get(key))
        if parsed is None:
            continue
        low, high = parsed
        if low is not None:
            values.append(float(low))
        if high is not None:
            values.append(float(high))
    values.extend(metric_band_thresholds_from_spec(spec))
    return sorted(set(values))


def metric_band_regions_from_spec(
    *,
    spec: Optional[Mapping[str, Any]],
    axis_min: float,
    axis_max: float,
) -> Dict[str, List[Dict[str, float]]]:
    if not isinstance(spec, Mapping):
        return {"regions": [], "reference_lines": []}
    lo_axis = float(axis_min)
    hi_axis = float(axis_max)
    if not (math.isfinite(lo_axis) and math.isfinite(hi_axis) and hi_axis > lo_axis):
        return {"regions": [], "reference_lines": []}
    direction = str(spec.get("direction") or "").strip().upper()
    good_range = _coerce_band_range(spec.get("good_range"))
    warn_range = _coerce_band_range(spec.get("warn_range"))
    target = _coerce_finite(spec.get("target_value"))
    regions: List[Dict[str, float]] = []
    reference_lines: List[float] = []

    def _append(role: str, interval: Optional[Tuple[float, float]]) -> None:
        if interval is None:
            return
        region_lo, region_hi = interval
        if not (math.isfinite(region_lo) and math.isfinite(region_hi) and region_hi > region_lo):
            return
        regions.append({"role": str(role), "y_low": float(region_lo), "y_high": float(region_hi)})

    if direction in {LOWER_IS_BETTER, HIGHER_IS_BETTER, RANGE_IS_BEST}:
        _append("good", _clip_interval(good_range, lo_axis, hi_axis))
        _append("warn", _clip_interval(warn_range, lo_axis, hi_axis))
    elif direction == TARGET_IS_BEST:
        good_interval = _clip_interval(good_range, lo_axis, hi_axis)
        warn_interval = _clip_interval(warn_range, lo_axis, hi_axis)
        _append("good", good_interval)
        if warn_interval is not None and good_interval is not None:
            warn_lo, warn_hi = warn_interval
            good_lo, good_hi = good_interval
            _append("warn", _clip_interval((warn_lo, min(warn_hi, good_lo)), lo_axis, hi_axis))
            _append("warn", _clip_interval((max(warn_lo, good_hi), warn_hi), lo_axis, hi_axis))
        else:
            _append("warn", warn_interval)

    if not regions and target is not None and lo_axis <= target <= hi_axis:
        reference_lines.append(float(target))
    return {"regions": regions, "reference_lines": sorted(set(reference_lines))}


def _coerce_finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if not math.isfinite(parsed):
        return None
    return float(parsed)


def _coerce_band_range(value: Any) -> Optional[Tuple[Optional[float], Optional[float]]]:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    low = _coerce_finite(value[0])
    high = _coerce_finite(value[1])
    if low is None and high is None:
        return None
    if low is not None and high is not None and high <= low:
        return None
    return (low, high)


def _clip_interval(
    interval: Optional[Tuple[Optional[float], Optional[float]]],
    axis_min: float,
    axis_max: float,
) -> Optional[Tuple[float, float]]:
    if interval is None:
        return None
    low, high = interval
    low_value = float(axis_min) if low is None else max(float(axis_min), float(low))
    high_value = float(axis_max) if high is None else min(float(axis_max), float(high))
    if not (math.isfinite(low_value) and math.isfinite(high_value) and high_value > low_value):
        return None
    return (float(low_value), float(high_value))

