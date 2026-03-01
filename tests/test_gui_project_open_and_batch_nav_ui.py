from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import GuiController
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
class ProjectOpenAndBatchNavUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_controller_defers_main_window_until_needed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui_regression_lazy_main_") as tmp:
            service = _build_service(Path(tmp))
            controller = GuiController(service)

            self.assertIsNone(controller._main_window)
            controller.set_startup_status("Doctor ok.", detail='{"overall_status":"ok"}')
            self.assertIsNone(controller._main_window)

            window = controller.main_window
            self.assertEqual(window.status_message.text(), "Doctor ok.")
            window.close()
            controller.project_manager.close()

    def test_create_project_is_single_shot_when_create_clicked_twice(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui_regression_create_once_") as tmp:
            service = _build_service(Path(tmp))
            controller = GuiController(service)
            window = controller.main_window
            window.show_project()
            window.project_page.project_name.setText("RegressionProject")

            window.project_page.create_btn.click()
            self.app.processEvents()
            window.project_page.create_btn.click()
            self.app.processEvents()

            named = [project for project in service.list_projects() if project.name == "RegressionProject"]
            self.assertEqual(len(named), 1)
            window.close()
            controller.project_manager.close()

    def test_open_project_then_batch_navigation_paths_work(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui_regression_open_batch_") as tmp:
            service = _build_service(Path(tmp))
            created = service.create_project(
                "RegressionOpen",
                {"fixed_params": {}, "limits": {}, "param_states": []},
            )
            controller = GuiController(service)
            project_manager = controller.project_manager
            window = controller.main_window

            project_manager.refresh()
            project_manager.project_list.setCurrentRow(0)
            project_manager.open_btn.click()
            self.app.processEvents()

            self.assertIsNotNone(window.current_project)
            assert window.current_project is not None
            self.assertEqual(window.current_project.project_id, created.project_id)

            window.batch_mode_button.click()
            self.app.processEvents()
            self.assertIs(window.stack.currentWidget(), window.batch_page)

            window.show_dashboard()
            self.app.processEvents()
            window.dashboard_page.new_batch_btn.click()
            self.app.processEvents()
            self.assertIs(window.stack.currentWidget(), window.batch_page)

            window.close()
            project_manager.close()

    def test_batch_mode_without_project_stays_on_dashboard(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui_regression_batch_guard_") as tmp:
            service = _build_service(Path(tmp))
            controller = GuiController(service)
            window = controller.main_window

            window.show_dashboard()
            self.app.processEvents()
            window.batch_mode_button.click()
            self.app.processEvents()

            self.assertIs(window.stack.currentWidget(), window.dashboard_page)
            self.assertIn("Open or create a project", window.status_message.text())

            window.close()
            controller.project_manager.close()


if __name__ == "__main__":
    unittest.main()
