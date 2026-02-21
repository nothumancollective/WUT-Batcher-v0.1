from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.theme import build_stylesheet

try:
    from PySide6.QtWidgets import QApplication, QComboBox, QSpinBox, QStyle, QStyleOptionComboBox, QStyleOptionSpinBox
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QComboBox = None  # type: ignore[assignment]
    QSpinBox = None  # type: ignore[assignment]
    QStyle = None  # type: ignore[assignment]
    QStyleOptionComboBox = None  # type: ignore[assignment]
    QStyleOptionSpinBox = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class ArrowResourcesUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_stylesheet_references_qrc_arrow_icons(self) -> None:
        css = build_stylesheet()
        self.assertIn(":/icons/chevron_down.svg", css)
        self.assertIn(":/icons/chevron_up.svg", css)

    def test_combo_and_spin_subcontrols_have_visible_arrow_rects(self) -> None:
        self.app.setStyleSheet(build_stylesheet())

        combo = QComboBox()
        combo.setObjectName("BatchExportCombo")
        combo.addItems(["one", "two"])
        combo.resize(180, 32)
        combo_opt = QStyleOptionComboBox()
        combo_opt.initFrom(combo)
        combo_opt.rect = combo.rect()
        arrow_rect = combo.style().subControlRect(QStyle.CC_ComboBox, combo_opt, QStyle.SC_ComboBoxArrow, combo)
        self.assertGreater(arrow_rect.width(), 0)
        self.assertGreater(arrow_rect.height(), 0)

        spin = QSpinBox()
        spin.resize(180, 32)
        spin_opt = QStyleOptionSpinBox()
        spin_opt.initFrom(spin)
        spin_opt.rect = spin.rect()
        up_rect = spin.style().subControlRect(QStyle.CC_SpinBox, spin_opt, QStyle.SC_SpinBoxUp, spin)
        down_rect = spin.style().subControlRect(QStyle.CC_SpinBox, spin_opt, QStyle.SC_SpinBoxDown, spin)
        self.assertGreater(up_rect.width(), 0)
        self.assertGreater(up_rect.height(), 0)
        self.assertGreater(down_rect.width(), 0)
        self.assertGreater(down_rect.height(), 0)


if __name__ == "__main__":
    unittest.main()

