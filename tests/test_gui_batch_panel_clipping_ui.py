from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import BatchPage

try:
    from ui.form_builder import ElidedFixedLabel
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    ElidedFixedLabel = None  # type: ignore[assignment]
    QApplication = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class BatchPanelClippingUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_exports_footer_actions_have_padding_and_non_fixed_heights(self) -> None:
        page = BatchPage()
        footer_margins = page.export_panel.footer_layout.contentsMargins()
        self.assertGreaterEqual(int(footer_margins.bottom()), 2)
        self.assertGreaterEqual(page.export_panel.layout().contentsMargins().bottom(), 10)
        for button in (page.export_panel.enclosure_btn, page.export_panel.advanced_btn):
            self.assertGreaterEqual(button.minimumHeight(), 30)
            self.assertGreater(button.maximumHeight(), button.minimumHeight())

    def test_mesh_advanced_button_uses_non_clipping_height_policy(self) -> None:
        page = BatchPage()
        button = page.parameter_form._mesh_advanced_button
        self.assertIsNotNone(button)
        assert button is not None
        self.assertGreaterEqual(button.minimumHeight(), page.parameter_form._control_height)
        self.assertGreater(button.maximumHeight(), button.minimumHeight())

    def test_basics_rows_use_shared_alignment_spec_without_mode_hierarchy_changes(self) -> None:
        page = BatchPage()
        basics_spec = page.parameter_form._grid_spec_for_group("Basics")
        default_spec = page.parameter_form._grid_spec_for_group("Morph")
        self.assertLessEqual(int(basics_spec.label_width), int(default_spec.label_width))
        self.assertEqual(page.parameter_form.group_name_for_key("Length"), "Basics")
        length_row = page.parameter_form._rows.get("Length")
        self.assertIsNotNone(length_row)
        assert length_row is not None
        label = length_row.container.findChild(ElidedFixedLabel)
        self.assertIsNotNone(label)
        assert label is not None
        self.assertEqual(int(label.minimumWidth()), int(basics_spec.label_width))


if __name__ == "__main__":
    unittest.main()
