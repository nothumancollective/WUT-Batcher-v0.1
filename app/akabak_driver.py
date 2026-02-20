"""Deterministic AKABAK UIA driver (pywinauto primary, no pixel scanning)."""

from __future__ import annotations

import ctypes
import csv
from datetime import datetime, timezone
from dataclasses import dataclass
import io
import json
from pathlib import Path
import re
import subprocess
import time
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
VK_F4 = 0x73
IDOK = 1
BN_CLICKED = 0
CBN_SELCHANGE = 1
OPEN_FILE_NAME_CONTROL_ID = 1148
OPEN_FILE_TYPE_CONTROL_ID = 1136
IMPORT_ABEC_COMMAND_ID = 113
AKABAK_IMAGE_NAME = "akabak.exe"
VACS_IMAGE_CANDIDATES = ("vacsviewer_32.exe", "vacsviewer.exe")
VACS_GRAPH_KEYWORDS = ("graph", "impedance", "spl", "phase", "radiation", "polar", "directivity")
MESH_FILE_MISSING_RE = re.compile(r"cannot\s+find\s+mesh[-\s]*file", re.IGNORECASE)
ALL_SOURCES_MUTED_RE = re.compile(r"all\s+sources\s+muted", re.IGNORECASE)


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
        self.startup_timeout_s = max(5, int(startup_timeout_s))
        self.step_timeout_s = max(1, int(step_timeout_s))
        self.state = "init"
        self.current_project: Optional[str] = None
        self.session = UiaSession(
            executable=self.executable,
            app_name="akabak",
            startup_timeout_s=self.startup_timeout_s,
            allow_fallback=True,
            prefer_start=True,
        )
        self.logger = StructuredStepLogger(self.log_dir / "akabak_driver.log.jsonl")
        self.watchdog: Optional[ModalDialogWatchdog] = None
        self.watchdog_events: List[Dict[str, Any]] = []
        self.last_open_dialog_diagnostics_path: Optional[str] = None
        self.last_import_diagnostics_path: Optional[str] = None
        self.last_solve_diagnostics_path: Optional[str] = None
        self.solve_context: Dict[str, Any] = {}

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

    def _send_key_f4(self, hwnd: int) -> None:
        if hwnd <= 0:
            return
        user32 = self._user32()
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_F4, 0)
        user32.PostMessageW(hwnd, WM_KEYUP, VK_F4, 0)

    def _list_process_ids_by_image(self, image_name: str) -> List[int]:
        target = str(image_name or "").strip().lower()
        if not target:
            return []
        try:
            cp = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {target}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            return []
        rows: List[int] = []
        for row in csv.reader(io.StringIO(str(cp.stdout or ""))):
            if not row or len(row) < 2:
                continue
            name = str(row[0] or "").strip().strip('"').lower()
            if name != target:
                continue
            try:
                rows.append(int(str(row[1] or "").strip().strip('"')))
            except Exception:
                continue
        return sorted(set(rows))

    def _list_akabak_process_ids(self) -> List[int]:
        return self._list_process_ids_by_image(AKABAK_IMAGE_NAME)

    def _list_vacs_process_ids(self) -> List[int]:
        rows: List[int] = []
        for image in VACS_IMAGE_CANDIDATES:
            rows.extend(self._list_process_ids_by_image(image))
        return sorted(set(rows))

    def _process_top_level_windows(self, *, process_id: Optional[int] = None) -> List[Any]:
        pid = int(process_id or self.session.process_id or 0)
        if pid <= 0:
            return []
        try:
            from pywinauto import Desktop
        except Exception:
            return []
        try:
            return list(Desktop(backend="uia").windows(process=pid))
        except Exception:
            return []

    def _window_signature_row(self, window: Any) -> Dict[str, Any]:
        info = getattr(window, "element_info", None)
        is_visible = False
        try:
            is_visible = bool(window.is_visible())
        except Exception:
            is_visible = False
        return {
            "title": self._window_title(window),
            "class_name": str(getattr(info, "class_name", "") or ""),
            "control_type": str(getattr(info, "control_type", "") or ""),
            "automation_id": str(getattr(info, "automation_id", "") or ""),
            "native_handle": int(getattr(info, "handle", 0) or 0),
            "is_visible": is_visible,
        }

    def _vacs_window_metrics(self, window: Any) -> Dict[str, Any]:
        row = self._window_signature_row(window)
        controls = 0
        keyword_hits = 0
        try:
            descendants = list(window.descendants())
            controls = len(descendants)
            for control in descendants[:1500]:
                try:
                    title = str(control.window_text() or "").strip().lower()
                except Exception:
                    title = ""
                if not title:
                    continue
                if any(token in title for token in VACS_GRAPH_KEYWORDS):
                    keyword_hits += 1
        except Exception:
            pass
        row["controls_count"] = int(controls)
        row["graph_keyword_hits"] = int(keyword_hits)
        return row

    def _vacs_ui_snapshot(self) -> Dict[str, Any]:
        pid_rows: Dict[str, Any] = {}
        max_controls = 0
        max_keyword_hits = 0
        for pid in self._list_vacs_process_ids():
            rows: List[Dict[str, Any]] = []
            for window in self._process_top_level_windows(process_id=pid)[:4]:
                metrics = self._vacs_window_metrics(window)
                rows.append(metrics)
                max_controls = max(max_controls, int(metrics.get("controls_count", 0)))
                max_keyword_hits = max(max_keyword_hits, int(metrics.get("graph_keyword_hits", 0)))
            pid_rows[str(pid)] = rows
        return {
            "pids": self._list_vacs_process_ids(),
            "windows": pid_rows,
            "max_controls_count": int(max_controls),
            "max_graph_keyword_hits": int(max_keyword_hits),
        }

    def _is_interpreter_window_row(self, row: Dict[str, Any]) -> bool:
        class_name = str(row.get("class_name", "") or "")
        title = str(row.get("title", "") or "")
        class_match = bool(
            AKABAK_INTERPRETER_WINDOW.class_name_regex
            and re.search(AKABAK_INTERPRETER_WINDOW.class_name_regex, class_name, re.IGNORECASE)
        )
        title_match = bool(
            AKABAK_INTERPRETER_WINDOW.title_regex
            and re.search(AKABAK_INTERPRETER_WINDOW.title_regex, title, re.IGNORECASE)
        )
        return bool(class_match and title_match)

    def _is_main_window_row(self, row: Dict[str, Any]) -> bool:
        class_name = str(row.get("class_name", "") or "")
        title = str(row.get("title", "") or "")
        class_match = bool(
            AKABAK_MAIN_WINDOW.class_name_regex and re.search(AKABAK_MAIN_WINDOW.class_name_regex, class_name, re.IGNORECASE)
        )
        title_match = bool(
            AKABAK_MAIN_WINDOW.title_regex and re.search(AKABAK_MAIN_WINDOW.title_regex, title, re.IGNORECASE)
        )
        return bool(class_match and title_match)

    def _solve_signal_snapshot(self, *, include_vacs_ui: bool = True) -> Dict[str, Any]:
        main_pid = int(self.session.process_id or 0)
        akabak_pids = self._list_akabak_process_ids()
        vacs_ui: Dict[str, Any] = {}
        vacs_pids: List[int] = self._list_vacs_process_ids()
        if include_vacs_ui:
            vacs_ui = self._vacs_ui_snapshot()
            vacs_pids = list(vacs_ui.get("pids", []))
        progress = self.session.find_window(
            title_regex=AKABAK_SOLVE_PROGRESS.title_regex,
            class_name_regex=AKABAK_SOLVE_PROGRESS.class_name_regex,
        )
        return {
            "main_pid": main_pid,
            "akabak_pids": akabak_pids,
            "vacs_pids": vacs_pids,
            "worker_akabak_pids": [pid for pid in akabak_pids if pid != main_pid],
            "progress_window_present": bool(progress is not None),
            "vacs_ui": vacs_ui,
        }

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
            title_folded = title_lower.replace("ö", "oe").replace("Ã¶", "oe")

            if control_type in {"Edit", "ComboBox"}:
                score = 0
                if control_type == "Edit":
                    score += 80
                elif control_type == "ComboBox":
                    score += 10
                if automation_id == str(OPEN_FILE_NAME_CONTROL_ID):
                    score += 100
                if re.search(r"(Edit|ComboBox)", class_name, re.IGNORECASE):
                    score += 40
                if hasattr(control, "set_edit_text") or hasattr(control, "set_text") or hasattr(control, "type_keys"):
                    score += 20
                if not title_lower:
                    score += 15
                if re.search(r"(file\s*name|dateiname|datei\s*name|filename|dateityp)", title_folded, re.IGNORECASE):
                    score -= 120
                edit_candidates.append((score, control))

            if control_type == "Button":
                score = 0
                if automation_id == str(IDOK):
                    score += 100
                else:
                    score -= 70
                if re.search(r"(open|oeffnen)", title_folded, re.IGNORECASE):
                    score += 40
                if hasattr(control, "invoke") or hasattr(control, "click"):
                    score += 10
                button_candidates.append((score, control))

        edit = sorted(edit_candidates, key=lambda item: item[0], reverse=True)[0][1] if edit_candidates else None
        open_button = sorted(button_candidates, key=lambda item: item[0], reverse=True)[0][1] if button_candidates else None
        return edit, open_button

    def _dialog_has_filename_control(self, dialog_window: Any) -> bool:
        handle = self._window_handle(dialog_window)
        if handle > 0:
            try:
                edit_handle = int(self._user32().GetDlgItem(handle, OPEN_FILE_NAME_CONTROL_ID) or 0)
                if edit_handle > 0:
                    return True
            except Exception:
                pass
        try:
            for control in dialog_window.descendants():
                info = control.element_info
                automation_id = str(getattr(info, "automation_id", "") or "")
                if automation_id == str(OPEN_FILE_NAME_CONTROL_ID):
                    return True
        except Exception:
            return False
        return False

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
            start_button = self._find_first_control(
                interpreter,
                class_name_regex=r"TRzBitBtn",
                title_regex=r"start\s+importing",
            )
            apply_button = self._find_first_control(
                interpreter,
                class_name_regex=r"TRzBitBtn",
                title_regex=r"apply",
            )
            if start_button is not None and apply_button is not None:
                return True, "interpreter_import_controls_present"
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
        if dialog_closed:
            project_loaded, project_signal = self._project_loaded_signal(
                main_window=main_window,
                project_path=project_path,
                main_title_before=main_title_before,
            )
        else:
            project_loaded = False
            project_signal = "dialog_still_open"
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

    def _classify_fatal_modal(self, modal_details: Dict[str, Any]) -> Optional[str]:
        title = str(modal_details.get("title", "") or "")
        message = str(modal_details.get("message", "") or "")
        blob = f"{title} {message}".strip()
        if not blob:
            return None
        if MESH_FILE_MISSING_RE.search(blob):
            return "mesh_file_missing"
        if ALL_SOURCES_MUTED_RE.search(blob):
            return "all_sources_muted"
        return None

    def _find_main_process_modal(self) -> Optional[Any]:
        process_id = int(self.session.process_id or 0)
        if process_id <= 0:
            return None
        for window in self._process_top_level_windows(process_id=process_id):
            row = self._window_signature_row(window)
            class_name = str(row.get("class_name", "") or "")
            title = str(row.get("title", "") or "")
            is_modal_class = class_name == "#32770" or bool(re.search(r"(dialog|message)", class_name, re.IGNORECASE))
            is_modal_title = bool(re.search(r"(error|warning|warnung|meldung|message)", title, re.IGNORECASE))
            if not (is_modal_class or is_modal_title):
                continue
            if self._is_main_window_row(row) or self._is_interpreter_window_row(row):
                continue
            return window
        return None

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

    def _run_watchdog_modal_sweep(self, *, step: str, phase: str, timeout_s: float = 4.0) -> Dict[str, Any]:
        row: Dict[str, Any] = {"phase": str(phase), "handled": 0}
        if not self.watchdog:
            row["status"] = "watchdog_missing"
            return row
        try:
            events = self.watchdog.run_watch(step_name=f"{step}_{phase}", timeout_s=max(0.5, float(timeout_s))) or []
        except Exception as exc:
            row["status"] = "watchdog_error"
            row["error"] = repr(exc)
            return row
        self._record_watchdog_events(step=step, events=events)
        if events:
            self._log(level="info", step=step, event="watchdog_handled", payload={"phase": phase, "count": len(events)})
        row["status"] = "ok"
        row["handled"] = int(len(events))
        row["events"] = list(events[:4])
        return row

    def _confirm_after_interpreter_action(
        self,
        *,
        main_window: Any,
        step: str,
        phase: str,
        allow_enter_fallback: bool = True,
        watchdog_timeout_s: float = 0.9,
    ) -> Dict[str, Any]:
        row: Dict[str, Any] = {"phase": str(phase), "method": None, "allow_enter_fallback": bool(allow_enter_fallback)}

        # Always sweep global/top-level modals first so close/apply confirmations
        # are handled even if the interpreter window already disappeared.
        watchdog_row = self._run_watchdog_modal_sweep(step=step, phase=phase, timeout_s=max(0.6, float(watchdog_timeout_s)))
        row["watchdog"] = watchdog_row
        if int(watchdog_row.get("handled", 0)) > 0:
            row["status"] = "watchdog_handled"
            return row

        interpreter = self._find_interpreter_window(main_window=main_window)
        if interpreter is None:
            row["status"] = "interpreter_missing"
            return row

        modal = self._find_interpreter_modal(interpreter_window=interpreter)
        if modal is not None:
            modal_details = self._modal_details(modal)
            dismissed = self._invoke_modal_primary(modal_window=modal, step=step)
            row["status"] = "interpreter_modal"
            row["modal"] = modal_details
            row["dismissed"] = bool(dismissed)
            return row

        if not allow_enter_fallback:
            row["status"] = "no_confirm_needed"
            return row

        interpreter_handle = self._window_handle(interpreter)
        if interpreter_handle > 0:
            self._send_key_enter(interpreter_handle)
            row["method"] = "interpreter_enter"
            row["status"] = "enter_sent"
            watchdog_after_enter = self._run_watchdog_modal_sweep(
                step=step,
                phase=f"{phase}_after_enter",
                timeout_s=max(0.6, float(watchdog_timeout_s)),
            )
            row["watchdog_after_enter"] = watchdog_after_enter
            return row

        row["status"] = "no_action"
        return row

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

    def _close_interpreter_after_apply(self, *, main_window: Any, step: str) -> Dict[str, Any]:
        interpreter = self._find_interpreter_window(main_window=main_window)
        if interpreter is None:
            return {"status": "interpreter_already_closed"}
        action = self._invoke_interpreter_button(
            interpreter_window=interpreter,
            title_regex=r"close",
            step=step,
            action_name="close_interpreter",
        )
        close_wait: Dict[str, Any] = {}
        close_retry_sent = False
        enter_confirm_sent = False

        def _close_state() -> Tuple[bool, Dict[str, Any]]:
            nonlocal close_retry_sent, enter_confirm_sent
            interpreter_now = self._find_interpreter_window(main_window=main_window)
            if interpreter_now is None:
                return True, {"status": "interpreter_closed"}

            modal = self._find_interpreter_modal(interpreter_window=interpreter_now)
            if modal is not None:
                modal_details = self._modal_details(modal)
                dismissed = self._invoke_modal_primary(modal_window=modal, step=step)
                return False, {
                    "status": "interpreter_close_modal",
                    "modal": modal_details,
                    "dismissed": bool(dismissed),
                }

            watchdog_row = self._run_watchdog_modal_sweep(step=step, phase="close_interpreter_wait", timeout_s=1.0)
            if int(watchdog_row.get("handled", 0)) > 0:
                return False, {"status": "watchdog_handled", "watchdog": watchdog_row}

            # Deterministic close-confirm ladder before force-close fallback.
            if not close_retry_sent:
                close_button = self._find_first_control(
                    interpreter_now,
                    class_name_regex=r"TRzBitBtn|TRzMenuButton",
                    title_regex=r"close",
                )
                if close_button is not None:
                    close_retry_sent = True
                    try:
                        close_button.set_focus()
                    except Exception:
                        pass
                    try:
                        if hasattr(close_button, "invoke"):
                            close_button.invoke()
                            return False, {"status": "close_retry_invoke"}
                    except Exception:
                        pass
                    try:
                        if hasattr(close_button, "click"):
                            close_button.click()
                            return False, {"status": "close_retry_click"}
                    except Exception:
                        pass
                    close_hwnd = self._window_handle(close_button)
                    if close_hwnd > 0:
                        self._user32().SendMessageW(close_hwnd, BM_CLICK, 0, 0)
                        return False, {"status": "close_retry_bm_click"}
                    return False, {"status": "close_retry_noop"}

            if not enter_confirm_sent:
                interpreter_hwnd = self._window_handle(interpreter_now)
                if interpreter_hwnd > 0:
                    enter_confirm_sent = True
                    self._send_key_enter(interpreter_hwnd)
                    return False, {"status": "close_confirm_enter_sent"}

            return False, {"status": "waiting_close"}

        try:
            close_wait = wait_until(
                predicate=_close_state,
                timeout_s=min(20.0, float(self.step_timeout_s)),
            )
            return {**action, **close_wait}
        except Exception:
            pass

        # Last resort only: force-close interpreter window if deterministic close path stalled.
        hwnd = self._window_handle(interpreter)
        if hwnd > 0:
            self._user32().SendMessageW(hwnd, WM_CLOSE, 0, 0)
            try:
                close_wait = wait_until(
                    predicate=_close_state,
                    timeout_s=min(10.0, float(self.step_timeout_s)),
                )
                payload = {"status": "interpreter_closed_after_wm_close", **action, **close_wait, "wm_close_handle": hwnd}
                return payload
            except Exception:
                pass
        return {"status": "interpreter_close_timeout", **action}

    def _ensure_import_window_closed(self, *, main_window: Any, step: str) -> Dict[str, Any]:
        main_handle = self._window_handle(main_window)
        self._require(main_handle > 0, "AKABAK main window handle unavailable in import-close assertion.", step)

        closed_handles: List[int] = []

        def _state() -> Tuple[bool, Dict[str, Any]]:
            nonlocal closed_handles
            windows = self._process_top_level_windows()
            rows = [self._window_signature_row(window) for window in windows]
            visible = [row for row in rows if bool(row.get("is_visible", False))]
            main_visible = [row for row in visible if int(row.get("native_handle", 0) or 0) == main_handle]
            extras = [row for row in visible if int(row.get("native_handle", 0) or 0) != main_handle]
            interpreter_extras = [row for row in extras if self._is_interpreter_window_row(row)]

            for row in interpreter_extras:
                hwnd = int(row.get("native_handle", 0) or 0)
                if hwnd <= 0 or hwnd in closed_handles:
                    continue
                self._user32().SendMessageW(hwnd, WM_CLOSE, 0, 0)
                closed_handles.append(hwnd)

            if main_visible and not extras:
                return True, {
                    "status": "main_only_open",
                    "visible_window_count": len(visible),
                    "main_handle": main_handle,
                    "closed_interpreter_handles": list(closed_handles),
                }

            return False, {
                "status": "waiting_main_only",
                "visible_window_count": len(visible),
                "main_handle": main_handle,
                "extras": extras[:6],
                "closed_interpreter_handles": list(closed_handles),
            }

        return wait_until(
            predicate=_state,
            timeout_s=min(20.0, float(self.step_timeout_s)),
        )

    def _write_solve_diagnostics(self, *, step: str, reason: str, context: Dict[str, Any]) -> Optional[Path]:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_path = self.log_dir / f"solve_failure_{stamp}.json"

        payload: Dict[str, Any] = {
            "step": step,
            "reason": reason,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "context": dict(context or {}),
            "main_pid": int(self.session.process_id or 0),
            "solve_snapshot": self._solve_signal_snapshot(),
            "watchdog_events": list(self.watchdog_events),
        }
        try:
            payload["akabak_windows"] = [
                self._window_signature_row(window) for window in self._process_top_level_windows(process_id=int(self.session.process_id or 0))
            ]
        except Exception as exc:
            payload["akabak_windows_error"] = repr(exc)
        vacs_windows: Dict[str, Any] = {}
        for vacs_pid in self._list_vacs_process_ids():
            try:
                vacs_windows[str(vacs_pid)] = [
                    self._window_signature_row(window) for window in self._process_top_level_windows(process_id=vacs_pid)
                ]
            except Exception as exc:
                vacs_windows[str(vacs_pid)] = {"error": repr(exc)}
        payload["vacs_windows"] = vacs_windows
        try:
            json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            return None
        return json_path

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
        # Primary path: enumerate all top-level windows for the AKABAK process.
        for window in self._process_top_level_windows():
            row = self._window_signature_row(window)
            if self._is_interpreter_window_row(row):
                return window

        # Fallback path: child-window traversal relative to main window.
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
                    if self._dialog_has_filename_control(candidate):
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
            if self._dialog_has_filename_control(candidate):
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
        fast_timeout_s = min(1.0, max(0.35, float(timeout_s) / 6.0))
        try:
            file_dialog = wait_until(
                predicate=lambda: (
                    self._find_open_file_dialog(main_window=main_window) is not None,
                    self._find_open_file_dialog(main_window=main_window),
                ),
                timeout_s=fast_timeout_s,
                initial_interval_s=0.03,
                max_interval_s=0.12,
                backoff_factor=1.5,
            )
        except TimeoutError:
            self._log(
                level="info",
                step=step,
                event="open_dialog_menu_wait_fallback",
                payload={"fast_timeout_s": fast_timeout_s, "fallback_timeout_s": max(2.0, float(timeout_s))},
            )
            file_dialog = wait_until(
                predicate=lambda: (
                    self._find_open_file_dialog(main_window=main_window) is not None,
                    self._find_open_file_dialog(main_window=main_window),
                ),
                timeout_s=max(2.0, float(timeout_s)),
                initial_interval_s=0.05,
                max_interval_s=0.3,
                backoff_factor=1.7,
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
        try:
            action = self._invoke_interpreter_button(
                interpreter_window=interpreter_window,
                title_regex=r"open\s+abec\s+project",
                step=step,
                action_name="open_abec_project",
            )
        except Exception:
            action = self._invoke_interpreter_button(
                interpreter_window=interpreter_window,
                title_regex=r"open.*abec",
                step=step,
                action_name="open_abec_project_fallback",
            )
        dialog = wait_until(
            predicate=lambda: (
                self._find_open_file_dialog(main_window=main_window) is not None,
                self._find_open_file_dialog(main_window=main_window),
            ),
            timeout_s=min(8.0, float(self.step_timeout_s)),
        )
        self._require(dialog is not None, "Open-file dialog did not appear after Open ABEC Project action.", step)
        self._log(level="info", step=step, event="interpreter_open_button_triggered", payload={"action": action})

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
        strict_filename_edit = self._find_first_control(
            file_dialog,
            control_type="Edit",
            automation_id=str(OPEN_FILE_NAME_CONTROL_ID),
        )
        if strict_filename_edit is not None:
            filename_edit = strict_filename_edit
        filename_combo = self._find_first_control(
            file_dialog,
            control_type="ComboBox",
            automation_id=str(OPEN_FILE_NAME_CONTROL_ID),
        )
        idok_handle = int(user32.GetDlgItem(dialog_handle, IDOK) or 0)
        open_button_handle = idok_handle or (self._window_handle(open_button) if open_button is not None else 0)
        if open_button is not None and open_button_handle > 0 and self._window_handle(open_button) != open_button_handle:
            open_button = None
        edit_handle = self._window_handle(filename_edit) if filename_edit is not None else 0
        combo_handle = self._window_handle(filename_combo) if filename_combo is not None else 0
        attempts: List[Dict[str, Any]] = []
        path_written_once = False
        dialog_close_wait_fast_s = min(0.35, max(0.18, float(self.step_timeout_s) / 600.0))
        dialog_close_wait_fallback_s = min(1.2, max(0.6, float(self.step_timeout_s) / 90.0))
        postcondition_timeout_fast_s = min(2.0, max(0.5, float(self.step_timeout_s) / 150.0))
        postcondition_timeout_fallback_total_s = min(float(self.step_timeout_s), 12.0)

        def _wait_for_postcondition(timeout_s: float, *, fast_poll: bool = False) -> Dict[str, Any]:
            kwargs: Dict[str, Any] = {}
            if fast_poll:
                kwargs = {
                    "initial_interval_s": 0.04,
                    "max_interval_s": 0.2,
                    "backoff_factor": 1.6,
                }
            return wait_until(
                predicate=lambda: self._open_dialog_postcondition(
                    main_window=main_window,
                    project_path=project_path,
                    main_title_before=main_title_before,
                ),
                timeout_s=timeout_s,
                **kwargs,
            )

        def _wait_for_postcondition_with_fallback() -> Dict[str, Any]:
            start = time.perf_counter()
            try:
                return _wait_for_postcondition(postcondition_timeout_fast_s, fast_poll=True)
            except TimeoutError:
                elapsed = max(0.0, time.perf_counter() - start)
                remaining = max(0.25, postcondition_timeout_fallback_total_s - elapsed)
                return _wait_for_postcondition(remaining, fast_poll=False)

        def _normalize_path_value(value: str) -> str:
            normalized = str(value or "").strip().strip('"')
            return normalized.replace("/", "\\").lower()

        def _path_matches(value: str) -> bool:
            if not str(value or "").strip():
                return False
            return _normalize_path_value(value) == _normalize_path_value(str(project_path))

        def _readback_snapshot() -> Dict[str, str]:
            return {
                "edit": self._edit_readback(filename_edit),
                "dialog": self._dialog_filename_readback(dialog_handle),
            }

        def _ensure_abec_file_type() -> Dict[str, Any]:
            details: Dict[str, Any] = {
                "available": False,
                "ok": False,
                "selected_before": "",
                "selected_after": "",
                "matched_item": "",
                "items": [],
            }
            try:
                from pywinauto import Desktop
            except Exception as exc:
                details["error"] = repr(exc)
                return details
            try:
                w32_dialog = Desktop(backend="win32").window(handle=dialog_handle)
                combo = w32_dialog.child_window(control_id=OPEN_FILE_TYPE_CONTROL_ID, class_name="ComboBox").wrapper_object()
                details["available"] = True
                try:
                    details["selected_before"] = str(combo.selected_text() or "")
                except Exception:
                    details["selected_before"] = ""
                try:
                    items = [str(item or "") for item in combo.item_texts()]
                except Exception:
                    items = []
                details["items"] = items[:8]
                match = ""
                for item in items:
                    item_lower = item.lower()
                    if ".abec" in item_lower or "abec project" in item_lower:
                        match = item
                        break
                if match:
                    combo.select(match)
                    details["matched_item"] = match
                    details["selected_after"] = str(combo.selected_text() or "")
                else:
                    details["selected_after"] = str(details["selected_before"] or "")
                selected_lower = str(details["selected_after"] or "").lower()
                details["ok"] = bool(".abec" in selected_lower or "abec project" in selected_lower)
            except Exception as exc:
                details["error"] = repr(exc)
            return details

        def _wait_dialog_closed(timeout_s: float, *, fast_poll: bool = False) -> bool:
            kwargs: Dict[str, Any] = {}
            if fast_poll:
                kwargs = {
                    "initial_interval_s": 0.03,
                    "max_interval_s": 0.1,
                    "backoff_factor": 1.5,
                }
            try:
                wait_until(
                    predicate=lambda: (self._find_open_file_dialog(main_window=main_window) is None, None),
                    timeout_s=timeout_s,
                    **kwargs,
                )
            except Exception:
                return False
            return True

        def _wait_dialog_closed_with_fallback() -> bool:
            if _wait_dialog_closed(timeout_s=dialog_close_wait_fast_s, fast_poll=True):
                return True
            return _wait_dialog_closed(timeout_s=dialog_close_wait_fallback_s, fast_poll=False)

        def _confirm_by_enter() -> str:
            actions: List[Tuple[str, Any]] = []
            if filename_edit is not None:
                if hasattr(filename_edit, "set_focus"):
                    actions.append(("edit_set_focus", lambda: filename_edit.set_focus()))
                if hasattr(filename_edit, "type_keys"):
                    actions.append(("edit_enter", lambda: filename_edit.type_keys("{ENTER}", set_foreground=True)))
            if filename_combo is not None:
                if hasattr(filename_combo, "set_focus"):
                    actions.append(("combo_set_focus", lambda: filename_combo.set_focus()))
                if hasattr(filename_combo, "type_keys"):
                    actions.append(("combo_enter", lambda: filename_combo.type_keys("{ENTER}", set_foreground=True)))
            if edit_handle > 0:
                actions.append(("edit_hwnd_enter", lambda: self._send_key_enter(edit_handle)))
            if combo_handle > 0:
                actions.append(("combo_hwnd_enter", lambda: self._send_key_enter(combo_handle)))
            actions.append(("dialog_enter", lambda: self._send_key_enter(dialog_handle)))
            for action_name, action in actions:
                try:
                    action()
                    if _wait_dialog_closed_with_fallback():
                        return action_name
                except Exception:
                    continue
            return ""

        def _confirm_open_dialog(*, prefer_uia: bool) -> str:
            actions: List[Tuple[str, Any]] = []

            if prefer_uia and open_button is not None:
                if hasattr(open_button, "set_focus"):
                    actions.append(("uia_set_focus_open_button", lambda: open_button.set_focus()))
                if hasattr(open_button, "invoke"):
                    actions.append(("uia_invoke", lambda: open_button.invoke()))
                if hasattr(open_button, "click"):
                    actions.append(("uia_click", lambda: open_button.click()))

            actions.append(("wm_command_idok", lambda: user32.SendMessageW(dialog_handle, WM_COMMAND, IDOK, open_button_handle)))
            actions.append(("wm_command_idok_lparam0", lambda: user32.SendMessageW(dialog_handle, WM_COMMAND, IDOK, 0)))
            if open_button_handle > 0:
                actions.append(
                    (
                        "wm_command_bn_clicked_id",
                        lambda: self._send_wm_command_click(parent_hwnd=dialog_handle, control_hwnd=open_button_handle),
                    )
                )
                actions.append(("bm_click", lambda: user32.SendMessageW(open_button_handle, BM_CLICK, 0, 0)))
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

            for action_name, action in actions:
                try:
                    action()
                    if _wait_dialog_closed_with_fallback():
                        return action_name
                except Exception:
                    continue
            return ""

        file_type_state: Dict[str, Any] = {
            "strategy": "no_file_type_switch",
            "available": False,
            "ok": True,
        }
        self._log(level="info", step=step, event="open_dialog_file_type", payload=file_type_state)

        # Tier A: fast path - write filename and confirm with Open button.
        try:
            filename_target = filename_edit or filename_combo
            set_method = ""
            if filename_target is not None:
                if hasattr(filename_target, "set_edit_text"):
                    filename_target.set_edit_text(str(project_path))
                    set_method = "uia_set_edit_text"
                elif hasattr(filename_target, "set_text"):
                    filename_target.set_text(str(project_path))
                    set_method = "uia_set_text"
                else:
                    iface_value = getattr(filename_target, "iface_value", None)
                    if iface_value is not None and hasattr(iface_value, "SetValue"):
                        iface_value.SetValue(str(project_path))
                        set_method = "uia_value_pattern"
            self._require(bool(set_method), "Open dialog filename edit control unavailable for Tier A.", step)
            path_written_once = True
            readback_before_submit = _readback_snapshot()
            readback_match = _path_matches(readback_before_submit.get("edit", "")) or _path_matches(
                readback_before_submit.get("dialog", "")
            )
            confirm_method = _confirm_open_dialog(prefer_uia=True)
            self._require(bool(confirm_method), "Open dialog confirm failed in Tier A.", step)
            state_snapshot: Dict[str, Any] = {}
            ok = False
            error_text = ""
            try:
                state_snapshot = _wait_for_postcondition_with_fallback()
                ok = bool(state_snapshot.get("ok", False))
            except Exception as exc:
                error_text = repr(exc)
                _, state_snapshot = self._open_dialog_postcondition(
                    main_window=main_window,
                    project_path=project_path,
                    main_title_before=main_title_before,
                )
            attempts.append(
                {
                    "tier": "A_FAST_FILENAME_OPEN",
                    "set_method": set_method,
                    "invoke_method": confirm_method,
                    "confirm_method": confirm_method or None,
                    "readback_edit": str(readback_before_submit.get("edit", "")),
                    "readback_dialog": str(readback_before_submit.get("dialog", "")),
                    "readback_match": bool(readback_match),
                    "readback": self._dialog_filename_readback(dialog_handle),
                    "file_type_state": file_type_state,
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

            # Keep the typed filename unchanged. Retry only the confirm action.
            retry_confirm_method = _confirm_open_dialog(prefer_uia=False)
            self._require(bool(retry_confirm_method), "Open dialog confirm retry failed in Tier A.", step)
            retry_snapshot: Dict[str, Any] = {}
            retry_ok = False
            retry_error = ""
            try:
                retry_snapshot = _wait_for_postcondition_with_fallback()
                retry_ok = bool(retry_snapshot.get("ok", False))
            except Exception as exc:
                retry_error = repr(exc)
                _, retry_snapshot = self._open_dialog_postcondition(
                    main_window=main_window,
                    project_path=project_path,
                    main_title_before=main_title_before,
                )
            attempts.append(
                {
                    "tier": "A_CONFIRM_RETRY_NO_REWRITE",
                    "invoke_method": retry_confirm_method,
                    "readback": self._dialog_filename_readback(dialog_handle),
                    "result": "ok" if retry_ok else "postcondition_failed",
                    "project_signal": str(retry_snapshot.get("project_signal", "")),
                    "dialog_closed": bool(retry_snapshot.get("dialog_closed", False)),
                    "project_loaded": bool(retry_snapshot.get("project_loaded", False)),
                    "main_title_before": str(retry_snapshot.get("main_title_before", "")),
                    "main_title_after": str(retry_snapshot.get("main_title_after", "")),
                    "error": retry_error or None,
                }
            )
            if retry_ok:
                self._log(level="info", step=step, event="open_dialog_submit", payload={"attempts": attempts})
                return
        except Exception as exc:
            attempts.append(
                {
                    "tier": "A_FAST_FILENAME_OPEN",
                    "result": "error",
                    "error": repr(exc),
                    "readback": self._dialog_filename_readback(dialog_handle),
                    "file_type_state": file_type_state,
                }
            )

        # If the file name was already written, do not rewrite it in fallback tiers.
        # Rewriting caused duplicate path text in the dialog and invalid file-format errors.
        if path_written_once:
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
                "ABEC open-file dialog did not close with loaded-project signal after single-write submission."
                + (f" diagnostics={self.last_open_dialog_diagnostics_path}" if self.last_open_dialog_diagnostics_path else "")
            )

        # Tier B: Win32 fallback.
        try:
            set_method = ""
            if edit_handle > 0:
                user32.SendMessageW(edit_handle, WM_SETTEXT, 0, str(project_path))
                set_method = "WM_SETTEXT_edit_handle"
            if not set_method and combo_handle > 0:
                user32.SendMessageW(combo_handle, WM_SETTEXT, 0, str(project_path))
                set_method = "WM_SETTEXT_combo_handle"
            if not set_method:
                set_ok = bool(user32.SetDlgItemTextW(dialog_handle, OPEN_FILE_NAME_CONTROL_ID, str(project_path)))
                if set_ok:
                    set_method = "SetDlgItemTextW_id1148"
            self._require(bool(set_method), "Unable to write project path into Dateiname field (Tier B).", step)
            readback_before_submit = _readback_snapshot()
            readback_match = _path_matches(readback_before_submit.get("edit", "")) or _path_matches(
                readback_before_submit.get("dialog", "")
            )
            confirm_method = _confirm_open_dialog(prefer_uia=False)
            self._require(bool(confirm_method), "Unable to confirm open dialog (Tier B).", step)
            state_snapshot: Dict[str, Any] = {}
            ok = False
            error_text = ""
            try:
                state_snapshot = _wait_for_postcondition_with_fallback()
                ok = bool(state_snapshot.get("ok", False))
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
                    "set_method": set_method,
                    "invoke_method": confirm_method,
                    "confirm_method": confirm_method,
                    "readback_edit": str(readback_before_submit.get("edit", "")),
                    "readback_dialog": str(readback_before_submit.get("dialog", "")),
                    "readback_match": bool(readback_match),
                    "readback": self._dialog_filename_readback(dialog_handle),
                    "file_type_state": file_type_state,
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
                    "file_type_state": file_type_state,
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
                state_snapshot = _wait_for_postcondition_with_fallback()
                ok = bool(state_snapshot.get("ok", False))
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
        main_window = wait_until(
            predicate=lambda: (
                (
                    self.session.find_window(
                        title_regex=AKABAK_MAIN_WINDOW.title_regex,
                        class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
                    )
                    is not None
                ),
                self.session.find_window(
                    title_regex=AKABAK_MAIN_WINDOW.title_regex,
                    class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
                ),
            ),
            timeout_s=float(self.startup_timeout_s),
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

        self._log(level="info", step=step, event="action_open_project", payload={"project": project_path})
        try:
            # Keep open-dialog wait tight to avoid perceived idle time before filename entry.
            open_dialog_timeout = min(float(self.step_timeout_s), 5.0)
            main_window.set_focus()
            try:
                file_dialog = self._open_dialog_via_main_menu(
                    main_window=main_window,
                    step=step,
                    timeout_s=open_dialog_timeout,
                )
                self._log(
                    level="info",
                    step=step,
                    event="open_dialog_primary_path",
                    payload={"path": "main_menu_open_project"},
                )
            except Exception as main_menu_exc:
                self._log(
                    level="info",
                    step=step,
                    event="open_dialog_main_menu_fallback",
                    payload={"reason": repr(main_menu_exc)},
                )
                self._send_import_command(main_window=main_window, step=step)
                interpreter = wait_until(
                    predicate=lambda: (
                        self._find_interpreter_window(main_window=main_window) is not None,
                        self._find_interpreter_window(main_window=main_window),
                    ),
                    timeout_s=min(float(self.step_timeout_s), 10.0),
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
            open_confirm = self._confirm_after_interpreter_action(
                main_window=main_window,
                step=step,
                phase="confirm_after_open",
                allow_enter_fallback=False,
            )
            self._log(level="info", step=step, event="confirm_after_open", payload=open_confirm)
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
            attempt_trace.append(self._confirm_after_interpreter_action(main_window=main_window, step=step, phase="confirm_after_start"))

            apply_ready = wait_until(
                predicate=lambda: self._import_apply_ready_state(main_window=main_window),
                timeout_s=max(15.0, float(self.step_timeout_s)),
            )
            apply_status = str(apply_ready.get("status", "unknown"))
            attempt_trace.append({"phase": "wait_apply_ready", "status": apply_status})
            if apply_status == "modal_detected":
                modal = apply_ready.get("modal_window")
                modal_details = self._modal_details(modal) if modal is not None else {"title": "unknown", "message": ""}
                fatal_modal = self._classify_fatal_modal(modal_details)
                dismissed = bool(modal is not None and self._invoke_modal_primary(modal_window=modal, step=step))
                attempt_trace.append(
                    {
                        "phase": "modal_detected_before_apply",
                        "modal": modal_details,
                        "dismissed": dismissed,
                        "fatal_modal": fatal_modal,
                    }
                )
                self._require(dismissed, f"AKABAK import modal before apply not dismissable: {modal_details}", step)
                if fatal_modal:
                    raise RuntimeError(f"AKABAK import fatal modal ({fatal_modal}): {modal_details}")
                apply_ready = wait_until(
                    predicate=lambda: self._import_apply_ready_state(main_window=main_window),
                    timeout_s=max(10.0, float(self.step_timeout_s)),
                )
                apply_status = str(apply_ready.get("status", "unknown"))
                attempt_trace.append({"phase": "wait_apply_ready_after_modal", "status": apply_status})
                self._require(apply_status == "apply_ready", f"Apply not ready after modal handling: {apply_status}", step)

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
            attempt_trace.append(self._confirm_after_interpreter_action(main_window=main_window, step=step, phase="confirm_after_apply"))

            # Only a short settle window after Apply; close/confirm path handles late transitions.
            post_apply_timeout_s = min(1.2, max(0.35, float(self.step_timeout_s) / 180.0))
            post_apply: Dict[str, Any] = {}
            post_status = "unknown"
            try:
                post_apply = wait_until(
                    predicate=lambda: self._import_post_apply_state(
                        main_window=main_window,
                        report_before=report_before_apply,
                    ),
                    timeout_s=post_apply_timeout_s,
                    initial_interval_s=0.03,
                    max_interval_s=0.15,
                    backoff_factor=1.6,
                )
                post_status = str(post_apply.get("status", "unknown"))
                attempt_trace.append(
                    {
                        "phase": "post_apply",
                        "status": post_status,
                        "report_chars": len(str(post_apply.get("report_text", "") or "")),
                        "timeout_s": post_apply_timeout_s,
                    }
                )
            except TimeoutError:
                post_status = "no_post_apply_signal_timeout"
                attempt_trace.append(
                    {
                        "phase": "post_apply",
                        "status": post_status,
                        "timeout_s": post_apply_timeout_s,
                    }
                )
            if post_status == "modal_detected":
                modal = post_apply.get("modal_window")
                modal_details = self._modal_details(modal) if modal is not None else {"title": "unknown", "message": ""}
                fatal_modal = self._classify_fatal_modal(modal_details)
                dismissed = bool(modal is not None and self._invoke_modal_primary(modal_window=modal, step=step))
                attempt_trace.append(
                    {
                        "phase": "modal_detected_after_apply",
                        "modal": modal_details,
                        "dismissed": dismissed,
                        "fatal_modal": fatal_modal,
                    }
                )
                self._require(dismissed, f"AKABAK import modal after apply not dismissable: {modal_details}", step)
                if fatal_modal:
                    raise RuntimeError(f"AKABAK import fatal modal ({fatal_modal}): {modal_details}")
                post_apply = wait_until(
                    predicate=lambda: self._import_post_apply_state(
                        main_window=main_window,
                        report_before=report_before_apply,
                    ),
                    timeout_s=max(10.0, float(self.step_timeout_s)),
                )
                post_status = str(post_apply.get("status", "unknown"))
                attempt_trace.append(
                    {
                        "phase": "post_apply_after_modal",
                        "status": post_status,
                        "report_chars": len(str(post_apply.get("report_text", "") or "")),
                    }
                )
            if post_status not in {
                "start_button_disabled",
                "apply_button_disabled",
                "interpreter_closed",
                "report_text_changed",
                "no_post_apply_signal_timeout",
            }:
                raise RuntimeError(f"AKABAK import postcondition failed: {post_status}")
            close_result = self._close_interpreter_after_apply(main_window=main_window, step=step)
            attempt_trace.append({"phase": "close_interpreter", **close_result})
            close_confirm = self._confirm_after_interpreter_action(
                main_window=main_window,
                step=step,
                phase="confirm_after_close",
                allow_enter_fallback=False,
            )
            attempt_trace.append(close_confirm)
            close_state = self._ensure_import_window_closed(main_window=main_window, step=step)
            attempt_trace.append({"phase": "ensure_main_only_after_import", **close_state})
            if str(close_result.get("status", "")) not in {
                "interpreter_closed",
                "interpreter_closed_after_wm_close",
                "interpreter_already_closed",
            }:
                raise RuntimeError(f"AKABAK import close step failed: {close_result}")
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
        self.last_solve_diagnostics_path = None
        self.solve_context = {}
        self._connect()
        self._require(self.state in {"project_open", "completed"}, "Project must be open before solve.", step)
        main_window = self.session.find_window(
            title_regex=AKABAK_MAIN_WINDOW.title_regex,
            class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
        )
        self._require(main_window is not None, "AKABAK main window is unavailable.", step)
        main_handle = self._window_handle(main_window)
        self._require(main_handle > 0, "AKABAK main window handle unavailable for solve.", step)
        baseline = {
            "main_pid": int(self.session.process_id or 0),
            "akabak_pids": self._list_akabak_process_ids(),
            "vacs_pids": self._list_vacs_process_ids(),
        }
        trigger_attempts: List[Dict[str, Any]] = []

        def _started_state() -> Tuple[bool, Dict[str, Any]]:
            if self.watchdog:
                handled = self.watchdog.run_watch(step_name=f"{step}_startup_watch", timeout_s=1)
                if handled:
                    self._record_watchdog_events(step=step, events=handled)
            process_modal = self._find_main_process_modal()
            if process_modal is not None:
                modal_details = self._modal_details(process_modal)
                fatal_modal = self._classify_fatal_modal(modal_details)
                if fatal_modal:
                    dismissed = self._invoke_modal_primary(modal_window=process_modal, step=step)
                    raise RuntimeError(
                        f"AKABAK solve fatal modal ({fatal_modal})"
                        f" dismissed={bool(dismissed)} details={modal_details}"
                    )
            snapshot = self._solve_signal_snapshot(include_vacs_ui=False)
            baseline_akabak = {int(pid) for pid in baseline.get("akabak_pids", [])}
            baseline_vacs = {int(pid) for pid in baseline.get("vacs_pids", [])}
            new_akabak = [pid for pid in snapshot.get("akabak_pids", []) if int(pid) not in baseline_akabak]
            new_vacs = [pid for pid in snapshot.get("vacs_pids", []) if int(pid) not in baseline_vacs]
            snapshot["new_akabak_pids"] = new_akabak
            snapshot["new_vacs_pids"] = new_vacs
            if bool(snapshot.get("progress_window_present")):
                snapshot["start_signal"] = "progress_window_present"
                return True, snapshot
            if new_akabak or snapshot.get("worker_akabak_pids"):
                snapshot["start_signal"] = "akabak_worker_process_started"
                return True, snapshot
            if new_vacs:
                snapshot["start_signal"] = "vacs_process_started"
                return True, snapshot
            snapshot["start_signal"] = "not_started"
            return False, snapshot

        try:
            # Fast dual-trigger: UIA F4 plus hwnd F4, then fast start wait with
            # an extended fallback window to avoid false negatives on slower hosts.
            try:
                main_window.set_focus()
                main_window.type_keys("{F4}", set_foreground=True)
                trigger_attempts.append({"trigger": "uia_type_keys_f4", "status": "sent"})
            except Exception as exc:
                trigger_attempts.append({"trigger": "uia_type_keys_f4", "status": "error", "error": repr(exc)})
            self._send_key_f4(main_handle)
            trigger_attempts.append({"trigger": "hwnd_postmessage_f4", "status": "sent", "main_handle": main_handle})
            started: Dict[str, Any]
            try:
                started = wait_until(
                    predicate=_started_state,
                    timeout_s=min(6.0, float(self.step_timeout_s)),
                    initial_interval_s=0.05,
                    max_interval_s=0.3,
                    backoff_factor=1.7,
                )
                trigger_attempts.append({"trigger": "wait_tier_fast", "status": "started"})
            except TimeoutError:
                trigger_attempts.append({"trigger": "wait_tier_fast", "status": "timeout"})
                try:
                    main_window.set_focus()
                    main_window.type_keys("{F4}", set_foreground=True)
                    trigger_attempts.append({"trigger": "uia_type_keys_f4_retry", "status": "sent"})
                except Exception as retry_exc:
                    trigger_attempts.append(
                        {"trigger": "uia_type_keys_f4_retry", "status": "error", "error": repr(retry_exc)}
                    )
                self._send_key_f4(main_handle)
                trigger_attempts.append({"trigger": "hwnd_postmessage_f4_retry", "status": "sent", "main_handle": main_handle})
                started = wait_until(
                    predicate=_started_state,
                    timeout_s=min(30.0, float(self.step_timeout_s)),
                    initial_interval_s=0.08,
                    max_interval_s=0.45,
                    backoff_factor=1.8,
                )
                trigger_attempts.append({"trigger": "wait_tier_extended", "status": "started"})
            self.solve_context = {"baseline": baseline, "started": started, "trigger_attempts": trigger_attempts}
            self.state = "running"
            self._log(
                level="info",
                step=step,
                event="solve_started",
                payload={"state": self.state, "trigger_attempts": trigger_attempts, "started": started},
            )
            return AkabakDriverResult(ok=True, status=self.state, details={"started": started, "trigger_attempts": trigger_attempts})
        except Exception as exc:
            diagnostics_path = self._write_solve_diagnostics(
                step=step,
                reason="solve_not_started",
                context={"error": repr(exc), "baseline": baseline, "trigger_attempts": trigger_attempts},
            )
            self.last_solve_diagnostics_path = str(diagnostics_path) if diagnostics_path is not None else None
            raise RuntimeError(
                f"Failed to trigger AKABAK solve with start signal: {exc!r}"
                + (f" diagnostics={self.last_solve_diagnostics_path}" if self.last_solve_diagnostics_path else "")
            ) from exc

    def wait_for_completion(self, timeout_s: int = 300, require_vacs_graph_import: bool = True) -> AkabakDriverResult:
        step = "wait_for_completion"
        self._connect()
        self._require(self.state == "running", "AKABAK solve is not running.", step)

        start_snapshot = dict(self.solve_context.get("started", {}))
        if not start_snapshot:
            self._log(level="error", step=step, event="missing_start_context", payload={})
            raise RuntimeError("AKABAK solve completion wait missing start context; run_solve start signal was not captured.")

        baseline_vacs = {int(pid) for pid in self.solve_context.get("baseline", {}).get("vacs_pids", [])}
        start_vacs_ui = dict(start_snapshot.get("vacs_ui", {}))
        start_controls = int(start_vacs_ui.get("max_controls_count", 0) or 0)
        start_graph_hits = int(start_vacs_ui.get("max_graph_keyword_hits", 0) or 0)

        def _completed() -> Tuple[bool, Dict[str, Any]]:
            if self.watchdog:
                handled = self.watchdog.run_watch(step_name=f"{step}_modal_watch", timeout_s=1)
                if handled:
                    self._record_watchdog_events(step=step, events=handled)
                    self._log(level="info", step=step, event="watchdog_handled", payload={"count": len(handled)})
            snapshot = self._solve_signal_snapshot()
            new_vacs = [pid for pid in snapshot.get("vacs_pids", []) if int(pid) not in baseline_vacs]
            snapshot["new_vacs_pids"] = new_vacs

            if snapshot.get("progress_window_present") or snapshot.get("worker_akabak_pids"):
                snapshot["status"] = "running"
                return False, snapshot

            vacs_ui = dict(snapshot.get("vacs_ui", {}))
            max_controls = int(vacs_ui.get("max_controls_count", 0) or 0)
            max_graph_hits = int(vacs_ui.get("max_graph_keyword_hits", 0) or 0)
            controls_growth = int(max_controls - start_controls)
            graph_hits_growth = int(max_graph_hits - start_graph_hits)
            graphs_imported = bool(
                max_controls >= 80
                or max_graph_hits >= 5
                or (controls_growth >= 40 and graph_hits_growth >= 2)
            )
            snapshot["graphs_imported_signal"] = graphs_imported
            snapshot["max_controls_count"] = max_controls
            snapshot["max_graph_keyword_hits"] = max_graph_hits
            snapshot["controls_growth"] = controls_growth
            snapshot["graph_hits_growth"] = graph_hits_growth

            if not bool(require_vacs_graph_import):
                snapshot["status"] = "completed_no_vacs_signal_required"
                return True, snapshot

            if new_vacs or snapshot.get("vacs_pids"):
                if graphs_imported:
                    snapshot["status"] = "completed_vacs_graphs_imported"
                    return True, snapshot
                snapshot["status"] = "waiting_vacs_graph_import"
                return False, snapshot

            snapshot["status"] = "waiting_vacs_after_solve_start"
            return False, snapshot

        completion_snapshot: Dict[str, Any]
        try:
            completion_snapshot = wait_until(
                predicate=_completed,
                timeout_s=max(1.0, float(timeout_s)),
                initial_interval_s=0.08,
                max_interval_s=0.5,
                backoff_factor=1.7,
            )
        except TimeoutError as exc:
            diagnostics_path = self._write_solve_diagnostics(
                step=step,
                reason="solve_completion_timeout",
                context={"timeout_s": timeout_s, "start_snapshot": start_snapshot},
            )
            self.last_solve_diagnostics_path = str(diagnostics_path) if diagnostics_path is not None else None
            self._log(
                level="error",
                step=step,
                event="timeout",
                payload={"timeout_s": timeout_s, "diagnostics_path": self.last_solve_diagnostics_path},
            )
            raise TimeoutError(
                f"AKABAK solve did not complete within {timeout_s}s."
                + (f" diagnostics={self.last_solve_diagnostics_path}" if self.last_solve_diagnostics_path else "")
            ) from exc
        self.state = "completed"
        self._log(level="info", step=step, event="completed", payload={"state": self.state, "completion": completion_snapshot})
        return AkabakDriverResult(ok=True, status=self.state, details={"completion": completion_snapshot})

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
