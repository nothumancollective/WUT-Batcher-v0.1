"""Static presets for Analyzer Batch Review (MVP)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

ALGO_VERSION = "analyzer-mvp-2a-v3"

DEFAULT_TOL_DEG = 5.0

COVERAGE_PRESETS: List[Dict[str, Any]] = [
    {"id": "90x40", "label": "90 x 40", "h_deg": 90.0, "v_deg": 40.0},
    {"id": "60x60", "label": "60 x 60", "h_deg": 60.0, "v_deg": 60.0},
    {"id": "60x40", "label": "60 x 40", "h_deg": 60.0, "v_deg": 40.0},
    {"id": "90x60", "label": "90 x 60", "h_deg": 90.0, "v_deg": 60.0},
    {"id": "80x40", "label": "80 x 40", "h_deg": 80.0, "v_deg": 40.0},
    {"id": "75x50", "label": "75 x 50", "h_deg": 75.0, "v_deg": 50.0},
    {"id": "60x30", "label": "60 x 30", "h_deg": 60.0, "v_deg": 30.0},
    {"id": "50x50", "label": "50 x 50", "h_deg": 50.0, "v_deg": 50.0},
    {"id": "40x40", "label": "40 x 40", "h_deg": 40.0, "v_deg": 40.0},
]
DEFAULT_COVERAGE_PRESET_ID = "90x40"

BAND_PRESETS: List[Dict[str, Any]] = [
    {"id": "full_auto", "label": "Full (auto)", "low_hz": None, "high_hz": None, "kind": "auto"},
    {"id": "200-16000", "label": "200-16k Hz", "low_hz": 200.0, "high_hz": 16000.0, "kind": "fixed"},
    {"id": "200-500", "label": "200-500 Hz", "low_hz": 200.0, "high_hz": 500.0, "kind": "fixed"},
    {"id": "500-1000", "label": "500-1k Hz", "low_hz": 500.0, "high_hz": 1000.0, "kind": "fixed"},
    {"id": "1000-2000", "label": "1-2k Hz", "low_hz": 1000.0, "high_hz": 2000.0, "kind": "fixed"},
    {"id": "2000-4000", "label": "2-4k Hz", "low_hz": 2000.0, "high_hz": 4000.0, "kind": "fixed"},
    {"id": "4000-8000", "label": "4-8k Hz", "low_hz": 4000.0, "high_hz": 8000.0, "kind": "fixed"},
    {"id": "8000-16000", "label": "8-16k Hz", "low_hz": 8000.0, "high_hz": 16000.0, "kind": "fixed"},
    {"id": "custom", "label": "Custom...", "low_hz": None, "high_hz": None, "kind": "custom"},
]
DEFAULT_BAND_PRESET_ID = "200-16000"

STAGE_PRESETS: Dict[str, Dict[str, Any]] = {
    "concept": {
        "label": "Concept",
        "weights": {"b_pc_oct": 0.30, "e_bw": 0.30, "e_cov": 0.18, "r_spill": 0.14, "flags": 0.08},
        "visible_columns": ["score", "b_pc_oct", "e_bw", "e_cov", "r_spill", "flags_count"],
        "filters": {"exclude_flagged": False, "exclude_warnings": False, "min_score": 0.0},
    },
    "stabilization": {
        "label": "Stabilization",
        "weights": {"di_proxy": 0.34, "s_theta": 0.30, "e_sym_shape": 0.24, "flags": 0.12},
        "visible_columns": ["score", "di_proxy", "s_theta", "e_sym_shape", "flags_count"],
        "filters": {"exclude_flagged": True, "exclude_warnings": True, "min_score": 0.0},
    },
    "final": {
        "label": "Final",
        "weights": {"r_off": 0.38, "s_theta": 0.28, "e_sym_shape": 0.22, "flags": 0.12},
        "visible_columns": ["score", "r_off", "s_theta", "e_sym_shape", "flags_count"],
        "filters": {"exclude_flagged": True, "exclude_warnings": True, "min_score": 0.0},
    },
}
DEFAULT_STAGE_ID = "concept"
STAGE_ORDER: Tuple[str, ...] = ("concept", "stabilization", "final")
LEGACY_STAGE_ALIASES: Dict[str, str] = {"shaping": "concept"}


def normalize_stage_id(stage_id: Optional[str], fallback: str = DEFAULT_STAGE_ID) -> str:
    token = str(stage_id or "").strip().lower()
    if token in LEGACY_STAGE_ALIASES:
        token = str(LEGACY_STAGE_ALIASES[token]).strip().lower()
    if token in STAGE_PRESETS:
        return token
    fallback_token = str(fallback or DEFAULT_STAGE_ID).strip().lower() or DEFAULT_STAGE_ID
    if fallback_token in LEGACY_STAGE_ALIASES:
        fallback_token = str(LEGACY_STAGE_ALIASES[fallback_token]).strip().lower()
    return fallback_token if fallback_token in STAGE_PRESETS else DEFAULT_STAGE_ID


def coverage_preset_map() -> Dict[str, Dict[str, Any]]:
    return {str(item["id"]): dict(item) for item in COVERAGE_PRESETS}


def band_preset_map() -> Dict[str, Dict[str, Any]]:
    return {str(item["id"]): dict(item) for item in BAND_PRESETS}


def resolve_band_limits(
    *,
    preset_id: str,
    freq_min_hz: Optional[float],
    freq_max_hz: Optional[float],
    custom_low_hz: Optional[float] = None,
    custom_high_hz: Optional[float] = None,
) -> Tuple[float, float]:
    presets = band_preset_map()
    token = str(preset_id or DEFAULT_BAND_PRESET_ID).strip().lower()
    preset = presets.get(token) or presets.get(DEFAULT_BAND_PRESET_ID) or BAND_PRESETS[0]

    if str(preset.get("kind")) == "auto":
        low = float(freq_min_hz or 0.0)
        high = float(freq_max_hz or 0.0)
    elif str(preset.get("kind")) == "custom":
        low = float(custom_low_hz or 0.0)
        high = float(custom_high_hz or 0.0)
    else:
        low = float(preset.get("low_hz") or 0.0)
        high = float(preset.get("high_hz") or 0.0)

    if low <= 0.0 and freq_min_hz is not None:
        low = float(freq_min_hz)
    if high <= 0.0 and freq_max_hz is not None:
        high = float(freq_max_hz)
    if low <= 0.0:
        low = 200.0
    if high <= low:
        high = max(low + 1.0, float(freq_max_hz or (low + 1.0)))
    return (low, high)
