from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE
from app.gui import ProjectPage

try:
    from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton, QToolButton
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QGroupBox = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]
    QToolButton = None  # type: ignore[assignment]

from ui.form_builder import NullableNumericInput, ParameterForm, SegmentedEnumInput
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
        self.assertIn("Projekt erstellen", labels)
        self.assertNotIn("Back to Dashboard", labels)
        self.assertNotIn("Show details", labels)
        self.assertFalse(
            any("Project Compatibility" == str(box.title()) for box in page.findChildren(QGroupBox))
        )

    def test_form_layout_has_two_columns_geometry_and_mesh(self) -> None:
        self.assertTrue(hasattr(self.form, "geometry_scroll"))
        self.assertTrue(hasattr(self.form, "mesh_scroll"))

    def test_geometry_order_matches_spec(self) -> None:
        section_layout = self.form.geometry_section.content_layout
        titles = [
            section_layout.itemAt(index).widget().title()
            for index in range(section_layout.count())
            if section_layout.itemAt(index).widget() is not None
            and isinstance(section_layout.itemAt(index).widget(), QGroupBox)
        ]
        self.assertEqual(titles, ["Basics", "Throat Profile", "Morph", "GCurve", "Rollback"])

    def test_mesh_order_matches_spec(self) -> None:
        section_layout = self.form.mesh_section.content_layout
        titles = [
            section_layout.itemAt(index).widget().title()
            for index in range(section_layout.count())
            if section_layout.itemAt(index).widget() is not None
            and isinstance(section_layout.itemAt(index).widget(), QGroupBox)
        ]
        self.assertEqual(titles, ["Core", "Enclosure"])

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
        self.assertGreaterEqual(checked_id, 0)
        checked_button = segment.group.button(checked_id)
        self.assertIsNotNone(checked_button)
        assert checked_button is not None
        checked_button.click()

        self.assertFalse(segment.is_set())
        payload = self.form.payload()
        state = next(item for item in payload["param_states"] if item.get("param_name") == "Throat.Profile")
        self.assertEqual(state["is_set"], 0)

    def test_optional_is_placeholder_not_actual_value_and_numeric_is_editable(self) -> None:
        widget = self.form.value_widget_for_key("Throat.Diameter")
        self.assertIsNotNone(widget)
        assert isinstance(widget, NullableNumericInput)
        self.assertEqual(widget.edit.text(), "")
        self.assertEqual(widget.edit.placeholderText(), "optional")
        widget.edit.setText("12.5")
        self.assertEqual(widget.value(), 12.5)

    def test_no_selection_clear_x_buttons_exist(self) -> None:
        clear_buttons = [button for button in self.form.findChildren(QToolButton) if button.text().strip() == "x"]
        self.assertEqual(clear_buttons, [])


if __name__ == "__main__":
    unittest.main()
