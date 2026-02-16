from __future__ import annotations

import unittest
from unittest.mock import patch

from app.compatibility_service import CompatibilityService


class _Resolved:
    def __init__(self) -> None:
        self.issues = []
        self.versions = [object()]


class CompatibilityFatalPreventionTests(unittest.TestCase):
    @patch("app.compatibility_service.resolve_versions", return_value=_Resolved())
    @patch("app.compatibility_service.sweepable_params", return_value=[])
    @patch("app.compatibility_service.visible_params", return_value=["Param.A"])
    def test_prevented_keys_are_reported_for_actionable_fatals(
        self,
        _visible_mock,
        _sweepable_mock,
        _resolve_mock,
    ) -> None:
        svc = CompatibilityService()

        def fake_validity(preview, runner_mode=None, bundle=None):  # noqa: ANN001
            fixed = dict(preview.get("fixed_params", {}) or {})
            if fixed.get("Param.A") is not None:
                return {
                    "issues": [
                        {
                            "rule_id": "fatal_conflict_probe",
                            "severity": "fatal",
                            "category": "ath",
                            "message": "Param.A conflicts with current mode.",
                        }
                    ]
                }
            return {"issues": []}

        with patch("app.compatibility_service.validity_report", side_effect=fake_validity):
            state = svc.evaluate_batch_definition(
                {"project_id": "P001", "fixed_params": {}, "limits": {}, "runner_mode": "AkabakImportFixedSource"},
                selected_params={},
                sweeps={},
                sweep_mode="single",
                ui_hint_trigger_key="Throat.Profile",
            )

        self.assertIn("Param.A", set(state.get("prevented_keys", [])))
        reasons = dict(state.get("prevented_reasons", {}))
        self.assertIn("Param.A", reasons)
        self.assertEqual(reasons["Param.A"].get("trigger_key"), "Throat.Profile")

    @patch("app.compatibility_service.resolve_versions", return_value=_Resolved())
    @patch("app.compatibility_service.sweepable_params", return_value=[])
    @patch("app.compatibility_service.visible_params", return_value=["Param.A"])
    def test_prevention_also_applies_to_already_selected_conflict_key(
        self,
        _visible_mock,
        _sweepable_mock,
        _resolve_mock,
    ) -> None:
        svc = CompatibilityService()

        def fake_validity(preview, runner_mode=None, bundle=None):  # noqa: ANN001
            fixed = dict(preview.get("fixed_params", {}) or {})
            if fixed.get("Param.A") is not None:
                return {
                    "issues": [
                        {
                            "rule_id": "fatal_conflict_probe",
                            "severity": "fatal",
                            "category": "ath",
                            "message": "Param.A conflicts with current mode.",
                        }
                    ]
                }
            return {"issues": []}

        with patch("app.compatibility_service.validity_report", side_effect=fake_validity):
            state = svc.evaluate_batch_definition(
                {"project_id": "P001", "fixed_params": {}, "limits": {}, "runner_mode": "AkabakImportFixedSource"},
                selected_params={"Param.A": 2.0},
                sweeps={},
                sweep_mode="single",
                ui_hint_trigger_key="Param.B",
            )

        self.assertIn("Param.A", set(state.get("prevented_keys", [])))

    @patch("app.compatibility_service.resolve_versions", return_value=_Resolved())
    @patch("app.compatibility_service.sweepable_params", return_value=[])
    @patch("app.compatibility_service.visible_params", return_value=["Param.A"])
    def test_missing_required_fatals_are_not_prevented(
        self,
        _visible_mock,
        _sweepable_mock,
        _resolve_mock,
    ) -> None:
        svc = CompatibilityService()

        def fake_validity(preview, runner_mode=None, bundle=None):  # noqa: ANN001
            fixed = dict(preview.get("fixed_params", {}) or {})
            if fixed.get("Param.A") is not None:
                return {
                    "issues": [
                        {
                            "rule_id": "validity_length_required",
                            "severity": "fatal",
                            "category": "ath",
                            "message": "Length is required.",
                        }
                    ]
                }
            return {"issues": []}

        with patch("app.compatibility_service.validity_report", side_effect=fake_validity):
            state = svc.evaluate_batch_definition(
                {"project_id": "P001", "fixed_params": {}, "limits": {}, "runner_mode": "AkabakImportFixedSource"},
                selected_params={},
                sweeps={},
                sweep_mode="single",
                ui_hint_trigger_key="Param.A",
            )

        self.assertEqual(list(state.get("prevented_keys", [])), [])


if __name__ == "__main__":
    unittest.main()
