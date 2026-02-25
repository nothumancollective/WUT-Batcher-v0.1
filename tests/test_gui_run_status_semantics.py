from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import MainWindow
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
class GuiRunStatusSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_finished_handler_marks_failure_when_runtime_status_failed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_gui_run_status_failed_") as tmp:
            window = MainWindow(_build_service(Path(tmp)))
            with patch.object(window, "refresh_dashboard"), patch.object(window, "_exit_run_presentation"):
                window._on_batch_run_finished(
                    "B001",
                    {"run_status": "failed", "versions": ["V001"], "dry_run": False},
                )
            self.assertTrue(str(window.status_message.text()).startswith("Run failed for B001"))
            self.assertEqual(str(window.run_page.mode_label.text()), "Mode: failed")
            self.assertEqual(str(window.run_page.progress.format()), "Run failed")
            window.close()

    def test_finished_handler_marks_noop_when_runtime_status_noop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_gui_run_status_noop_") as tmp:
            window = MainWindow(_build_service(Path(tmp)))
            with patch.object(window, "refresh_dashboard"), patch.object(window, "_exit_run_presentation"):
                window._on_batch_run_finished(
                    "B001",
                    {"run_status": "noop", "versions": [], "dry_run": False},
                )
            self.assertTrue(str(window.status_message.text()).startswith("Nothing to run for B001"))
            self.assertEqual(str(window.run_page.mode_label.text()), "Mode: no-op")
            self.assertEqual(str(window.run_page.progress.format()), "Nothing to run")
            window.close()

    def test_finished_handler_marks_success_when_runtime_status_succeeded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_gui_run_status_success_") as tmp:
            window = MainWindow(_build_service(Path(tmp)))
            with patch.object(window, "refresh_dashboard"), patch.object(window, "_exit_run_presentation"):
                window._on_batch_run_finished(
                    "B001",
                    {"run_status": "succeeded", "versions": ["V001"], "dry_run": False},
                )
            self.assertTrue(str(window.status_message.text()).startswith("Run finished for B001"))
            self.assertEqual(str(window.run_page.mode_label.text()), "Mode: real")
            self.assertEqual(str(window.run_page.progress.format()), "Run complete")
            window.close()


if __name__ == "__main__":
    unittest.main()
