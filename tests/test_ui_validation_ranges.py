from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.ui_validation import UiValidationEngine


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class UiValidationRangesTests(unittest.TestCase):
    def test_in_range_out_of_range_and_hard_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "range_suggestions.v1.3.json",
                {
                    "per_key": {
                        "Length": {
                            "safe_min": 100.0,
                            "safe_max": 1200.0,
                            "rec_p05": 200.0,
                            "rec_p95": 1000.0,
                            "notes": "range-test",
                        }
                    }
                },
            )
            _write(
                root / "compat_rule_candidates.v2.json",
                {
                    "candidates": [
                        {
                            "id": "fatal_input_hard_cap_5000_mm",
                            "severity": "fatal",
                            "condition": "any(gt(input_numeric, 5000))",
                            "suggested_message_de": "Hard cap exceeded.",
                            "verification_plan": "Reduce inputs.",
                        }
                    ]
                },
            )
            engine = UiValidationEngine(reports_root=root)
            self.assertTrue(engine.enabled)

            draft_ok = {
                "fixed_params": {"Length": 600.0},
                "limits": {},
                "param_states": [{"param_name": "Length", "is_set": 1, "value": 600.0}],
            }
            ok_issues = engine.evaluate_experiment_issues(draft_ok, visible_keys={"Length"})
            self.assertTrue(any(item.severity == "ok" and item.key == "Length" for item in ok_issues))

            draft_warn = {
                "fixed_params": {"Length": 1100.0},
                "limits": {},
                "param_states": [{"param_name": "Length", "is_set": 1, "value": 1100.0}],
            }
            warn_issues = engine.evaluate_experiment_issues(draft_warn, visible_keys={"Length"})
            self.assertTrue(any(item.severity == "warn" and item.key == "Length" for item in warn_issues))

            draft_fatal = {
                "fixed_params": {"Length": 6000.0},
                "limits": {},
                "param_states": [{"param_name": "Length", "is_set": 1, "value": 6000.0}],
            }
            fatal_issues = engine.evaluate_experiment_issues(draft_fatal, visible_keys={"Length"})
            self.assertTrue(any(item.severity == "fatal" and item.key == "Length" for item in fatal_issues))

    def test_latest_versioned_files_are_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "range_suggestions.v1.2.json", {"per_key": {}})
            _write(root / "range_suggestions.v1.3.json", {"per_key": {"Length": {"safe_min": 10, "safe_max": 20}}})
            _write(root / "compat_rule_candidates.v1.json", {"candidates": []})
            _write(root / "compat_rule_candidates.v2.json", {"candidates": []})
            engine = UiValidationEngine(reports_root=root)
            self.assertEqual(engine.range_path.name, "range_suggestions.v1.3.json")
            self.assertEqual(engine.candidates_path.name, "compat_rule_candidates.v2.json")


if __name__ == "__main__":
    unittest.main()

