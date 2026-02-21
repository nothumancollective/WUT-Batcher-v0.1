from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import BatchPage

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
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


if __name__ == "__main__":
    unittest.main()

