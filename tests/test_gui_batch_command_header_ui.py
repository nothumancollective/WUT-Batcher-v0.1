from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import BatchPage

try:
    from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]
    QScrollArea = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class BatchCommandHeaderUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_batch_page_uses_command_header_widget(self) -> None:
        page = BatchPage()
        self.assertEqual(page.command_header.objectName(), "CommandHeaderWidget")
        self.assertIs(page.batch_name, page.command_header.batch_name_edit)
        self.assertIs(page.save_btn, page.command_header.save_button)
        self.assertIs(page.run_btn, page.command_header.run_button)

    def test_command_header_switches_between_wide_and_narrow_layouts(self) -> None:
        page = BatchPage()
        page.resize(1320, 900)
        page._apply_equal_widths()
        self.assertEqual(page.command_header.current_layout_mode(), "wide")
        self.assertGreaterEqual(page.batch_name.maximumWidth(), 320)
        self.assertLessEqual(page.batch_name.maximumWidth(), 720)

        page.resize(760, 900)
        page._apply_equal_widths()
        self.assertEqual(page.command_header.current_layout_mode(), "narrow")

    def test_issue_chip_reflects_warnings_and_exposes_popover(self) -> None:
        page = BatchPage()
        page.batch_name.setText("A7-Issue-Chip")
        page.apply_ui_risks(
            [
                {
                    "severity": "warn",
                    "field_key": "Length",
                    "message": "Length warning from test.",
                }
            ]
        )
        issue_chip = page.findChild(QPushButton, "CommandIssuesChip")
        self.assertIsNotNone(issue_chip)
        assert issue_chip is not None
        self.assertIn("Warnings:", issue_chip.text())
        self.assertNotIn(" v", issue_chip.text())
        self.assertIn("Length warning from test.", issue_chip.toolTip())

    def test_issue_popover_uses_scrollable_body(self) -> None:
        page = BatchPage()
        issues = [{"severity": "warn", "field_key": "Length", "message": f"Warning {idx}"} for idx in range(1, 18)]
        page.apply_ui_risks(issues)
        page.command_header._show_issue_popover()  # type: ignore[attr-defined]
        menu = page.command_header._issues_menu  # type: ignore[attr-defined]
        self.assertIsNotNone(menu)
        assert menu is not None
        scroll = menu.findChild(QScrollArea)
        self.assertIsNotNone(scroll)
        assert scroll is not None
        self.assertEqual(int(scroll.maximumHeight()), 320)
        menu.close()


if __name__ == "__main__":
    unittest.main()
