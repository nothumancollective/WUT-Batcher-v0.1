"""Polar plot data loading and derivation for Analyzer Explorer."""

from __future__ import annotations

import math
from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.analyzer.cache import AnalyzerPlotCache
from app.analyzer.orientation import orientation_query_aliases

_EPS = 1.0e-12


def cache_key_for_request(
    *,
    project_id: str,
    batch_id: str,
    run_id: Optional[str],
    version_id: str,
    plane: str,
    norm_policy: str,
    band_low_hz: float,
    band_high_hz: float,
) -> str:
    return "|".join(
        [
            str(project_id),
            str(batch_id),
            str(run_id or ""),
            str(version_id),
            str(plane).upper(),
            str(norm_policy),
            f"{float(band_low_hz):.3f}",
            f"{float(band_high_hz):.3f}",
        ]
    )


def _mag_db(re: float, im: float) -> float:
    return 20.0 * math.log10(max(math.hypot(float(re), float(im)), _EPS))


def normalize_relative_to_reference(
    *,
    freqs_hz: Sequence[float],
    angles_deg: Sequence[float],
    matrix_db: Sequence[Sequence[Optional[float]]],  # angle x freq
    preferred_ref_angle_deg: Optional[float] = None,
) -> Tuple[List[List[Optional[float]]], float]:
    if not freqs_hz or not angles_deg:
        return ([], 0.0)
    angles = [float(value) for value in angles_deg]
    if preferred_ref_angle_deg is None:
        ref_idx = min(range(len(angles)), key=lambda idx: abs(angles[idx]))
    else:
        ref_idx = min(range(len(angles)), key=lambda idx: abs(angles[idx] - float(preferred_ref_angle_deg)))
    ref_angle = float(angles[ref_idx])
    rows = len(angles)
    cols = len(freqs_hz)
    normalized: List[List[Optional[float]]] = [[None] * cols for _ in range(rows)]
    for col_idx in range(cols):
        ref_value = None
        if ref_idx < len(matrix_db):
            ref_value = matrix_db[ref_idx][col_idx]
        if ref_value is None:
            # fallback to nearest available angle for this frequency column
            candidate = None
            candidate_dist = None
            for row_idx in range(rows):
                value = matrix_db[row_idx][col_idx]
                if value is None:
                    continue
                dist = abs(angles[row_idx])
                if candidate is None or dist < float(candidate_dist):
                    candidate = float(value)
                    candidate_dist = float(dist)
            ref_value = candidate
        if ref_value is None:
            continue
        ref = float(ref_value)
        for row_idx in range(rows):
            value = matrix_db[row_idx][col_idx]
            if value is None:
                normalized[row_idx][col_idx] = None
            else:
                normalized[row_idx][col_idx] = float(value) - ref
    return (normalized, ref_angle)


def normalize_relative_to_nearest_zero(
    *,
    freqs_hz: Sequence[float],
    angles_deg: Sequence[float],
    matrix_db: Sequence[Sequence[Optional[float]]],  # angle x freq
) -> Tuple[List[List[Optional[float]]], float]:
    return normalize_relative_to_reference(
        freqs_hz=freqs_hz,
        angles_deg=angles_deg,
        matrix_db=matrix_db,
        preferred_ref_angle_deg=None,
    )


def _interp_cross(x0: float, y0: float, x1: float, y1: float, threshold: float) -> float:
    if abs(y1 - y0) <= _EPS:
        return float(x0)
    t = (float(threshold) - float(y0)) / (float(y1) - float(y0))
    return float(x0 + ((x1 - x0) * t))


