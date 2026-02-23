from __future__ import annotations

import unittest

from app.analyzer.orientation import canonical_orientation_token, orientation_query_aliases


class AnalyzerOrientationTests(unittest.TestCase):
    def test_canonical_orientation_maps_known_aliases_without_collisions(self) -> None:
        self.assertEqual(canonical_orientation_token("H"), "H")
        self.assertEqual(canonical_orientation_token("x3_0"), "H")
        self.assertEqual(canonical_orientation_token("X3_90"), "V")
        self.assertEqual(canonical_orientation_token("X3_45"), "D")
        self.assertEqual(canonical_orientation_token("X3_42.0"), "D")

    def test_query_aliases_include_high_precision_x3_tokens(self) -> None:
        h_aliases = orientation_query_aliases("H")
        self.assertIn("X3_0.000000", h_aliases)
        v_aliases = orientation_query_aliases("V")
        self.assertIn("X3_90.000000", v_aliases)
        d_aliases = orientation_query_aliases("D")
        self.assertIn("X3_45.000000", d_aliases)

    def test_unknown_orientation_stays_unknown(self) -> None:
        self.assertEqual(canonical_orientation_token("X3_13"), "X3_13")
        self.assertEqual(orientation_query_aliases("X3_13"), ["X3_13"])


if __name__ == "__main__":
    unittest.main()
