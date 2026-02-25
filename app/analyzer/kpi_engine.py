"""MVP KPI engine for Analyzer Batch Review (polar magnitude only)."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from app.analyzer.presets import DEFAULT_STAGE_ID, STAGE_PRESETS, normalize_stage_id
from app.analyzer.reason_codes import reason_items_for_codes
from app.analyzer.stage_plot_engine import (
    compute_di_proxy_curve,
    compute_plane_consistency_curve,
    compute_r_off_curve,
    compute_s_theta_curve,
    summarize_curve,
)

_EPS = 1.0e-12


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _mag_db(re: float, im: float) -> float:
    magnitude = max(math.hypot(float(re), float(im)), _EPS)
    return 20.0 * math.log10(magnitude)


def _interp_crossing(x0: float, y0: float, x1: float, y1: float, threshold: float) -> float:
    if abs(y1 - y0) <= _EPS:
        return float(x0)
    t = (float(threshold) - float(y0)) / (float(y1) - float(y0))
    return float(x0 + ((x1 - x0) * t))


def _beamwidth_minus6db(angles: List[float], normalized_db: List[float]) -> Tuple[Optional[float], bool]:
    if len(angles) != len(normalized_db) or len(angles) < 3:
        return (None, True)
    pivot = min(range(len(angles)), key=lambda idx: abs(angles[idx]))
    if float(normalized_db[pivot]) < -6.0:
        return (None, True)

    left = float(angles[0])
    right = float(angles[-1])
    threshold = -6.0
    pivot_angle = float(angles[pivot])
    has_left_side = any(float(angle) < pivot_angle for angle in angles)
    has_right_side = any(float(angle) > pivot_angle for angle in angles)
    left_crossed = False
    right_crossed = False

    for idx in range(pivot, len(angles) - 1):
        y_a = float(normalized_db[idx])
        y_b = float(normalized_db[idx + 1])
        if y_a >= threshold and y_b >= threshold:
            continue
        if y_a >= threshold and y_b < threshold:
            right = _interp_crossing(float(angles[idx]), y_a, float(angles[idx + 1]), y_b, threshold)
            right_crossed = True
            break
        right = float(angles[idx])
        break

    for idx in range(pivot, 0, -1):
        y_a = float(normalized_db[idx])
        y_b = float(normalized_db[idx - 1])
        if y_a >= threshold and y_b >= threshold:
            continue
        if y_a >= threshold and y_b < threshold:
            left = _interp_crossing(float(angles[idx]), y_a, float(angles[idx - 1]), y_b, threshold)
            left_crossed = True
            break
        left = float(angles[idx])
        break

    if right_crossed and left_crossed:
        width = float(right - left)
        if width <= 0.0:
            return (None, True)
        return (width, False)

    # Saturation support: one or both -6 dB crossings are outside available angle range.
    if has_left_side and has_right_side:
        span = float(right - left)
        if span > 0.0:
            return (span, True)

    # One-sided support: mirror the available half-angle when only one side exists.
    if (not has_left_side) and right_crossed:
        half = float(right - pivot_angle)
        if half > 0.0:
            return (2.0 * half, True)
    if (not has_right_side) and left_crossed:
        half = float(pivot_angle - left)
        if half > 0.0:
            return (2.0 * half, True)
    return (None, True)


def _longest_pass_band_octaves(
    freqs: List[float],
    beamwidths: List[Optional[float]],
    *,
    target_deg: float,
    tol_deg: float,
) -> Dict[str, Optional[float]]:
    best_start: Optional[float] = None
    best_end: Optional[float] = None
    cur_start: Optional[float] = None
    cur_end: Optional[float] = None

    for freq, width in zip(freqs, beamwidths):
        is_ok = width is not None and abs(float(width) - float(target_deg)) <= float(tol_deg)
        if is_ok:
            if cur_start is None:
                cur_start = float(freq)
            cur_end = float(freq)
        else:
            if cur_start is not None and cur_end is not None:
                best_start, best_end = _pick_wider_band(best_start, best_end, cur_start, cur_end)
            cur_start = None
            cur_end = None
    if cur_start is not None and cur_end is not None:
        best_start, best_end = _pick_wider_band(best_start, best_end, cur_start, cur_end)

    if best_start is None or best_end is None or best_end <= best_start:
        return {"f_low_hz": None, "f_high_hz": None, "octaves": 0.0}
    return {
        "f_low_hz": float(best_start),
        "f_high_hz": float(best_end),
        "octaves": float(math.log2(best_end / best_start)) if best_start > 0.0 else 0.0,
    }


def _pick_wider_band(
    best_start: Optional[float],
    best_end: Optional[float],
    cand_start: float,
    cand_end: float,
) -> Tuple[Optional[float], Optional[float]]:
    if best_start is None or best_end is None:
        return (cand_start, cand_end)
    best_oct = math.log2(best_end / best_start) if best_start > 0.0 and best_end > best_start else 0.0
    cand_oct = math.log2(cand_end / cand_start) if cand_start > 0.0 and cand_end > cand_start else 0.0
    if cand_oct > best_oct:
        return (cand_start, cand_end)
    return (best_start, best_end)


def _orientation_target_deg(orientation: str, target_h_deg: float, target_v_deg: float) -> float:
    token = str(orientation or "").strip().upper()
    if token == "H":
        return float(target_h_deg)
    if token == "V":
        return float(target_v_deg)
    return float((float(target_h_deg) + float(target_v_deg)) * 0.5)


def _plane_weights(planes: Iterable[str]) -> Dict[str, float]:
    default = {"H": 0.45, "V": 0.45, "D": 0.10}
    present = [str(item).strip().upper() for item in planes if str(item).strip()]
    present = [item for item in present if item in {"H", "V", "D"}]
    if not present:
        return {}
    total = sum(default.get(item, 0.0) for item in present)
    if total <= 0.0:
        equal = 1.0 / float(len(present))
        return {item: equal for item in present}
    return {item: default.get(item, 0.0) / total for item in present}


def _weighted_mean(values: Mapping[str, Optional[float]], weights: Mapping[str, float]) -> Optional[float]:
    numerator = 0.0
    denominator = 0.0
    for plane, weight in weights.items():
        value = values.get(plane)
        if value is None:
            continue
        numerator += float(value) * float(weight)
        denominator += float(weight)
    if denominator <= 0.0:
        return None
    return numerator / denominator


def _build_plane_matrix(
    rows: Sequence[Mapping[str, Any]],
) -> Tuple[List[float], List[float], List[List[Optional[float]]]]:
    freqs = sorted({float(item["freq_hz"]) for item in rows if item.get("freq_hz") is not None})
    angles = sorted({float(item["angle_deg"]) for item in rows if item.get("angle_deg") is not None})
    if not freqs or not angles:
        return ([], [], [])

    freq_idx = {freq: idx for idx, freq in enumerate(freqs)}
    angle_idx = {angle: idx for idx, angle in enumerate(angles)}
    matrix: List[List[Optional[float]]] = [[None for _ in freqs] for _ in angles]
    for item in rows:
        try:
            freq_hz = float(item.get("freq_hz"))
            angle_deg = float(item.get("angle_deg"))
            re = float(item.get("re"))
            im = float(item.get("im"))
        except Exception:
            continue
        if freq_hz not in freq_idx or angle_deg not in angle_idx:
            continue
        matrix[angle_idx[angle_deg]][freq_idx[freq_hz]] = _mag_db(re, im)
    return (freqs, angles, matrix)


def _compute_advanced_stage_metrics(
    *,
    planes_points: Mapping[str, Sequence[Mapping[str, Any]]],
    target_h_deg: float,
    target_v_deg: float,
) -> Dict[str, Optional[float]]:
    plane_weights = _plane_weights(planes_points.keys())
    di_means: Dict[str, Optional[float]] = {}
    smooth_means: Dict[str, Optional[float]] = {}
    ripple_means: Dict[str, Optional[float]] = {}
    di_curves_by_plane: Dict[str, List[Dict[str, float]]] = {}

    for plane, rows in planes_points.items():
        token = str(plane or "").strip().upper()
        if token not in {"H", "V", "D"}:
            continue
        freqs_hz, angles_deg, matrix_db = _build_plane_matrix(list(rows or []))
        if not freqs_hz or not angles_deg or not matrix_db:
            continue
        target_deg = _orientation_target_deg(token, float(target_h_deg), float(target_v_deg))
        di_curve = compute_di_proxy_curve(
            freqs_hz=freqs_hz,
            angles_deg=angles_deg,
            matrix_db=matrix_db,
            target_deg=float(target_deg),
            norm_angle_deg=0.0,
        )
        smooth_curve = compute_s_theta_curve(
            freqs_hz=freqs_hz,
            angles_deg=angles_deg,
            matrix_db=matrix_db,
            target_deg=float(target_deg),
            use_full_angles=False,
        )
        ripple_curve = compute_r_off_curve(
            freqs_hz=freqs_hz,
            angles_deg=angles_deg,
            matrix_db=matrix_db,
        )
        di_curves_by_plane[token] = [dict(item) for item in list(di_curve or []) if isinstance(item, Mapping)]
        di_means[token] = summarize_curve(di_curve)
        smooth_means[token] = summarize_curve(smooth_curve)
        ripple_means[token] = summarize_curve(ripple_curve)

    e_sym_curve = compute_plane_consistency_curve(bw_by_plane={}, di_by_plane=di_curves_by_plane)
    return {
        "di_proxy": _weighted_mean(di_means, plane_weights),
        "s_theta": _weighted_mean(smooth_means, plane_weights),
        "r_off": _weighted_mean(ripple_means, plane_weights),
        "e_sym_shape": summarize_curve(e_sym_curve),
    }


def _normalize_rows(points: Sequence[Mapping[str, Any]]) -> Dict[float, Dict[float, float]]:
    """Return {freq_hz: {angle_deg: magnitude_db}} with duplicates averaged."""
    buckets: Dict[float, Dict[float, List[float]]] = {}
    for row in points:
        freq = _safe_float(row.get("freq_hz"), 0.0)
        angle = _safe_float(row.get("angle_deg"), 0.0)
        re = _safe_float(row.get("re"), 0.0)
        im = _safe_float(row.get("im"), 0.0)
        if freq <= 0.0:
            continue
        by_angle = buckets.setdefault(freq, {})
        by_angle.setdefault(angle, []).append(_mag_db(re, im))
    normalized: Dict[float, Dict[float, float]] = {}
    for freq, by_angle in buckets.items():
        normalized[freq] = {
            angle: (sum(values) / float(len(values))) for angle, values in by_angle.items() if values
        }
    return normalized


def compute_plane_kpis(
    *,
    orientation: str,
    points: Sequence[Mapping[str, Any]],
    target_h_deg: float,
    target_v_deg: float,
    tol_deg: float,
    band_low_hz: float,
    band_high_hz: float,
) -> Dict[str, Any]:
    target_deg = _orientation_target_deg(orientation, target_h_deg, target_v_deg)
    grouped = _normalize_rows(points)
    reason_codes: Set[str] = set()
    if not grouped:
        reason_codes.add("NO_POINTS")
        return {
            "orientation": str(orientation).upper(),
            "target_deg": target_deg,
            "insufficient_coverage": True,
            "unscorable": True,
            "reason_codes": sorted(reason_codes),
            "reason": "no_points",
        }

    selected_freqs = sorted(freq for freq in grouped.keys() if float(band_low_hz) <= freq <= float(band_high_hz))
    if not selected_freqs:
        reason_codes.add("EMPTY_BAND_INTERSECTION")
        return {
            "orientation": str(orientation).upper(),
            "target_deg": target_deg,
            "insufficient_coverage": True,
            "unscorable": True,
            "reason_codes": sorted(reason_codes),
            "reason": "empty_band_intersection",
        }

    beamwidth_rows: List[Dict[str, Any]] = []
    rms_inside_values: List[float] = []
    spill_values: List[float] = []
    insufficient_coverage = False
    limited_angle_coverage = False

    coverage_half = max(float(target_deg) * 0.5, 1.0)
    for freq in selected_freqs:
        by_angle = grouped.get(freq, {})
        if len(by_angle) < 3:
            insufficient_coverage = True
            reason_codes.add("INSUFFICIENT_ANGLE_COVERAGE")
            continue
        angles = sorted(by_angle.keys())
        values = [float(by_angle[angle]) for angle in angles]
        pivot_idx = min(range(len(angles)), key=lambda idx: abs(float(angles[idx])))
        ref_db = float(values[pivot_idx])
        normalized_db = [float(value - ref_db) for value in values]

        bw, bw_limited = _beamwidth_minus6db([float(a) for a in angles], normalized_db)
        span_available = float(max(angles) - min(angles)) if angles else 0.0
        saturated_full_span = bool(
            bw is not None
            and bw_limited
            and span_available > 0.0
            and abs(float(bw) - span_available) <= 1.0e-6
        )
        if bw is not None:
            beamwidth_rows.append(
                {
                    "freq_hz": float(freq),
                    "beamwidth_deg": float(bw),
                    "limited": bool(bw_limited),
                }
            )
        if saturated_full_span:
            reason_codes.add("BEAMWIDTH_SATURATED")
        elif bw_limited:
            limited_angle_coverage = True

        inside_values = [normalized_db[idx] for idx, angle in enumerate(angles) if abs(float(angle)) <= coverage_half]
        outside_values = [normalized_db[idx] for idx, angle in enumerate(angles) if abs(float(angle)) > coverage_half]
        if len(inside_values) < 2:
            insufficient_coverage = True
            reason_codes.add("INSUFFICIENT_ANGLE_COVERAGE")
            continue
        inside_mean = sum(inside_values) / float(len(inside_values))
        inside_rms = math.sqrt(sum((value - inside_mean) ** 2 for value in inside_values) / float(len(inside_values)))
        rms_inside_values.append(float(inside_rms))

        if outside_values:
            inside_power = sum(10.0 ** (value / 10.0) for value in inside_values) / float(len(inside_values))
            outside_power = sum(10.0 ** (value / 10.0) for value in outside_values) / float(len(outside_values))
            spill_values.append(float(outside_power / max(inside_power, _EPS)))
        else:
            spill_values.append(0.0)

        min_angle = float(min(angles))
        max_angle = float(max(angles))
        if min_angle > -coverage_half or max_angle < coverage_half:
            limited_angle_coverage = True
            reason_codes.add("INSUFFICIENT_ANGLE_COVERAGE")

    if limited_angle_coverage:
        reason_codes.add("INSUFFICIENT_ANGLE_COVERAGE")

    beamwidths = [float(item["beamwidth_deg"]) for item in beamwidth_rows]
    beamwidth_freqs = [float(item["freq_hz"]) for item in beamwidth_rows]
    e_bw = None
    if beamwidths:
        e_bw = sum(abs(float(value) - float(target_deg)) for value in beamwidths) / float(len(beamwidths))

    pass_band = _longest_pass_band_octaves(
        beamwidth_freqs,
        [item["beamwidth_deg"] for item in beamwidth_rows],
        target_deg=target_deg,
        tol_deg=float(tol_deg),
    )

    jumps: List[float] = []
    collapse: List[float] = []
    wide: List[float] = []
    flag_rows = [row for row in beamwidth_rows if not bool(row.get("limited"))]
    if flag_rows:
        jump_threshold = max(12.0, float(target_deg) * 0.25)
        prev_width: Optional[float] = None
        for row in flag_rows:
            freq = float(row["freq_hz"])
            width = float(row["beamwidth_deg"])
            if prev_width is not None and abs(width - prev_width) >= jump_threshold:
                jumps.append(freq)
            if width <= max(5.0, float(target_deg) * 0.45):
                collapse.append(freq)
            if width >= float(target_deg) * 1.9:
                wide.append(freq)
            prev_width = width

    # Morphology flags are not reliable under limited/insufficient angle coverage.
    if bool(insufficient_coverage or limited_angle_coverage):
        jumps = []
        collapse = []
        wide = []

    unscorable = not beamwidth_rows

    return {
        "orientation": str(orientation).upper(),
        "target_deg": float(target_deg),
        "band_low_hz": float(min(selected_freqs)),
        "band_high_hz": float(max(selected_freqs)),
        "beamwidth_curve": beamwidth_rows[:: max(1, int(len(beamwidth_rows) / 80) or 1)],
        "e_bw": float(e_bw) if e_bw is not None else None,
        "b_pc_oct": float(pass_band.get("octaves") or 0.0),
        "b_pc_f_low_hz": pass_band.get("f_low_hz"),
        "b_pc_f_high_hz": pass_band.get("f_high_hz"),
        "e_cov": (sum(rms_inside_values) / float(len(rms_inside_values))) if rms_inside_values else None,
        "r_spill": (sum(spill_values) / float(len(spill_values))) if spill_values else None,
        "flags": {
            "jump_hz": jumps,
            "collapse_hz": collapse,
            "wide_hz": wide,
        },
        "flag_count": int(len(jumps) + len(collapse) + len(wide)),
        "insufficient_coverage": bool(insufficient_coverage or limited_angle_coverage),
        "limited_angle_coverage": bool(limited_angle_coverage),
        "unscorable": bool(unscorable),
        "reason_codes": sorted(reason_codes),
        "reason_items": reason_items_for_codes(sorted(reason_codes)),
    }


def compute_run_kpis(
    *,
    planes_points: Mapping[str, Sequence[Mapping[str, Any]]],
    target_h_deg: float,
    target_v_deg: float,
    tol_deg: float,
    band_low_hz: float,
    band_high_hz: float,
) -> Dict[str, Any]:
    per_plane: Dict[str, Dict[str, Any]] = {}
    per_plane_points: Dict[str, List[Mapping[str, Any]]] = {}
    reason_codes: Set[str] = set()
    for orientation, rows in planes_points.items():
        token = str(orientation or "").strip().upper()
        if token not in {"H", "V", "D"}:
            continue
        if not rows:
            continue
        per_plane_points[token] = [dict(item) for item in list(rows or []) if isinstance(item, Mapping)]
        plane_payload = compute_plane_kpis(
            orientation=token,
            points=rows,
            target_h_deg=float(target_h_deg),
            target_v_deg=float(target_v_deg),
            tol_deg=float(tol_deg),
            band_low_hz=float(band_low_hz),
            band_high_hz=float(band_high_hz),
        )
        per_plane[token] = plane_payload
        reason_codes.update(str(code) for code in list(plane_payload.get("reason_codes", []) or []) if str(code).strip())

    missing_planes = [plane for plane in ("H", "V", "D") if plane not in per_plane]
    if missing_planes:
        reason_codes.add("MISSING_PLANE")

    weights = _plane_weights(per_plane.keys())
    e_bw_values = {plane: row.get("e_bw") for plane, row in per_plane.items()}
    b_pc_values = {plane: row.get("b_pc_oct") for plane, row in per_plane.items()}
    e_cov_values = {plane: row.get("e_cov") for plane, row in per_plane.items()}
    spill_values = {plane: row.get("r_spill") for plane, row in per_plane.items()}

    flag_count = sum(int(row.get("flag_count") or 0) for row in per_plane.values())
    insufficient_coverage = any(bool(row.get("insufficient_coverage")) for row in per_plane.values()) or not per_plane
    unscorable = any(bool(row.get("unscorable")) for row in per_plane.values()) or not per_plane
    aggregate = {
        "e_bw": _weighted_mean(e_bw_values, weights),
        "b_pc_oct": _weighted_mean(b_pc_values, weights),
        "e_cov": _weighted_mean(e_cov_values, weights),
        "r_spill": _weighted_mean(spill_values, weights),
        "flags_count": int(flag_count),
        "flagged": bool(flag_count > 0),
        "insufficient_coverage": bool(insufficient_coverage),
        "unscorable": bool(unscorable),
        "reason_codes": sorted(reason_codes),
        "reason_items": reason_items_for_codes(sorted(reason_codes)),
    }
    aggregate.update(
        _compute_advanced_stage_metrics(
            planes_points=per_plane_points,
            target_h_deg=float(target_h_deg),
            target_v_deg=float(target_v_deg),
        )
    )

    flags = {
        "jump_hz": {
            plane: list(row.get("flags", {}).get("jump_hz", []))
            for plane, row in per_plane.items()
            if list(row.get("flags", {}).get("jump_hz", []))
        },
        "collapse_hz": {
            plane: list(row.get("flags", {}).get("collapse_hz", []))
            for plane, row in per_plane.items()
            if list(row.get("flags", {}).get("collapse_hz", []))
        },
        "wide_hz": {
            plane: list(row.get("flags", {}).get("wide_hz", []))
            for plane, row in per_plane.items()
            if list(row.get("flags", {}).get("wide_hz", []))
        },
        "insufficient_coverage": bool(insufficient_coverage),
        "reason_codes": sorted(reason_codes),
        "reason_items": reason_items_for_codes(sorted(reason_codes)),
        "missing_planes": missing_planes,
    }

    return {
        "band_low_hz": float(band_low_hz),
        "band_high_hz": float(band_high_hz),
        "planes": per_plane,
        "aggregate": aggregate,
        "flags": flags,
    }


def compute_stage_score(kpi_payload: Mapping[str, Any], stage_id: str = DEFAULT_STAGE_ID) -> Optional[float]:
    aggregate = dict(kpi_payload.get("aggregate", {}) or {})
    if bool(aggregate.get("unscorable")):
        return None
    stage_key = normalize_stage_id(stage_id, fallback=DEFAULT_STAGE_ID)
    stage = dict(STAGE_PRESETS.get(stage_key) or STAGE_PRESETS[DEFAULT_STAGE_ID])
    weights = dict(stage.get("weights", {}) or {})

    b_pc = aggregate.get("b_pc_oct")
    e_bw = aggregate.get("e_bw")
    e_cov = aggregate.get("e_cov")
    r_spill = aggregate.get("r_spill")
    di_proxy = aggregate.get("di_proxy")
    s_theta = aggregate.get("s_theta")
    e_sym_shape = aggregate.get("e_sym_shape")
    r_off = aggregate.get("r_off")
    flags_count = int(aggregate.get("flags_count") or 0)
    flagged = bool(aggregate.get("flagged"))

    b_pc_norm = _clamp(_safe_float(b_pc, 0.0) / 3.0, 0.0, 1.0)
    e_bw_norm = _clamp(1.0 - (_safe_float(e_bw, 100.0) / 20.0), 0.0, 1.0)
    e_cov_norm = _clamp(1.0 - (_safe_float(e_cov, 100.0) / 6.0), 0.0, 1.0)
    spill_db = 10.0 * math.log10(max(_safe_float(r_spill, 10.0), _EPS))
    spill_norm = _clamp((5.0 - spill_db) / 20.0, 0.0, 1.0)
    di_proxy_norm = _clamp(_safe_float(di_proxy, 0.0) / 6.0, 0.0, 1.0)
    s_theta_norm = _clamp(1.0 - (_safe_float(s_theta, 10.0) / 0.35), 0.0, 1.0)
    e_sym_norm = _clamp(1.0 - (_safe_float(e_sym_shape, 100.0) / 12.0), 0.0, 1.0)
    r_off_norm = _clamp(1.0 - (_safe_float(r_off, 100.0) / 8.0), 0.0, 1.0)
    if not flagged:
        flags_norm = 1.0
    else:
        flags_norm = _clamp(1.0 - (min(flags_count, 3) / 3.0), 0.0, 1.0)

    normalized_metrics = {
        "b_pc_oct": b_pc_norm,
        "e_bw": e_bw_norm,
        "e_cov": e_cov_norm,
        "r_spill": spill_norm,
        "di_proxy": di_proxy_norm,
        "s_theta": s_theta_norm,
        "e_sym_shape": e_sym_norm,
        "r_off": r_off_norm,
        "flags": flags_norm,
    }
    weighted = sum(
        _safe_float(weights.get(metric_key), 0.0) * float(metric_value)
        for metric_key, metric_value in normalized_metrics.items()
    )
    if bool(aggregate.get("insufficient_coverage")):
        weighted *= 0.75
    return round(_clamp(weighted, 0.0, 1.0) * 100.0, 2)
