from __future__ import annotations

import unittest

from app.analyzer.heatmap_style import compare_overlay_color, get_vacs_like_lut


class AnalyzerHeatmapStyleTests(unittest.TestCase):
    def test_lut_shape_and_endpoint_contrast(self) -> None:
        lut = get_vacs_like_lut(256)
        self.assertEqual(len(lut), 256)
        self.assertTrue(all(len(item) == 3 for item in lut))
        low = lut[0]
        high = lut[-1]
        self.assertNotEqual(low, high)
        self.assertGreater(sum(high), sum(low))
        self.assertGreater(high[0], low[0])

    def test_overlay_palette_returns_distinct_colors_for_first_five(self) -> None:
        colors = [compare_overlay_color(index) for index in range(5)]
        self.assertEqual(len(colors), 5)
        self.assertEqual(len(set(colors)), 5)


if __name__ == "__main__":
    unittest.main()
