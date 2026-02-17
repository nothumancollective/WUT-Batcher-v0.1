from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE
from app.gui import BatchPage
from ui.form_builder import AccordionGroupBox

try:
    from PySide6.QtWidgets import QApplication, QLabel
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QLabel = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class BatchPageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _compat_state(
        self,
        *,
        selected_params: dict | None = None,
        sweeps: dict | None = None,
    ) -> dict:
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
        base = self._compat_state()
        page.apply_compatibility(base)
        throat_row = page.parameter_form._rows.get("Throat.Profile")
        if throat_row is None:
            self.skipTest("Throat.Profile not available.")
        if hasattr(throat_row.base_editor, "set_value"):
            throat_row.base_editor.set_value(2)  # type: ignore[attr-defined]
        payload = page._payload(include_name=False)
        state = self._compat_state(
            selected_params=dict(payload.get("selected_params", {}) or {}),
            sweeps=dict(payload.get("sweeps", {}) or {}),
        )
        page.apply_compatibility(state)

        row = page.parameter_form._rows.get("R-OSSE")
        if row is None:
            self.skipTest("R-OSSE not available.")
        self.assertFalse(row.container.isHidden())
        editor = row.base_editor
        self.assertTrue(hasattr(editor, "property_editors"))
        props = getattr(editor, "property_editors")
        self.assertIn("R-OSSE.R", props)
        self.assertIn("R-OSSE.r0", props)

        props["R-OSSE.R"].set_value(120.0)
        props["R-OSSE.r0"].set_value(17.0)
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

        if not hasattr(row.base_editor, "set_value"):
            self.skipTest("Throat.Profile editor does not expose set_value.")
        row.base_editor.set_value(1)  # type: ignore[attr-defined]
        payload = page._payload(include_name=False)
        state_a = self._compat_state(
            selected_params=dict(payload.get("selected_params", {}) or {}),
            sweeps=dict(payload.get("sweeps", {}) or {}),
        )
        page.apply_compatibility(state_a)

        row.base_editor.set_value(2)  # type: ignore[attr-defined]
        page.parameter_form._last_changed_key = "Throat.Profile"  # type: ignore[attr-defined]
        payload = page._payload(include_name=False)
        state_b = self._compat_state(
            selected_params=dict(payload.get("selected_params", {}) or {}),
            sweeps=dict(payload.get("sweeps", {}) or {}),
        )
        page.apply_compatibility(state_b)
        self.assertFalse(row.helper_label.isHidden())
        self.assertTrue(bool(row.helper_label.text().strip()))

        value_widget = row.base_editor.value_widget()  # type: ignore[attr-defined]
        segment = getattr(value_widget, "segment", None)
        if segment is None:
            self.skipTest("Throat.Profile does not use segmented input.")
        selected = segment.group.checkedButton()
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(str(selected.property("disclosureHint")), "true")

    def test_core_group_is_renamed_to_mesh(self) -> None:
        page = BatchPage()
        self.assertEqual(page.parameter_form.group_name_for_key("Mesh.Quadrants"), "Mesh")

    def test_project_fixed_controller_keys_are_hidden_in_batch_form(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.set_project_fixed_keys(["Throat.Profile", "Morph.TargetShape", "GCurve.Type", "Mesh.Enclosure"])
        page.apply_compatibility(state)

        throat = page.parameter_form._rows.get("Throat.Profile")
        morph = page.parameter_form._rows.get("Morph.TargetShape")
        gcurve = page.parameter_form._rows.get("GCurve.Type")
        enclosure = page.parameter_form._rows.get("Mesh.Enclosure")
        self.assertIsNotNone(throat)
        self.assertIsNotNone(morph)
        self.assertIsNotNone(gcurve)
        self.assertIsNotNone(enclosure)
        assert throat is not None and morph is not None and gcurve is not None and enclosure is not None
        self.assertTrue(throat.container.isHidden())
        self.assertTrue(morph.container.isHidden())
        self.assertTrue(gcurve.container.isHidden())
        self.assertTrue(enclosure.container.isHidden())

    def test_compat_ui_hidden_keys_are_applied_in_batch_form(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        state["compat_ui_state"] = {"hidden_keys": ["GCurve.Type"], "blocked_options": {}}
        page.apply_compatibility(state)
        row = page.parameter_form._rows.get("GCurve.Type")
        if row is None:
            self.skipTest("GCurve.Type not available.")
        self.assertTrue(row.container.isHidden())

    def test_labels_do_not_render_key_suffix(self) -> None:
        page = BatchPage()
        row = page.parameter_form._rows.get("Length")
        if row is None:
            self.skipTest("Length row not available.")
        if QLabel is None:
            self.skipTest("QLabel unavailable.")
        text_candidates = [label.text() for label in row.container.findChildren(QLabel)]
        self.assertTrue(any(str(text).strip() == "Length" for text in text_candidates))

    def test_summary_cards_and_right_column_use_thirds(self) -> None:
        page = BatchPage()
        page.resize(1500, 900)
        page.show()
        self.app.processEvents()
        widths = [page.summary_left_card.width(), page.summary_center_card.width(), page.summary_right_card.width()]
        self.assertTrue(all(width > 0 for width in widths))
        self.assertAlmostEqual(widths[0], widths[1], delta=3)
        self.assertAlmostEqual(widths[1], widths[2], delta=3)

        margins = page._root_layout.contentsMargins()
        available = int(page.width() - margins.left() - margins.right())
        expected_right = max((available - int(page._body_layout.spacing())) // 3, 1)
        self.assertAlmostEqual(page._right_panel.width(), expected_right, delta=5)

    def test_batch_name_input_uses_one_third_width(self) -> None:
        page = BatchPage()
        page.resize(1500, 900)
        page.show()
        self.app.processEvents()
        margins = page._root_layout.contentsMargins()
        available = int(page.width() - margins.left() - margins.right())
        expected = max(240, available // 3)
        self.assertAlmostEqual(page.batch_name.width(), expected, delta=5)

    def test_gcurve_subgroup_headers_hidden_for_no_gcurve(self) -> None:
        page = BatchPage()
        state = self._compat_state(selected_params={"GCurve.Type": None})
        page.apply_compatibility(state)
        headers = [
            label
            for label in page.parameter_form.findChildren(QLabel)
            if label.objectName() == "IssuesPanelGroupTitle"
            and str(label.text()).strip() in {"Superellipse", "Superformula"}
        ]
        self.assertTrue(headers, "Expected GCurve subgroup headers to exist.")
        for header in headers:
            self.assertTrue(header.isHidden())

    def test_sweep_button_locks_base_editor_when_active(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        key = None
        for candidate in list(state.get("sweepable_keys", []) or []):
            candidate_key = str(candidate)
            toggle = page.parameter_form.sweep_toggle_for_key(candidate_key)
            editor = page.parameter_form.editor_for_key(candidate_key)
            if toggle is not None and toggle.isVisible() and toggle.isEnabled() and editor is not None:
                key = candidate_key
                break
        if key is None:
            self.skipTest("No scalar sweep candidate available.")
        toggle = page.parameter_form.sweep_toggle_for_key(key)
        editor = page.parameter_form.editor_for_key(key)
        assert toggle is not None and editor is not None
        toggle.setChecked(True)
        self.assertFalse(editor.isEnabled())
        self.assertTrue(bool(toggle.property("sweepActive")))

    def test_incomplete_sweep_is_not_emitted_until_inputs_are_complete(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        key = None
        for candidate in list(state.get("sweepable_keys", []) or []):
            candidate_key = str(candidate)
            toggle = page.parameter_form.sweep_toggle_for_key(candidate_key)
            if toggle is not None and toggle.isVisible() and toggle.isEnabled():
                key = candidate_key
                break
        if key is None:
            self.skipTest("No sweepable candidate available.")
        toggle = page.parameter_form.sweep_toggle_for_key(key)
        inputs = page.parameter_form.sweep_inputs_for_key(key)
        assert toggle is not None and inputs is not None
        toggle.setChecked(True)
        inputs["start"].setText("")
        inputs["end"].setText("")
        payload = page._payload(include_name=False)
        sweeps = dict(payload.get("sweeps", {}) or {})
        self.assertNotIn(key, sweeps)
        inputs["start"].setText("10")
        inputs["end"].setText("20")
        inputs["steps"].setText("3")
        payload_ready = page._payload(include_name=False)
        sweeps_ready = dict(payload_ready.get("sweeps", {}) or {})
        self.assertIn(key, sweeps_ready)

    def test_sweep_toggle_survives_compatibility_refresh(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        key = None
        for candidate in list(state.get("sweepable_keys", []) or []):
            candidate_key = str(candidate)
            toggle = page.parameter_form.sweep_toggle_for_key(candidate_key)
            inputs = page.parameter_form.sweep_inputs_for_key(candidate_key)
            if toggle is not None and inputs is not None and toggle.isVisible() and toggle.isEnabled():
                key = candidate_key
                break
        if key is None:
            self.skipTest("No sweepable candidate available.")
        toggle = page.parameter_form.sweep_toggle_for_key(key)
        inputs = page.parameter_form.sweep_inputs_for_key(key)
        assert toggle is not None and inputs is not None
        toggle.setChecked(True)
        inputs["start"].setText("12")
        inputs["end"].setText("18")
        inputs["steps"].setText("4")
        payload = page._payload(include_name=False)
        refreshed = self._compat_state(
            selected_params=dict(payload.get("selected_params", {}) or {}),
            sweeps=dict(payload.get("sweeps", {}) or {}),
        )
        page.apply_compatibility(refreshed)
        toggle_after = page.parameter_form.sweep_toggle_for_key(key)
        inputs_after = page.parameter_form.sweep_inputs_for_key(key)
        assert toggle_after is not None and inputs_after is not None
        self.assertTrue(toggle_after.isChecked())
        self.assertEqual(inputs_after["start"].text(), "12")
        self.assertEqual(inputs_after["end"].text(), "18")

    def test_batch_ui_risks_colorize_fields_and_warn_summary(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        page.apply_ui_risks(
            [
                {
                    "field_key": "Length",
                    "severity": "warn",
                    "rule_id": "exp_range_safe",
                    "message": "Length outside safe range.",
                    "source": "experiment",
                }
            ]
        )
        editor = page.parameter_form.editor_for_key("Length")
        self.assertIsNotNone(editor)
        assert editor is not None
        self.assertEqual(str(editor.property("fieldState")), "warn")
        self.assertIn("Warnings present", page.action_status_pill.text())

    def test_hidden_field_value_is_cleared_after_visibility_change(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)

        target_key = None
        target_editor = None
        for candidate in list(state.get("visible_keys", []) or []):
            key = str(candidate)
            editor = page.parameter_form.editor_for_key(key)
            if editor is None:
                continue
            target_key = key
            target_editor = editor
            break
        if target_key is None or target_editor is None:
            self.skipTest("No scalar visible field available.")

        target_editor.setText("33.3")
        payload_before = page._payload(include_name=False)
        selected_before = dict(payload_before.get("selected_params", {}) or {})
        self.assertEqual(float(selected_before.get(target_key)), 33.3)

        reduced_state = dict(state)
        reduced_state["visible_keys"] = [key for key in list(state.get("visible_keys", []) or []) if str(key) != target_key]
        page.apply_compatibility(reduced_state)
        page.apply_compatibility(state)
        payload_after = page._payload(include_name=False)
        selected_after = dict(payload_after.get("selected_params", {}) or {})
        self.assertIsNone(selected_after.get(target_key))

    def test_blocked_batch_segment_option_emits_interaction_and_keeps_selection(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        state["compat_ui_state"] = {
            "blocked_options": {
                "Throat.Profile": {
                    "2": {
                        "cause_key": "Length",
                        "message": "Blocked for test.",
                        "hidden_keys": ["Term.s"],
                    }
                }
            }
        }
        page.apply_compatibility(state)

        row = page.parameter_form._rows.get("Throat.Profile")
        if row is None:
            self.skipTest("Throat.Profile not available.")
        value_widget = row.base_editor.value_widget()  # type: ignore[attr-defined]
        segment = getattr(value_widget, "segment", value_widget)

        blocked_button = None
        for button_id, value in dict(getattr(segment, "_values_by_id", {})).items():
            if value == 2:
                blocked_button = segment.group.button(int(button_id))
                break
        if blocked_button is None:
            self.skipTest("Blocked option button not available.")

        captured: list[tuple[str, str, str]] = []
        page.blocked_interaction.connect(
            lambda target_key, cause_key, message: captured.append((target_key, cause_key, message))
        )
        before = segment.value()
        blocked_button.click()
        after = segment.value()
        self.assertEqual(before, after)
        self.assertTrue(captured)
        self.assertEqual(captured[-1][0], "Throat.Profile")
        self.assertEqual(captured[-1][1], "Length")


if __name__ == "__main__":
    unittest.main()
