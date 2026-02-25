from __future__ import annotations

import unittest

from app.analyzer.metric_band_specs import LOWER_IS_BETTER, metric_band_regions_from_spec


class MetricBandSpecMappingTests(unittest.TestCase):
    def test_lower_is_better_spec_maps_to_bottom_good_and_upper_warn_regions(self) -> None:
        spec = {
            "kpi_key": "s_theta",
            "direction": LOWER_IS_BETTER,
            "good_range": (0.0, 0.20),
            "warn_range": (0.20, 0.40),
        }
        mapped = metric_band_regions_from_spec(spec=spec, axis_min=0.0, axis_max=1.0)
        regions = list(mapped.get("regions", []) or [])
        self.assertEqual(
            regions,
            [
                {"role": "good", "y_low": 0.0, "y_high": 0.2},
                {"role": "warn", "y_low": 0.2, "y_high": 0.4},
            ],
        )


if __name__ == "__main__":
    unittest.main()

