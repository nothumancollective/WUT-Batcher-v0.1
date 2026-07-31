from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.vacs_export_enforcer import (
    BST_CHECKED,
    BST_UNCHECKED,
    ControlRecord,
    ExportConfigurationError,
    REQUIRED_EXPORT_CONTROLS,
    RequiredControlSpec,
    Win32UiaExportDialogBackend,
    enforce_required_controls_with_backend,
    required_export_controls_for_graph_class,
    resolve_required_controls,
)


class _FakeBackend:
    def __init__(self, *, initial_state: int, settable: bool = True) -> None:
        self.control = object()
        self.state = int(initial_state)
        self.settable = bool(settable)
        self.apply_calls = []

    def resolve_control(self, spec: RequiredControlSpec):  # type: ignore[no-untyped-def]
        return self.control, "fake_selector"

    def read_state(self, control: object):  # type: ignore[no-untyped-def]
        if control is not self.control:
            return None
        return int(self.state)

    def apply_method(self, control: object, method: str, expected_state: int):  # type: ignore[no-untyped-def]
        self.apply_calls.append((method, int(expected_state)))
        if control is not self.control:
            return None
        if method == "bm_setcheck" and self.settable:
            self.state = int(expected_state)
        return int(self.state)

    def is_alive(self, control: object):  # type: ignore[no-untyped-def]
        return control is self.control


class VacsExportEnforcerTests(unittest.TestCase):
    def test_no_action_when_state_already_matches(self) -> None:
        backend = _FakeBackend(initial_state=BST_CHECKED)
        spec = RequiredControlSpec(
            purpose="IncludeHeader",
            expected_state=BST_CHECKED,
            settable=False,
            selector={"name_regex": "header"},
            methods=("bm_setcheck", "bm_click"),
        )
        result = enforce_required_controls_with_backend(backend, [spec])
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["controls"]), 1)
        row = result["controls"][0]
        self.assertEqual(row["before_state"], "CHECKED")
        self.assertEqual(row["after_state"], "CHECKED")
        self.assertEqual(row["attempted_methods"], [])
        self.assertFalse(row["changed"])

    def test_settable_control_is_changed(self) -> None:
        backend = _FakeBackend(initial_state=BST_UNCHECKED, settable=True)
        spec = RequiredControlSpec(
            purpose="IncludeHeader",
            expected_state=BST_CHECKED,
            settable=True,
            selector={"name_regex": "header"},
            methods=("bm_setcheck",),
        )
        result = enforce_required_controls_with_backend(backend, [spec])
        self.assertTrue(result["ok"])
        row = result["controls"][0]
        self.assertEqual(row["before_state"], "UNCHECKED")
        self.assertEqual(row["after_state"], "CHECKED")
        self.assertEqual(row["attempted_methods"], ["bm_setcheck"])
        self.assertTrue(row["changed"])

    def test_non_settable_control_raises(self) -> None:
        backend = _FakeBackend(initial_state=BST_UNCHECKED, settable=False)
        spec = RequiredControlSpec(
            purpose="IncludeHeader",
            expected_state=BST_CHECKED,
            settable=False,
            selector={"name_regex": "header"},
            methods=("bm_setcheck", "bm_click"),
        )
        with self.assertRaises(ExportConfigurationError) as ctx:
            enforce_required_controls_with_backend(backend, [spec])
        self.assertIn("Export configuration invalid", str(ctx.exception))
        self.assertIn("IncludeHeader", str(ctx.exception))
        self.assertIn("set this option to the expected state", str(ctx.exception))

    def test_try_matrix_form_is_graph_class_specific(self) -> None:
        contour = required_export_controls_for_graph_class("TForm_DatContour")
        graph = required_export_controls_for_graph_class("TForm_DatGraph")
        unknown = required_export_controls_for_graph_class("")

        self.assertEqual(
            next(row.expected_state for row in contour if row.purpose == "TryMatrixForm"),
            BST_UNCHECKED,
        )
        self.assertEqual(
            next(row.expected_state for row in graph if row.purpose == "TryMatrixForm"),
            BST_CHECKED,
        )
        self.assertEqual(
            next(row.expected_state for row in unknown if row.purpose == "TryMatrixForm"),
            BST_UNCHECKED,
        )

    def test_probe_report_overrides_settable_flag(self) -> None:
        spec = RequiredControlSpec(
            purpose="IncludeHeader",
            expected_state=BST_CHECKED,
            settable=False,
            selector={"name_regex": "header"},
            methods=("bm_setcheck",),
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_path = Path(tmp_dir) / "probe.json"
            report_path.write_text(
                json.dumps({"controls": [{"purpose": "IncludeHeader", "settable": True}]}),
                encoding="utf-8",
            )
            resolved = resolve_required_controls([spec], probe_report_path=report_path)
        self.assertEqual(len(resolved), 1)
        self.assertTrue(resolved[0].settable)

    def test_complex_format_selector_targets_phase_as_radiant(self) -> None:
        backend = Win32UiaExportDialogBackend.__new__(Win32UiaExportDialogBackend)
        backend.dialog = None
        backend._controls = [  # type: ignore[attr-defined]
            ControlRecord(
                handle=1902598,
                class_name="TRzCheckBox",
                control_type="Pane",
                automation_id="1902598",
                title="Preserve continuous phase",
                text="Preserve continuous phase",
                ctrl_id=1902598,
                style=0,
                win32_index=8,
                checkbox_index=6,
                rect_top=0,
                rect_left=0,
                wrapper=None,
            ),
            ControlRecord(
                handle=788396,
                class_name="TRzCheckBox",
                control_type="Pane",
                automation_id="788396",
                title="Phase as radiant",
                text="Phase as radiant",
                ctrl_id=788396,
                style=0,
                win32_index=7,
                checkbox_index=8,
                rect_top=0,
                rect_left=0,
                wrapper=None,
            ),
        ]
        spec = next(row for row in REQUIRED_EXPORT_CONTROLS if row.purpose == "ComplexFormat")
        control, selector = backend.resolve_control(spec)
        self.assertIsNotNone(control)
        self.assertEqual(getattr(control, "automation_id", ""), "788396")
        self.assertIn("automation_id=788396", selector)


if __name__ == "__main__":
    unittest.main()
