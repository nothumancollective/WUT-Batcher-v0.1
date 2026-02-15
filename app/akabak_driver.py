"""Deterministic AKABAK UIA driver (pywinauto primary, no pixel scanning)."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from app.ui_automation.session import UiaSession, UiaSessionError
from app.ui_automation.step_logger import StructuredStepLogger
from app.ui_automation.waits import wait_until
from app.ui_automation.watchdog import ModalDialogWatchdog
from app.ui_contracts.window_signatures import (
    AKABAK_INTERPRETER_WINDOW,
    AKABAK_MAIN_WINDOW,
    AKABAK_OPEN_FILE_DIALOG,
    AKABAK_SOLVE_PROGRESS,
)


WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
SMTO_ABORTIFHUNG = 0x0002
VK_SPACE = 0x20
IDOK = 1
OPEN_FILE_NAME_CONTROL_ID = 1148
IMPORT_ABEC_COMMAND_ID = 113


@dataclass(frozen=True)
class AkabakDriverResult:
    ok: bool
    status: str
    details: Dict[str, Any]


class AkabakDriver:
    def __init__(
        self,
        *,
        executable: str | Path,
        log_dir: str | Path,
        startup_timeout_s: int = 20,
        step_timeout_s: int = 90,
    ) -> None:
        self.executable = str(executable)
        self.log_dir = Path(log_dir)
        self.step_timeout_s = max(1, int(step_timeout_s))
        self.state = "init"
        self.current_project: Optional[str] = None
        self.session = UiaSession(
            executable=self.executable,
            app_name="akabak",
            startup_timeout_s=startup_timeout_s,
            allow_fallback=True,
            prefer_start=True,
        )
        self.logger = StructuredStepLogger(self.log_dir / "akabak_driver.log.jsonl")
        self.watchdog: Optional[ModalDialogWatchdog] = None

    def _log(self, *, level: str, step: str, event: str, payload: Dict[str, Any]) -> None:
        self.logger.write(level=level, step=step, event=event, payload=payload)

    def _require(self, condition: bool, message: str, step: str) -> None:
        if condition:
            return
        self._log(level="error", step=step, event="precondition_failed", payload={"message": message})
        raise RuntimeError(message)

    def _user32(self):
        return ctypes.windll.user32

    def _window_handle(self, window: Any) -> int:
        try:
            return int(getattr(window.element_info, "handle", 0) or 0)
        except Exception:
            return 0

    def _child_windows(
        self,
        parent_window: Any,
        *,
        class_name_regex: Optional[str] = None,
        title_regex: Optional[str] = None,
    ) -> List[Any]:
        rows: List[Any] = []
        try:
            children = list(parent_window.children(control_type="Window"))
        except Exception:
            children = []
        for child in children:
            try:
                info = child.element_info
                title = str(getattr(info, "name", "") or "")
                class_name = str(getattr(info, "class_name", "") or "")
            except Exception:
                continue
            if class_name_regex and not re.search(class_name_regex, class_name, re.IGNORECASE):
                continue
            if title_regex and not re.search(title_regex, title, re.IGNORECASE):
                continue
            rows.append(child)
        return rows

    def _send_key_space(self, hwnd: int) -> None:
        if hwnd <= 0:
            return
        user32 = self._user32()
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_SPACE, 0)
        user32.PostMessageW(hwnd, WM_KEYUP, VK_SPACE, 0)

    def _dismiss_startup_windows(self, *, main_window: Any, step: str) -> None:
        startup_windows = self._child_windows(
            main_window,
            class_name_regex=r"TForm_ExampleFiles",
        )
        if not startup_windows:
            return
        user32 = self._user32()
        for popup in startup_windows:
            hwnd = self._window_handle(popup)
            if hwnd <= 0:
                continue
            user32.SendMessageW(hwnd, WM_CLOSE, 0, 0)
            self._log(
                level="info",
                step=step,
                event="startup_modal_closed",
                payload={"class_name": "TForm_ExampleFiles", "handle": hwnd},
            )
        wait_until(
            predicate=lambda: (
                len(self._child_windows(main_window, class_name_regex=r"TForm_ExampleFiles")) == 0,
                None,
            ),
            timeout_s=6.0,
        )

    def _find_interpreter_window(self, *, main_window: Any) -> Optional[Any]:
        matches = self._child_windows(
            main_window,
            class_name_regex=AKABAK_INTERPRETER_WINDOW.class_name_regex,
            title_regex=AKABAK_INTERPRETER_WINDOW.title_regex,
        )
        if matches:
            return matches[0]
        return None

    def _find_open_file_dialog(self, *, main_window: Any) -> Optional[Any]:
        matches = self._child_windows(
            main_window,
            class_name_regex=AKABAK_OPEN_FILE_DIALOG.class_name_regex,
            title_regex=AKABAK_OPEN_FILE_DIALOG.title_regex,
        )
        if matches:
            return matches[0]
        return None

    def _send_import_command(self, *, main_window: Any, step: str) -> None:
        hwnd = self._window_handle(main_window)
        self._require(hwnd > 0, "AKABAK main window handle unavailable.", step)
        user32 = self._user32()
        result = ctypes.c_ulong()
        ok = user32.SendMessageTimeoutW(
            hwnd,
            WM_COMMAND,
            IMPORT_ABEC_COMMAND_ID,
            0,
            SMTO_ABORTIFHUNG,
            1000,
            ctypes.byref(result),
        )
        self._require(bool(ok), "Failed to trigger Import ABEC command.", step)
        self._log(
            level="info",
            step=step,
            event="import_command_sent",
            payload={"command_id": IMPORT_ABEC_COMMAND_ID, "result": int(result.value)},
        )

    def _trigger_interpreter_open_button(self, *, interpreter_window: Any, step: str) -> None:
        target = None
        try:
            for control in interpreter_window.descendants():
                title = str(control.window_text() or "").strip()
                if re.search(r"open\s+abec\s+project", title, re.IGNORECASE):
                    target = control
                    break
        except Exception:
            target = None
        self._require(target is not None, "Interpreter button 'Open ABEC Project' not found.", step)
        handle = self._window_handle(target)
        self._require(handle > 0, "Interpreter open button handle unavailable.", step)
        self._send_key_space(handle)
        self._log(
            level="info",
            step=step,
            event="interpreter_open_button_triggered",
            payload={"handle": handle},
        )

    def _submit_open_file_dialog(
        self,
        *,
        main_window: Any,
        file_dialog: Any,
        project_path: str,
        step: str,
    ) -> None:
        user32 = self._user32()
        dialog_handle = self._window_handle(file_dialog)
        self._require(dialog_handle > 0, "Open-file dialog handle unavailable.", step)

        set_ok = bool(user32.SetDlgItemTextW(dialog_handle, OPEN_FILE_NAME_CONTROL_ID, str(project_path)))
        self._require(set_ok, "Unable to write project path into open-file dialog.", step)
        readback = ctypes.create_unicode_buffer(2048)
        user32.GetDlgItemTextW(dialog_handle, OPEN_FILE_NAME_CONTROL_ID, readback, 2047)
        self._log(
            level="info",
            step=step,
            event="dialog_filename_set",
            payload={"path": project_path, "readback": readback.value},
        )

        open_button_handle = int(user32.GetDlgItem(dialog_handle, IDOK) or 0)
        if open_button_handle > 0:
            self._send_key_space(open_button_handle)
        user32.PostMessageW(dialog_handle, WM_COMMAND, IDOK, open_button_handle)

        def _dialog_closed():
            dialog = self._find_open_file_dialog(main_window=main_window)
            return (dialog is None, None)

        try:
            wait_until(predicate=_dialog_closed, timeout_s=6.0)
        except TimeoutError as exc:
            raise RuntimeError(
                "ABEC open-file dialog did not close after non-visual confirmation attempts."
            ) from exc

    def _connect(self) -> None:
        if self.state != "init":
            return
        step = "connect"
        self._log(level="info", step=step, event="start", payload={"executable": self.executable})
        self.session.connect_or_start()
        self.watchdog = ModalDialogWatchdog(
            process_id=self.session.process_id,
            output_dir=self.log_dir / "watchdog",
            capture_screenshot=False,
            global_timeout_s=300,
        )
        main_window = self.session.find_window(
            title_regex=AKABAK_MAIN_WINDOW.title_regex,
            class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
        )
        self._require(main_window is not None, "AKABAK main window was not found.", step)
        self.state = "ready"
        self._log(
            level="info",
            step=step,
            event="connected",
            payload={"process_id": self.session.process_id, "backend": self.session.backend},
        )

    def open_project(self, abec_project_path: str | Path) -> AkabakDriverResult:
        step = "open_project"
        project_path = str(Path(abec_project_path).resolve())
        self._connect()
        if self.state in {"project_open", "running", "completed"} and self.current_project == project_path:
            self._log(level="info", step=step, event="idempotent_skip", payload={"project": project_path})
            return AkabakDriverResult(ok=True, status=self.state, details={"project": project_path, "idempotent": True})

        self._require(Path(project_path).exists(), f"ABEC project file not found: {project_path}", step)
        main_window = self.session.find_window(
            title_regex=AKABAK_MAIN_WINDOW.title_regex,
            class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
        )
        self._require(main_window is not None, "AKABAK main window is unavailable.", step)
        self._dismiss_startup_windows(main_window=main_window, step=step)

        self._log(level="info", step=step, event="action_open_shortcut", payload={"project": project_path})
        try:
            main_window.set_focus()
            self._send_import_command(main_window=main_window, step=step)
            interpreter = wait_until(
                predicate=lambda: (
                    self._find_interpreter_window(main_window=main_window) is not None,
                    self._find_interpreter_window(main_window=main_window),
                ),
                timeout_s=min(float(self.step_timeout_s), 8.0),
            )
            self._trigger_interpreter_open_button(interpreter_window=interpreter, step=step)
            file_dialog = wait_until(
                predicate=lambda: (
                    self._find_open_file_dialog(main_window=main_window) is not None,
                    self._find_open_file_dialog(main_window=main_window),
                ),
                timeout_s=min(float(self.step_timeout_s), 8.0),
            )
            self._submit_open_file_dialog(
                main_window=main_window,
                file_dialog=file_dialog,
                project_path=project_path,
                step=step,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to open project in AKABAK: {exc!r}") from exc

        if self.watchdog:
            handled = self.watchdog.run_watch(step_name=step, timeout_s=5)
            if handled:
                self._log(level="info", step=step, event="watchdog_handled", payload={"count": len(handled)})

        self.current_project = project_path
        self.state = "project_open"
        self._log(level="info", step=step, event="postcondition_ok", payload={"state": self.state})
        return AkabakDriverResult(ok=True, status=self.state, details={"project": project_path})

    def import_if_needed(self) -> AkabakDriverResult:
        step = "import_if_needed"
        self._connect()
        self._require(self.state in {"project_open", "running", "completed"}, "Project must be open first.", step)
        main_window = self.session.find_window(
            title_regex=AKABAK_MAIN_WINDOW.title_regex,
            class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
        )
        self._require(main_window is not None, "AKABAK main window is unavailable.", step)
        interpreter = self._find_interpreter_window(main_window=main_window)
        if interpreter is None:
            self._log(level="info", step=step, event="idempotent_noop", payload={"state": self.state})
            return AkabakDriverResult(ok=True, status=self.state, details={"import_needed": False})
        target = None
        try:
            for control in interpreter.descendants():
                title = str(control.window_text() or "").strip()
                if re.search(r"start\s+importing", title, re.IGNORECASE):
                    target = control
                    break
        except Exception:
            target = None
        self._require(target is not None, "Interpreter 'Start Importing' button not found.", step)
        handle = self._window_handle(target)
        self._require(handle > 0, "Interpreter start-importing button handle unavailable.", step)
        self._send_key_space(handle)
        wait_until(
            predicate=lambda: (
                self._find_interpreter_window(main_window=main_window) is None,
                None,
            ),
            timeout_s=min(float(self.step_timeout_s), 20.0),
        )
        self._log(level="info", step=step, event="import_triggered", payload={"button_handle": handle})
        return AkabakDriverResult(ok=True, status=self.state, details={"import_needed": False})

    def run_solve(self) -> AkabakDriverResult:
        step = "run_solve"
        self._connect()
        self._require(self.state in {"project_open", "completed"}, "Project must be open before solve.", step)
        main_window = self.session.find_window(
            title_regex=AKABAK_MAIN_WINDOW.title_regex,
            class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
        )
        self._require(main_window is not None, "AKABAK main window is unavailable.", step)
        try:
            main_window.set_focus()
            main_window.type_keys("{F5}")
        except Exception as exc:
            raise RuntimeError(f"Failed to trigger AKABAK solve: {exc}") from exc
        self.state = "running"
        self._log(level="info", step=step, event="solve_started", payload={"state": self.state})
        return AkabakDriverResult(ok=True, status=self.state, details={})

    def wait_for_completion(self, timeout_s: int = 300) -> AkabakDriverResult:
        step = "wait_for_completion"
        self._connect()
        self._require(self.state == "running", "AKABAK solve is not running.", step)

        def _completed():
            progress = self.session.find_window(
                title_regex=AKABAK_SOLVE_PROGRESS.title_regex,
                class_name_regex=AKABAK_SOLVE_PROGRESS.class_name_regex,
            )
            if self.watchdog:
                handled = self.watchdog.run_watch(step_name=step, timeout_s=2)
                if handled:
                    self._log(level="info", step=step, event="watchdog_handled", payload={"count": len(handled)})
            if progress is None:
                return True, {"status": "completed"}
            return False, {"status": "running"}

        try:
            wait_until(predicate=_completed, timeout_s=max(1.0, float(timeout_s)))
        except TimeoutError:
            self._log(level="error", step=step, event="timeout", payload={"timeout_s": timeout_s})
            raise TimeoutError(f"AKABAK solve did not complete within {timeout_s}s.")
        self.state = "completed"
        self._log(level="info", step=step, event="completed", payload={"state": self.state})
        return AkabakDriverResult(ok=True, status=self.state, details={})

    def close(self) -> AkabakDriverResult:
        step = "close"
        if self.state == "closed":
            return AkabakDriverResult(ok=True, status=self.state, details={"idempotent": True})
        main_window = self.session.find_window(
            title_regex=AKABAK_MAIN_WINDOW.title_regex,
            class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
        )
        if main_window is not None:
            try:
                main_window.close()
            except Exception:
                pass
        self.session.close()
        self.state = "closed"
        self._log(level="info", step=step, event="closed", payload={})
        return AkabakDriverResult(ok=True, status=self.state, details={})