def _beamwidth_minus6db(angles: Sequence[float], column_db: Sequence[Optional[float]]) -> Tuple[Optional[float], bool]:
    samples = [(float(a), float(v)) for a, v in zip(angles, column_db) if v is not None]
    if len(samples) < 3:
        return (None, False)
    angles_clean = [item[0] for item in samples]
    values_clean = [item[1] for item in samples]
    pivot = min(range(len(angles_clean)), key=lambda idx: abs(angles_clean[idx]))
    if values_clean[pivot] < -6.0:
        return (None, False)
    threshold = -6.0
    pivot_angle = float(angles_clean[pivot])
    has_left_side = any(float(angle) < pivot_angle for angle in angles_clean)
    has_right_side = any(float(angle) > pivot_angle for angle in angles_clean)
    left = angles_clean[0]
    right = angles_clean[-1]
    left_crossed = False
    right_crossed = False

    for idx in range(pivot, len(angles_clean) - 1):
        y_a = values_clean[idx]
        y_b = values_clean[idx + 1]
        if y_a >= threshold and y_b >= threshold:
            continue
        if y_a >= threshold and y_b < threshold:
            right = _interp_cross(angles_clean[idx], y_a, angles_clean[idx + 1], y_b, threshold)
            right_crossed = True
            break
        right = angles_clean[idx]
        break

    for idx in range(pivot, 0, -1):
        y_a = values_clean[idx]
        y_b = values_clean[idx - 1]
        if y_a >= threshold and y_b >= threshold:
            continue
        if y_a >= threshold and y_b < threshold:
            left = _interp_cross(angles_clean[idx], y_a, angles_clean[idx - 1], y_b, threshold)
            left_crossed = True
            break
        left = angles_clean[idx]
        break
    if left_crossed and right_crossed:
        width = float(right - left)
        if width <= 0.0:
            return (None, False)
        return (width, False)

    if has_left_side and has_right_side:
        width = float(right - left)
        if width > 0.0:
            return (width, True)

    # AKABAK commonly exports a symmetry-reduced 0..90 degree polar. Mirror the
    # measured half-angle so plot payloads use the same full-width convention as
    # the KPI engine; keep the result flagged because one side was inferred.
    if (not has_left_side) and right_crossed:
        half_width = float(right - pivot_angle)
        if half_width > 0.0:
            return (2.0 * half_width, True)
    if (not has_right_side) and left_crossed:
        half_width = float(pivot_angle - left)
        if half_width > 0.0:
            return (2.0 * half_width, True)
    return (None, False)


def compute_beamwidth_curve(
    *,
    freqs_hz: Sequence[float],
    angles_deg: Sequence[float],
    matrix_db: Sequence[Sequence[Optional[float]]],  # angle x freq
) -> List[Dict[str, float]]:
    if not freqs_hz or not angles_deg or not matrix_db:
        return []
    curve: List[Dict[str, float]] = []
    cols = len(freqs_hz)
    rows = len(angles_deg)
    for col_idx in range(cols):
        column = [matrix_db[row_idx][col_idx] if row_idx < len(matrix_db) else None for row_idx in range(rows)]
        bw, saturated = _beamwidth_minus6db(angles_deg, column)
        if bw is None:
            continue
        curve.append(
            {
                "freq_hz": float(freqs_hz[col_idx]),
                "beamwidth_deg": float(bw),
                "saturated": bool(saturated),
            }
        )
    return curve


def _downsample_indices(length: int, max_count: int) -> List[int]:
    if length <= max_count:
        return list(range(length))
    if max_count <= 1:
        return [0]
    indices: List[int] = []
    for i in range(max_count):
        ratio = i / float(max_count - 1)
        idx = int(round(ratio * float(length - 1)))
        if not indices or idx != indices[-1]:
            indices.append(idx)
    return indices


