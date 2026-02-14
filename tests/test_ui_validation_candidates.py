from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.ui_validation import UiValidationEngine


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class UiValidationCandidatesTests(unittest.TestCase):
    def test_osse_superformula_candidate_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "range_suggestions.v1.3.json", {"per_key": {}})
            _write(
                root / "compat_rule_candidates.v2.json",
                {
                    "candidates": [
                        {
                            "id": "warn_superformula_osse_risk",
                            "severity": "warn",
                            "condition": "and(eq('Throat.Profile',1), eq('GCurve.Type',2))",
                            "suggested_message_de": "Superformula + OS-SE risk.",
                            "verification_plan": "Counterfactual sweep.",
                        }
                    ]
                },
            )
            engine = UiValidationEngine(reports_root=root)
            draft = {
                "fixed_params": {"Throat.Profile": 1, "GCurve.Type": 2},
                "limits": {},
                "param_states": [
                    {"param_name": "Throat.Profile", "is_set": 1, "value": 1},
                    {"param_name": "GCurve.Type", "is_set": 1, "value": 2},
                ],
            }
            issues = engine.evaluate_experiment_issues(draft, visible_keys={"Throat.Profile", "GCurve.Type"})
            keys = sorted(item.key for item in issues if item.severity == "warn")
            self.assertEqual(keys, ["GCurve.Type", "Throat.Profile"])

    def test_normative_issues_are_mapped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "range_suggestions.v1.3.json", {"per_key": {}})
            _write(root / "compat_rule_candidates.v2.json", {"candidates": []})
            engine = UiValidationEngine(reports_root=root)
            state = {
                "issues": [
                    {
                        "field_key": "Length",
                        "severity": "fatal",
                        "message": "Length required.",
                        "rule_id": "required_length",
                        "evidence_type": "guide",
                    }
                ]
            }
            issues = engine.evaluate_normative_issues(state)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0].key, "Length")
            self.assertEqual(issues[0].severity, "fatal")
            self.assertEqual(issues[0].source, "normative")


if __name__ == "__main__":
    unittest.main()

