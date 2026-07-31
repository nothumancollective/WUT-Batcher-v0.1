from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.ui_automation.session import UiaSession, WindowInfo


class UiaAutomationSessionTests(unittest.TestCase):
    def test_pywinauto_start_does_not_perform_unbounded_desktop_warmup(self) -> None:
        class FakeApplication:
            process = 4321

            def __init__(self, *, backend: str) -> None:
                self.backend = backend

            def start(self, executable: str, *, timeout: int):
                self.executable = executable
                self.timeout = timeout
                return self

        class ForbiddenDesktop:
            def __init__(self, **_: object) -> None:
                raise AssertionError("Desktop enumeration must not run during session startup")

        with tempfile.TemporaryDirectory() as tmp_dir:
            executable = Path(tmp_dir) / "AKABAK.exe"
            executable.write_bytes(b"stub")
            session = UiaSession(
                executable=executable,
                app_name="akabak",
                startup_timeout_s=7,
                prefer_start=True,
            )
            session._import_pywinauto = lambda: (FakeApplication, ForbiddenDesktop, RuntimeError)  # type: ignore[method-assign]
            process = SimpleNamespace(pid=4321)

            with patch("app.ui_automation.session.subprocess.Popen", return_value=process) as popen:
                connected = session._connect_or_start_pywinauto()

            self.assertTrue(connected)
            self.assertEqual(session.process_id, 4321)
            self.assertEqual(session.backend, "pywinauto-uia")
            self.assertTrue(session.started_process)
            popen.assert_called_once_with([str(executable)], close_fds=True)

    def test_windows_find_uses_native_lookup_without_desktop_enumeration(self) -> None:
        session = UiaSession(
            executable=r"C:\Tools\AKABAK\AKABAK.exe",
            app_name="akabak",
        )
        session.backend = "pywinauto-uia"
        session.process_id = 4321
        calls = []
        session._find_window_pywinauto_native = lambda **kwargs: calls.append(kwargs) or "main-window"  # type: ignore[method-assign]

        found = session.find_window(title_regex=r"AKABAK", class_name_regex=r"TForm_Main")

        self.assertEqual(found, "main-window")
        self.assertEqual(
            calls,
            [{"title_regex": r"AKABAK", "class_name_regex": r"TForm_Main"}],
        )

    def test_find_window_filters_native_rows_before_wrapping_exact_handle(self) -> None:
        session = UiaSession(executable=r"C:\Tools\AKABAK\AKABAK.exe", app_name="akabak")
        session.backend = "pywinauto-uia"
        session.process_id = 77
        session._native_top_level_window_rows = lambda: [  # type: ignore[method-assign]
            WindowInfo("Helper", "TPUtilWindow", 77, "akabak.exe", "native_hwnd", "Window", "", 101),
            WindowInfo("AKABAK", "TForm_Main", 77, "akabak.exe", "native_hwnd", "Window", "", 202),
        ]
        desktop = Mock()
        desktop.window.return_value = "main-window"
        desktop.windows.side_effect = AssertionError("global UIA enumeration must not run")
        session._import_pywinauto = lambda: (Mock(), lambda **_: desktop, RuntimeError)  # type: ignore[method-assign]

        window = session.find_window(title_regex=r"AKABAK", class_name_regex=r"TForm_Main")

        self.assertEqual(window, "main-window")
        desktop.window.assert_called_once_with(handle=202)
        desktop.windows.assert_not_called()


if __name__ == "__main__":
    unittest.main()
