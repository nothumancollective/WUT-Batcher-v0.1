from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.geometry_driver_ui import DriverLibraryDialog, GeometryManagerDialog
from app.gui import MainWindow, ProjectPage
from app.driver_library import DriverDefinition, DriverRevision
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]


def _service(root: Path) -> OrchestratorService:
    store = SettingsStore(root / "settings.json")
    store.save(UserSettings(library_root=str(root / "library")))
    return OrchestratorService(store)


@unittest.skipIf(QApplication is None, "PySide6 is required")
class GeometryDriverUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_project_page_shows_long_geometry_context_and_manage_action(self) -> None:
        page = ProjectPage()
        page.set_geometry_context({
            "geometry_id": "G1", "name": "A very long geometry name " * 8,
            "role": "mid_horn", "default_driver_revision_id": None,
            "description": "A detailed description " * 20,
        })
        self.assertTrue(page.geometry_context.isVisible() or not page.isVisible())
        self.assertIn("mid_horn", page.geometry_label.text())
        self.assertIn("no default driver", page.geometry_label.text())
        self.assertTrue(page.manage_geometries_button.isEnabled())

    def test_geometry_manager_lists_primary_geometry_and_driver_none_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_geometry_ui_") as tmp:
            service = _service(Path(tmp))
            project = service.create_project("Geometry UI", {"fixed_params": {}, "limits": {}})
            dialog = GeometryManagerDialog(service, project.project_id)
            self.assertEqual(dialog.list.count(), 1)
            self.assertIn("Primary Geometry", dialog.list.item(0).text())
            self.assertEqual(dialog.default_driver.itemData(0), "")
            dialog.close()

    def test_main_window_filters_batches_to_active_geometry_and_labels_snapshot_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_geometry_main_ui_") as tmp:
            service = _service(Path(tmp))
            project = service.create_project("Geometry Main", {"fixed_params": {}, "limits": {}})
            second = service.create_geometry(project.project_id, name="Second", role="waveguide")
            first = service.list_geometries(project.project_id)[0]
            window = MainWindow(service)
            window.load_project(project)
            self.assertEqual(window.current_geometry_id, first["geometry_id"])
            self.assertIn("Simulation context", window.batch_page.execution_context_label.text())
            window.current_geometry_id = second["geometry_id"]
            window._sync_geometry_context()
            self.assertIn("Second", window.batch_page.command_header.name_label.text())
            window.close()

    def test_driver_library_empty_state_is_usable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_driver_ui_") as tmp:
            dialog = DriverLibraryDialog(_service(Path(tmp)))
            self.assertEqual(dialog.list.count(), 0)
            self.assertIn("No driver selected", dialog.details.toPlainText())
            self.assertTrue(dialog.import_button.isEnabled())
            dialog.close()

    def test_driver_filters_accept_qt_signal_arguments(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_driver_filter_ui_") as tmp:
            dialog = DriverLibraryDialog(_service(Path(tmp)))
            dialog.search.setText("compression")
            dialog.kind.setCurrentIndex(1)
            self.assertNotIn("Â", dialog.details.toPlainText())
            dialog.close()

    def test_geometry_can_select_and_display_non_latest_driver_revision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_driver_revision_ui_") as tmp:
            service = _service(Path(tmp))
            project = service.create_project("Revision UI", {"fixed_params": {}, "limits": {}})
            geometry = service.list_geometries(project.project_id)[0]
            first = service.create_driver(
                definition=DriverDefinition(
                    driver_id="D-UI", manufacturer="Example", model="CD-1", kind="compression_driver",
                ).__dict__,
                revision=DriverRevision(
                    revision_id="DR-UI-1", driver_id="D-UI", revision_number=1,
                    provenance={"source": "test", "trust": "user_asserted"},
                ).__dict__,
            )
            service.create_driver_revision(
                "D-UI", parameters={}, provenance={"source": "test", "trust": "user_asserted"},
            )
            service.set_geometry_default_driver(project.project_id, geometry["geometry_id"], first["revision_id"])

            dialog = GeometryManagerDialog(service, project.project_id)
            self.assertGreaterEqual(dialog.default_driver.count(), 3)
            self.assertGreaterEqual(dialog.default_driver.findData("DR-UI-1"), 1)
            dialog.close()

            window = MainWindow(service)
            window.load_project(project)
            self.assertIn("DR-UI-1", window.batch_page.execution_context_label.text())
            self.assertIn(first["revision_hash"][:12], window.batch_page.execution_context_label.text())
            window.close()


if __name__ == "__main__":
    unittest.main()
