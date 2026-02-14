from __future__ import annotations

import unittest

from app.project_issue_model import classify_ui_severity, normalize_project_issues


class ProjectIssueModelTests(unittest.TestCase):
    def test_required_missing_fatal_is_incomplete_when_unset(self) -> None:
        raw = {
            "field_key": "Length",
            "severity": "fatal",
            "rule_id": "validity_length_required",
            "message": "Length is required.",
        }
        self.assertEqual(classify_ui_severity(raw, field_is_set=False), "incomplete")
        self.assertEqual(classify_ui_severity(raw, field_is_set=True), "error")

    def test_deterministic_order_error_warn_incomplete(self) -> None:
        issues = normalize_project_issues(
            [
                {"field_key": "A", "severity": "warn", "message": "warn a", "rule_id": "warn_a"},
                {"field_key": "B", "severity": "fatal", "message": "bad b", "rule_id": "bad_b"},
                {"field_key": "C", "severity": "fatal", "message": "C required", "rule_id": "c_required"},
            ],
            field_is_set={"A": True, "B": True, "C": False},
            field_labels={"A": "Alpha", "B": "Beta", "C": "Gamma"},
            field_sections={"A": "Basics", "B": "Basics", "C": "Basics"},
        )
        self.assertEqual([item.severity for item in issues], ["error", "warn", "incomplete"])
        self.assertEqual([item.key for item in issues], ["B", "A", "C"])


if __name__ == "__main__":
    unittest.main()

