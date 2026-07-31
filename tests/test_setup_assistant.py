from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.settings_store import SettingsStore, UserSettings
from app.setup_assistant import (
    autoconfigure_detected_tools,
    discover_tool_path,
    install_gmsh_with_winget,
    inspect_setup,
)


class SetupAssistantTests(unittest.TestCase):
    def test_valid_configured_path_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            exe = Path(tmp_dir) / "ath.exe"
            exe.write_bytes(b"stub")
            resolved, source = discover_tool_path("ath", configured_path=str(exe))
            self.assertEqual(resolved, str(exe.resolve()))
            self.assertEqual(source, "configured")

    def test_gmsh_is_discovered_next_to_ath(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ath = root / "ath.exe"
            gmsh = root / "gmsh.exe"
            ath.write_bytes(b"ath")
            gmsh.write_bytes(b"gmsh")
            with patch("app.setup_assistant.shutil.which", return_value=None):
                resolved, source = discover_tool_path("gmsh", ath_executable=str(ath))
            self.assertEqual(resolved, str(gmsh.resolve()))
            self.assertEqual(source, "ath_sibling")

    def test_autoconfigure_does_not_overwrite_valid_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            configured = root / "configured_ath.exe"
            detected = root / "detected_ath.exe"
            configured.write_bytes(b"configured")
            detected.write_bytes(b"detected")
            store = SettingsStore(root / "config.json")
            store.save(UserSettings(library_root=str(root / "library"), ath_exe=str(configured)))
            inspection = inspect_setup(store.load())
            ath_status = next(tool for tool in inspection.tools if tool.key == "ath")
            self.assertEqual(ath_status.path, str(configured.resolve()))

            with patch("app.setup_assistant.discover_tool_path") as discover:
                discover.side_effect = [
                    (str(detected), "known_location"),
                    (None, "missing"),
                    (None, "missing"),
                    (None, "missing"),
                    (str(detected), "known_location"),
                    (None, "missing"),
                    (None, "missing"),
                    (None, "missing"),
                ]
                result = autoconfigure_detected_tools(store)
            self.assertFalse(result["changed"])
            self.assertEqual(store.load().ath_exe, str(configured))

    def test_install_requires_confirmation_without_running_winget(self) -> None:
        with patch("app.setup_assistant.discover_tool_path", return_value=(None, "missing")):
            with patch("app.setup_assistant.subprocess.run") as run:
                result = install_gmsh_with_winget(confirmed=False)
            self.assertEqual(result["status"], "confirmation_required")
            run.assert_not_called()

    def test_install_skips_when_gmsh_exists(self) -> None:
        with patch("app.setup_assistant.discover_tool_path", return_value=(r"C:\Tools\gmsh.exe", "path")):
            with patch("app.setup_assistant.subprocess.run") as run:
                result = install_gmsh_with_winget(confirmed=True)
            self.assertEqual(result["status"], "already_installed")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
