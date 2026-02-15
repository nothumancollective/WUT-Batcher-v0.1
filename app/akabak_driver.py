"""Deterministic AKABAK UIA driver (pywinauto primary, no pixel scanning)."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

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
WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5
SMTO_ABORTIFHUNG = 0x0002
VK_SPACE = 0x20
VK_RETURN = 0x0D
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

    def _send_key_enter(self, hwnd: int) -> None:
        if hwnd <= 0:
            return
        user32 = self._user32()
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_RETURN, 0)
        user32.PostMessageW(hwnd, WM_KEYUP, VK_RETURN, 0)

    def _window_title(self, control: Any) -> str:
        try:
            return str(control.window_text() or "").strip()
        except Exception:
            try:
                return str(getattr(control.element_info, "name", "") or "").strip()
            except Exception:
                return ""

    def _find_first_control(
        self,
        root: Any,
        *,
        control_type: Optional[str] = None,
        automation_id: Optional[str] = None,
        class_name_regex: Optional[str] = None,
        title_regex: Optional[str] = None,
    ) -> Optional[Any]:
        controls: List[Any] = []
        try:
            controls = list(root.descendants())
        except Exception:
            controls = []
        for control in controls:
            try:
                info = control.element_info
            except Exception:
                continue
            info_control_type = str(getattr(info, "control_type", "") or "")
            info_automation_id = str(getattr(info, "automation_id", "") or "")
            info_class_name = str(getattr(info, "class_name", "") or "")
            info_title = self._window_title(control)
            if control_type and info_control_type != control_type:
                continue
            if automation_id and info_automation_id != automation_id:
                continue
            if class_name_regex and not re.search(class_name_regex, info_class_name, re.IGNORECASE):
                continue
            if title_regex and not re.search(title_regex, info_title, re.IGNORECASE):
                continue
            return control
        return None

    def _find_open_dialog_controls(self, file_dialog: Any) -> Tuple[Optional[Any], Optional[Any]]:
        edit = self._find_first_control(
            file_dialog,
            control_type="Edit",
            automation_id=str(OPEN_FILE_NAME_CONTROL_ID),
        )
        if edit is None:
            edit = self._find_first_control(
                file_dialog,
                control_type="Edit",
                class_name_regex=r"(Edit|ComboBox)",
            )
        open_button = self._find_first_control(
            file_dialog,
            control_type="Button",
            automation_id=str(IDOK),
        )
        if open_button is None:
            open_button = self._find_first_control(
                file_dialog,
                control_type="Button",
                title_regex=r"(open|oeffnen)",
            )
        return edit, open_button

    def _dialog_filename_readback(self, dialog_handle: int) -> str:
        if dialog_handle <= 0:
            return ""
        readback = ctypes.create_unicode_buffer(2048)
        self._user32().GetDlgItemTextW(dialog_handle, OPEN_FILE_NAME_CONTROL_ID, readback, 2047)
        return str(readback.value or "")

    def _project_loaded_signal(self, *, main_window: Any, project_path: str) -> Tuple[bool, str]:
        interpreter = self._find_interpreter_window(main_window=main_window)
        if interpreter is not None:
            start_button = self._find_first_control(
                interpreter,
                class_name_regex=r"TRzBitBtn",
                title_regex=r"start\s+importing",
            )
            if start_button is not None:
                return True, "interpreter_start_importing_visible"

        project_stem = str(Path(project_path).stem or "").strip().lower()
        if project_stem:
            try:
                main_title = self._window_title(main_window).lower()
                if project_stem in main_title:
                    return True, "main_title_contains_project_stem"
            except Exception:
                pass
            try:
                for control in main_window.descendants():
                    if project_stem in self._window_title(control).lower():
                        return True, "child_title_contains_project_stem"
            except Exception:
                pass
        return False, "project_loaded_signal_missing"

    def _open_dialog_postcondition(self, *, main_window: Any, project_path: str) -> Tuple[bool, Dict[str, Any]]:
        dialog = self._find_open_file_dialog(main_window=main_window)
        dialog_closed = dialog is None
        project_loaded, project_signal = self._project_loaded_signal(main_window=main_window, project_path=project_path)
        payload = {
            "ok": bool(dialog_closed and project_loaded),
            "dialog_closed": bool(dialog_closed),
            "project_loaded": bool(project_loaded),
            "project_signal": str(project_signal),
        }
        return bool(payload["ok"]), payload

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
        filename_edit, open_button = self._find_open_dialog_controls(file_dialog)
        open_button_handle = self._window_handle(open_button) if open_button is not None else int(
            user32.GetDlgItem(dialog_handle, IDOK) or 0
        )
        attempts: List[Dict[str, Any]] = []

        def _wait_for_postcondition(timeout_s: float) -> Tuple[bool, str]:
            state = wait_until(
                predicate=lambda: self._open_dialog_postcondition(main_window=main_window, project_path=project_path),
                timeout_s=timeout_s,
            )
            return bool(state.get("ok", False)), str(state.get("project_signal", ""))

        # Tier A: UIA value/invoke.
        try:
            set_method = ""
            if filename_edit is not None:
                if hasattr(filename_edit, "set_edit_text"):
                    filename_edit.set_edit_text(str(project_path))
                    set_method = "uia_set_edit_text"
                elif hasattr(filename_edit, "set_text"):
                    filename_edit.set_text(str(project_path))
                    set_method = "uia_set_text"
                else:
                    iface_value = getattr(filename_edit, "iface_value", None)
                    if iface_value is not None and hasattr(iface_value, "SetValue"):
                        iface_value.SetValue(str(project_path))
                        set_method = "uia_value_pattern"
            self._require(bool(set_method), "Open dialog filename edit control unavailable for Tier A.", step)
            invoked = ""
            if open_button is not None:
                if hasattr(open_button, "invoke"):
                    open_button.invoke()
                    invoked = "uia_invoke"
                elif hasattr(open_button, "click"):
                    open_button.click()
                    invoked = "uia_click"
                elif open_button_handle > 0:
                    user32.SendMessageW(open_button_handle, BM_CLICK, 0, 0)
                    invoked = "bm_click"
            elif open_button_handle > 0:
                user32.SendMessageW(open_button_handle, BM_CLICK, 0, 0)
                invoked = "bm_click"
            self._require(bool(invoked), "Open dialog Open button unavailable for Tier A.", step)
            ok, signal = _wait_for_postcondition(timeout_s=4.0)
            attempts.append(
                {
                    "tier": "A_UIA",
                    "set_method": set_method,
                    "invoke_method": invoked,
                    "readback": self._dialog_filename_readback(dialog_handle),
                    "result": "ok" if ok else "postcondition_failed",
                    "project_signal": signal,
                }
            )
            if ok:
                self._log(level="info", step=step, event="open_dialog_submit", payload={"attempts": attempts})
                return
        except Exception as exc:
            attempts.append(
                {
                    "tier": "A_UIA",
                    "result": "error",
                    "error": repr(exc),
                    "readback": self._dialog_filename_readback(dialog_handle),
                }
            )

        # Tier B: Win32 handle/message path.
        try:
            set_ok = bool(user32.SetDlgItemTextW(dialog_handle, OPEN_FILE_NAME_CONTROL_ID, str(project_path)))
            self._require(set_ok, "Unable to write project path into open-file dialog (Tier B).", step)
            confirm_sent = False
            if open_button_handle > 0:
                user32.SendMessageW(open_button_handle, BM_CLICK, 0, 0)
                confirm_sent = True
            user32.PostMessageW(dialog_handle, WM_COMMAND, IDOK, open_button_handle)
            confirm_sent = True
            self._require(confirm_sent, "Unable to confirm open dialog (Tier B).", step)
            ok, signal = _wait_for_postcondition(timeout_s=4.0)
            attempts.append(
                {
                    "tier": "B_WIN32",
                    "set_method": "SetDlgItemTextW",
                    "invoke_method": "WM_COMMAND_IDOK",
                    "readback": self._dialog_filename_readback(dialog_handle),
                    "result": "ok" if ok else "postcondition_failed",
                    "project_signal": signal,
                }
            )
            if ok:
                self._log(level="info", step=step, event="open_dialog_submit", payload={"attempts": attempts})
                return
        except Exception as exc:
            attempts.append(
                {
                    "tier": "B_WIN32",
                    "result": "error",
                    "error": repr(exc),
                    "readback": self._dialog_filename_readback(dialog_handle),
                }
            )

        # Tier C: controlled keystrokes only with verified focus on filename edit.
        try:
            self._require(filename_edit is not None, "Filename edit control unavailable for Tier C.", step)
            filename_edit.set_focus()
            has_focus = False
            if hasattr(filename_edit, "has_keyboard_focus"):
                has_focus = bool(filename_edit.has_keyboard_focus())
            self._require(has_focus, "Filename edit does not have keyboard focus for Tier C.", step)
            filename_edit.type_keys("^a{BACKSPACE}", set_foreground=True)
            filename_edit.type_keys(str(project_path), with_spaces=True, set_foreground=True)
            self._send_key_enter(dialog_handle)
            ok, signal = _wait_for_postcondition(timeout_s=4.0)
            attempts.append(
                {
                    "tier": "C_SCOPED_KEYS",
                    "set_method": "type_keys_on_focused_edit",
                    "invoke_method": "enter_key",
                    "readback": self._dialog_filename_readback(dialog_handle),
                    "focus_verified": has_focus,
                    "result": "ok" if ok else "postcondition_failed",
                    "project_signal": signal,
                }
            )
            if ok:
                self._log(level="info", step=step, event="open_dialog_submit", payload={"attempts": attempts})
                return
        except Exception as exc:
            attempts.append(
                {
                    "tier": "C_SCOPED_KEYS",
                    "result": "error",
                    "error": repr(exc),
                    "readback": self._dialog_filename_readback(dialog_handle),
                }
            )

        self._log(level="error", step=step, event="open_dialog_submit_failed", payload={"attempts": attempts})
        raise RuntimeError(
            "ABEC open-file dialog did not close with loaded-project signal after Tier A/B/C non-visual submission."
        )

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
