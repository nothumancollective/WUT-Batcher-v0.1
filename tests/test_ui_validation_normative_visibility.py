from __future__ import annotations

from app.ui_validation import UiValidationEngine


def test_normative_issues_skip_hidden_and_visibility_noise() -> None:
    engine = UiValidationEngine()
    validation_state = {
        "issues": [
            {
                "field_key": "GCurve.Type",
                "severity": "warn",
                "message": "Visible warning",
                "rule_id": "warn_visible",
            },
            {
                "field_key": "GCurve.Width",
                "severity": "fatal",
                "message": "Hidden fatal should be filtered",
                "rule_id": "fatal_hidden",
            },
            {
                "field_key": "GCurve.Dist",
                "severity": "fatal",
                "message": "Batch parameter 'GCurve.Dist' is not visible for current project constraints.",
                "rule_id": "batch_param_not_visible",
            },
        ]
    }
    issues = engine.evaluate_normative_issues(validation_state, visible_keys={"GCurve.Type"})
    assert [item.key for item in issues] == ["GCurve.Type"]
    assert [item.rule_id for item in issues] == ["warn_visible"]

