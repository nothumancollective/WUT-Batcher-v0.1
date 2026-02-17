from __future__ import annotations

import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.constants import DEFAULT_RUNNER_MODE
from app.gui import MainWindow
from app.services import OrchestratorService

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class ProjectValidationAlignmentFuzzTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_project_ui_alignment_under_random_sequences(self) -> None:
        random.seed(20260217)
        service = OrchestratorService()
        window = MainWindow(service)
        window.current_project = None
        form = window.project_page.constraints_form

        keys = [
            "Length",
            "Throat.Profile",
            "GCurve.Type",
            "Morph.TargetShape",
            "Coverage.Angle",
            "GCurve.Dist",
            "GCurve.Width",
            "CircArc.TermAngle",
            "CircArc.Radius",
            "R-OSSE.R",
            "R-OSSE.r0",
        ]

        def random_value(key: str):
            if key == "Length":
                return random.choice([None, "180", "250", "300+0*p", "abc", ""])
            if key == "Throat.Profile":
                return random.choice([None, 1, 2, 3])
            if key == "GCurve.Type":
                return random.choice([None, 1, 2])
            if key == "Morph.TargetShape":
                return random.choice([None, 0, 1, 2])
            if key.startswith("R-OSSE."):
                return random.choice([None, 12, 20, 35, 48])
            return random.choice([None, 10, 30, 45, 80, 120])

        for _ in range(450):
            key = random.choice(keys)
            editor = form.editor_for_key(key)
            if editor is None or not hasattr(editor, "set_value"):
                continue
            editor.set_value(random_value(key))  # type: ignore[attr-defined]

            payload = window.project_page._raw_constraints_payload()
            window._on_project_draft_changed(payload)

            current = window.project_page._raw_constraints_payload()
            compat_state = service.evaluate_project_constraints(
                {
                    "fixed_params": dict(current.get("fixed_params", {}) or {}),
                    "limits": dict(current.get("limits", {}) or {}),
                    "param_states": [row for row in list(current.get("param_states", []) or []) if isinstance(row, dict)],
                    "runner_mode": DEFAULT_RUNNER_MODE,
                }
            )
            compat_rule_ids = {
                str(issue.get("rule_id", ""))
                for issue in list(compat_state.get("issues", []) or [])
                if isinstance(issue, dict)
            }
            ui_normative_rule_ids = {
                str(issue.rule_id)
                for issue in list(window.project_page._ui_issues)
                if str(getattr(issue, "source", "")).strip().lower() != "experiment"
            }

            self.assertTrue(ui_normative_rule_ids.issubset(compat_rule_ids))
            self.assertNotIn("project_param_not_visible", ui_normative_rule_ids)
            self.assertNotIn("batch_param_not_visible", ui_normative_rule_ids)

            length_defined = "Length" in dict(current.get("fixed_params", {}) or {})
            rosse_defined = "R-OSSE" in dict(current.get("fixed_params", {}) or {})
            osse_defined = "OSSE" in dict(current.get("fixed_params", {}) or {})
            if length_defined:
                self.assertNotIn("validity_length_required", compat_rule_ids)
                self.assertNotIn("validity_length_required", ui_normative_rule_ids)
            if "validity_length_required" in ui_normative_rule_ids:
                self.assertFalse(length_defined)
                self.assertFalse(rosse_defined)
                self.assertFalse(osse_defined)


if __name__ == "__main__":
    unittest.main()

