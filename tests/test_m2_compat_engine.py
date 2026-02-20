from __future__ import annotations

import unittest

from app.compat_engine import sweepable_params, validity_report, visible_params


class CompatEngineTests(unittest.TestCase):
    def test_length_required_is_fatal_for_explicit_mode(self) -> None:
        report = validity_report({"fixed_params": {}})
        fatal_rule_ids = {item["rule_id"] for item in report["fatal"]}
        self.assertIn("validity_length_required", fatal_rule_ids)

    def test_length_not_required_when_osse_block_is_defined(self) -> None:
        report = validity_report({"fixed_params": {"OSSE": {"L": 80}}})
        fatal_rule_ids = {item["rule_id"] for item in report["fatal"]}
        self.assertNotIn("validity_length_required", fatal_rule_ids)

    def test_length_not_required_when_rosse_block_is_defined(self) -> None:
        report = validity_report({"fixed_params": {"R-OSSE": {"R": 120}}})
        fatal_rule_ids = {item["rule_id"] for item in report["fatal"]}
        self.assertNotIn("validity_length_required", fatal_rule_ids)

    def test_source_contours_overrides_visibility(self) -> None:
        constraints = {
            "fixed_params": {
                "Length": 100,
                "Source.Contours": "::esp section1",
                "Source.Shape": 1,
                "Source.Radius": 24.0,
                "Source.Curv": 1,
            }
        }
        visible = set(visible_params(constraints, runner_mode="AthGuidePreview"))
        self.assertNotIn("Source.Shape", visible)
        self.assertNotIn("Source.Radius", visible)
        self.assertNotIn("Source.Curv", visible)
        self.assertIn("Source.Velocity", visible)

    def test_source_contours_emits_ignored_semantics_notes(self) -> None:
        constraints = {
            "fixed_params": {
                "Length": 100,
                "Source.Contours": "::esp section1",
                "Source.Shape": 1,
                "Source.Radius": 20.0,
                "Source.Curv": -1,
            }
        }
        report = validity_report(constraints, runner_mode="AthGuidePreview")
        info_entries = [item for item in report["info"] if item["category"] == "semantics"]
        messages = [entry["message"] for entry in info_entries]
        self.assertTrue(any("Source.Shape" in message and "Source.Contours" in message for message in messages))
        self.assertTrue(any("Source.Radius" in message and "Source.Contours" in message for message in messages))
        self.assertTrue(any("Source.Curv" in message and "Source.Contours" in message for message in messages))

    def test_runner_restrictions_create_fatal_and_hide_source_keys(self) -> None:
        constraints = {
            "fixed_params": {
                "Length": 90,
                "ABEC.AkabakMode": 2,
                "LE": "something_else",
                "LE.Voltage": 2.5,
                "Source.Shape": 2,
            }
        }
        report = validity_report(constraints)
        runner_fatal = [item for item in report["fatal"] if item["category"] == "runner"]
        self.assertGreaterEqual(len(runner_fatal), 3)

        visible = set(visible_params({"fixed_params": {"Length": 90}}))
        self.assertNotIn("Source.Shape", visible)
        self.assertNotIn("Source.Radius", visible)
        self.assertNotIn("Source.Curv", visible)
        self.assertNotIn("Source.Contours", visible)
        self.assertNotIn("Source.Velocity", visible)

    def test_sweepable_is_deterministic(self) -> None:
        constraints = {"fixed_params": {"Length": 80, "Throat.Profile": 1}}
        first = sweepable_params(constraints)
        second = sweepable_params(constraints)
        self.assertEqual(first, second)

    def test_guidingcurve_requires_dist_and_width_is_fatal(self) -> None:
        constraints = {
            "fixed_params": {
                "Length": 120,
                "GCurve.Type": 2,
            }
        }
        report = validity_report(constraints)
        fatal_rule_ids = {item["rule_id"] for item in report["fatal"]}
        self.assertIn("validity_guidingcurve_requires_dist_and_width", fatal_rule_ids)
        fatal_messages = [
            item["message"]
            for item in report["fatal"]
            if item["rule_id"] == "validity_guidingcurve_requires_dist_and_width"
        ]
        self.assertTrue(any("GCurve.Dist" in message for message in fatal_messages))
        self.assertTrue(any("GCurve.Width" in message for message in fatal_messages))

    def test_guidingcurve_dist_width_not_required_without_type(self) -> None:
        constraints = {
            "fixed_params": {
                "Length": 120,
            }
        }
        report = validity_report(constraints)
        fatal_rule_ids = {item["rule_id"] for item in report["fatal"]}
        warn_rule_ids = {item["rule_id"] for item in report["warn"]}
        self.assertNotIn("validity_guidingcurve_requires_dist_and_width", fatal_rule_ids)
        self.assertNotIn("validity_guidingcurve_requires_dist_and_width", warn_rule_ids)

    def test_dependent_fields_hidden_when_controller_is_not_set(self) -> None:
        visible = set(visible_params({"fixed_params": {"Length": 90}}))
        self.assertNotIn("GCurve.Dist", visible)
        self.assertNotIn("GCurve.SE.n", visible)
        self.assertNotIn("GCurve.SF", visible)
        self.assertNotIn("Term.s", visible)
        self.assertNotIn("CircArc.TermAngle", visible)
        self.assertNotIn("Morph.TargetWidth", visible)
        self.assertNotIn("Rollback.StartAt", visible)
        self.assertIn("Mesh.InterfaceOffset", visible)

    def test_guidingcurve_fields_become_visible_when_type_is_set(self) -> None:
        visible = set(visible_params({"fixed_params": {"Length": 90, "GCurve.Type": 1}}))
        self.assertIn("GCurve.Dist", visible)
        self.assertIn("GCurve.Width", visible)
        self.assertIn("GCurve.SE.n", visible)
        self.assertNotIn("GCurve.SF", visible)

    def test_unset_parameter_is_treated_as_not_defined(self) -> None:
        report = validity_report(
            {
                "fixed_params": {"Length": 120, "GCurve.Type": 1},
                "param_states": [
                    {"param_name": "GCurve.Dist", "is_set": 0, "value": 10},
                    {"param_name": "GCurve.Width", "is_set": 1, "value": 4},
                ],
            }
        )
        fatal_rule_ids = {item["rule_id"] for item in report["fatal"]}
        self.assertIn("validity_guidingcurve_requires_dist_and_width", fatal_rule_ids)


if __name__ == "__main__":
    unittest.main()

