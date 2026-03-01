from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.widgets.project_card import ProjectCardV2

try:
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QColor = None  # type: ignore[assignment]
    QPixmap = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None or QPixmap is None or QColor is None, "PySide6 is required")
class ProjectCardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_project_card_resizes_and_accepts_preview_pixmap(self) -> None:
        card = ProjectCardV2(project_name="Project Card Stress Preview Name")
        pixmap = QPixmap(512, 384)
        pixmap.fill(QColor("#507090"))
        card.set_preview_pixmap(pixmap)
        card.resize(ProjectCardV2.size_hint())
        self.app.processEvents()
        self.assertEqual(card.sizeHint(), ProjectCardV2.size_hint())
        self.assertEqual(card.minimumSizeHint(), ProjectCardV2.size_hint())
        self.assertEqual(card.sizeHint().width(), 240)
        self.assertEqual(card.sizeHint().height(), 180)
        self.assertEqual(card.preview.sizeHint(), ProjectCardV2.preview_size_hint())
        self.assertEqual(card.preview.sizeHint().height(), round(card.preview.sizeHint().width() * 9 / 16))
        self.assertTrue(bool(card.title_label.text()))
        card.resize(240, 180)
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
