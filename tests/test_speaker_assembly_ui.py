from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.geometry_driver_ui import GeometryPage
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings
from app.speaker_assembly_ui import (
    AssemblyEditorDialog,
    AssemblyInstanceEditorDialog,
    SpeakerAssemblyManagerDialog,
)

try:
    from PySide6.QtWidgets import QApplication, QDialog
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QDialog = None  # type: ignore[assignment]


def _service(root: Path) -> OrchestratorService:
    store = SettingsStore(root / "settings.json")
    store.save(UserSettings(library_root=str(root / "library")))
    return OrchestratorService(store)


@unittest.skipIf(QApplication is None, "PySide6 is required")
class SpeakerAssemblyUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_editor_payloads_preserve_coaxial_transform_and_description(self) -> None:
        assembly = AssemblyEditorDialog(
            title="Edit",
            seed={"name": "Monitor pair", "description": "Reusable layout"},
        )
        self.assertEqual(
            assembly.payload(),
            {"name": "Monitor pair", "description": "Reusable layout"},
        )

        instance = AssemblyInstanceEditorDialog(
            title="Edit instance",
            geometries=[{"geometry_id": "G-1", "name": "HF", "role": "hf_horn"}],
            seed={
                "geometry_id": "G-1",
                "name": "Coax HF",
                "description": "Centered above LF",
                "arrangement": "coaxial",
                "transform": {
                    "translation_x_m": 0.0125,
                    "translation_y_m": -0.025,
                    "translation_z_m": 0.18,
                    "rotation_x_deg": 2.5,
                    "rotation_y_deg": -7.25,
                    "rotation_z_deg": 15.0,
                },
            },
        )
        payload = instance.payload()
        self.assertEqual(payload["geometry_id"], "G-1")
        self.assertEqual(payload["arrangement"], "coaxial")
        self.assertEqual(payload["description"], "Centered above LF")
        self.assertAlmostEqual(payload["transform"]["translation_z_m"], 0.18)
        self.assertAlmostEqual(payload["transform"]["rotation_y_deg"], -7.25)
        assembly.close()
        instance.close()

    def test_manager_service_path_round_trips_two_instances_and_reorders(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_assembly_ui_") as tmp:
            service = _service(Path(tmp))
            project = service.create_project("Assembly UI", {"fixed_params": {}, "limits": {}})
            geometries = service.list_geometries(project.project_id)
            first = geometries[0]
            second = service.create_geometry(
                project.project_id,
                name="Coaxial HF",
                role="hf_horn",
                description="Second reusable Geometry",
                ath_parameters={"Length": 175.0},
            )
            dialog = SpeakerAssemblyManagerDialog(service, project.project_id)
            created = dialog.create_assembly({"name": "Two-way", "description": "UI fixture"})
            dialog.add_instance({
                "geometry_id": first["geometry_id"],
                "name": "Main horn",
                "description": "Normal instance",
                "arrangement": "normal",
                "transform": {},
            })
            dialog.add_instance({
                "geometry_id": second["geometry_id"],
                "name": "Coaxial horn",
                "description": "Offset and rotated",
                "arrangement": "coaxial",
                "transform": {
                    "translation_x_m": 0.035,
                    "translation_y_m": -0.01,
                    "translation_z_m": 0.22,
                    "rotation_x_deg": 3.0,
                    "rotation_y_deg": -8.0,
                    "rotation_z_deg": 12.0,
                },
            })

            self.assertEqual(dialog.instance_list.count(), 2)
            self.assertIn("coaxial", dialog.instance_list.item(1).text())
            original_snapshot = service.get_speaker_assembly(
                project.project_id, created["assembly_id"],
            )["instances"][1]

            service.update_geometry(project.project_id, second["geometry_id"], name="Renamed source")
            reloaded = SpeakerAssemblyManagerDialog(service, project.project_id)
            reloaded.instance_list.setCurrentRow(1)
            reloaded.update_instance({
                "geometry_id": second["geometry_id"],
                "name": "Edited coaxial horn",
                "description": "Edited without refreshing snapshot",
                "arrangement": "coaxial",
                "transform": original_snapshot["transform"],
            })
            reloaded.move_instance(-1)
            persisted = service.get_speaker_assembly(project.project_id, created["assembly_id"])

            self.assertEqual([row["name"] for row in persisted["instances"]], ["Edited coaxial horn", "Main horn"])
            self.assertEqual(persisted["instances"][0]["geometry_snapshot_hash"], original_snapshot["geometry_snapshot_hash"])
            self.assertEqual(persisted["instances"][0]["geometry_snapshot"]["name"], "Coaxial HF")
            self.assertEqual(persisted["instances"][0]["order_index"], 0)
            self.assertEqual(persisted["instances"][1]["order_index"], 1)
            dialog.close()
            reloaded.close()

    def test_geometry_page_exposes_single_assembly_management_entry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_assembly_navigation_") as tmp:
            service = _service(Path(tmp))
            project = service.create_project("Assembly navigation", {"fixed_params": {}, "limits": {}})
            page = GeometryPage(service)
            page.set_project(project.project_id)
            page.resize(680, 500)
            page.show()
            QApplication.processEvents()

            self.assertEqual(page.assemblies_button.text(), "Speaker Assemblies")
            self.assertTrue(page.assemblies_button.isVisible())
            self.assertTrue(page.assemblies_button.isEnabled())
            with patch("app.geometry_driver_ui.SpeakerAssemblyManagerDialog") as manager:
                page.assemblies_button.click()
            manager.assert_called_once_with(service, project.project_id, page)
            manager.return_value.exec.assert_called_once_with()
            page.close()

    def test_manager_small_window_keeps_keyboard_reachable_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_assembly_small_ui_") as tmp:
            service = _service(Path(tmp))
            project = service.create_project("Small Assembly UI", {"fixed_params": {}, "limits": {}})
            dialog = SpeakerAssemblyManagerDialog(service, project.project_id)
            dialog.create_assembly({"name": "Compact", "description": "Long text " * 30})
            dialog.resize(680, 500)
            dialog.show()
            QApplication.processEvents()

            self.assertGreaterEqual(dialog.width(), 680)
            self.assertGreaterEqual(dialog.height(), 500)
            self.assertTrue(dialog.add_instance_button.isVisible())
            self.assertTrue(dialog.add_instance_button.isEnabled())
            dialog.add_instance_button.setFocus()
            self.assertTrue(dialog.add_instance_button.hasFocus())
            dialog.close()
