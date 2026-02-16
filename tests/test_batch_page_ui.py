from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE
from app.gui import BatchPage
from ui.form_builder import AccordionGroupBox, ObjectFieldEditor

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class BatchPageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _compat_state(self, *, selected_params: dict | None = None, sweeps: dict | None = None) -> dict:
        service = CompatibilityService()
        return service.evaluate_batch_definition(
            {
                "project_id": "P001",
                "fixed_params": {"Length": 200},
                "limits": {},
                "runner_mode": DEFAULT_RUNNER_MODE,
            },
            selected_params=dict(selected_params or {}),
            sweeps=dict(sweeps or {}),
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
        self.assertEqual(page.parameter_form.group_name_for_key("Throat.Profile"), "Throat Profile")

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

    def test_rosse_block_uses_object_editor_with_details(self) -> None:
        page = BatchPage()
        row = page.parameter_form._rows.get("R-OSSE")
        if row is None:
            self.skipTest("R-OSSE not available.")
        self.assertIsInstance(row.base_editor, ObjectFieldEditor)
        editor = row.base_editor
        assert isinstance(editor, ObjectFieldEditor)
        self.assertIn("R-OSSE.R", editor.property_editors)
        self.assertIn("R-OSSE.r0", editor.property_editors)

        editor.property_editors["R-OSSE.R"].set_value(120.0)
        editor.property_editors["R-OSSE.r0"].set_value(17.0)
        payload = page.parameter_form.selected_params_payload()
        self.assertIn("R-OSSE", payload)
        self.assertIsInstance(payload["R-OSSE"], dict)
        value = payload["R-OSSE"]
        assert isinstance(value, dict)
        self.assertEqual(float(value["R"]), 120.0)
        self.assertEqual(float(value["r0"]), 17.0)

    def test_disclosure_hint_marks_selected_segment_button(self) -> None:
        page = BatchPage()
        initial = self._compat_state()
        page.apply_compatibility(initial)
        row = page.parameter_form._rows.get("Throat.Profile")
        if row is None:
            self.skipTest("Throat.Profile not available.")

        applied = False
        for mode in (1, 2, 3):
            if hasattr(row.base_editor, "set_value"):
                row.base_editor.set_value(mode)  # type: ignore[attr-defined]
            payload = page._payload(include_name=False)
            next_state = self._compat_state(
                selected_params=dict(payload.get("selected_params", {}) or {}),
                sweeps=dict(payload.get("sweeps", {}) or {}),
            )
            page.apply_compatibility(next_state)
            if row.helper_label.isVisible():
                applied = True
                break
        if not applied:
            self.skipTest("No disclosure hint scenario produced by current compatibility rules.")

        value_widget = row.base_editor.value_widget()  # type: ignore[attr-defined]
        segment = getattr(value_widget, "segment", None)
        if segment is None:
            self.skipTest("Throat.Profile does not use segmented input.")
        selected = segment.group.checkedButton()
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(str(selected.property("disclosureHint")), "true")


if __name__ == "__main__":
    unittest.main()
