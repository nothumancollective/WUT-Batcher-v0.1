from __future__ import annotations

from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest.mock import patch

from app.vacs_driver import VacsDriver


class _FakeWindow:
    def __init__(self, *, class_name: str, title: str, handle: int, process_id: int) -> None:
        self.element_info = types.SimpleNamespace(
            class_name=class_name,
            name=title,
            handle=handle,
            process_id=process_id,
            control_type="Window",
            automation_id="",
        )
        self.keys: list[str] = []

    def set_focus(self) -> None:
        return None

    def type_keys(self, value: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.keys.append(str(value))


class _FakeSession:
    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.process_id = 4321
        self.backend = "pywinauto-uia"
        self.started_process = False
        self._main = _FakeWindow(class_name="TForm_DatMain", title="VACS", handle=1001, process_id=self.process_id)
        self._export = _FakeWindow(class_name="TForm_Export", title="Data Export", handle=1002, process_id=self.process_id)

    def connect_or_start(self) -> None:
        return None

    def find_window(self, *, title_regex: str, class_name_regex: str):  # type: ignore[no-untyped-def]
        if re.search("TForm_DatMain", str(class_name_regex)):
            return self._main
        if re.search("TForm_Export", str(class_name_regex)):
            return self._export
        return None

    def close(self) -> None:
        return None


class _FakeWatchdog:
    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    def run_watch(self, *, step_name: str, timeout_s: float):  # type: ignore[no-untyped-def]
        return []


class VacsDriverExportEnforcementTests(unittest.TestCase):
    def test_export_txt_runs_enforcement_hook_in_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output_path = root / "out.txt"
            output_path.write_text("Frequency [Hz];SPL [dB]\n100;90\n", encoding="utf-8")
            recipes = [
                {
                    "recipe_id": "r1",
                    "graph_type": "spl",
                    "required_settings": [],
                    "expected_output": {"file_pattern": r".*\.txt$"},
                }
            ]
            with patch("app.vacs_driver.UiaSession", _FakeSession):
                with patch("app.vacs_driver.ModalDialogWatchdog", _FakeWatchdog):
                    with patch("app.vacs_driver.load_vacs_export_recipes", return_value=recipes):
                        driver = VacsDriver(executable="C:\\fake\\vacs.exe", log_dir=root)
            driver.state = "graph_open"
            driver.current_graph = "spl"
            with patch("app.vacs_driver.enforce_export_dialog_controls", return_value={"ok": True, "controls": []}) as mocked:
                result = driver.export_txt(
                    {
                        "recipe_id": "r1",
                        "graph_type": "spl",
                        "output_file": str(output_path),
                    }
                )
            self.assertTrue(result.ok)
            self.assertEqual(result.details["output_file"], str(output_path))
            self.assertTrue(result.details["output_exists"])
            self.assertGreater(result.details["output_size"], 0)
            mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
