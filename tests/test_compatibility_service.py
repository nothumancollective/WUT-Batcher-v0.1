from __future__ import annotations

import unittest

from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE


class CompatibilityServiceTests(unittest.TestCase):
    def test_project_evaluation_reports_locked_and_doc_backed_length_rule(self) -> None:
        service = CompatibilityService()
        state = service.evaluate_project_constraints(
            {
                "fixed_params": {},
                "limits": {},
                "runner_mode": DEFAULT_RUNNER_MODE,
            }
        )
        self.assertIn("Source.Shape", state["locked_keys"])
        length_issues = [item for item in state["issues"] if item["rule_id"] == "validity_length_required"]
        self.assertGreaterEqual(len(length_issues), 1)
        self.assertEqual(length_issues[0]["evidence_type"], "ath_doc")

    def test_batch_evaluation_uses_selected_params_for_visibility(self) -> None:
        service = CompatibilityService()
        state = service.evaluate_batch_definition(
            {
                "project_id": "P001",
                "fixed_params": {"Length": 120},
                "limits": {},
                "runner_mode": DEFAULT_RUNNER_MODE,
            },
            selected_params={"GCurve.Type": 1},
            sweeps={},
            sweep_mode="single",
        )
        self.assertIn("GCurve.Dist", state["visible_keys"])
        issues = [item for item in state["issues"] if item["rule_id"] == "validity_guidingcurve_requires_dist_and_width"]
        self.assertGreaterEqual(len(issues), 1)
        self.assertEqual(issues[0]["evidence_type"], "hypothesis")

    def test_batch_evaluation_respects_length_defined_by_batch(self) -> None:
        service = CompatibilityService()
        state = service.evaluate_batch_definition(
            {
                "project_id": "P001",
                "fixed_params": {},
                "limits": {},
                "runner_mode": DEFAULT_RUNNER_MODE,
            },
            selected_params={"Length": 220.0},
            sweeps={},
            sweep_mode="single",
        )
        rule_ids = {str(item.get("rule_id", "")) for item in list(state.get("issues", []) or [])}
        self.assertNotIn("validity_length_required", rule_ids)


if __name__ == "__main__":
    unittest.main()
