from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE
from app.gui import BatchPage
from ui.form_builder import AccordionGroupBox

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class BatchPageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _compat_state(self) -> dict:
        service = CompatibilityService()
        return service.evaluate_batch_definition(
            {
                "project_id": "P001",
                "fixed_params": {"Length": 200},
                "limits": {},
                "runner_mode": DEFAULT_RUNNER_MODE,
            },
            selected_params={},
            sweeps={},
            sweep_mode="single",
        )

    def test_sweep_toggle_disabled_when_field_not_sweepable(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)

        visible = [str(item) for item in list(state.get("visible_keys", []) or [])]
        sweepable = set(str(item) for item in list(state.get("sweepable_keys", []) or []))
        locked = set(str(item) for item in list(state.get("locked_keys", []) or []))
        candidate = next((key for key in visible if key not in sweepable and key not in locked), None)
        if candidate is None:
            self.skipTest("No non-sweepable candidate available in current ruleset.")
        toggle = page.parameter_form.sweep_toggle_for_key(candidate)
        self.assertIsNotNone(toggle)
        assert toggle is not None
        self.assertFalse(toggle.isEnabled())

    def test_sweep_details_show_and_payload_maps_values(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)

        key = None
        for candidate in list(state.get("sweepable_keys", []) or []):
            candidate_key = str(candidate)
            toggle = page.parameter_form.sweep_toggle_for_key(candidate_key)
            if toggle is not None and toggle.isEnabled():
                key = candidate_key
                break
        if key is None:
            self.skipTest("No sweepable candidate available in current ruleset.")

        editor = page.parameter_form.editor_for_key(key)
        toggle = page.parameter_form.sweep_toggle_for_key(key)
        panel = page.parameter_form.sweep_panel_for_key(key)
        inputs = page.parameter_form.sweep_inputs_for_key(key)
        self.assertIsNotNone(editor)
        self.assertIsNotNone(toggle)
        self.assertIsNotNone(panel)
        self.assertIsNotNone(inputs)
        assert editor is not None and toggle is not None and panel is not None and inputs is not None

        editor.setText("42.5")
        toggle.setChecked(True)
        inputs["start"].setText("10")
        inputs["end"].setText("20")
        inputs["steps"].setText("3")

        self.assertFalse(panel.isHidden())
        payload = page._payload(include_name=False)
        selected = dict(payload.get("selected_params", {}) or {})
        sweeps = dict(payload.get("sweeps", {}) or {})
        self.assertEqual(float(selected[key]), 42.5)
        self.assertIn(key, sweeps)
        self.assertEqual(float(sweeps[key]["start"]), 10.0)
        self.assertEqual(float(sweeps[key]["end"]), 20.0)
        self.assertEqual(int(sweeps[key]["steps"]), 3)

    def test_button_layout_fields_are_not_sweepable(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)

        toggle = page.parameter_form.sweep_toggle_for_key("Throat.Profile")
        if toggle is None:
            self.skipTest("Throat.Profile not available.")
        self.assertFalse(toggle.isVisible())

    def test_only_one_accordion_group_is_expanded(self) -> None:
        page = BatchPage()
        boxes = [box for box in page.parameter_form.findChildren(AccordionGroupBox) if box.isVisible()]
        if len(boxes) < 2:
            self.skipTest("Not enough accordion groups available.")
        expanded_initial = [box for box in boxes if not box.is_collapsed()]
        self.assertEqual(len(expanded_initial), 1)

        second = boxes[1]
        second.set_collapsed(False)
        expanded_after = [box for box in boxes if not box.is_collapsed()]
        self.assertEqual(len(expanded_after), 1)
        self.assertEqual(expanded_after[0].title(), second.title())


if __name__ == "__main__":
    unittest.main()
