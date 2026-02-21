from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import ElidedToolButton, MainWindow
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]


def _build_service(tmp_root: Path) -> OrchestratorService:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / "library"
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store)


@unittest.skipIf(QApplication is None, "PySide6 is required")
class ModeBarUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_modebar_uses_compact_elided_toolbuttons(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui1d3_modebar_") as tmp:
            service = _build_service(Path(tmp))
            window = MainWindow(service)
            self.assertEqual(window.bottom_mode_bar.objectName(), "GlobalModeBar")
            for button in (window.project_mode_button, window.batch_mode_button, window.analyse_mode_button):
                self.assertIsInstance(button, ElidedToolButton)
                self.assertTrue(button.isCheckable())
                self.assertEqual(button.objectName(), "ModeBarButton")
            self.assertLessEqual(window.bottom_mode_bar.maximumHeight(), 40)
            window.close()

    def test_modebar_switches_page_and_checked_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui1d3_modebar_nav_") as tmp:
            service = _build_service(Path(tmp))
            window = MainWindow(service)
            project = service.create_project(
                "ModebarNavProject",
                {"fixed_params": {}, "limits": {}, "param_states": []},
            )
            window.load_project(project)
            window.batch_mode_button.click()
            self.assertIs(window.stack.currentWidget(), window.batch_page)
            self.assertTrue(window.batch_mode_button.isChecked())
            self.assertEqual(window.page_title_label.text().strip(), "BATCH")
            window.analyse_mode_button.click()
            self.assertIs(window.stack.currentWidget(), window.analyse_page)
            self.assertTrue(window.analyse_mode_button.isChecked())
            window.close()


if __name__ == "__main__":
    unittest.main()
