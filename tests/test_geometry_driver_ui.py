from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.geometry_driver_ui import DriverLibraryDialog, DriverRevisionEditorDialog, GeometryManagerDialog
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

    def test_geometry_manager_refresh_can_prefer_new_geometry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_geometry_ui_select_") as tmp:
            service = _service(Path(tmp))
            project = service.create_project("Geometry UI selection", {"fixed_params": {}, "limits": {}})
            dialog = GeometryManagerDialog(service, project.project_id)
            original_id = dialog.current_geometry_id()
            created = service.create_geometry(project.project_id, name="Created", role="hf_horn")

            dialog.refresh(preferred_geometry_id=created["geometry_id"])

            self.assertNotEqual(dialog.current_geometry_id(), original_id)
            self.assertEqual(dialog.current_geometry_id(), created["geometry_id"])
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
            self.assertIn(first["name"], window.dashboard_page.geometry_context_label.text())
            self.assertTrue(window.dashboard_page.manage_geometries_btn.isEnabled())
            window.current_geometry_id = second["geometry_id"]
            window._sync_geometry_context()
            self.assertIn("Second", window.batch_page.command_header.name_label.text())
            self.assertIn("Second", window.dashboard_page.geometry_context_label.text())
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

    def test_compression_form_round_trip_with_le_asset_and_revision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_driver_form_compression_") as tmp:
            root = Path(tmp)
            service = _service(root)
            source = root / "custom.le"
            source.write_text("System 'S1'\nDriver 'D1'\n", encoding="utf-8")
            dialog = DriverRevisionEditorDialog(
                service=service, title="Create", kind="compression_driver",
            )
            dialog.manufacturer.setText("Example Audio")
            dialog.model.setText("CD-25")
            dialog.variant.setText("8 ohm")
            dialog.parameter_inputs["exit_diameter"][0].setText("25.4")
            dialog.parameter_inputs["exit_diameter"][1].setCurrentText("mm")
            dialog.parameter_inputs["re"][0].setText("6.2")
            self.assertTrue(dialog.set_le_file(str(source)))
            definition_payload, revision_payload = dialog.build_payload()
            le_path = revision_payload.pop("le_source_path")
            expected = revision_payload.pop("le_expected_sha256")
            definition = DriverDefinition(driver_id="D-FORM-CD", origin="user", **definition_payload)
            revision = DriverRevision(
                revision_id="DR-FORM-CD-1", driver_id=definition.driver_id,
                revision_number=1, **revision_payload,
            )
            created = service.create_driver(
                definition=definition.__dict__, revision=revision.__dict__,
                le_source_path=le_path, le_expected_sha256=expected,
            )

            self.assertEqual(created["parameters"]["exit_diameter"], {"value": 25.4, "unit": "mm"})
            self.assertEqual(created["completeness"], "simulation_ready")
            self.assertTrue(created["le_network_hash"])
            self.assertTrue(source.exists())

            row = service.list_drivers()[0]
            revision_dialog = DriverRevisionEditorDialog(
                service=service, title="Revision", kind="compression_driver",
                definition=row, seed=row["latest_revision"],
            )
            revision_dialog.parameter_inputs["re"][0].setText("6.4")
            _, next_payload = revision_dialog.build_payload()
            next_revision = service.create_driver_revision("D-FORM-CD", **next_payload)
            self.assertEqual(next_revision["revision_number"], 2)
            self.assertEqual(next_revision["le_network_hash"], created["le_network_hash"])
            self.assertEqual(next_revision["parameters"]["re"], {"value": 6.4, "unit": "ohm"})
            dialog.close()
            revision_dialog.close()

    def test_cone_form_allows_missing_values_and_explicit_units(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_driver_form_cone_") as tmp:
            dialog = DriverRevisionEditorDialog(
                service=_service(Path(tmp)), title="Create", kind="cone_driver",
            )
            dialog.manufacturer.setText("Custom")
            dialog.model.setText("Mid 8")
            dialog.parameter_inputs["moving_mass"][0].setText("18.5")
            dialog.parameter_inputs["moving_mass"][1].setCurrentText("g")
            definition, revision = dialog.build_payload()

            self.assertEqual(definition["kind"], "cone_driver")
            self.assertEqual(revision["parameters"]["moving_mass"], {"value": 18.5, "unit": "g"})
            self.assertNotIn("qts", revision["parameters"])
            self.assertEqual(revision["completeness"], "incomplete")
            self.assertIn("cannot simulate", dialog.completeness.text())
            dialog.close()

    def test_builtin_driver_revision_controls_are_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_driver_form_builtin_") as tmp:
            root = Path(tmp)
            service = _service(root)
            source = root / "generic25.txt"
            source.write_text("System 'S1'\nDriver 'D1'\n", encoding="utf-8")
            service.driver_library.seed_generic25(source)
            dialog = DriverLibraryDialog(service)

            self.assertEqual(dialog.selected_driver_id(), "generic25")
            self.assertFalse(dialog.new_revision.isEnabled())
            self.assertFalse(dialog.archive.isEnabled())
            self.assertIn("built-in/read-only", dialog.list.currentItem().text())
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
            dialog.default_driver.setCurrentIndex(dialog.default_driver.findData("DR-UI-1"))
            self.assertIn("Incomplete", dialog.driver_status.text())
            dialog.close()

            window = MainWindow(service)
            window.load_project(project)
            self.assertIn("DR-UI-1", window.batch_page.execution_context_label.text())
            self.assertIn(first["revision_hash"][:12], window.batch_page.execution_context_label.text())
            window.close()


if __name__ == "__main__":
    unittest.main()
