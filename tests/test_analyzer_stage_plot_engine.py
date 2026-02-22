from __future__ import annotations

import unittest

from app.analyzer.plot_service import compute_beamwidth_curve
from app.analyzer.stage_plot_engine import (
    compute_di_proxy_curve,
    compute_plane_consistency_curve,
    compute_stage1_curves,
    compute_stage_plot_payload,
)


def _build_matrix(
    *,
    freqs: list[float],
    angles: list[float],
    half_bw_by_freq: dict[float, float],
) -> list[list[float]]:
    rows: list[list[float]] = []
    for angle in angles:
        row: list[float] = []
        for freq in freqs:
            half_bw = max(float(half_bw_by_freq.get(float(freq), 30.0)), 1.0)
            attenuation = min((abs(float(angle)) / half_bw) * 6.0, 30.0)
            row.append(-attenuation)
        rows.append(row)
    return rows


class AnalyzerStagePlotEngineTests(unittest.TestCase):
    def test_stage1_curves_include_overlays_and_primary_metrics(self) -> None:
        freqs = [200.0, 400.0, 800.0, 1600.0]
        angles = [-60.0, -40.0, -20.0, 0.0, 20.0, 40.0, 60.0]
        matrix = _build_matrix(
            freqs=freqs,
            angles=angles,
            half_bw_by_freq={200.0: 30.0, 400.0: 30.0, 800.0: 30.0, 1600.0: 30.0},
        )
        payload = compute_stage1_curves(
            freqs_hz=freqs,
            angles_deg=angles,
            matrix_db=matrix,
            target_deg=60.0,
            tol_deg=5.0,
        )
        self.assertGreater(len(payload["beamwidth_curve"]), 0)
        self.assertGreater(len(payload["e_bw_curve"]), 0)
        self.assertGreater(len(payload["e_cov_curve"]), 0)
        self.assertGreater(len(payload["r_spill_curve"]), 0)
        overlays = dict(payload.get("heatmap_overlays") or {})
        self.assertGreater(len(list(overlays.get("minus6_contour", []) or [])), 0)
        self.assertAlmostEqual(float(overlays.get("target_half_window_deg") or 0.0), 30.0)

    def test_stabilization_payload_contains_di_smoothness_and_plane_consistency(self) -> None:
        freqs = [200.0, 400.0, 800.0, 1600.0]
        angles = [-60.0, -40.0, -20.0, 0.0, 20.0, 40.0, 60.0]
        matrix_h = _build_matrix(
            freqs=freqs,
            angles=angles,
            half_bw_by_freq={200.0: 30.0, 400.0: 28.0, 800.0: 26.0, 1600.0: 24.0},
        )
        matrix_v = _build_matrix(
            freqs=freqs,
            angles=angles,
            half_bw_by_freq={200.0: 30.0, 400.0: 30.0, 800.0: 30.0, 1600.0: 30.0},
        )
        bw_h = compute_beamwidth_curve(freqs_hz=freqs, angles_deg=angles, matrix_db=matrix_h)
        bw_v = compute_beamwidth_curve(freqs_hz=freqs, angles_deg=angles, matrix_db=matrix_v)
        di_h = compute_di_proxy_curve(
            freqs_hz=freqs,
            angles_deg=angles,
            matrix_db=matrix_h,
            target_deg=60.0,
            norm_angle_deg=0.0,
        )
        di_v = compute_di_proxy_curve(
            freqs_hz=freqs,
            angles_deg=angles,
            matrix_db=matrix_v,
            target_deg=60.0,
            norm_angle_deg=0.0,
        )
        payload = compute_stage_plot_payload(
            stage_mode="stabilization",
            target_deg=60.0,
            tol_deg=5.0,
            freqs_hz=freqs,
            angles_deg=angles,
            matrix_db=matrix_h,
            beamwidth_curve=bw_h,
            norm_angle_deg=0.0,
            use_full_angles_for_smoothness=False,
            bw_curves_by_plane={"H": bw_h, "V": bw_v},
            di_curves_by_plane={"H": di_h, "V": di_v},
            artifact_status={"POLAR": {"available": True}},
        )
        curves = dict(payload.get("curves") or {})
        self.assertGreater(len(list(curves.get("di_proxy", []) or [])), 0)
        self.assertGreater(len(list(curves.get("s_theta", []) or [])), 0)
        self.assertGreater(len(list(curves.get("e_sym_shape", []) or [])), 0)

    def test_plane_consistency_prefers_bw_then_falls_back_to_di(self) -> None:
        bw_consistency = compute_plane_consistency_curve(
            bw_by_plane={
                "H": [{"freq_hz": 500.0, "beamwidth_deg": 60.0}],
                "V": [{"freq_hz": 500.0, "beamwidth_deg": 64.0}],
            }
        )
        self.assertEqual(len(bw_consistency), 1)
        self.assertGreater(float(bw_consistency[0]["value"]), 0.0)

        di_consistency = compute_plane_consistency_curve(
            bw_by_plane={},
            di_by_plane={
                "H": [{"freq_hz": 1000.0, "value": 3.0}],
                "V": [{"freq_hz": 1000.0, "value": 4.0}],
            },
        )
        self.assertEqual(len(di_consistency), 1)
        self.assertGreater(float(di_consistency[0]["value"]), 0.0)


if __name__ == "__main__":
    unittest.main()
