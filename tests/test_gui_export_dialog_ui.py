from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import ExportDialog, MainWindow
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
except ImportError:  # pragma: no cover
    QSize = None  # type: ignore[assignment]
    QApplication = None  # type: ignore[assignment]
    QDialog = None  # type: ignore[assignment]
    QFileDialog = None  # type: ignore[assignment]
    QMessageBox = None  # type: ignore[assignment]


def _build_service(tmp_root: Path) -> OrchestratorService:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / "library"
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store)


@unittest.skipIf(
    QApplication is None or QDialog is None or QFileDialog is None or QMessageBox is None or QSize is None,
    "PySide6 is required",
)
class ExportDialogUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_export_dialog_click_opens_safe_folder_picker_and_accepts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_export_dialog_pick_") as tmp:
            root = Path(tmp)
            target = root / "picked_export"
            target.mkdir(parents=True, exist_ok=True)
            dialog = ExportDialog({"B001": ["V001"]})

            class _FakeDialog:
                Directory = QFileDialog.Directory
                DontUseNativeDialog = QFileDialog.DontUseNativeDialog
                ShowDirsOnly = QFileDialog.ShowDirsOnly
                Detail = QFileDialog.Detail
                Accept = QFileDialog.Accept
                Reject = QFileDialog.Reject
                last_instance = None

                def __init__(self, *_args, **_kwargs) -> None:
                    self.options: list[tuple[object, bool]] = []
                    _FakeDialog.last_instance = self

                def setObjectName(self, _name: str) -> None:
                    return None

                def setModal(self, _on: bool) -> None:
                    return None

                def setWindowFlag(self, *_args, **_kwargs) -> None:
                    return None

                def setViewMode(self, _mode) -> None:
                    return None

                def setFileMode(self, _mode) -> None:
                    return None

                def setOption(self, option, on: bool = True) -> None:
                    self.options.append((option, bool(on)))

                def setDirectory(self, _directory: str) -> None:
                    return None

                def setLabelText(self, *_args, **_kwargs) -> None:
                    return None

                def layout(self):
                    return None

                def adjustSize(self) -> None:
                    return None

                def sizeHint(self) -> QSize:
                    return QSize(800, 520)

                def width(self) -> int:
                    return 0

                def height(self) -> int:
                    return 0

                def resize(self, *_args) -> None:
                    return None

                def exec(self) -> int:
                    return int(QDialog.Accepted)

                def selectedFiles(self) -> list[str]:
                    return [str(target)]

            with patch("app.gui.QFileDialog", _FakeDialog), patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok) as critical_mock:
                dialog.export_btn.click()

            self.assertTrue(bool(dialog.property("framelessShell")))
            self.assertEqual(dialog.result(), int(QDialog.Accepted))
            self.assertEqual(str(dialog.payload().get("destination_dir") or ""), str(target))
            self.assertEqual(critical_mock.call_count, 0)
            self.assertIsNotNone(_FakeDialog.last_instance)
            assert _FakeDialog.last_instance is not None
            self.assertIn((_FakeDialog.DontUseNativeDialog, True), _FakeDialog.last_instance.options)

    def test_export_dialog_cancelled_picker_keeps_popup_open(self) -> None:
        dialog = ExportDialog({"B001": ["V001"]})

        class _FakeDialog:
            Directory = QFileDialog.Directory
            DontUseNativeDialog = QFileDialog.DontUseNativeDialog
            ShowDirsOnly = QFileDialog.ShowDirsOnly
            Detail = QFileDialog.Detail
            Accept = QFileDialog.Accept
            Reject = QFileDialog.Reject

            def __init__(self, *_args, **_kwargs) -> None:
                return None

            def setObjectName(self, _name: str) -> None:
                return None

            def setModal(self, _on: bool) -> None:
                return None

            def setWindowFlag(self, *_args, **_kwargs) -> None:
                return None

            def setViewMode(self, _mode) -> None:
                return None

            def setFileMode(self, _mode) -> None:
                return None

            def setOption(self, *_args, **_kwargs) -> None:
                return None

            def setDirectory(self, _directory: str) -> None:
                return None

            def setLabelText(self, *_args, **_kwargs) -> None:
                return None

            def layout(self):
                return None

            def adjustSize(self) -> None:
                return None

            def sizeHint(self) -> QSize:
                return QSize(800, 520)

            def width(self) -> int:
                return 0

            def height(self) -> int:
                return 0

            def resize(self, *_args) -> None:
                return None

            def exec(self) -> int:
                return int(QDialog.Rejected)

            def selectedFiles(self) -> list[str]:
                return []

        with patch("app.gui.QFileDialog", _FakeDialog), patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok) as critical_mock:
            dialog.export_btn.click()

        self.assertEqual(dialog.result(), 0)
        self.assertEqual(str(dialog.payload().get("destination_dir") or ""), "")
        self.assertEqual(critical_mock.call_count, 0)

    def test_export_version_copies_generated_bundle_to_selected_destination(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_export_copy_") as tmp:
            root = Path(tmp)
            service = _build_service(root)
            project = service.create_project("Export Copy", {"fixed_params": {"Length": 120.0}, "limits": {}})
            window = MainWindow(service)
            window.current_project = project
            source_dir = root / "generated_export"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "mesh.stl").write_text("solid test\nendsolid test\n", encoding="utf-8")
            logs_dir = source_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "ath.stdout.log").write_text("ok\n", encoding="utf-8")
            destination = root / "chosen_export"
            destination.mkdir(parents=True, exist_ok=True)

            with patch.object(
                service,
                "export_version",
                return_value={"export_dir": str(source_dir), "version_id": "V001", "exported_stl": [str(source_dir / "mesh.stl")]},
            ) as export_mock:
                window._export_version("B001", "V001", True, False, str(destination))

            self.assertEqual(export_mock.call_count, 1)
            self.assertTrue((destination / "mesh.stl").exists())
            self.assertTrue((destination / "logs" / "ath.stdout.log").exists())
            window.close()

    def test_export_version_failure_shows_message_box(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_export_fail_") as tmp:
            root = Path(tmp)
            service = _build_service(root)
            project = service.create_project("Export Fail", {"fixed_params": {"Length": 120.0}, "limits": {}})
            window = MainWindow(service)
            window.current_project = project

            with patch.object(service, "export_version", side_effect=RuntimeError("boom")):
                with patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok) as critical_mock:
                    window._export_version("B001", "V001", True, False, str(root / "chosen_export"))

            self.assertEqual(critical_mock.call_count, 1)
            window.close()


if __name__ == "__main__":
    unittest.main()
