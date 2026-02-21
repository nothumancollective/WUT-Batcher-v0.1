from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE
from app.gui import BatchPage
from ui.form_builder import AccordionGroupBox, NullableSliderNumericInput
from ui.form_metrics import FORM_METRICS
from ui.theme import build_stylesheet

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

        self.assertIsNotNone(panel)
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
        if row.container.isHidden():
            advanced_btn = page.parameter_form._group_advanced_buttons.get(str(row.group_name))  # type: ignore[attr-defined]
            if advanced_btn is not None and not advanced_btn.isHidden():
                advanced_btn.click()
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

    def test_rosse_property_rows_are_sweepable_in_rosse_mode(self) -> None:
        page = BatchPage()
        state = self._compat_state(selected_params={"Throat.Profile": 2})
        page.parameter_form.set_selected_params({"Throat.Profile": 2})
        page.apply_compatibility(state)
        self.assertIn("R-OSSE", set(str(item) for item in list(state.get("sweepable_keys", []) or [])))

        for key in ("R-OSSE.R", "R-OSSE.r0"):
            row = page.parameter_form._rows.get(key)
            if row is None:
                self.skipTest(f"{key} row missing.")
            self.assertFalse(row.container.isHidden())
            self.assertTrue(row.sweep_capable)
            self.assertTrue(row.sweep_toggle.isEnabled())
            row.sweep_toggle.setChecked(True)
            row.start_edit.setText("10")
            row.end_edit.setText("12")
            row.steps_edit.setText("3")

        sweeps = page.parameter_form.sweeps_payload()
        self.assertIn("R-OSSE.R", sweeps)
        self.assertIn("R-OSSE.r0", sweeps)

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
        # For controller groups, helper text is suppressed; the disclosure hint is carried on segment buttons.
        self.assertTrue(row.helper_label.isHidden())

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

    def test_command_header_layout_and_right_column_use_thirds(self) -> None:
        page = BatchPage()
        page.resize(1500, 900)
        page.show()
        self.app.processEvents()
        self.assertTrue(hasattr(page, "command_header"))
        self.assertFalse(hasattr(page, "summary_left_card"))
        self.assertEqual(page.command_header.objectName(), "CommandHeaderWidget")

        margins = page._root_layout.contentsMargins()
        available = int(page.width() - margins.left() - margins.right())
        expected_right = max((available - int(page._body_layout.spacing())) // 3, 1)
        self.assertAlmostEqual(page._right_panel.width(), expected_right, delta=5)

    def test_batch_name_input_uses_responsive_soft_cap(self) -> None:
        page = BatchPage()
        page.resize(1500, 900)
        page.show()
        self.app.processEvents()
        margins = page._root_layout.contentsMargins()
        available = int(page.width() - margins.left() - margins.right())
        expected_max = max(320, min(int(available * 0.45), 720))
        self.assertEqual(int(page.batch_name.maximumWidth()), expected_max)

    def test_controller_keys_are_not_sweepable_and_mesh_keys_are_not(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        for key in ("Throat.Profile", "GCurve.Type", "Morph.TargetShape"):
            row = page.parameter_form._rows.get(key)
            self.assertIsNotNone(row, f"Missing controller row: {key}")
            assert row is not None
            self.assertFalse(row.sweep_capable)
            self.assertTrue(row.sweep_toggle.isHidden())
        mesh_row = page.parameter_form._rows.get("Mesh.AngularSegments")
        self.assertIsNotNone(mesh_row)
        assert mesh_row is not None
        self.assertFalse(mesh_row.sweep_capable)
        self.assertFalse(mesh_row.sweep_toggle.isVisible())

    def test_non_basic_group_numeric_field_can_be_swept_when_visible(self) -> None:
        page = BatchPage()
        # Select profile so throat profile sub-parameters become visible.
        selected = {"Throat.Profile": 1}
        state = self._compat_state(selected_params=selected)
        page.parameter_form.set_selected_params(selected)
        page.apply_compatibility(state)
        candidate = "Term.s"
        row = page.parameter_form._rows.get(candidate)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertFalse(row.container.isHidden())
        self.assertTrue(row.sweep_capable)
        self.assertFalse(row.sweep_toggle.isHidden())
        self.assertTrue(row.sweep_toggle.isEnabled())

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
        # Compact batch layout omits GCurve subgroup titles; mode chips provide the context instead.
        self.assertFalse(headers)

    def test_basics_and_gcurve_share_same_form_grid_spec(self) -> None:
        page = BatchPage()
        basics_spec = page.parameter_form._grid_spec_for_group("Basics")  # type: ignore[attr-defined]
        gcurve_spec = page.parameter_form._grid_spec_for_group("GCurve")  # type: ignore[attr-defined]
        self.assertEqual(basics_spec, gcurve_spec)

    def test_circular_arc_termangle_and_radius_share_row_alignment(self) -> None:
        page = BatchPage()
        state = self._compat_state(selected_params={"Throat.Profile": 3})
        page.parameter_form.set_selected_params({"Throat.Profile": 3})
        page.apply_compatibility(state)
        page.resize(1500, 900)
        page.show()
        self.app.processEvents()

        throat_box = page.parameter_form._group_boxes.get("Throat Profile")  # type: ignore[attr-defined]
        if throat_box is None:
            self.skipTest("Throat Profile group missing.")
        throat_box.set_collapsed(False)
        self.app.processEvents()

        term_row = page.parameter_form._rows.get("CircArc.TermAngle")
        radius_row = page.parameter_form._rows.get("CircArc.Radius")
        if term_row is None or radius_row is None:
            self.skipTest("Circular Arc rows are missing.")
        self.assertFalse(term_row.container.isHidden())
        self.assertFalse(radius_row.container.isHidden())

        term_pos = term_row.container.mapToGlobal(term_row.container.rect().topLeft())
        radius_pos = radius_row.container.mapToGlobal(radius_row.container.rect().topLeft())
        self.assertLessEqual(abs(int(term_pos.y()) - int(radius_pos.y())), 6)
        self.assertLess(int(term_pos.x()), int(radius_pos.x()))

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

    def test_apply_policy_defaults_merges_enclosure_subdefaults(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        row = page.parameter_form._rows.get("Mesh.Enclosure")
        if row is None or row.container.isHidden():
            self.skipTest("Mesh.Enclosure row not available.")
        page.parameter_form.set_selected_params({"Mesh.Enclosure": {}})
        page.apply_policy_defaults({"Mesh.Enclosure": {"Depth": 180.0, "EdgeType": 1}})
        payload = page.parameter_form.selected_params_payload()
        enclosure = dict(payload.get("Mesh.Enclosure", {}) or {})
        self.assertEqual(float(enclosure.get("Depth", 0.0)), 180.0)
        self.assertEqual(int(enclosure.get("EdgeType", 0)), 1)

    def test_sweep_remains_enabled_under_warning_without_warn_tint(self) -> None:
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
        assert toggle is not None
        page.apply_ui_risks(
            [
                {
                    "field_key": key,
                    "severity": "warn",
                    "rule_id": "warn_test",
                    "message": "Warning for sweep test.",
                    "source": "experiment",
                }
            ]
        )
        self.assertTrue(toggle.isEnabled())
        toggle.setChecked(True)
        self.assertEqual(str(toggle.property("riskLevel") or ""), "")

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
        self.assertEqual(str(page.summary_issue_hint.property("severity")), "warn")
        self.assertIn("Warnings: 1", page.summary_issue_hint.text())
        self.assertIn("Length outside safe range.", str(page.summary_issue_hint.toolTip() or ""))

    def test_warning_summary_sorts_messages_and_sets_hover_tooltip(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        page.apply_ui_risks(
            [
                {
                    "field_key": "Length",
                    "severity": "warn",
                    "rule_id": "warn_b",
                    "message": "Zulu warning",
                    "source": "experiment",
                },
                {
                    "field_key": "Length",
                    "severity": "warn",
                    "rule_id": "warn_a",
                    "message": "Alpha warning",
                    "source": "experiment",
                },
            ]
        )
        text = str(page.summary_issue_hint.text())
        self.assertTrue(text.startswith("Warnings:"))
        tooltip = str(page.summary_issue_hint.toolTip() or "")
        self.assertIn("Alpha warning", tooltip)
        self.assertIn("Zulu warning", tooltip)
        self.assertLess(tooltip.index("Alpha warning"), tooltip.index("Zulu warning"))

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

    def test_field_reset_restores_unset_and_ghost_default(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        page.set_policy_default_suggestions({"Mesh.AngularSegments": 64})

        row = page.parameter_form._rows.get("Mesh.AngularSegments")
        if row is None:
            self.skipTest("Mesh.AngularSegments not available.")
        editor = row.base_editor
        value_widget = page.parameter_form.value_widget_for_key("Mesh.AngularSegments")
        self.assertIsNotNone(value_widget)
        assert value_widget is not None
        self.assertEqual(str(value_widget.spin.lineEdit().placeholderText()), "64")

        payload_before = page.parameter_form.selected_params_payload()
        self.assertIsNone(payload_before.get("Mesh.AngularSegments"))

        editor.set_value(68)  # type: ignore[attr-defined]
        payload_set = page.parameter_form.selected_params_payload()
        self.assertEqual(int(payload_set.get("Mesh.AngularSegments", 0)), 68)
        self.assertFalse(editor._reset_button.isHidden())  # type: ignore[attr-defined]
        self.assertTrue(editor._reset_button.isEnabled())  # type: ignore[attr-defined]

        editor._reset_button.click()  # type: ignore[attr-defined]
        payload_reset = page.parameter_form.selected_params_payload()
        self.assertIsNone(payload_reset.get("Mesh.AngularSegments"))
        self.assertEqual(str(value_widget.spin.lineEdit().placeholderText()), "64")
        page.apply_ui_risks([])
        self.assertEqual(str(value_widget.spin.lineEdit().property("fieldState")), "neutral")

    def test_reset_state_toggle_does_not_change_editor_width(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        row = page.parameter_form._rows.get("Length")
        if row is None:
            self.skipTest("Length not available.")
        editor = row.base_editor
        if not hasattr(editor, "set_value") or not hasattr(editor, "set_is_set"):
            self.skipTest("Length editor does not support override state toggles.")
        page.show()
        self.app.processEvents()
        width_unset = int(editor.width())
        hint_unset = int(editor.sizeHint().width())
        editor.set_value(320.0)  # type: ignore[attr-defined]
        self.app.processEvents()
        width_set = int(editor.width())
        hint_set = int(editor.sizeHint().width())
        editor.set_is_set(False)  # type: ignore[attr-defined]
        self.app.processEvents()
        width_reset = int(editor.width())
        hint_reset = int(editor.sizeHint().width())
        self.assertEqual(width_unset, width_set)
        self.assertEqual(width_set, width_reset)
        self.assertEqual(hint_unset, hint_set)
        self.assertEqual(hint_set, hint_reset)

    def test_sweep_buttons_align_in_basics_group(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        page.resize(1600, 900)
        page.show()
        self.app.processEvents()
        rows = [
            row
            for row in page.parameter_form._rows.values()
            if str(row.group_name) == "Basics" and not row.container.isHidden() and row.sweep_toggle.isVisible()
        ]
        if len(rows) < 2:
            self.skipTest("Not enough sweep-enabled rows in Basics.")
        xs = [int(row.sweep_toggle.geometry().x()) for row in rows]
        self.assertLessEqual(max(xs) - min(xs), 1)

    def test_rosse_angle_fields_use_single_row_slider_height(self) -> None:
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
        if row.container.isHidden():
            advanced_btn = page.parameter_form._group_advanced_buttons.get(str(row.group_name))  # type: ignore[attr-defined]
            if advanced_btn is not None and not advanced_btn.isHidden():
                advanced_btn.click()
        self.assertFalse(row.container.isHidden())
        props = getattr(row.base_editor, "property_editors", {})
        for key in ("R-OSSE.a0", "R-OSSE.a"):
            editor = props.get(key)
            if editor is None:
                self.skipTest(f"{key} not available.")
            value_widget = editor.value_widget()
            self.assertIsInstance(value_widget, NullableSliderNumericInput)
            self.assertLessEqual(int(value_widget.sizeHint().height()), int(FORM_METRICS.control_height) + 4)

    def test_slider_clear_resets_slider_position(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        value_widget = page.parameter_form.value_widget_for_key("Morph.FixedPart")
        if value_widget is None or not isinstance(value_widget, NullableSliderNumericInput):
            self.skipTest("Morph.FixedPart slider widget not available.")
        events: list[str] = []
        value_widget.changed.connect(lambda: events.append("changed"))
        value_widget.set_value(0.66)
        self.assertGreater(int(value_widget.slider.value()), 0)
        events.clear()
        value_widget.clear()
        self.assertEqual(int(value_widget.slider.value()), 0)
        self.assertFalse(value_widget.is_set())
        self.assertTrue(events)

    def test_sweep_active_selector_exists_in_stylesheet(self) -> None:
        css = build_stylesheet()
        self.assertIn('QPushButton#SweepButton[sweepActive="true"]', css)

    def test_warning_stylesheet_covers_spinboxes_without_sweep_warn_tint(self) -> None:
        css = build_stylesheet()
        self.assertIn('QSpinBox[fieldState="warn"]', css)
        self.assertIn('QSpinBox[riskLevel="warn"]', css)
        self.assertNotIn('QPushButton#SweepButton[sweepActive="true"][riskLevel="warn"]', css)

    def test_block_reset_clears_all_overrides_in_group(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        row_length = page.parameter_form._rows.get("Length")
        row_coverage = page.parameter_form._rows.get("Coverage.Angle")
        if row_length is None or row_coverage is None:
            self.skipTest("Required Basics fields are missing.")
        row_length.base_editor.set_value(320.0)  # type: ignore[attr-defined]
        row_coverage.base_editor.set_value(40.0)  # type: ignore[attr-defined]

        reset_btn = page.parameter_form.block_reset_button_for_group("Basics")
        self.assertIsNotNone(reset_btn)
        assert reset_btn is not None
        self.assertTrue(reset_btn.isEnabled())
        reset_btn.click()

        payload = page.parameter_form.selected_params_payload()
        self.assertIsNone(payload.get("Length"))
        self.assertIsNone(payload.get("Coverage.Angle"))
        self.assertFalse(reset_btn.isEnabled())

    def test_block_reset_button_visible_only_when_collapsed_and_overridden(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        row = page.parameter_form._rows.get("Length")
        if row is None:
            self.skipTest("Length row not available.")
        row.base_editor.set_value(320.0)  # type: ignore[attr-defined]
        page.parameter_form._update_group_reset_buttons()  # type: ignore[attr-defined]

        reset_btn = page.parameter_form.block_reset_button_for_group("Basics")
        self.assertIsNotNone(reset_btn)
        assert reset_btn is not None
        basics_box = page.parameter_form._group_boxes.get("Basics")  # type: ignore[attr-defined]
        self.assertIsNotNone(basics_box)
        assert basics_box is not None

        # Expanded block with overrides: reset action stays hidden in header.
        basics_box.set_collapsed(False)
        self.app.processEvents()
        self.assertTrue(reset_btn.isEnabled())
        self.assertTrue(reset_btn.isHidden())

        # Collapsed + overrides: reset action becomes visible.
        basics_box.set_collapsed(True)
        self.app.processEvents()
        self.assertFalse(reset_btn.isHidden())

        reset_btn.click()
        self.app.processEvents()
        self.assertTrue(reset_btn.isHidden())

    def test_block_reset_button_starts_hidden_without_overrides(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        reset_btn = page.parameter_form.block_reset_button_for_group("Basics")
        self.assertIsNotNone(reset_btn)
        assert reset_btn is not None
        self.assertFalse(reset_btn.isEnabled())
        self.assertTrue(reset_btn.isHidden())

    def test_mesh_angular_segments_step_and_multiple_validation(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        value_widget = page.parameter_form.value_widget_for_key("Mesh.AngularSegments")
        if value_widget is None:
            self.skipTest("Mesh.AngularSegments not available.")

        self.assertEqual(int(value_widget.spin.singleStep()), 4)
        value_widget.set_value(66)
        self.assertFalse(value_widget.is_set())
        self.assertIn("multiple of 4", str(value_widget.spin.lineEdit().toolTip()).lower())
        payload_invalid = page.parameter_form.selected_params_payload()
        self.assertIsNone(payload_invalid.get("Mesh.AngularSegments"))

        value_widget.set_value(68)
        self.assertTrue(value_widget.is_set())
        payload_valid = page.parameter_form.selected_params_payload()
        self.assertEqual(int(payload_valid.get("Mesh.AngularSegments", 0)), 68)

    def test_vector_and_list_editors_serialize_and_empty_is_unset(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)

        page.parameter_form.set_selected_params({"Mesh.InterfaceOffset": [1.0, 2.0, 3.0]})
        payload = page.parameter_form.selected_params_payload()
        values = list(payload.get("Mesh.InterfaceOffset") or [])
        self.assertEqual([float(item) for item in values], [1.0, 2.0, 3.0])

        row = page.parameter_form._rows.get("Mesh.InterfaceOffset")
        self.assertIsNotNone(row)
        assert row is not None
        row.base_editor.set_is_set(False)  # type: ignore[attr-defined]
        payload_empty = page.parameter_form.selected_params_payload()
        self.assertIsNone(payload_empty.get("Mesh.InterfaceOffset"))

        enclosure = page.parameter_form._rows.get("Mesh.Enclosure")
        if enclosure is None:
            self.skipTest("Mesh.Enclosure not available.")
        page.parameter_form.set_selected_params({"Mesh.Enclosure": {"Depth": 180.0, "Spacing": [4.0, 5.0, 6.0, 7.0]}})
        payload_enclosure = page.parameter_form.selected_params_payload()
        enclosure_value = dict(payload_enclosure.get("Mesh.Enclosure", {}) or {})
        spacing = list(enclosure_value.get("Spacing") or [])
        self.assertEqual([float(item) for item in spacing], [4.0, 5.0, 6.0, 7.0])

    def test_advanced_toggle_hides_advanced_rows_by_default(self) -> None:
        page = BatchPage()
        state = self._compat_state()
        page.apply_compatibility(state)
        target_key = "Mesh.InterfaceOffset"
        row = page.parameter_form._rows.get(target_key)
        if row is None:
            self.skipTest(f"{target_key} not available.")

        button = getattr(page.parameter_form, "_mesh_advanced_button", None)
        self.assertIsNotNone(button)
        assert button is not None
        self.assertEqual(str(button.text()).strip().lower(), "advanced")
        self.assertTrue(row.container.isHidden())
        self.assertEqual(str(row.container.property("meshAdvancedDetached") or "false").lower(), "true")

    def test_batch_form_has_no_horizontal_overflow_at_1920x1080(self) -> None:
        page = BatchPage()
        page.resize(1920, 1080)
        page.show()
        self.app.processEvents()
        hbar = page.parameter_form.scroll.horizontalScrollBar()
        self.assertEqual(int(hbar.maximum()), 0)

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
