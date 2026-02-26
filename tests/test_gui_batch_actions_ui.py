from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import BatchPage, MainWindow
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtWidgets import QApplication, QFrame, QPushButton
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QFrame = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]


def _build_service(tmp_root: Path) -> OrchestratorService:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / "library"
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store)


@unittest.skipIf(QApplication is None, "PySide6 is required")
class BatchActionsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_legacy_bottom_bar_controls_are_removed(self) -> None:
        page = BatchPage()
        labels = [str(button.text()) for button in page.findChildren(QPushButton)]
        self.assertIn("Save Batch", labels)
        self.assertIn("Run Batch", labels)
        self.assertNotIn("Project Manager", labels)
        self.assertNotIn("Back to Dashboard", labels)
        self.assertIsNotNone(page.command_header)
        self.assertEqual(page.command_header.objectName(), "CommandHeaderWidget")
        legacy_bar = page.findChildren(QFrame, "BatchActionBar")
        self.assertEqual(legacy_bar, [])

    def test_save_run_buttons_emit_batch_payload_signals(self) -> None:
        page = BatchPage()
        page.batch_name.setText("UI-1B-Check")
        seen: dict[str, dict] = {}
        page.save_batch.connect(lambda payload: seen.setdefault("save", dict(payload)))
        page.run_batch.connect(lambda payload: seen.setdefault("run", dict(payload)))

        page.save_btn.click()
        page.run_btn.click()

        self.assertIn("save", seen)
        self.assertIn("run", seen)
        self.assertEqual(str(seen["save"].get("batch_name")), "UI-1B-Check")
        self.assertEqual(str(seen["run"].get("batch_name")), "UI-1B-Check")

    def test_mainwindow_keeps_existing_save_run_handler_wiring(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui1b_batch_actions_") as tmp:
            service = _build_service(Path(tmp))
            with patch.object(MainWindow, "_save_batch", autospec=True, return_value=None) as save_mock, patch.object(
                MainWindow, "_run_batch", autospec=True
            ) as run_mock:
                window = MainWindow(service)
                window.show_batch()
                window.batch_page.batch_name.setText("UI-1B-Wiring")

                window.batch_page.save_btn.click()
                window.batch_page.run_btn.click()

                self.assertEqual(save_mock.call_count, 1)
                self.assertEqual(run_mock.call_count, 1)
                save_args = save_mock.call_args.args
                run_args = run_mock.call_args.args
                self.assertGreaterEqual(len(save_args), 2)
                self.assertGreaterEqual(len(run_args), 2)
                self.assertEqual(str(save_args[1].get("batch_name")), "UI-1B-Wiring")
                self.assertEqual(str(run_args[1].get("batch_name")), "UI-1B-Wiring")
                window.close()

    def test_command_header_issues_chip_survives_repeated_runtime_updates(self) -> None:
        page = BatchPage()
        page.batch_name.setText("Runtime-Header-Rebuild")
        self.app.processEvents()

        page.set_eta(None, sample_count=0, median_seconds=None)
        self.app.processEvents()
        page.apply_ui_risks(
            [
                {
                    "severity": "warn",
                    "field_key": "Length",
                    "message": "Runtime warning for header rebuild.",
                }
            ]
        )
        self.app.processEvents()
        page.set_project_fixed_keys(["Length"])
        self.app.processEvents()
        page.set_eta(75.0, sample_count=3, median_seconds=22.5)
        self.app.processEvents()

        issue_chip = page.command_header.issues_chip
        self.assertEqual(issue_chip.objectName(), "CommandIssuesChip")
        self.assertTrue(bool(issue_chip.text().strip()))
        self.assertIn("warning", issue_chip.toolTip().lower())

    def test_clone_save_persists_clone_lineage_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui_lineage_clone_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Clone lineage", {"fixed_params": {"Length": 120}, "limits": {}})
            parent = service.create_batch(
                project_id=project.project_id,
                batch_name="Parent Batch",
                selected_params={"Throat.Diameter": 30.0},
                sweeps={},
                sweep_mode="single",
                sim_export_params={},
            )
            window = MainWindow(service)
            window.load_project(project)
            window._clone_batch(parent.batch_id)
            payload = window.batch_page._payload(include_name=True)
            created_batch_id = window._save_batch(dict(payload), for_run=False)
            self.assertIsNotNone(created_batch_id)
            assert created_batch_id is not None
            lineage_rows = service.list_batch_lineage(project_id=project.project_id)
            lineage_by_batch = {str(row.get("batch_id") or ""): row for row in lineage_rows}
            self.assertIn(created_batch_id, lineage_by_batch)
            self.assertEqual(str(lineage_by_batch[created_batch_id]["created_via"]), "clone")
            self.assertEqual(str(lineage_by_batch[created_batch_id]["parent_batch_id"]), str(parent.batch_id))
            self.assertIsNone(lineage_by_batch[created_batch_id]["created_from_version_id"])
            window.close()


if __name__ == "__main__":
    unittest.main()
