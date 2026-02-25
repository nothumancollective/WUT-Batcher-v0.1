from __future__ import annotations

import unittest

from app.analyzer.reason_codes import reason_item, reason_items_for_codes


class AnalyzerReasonCodesTests(unittest.TestCase):
    def test_catalog_contains_expected_severity(self) -> None:
        self.assertEqual(str(reason_item("MISSING_PLANE").get("severity") or ""), "warn")
        self.assertEqual(str(reason_item("EMPTY_BAND_INTERSECTION").get("severity") or ""), "error")
        self.assertEqual(str(reason_item("BEAMWIDTH_SATURATED").get("severity") or ""), "warn")

    def test_reason_items_dedup_preserves_order(self) -> None:
        items = reason_items_for_codes(["MISSING_PLANE", "MISSING_PLANE", "INSUFFICIENT_ANGLE_COVERAGE"])
        self.assertEqual([str(item.get("code")) for item in items], ["MISSING_PLANE", "INSUFFICIENT_ANGLE_COVERAGE"])


if __name__ == "__main__":
    unittest.main()
