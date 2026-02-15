"""Deterministic AKABAK UIA driver (pywinauto primary, no pixel scanning)."""

from __future__ import annotations

import ctypes
from datetime import datetime, timezone
from dataclasses import dataclass
import json
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
BN_CLICKED = 0
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
        self.watchdog_events: List[Dict[str, Any]] = []
        self.last_open_dialog_diagnostics_path: Optional[str] = None
        self.last_import_diagnostics_path: Optional[str] = None

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

    def _read_window_text_by_handle(self, hwnd: int, max_chars: int = 16384) -> str:
        if hwnd <= 0:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(max_chars)
            self._user32().GetWindowTextW(hwnd, buffer, max_chars - 1)
            return str(buffer.value or "").strip()
        except Exception:
            return ""

    def _send_wm_command_click(self, *, parent_hwnd: int, control_hwnd: int) -> bool:
        if parent_hwnd <= 0 or control_hwnd <= 0:
            return False
        user32 = self._user32()
        try:
            ctrl_id = int(user32.GetDlgCtrlID(control_hwnd))
        except Exception:
            return False
        if ctrl_id <= 0:
            return False
        wparam = (int(ctrl_id) & 0xFFFF) | ((int(BN_CLICKED) & 0xFFFF) << 16)
        user32.SendMessageW(parent_hwnd, WM_COMMAND, wparam, control_hwnd)
        return True

    def _record_watchdog_events(self, *, step: str, events: List[Dict[str, Any]]) -> None:
        if not events:
            return
        for item in events:
            row = {"step": str(step), **dict(item)}
            self.watchdog_events.append(row)

    def _window_title(self, control: Any) -> str:
        try:
            return str(control.window_text() or "").strip()
        except Exception:
            try:
                return str(getattr(control.element_info, "name", "") or "").strip()
            except Exception:
                return ""

    def _control_enabled(self, control: Any) -> Optional[bool]:
        try:
            return bool(control.is_enabled())
        except Exception:
            return None

    def _read_interpreter_report_text(self, interpreter_window: Any) -> str:
        memo = self._find_first_control(
            interpreter_window,
            class_name_regex=r"TRzMemo",
        )
        if memo is None:
            return ""
        handle = self._window_handle(memo)
        try:
            text = str(memo.window_text() or "")
        except Exception:
            text = ""
        if not text.strip() and handle > 0:
            text = self._read_window_text_by_handle(handle)
        if not text.strip() and hasattr(memo, "texts"):
            try:
                text = "\n".join(str(item) for item in list(memo.texts()) if str(item).strip())
            except Exception:
                text = text
        return text.strip()

    def _interpreter_button_states(self, interpreter_window: Any) -> List[Dict[str, Any]]:
        specs = [
            ("start_importing", r"start\s+importing"),
            ("apply", r"apply"),
            ("open_abec_project", r"open\s+abec\s+project"),
            ("close", r"close"),
        ]
        rows: List[Dict[str, Any]] = []
        for button_id, title_regex in specs:
            control = self._find_first_control(
                interpreter_window,
                class_name_regex=r"TRzBitBtn|TRzMenuButton",
                title_regex=title_regex,
            )
            if control is None:
                rows.append({"button_id": button_id, "present": False})
                continue
            rows.append(
                {
                    "button_id": button_id,
                    "present": True,
                    "title": self._window_title(control),
                    "class_name": str(getattr(control.element_info, "class_name", "") or ""),
                    "native_handle": self._window_handle(control),
                    "enabled": self._control_enabled(control),
                }
            )
        return rows

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
        edit_candidates: List[Tuple[int, Any]] = []
        button_candidates: List[Tuple[int, Any]] = []
        try:
            controls = list(file_dialog.descendants())
        except Exception:
            controls = []
        for control in controls:
            try:
                info = control.element_info
            except Exception:
                continue
            control_type = str(getattr(info, "control_type", "") or "")
            automation_id = str(getattr(info, "automation_id", "") or "")
            class_name = str(getattr(info, "class_name", "") or "")
            title = self._window_title(control)
            title_lower = title.lower()

            if control_type in {"Edit", "ComboBox"}:
                score = 0
                if automation_id == str(OPEN_FILE_NAME_CONTROL_ID):
                    score += 100
                if re.search(r"(Edit|ComboBox)", class_name, re.IGNORECASE):
                    score += 40
                if hasattr(control, "set_edit_text") or hasattr(control, "set_text") or hasattr(control, "type_keys"):
                    score += 20
                if not title_lower:
                    score += 15
                if re.search(r"(file\s*name|dateiname|datei\s*name|filename|dateityp)", title_lower, re.IGNORECASE):
                    score -= 60
                edit_candidates.append((score, control))

            if control_type == "Button":
                score = 0
                if automation_id == str(IDOK):
                    score += 100
                if re.search(r"(open|oeffnen|öffnen)", title_lower, re.IGNORECASE):
                    score += 40
                if hasattr(control, "invoke") or hasattr(control, "click"):
                    score += 10
                button_candidates.append((score, control))

        edit = sorted(edit_candidates, key=lambda item: item[0], reverse=True)[0][1] if edit_candidates else None
        open_button = sorted(button_candidates, key=lambda item: item[0], reverse=True)[0][1] if button_candidates else None
        return edit, open_button

    def _dialog_filename_readback(self, dialog_handle: int) -> str:
        if dialog_handle <= 0:
            return ""
        readback = ctypes.create_unicode_buffer(2048)
        self._user32().GetDlgItemTextW(dialog_handle, OPEN_FILE_NAME_CONTROL_ID, readback, 2047)
        return str(readback.value or "")

    def _edit_readback(self, edit_control: Optional[Any]) -> str:
        if edit_control is None:
            return ""
        try:
            value = str(edit_control.window_text() or "").strip()
            if value:
                return value
        except Exception:
            pass
        try:
            iface_value = getattr(edit_control, "iface_value", None)
            if iface_value is not None and hasattr(iface_value, "CurrentValue"):
                value = str(iface_value.CurrentValue or "").strip()
                if value:
                    return value
        except Exception:
            pass
        return ""

    def _project_loaded_signal(
        self,
        *,
        main_window: Any,
        project_path: str,
        main_title_before: str,
    ) -> Tuple[bool, str]:
        main_title = self._window_title(main_window)
        main_title_lower = main_title.lower()
        if main_title and "(new)" not in main_title_lower and main_title.strip() != str(main_title_before or "").strip():
            return True, "main_title_changed_not_new"

        path = Path(project_path)
        candidate_tokens = {
            str(path.name or "").strip().lower(),
            str(path.stem or "").strip().lower(),
            str(path.parent.name or "").strip().lower(),
        }
        ignored_tokens = {"", "project", "input", "abec", "(new)", "new"}
        tokens = [token for token in candidate_tokens if token not in ignored_tokens and len(token) >= 4]
        for token in tokens:
            if token in main_title_lower:
                return True, f"main_title_contains_{token}"

        try:
            for control in main_window.descendants():
                title = self._window_title(control).lower()
                for token in tokens:
                    if token in title:
                        return True, f"child_title_contains_{token}"
        except Exception:
            pass

        interpreter = self._find_interpreter_window(main_window=main_window)
        if interpreter is not None:
            report_text = self._read_interpreter_report_text(interpreter)
            if report_text:
                return True, "interpreter_report_nonempty"
        return False, "project_loaded_signal_missing"

    def _open_dialog_postcondition(
        self,
        *,
        main_window: Any,
        project_path: str,
        main_title_before: str,
    ) -> Tuple[bool, Dict[str, Any]]:
        dialog = self._find_open_file_dialog(main_window=main_window)
        dialog_closed = dialog is None
        project_loaded, project_signal = self._project_loaded_signal(
            main_window=main_window,
            project_path=project_path,
            main_title_before=main_title_before,
        )
        main_title_after = self._window_title(main_window)
        payload = {
            "ok": bool(dialog_closed and project_loaded),
            "dialog_closed": bool(dialog_closed),
            "project_loaded": bool(project_loaded),
            "project_signal": str(project_signal),
            "main_title_before": str(main_title_before),
            "main_title_after": str(main_title_after),
        }
        return bool(payload["ok"]), payload

    def _find_interpreter_modal(self, *, interpreter_window: Any) -> Optional[Any]:
        rows = self._child_windows(interpreter_window, class_name_regex=r"(#32770|Dialog)")
        if rows:
            return rows[0]
        return None

    def _modal_details(self, modal_window: Any) -> Dict[str, Any]:
        details: Dict[str, Any] = {"title": self._window_title(modal_window), "class_name": "", "message": "", "buttons": []}
        try:
            info = modal_window.element_info
            details["class_name"] = str(getattr(info, "class_name", "") or "")
        except Exception:
            pass
        messages: List[str] = []
        buttons: List[str] = []
        try:
            for control in modal_window.descendants():
                text = self._window_title(control)
                if not text:
                    continue
                control_type = ""
                try:
                    control_type = str(getattr(control.element_info, "control_type", "") or "")
                except Exception:
                    control_type = ""
                if control_type == "Button":
                    buttons.append(text)
                elif control_type in {"Text", "Document"}:
                    messages.append(text)
        except Exception:
            pass
        details["buttons"] = buttons[:8]
        details["message"] = " | ".join(messages[:4])
        return details

    def _invoke_modal_primary(self, *, modal_window: Any, step: str) -> bool:
        # Deterministic non-visual modal handling: prefer explicit button invoke on OK/Yes.
        target = self._find_first_control(
            modal_window,
            control_type="Button",
            title_regex=r"(ok|yes|ja|continue|fortfahren|close|schliessen)",
        )
        if target is None:
            target = self._find_first_control(modal_window, control_type="Button")
        if target is None:
            return False
        handle = self._window_handle(target)
        try:
            if hasattr(target, "invoke"):
                target.invoke()
                return True
        except Exception:
            pass
        if handle > 0:
            self._user32().SendMessageW(handle, BM_CLICK, 0, 0)
            return True
        return False

    def _import_transition_state(self, *, main_window: Any) -> Tuple[bool, Dict[str, Any]]:
        interpreter = self._find_interpreter_window(main_window=main_window)
        if interpreter is None:
            return True, {"status": "interpreter_closed"}
        modal = self._find_interpreter_modal(interpreter_window=interpreter)
        if modal is not None:
            return True, {"status": "modal_detected", "modal_window": modal}
        start_button = self._find_first_control(
            interpreter,
            class_name_regex=r"TRzBitBtn",
            title_regex=r"start\s+importing",
        )
        if start_button is not None:
            try:
                if not bool(start_button.is_enabled()):
                    return True, {"status": "start_button_disabled"}
            except Exception:
                pass
        return False, {"status": "waiting"}

    def _import_apply_ready_state(self, *, main_window: Any) -> Tuple[bool, Dict[str, Any]]:
        interpreter = self._find_interpreter_window(main_window=main_window)
        if interpreter is None:
            return True, {"status": "interpreter_closed_before_apply"}
        modal = self._find_interpreter_modal(interpreter_window=interpreter)
        if modal is not None:
            return True, {"status": "modal_detected", "modal_window": modal}
        apply_button = self._find_first_control(
            interpreter,
            class_name_regex=r"TRzBitBtn",
            title_regex=r"apply",
        )
        if apply_button is None:
            return False, {"status": "waiting_apply_button"}
        try:
            if bool(apply_button.is_enabled()):
                return True, {"status": "apply_ready", "apply_button": apply_button}
        except Exception:
            return True, {"status": "apply_ready", "apply_button": apply_button}
        return False, {"status": "waiting_apply_button_enabled"}

    def _import_post_apply_state(self, *, main_window: Any, report_before: str = "") -> Tuple[bool, Dict[str, Any]]:
        interpreter = self._find_interpreter_window(main_window=main_window)
        if interpreter is None:
            return True, {"status": "interpreter_closed"}
        modal = self._find_interpreter_modal(interpreter_window=interpreter)
        if modal is not None:
            return True, {"status": "modal_detected", "modal_window": modal}
        start_button = self._find_first_control(
            interpreter,
            class_name_regex=r"TRzBitBtn",
            title_regex=r"start\s+importing",
        )
        if start_button is not None:
            try:
                if not bool(start_button.is_enabled()):
                    return True, {"status": "start_button_disabled"}
            except Exception:
                pass
        apply_button = self._find_first_control(
            interpreter,
            class_name_regex=r"TRzBitBtn",
            title_regex=r"apply",
        )
        if apply_button is not None:
            try:
                if not bool(apply_button.is_enabled()):
                    return True, {"status": "apply_button_disabled"}
            except Exception:
                pass
        report_text = self._read_interpreter_report_text(interpreter)
        if report_text and report_text.strip() != str(report_before or "").strip():
            return True, {"status": "report_text_changed", "report_text": report_text[:1200]}
        return False, {"status": "waiting_post_apply", "report_text": report_text[:1200]}

    def _invoke_interpreter_button(self, *, interpreter_window: Any, title_regex: str, step: str, action_name: str) -> Dict[str, Any]:
        target = self._find_first_control(
            interpreter_window,
            class_name_regex=r"TRzBitBtn|TRzMenuButton",
            title_regex=title_regex,
        )
        self._require(target is not None, f"Interpreter button for '{action_name}' not found.", step)
        handle = self._window_handle(target)
        parent_handle = self._window_handle(interpreter_window)
        invoke_method = ""
        try:
            target.set_focus()
        except Exception:
            pass
        try:
            if hasattr(target, "invoke"):
                target.invoke()
                invoke_method = "uia_invoke"
        except Exception:
            invoke_method = ""
        if not invoke_method and hasattr(target, "click"):
            try:
                target.click()
                invoke_method = "uia_click"
            except Exception:
                invoke_method = ""
        if not invoke_method and self._send_wm_command_click(parent_hwnd=parent_handle, control_hwnd=handle):
            invoke_method = "wm_command_click"
        if not invoke_method and handle > 0:
            self._user32().SendMessageW(handle, BM_CLICK, 0, 0)
            invoke_method = "bm_click"
        if not invoke_method and handle > 0:
            self._send_key_space(handle)
            invoke_method = "key_space"
        self._require(bool(invoke_method), f"Interpreter button invoke failed for '{action_name}'.", step)
        return {
            "handle": handle,
            "parent_handle": parent_handle,
            "invoke_method": invoke_method,
            "action_name": action_name,
        }

    def _write_open_dialog_diagnostics(
        self,
        *,
        step: str,
        file_dialog: Any,
        dialog_handle: int,
        project_path: str,
        attempts: List[Dict[str, Any]],
    ) -> Optional[Path]:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base = self.log_dir / f"open_dialog_failure_{stamp}"
        json_path = base.with_suffix(".json")
        txt_path = base.with_suffix(".txt")
        readback = self._dialog_filename_readback(dialog_handle)
        payload: Dict[str, Any] = {
            "step": step,
            "project_path": project_path,
            "dialog_handle": int(dialog_handle),
            "filename_readback": readback,
            "attempts": list(attempts),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            info = file_dialog.element_info
            payload["dialog_signature"] = {
                "title": str(getattr(info, "name", "") or ""),
                "class_name": str(getattr(info, "class_name", "") or ""),
                "control_type": str(getattr(info, "control_type", "") or ""),
                "automation_id": str(getattr(info, "automation_id", "") or ""),
                "handle": int(getattr(info, "handle", dialog_handle) or dialog_handle),
            }
        except Exception:
            payload["dialog_signature"] = {"handle": int(dialog_handle)}

        try:
            lines: List[str] = []
            capture_controls = list(file_dialog.descendants())
            for control in capture_controls[:400]:
                try:
                    info = control.element_info
                    lines.append(
                        "\t".join(
                            [
                                str(getattr(info, "name", "") or ""),
                                str(getattr(info, "class_name", "") or ""),
                                str(getattr(info, "control_type", "") or ""),
                                str(getattr(info, "automation_id", "") or ""),
                                str(int(getattr(info, "handle", 0) or 0)),
                            ]
                        )
                    )
                except Exception:
                    continue
            txt_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            payload["control_dump_path"] = str(txt_path)
        except Exception as exc:
            payload["control_dump_error"] = repr(exc)

        try:
            json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            return None
        return json_path

    def _write_interpreter_diagnostics(
        self,
        *,
        step: str,
        main_window: Any,
        interpreter_window: Optional[Any],
        reason: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base = self.log_dir / f"import_failure_{stamp}"
        json_path = base.with_suffix(".json")
        txt_path = base.with_suffix(".txt")
        payload: Dict[str, Any] = {
            "step": step,
            "reason": reason,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "context": dict(context or {}),
        }
        if interpreter_window is not None:
            payload["interpreter_signature"] = {
                "title": self._window_title(interpreter_window),
                "class_name": str(getattr(interpreter_window.element_info, "class_name", "") or ""),
                "control_type": str(getattr(interpreter_window.element_info, "control_type", "") or ""),
                "native_handle": self._window_handle(interpreter_window),
            }
            payload["interpreter_button_states"] = self._interpreter_button_states(interpreter_window)
            payload["interpreter_report_text"] = self._read_interpreter_report_text(interpreter_window)
        else:
            payload["interpreter_signature"] = {"missing": True}

        for key, control in (("main_window", main_window), ("interpreter_window", interpreter_window)):
            if control is None:
                continue
            lines: List[str] = []
            try:
                for child in list(control.descendants())[:400]:
                    info = child.element_info
                    lines.append(
                        "\t".join(
                            [
                                str(getattr(info, "control_type", "") or ""),
                                str(getattr(info, "automation_id", "") or ""),
                                str(getattr(info, "class_name", "") or ""),
                                self._window_title(child),
                                str(int(getattr(info, "handle", 0) or 0)),
                            ]
                        )
                    )
            except Exception as exc:
                lines.append(f"<dump_error>\t{repr(exc)}")
            payload[f"{key}_control_count"] = len(lines)
            payload[f"{key}_control_dump_path"] = str(txt_path.with_name(f"{txt_path.stem}_{key}{txt_path.suffix}"))
            dump_path = Path(payload[f"{key}_control_dump_path"])
            dump_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        try:
            json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            return None
        return json_path

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
        main_handle = self._window_handle(main_window)
        interpreter = self._find_interpreter_window(main_window=main_window)
        interpreter_handle = self._window_handle(interpreter) if interpreter is not None else 0
        process_id = int(self.session.process_id or 0)
        try:
            from pywinauto import Desktop
        except Exception:
            Desktop = None  # type: ignore[assignment]

        if Desktop is not None and process_id > 0:
            try:
                for candidate in Desktop(backend="uia").windows(process=process_id):
                    handle = self._window_handle(candidate)
                    if handle <= 0 or handle in {main_handle, interpreter_handle}:
                        continue
                    class_name = str(getattr(candidate.element_info, "class_name", "") or "")
                    if not re.search(r"(#32770|Dialog)", class_name, re.IGNORECASE):
                        continue
                    edit, open_button = self._find_open_dialog_controls(candidate)
                    if edit is not None and open_button is not None:
                        return candidate
            except Exception:
                pass

        matches = self._child_windows(
            main_window,
            class_name_regex=AKABAK_OPEN_FILE_DIALOG.class_name_regex,
            title_regex=AKABAK_OPEN_FILE_DIALOG.title_regex,
        )
        for candidate in matches:
            handle = self._window_handle(candidate)
            if handle > 0 and handle in {main_handle, interpreter_handle}:
                continue
            edit, open_button = self._find_open_dialog_controls(candidate)
            if edit is not None or open_button is not None:
                return candidate
        return None

    def _open_dialog_via_main_menu(self, *, main_window: Any, step: str, timeout_s: float) -> Any:
        hwnd = self._window_handle(main_window)
        self._require(hwnd > 0, "AKABAK main window handle unavailable for menu-select path.", step)
        try:
            from pywinauto import Desktop
        except Exception as exc:
            raise RuntimeError(f"pywinauto Desktop unavailable for menu-select: {exc!r}") from exc
        win32_main = Desktop(backend="win32").window(handle=hwnd)
        win32_main.menu_select("File->Open project...")
        file_dialog = wait_until(
            predicate=lambda: (
                self._find_open_file_dialog(main_window=main_window) is not None,
                self._find_open_file_dialog(main_window=main_window),
            ),
            timeout_s=max(2.0, float(timeout_s)),
        )
        self._log(level="info", step=step, event="open_dialog_opened_via_main_menu", payload={"menu_path": "File->Open project..."})
        return file_dialog

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

    def _trigger_interpreter_open_button(self, *, main_window: Any, interpreter_window: Any, step: str) -> None:
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
        attempts: List[Dict[str, Any]] = []

        def _action(method_name: str, fn) -> bool:
            try:
                fn()
            except Exception as exc:
                attempts.append({"method": method_name, "result": "error", "error": repr(exc)})
                return False
            try:
                dialog = wait_until(
                    predicate=lambda: (
                        self._find_open_file_dialog(main_window=main_window) is not None,
                        self._find_open_file_dialog(main_window=main_window),
                    ),
                    timeout_s=2.5,
                )
                attempts.append({"method": method_name, "result": "ok", "dialog_visible": dialog is not None})
                return True
            except TimeoutError:
                attempts.append({"method": method_name, "result": "timeout", "dialog_visible": False})
                return False

        try:
            target.set_focus()
        except Exception:
            pass
        if hasattr(target, "invoke") and _action("uia_invoke", lambda: target.invoke()):
            self._log(level="info", step=step, event="interpreter_open_button_triggered", payload={"handle": handle, "attempts": attempts})
            return
        if hasattr(target, "click") and _action("uia_click", lambda: target.click()):
            self._log(level="info", step=step, event="interpreter_open_button_triggered", payload={"handle": handle, "attempts": attempts})
            return
        if hasattr(target, "type_keys") and _action(
            "scoped_type_space",
            lambda: target.type_keys("{SPACE}", set_foreground=True),
        ):
            self._log(level="info", step=step, event="interpreter_open_button_triggered", payload={"handle": handle, "attempts": attempts})
            return
        if hasattr(target, "type_keys") and _action(
            "scoped_type_enter",
            lambda: target.type_keys("{ENTER}", set_foreground=True),
        ):
            self._log(level="info", step=step, event="interpreter_open_button_triggered", payload={"handle": handle, "attempts": attempts})
            return
        if handle > 0 and _action("key_space", lambda: self._send_key_space(handle)):
            self._log(level="info", step=step, event="interpreter_open_button_triggered", payload={"handle": handle, "attempts": attempts})
            return
        if handle > 0 and _action("key_enter", lambda: self._send_key_enter(handle)):
            self._log(level="info", step=step, event="interpreter_open_button_triggered", payload={"handle": handle, "attempts": attempts})
            return
        if handle > 0 and _action("bm_click", lambda: self._user32().SendMessageW(handle, BM_CLICK, 0, 0)):
            self._log(level="info", step=step, event="interpreter_open_button_triggered", payload={"handle": handle, "attempts": attempts})
            return
        self._log(level="error", step=step, event="interpreter_open_button_failed", payload={"handle": handle, "attempts": attempts})
        self._require(False, "Interpreter open button invocation failed.", step)

    def _submit_open_file_dialog(
        self,
        *,
        main_window: Any,
        file_dialog: Any,
        project_path: str,
        main_title_before: str,
        step: str,
    ) -> None:
        self.last_open_dialog_diagnostics_path = None
        user32 = self._user32()
        dialog_handle = self._window_handle(file_dialog)
        self._require(dialog_handle > 0, "Open-file dialog handle unavailable.", step)
        filename_edit, open_button = self._find_open_dialog_controls(file_dialog)
        open_button_handle = self._window_handle(open_button) if open_button is not None else int(
            user32.GetDlgItem(dialog_handle, IDOK) or 0
        )
        attempts: List[Dict[str, Any]] = []

        def _wait_for_postcondition(timeout_s: float) -> Tuple[bool, Dict[str, Any]]:
            return wait_until(
                predicate=lambda: self._open_dialog_postcondition(
                    main_window=main_window,
                    project_path=project_path,
                    main_title_before=main_title_before,
                ),
                timeout_s=timeout_s,
            )

        def _confirm_open_dialog() -> str:
            def _wait_dialog_closed(timeout_s: float) -> bool:
                wait_until(
                    predicate=lambda: (self._find_open_file_dialog(main_window=main_window) is None, None),
                    timeout_s=timeout_s,
                )
                return True

            actions: List[Tuple[str, Any]] = []
            if open_button_handle > 0:
                actions.append(("bm_click", lambda: user32.SendMessageW(open_button_handle, BM_CLICK, 0, 0)))
            actions.append(("wm_command_idok", lambda: user32.SendMessageW(dialog_handle, WM_COMMAND, IDOK, open_button_handle)))
            actions.append(
                (
                    "wm_command_bn_clicked",
                    lambda: user32.SendMessageW(
                        dialog_handle,
                        WM_COMMAND,
                        (int(IDOK) & 0xFFFF) | ((int(BN_CLICKED) & 0xFFFF) << 16),
                        open_button_handle,
                    ),
                )
            )
            actions.append(("dialog_enter", lambda: self._send_key_enter(dialog_handle)))
            if filename_edit is not None and hasattr(filename_edit, "type_keys"):
                actions.append(("edit_enter", lambda: filename_edit.type_keys("{ENTER}", set_foreground=True)))

            for action_name, action in actions:
                try:
                    action()
                    _wait_dialog_closed(timeout_s=1.2)
                    return action_name
                except Exception:
                    continue
            return ""

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
            readback_before_submit = self._edit_readback(filename_edit)
            invoked = ""
            if filename_edit is not None and hasattr(filename_edit, "set_focus"):
                try:
                    filename_edit.set_focus()
                except Exception:
                    pass
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
            confirm_method = _confirm_open_dialog()
            state_snapshot: Dict[str, Any] = {}
            ok = False
            error_text = ""
            try:
                ok, state_snapshot = _wait_for_postcondition(timeout_s=4.0)
            except Exception as exc:
                error_text = repr(exc)
                _, state_snapshot = self._open_dialog_postcondition(
                    main_window=main_window,
                    project_path=project_path,
                    main_title_before=main_title_before,
                )
            attempts.append(
                {
                    "tier": "A_UIA",
                    "set_method": set_method,
                    "invoke_method": invoked,
                    "confirm_method": confirm_method or None,
                    "readback_edit": readback_before_submit,
                    "readback": self._dialog_filename_readback(dialog_handle),
                    "result": "ok" if ok else "postcondition_failed",
                    "project_signal": str(state_snapshot.get("project_signal", "")),
                    "dialog_closed": bool(state_snapshot.get("dialog_closed", False)),
                    "project_loaded": bool(state_snapshot.get("project_loaded", False)),
                    "main_title_before": str(state_snapshot.get("main_title_before", "")),
                    "main_title_after": str(state_snapshot.get("main_title_after", "")),
                    "error": error_text or None,
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
            confirm_method = _confirm_open_dialog()
            self._require(bool(confirm_method), "Unable to confirm open dialog (Tier B).", step)
            state_snapshot: Dict[str, Any] = {}
            ok = False
            error_text = ""
            try:
                ok, state_snapshot = _wait_for_postcondition(timeout_s=4.0)
            except Exception as exc:
                error_text = repr(exc)
                _, state_snapshot = self._open_dialog_postcondition(
                    main_window=main_window,
                    project_path=project_path,
                    main_title_before=main_title_before,
                )
            attempts.append(
                {
                    "tier": "B_WIN32",
                    "set_method": "SetDlgItemTextW",
                    "invoke_method": "WM_COMMAND_IDOK",
                    "confirm_method": confirm_method,
                    "readback": self._dialog_filename_readback(dialog_handle),
                    "result": "ok" if ok else "postcondition_failed",
                    "project_signal": str(state_snapshot.get("project_signal", "")),
                    "dialog_closed": bool(state_snapshot.get("dialog_closed", False)),
                    "project_loaded": bool(state_snapshot.get("project_loaded", False)),
                    "main_title_before": str(state_snapshot.get("main_title_before", "")),
                    "main_title_after": str(state_snapshot.get("main_title_after", "")),
                    "error": error_text or None,
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
            state_snapshot: Dict[str, Any] = {}
            ok = False
            error_text = ""
            try:
                ok, state_snapshot = _wait_for_postcondition(timeout_s=4.0)
            except Exception as exc:
                error_text = repr(exc)
                _, state_snapshot = self._open_dialog_postcondition(
                    main_window=main_window,
                    project_path=project_path,
                    main_title_before=main_title_before,
                )
            attempts.append(
                {
                    "tier": "C_SCOPED_KEYS",
                    "set_method": "type_keys_on_focused_edit",
                    "invoke_method": "enter_key",
                    "readback": self._dialog_filename_readback(dialog_handle),
                    "focus_verified": has_focus,
                    "result": "ok" if ok else "postcondition_failed",
                    "project_signal": str(state_snapshot.get("project_signal", "")),
                    "dialog_closed": bool(state_snapshot.get("dialog_closed", False)),
                    "project_loaded": bool(state_snapshot.get("project_loaded", False)),
                    "main_title_before": str(state_snapshot.get("main_title_before", "")),
                    "main_title_after": str(state_snapshot.get("main_title_after", "")),
                    "error": error_text or None,
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

        diagnostics_path = self._write_open_dialog_diagnostics(
            step=step,
            file_dialog=file_dialog,
            dialog_handle=dialog_handle,
            project_path=project_path,
            attempts=attempts,
        )
        self.last_open_dialog_diagnostics_path = str(diagnostics_path) if diagnostics_path is not None else None
        self._log(
            level="error",
            step=step,
            event="open_dialog_submit_failed",
            payload={"attempts": attempts, "diagnostics_path": self.last_open_dialog_diagnostics_path},
        )
        raise RuntimeError(
            "ABEC open-file dialog did not close with loaded-project signal after Tier A/B/C non-visual submission."
            + (f" diagnostics={self.last_open_dialog_diagnostics_path}" if self.last_open_dialog_diagnostics_path else "")
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
        main_title_before = self._window_title(main_window)

        self._log(level="info", step=step, event="action_open_shortcut", payload={"project": project_path})
        try:
            main_window.set_focus()
            open_dialog_timeout = min(float(self.step_timeout_s), 20.0)
            try:
                file_dialog = self._open_dialog_via_main_menu(
                    main_window=main_window,
                    step=step,
                    timeout_s=open_dialog_timeout,
                )
            except Exception as exc:
                self._log(
                    level="info",
                    step=step,
                    event="open_dialog_main_menu_fallback",
                    payload={"reason": repr(exc)},
                )
                self._send_import_command(main_window=main_window, step=step)
                interpreter = wait_until(
                    predicate=lambda: (
                        self._find_interpreter_window(main_window=main_window) is not None,
                        self._find_interpreter_window(main_window=main_window),
                    ),
                    timeout_s=min(float(self.step_timeout_s), 20.0),
                )
                self._trigger_interpreter_open_button(main_window=main_window, interpreter_window=interpreter, step=step)
                file_dialog = wait_until(
                    predicate=lambda: (
                        self._find_open_file_dialog(main_window=main_window) is not None,
                        self._find_open_file_dialog(main_window=main_window),
                    ),
                    timeout_s=open_dialog_timeout,
                )
            self._submit_open_file_dialog(
                main_window=main_window,
                file_dialog=file_dialog,
                project_path=project_path,
                main_title_before=main_title_before,
                step=step,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to open project in AKABAK: {exc!r}") from exc

        if self.watchdog:
            handled = self.watchdog.run_watch(step_name=step, timeout_s=5)
            if handled:
                self._record_watchdog_events(step=step, events=handled)
                self._log(level="info", step=step, event="watchdog_handled", payload={"count": len(handled)})

        self.current_project = project_path
        self.state = "project_open"
        self._log(level="info", step=step, event="postcondition_ok", payload={"state": self.state})
        return AkabakDriverResult(ok=True, status=self.state, details={"project": project_path})

    def import_if_needed(self) -> AkabakDriverResult:
        step = "import_if_needed"
        self.last_import_diagnostics_path = None
        self._connect()
        self._require(self.state in {"project_open", "running", "completed"}, "Project must be open first.", step)
        main_window = self.session.find_window(
            title_regex=AKABAK_MAIN_WINDOW.title_regex,
            class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
        )
        self._require(main_window is not None, "AKABAK main window is unavailable.", step)
        interpreter = self._find_interpreter_window(main_window=main_window)
        if interpreter is None:
            diagnostics_path = self._write_interpreter_diagnostics(
                step=step,
                main_window=main_window,
                interpreter_window=None,
                reason="interpreter_window_missing",
                context={"state": self.state},
            )
            self.last_import_diagnostics_path = str(diagnostics_path) if diagnostics_path is not None else None
            raise RuntimeError(
                "AKABAK interpreter window missing before import-start-apply flow."
                + (f" diagnostics={self.last_import_diagnostics_path}" if self.last_import_diagnostics_path else "")
            )

        attempt_trace: List[Dict[str, Any]] = []
        try:
            start_action = self._invoke_interpreter_button(
                interpreter_window=interpreter,
                title_regex=r"start\s+importing",
                step=step,
                action_name="start_importing",
            )
            attempt_trace.append({"phase": "start_importing", **start_action})

            apply_ready = wait_until(
                predicate=lambda: self._import_apply_ready_state(main_window=main_window),
                timeout_s=max(15.0, float(self.step_timeout_s)),
            )
            apply_status = str(apply_ready.get("status", "unknown"))
            attempt_trace.append({"phase": "wait_apply_ready", "status": apply_status})
            if apply_status == "modal_detected":
                modal = apply_ready.get("modal_window")
                modal_details = self._modal_details(modal) if modal is not None else {"title": "unknown", "message": ""}
                dismissed = bool(modal is not None and self._invoke_modal_primary(modal_window=modal, step=step))
                attempt_trace.append({"phase": "modal_detected_before_apply", "modal": modal_details, "dismissed": dismissed})
                raise RuntimeError(f"AKABAK import modal before apply: {modal_details}")

            interpreter_for_apply = self._find_interpreter_window(main_window=main_window) or interpreter
            report_before_apply = self._read_interpreter_report_text(interpreter_for_apply)
            attempt_trace.append(
                {
                    "phase": "pre_apply_report",
                    "chars": len(report_before_apply),
                }
            )
            apply_action = self._invoke_interpreter_button(
                interpreter_window=interpreter_for_apply,
                title_regex=r"apply",
                step=step,
                action_name="apply",
            )
            attempt_trace.append({"phase": "apply", **apply_action})

            post_apply = wait_until(
                predicate=lambda: self._import_post_apply_state(
                    main_window=main_window,
                    report_before=report_before_apply,
                ),
                timeout_s=max(15.0, float(self.step_timeout_s)),
            )
            post_status = str(post_apply.get("status", "unknown"))
            attempt_trace.append(
                {
                    "phase": "post_apply",
                    "status": post_status,
                    "report_chars": len(str(post_apply.get("report_text", "") or "")),
                }
            )
            if post_status == "modal_detected":
                modal = post_apply.get("modal_window")
                modal_details = self._modal_details(modal) if modal is not None else {"title": "unknown", "message": ""}
                dismissed = bool(modal is not None and self._invoke_modal_primary(modal_window=modal, step=step))
                attempt_trace.append({"phase": "modal_detected_after_apply", "modal": modal_details, "dismissed": dismissed})
                raise RuntimeError(f"AKABAK import modal after apply: {modal_details}")
            if post_status not in {"start_button_disabled", "apply_button_disabled", "interpreter_closed", "report_text_changed"}:
                raise RuntimeError(f"AKABAK import postcondition failed: {post_status}")
        except Exception as exc:
            interpreter_now = self._find_interpreter_window(main_window=main_window)
            diagnostics_path = self._write_interpreter_diagnostics(
                step=step,
                main_window=main_window,
                interpreter_window=interpreter_now,
                reason="import_start_apply_failed",
                context={"attempt_trace": attempt_trace, "error": str(exc)},
            )
            self.last_import_diagnostics_path = str(diagnostics_path) if diagnostics_path is not None else None
            self._log(
                level="error",
                step=step,
                event="import_start_apply_failed",
                payload={"error": str(exc), "attempt_trace": attempt_trace, "diagnostics_path": self.last_import_diagnostics_path},
            )
            raise RuntimeError(
                str(exc)
                + (f" diagnostics={self.last_import_diagnostics_path}" if self.last_import_diagnostics_path else "")
            ) from exc

        self._log(
            level="info",
            step=step,
            event="import_start_apply_ok",
            payload={"attempt_trace": attempt_trace},
        )
        return AkabakDriverResult(
            ok=True,
            status=self.state,
            details={"import_needed": True, "import_mode": "start_importing_apply", "attempt_trace": attempt_trace},
        )

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
                    self._record_watchdog_events(step=step, events=handled)
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

    def detect_le_script_binding_signal(self, expected_script_name: str = "generic25.txt") -> Dict[str, Any]:
        step = "detect_le_script_binding_signal"
        self._connect()
        main_window = self.session.find_window(
            title_regex=AKABAK_MAIN_WINDOW.title_regex,
            class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
        )
        if main_window is None:
            return {
                "ok": False,
                "reason": "main_window_missing",
                "matches": [],
                "expected_script_name": expected_script_name,
            }
        interpreter = self._find_interpreter_window(main_window=main_window)
        if interpreter is None:
            return {
                "ok": False,
                "reason": "interpreter_window_missing",
                "matches": [],
                "expected_script_name": expected_script_name,
            }

        expected = str(expected_script_name or "").strip().lower()
        expected_stem = str(Path(expected).stem).strip().lower()
        matches: List[str] = []
        controls: List[Any] = []
        try:
            controls = list(interpreter.descendants())
        except Exception:
            controls = []
        for control in controls:
            title = self._window_title(control)
            if not title:
                continue
            token = title.strip().lower()
            if expected and expected in token:
                matches.append(title)
                continue
            if expected_stem and expected_stem in token:
                matches.append(title)

        payload = {
            "ok": len(matches) > 0,
            "reason": "match_found" if matches else "no_le_script_text_match",
            "expected_script_name": expected_script_name,
            "matches": matches[:20],
            "watchdog_events": list(self.watchdog_events),
        }
        self._log(level="info", step=step, event="result", payload=payload)
        return payload

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
