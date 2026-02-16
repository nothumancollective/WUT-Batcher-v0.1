from __future__ import annotations

import unittest

from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE


class CompatibilityServiceBatchUiSeparationTests(unittest.TestCase):
    def test_batch_evaluation_does_not_return_ui_specific_prevention_fields(self) -> None:
        service = CompatibilityService()
        state = service.evaluate_batch_definition(
            {
                "project_id": "P001",
                "fixed_params": {"Length": 200},
                "limits": {},
                "runner_mode": DEFAULT_RUNNER_MODE,
            },
            selected_params={"GCurve.Type": 1},
            sweeps={},
            sweep_mode="single",
        )
        self.assertNotIn("prevented_keys", state)
        self.assertNotIn("prevented_reasons", state)
        self.assertNotIn("ui_hint_trigger_key", state)
        self.assertIn("visible_keys", state)
        self.assertIn("locked_keys", state)
        self.assertIn("sweepable_keys", state)
        self.assertIn("issues", state)


if __name__ == "__main__":
    unittest.main()
