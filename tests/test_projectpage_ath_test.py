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

    def test_parse_empty_object_assignment_with_following_members(self) -> None:
        text = (
            "R-OSSE = \n"
            "R = 100\n"
            "r0 = 17\n"
            "a0 = 4.5\n"
            "Coverage.Angle = 52\n"
        )
        parsed = parse_key_value_text(text)
        self.assertEqual(parsed["R-OSSE.R"], "100")
        self.assertEqual(parsed["R-OSSE.r0"], "17")
        self.assertEqual(parsed["R-OSSE.a0"], "4.5")
        self.assertEqual(parsed["Coverage.Angle"], "52")

    def test_parse_empty_list_assignment_with_braces(self) -> None:
        text = (
            "Mesh.SubdomainSlices = \n"
            "{\n"
            "12, 14, 18\n"
            "}\n"
            "Length = 120\n"
        )
        parsed = parse_key_value_text(text)
        self.assertEqual(parsed["Mesh.SubdomainSlices"], [12, 14, 18])
        self.assertEqual(parsed["Length"], "120")

    def test_parse_inline_list_assignment(self) -> None:
        text = "GCurve.SF = 1.0, 1.0, 5.0, 0.3, 1.1, 1.1\n"
        parsed = parse_key_value_text(text)
        self.assertEqual(parsed["GCurve.SF"], [1, 1, 5, 0.3, 1.1, 1.1])

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
        self.assertEqual(result["missing_keys_required"], [])
        self.assertEqual(result["extra_keys_ghost"], ["Ghost.Key"])
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

    def test_compare_expected_supports_optional_missing_prefixes(self) -> None:
        expected = {"Mesh.AngularSegments": 64, "Length": 120}
        observed = {"Length": "120"}
        result = compare_expected(
            expected=expected,
            observed=observed,
            allowed_global_keys={"ABEC.AkabakMode", "LE", "LE.Voltage"},
            optional_missing_prefixes=("Mesh.",),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing_keys_required"], [])
        self.assertEqual(result["missing_keys_optional"], ["Mesh.AngularSegments"])

    def test_compare_expected_treats_bool_and_numeric_true_equal(self) -> None:
        expected = {"Morph.AllowShrinkage": True}
        observed = {"Morph.AllowShrinkage": "1.0"}
        result = compare_expected(
            expected=expected,
            observed=observed,
            allowed_global_keys={"ABEC.AkabakMode", "LE", "LE.Voltage"},
            comparison_target="ath_config",
        )
        self.assertTrue(result["ok"])

    def test_compare_expected_treats_list_string_and_list_equal(self) -> None:
        expected = {"Mesh.SubdomainSlices": [12, 14, 18]}
        observed = {"Mesh.SubdomainSlices": "12,14,18"}
        result = compare_expected(
            expected=expected,
            observed=observed,
            allowed_global_keys={"ABEC.AkabakMode", "LE", "LE.Voltage"},
            comparison_target="ath_config",
        )
        self.assertTrue(result["ok"])

    def test_compare_expected_treats_empty_optional_lists_as_config_equivalent(self) -> None:
        expected = {
            "Mesh.SubdomainSlices": [12, 14, 18],
            "Mesh.InterfaceDraw": [8.1, 2.3, 4.4],
            "Mesh.ZMapPoints": [0.2, 0.5, 0.9],
        }
        observed = {
            "Mesh.SubdomainSlices": "",
            "Mesh.InterfaceDraw": "",
            "Mesh.ZMapPoints": "",
        }
        result = compare_expected(
            expected=expected,
            observed=observed,
            allowed_global_keys={"ABEC.AkabakMode", "LE", "LE.Voltage"},
            comparison_target="ath_config",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["value_mismatches"], [])

    def test_compare_expected_supports_gcurve_sf_alias_subkeys(self) -> None:
        expected = {"GCurve.SF": [1.0, 1.0, 5.0, 0.3, 1.1, 1.1]}
        observed = {
            "GCurve.SF.a": "1",
            "GCurve.SF.b": "1",
            "GCurve.SF.m1": "5",
            "GCurve.SF.m2": "5",
            "GCurve.SF.n1": "0.3",
            "GCurve.SF.n2": "1.1",
            "GCurve.SF.n3": "1.1",
        }
        result = compare_expected(
            expected=expected,
            observed=observed,
            allowed_global_keys={"ABEC.AkabakMode", "LE", "LE.Voltage"},
            comparison_target="ath_config",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["extra_keys_ghost"], [])


if __name__ == "__main__":
    unittest.main()
