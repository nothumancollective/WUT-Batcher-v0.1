from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import BatchPage

try:
    from PySide6.QtWidgets import QApplication
    from ui.form_builder import ScalarFieldEditor
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    ScalarFieldEditor = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class ThroatRosseUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_rosse_mode_uses_property_rows_and_preserves_object_payload_shape(self) -> None:
        page = BatchPage()
        form = page.parameter_form
        self.assertNotIn("R-OSSE", form._rows)
        rosse_keys = sorted(key for key in form._rows.keys() if key.startswith("R-OSSE."))
        self.assertGreater(len(rosse_keys), 0)

        form.set_selected_params({"Throat.Profile": 2, "R-OSSE": {"a0": 5.0, "a": 35.0}})
        form.apply_compatibility(
            {
                "visible_keys": ["Throat.Profile", *rosse_keys],
                "locked_keys": [],
                "sweepable_keys": list(rosse_keys),
                "compat_ui_state": {},
            }
        )

        sample_key = next((key for key in rosse_keys if key.endswith(".a")), rosse_keys[0])
        row = form._rows[sample_key]
        self.assertEqual(str(row.container.property("rowVisible")).lower(), "true")
        self.assertIsInstance(row.base_editor, ScalarFieldEditor)
        self.assertFalse(row.sweep_toggle.isHidden())
        self.assertTrue(row.sweep_toggle.isEnabled())

        payload = form.selected_params_payload()
        self.assertIn("R-OSSE", payload)
        self.assertIsInstance(payload["R-OSSE"], dict)
        self.assertEqual(payload["R-OSSE"].get("a0"), 5.0)
        self.assertEqual(payload["R-OSSE"].get("a"), 35.0)

    def test_rosse_property_sweeps_use_dotted_keys(self) -> None:
        page = BatchPage()
        form = page.parameter_form
        rosse_keys = sorted(key for key in form._rows.keys() if key.startswith("R-OSSE."))
        sample_key = next((key for key in rosse_keys if key.endswith(".a")), rosse_keys[0])
        form.set_selected_params({"Throat.Profile": 2, "R-OSSE": {"a": 25.0}})
        form.apply_compatibility(
            {
                "visible_keys": ["Throat.Profile", *rosse_keys],
                "locked_keys": [],
                "sweepable_keys": [sample_key],
                "compat_ui_state": {},
            }
        )
        form.set_sweeps({sample_key: {"start": 10.0, "end": 40.0, "steps": 4}})
        sweeps = form.sweeps_payload()
        self.assertIn(sample_key, sweeps)
        self.assertEqual(int(sweeps[sample_key]["steps"]), 4)


if __name__ == "__main__":
    unittest.main()
