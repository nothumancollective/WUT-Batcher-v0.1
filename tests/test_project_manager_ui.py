from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import ProjectManagerWindow
from app.models import Project
from ui.widgets.project_card import ProjectCardV2

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

    def test_project_list_uses_tile_widgets_in_icon_mode(self) -> None:
        window = ProjectManagerWindow(_FakeService())
        self.assertEqual(window.project_list.viewMode(), QListView.IconMode)
        self.assertEqual(window.project_list.count(), 2)
        first = window.project_list.item(0)
        self.assertIsNotNone(first)
        assert first is not None
        card = window.project_list.itemWidget(first)
        self.assertIsInstance(card, ProjectCardV2)
        assert isinstance(card, ProjectCardV2)
        self.assertEqual(first.sizeHint(), ProjectCardV2.size_hint())
        self.assertEqual(window.project_list.gridSize(), ProjectCardV2.grid_size_hint())
        self.assertEqual(window.project_list.spacing(), ProjectCardV2.grid_spacing())
        self.assertTrue(card.is_selected())

    def test_project_list_selection_highlight_is_transparent(self) -> None:
        window = ProjectManagerWindow(_FakeService())
        color = window.project_list.palette().color(window.project_list.backgroundRole())
        _ = color
        highlight = window.project_list.palette().color(QPalette.ColorRole.Highlight)
        self.assertEqual(int(highlight.alpha()), 0)

    def test_card_click_updates_selection_state(self) -> None:
        window = ProjectManagerWindow(_FakeService())
        first = window.project_list.item(0)
        second = window.project_list.item(1)
        assert first is not None
        assert second is not None
        first_card = window.project_list.itemWidget(first)
        second_card = window.project_list.itemWidget(second)
        assert isinstance(first_card, ProjectCardV2)
        assert isinstance(second_card, ProjectCardV2)
        second_card.clicked.emit()
        self.assertIs(window.project_list.currentItem(), second)
        self.assertFalse(first_card.is_selected())
        self.assertTrue(second_card.is_selected())


if __name__ == "__main__":
    unittest.main()
