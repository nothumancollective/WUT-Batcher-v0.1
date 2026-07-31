from __future__ import annotations

import unittest

from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE


class CompatibilityServiceBatchSweepValidationTests(unittest.TestCase):
    def test_invalid_sweep_payload_reports_issue_and_blocks_preview_count(self) -> None:
        service = CompatibilityService()
        state = service.evaluate_batch_definition(
            {
                "project_id": "P001",
                "fixed_params": {"Length": 200},
                "limits": {},
                "runner_mode": DEFAULT_RUNNER_MODE,
            },
            selected_params={},
            sweeps={"Throat.Diameter": {"start": "x", "end": 20, "steps": 3}},
            sweep_mode="single",
        )
        rules = [str(item.get("rule_id", "")) for item in list(state.get("issues", []) or []) if isinstance(item, dict)]
        self.assertIn("sweep_parse_failed", rules)
        self.assertEqual(int(state.get("version_count_preview", -1)), 0)

    def test_cartesian_explosion_is_rejected_without_materialization(self) -> None:
        service = CompatibilityService()
        state = service.evaluate_batch_definition(
            {
                "project_id": "P001",
                "fixed_params": {"Length": 200},
                "limits": {},
                "runner_mode": "AthGuidePreview",
            },
            selected_params={},
            sweeps={
                "Coverage.Angle": {"start": 20, "end": 80, "steps": 101},
                "Throat.Diameter": {"start": 20, "end": 80, "steps": 101},
            },
            sweep_mode="combined",
        )
        rules = {str(item.get("rule_id", "")) for item in list(state.get("issues", []) or [])}
        self.assertIn("batch_version_limit_exceeded", rules)
        self.assertEqual(int(state.get("version_count_preview", -1)), 0)
        self.assertEqual(int(state.get("version_count_estimate", -1)), 10_201)


if __name__ == "__main__":
    unittest.main()
