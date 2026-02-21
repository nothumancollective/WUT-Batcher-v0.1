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
        self.assertEqual(page.save_btn.parent(), page.run_btn.parent())
        self.assertEqual(page.batch_name.parent(), page.run_btn.parent())
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


if __name__ == "__main__":
    unittest.main()
