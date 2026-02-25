from __future__ import annotations

import unittest

from app.analyzer.plot_service import (
    compute_beamwidth_curve,
    normalize_relative_to_nearest_zero,
    normalize_relative_to_reference,
)


class AnalyzerPlotServiceMathTests(unittest.TestCase):
    def test_normalize_uses_nearest_angle_to_zero(self) -> None:
        freqs = [200.0, 400.0]
        angles = [-15.0, 5.0, 25.0]
        matrix = [
            [-8.0, -7.0],
            [-2.0, -1.0],
            [-10.0, -9.0],
        ]
        normalized, ref_angle = normalize_relative_to_nearest_zero(
            freqs_hz=freqs,
            angles_deg=angles,
            matrix_db=matrix,
        )
        self.assertAlmostEqual(ref_angle, 5.0)
        self.assertEqual(normalized[1], [0.0, 0.0])
        self.assertAlmostEqual(float(normalized[0][0]), -6.0)

    def test_beamwidth_curve_from_synthetic_minus6_profile(self) -> None:
        freqs = [500.0, 1000.0, 2000.0]
        angles = [-30.0, -20.0, -10.0, 0.0, 10.0, 20.0, 30.0]
        # Symmetric profile around 0deg. -6 dB crossing lies between 10deg and 20deg.
        matrix = [
            [-18.0, -18.0, -18.0],
            [-8.0, -8.0, -8.0],
            [-3.0, -3.0, -3.0],
            [0.0, 0.0, 0.0],
            [-3.0, -3.0, -3.0],
            [-8.0, -8.0, -8.0],
            [-18.0, -18.0, -18.0],
        ]
        curve = compute_beamwidth_curve(freqs_hz=freqs, angles_deg=angles, matrix_db=matrix)
        self.assertEqual(len(curve), 3)
        for point in curve:
            self.assertGreater(float(point["beamwidth_deg"]), 30.0)
            self.assertLess(float(point["beamwidth_deg"]), 34.0)
            self.assertFalse(bool(point.get("saturated")))

    def test_beamwidth_curve_saturates_when_minus6_crossing_is_absent(self) -> None:
        freqs = [1000.0]
        angles = [-90.0, -45.0, 0.0, 45.0, 90.0]
        matrix = [[-2.0], [-1.5], [0.0], [-1.5], [-2.0]]
        curve = compute_beamwidth_curve(freqs_hz=freqs, angles_deg=angles, matrix_db=matrix)
        self.assertEqual(len(curve), 1)
        self.assertAlmostEqual(float(curve[0]["beamwidth_deg"]), 180.0)
        self.assertTrue(bool(curve[0].get("saturated")))

    def test_normalize_prefers_provided_norm_angle_when_present(self) -> None:
        freqs = [1000.0]
        angles = [-10.0, 0.0, 10.0]
        matrix = [[-8.0], [0.0], [-2.0]]
        normalized, ref_angle = normalize_relative_to_reference(
            freqs_hz=freqs,
            angles_deg=angles,
            matrix_db=matrix,
            preferred_ref_angle_deg=10.0,
        )
        self.assertAlmostEqual(ref_angle, 10.0)
        self.assertAlmostEqual(float(normalized[2][0]), 0.0)


if __name__ == "__main__":
    unittest.main()