class AnalyzerPlotService:
    def __init__(self, cache: AnalyzerPlotCache) -> None:
        self._cache = cache

    def load_plane_plot_payload(
        self,
        *,
        db_path: Path,
        project_id: str,
        batch_id: str,
        run_id: Optional[str],
        version_id: str,
        plane: str,
        band_low_hz: float,
        band_high_hz: float,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        key = cache_key_for_request(
            project_id=project_id,
            batch_id=batch_id,
            run_id=run_id,
            version_id=version_id,
            plane=plane,
            norm_policy="nearest_zero",
            band_low_hz=band_low_hz,
            band_high_hz=band_high_hz,
        )
        cached = self._cache.get(key)
        if cached is not None:
            payload = dict(cached)
            payload["cache_hit"] = True
            return payload

        if cancel_check and bool(cancel_check()):
            raise RuntimeError("canceled")

        run_token = str(run_id or "").strip()
        orientation_tokens = orientation_query_aliases(str(plane or "").strip().upper())
        if not orientation_tokens:
            orientation_tokens = [str(plane or "").strip().upper()]
        placeholders = ",".join("?" for _ in orientation_tokens)
        # sqlite3.Connection.__exit__ only commits/rolls back; it does not
        # close the native handle.  Keep closure explicit so Windows project
        # databases can be moved or removed immediately after a plot worker
        # finishes.
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT
                    pm.norm_angle_deg AS norm_angle_deg,
                    pp.freq_hz AS freq_hz,
                    pp.angle_deg AS angle_deg,
                    pp.re AS re,
                    pp.im AS im
                FROM polar_measurements pm
                JOIN polar_points pp ON pp.polar_id = pm.polar_id
                WHERE pm.project_id = ?
                  AND pm.batch_id = ?
                  AND pm.version_id = ?
                  AND COALESCE(pm.run_id, '') = ?
                  AND pm.orientation IN ({placeholders})
                  AND (
                    TRIM(COALESCE(pm.data_level_type, '')) = ''
                    OR LOWER(REPLACE(TRIM(pm.data_level_type), ' ', '')) IN ('soundpressure', 'spl')
                  )
                ORDER BY pp.freq_hz ASC, pp.angle_deg ASC
                """,
                (str(project_id), str(batch_id), str(version_id), run_token, *orientation_tokens),
            ).fetchall()

        if cancel_check and bool(cancel_check()):
            raise RuntimeError("canceled")

        if not rows:
            return {
                "cache_hit": False,
                "freqs_hz": [],
                "angles_deg": [],
                "matrix_db": [],
                "display_freqs_hz": [],
                "display_matrix_db": [],
                "beamwidth_curve": [],
                "ref_angle_deg": None,
                "insufficient_bw": True,
                "message": "Plane not available for selected run/version.",
            }

        freqs = sorted({float(row["freq_hz"]) for row in rows})
        angles = sorted({float(row["angle_deg"]) for row in rows})
        norm_angle_deg = None
        for row in rows:
            raw_norm = row["norm_angle_deg"]
            if raw_norm is None:
                continue
            try:
                norm_angle_deg = float(raw_norm)
                break
            except Exception:
                continue
        freq_index = {value: idx for idx, value in enumerate(freqs)}
        angle_index = {value: idx for idx, value in enumerate(angles)}

        matrix_abs: List[List[Optional[float]]] = [[None] * len(freqs) for _ in range(len(angles))]
        for row in rows:
            f_idx = freq_index.get(float(row["freq_hz"]))
            a_idx = angle_index.get(float(row["angle_deg"]))
            if f_idx is None or a_idx is None:
                continue
            matrix_abs[a_idx][f_idx] = _mag_db(float(row["re"]), float(row["im"]))

        normalized, ref_angle = normalize_relative_to_reference(
            freqs_hz=freqs,
            angles_deg=angles,
            matrix_db=matrix_abs,
            preferred_ref_angle_deg=norm_angle_deg,
        )

        band_cols = [idx for idx, freq in enumerate(freqs) if float(band_low_hz) <= freq <= float(band_high_hz)]
        if not band_cols:
            band_cols = list(range(len(freqs)))
        band_freqs = [freqs[idx] for idx in band_cols]
        band_matrix = [[row[idx] for idx in band_cols] for row in normalized]

        curve = compute_beamwidth_curve(freqs_hz=band_freqs, angles_deg=angles, matrix_db=band_matrix)
        display_indices = _downsample_indices(len(band_freqs), 512)
        display_freqs = [band_freqs[idx] for idx in display_indices]
        display_matrix = [[row[idx] for idx in display_indices] for row in band_matrix]

        payload = {
            "cache_hit": False,
            "freqs_hz": band_freqs,
            "angles_deg": angles,
            "matrix_db": band_matrix,
            "display_freqs_hz": display_freqs,
            "display_matrix_db": display_matrix,
            "beamwidth_curve": curve,
            "ref_angle_deg": float(ref_angle),
            "ref_angle_source": "norm_angle_deg" if norm_angle_deg is not None else "nearest_zero",
            "insufficient_bw": len(curve) <= 2,
            "message": "",
        }
        self._cache.put(key, payload)
        return payload
