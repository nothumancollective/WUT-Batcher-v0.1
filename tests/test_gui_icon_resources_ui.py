from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

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
class IconResourcesUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_topbar_uses_resource_icons_and_expected_tooltips(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui1d1_icons_") as tmp:
            service = _build_service(Path(tmp))
            window = MainWindow(service)
            self.assertEqual(window.home_button.toolTip(), "Project Manager")
            self.assertEqual(window.settings_button.toolTip(), "Settings")
            self.assertFalse(window.home_button.icon().isNull())
            self.assertFalse(window.settings_button.icon().isNull())
            window.close()


if __name__ == "__main__":
    unittest.main()

