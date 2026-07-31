from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import SettingsDialog
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QTabWidget
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QComboBox = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]
    QTabWidget = None  # type: ignore[assignment]


def _build_service(tmp_root: Path) -> OrchestratorService:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / "library"
    library_root.mkdir(parents=True, exist_ok=True)
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store)


@unittest.skipIf(QApplication is None, "PySide6 is required")
class SettingsAnalyzerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_has_analyzer_tab_with_data_source_combo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_settings_analyzer_tab_") as tmp:
            service = _build_service(Path(tmp))
            dialog = SettingsDialog(service)
            tabs = dialog.findChild(QTabWidget, "SettingsTabs")
            source_combo = dialog.findChild(QComboBox, "AnalyzerDataSourceSettingsCombo")
            self.assertIsNotNone(tabs)
            self.assertIsNotNone(source_combo)
            assert tabs is not None and source_combo is not None
            tab_titles = [tabs.tabText(index) for index in range(tabs.count())]
            self.assertIn("Analyzer", tab_titles)
            self.assertIn(str(source_combo.currentData() or ""), {"project", "global"})

    def test_analyzer_data_source_saves_to_user_settings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_settings_analyzer_save_") as tmp:
            service = _build_service(Path(tmp))
            dialog = SettingsDialog(service)
            source_combo = dialog.findChild(QComboBox, "AnalyzerDataSourceSettingsCombo")
            self.assertIsNotNone(source_combo)
            assert source_combo is not None
            for index in range(source_combo.count()):
                if str(source_combo.itemData(index) or "") == "global":
                    source_combo.setCurrentIndex(index)
                    break
            with patch.object(dialog, "accept", autospec=True) as accept_mock:
                dialog._save()
                self.assertEqual(accept_mock.call_count, 1)
            self.assertEqual(str(service.settings.analyzer_data_source), "global")

    def test_settings_exposes_license_aware_tool_setup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_settings_setup_ui_") as tmp:
            dialog = SettingsDialog(_build_service(Path(tmp)))
            detect_button = dialog.findChild(QPushButton, "SetupDetectToolsButton")
            self.assertIsNotNone(detect_button)
            self.assertTrue(str(dialog.setup_status_label.text() or "").strip())
            self.assertIn("ATH download", str(dialog.setup_ath_link_btn.text()))
            self.assertIn("AKABAK download", str(dialog.setup_akabak_link_btn.text()))
            self.assertIn("VACS download", str(dialog.setup_vacs_link_btn.text()))
            self.assertIn("winget", str(dialog.setup_gmsh_install_btn.text()).lower())


if __name__ == "__main__":
    unittest.main()
