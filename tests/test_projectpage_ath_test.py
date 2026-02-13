from __future__ import annotations

import unittest

from app.projectpage_ath_test import compare_expected, parse_key_value_text


class ProjectPageAthTestParsingTests(unittest.TestCase):
    def test_parse_cfg_object_json_into_flattened_keys(self) -> None:
        text = (
            'Length = 130\n'
            'R-OSSE = {"R": 100, "r0": 17.0, "a0": 4.5}\n'
            'ABEC.AkabakMode = 1\n'
        )
        parsed = parse_key_value_text(text)
        self.assertEqual(parsed["Length"], "130")
        self.assertEqual(parsed["R-OSSE.R"], 100)
        self.assertEqual(parsed["R-OSSE.r0"], 17.0)
        self.assertEqual(parsed["R-OSSE.a0"], 4.5)

    def test_parse_config_block_into_flattened_keys(self) -> None:
        text = (
            "OSSE = {\n"
            "s = 0.7 + 0.2*cos(p)^2\n"
            "q = 0.995\n"
            "}\n"
            "Mesh.AngularSegments = 80\n"
        )
        parsed = parse_key_value_text(text)
        self.assertEqual(parsed["OSSE.s"], "0.7 + 0.2*cos(p)^2")
        self.assertEqual(parsed["OSSE.q"], "0.995")
        self.assertEqual(parsed["Mesh.AngularSegments"], "80")

    def test_compare_expected_detects_missing_extra_and_mismatch(self) -> None:
        expected = {"Length": 130.0, "Coverage.Angle": "48.5"}
        observed = {
            "Length": "129.0",
            "Coverage.Angle": "48,5",
            "Ghost.Key": "1",
        }
        result = compare_expected(
            expected=expected,
            observed=observed,
            allowed_global_keys={"ABEC.AkabakMode", "LE", "LE.Voltage"},
        )
        self.assertEqual(result["missing_keys"], [])
        self.assertEqual(result["extra_keys"], ["Ghost.Key"])
        self.assertEqual(len(result["value_mismatches"]), 1)
        self.assertEqual(result["value_mismatches"][0]["key"], "Length")

    def test_compare_expected_allows_mandatory_global_keys(self) -> None:
        expected = {"Length": 120}
        observed = {
            "Length": "120",
            "ABEC.AkabakMode": "1",
            "LE": "generic25",
            "LE.Voltage": "1.0",
        }
        result = compare_expected(
            expected=expected,
            observed=observed,
            allowed_global_keys={"ABEC.AkabakMode", "LE", "LE.Voltage"},
        )
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()

