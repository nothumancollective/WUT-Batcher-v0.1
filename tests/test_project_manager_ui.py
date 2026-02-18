from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import ProjectManagerWindow
from app.models import Project

try:
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication, QListView
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QColor = None  # type: ignore[assignment]
    QPalette = None  # type: ignore[assignment]
    QListView = None  # type: ignore[assignment]


class _FakeService:
    def list_projects(self):
        return [
            Project(project_id="P001", name="Project Alpha", root_path="."),
            Project(project_id="P002", name="Project Beta", root_path="."),
        ]

    def project_preview_image_path(self, project_id: str):
        return Path(".") / "_non_existing_preview" / f"{project_id}.png"


@unittest.skipIf(QApplication is None, "PySide6 is required")
class ProjectManagerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_project_list_uses_tile_icon_mode(self) -> None:
        window = ProjectManagerWindow(_FakeService())
        self.assertEqual(window.project_list.viewMode(), QListView.IconMode)
        self.assertEqual(window.project_list.count(), 2)
        first = window.project_list.item(0)
        self.assertIsNotNone(first)
        assert first is not None
        self.assertFalse(first.icon().isNull())

    def test_project_list_selection_highlight_is_transparent(self) -> None:
        window = ProjectManagerWindow(_FakeService())
        color = window.project_list.palette().color(window.project_list.backgroundRole())
        _ = color
        highlight = window.project_list.palette().color(QPalette.ColorRole.Highlight)
        self.assertEqual(int(highlight.alpha()), 0)


if __name__ == "__main__":
    unittest.main()
