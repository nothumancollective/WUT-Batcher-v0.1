"""Stage-specific Analyzer plot curve computations (polar-only base)."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.analyzer.plot_service import compute_beamwidth_curve

_EPS = 1.0e-12


def _curve_row(freq_hz: float, value: float) -> Dict[str, float]:
    return {"freq_hz": float(freq_hz), "value": float(value)}


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return float(sum(float(item) for item in values) / float(len(values)))


def _rms(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return float(math.sqrt(sum(float(item) * float(item) for item in values) / float(len(values))))


def _stddev(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = _mean(values)
    if mean is None:
        return None
    return float(math.sqrt(sum((float(item) - float(mean)) ** 2 for item in values) / float(len(values))))


def _nearest_angle_index(angles_deg: Sequence[float], target_angle_deg: float) -> int:
    return min(range(len(angles_deg)), key=lambda idx: abs(float(angles_deg[idx]) - float(target_angle_deg)))


def _coverage_column_values(
    *,
    angles_deg: Sequence[float],
    column_db: Sequence[Optional[float]],
    half_window_deg: float,
) -> Tuple[List[float], List[float]]:
    inside: List[float] = []
    outside: List[float] = []
    for angle, value in zip(angles_deg, column_db):
        if value is None:
            continue
        if abs(float(angle)) <= float(half_window_deg):
            inside.append(float(value))
        else:
            outside.append(float(value))
    return inside, outside


def _column_by_freq(
    *,
    matrix_db: Sequence[Sequence[Optional[float]]],  # angle x freq
    freq_idx: int,
) -> List[Optional[float]]:
    return [row[freq_idx] if freq_idx < len(row) else None for row in matrix_db]


def _curve_to_map(curve: Sequence[Mapping[str, Any]]) -> Dict[float, float]:
    result: Dict[float, float] = {}
    for row in list(curve or []):
        try:
            freq_hz = float(row.get("freq_hz"))  # type: ignore[arg-type]
            value = float(row.get("value", row.get("beamwidth_deg")))  # type: ignore[arg-type]
        except Exception:
            continue
        result[freq_hz] = value
    return result


def compute_heatmap_overlays(
    *,
    beamwidth_curve: Sequence[Mapping[str, Any]],
    target_deg: float,
) -> Dict[str, Any]:
    contour: List[Dict[str, float]] = []
    for row in list(beamwidth_curve or []):
        try:
            freq_hz = float(row.get("freq_hz"))  # type: ignore[arg-type]
            beamwidth_deg = float(row.get("beamwidth_deg"))  # type: ignore[arg-type]
        except Exception:
            continue
        contour.append(
            {
                "freq_hz": freq_hz,
                "left_angle_deg": -0.5 * beamwidth_deg,
                "right_angle_deg": 0.5 * beamwidth_deg,
            }
        )
    return {
        "minus6_contour": contour,
        "target_half_window_deg": max(float(target_deg) * 0.5, 1.0),
    }


def compute_stage1_curves(
    *,
    freqs_hz: Sequence[float],
    angles_deg: Sequence[float],
    matrix_db: Sequence[Sequence[Optional[float]]],  # angle x freq
    target_deg: float,
    tol_deg: float,
) -> Dict[str, Any]:
    freqs = [float(item) for item in list(freqs_hz or [])]
    angles = [float(item) for item in list(angles_deg or [])]
    if not freqs or not angles or not matrix_db:
        return {
            "beamwidth_curve": [],
            "e_bw_curve": [],
            "e_cov_curve": [],
            "r_spill_curve": [],
            "summary": {},
        }

    beamwidth_curve = compute_beamwidth_curve(freqs_hz=freqs, angles_deg=angles, matrix_db=matrix_db)
    bw_map = {float(row["freq_hz"]): float(row["beamwidth_deg"]) for row in beamwidth_curve}
    half_window = max(float(target_deg) * 0.5, 1.0)

    e_bw_curve: List[Dict[str, float]] = []
    e_cov_curve: List[Dict[str, float]] = []
    r_spill_curve: List[Dict[str, float]] = []

    for freq_idx, freq_hz in enumerate(freqs):
        if freq_hz in bw_map:
            e_bw_curve.append(_curve_row(freq_hz, abs(float(bw_map[freq_hz]) - float(target_deg))))
        column = _column_by_freq(matrix_db=matrix_db, freq_idx=freq_idx)
        inside, outside = _coverage_column_values(
            angles_deg=angles,
            column_db=column,
            half_window_deg=half_window,
        )
        if len(inside) >= 2:
            inside_mean = _mean(inside)
            if inside_mean is not None:
                inside_dev = [float(value) - float(inside_mean) for value in inside]
                inside_rms = _rms(inside_dev)
                if inside_rms is not None:
                    e_cov_curve.append(_curve_row(freq_hz, inside_rms))
                if outside:
                    inside_power = sum(10.0 ** (float(value) / 10.0) for value in inside) / float(len(inside))
                    outside_power = sum(10.0 ** (float(value) / 10.0) for value in outside) / float(len(outside))
                    r_spill_curve.append(_curve_row(freq_hz, float(outside_power / max(inside_power, _EPS))))

    overlays = compute_heatmap_overlays(beamwidth_curve=beamwidth_curve, target_deg=float(target_deg))
    return {
        "beamwidth_curve": beamwidth_curve,
        "e_bw_curve": e_bw_curve,
        "e_cov_curve": e_cov_curve,
        "r_spill_curve": r_spill_curve,
        "heatmap_overlays": overlays,
        "summary": {
            "beamwidth_mean": _mean([float(item["beamwidth_deg"]) for item in beamwidth_curve]),
            "e_bw_mean": _mean([float(item["value"]) for item in e_bw_curve]),
            "e_cov_mean": _mean([float(item["value"]) for item in e_cov_curve]),
            "r_spill_mean": _mean([float(item["value"]) for item in r_spill_curve]),
            "tol_deg": float(tol_deg),
        },
    }


def compute_di_proxy_curve(
    *,
    freqs_hz: Sequence[float],
    angles_deg: Sequence[float],
    matrix_db: Sequence[Sequence[Optional[float]]],  # angle x freq
    target_deg: float,
    norm_angle_deg: Optional[float] = None,
) -> List[Dict[str, float]]:
    freqs = [float(item) for item in list(freqs_hz or [])]
    angles = [float(item) for item in list(angles_deg or [])]
    if not freqs or not angles or not matrix_db:
        return []
    reference_window = 10.0
    if norm_angle_deg is not None and abs(float(norm_angle_deg)) > 0.0:
        reference_window = min(reference_window, abs(float(norm_angle_deg)))
    reference_window = max(reference_window, min(2.0, 0.5 * float(target_deg)))

    curve: List[Dict[str, float]] = []
    for freq_idx, freq_hz in enumerate(freqs):
        column = _column_by_freq(matrix_db=matrix_db, freq_idx=freq_idx)
        all_values = [float(item) for item in column if item is not None]
        if len(all_values) < 3:
            continue
        local_values = [
            float(value)
            for angle, value in zip(angles, column)
            if value is not None and abs(float(angle)) <= float(reference_window)
        ]
        if not local_values:
            continue
        lw = _mean(local_values)
        sp = _mean(all_values)
        if lw is None or sp is None:
            continue
        curve.append(_curve_row(freq_hz, float(lw - sp)))
    return curve


def compute_s_theta_curve(
    *,
    freqs_hz: Sequence[float],
    angles_deg: Sequence[float],
    matrix_db: Sequence[Sequence[Optional[float]]],  # angle x freq
    target_deg: float,
    use_full_angles: bool,
) -> List[Dict[str, float]]:
    freqs = [float(item) for item in list(freqs_hz or [])]
    angles = [float(item) for item in list(angles_deg or [])]
    if not freqs or not angles or not matrix_db:
        return []
    half_window = max(float(target_deg) * 0.5, 1.0)
    curve: List[Dict[str, float]] = []
    for freq_idx, freq_hz in enumerate(freqs):
        samples: List[Tuple[float, float]] = []
        for angle, value in zip(angles, _column_by_freq(matrix_db=matrix_db, freq_idx=freq_idx)):
            if value is None:
                continue
            if not use_full_angles and abs(float(angle)) > half_window:
                continue
            samples.append((float(angle), float(value)))
        if len(samples) < 3:
            continue
        gradients: List[float] = []
        for idx in range(len(samples) - 1):
            angle_a, value_a = samples[idx]
            angle_b, value_b = samples[idx + 1]
            delta = float(angle_b - angle_a)
            if abs(delta) <= _EPS:
                continue
            gradients.append((float(value_b) - float(value_a)) / delta)
        rms_grad = _rms(gradients)
        if rms_grad is not None:
            curve.append(_curve_row(freq_hz, rms_grad))
    return curve


def compute_plane_consistency_curve(
    *,
    bw_by_plane: Mapping[str, Sequence[Mapping[str, Any]]],
    di_by_plane: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
) -> List[Dict[str, float]]:
    per_plane_bw = {
        plane: _curve_to_map(curve)
        for plane, curve in dict(bw_by_plane or {}).items()
        if str(plane).upper() in {"H", "V", "D"}
    }
    curve: List[Dict[str, float]] = []
    freq_keys = sorted({freq for values in per_plane_bw.values() for freq in values.keys()})
    for freq_hz in freq_keys:
        values = [float(values[freq_hz]) for values in per_plane_bw.values() if freq_hz in values]
        if len(values) >= 2:
            sigma = _stddev(values)
            if sigma is not None:
                curve.append(_curve_row(freq_hz, sigma))
    if curve:
        return curve
    per_plane_di = {
        plane: _curve_to_map(curve)
        for plane, curve in dict(di_by_plane or {}).items()
        if str(plane).upper() in {"H", "V", "D"}
    }
    freq_keys = sorted({freq for values in per_plane_di.values() for freq in values.keys()})
    for freq_hz in freq_keys:
        values = [float(values[freq_hz]) for values in per_plane_di.values() if freq_hz in values]
        if len(values) < 2:
            continue
        sigma = _stddev(values)
        if sigma is not None:
            curve.append(_curve_row(freq_hz, sigma))
    return curve


def compute_r_off_curve(
    *,
    freqs_hz: Sequence[float],
    angles_deg: Sequence[float],
    matrix_db: Sequence[Sequence[Optional[float]]],  # angle x freq
) -> List[Dict[str, float]]:
    freqs = [float(item) for item in list(freqs_hz or [])]
    angles = [float(item) for item in list(angles_deg or [])]
    if not freqs or not angles or not matrix_db:
        return []
    target_angles = [-60.0, -45.0, -30.0, 30.0, 45.0, 60.0]
    available_indices = sorted(
        {_nearest_angle_index(angles, angle_target) for angle_target in target_angles}
    )
    if len(available_indices) < 2:
        return []
    curve: List[Dict[str, float]] = []
    for freq_idx, freq_hz in enumerate(freqs):
        values = []
        for row_idx in available_indices:
            row = matrix_db[row_idx] if row_idx < len(matrix_db) else []
            value = row[freq_idx] if freq_idx < len(row) else None
            if value is None:
                continue
            values.append(float(value))
        if len(values) < 2:
            continue
        ripple = max(values) - min(values)
        curve.append(_curve_row(freq_hz, ripple))
    return curve


def summarize_curve(curve: Sequence[Mapping[str, Any]]) -> Optional[float]:
    values: List[float] = []
    for row in list(curve or []):
        try:
            values.append(float(row.get("value")))  # type: ignore[arg-type]
        except Exception:
            continue
    return _mean(values)


def compute_stage_plot_payload(
    *,
    stage_mode: str,
    target_deg: float,
    tol_deg: float,
    freqs_hz: Sequence[float],
    angles_deg: Sequence[float],
    matrix_db: Sequence[Sequence[Optional[float]]],  # angle x freq
    beamwidth_curve: Sequence[Mapping[str, Any]],
    norm_angle_deg: Optional[float],
    use_full_angles_for_smoothness: bool,
    bw_curves_by_plane: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    di_curves_by_plane: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    artifact_status: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    stage_token = str(stage_mode or "").strip().lower()
    stage1 = compute_stage1_curves(
        freqs_hz=freqs_hz,
        angles_deg=angles_deg,
        matrix_db=matrix_db,
        target_deg=float(target_deg),
        tol_deg=float(tol_deg),
    )
    stage_curves: Dict[str, List[Dict[str, float]]] = {
        "beamwidth": [dict(item) for item in list(stage1.get("beamwidth_curve", []) or [])],
        "e_bw": [dict(item) for item in list(stage1.get("e_bw_curve", []) or [])],
        "e_cov": [dict(item) for item in list(stage1.get("e_cov_curve", []) or [])],
        "r_spill": [dict(item) for item in list(stage1.get("r_spill_curve", []) or [])],
    }
    # Keep incoming beamwidth curve as source of truth if provided by plot service.
    if beamwidth_curve:
        stage_curves["beamwidth"] = [dict(item) for item in list(beamwidth_curve or []) if isinstance(item, Mapping)]

    if stage_token in {"stabilization", "final"}:
        di_proxy_curve = compute_di_proxy_curve(
            freqs_hz=freqs_hz,
            angles_deg=angles_deg,
            matrix_db=matrix_db,
            target_deg=float(target_deg),
            norm_angle_deg=norm_angle_deg,
        )
        s_theta_curve = compute_s_theta_curve(
            freqs_hz=freqs_hz,
            angles_deg=angles_deg,
            matrix_db=matrix_db,
            target_deg=float(target_deg),
            use_full_angles=bool(use_full_angles_for_smoothness),
        )
        e_sym_curve = compute_plane_consistency_curve(
            bw_by_plane=dict(bw_curves_by_plane or {}),
            di_by_plane=dict(di_curves_by_plane or {}),
        )
        stage_curves["di_proxy"] = di_proxy_curve
        stage_curves["s_theta"] = s_theta_curve
        stage_curves["e_sym_shape"] = e_sym_curve
    if stage_token == "final":
        r_off_curve = compute_r_off_curve(
            freqs_hz=freqs_hz,
            angles_deg=angles_deg,
            matrix_db=matrix_db,
        )
        stage_curves["r_off"] = r_off_curve

    summary = {
        "e_bw_mean": summarize_curve(stage_curves.get("e_bw", [])),
        "e_cov_mean": summarize_curve(stage_curves.get("e_cov", [])),
        "r_spill_mean": summarize_curve(stage_curves.get("r_spill", [])),
        "di_proxy_mean": summarize_curve(stage_curves.get("di_proxy", [])),
        "s_theta_mean": summarize_curve(stage_curves.get("s_theta", [])),
        "e_sym_shape_mean": summarize_curve(stage_curves.get("e_sym_shape", [])),
        "r_off_mean": summarize_curve(stage_curves.get("r_off", [])),
    }
    return {
        "stage_mode": stage_token,
        "heatmap_overlays": stage1.get("heatmap_overlays", {}),
        "curves": stage_curves,
        "summary": summary,
        "artifact_status": dict(artifact_status or {}),
    }
