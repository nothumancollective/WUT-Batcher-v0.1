from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE
from app.gui import ProjectPage

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QGroupBox, QLabel, QPushButton, QToolButton, QSplitter
except ImportError:  # pragma: no cover
    Qt = None  # type: ignore[assignment]
    QApplication = None  # type: ignore[assignment]
    QFrame = None  # type: ignore[assignment]
    QGridLayout = None  # type: ignore[assignment]
    QGroupBox = None  # type: ignore[assignment]
    QLabel = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]
    QToolButton = None  # type: ignore[assignment]
    QSplitter = None  # type: ignore[assignment]

from ui.form_builder import (
    NullableBoolInput,
    NullableNumericInput,
    ParameterForm,
    ResponsiveCompactGrid,
    SegmentedEnumInput,
)
from ui.form_schema import build_project_form_schema


@unittest.skipIf(QApplication is None, "PySide6 is required")
class ProjectFormUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.form = ParameterForm(build_project_form_schema())

    def test_widget_mapping_float_to_nullable_numeric_with_two_decimals(self) -> None:
        widget = self.form.value_widget_for_key("Throat.Diameter")
        self.assertIsNotNone(widget)
        self.assertIsInstance(widget, NullableNumericInput)
        assert isinstance(widget, NullableNumericInput)
        self.assertEqual(widget.decimals(), 2)

    def test_visibility_switching_uses_compatibility_actions(self) -> None:
        service = CompatibilityService()

        state_osse = service.evaluate_project_constraints(
            {
                "fixed_params": {"Length": 120, "Throat.Profile": 1},
                "limits": {},
                "runner_mode": DEFAULT_RUNNER_MODE,
            }
        )
        self.form.apply_compatibility(state_osse)

        term_editor = self.form.editor_for_key("Term.s")
        circarc_editor = self.form.editor_for_key("CircArc.TermAngle")
        self.assertIsNotNone(term_editor)
        self.assertIsNotNone(circarc_editor)
        assert term_editor is not None and circarc_editor is not None
        self.assertFalse(term_editor.isHidden())
        self.assertTrue(circarc_editor.isHidden())

        profile_editor = self.form.editor_for_key("Throat.Profile")
        self.assertIsNotNone(profile_editor)
        assert profile_editor is not None
        profile_editor.set_is_set(True)  # type: ignore[attr-defined]
        profile_editor.set_value(3)  # type: ignore[attr-defined]

        state_circarc = service.evaluate_project_constraints(
            {
                "fixed_params": {"Length": 120, "Throat.Profile": 3},
                "limits": {},
                "runner_mode": DEFAULT_RUNNER_MODE,
            }
        )
        self.form.apply_compatibility(state_circarc)

        self.assertTrue(term_editor.isHidden())
        self.assertFalse(circarc_editor.isHidden())

    def test_unset_semantics_are_serialized_as_param_states(self) -> None:
        diameter_editor = self.form.editor_for_key("Throat.Diameter")
        self.assertIsNotNone(diameter_editor)
        assert diameter_editor is not None

        diameter_editor.set_value(0.0)  # type: ignore[attr-defined]
        payload_set = self.form.payload()
        set_state = next(
            item for item in payload_set["param_states"] if item.get("param_name") == "Throat.Diameter"
        )
        self.assertEqual(set_state["is_set"], 1)
        self.assertEqual(set_state["value"], 0.0)

        diameter_editor.set_is_set(False)  # type: ignore[attr-defined]
        payload_unset = self.form.payload()
        unset_state = next(
            item for item in payload_unset["param_states"] if item.get("param_name") == "Throat.Diameter"
        )
        self.assertEqual(unset_state["is_set"], 0)
        self.assertIsNone(unset_state["value"])

    def test_project_page_has_only_create_button_and_no_compat_panel(self) -> None:
        page = ProjectPage()
        labels = [button.text() for button in page.findChildren(QPushButton)]
        self.assertIn("Create Project", labels)
        self.assertNotIn("Back to Dashboard", labels)
        self.assertNotIn("Show details", labels)
        self.assertFalse(
            any("Project Compatibility" == str(box.title()) for box in page.findChildren(QGroupBox))
        )
        captions = [label.text().strip() for label in page.findChildren(QLabel)]
        self.assertNotIn("Project Name", captions)
        self.assertFalse(hasattr(page, "summary_counts"))

    def test_project_page_hover_tooltip_is_clean_and_english(self) -> None:
        page = ProjectPage()
        editor = page.constraints_form.editor_for_key("Length")
        self.assertIsNotNone(editor)
        assert editor is not None
        editor.set_is_set(True)  # type: ignore[attr-defined]
        editor.set_value(1200.0)  # type: ignore[attr-defined]
        page.constraints_form._on_any_field_changed()  # type: ignore[attr-defined]

        page.apply_ui_risks(
            [
                {
                    "field_key": "Length",
                    "severity": "warn",
                    "message": "Length is outside the safe range [120, 900].",
                    "suggestion": "Recommended range: [200, 700].",
                    "source": "experiment",
                }
            ]
        )
        value_widget = page.constraints_form.value_widget_for_key("Length")
        self.assertIsNotNone(value_widget)
        assert value_widget is not None
        line_edit = getattr(value_widget, "edit", None)
        self.assertIsNotNone(line_edit)
        tooltip = str(line_edit.toolTip())
        self.assertIn("Length is outside the safe range [120.00, 900.00].", tooltip)
        self.assertIn("Recommended range: [200.00, 700.00].", tooltip)
        self.assertNotIn("Experiment", tooltip)

    def test_project_action_state_disables_create_on_fatal(self) -> None:
        page = ProjectPage()
        editor = page.constraints_form.editor_for_key("Length")
        self.assertIsNotNone(editor)
        assert editor is not None
        editor.set_is_set(True)  # type: ignore[attr-defined]
        editor.set_value(1200.0)  # type: ignore[attr-defined]
        page.constraints_form._on_any_field_changed()  # type: ignore[attr-defined]
        page.apply_ui_risks(
            [
                {
                    "field_key": "Length",
                    "severity": "fatal",
                    "message": "Length exceeds hard limit.",
                    "source": "normative",
                }
            ]
        )
        self.assertFalse(page.create_btn.isEnabled())
        self.assertFalse(page.view_issues_btn.isHidden())

    def test_required_missing_is_presented_as_incomplete_not_error(self) -> None:
        page = ProjectPage()
        page.apply_ui_risks(
            [
                {
                    "field_key": "Length",
                    "severity": "fatal",
                    "rule_id": "validity_length_required",
                    "message": "Length is required.",
                    "source": "normative",
                }
            ]
        )
        self.assertIn("Complete required fields", page.action_status_pill.text())
        self.assertEqual(str(page.action_status_pill.property("severity")), "neutral")
        self.assertFalse(page.create_btn.isEnabled())
        self.assertFalse(page.view_issues_btn.isHidden())

    def test_view_issues_panel_lists_all_and_orders_by_severity(self) -> None:
        page = ProjectPage()
        length_editor = page.constraints_form.editor_for_key("Length")
        throat_editor = page.constraints_form.editor_for_key("Throat.Diameter")
        self.assertIsNotNone(length_editor)
        self.assertIsNotNone(throat_editor)
        assert length_editor is not None and throat_editor is not None
        length_editor.set_is_set(True)  # type: ignore[attr-defined]
        length_editor.set_value(1200.0)  # type: ignore[attr-defined]
        throat_editor.set_is_set(True)  # type: ignore[attr-defined]
        throat_editor.set_value(0.1)  # type: ignore[attr-defined]
        page.constraints_form._on_any_field_changed()  # type: ignore[attr-defined]
        page.apply_ui_risks(
            [
                {
                    "field_key": "Throat.Diameter",
                    "severity": "warn",
                    "rule_id": "warn_low_diameter",
                    "message": "Diameter is near lower threshold.",
                },
                {
                    "field_key": "Length",
                    "severity": "fatal",
                    "rule_id": "fatal_hard_limit",
                    "message": "Length exceeds hard limit.",
                },
            ]
        )
        page._toggle_issues_panel()  # type: ignore[attr-defined]
        self.assertFalse(page.issues_host.isHidden())
        self.assertGreaterEqual(len(page._ui_issues), 2)  # type: ignore[attr-defined]
        self.assertEqual(page._ui_issues[0].severity, "error")  # type: ignore[attr-defined]
        self.assertEqual(page._ui_issues[0].key, "Length")  # type: ignore[attr-defined]

    def test_numeric_input_normalizes_decimal_comma_to_dot(self) -> None:
        editor = self.form.editor_for_key("Throat.Diameter")
        self.assertIsNotNone(editor)
        assert editor is not None
        value_widget = self.form.value_widget_for_key("Throat.Diameter")
        self.assertIsNotNone(value_widget)
        assert value_widget is not None
        line_edit = getattr(value_widget, "edit", None)
        self.assertIsNotNone(line_edit)
        line_edit.setText("123,45")
        self.assertEqual(line_edit.text(), "123.45")

    def test_form_layout_has_two_columns_geometry_and_mesh(self) -> None:
        self.assertTrue(hasattr(self.form, "geometry_scroll"))
        self.assertTrue(hasattr(self.form, "mesh_scroll"))
        splitters = self.form.findChildren(QSplitter)
        self.assertEqual(splitters, [])

    def test_geometry_order_matches_spec(self) -> None:
        section_layout = self.form.geometry_section.content_layout
        titles = [
            section_layout.itemAt(index).widget().title()
            for index in range(section_layout.count())
            if section_layout.itemAt(index).widget() is not None
            and isinstance(section_layout.itemAt(index).widget(), QGroupBox)
        ]
        self.assertEqual(titles, ["Basics", "Throat Profile", "Morph", "GCurve"])

    def test_mesh_order_matches_spec(self) -> None:
        section_layout = self.form.mesh_section.content_layout
        titles = [
            section_layout.itemAt(index).widget().title()
            for index in range(section_layout.count())
            if section_layout.itemAt(index).widget() is not None
            and isinstance(section_layout.itemAt(index).widget(), QGroupBox)
        ]
        self.assertEqual(titles, ["Core", "Enclosure"])

    def test_accordion_collapses_other_blocks_and_keeps_values(self) -> None:
        length_editor = self.form.editor_for_key("Length")
        self.assertIsNotNone(length_editor)
        assert length_editor is not None
        length_editor.set_is_set(True)  # type: ignore[attr-defined]
        length_editor.set_value(450.0)  # type: ignore[attr-defined]
        self.form._on_any_field_changed()  # type: ignore[attr-defined]

        basics_box = self.form._field_group_boxes.get("Length")  # type: ignore[attr-defined]
        throat_box = self.form._field_group_boxes.get("Throat.Profile")  # type: ignore[attr-defined]
        self.assertIsNotNone(basics_box)
        self.assertIsNotNone(throat_box)
        assert basics_box is not None
        assert throat_box is not None

        basics_box.set_collapsed(False)
        throat_box.set_collapsed(False)
        self.assertTrue(basics_box.is_collapsed())
        self.assertFalse(throat_box.is_collapsed())

        payload = self.form.payload()
        state = next(item for item in payload["param_states"] if item.get("param_name") == "Length")
        self.assertEqual(state["is_set"], 1)
        self.assertEqual(float(state["value"]), 450.0)

    def test_group_box_warn_state_when_child_has_warning(self) -> None:
        length_editor = self.form.editor_for_key("Length")
        self.assertIsNotNone(length_editor)
        assert length_editor is not None
        length_editor.set_is_set(True)  # type: ignore[attr-defined]
        length_editor.set_value(1200.0)  # type: ignore[attr-defined]
        self.form._on_any_field_changed()  # type: ignore[attr-defined]

        self.form.apply_ui_risks(
            [
                {
                    "field_key": "Length",
                    "severity": "warn",
                    "message": "Length is outside the safe range [120.00, 900.00].",
                    "source": "experiment",
                }
            ]
        )
        box = self.form._field_group_boxes.get("Length")  # type: ignore[attr-defined]
        self.assertIsNotNone(box)
        assert box is not None
        self.assertEqual(box.property("blockState"), "warn")

    def test_group_badge_fatal_dominates_warn(self) -> None:
        length_editor = self.form.editor_for_key("Length")
        throat_editor = self.form.editor_for_key("Throat.Diameter")
        self.assertIsNotNone(length_editor)
        self.assertIsNotNone(throat_editor)
        assert length_editor is not None
        assert throat_editor is not None
        length_editor.set_is_set(True)  # type: ignore[attr-defined]
        length_editor.set_value(1400.0)  # type: ignore[attr-defined]
        throat_editor.set_is_set(True)  # type: ignore[attr-defined]
        throat_editor.set_value(20.0)  # type: ignore[attr-defined]
        self.form._on_any_field_changed()  # type: ignore[attr-defined]

        self.form.apply_ui_risks(
            [
                {"field_key": "Length", "severity": "warn", "message": "Length warning."},
                {"field_key": "Throat.Diameter", "severity": "fatal", "message": "Diameter fatal."},
            ]
        )
        box = self.form._field_group_boxes.get("Length")  # type: ignore[attr-defined]
        self.assertIsNotNone(box)
        assert box is not None
        header = box.header_row()  # type: ignore[attr-defined]
        badges = [label for label in header.findChildren(QLabel) if label.objectName() == "AccordionStatusBadge"]
        self.assertTrue(badges)
        self.assertEqual(badges[0].property("severity"), "fatal")
        self.assertIn("x", badges[0].text().lower())

    def test_collapsed_header_chips_show_plus_n(self) -> None:
        box = self.form._field_group_boxes.get("Length")  # type: ignore[attr-defined]
        self.assertIsNotNone(box)
        assert box is not None
        box.set_summary_chips(["one", "two", "three", "four", "five"])  # type: ignore[attr-defined]
        box.set_collapsed(True)
        header = box.header_row()  # type: ignore[attr-defined]
        chips = [label.text() for label in header.findChildren(QLabel) if label.objectName() == "AccordionChip"]
        self.assertIn("+3", chips)

    def test_source_is_removed_and_rosse_not_duplicated(self) -> None:
        self.assertIsNone(self.form.editor_for_key("Source.Shape"))
        self.assertIsNone(self.form.editor_for_key("Source.Radius"))
        self.assertIsNone(self.form.editor_for_key("OSSE"))
        rosse_keys = [field.key for field in self.form.schema.fields if field.key == "R-OSSE"]
        self.assertEqual(len(rosse_keys), 1)

    def test_segment_reclick_clears_selection(self) -> None:
        profile_editor = self.form.editor_for_key("Throat.Profile")
        self.assertIsNotNone(profile_editor)
        assert profile_editor is not None
        segment = profile_editor.value_widget()  # type: ignore[attr-defined]
        self.assertIsInstance(segment, SegmentedEnumInput)
        assert isinstance(segment, SegmentedEnumInput)

        checked_id = segment.group.checkedId()
        if checked_id < 0:
            for button_id, value in segment._values_by_id.items():  # type: ignore[attr-defined]
                if value == 1:
                    btn = segment.group.button(button_id)
                    assert btn is not None
                    btn.click()
                    checked_id = button_id
                    break
        self.assertGreaterEqual(checked_id, 0)
        checked_button = segment.group.button(checked_id)
        self.assertIsNotNone(checked_button)
        assert checked_button is not None
        checked_button.click()

        self.assertFalse(segment.is_set())
        payload = self.form.payload()
        state = next(item for item in payload["param_states"] if item.get("param_name") == "Throat.Profile")
        self.assertEqual(state["is_set"], 0)

    def test_mode_defaults_start_on_no_or_disabled_selection(self) -> None:
        throat_editor = self.form.editor_for_key("Throat.Profile")
        gcurve_editor = self.form.editor_for_key("GCurve.Type")
        morph_editor = self.form.editor_for_key("Morph.TargetShape")
        enclosure_editor = self.form.editor_for_key("Mesh.Enclosure")
        self.assertIsNotNone(throat_editor)
        self.assertIsNotNone(gcurve_editor)
        self.assertIsNotNone(morph_editor)
        self.assertIsNone(self.form.editor_for_key("Rollback"))
        self.assertIsNotNone(enclosure_editor)
        assert throat_editor is not None
        assert gcurve_editor is not None
        assert morph_editor is not None
        assert enclosure_editor is not None

        throat_segment = throat_editor.value_widget()  # type: ignore[attr-defined]
        gcurve_segment = gcurve_editor.value_widget()  # type: ignore[attr-defined]
        morph_segment = morph_editor.value_widget()  # type: ignore[attr-defined]
        enclosure_toggle = enclosure_editor.toggle  # type: ignore[attr-defined]
        self.assertIsInstance(throat_segment, SegmentedEnumInput)
        self.assertIsInstance(gcurve_segment, SegmentedEnumInput)
        self.assertIsInstance(morph_segment, SegmentedEnumInput)
        self.assertIsInstance(enclosure_toggle, SegmentedEnumInput)
        assert isinstance(throat_segment, SegmentedEnumInput)
        assert isinstance(gcurve_segment, SegmentedEnumInput)
        assert isinstance(morph_segment, SegmentedEnumInput)
        assert isinstance(enclosure_toggle, SegmentedEnumInput)

        self.assertIsNone(throat_segment.value())
        self.assertIsNone(gcurve_segment.value())
        self.assertIsNone(morph_segment.value())
        self.assertEqual(enclosure_toggle.value(), 0)

    def test_reclick_other_option_returns_to_no_or_disabled_selection(self) -> None:
        def click_value(segment: SegmentedEnumInput, target: object) -> None:
            for button_id, value in segment._values_by_id.items():  # type: ignore[attr-defined]
                if value == target:
                    button = segment.group.button(button_id)
                    assert button is not None
                    button.click()
                    return
            self.fail(f"value {target!r} not found")

        gcurve_editor = self.form.editor_for_key("GCurve.Type")
        morph_editor = self.form.editor_for_key("Morph.TargetShape")
        enclosure_editor = self.form.editor_for_key("Mesh.Enclosure")
        self.assertIsNotNone(gcurve_editor)
        self.assertIsNotNone(morph_editor)
        self.assertIsNone(self.form.editor_for_key("Rollback"))
        self.assertIsNotNone(enclosure_editor)
        assert gcurve_editor is not None
        assert morph_editor is not None
        assert enclosure_editor is not None

        gcurve_segment = gcurve_editor.value_widget()  # type: ignore[attr-defined]
        morph_segment = morph_editor.value_widget()  # type: ignore[attr-defined]
        enclosure_toggle = enclosure_editor.toggle  # type: ignore[attr-defined]
        assert isinstance(gcurve_segment, SegmentedEnumInput)
        assert isinstance(morph_segment, SegmentedEnumInput)
        assert isinstance(enclosure_toggle, SegmentedEnumInput)

        click_value(gcurve_segment, 1)
        self.assertEqual(gcurve_segment.value(), 1)
        click_value(gcurve_segment, 1)
        self.assertIsNone(gcurve_segment.value())

        non_zero_morph = next(
            value for value in morph_segment._values_by_id.values()  # type: ignore[attr-defined]
            if isinstance(value, int) and value != 0
        )
        click_value(morph_segment, non_zero_morph)
        self.assertEqual(morph_segment.value(), non_zero_morph)
        click_value(morph_segment, non_zero_morph)
        self.assertIsNone(morph_segment.value())

        click_value(enclosure_toggle, 1)
        self.assertEqual(enclosure_toggle.value(), 1)
        click_value(enclosure_toggle, 1)
        self.assertEqual(enclosure_toggle.value(), 0)

    def test_zero_placeholder_is_not_actual_value_and_numeric_is_editable(self) -> None:
        widget = self.form.value_widget_for_key("Throat.Diameter")
        self.assertIsNotNone(widget)
        assert isinstance(widget, NullableNumericInput)
        self.assertEqual(widget.edit.text(), "")
        self.assertEqual(widget.edit.placeholderText(), "0")
        self.assertTrue(bool(widget.edit.alignment() & Qt.AlignLeft))
        widget.edit.setText("12.5")
        self.assertEqual(widget.value(), 12.5)
        widget.edit.clear()
        self.assertIsNone(widget.value())

    def test_no_selection_clear_x_buttons_exist(self) -> None:
        clear_buttons = [button for button in self.form.findChildren(QToolButton) if button.text().strip() == "x"]
        self.assertEqual(clear_buttons, [])

    def test_horizontal_scrollbars_are_disabled_for_project_columns(self) -> None:
        self.assertEqual(self.form.geometry_scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        self.assertEqual(self.form.mesh_scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)

    def test_gcurve_selection_has_no_gcurve_mode_and_unset_payload(self) -> None:
        editor = self.form.editor_for_key("GCurve.Type")
        self.assertIsNotNone(editor)
        assert editor is not None
        widget = editor.value_widget()  # type: ignore[attr-defined]
        self.assertIsInstance(widget, SegmentedEnumInput)
        assert isinstance(widget, SegmentedEnumInput)
        labels = [button.text() for button in widget.findChildren(QPushButton) if button.property("segment") == "true"]
        self.assertEqual(labels, ["no GCurve", "Superellipse", "Superformula"])

        payload = self.form.payload()
        state = next(item for item in payload["param_states"] if item.get("param_name") == "GCurve.Type")
        self.assertEqual(state["is_set"], 0)
        self.assertIsNone(state["value"])

    def test_morph_detail_context_frame_disclosure_and_bool_segment(self) -> None:
        target_width_editor = self.form.editor_for_key("Morph.TargetWidth")
        self.assertIsNotNone(target_width_editor)
        assert target_width_editor is not None
        self.assertTrue(target_width_editor.isHidden())

        target_shape_editor = self.form.editor_for_key("Morph.TargetShape")
        self.assertIsNotNone(target_shape_editor)
        assert target_shape_editor is not None
        target_shape_editor.set_value(1)  # type: ignore[attr-defined]
        self.form._on_any_field_changed()  # type: ignore[attr-defined]
        self.assertFalse(target_width_editor.isHidden())

        shrink_editor = self.form.value_widget_for_key("Morph.AllowShrinkage")
        self.assertIsNotNone(shrink_editor)
        self.assertIsInstance(shrink_editor, NullableBoolInput)
        assert isinstance(shrink_editor, NullableBoolInput)
        self.assertIsInstance(shrink_editor.segment, SegmentedEnumInput)

    def test_context_frames_exist_for_conditional_sections(self) -> None:
        frames = [
            frame
            for frame in self.form.findChildren(QFrame)
            if frame.objectName() == "ContextFrame"
        ]
        self.assertGreaterEqual(len(frames), 4)

    def test_mesh_core_is_two_column_with_selection_anchor(self) -> None:
        core_box = next(box for box in self.form.findChildren(QGroupBox) if box.title() == "Core")
        box_layout = core_box.layout()
        self.assertIsNotNone(box_layout)
        assert box_layout is not None
        body_widget = None
        for index in range(box_layout.count()):
            candidate = box_layout.itemAt(index).widget()
            if candidate is None:
                continue
            candidate_layout = candidate.layout()
            if candidate_layout is not None and candidate_layout.count() >= 2:
                first = candidate_layout.itemAt(0).layout()
                second = candidate_layout.itemAt(1).layout()
                if isinstance(first, QGridLayout) and isinstance(second, QGridLayout):
                    body_widget = candidate
                    break
        self.assertIsNotNone(body_widget)
        assert body_widget is not None
        body_layout = body_widget.layout()
        self.assertIsNotNone(body_layout)
        assert body_layout is not None
        selection_grid = body_layout.itemAt(0).layout()
        form_grid = body_layout.itemAt(1).layout()
        self.assertIsInstance(selection_grid, QGridLayout)
        self.assertIsInstance(form_grid, QGridLayout)
        assert isinstance(selection_grid, QGridLayout) and isinstance(form_grid, QGridLayout)

        # left input anchor (selection) should match left input anchor (form)
        _, sel_col, _, _ = selection_grid.getItemPosition(1)
        self.assertEqual(sel_col, 1)
        left_label_count = 0
        right_label_count = 0
        for index in range(form_grid.count()):
            _, col, _, _ = form_grid.getItemPosition(index)
            widget = form_grid.itemAt(index).widget()
            if not isinstance(widget, QLabel):
                continue
            if col == 0:
                left_label_count += 1
            if col == 3:
                right_label_count += 1
        self.assertGreater(right_label_count, 0)
        self.assertLessEqual(abs(left_label_count - right_label_count), 1)
        self.assertGreaterEqual(right_label_count, left_label_count)

    def test_enclosure_group_has_no_redundant_mesh_enclosure_label(self) -> None:
        labels = [label.text().strip() for label in self.form.findChildren(QLabel)]
        self.assertNotIn("Mesh Enclosure", labels)

    def test_slot_length_expression_shows_unit_mm(self) -> None:
        widget = self.form.value_widget_for_key("Slot.Length")
        self.assertIsNotNone(widget)
        assert widget is not None
        unit_label = getattr(widget, "unit_label", None)
        self.assertIsNotNone(unit_label)
        self.assertEqual(unit_label.text().strip(), "mm")

    def test_half_angle_unit_overrides_are_applied(self) -> None:
        specs = self.form.schema.by_key()
        self.assertEqual(specs["Throat.Angle"].unit, "deg/2")
        self.assertEqual(specs["Coverage.Angle"].unit, "deg/2")
        self.assertEqual(specs["Throat.Ext.Angle"].unit, "deg/2")
        throat_angle_widget = self.form.value_widget_for_key("Throat.Angle")
        self.assertIsNotNone(throat_angle_widget)
        assert throat_angle_widget is not None
        throat_unit = getattr(throat_angle_widget, "unit_label")
        self.assertEqual(throat_unit.text().strip(), "deg/2")
        self.assertGreaterEqual(throat_unit.width(), throat_unit.fontMetrics().horizontalAdvance("deg/2"))
        coverage_widget = self.form.value_widget_for_key("Coverage.Angle")
        self.assertIsNotNone(coverage_widget)
        assert coverage_widget is not None

    def test_field_state_ok_warn_fatal_and_badge(self) -> None:
        editor = self.form.editor_for_key("Length")
        self.assertIsNotNone(editor)
        assert editor is not None
        editor.set_is_set(True)  # type: ignore[attr-defined]
        editor.set_value(600.0)  # type: ignore[attr-defined]
        self.form._on_any_field_changed()  # type: ignore[attr-defined]

        self.form.apply_ui_risks([])
        value_widget = self.form.value_widget_for_key("Length")
        self.assertIsNotNone(value_widget)
        assert value_widget is not None
        line_edit = getattr(value_widget, "edit", None)
        self.assertIsNotNone(line_edit)
        self.assertEqual(line_edit.property("fieldState"), "ok")

        self.form.apply_ui_risks(
            [
                {
                    "field_key": "Length",
                    "severity": "warn",
                    "message": "Outside recommended range.",
                    "suggestion": "Use 200-1000.",
                    "source": "experiment",
                }
            ]
        )
        self.assertEqual(line_edit.property("fieldState"), "warn")
        badge = getattr(editor, "_state_badge", None)
        self.assertIsNotNone(badge)
        assert badge is not None
        self.assertEqual(badge.property("severity"), "warn")
        self.assertEqual(badge.text(), "!")

        self.form.apply_ui_risks(
            [
                {
                    "field_key": "Length",
                    "severity": "fatal",
                    "message": "Hard cap exceeded.",
                    "suggestion": "Reduce value.",
                    "source": "experiment",
                }
            ]
        )
        self.assertEqual(line_edit.property("fieldState"), "fatal")
        self.assertEqual(badge.property("severity"), "fatal")
        self.assertEqual(badge.text(), "x")

        editor.set_is_set(False)  # type: ignore[attr-defined]
        self.form._on_any_field_changed()  # type: ignore[attr-defined]
        self.form.apply_ui_risks([])
        self.assertEqual(line_edit.property("fieldState"), "neutral")
        self.assertEqual(badge.property("severity"), "neutral")
        self.assertEqual(badge.text(), "")

    def test_gcurve_common_and_superformula_use_compact_grid(self) -> None:
        gcurve_editor = self.form.editor_for_key("GCurve.Type")
        self.assertIsNotNone(gcurve_editor)
        assert gcurve_editor is not None
        gcurve_editor.set_value(2)  # type: ignore[attr-defined]
        self.form._on_any_field_changed()  # type: ignore[attr-defined]

        stacked, _ = self.form._mode_widgets["GCurve.Type"]  # type: ignore[attr-defined]
        current_page = stacked.currentWidget()
        self.assertIsNotNone(current_page)
        assert current_page is not None
        compact_grids = current_page.findChildren(ResponsiveCompactGrid)
        self.assertTrue(compact_grids)
        assert compact_grids
        compact = compact_grids[0]
        compact.resize(900, 300)
        compact._relayout()  # type: ignore[attr-defined]
        grid = compact.layout()
        self.assertIsNotNone(grid)
        assert grid is not None
        max_col = 0
        for index in range(grid.count()):
            _, col, _, _ = grid.getItemPosition(index)
            max_col = max(max_col, col)
        self.assertGreaterEqual(max_col, 2)

        compact.resize(520, 300)
        compact._relayout()  # type: ignore[attr-defined]
        max_col_small = 0
        for index in range(grid.count()):
            _, col, _, _ = grid.getItemPosition(index)
            max_col_small = max(max_col_small, col)
        self.assertLessEqual(max_col_small, 1)

    def test_common_block_hidden_for_no_gcurve(self) -> None:
        headings = [
            label
            for label in self.form.findChildren(QLabel)
            if label.text().strip() == "Common"
        ]
        self.assertTrue(headings)
        self.assertTrue(all(not label.isVisible() for label in headings))

    def test_input_widths_are_uniform_with_and_without_unit(self) -> None:
        with_unit = self.form.value_widget_for_key("Throat.Angle")
        without_unit = self.form.value_widget_for_key("Length")
        self.assertIsNotNone(with_unit)
        self.assertIsNotNone(without_unit)
        assert with_unit is not None and without_unit is not None
        with_edit = getattr(with_unit, "edit")
        without_edit = getattr(without_unit, "edit")
        self.assertEqual(with_edit.width(), without_edit.width())

    def test_project_action_bar_contains_primary_cta(self) -> None:
        page = ProjectPage()
        action_bar = getattr(page, "action_bar", None)
        self.assertIsNotNone(action_bar)
        assert action_bar is not None
        self.assertIs(page.create_btn.parent(), action_bar)
        self.assertEqual(page.create_btn.text(), "Create Project")

    def test_main_columns_are_not_collapsible(self) -> None:
        toggle_buttons = [
            button
            for button in self.form.findChildren(QToolButton)
            if button.text().strip() in {"Geometry", "Mesh"}
        ]
        self.assertEqual(toggle_buttons, [])

    def test_coverage_angle_is_in_basics_and_hidden_when_gcurve_enabled(self) -> None:
        coverage_editor = self.form.editor_for_key("Coverage.Angle")
        self.assertIsNotNone(coverage_editor)
        assert coverage_editor is not None
        self.assertFalse(coverage_editor.isHidden())

        gcurve_editor = self.form.editor_for_key("GCurve.Type")
        self.assertIsNotNone(gcurve_editor)
        assert gcurve_editor is not None
        gcurve_editor.set_value(1)  # type: ignore[attr-defined]
        self.form._on_any_field_changed()  # type: ignore[attr-defined]
        self.assertTrue(coverage_editor.isHidden())

    def test_no_gcurve_subblock_is_not_rendered(self) -> None:
        headings = [
            label.text().strip().lower()
            for label in self.form.findChildren(QLabel)
            if label.objectName() == "ContextTitle"
        ]
        self.assertNotIn("no gcurve", headings)

    def test_throat_page_headers_are_named_and_rosse_has_no_extra_header_frame(self) -> None:
        headings = [
            label.text().strip()
            for label in self.form.findChildren(QLabel)
            if label.objectName() == "ContextTitle"
        ]
        self.assertIn("OS-SE", headings)
        self.assertIn("Circular Arc", headings)
        self.assertNotIn("R-OSSE", headings)

    def test_throat_profile_unset_hides_osse_page(self) -> None:
        profile_editor = self.form.editor_for_key("Throat.Profile")
        self.assertIsNotNone(profile_editor)
        assert profile_editor is not None
        profile_editor.set_is_set(False)  # type: ignore[attr-defined]
        self.form._on_any_field_changed()  # type: ignore[attr-defined]

        term_editor = self.form.editor_for_key("Term.s")
        self.assertIsNotNone(term_editor)
        assert term_editor is not None
        self.assertFalse(term_editor.isVisible())


if __name__ == "__main__":
    unittest.main()
