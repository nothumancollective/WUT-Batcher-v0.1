from __future__ import annotations

import math
import unittest

from app.analyzer.kpi_engine import compute_run_kpis, compute_stage_score


def _build_plane_points(
    *,
    freqs: list[float],
    angles: list[float],
    nominal_bw_deg: float,
    bw_overrides: dict[float, float] | None = None,
) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    overrides = dict(bw_overrides or {})
    for freq in freqs:
        bw = float(overrides.get(freq, nominal_bw_deg))
        half_bw = max(bw * 0.5, 1.0)
        for angle in angles:
            attenuation_db = min((abs(angle) / half_bw) * 6.0, 30.0)
            db = -attenuation_db
            magnitude = 10.0 ** (db / 20.0)
            rows.append(
                {
                    "freq_hz": float(freq),
                    "angle_deg": float(angle),
                    "re": float(magnitude),
                    "im": 0.0,
                }
            )
    return rows


class AnalyzerKpiEngineTests(unittest.TestCase):
    def test_compute_run_kpis_balanced_pattern_has_low_error(self) -> None:
        freqs = [200.0, 400.0, 800.0, 1600.0]
        angles = [-90.0, -60.0, -45.0, -30.0, -15.0, 0.0, 15.0, 30.0, 45.0, 60.0, 90.0]
        plane_points = _build_plane_points(freqs=freqs, angles=angles, nominal_bw_deg=60.0)

        payload = compute_run_kpis(
            planes_points={"H": plane_points, "V": plane_points},
            target_h_deg=60.0,
            target_v_deg=60.0,
            tol_deg=5.0,
            band_low_hz=200.0,
            band_high_hz=1600.0,
        )
        aggregate = dict(payload.get("aggregate", {}) or {})
        self.assertLess(float(aggregate.get("e_bw") or 0.0), 1.5)
        self.assertGreater(float(aggregate.get("b_pc_oct") or 0.0), 2.5)
        self.assertEqual(int(aggregate.get("flags_count") or 0), 0)
        shaping_score = compute_stage_score(payload, stage_id="shaping")
        self.assertGreater(shaping_score, 70.0)

    def test_compute_run_kpis_detects_jump_and_collapse_flags(self) -> None:
        freqs = [200.0, 400.0, 800.0, 1600.0]
        angles = [-90.0, -60.0, -45.0, -30.0, -15.0, 0.0, 15.0, 30.0, 45.0, 60.0, 90.0]
        base = _build_plane_points(freqs=freqs, angles=angles, nominal_bw_deg=60.0)
        # Force a narrow collapse at 800 Hz in H plane.
        collapsed_h = _build_plane_points(
            freqs=freqs,
            angles=angles,
            nominal_bw_deg=60.0,
            bw_overrides={800.0: 18.0},
        )

        payload = compute_run_kpis(
            planes_points={"H": collapsed_h, "V": base},
            target_h_deg=60.0,
            target_v_deg=60.0,
            tol_deg=5.0,
            band_low_hz=200.0,
            band_high_hz=1600.0,
        )
        aggregate = dict(payload.get("aggregate", {}) or {})
        self.assertGreater(int(aggregate.get("flags_count") or 0), 0)
        self.assertTrue(bool(aggregate.get("flagged")))
        self.assertFalse(math.isnan(float(compute_stage_score(payload, stage_id="concept"))))

    def test_one_sided_angles_are_scored_with_limited_coverage_reason(self) -> None:
        freqs = [500.0, 1000.0, 2000.0, 4000.0]
        angles = [0.0, 10.0, 20.0, 30.0, 45.0, 60.0, 75.0, 90.0]
        plane_points = _build_plane_points(freqs=freqs, angles=angles, nominal_bw_deg=50.0)
        payload = compute_run_kpis(
            planes_points={"V": plane_points},
            target_h_deg=90.0,
            target_v_deg=50.0,
            tol_deg=5.0,
            band_low_hz=500.0,
            band_high_hz=4000.0,
        )
        reason_codes = list(payload.get("flags", {}).get("reason_codes", []) or [])
        self.assertIn("INSUFFICIENT_ANGLE_COVERAGE", reason_codes)
        score = compute_stage_score(payload, stage_id="shaping")
        self.assertIsNotNone(score)

    def test_empty_band_intersection_marks_payload_unscorable(self) -> None:
        freqs = [500.0, 1000.0, 2000.0]
        angles = [-60.0, -30.0, 0.0, 30.0, 60.0]
        plane_points = _build_plane_points(freqs=freqs, angles=angles, nominal_bw_deg=60.0)
        payload = compute_run_kpis(
            planes_points={"H": plane_points},
            target_h_deg=60.0,
            target_v_deg=60.0,
            tol_deg=5.0,
            band_low_hz=8000.0,
            band_high_hz=12000.0,
        )
        reason_codes = list(payload.get("flags", {}).get("reason_codes", []) or [])
        self.assertIn("EMPTY_BAND_INTERSECTION", reason_codes)
        self.assertIsNone(compute_stage_score(payload, stage_id="concept"))


if __name__ == "__main__":
    unittest.main()
