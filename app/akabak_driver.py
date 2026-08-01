"""Deterministic AKABAK UIA driver (pywinauto primary, no pixel scanning)."""

from __future__ import annotations

import ctypes
import csv
from datetime import datetime, timezone
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
WM_USER = 0x0400
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_CLEAR = 0x0303
BM_CLICK = 0x00F5
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
SMTO_ABORTIFHUNG = 0x0002
VK_SPACE = 0x20
VK_RETURN = 0x0D
KEYEVENTF_KEYUP = 0x0002
VK_F4 = 0x73
VK_F7 = 0x76
IDOK = 1
BN_CLICKED = 0
MK_LBUTTON = 0x0001
EM_SETSEL = 0x00B1
CBN_SELCHANGE = 1
CDM_SETCONTROLTEXT = WM_USER + 104
MF_BYPOSITION = 0x0400
MF_BYCOMMAND = 0x0000
MF_GRAYED = 0x0001
MF_DISABLED = 0x0002
OPEN_FILE_NAME_CONTROL_ID = 1148
OPEN_FILE_TYPE_CONTROL_ID = 1136
IMPORT_ABEC_COMMAND_ID = 113
CALCULATE_ALL_COMMAND_ID = 94
AKABAK_IMAGE_NAME = "akabak.exe"
VACS_IMAGE_CANDIDATES = ("vacsviewer_32.exe", "vacsviewer.exe")
VACS_GRAPH_KEYWORDS = ("graph", "impedance", "spl", "phase", "radiation", "polar", "directivity")
VACS_GRAPH_CLASS_NAMES = ("tform_datcontour", "tform_datgraph")
VACS_STARTUP_EDITOR_CLASS_NAME = "tform_editor"
VACS_STARTUP_EDITOR_TITLE_RE = re.compile(r"^editor\s*-\s*\d+$", re.IGNORECASE)
VACS_STARTUP_EDITOR_SIGNATURES = (
    ("vacs viewer", "skip this note next time", "saving projects is only possible"),
    ("welcome to visualize acoustics", "skip this note next time", "import some data"),
)
MESH_FILE_MISSING_RE = re.compile(r"cannot\s+find\s+mesh[-\s]*file", re.IGNORECASE)
ALL_SOURCES_MUTED_RE = re.compile(r"all\s+sources\s+muted", re.IGNORECASE)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260


@dataclass(frozen=True)
class _NativeElementInfo:
    handle: int
    name: str
    class_name: str
    control_type: str
    automation_id: str


class _NativeHwndControl:
    """Minimal pywinauto-compatible adapter for a process-owned child HWND."""

    def __init__(self, *, user32: Any, handle: int, title: str, class_name: str, control_id: int) -> None:
        class_lower = str(class_name or "").lower()
        if "button" in class_lower or "btn" in class_lower:
            control_type = "Button"
        elif "combo" in class_lower:
            control_type = "ComboBox"
        elif "edit" in class_lower:
            control_type = "Edit"
        else:
            control_type = "Text"
        self._user32 = user32
        self.element_info = _NativeElementInfo(
            handle=int(handle),
            name=str(title or ""),
            class_name=str(class_name or ""),
            control_type=control_type,
            automation_id=str(int(control_id)) if int(control_id) > 0 else "",
        )

    def window_text(self) -> str:
        return str(self.element_info.name or "")

    def is_enabled(self) -> bool:
        return bool(self._user32.IsWindowEnabled(int(self.element_info.handle)))

    def set_focus(self) -> None:
        self._user32.SetFocus(int(self.element_info.handle))

    def set_edit_text(self, value: str) -> None:
        hwnd = int(self.element_info.handle)
        text = ctypes.c_wchar_p(str(value))
        try:
            if self._user32.SetWindowTextW(hwnd, text):
                return
        except Exception:
            pass
        result = ctypes.c_size_t()
        self._user32.SendMessageTimeoutW(
            hwnd,
            WM_SETTEXT,
            0,
            text,
            SMTO_ABORTIFHUNG,
            1000,
            ctypes.byref(result),
        )

    def set_text(self, value: str) -> None:
        self.set_edit_text(value)


class _FileTime(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]


class _ClientRect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * MAX_PATH),
    ]


def _filetime_ticks(value: _FileTime) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _native_process_ids_by_image(image_name: str) -> List[int]:
    """Enumerate Windows processes without shelling out to access-sensitive tasklist."""

    target = str(image_name or "").strip().lower()
    if not target or os.name != "nt" or not hasattr(ctypes, "windll"):
        return []
    kernel32 = ctypes.windll.kernel32
    try:
        kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        snapshot = int(kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) or 0)
    except Exception:
        return []
    invalid_handle = int(ctypes.c_void_p(-1).value or 0)
    if snapshot <= 0 or snapshot == invalid_handle:
        return []
    rows: List[int] = []
    entry = _ProcessEntry32W()
    entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
    try:
        ok = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while ok:
            if str(entry.szExeFile or "").strip().lower() == target:
                rows.append(int(entry.th32ProcessID))
            ok = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    except Exception:
        return []
    finally:
        try:
            kernel32.CloseHandle(snapshot)
        except Exception:
            pass
    return sorted(set(rows))


def _solve_menu_candidate(rows: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    valid = [row for row in rows if int(row.get("command_id", 0) or 0) > 0]
    for row in valid:
        if re.search(r"(?:\t|\s)f4\b", str(row.get("title", "") or ""), re.IGNORECASE):
            return row
    for row in valid:
        if int(row.get("command_id", 0) or 0) == CALCULATE_ALL_COMMAND_ID:
            return row
    for row in valid:
        title = str(row.get("title", "") or "").replace("&", " ")
        if re.search(r"\b(calculate|calculation|solve|berechnen)\b", title, re.IGNORECASE):
            return row
    return None


def _process_cpu_time_seconds(process_id: int) -> Optional[float]:
    """Return kernel + user CPU time for a Windows process without extra dependencies."""
    pid = int(process_id or 0)
    if pid <= 0 or not hasattr(ctypes, "windll"):
        return None
    handle = None
    try:
        kernel32 = ctypes.windll.kernel32
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        open_process.restype = ctypes.c_void_p
        handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if not handle:
            return None
        created = _FileTime()
        exited = _FileTime()
        kernel = _FileTime()
        user = _FileTime()
        get_process_times = kernel32.GetProcessTimes
        get_process_times.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
        ]
        get_process_times.restype = ctypes.c_int
        if not get_process_times(handle, created, exited, kernel, user):
            return None
        return float(_filetime_ticks(kernel) + _filetime_ticks(user)) / 10_000_000.0
    except Exception:
        return None
    finally:
        if handle:
            try:
                ctypes.windll.kernel32.CloseHandle(handle)
            except Exception:
                pass


def _solve_snapshot_made_progress(
    previous: Dict[str, Any],
    current: Dict[str, Any],
    *,
    minimum_cpu_delta_s: float = 0.05,
) -> bool:
    """Detect real solver/import progress instead of treating mere process presence as progress."""
    previous_workers = {int(pid) for pid in previous.get("new_akabak_pids", []) or []}
    current_workers = {int(pid) for pid in current.get("new_akabak_pids", []) or []}
    if current_workers and current_workers != previous_workers:
        return True

    previous_cpu = dict(previous.get("akabak_cpu_times_s", previous.get("worker_cpu_times_s", {})) or {})
    current_cpu = dict(current.get("akabak_cpu_times_s", current.get("worker_cpu_times_s", {})) or {})
    active_solver_pids = set(current_workers)
    main_pid = int(current.get("main_pid", 0) or 0)
    if main_pid > 0:
        active_solver_pids.add(main_pid)
    for pid in active_solver_pids:
        before = previous_cpu.get(str(pid))
        after = current_cpu.get(str(pid))
        if before is None or after is None:
            continue
        try:
            if float(after) - float(before) >= max(0.0, float(minimum_cpu_delta_s)):
                return True
        except (TypeError, ValueError):
            continue

    if bool(current.get("progress_window_present")) and not bool(previous.get("progress_window_present")):
        return True
    previous_vacs = dict(previous.get("vacs_ui", {}) or {})
    current_vacs = dict(current.get("vacs_ui", {}) or {})
    for key in ("max_controls_count", "max_graph_keyword_hits"):
        try:
            if int(current_vacs.get(key, 0) or 0) > int(previous_vacs.get(key, 0) or 0):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _new_process_ids(current: List[int], baseline: List[int] | set[int]) -> List[int]:
    baseline_ids = {int(pid) for pid in baseline if int(pid) > 0}
    return sorted({int(pid) for pid in current if int(pid) > 0 and int(pid) not in baseline_ids})


def _title_matches_regex(pattern: str, title: str) -> bool:
    """Match visible captions while ignoring Windows accelerator markers."""

    value = str(title or "")
    if re.search(pattern, value, re.IGNORECASE):
        return True
    return bool(re.search(pattern, value.replace("&", ""), re.IGNORECASE))


def _is_noninteractive_tool_window(row: Dict[str, Any]) -> bool:
    """Return true only for known, titleless Delphi infrastructure HWNDs."""

    title = str(row.get("title", "") or "").strip()
    class_name = str(row.get("class_name", "") or "").strip().lower()
    return not title and class_name in {"tapplication", "tputilwindow"}


def _solve_heartbeat_payload(snapshot: Dict[str, Any], *, elapsed_s: float) -> Dict[str, Any]:
    vacs_ui = dict(snapshot.get("vacs_ui", {}) or {})
    return {
        "elapsed_s": round(max(0.0, float(elapsed_s)), 3),
        "status": str(snapshot.get("status", "") or ""),
        "main_pid": int(snapshot.get("main_pid", 0) or 0),
        "akabak_pids": [int(pid) for pid in list(snapshot.get("akabak_pids", []) or [])],
        "new_akabak_pids": [int(pid) for pid in list(snapshot.get("new_akabak_pids", []) or [])],
        "akabak_cpu_times_s": dict(snapshot.get("akabak_cpu_times_s", {}) or {}),
        "vacs_pids": [int(pid) for pid in list(snapshot.get("vacs_pids", []) or [])],
        "new_vacs_pids": [int(pid) for pid in list(snapshot.get("new_vacs_pids", []) or [])],
        "progress_window_present": bool(snapshot.get("progress_window_present", False)),
        "solve_command_enabled": snapshot.get("solve_command_enabled"),
        "vacs_max_controls_count": int(vacs_ui.get("max_controls_count", 0) or 0),
        "vacs_max_graph_keyword_hits": int(vacs_ui.get("max_graph_keyword_hits", 0) or 0),
    }


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
        vacs_executable: str | Path | None = None,
        startup_timeout_s: int = 20,
        step_timeout_s: int = 90,
    ) -> None:
        self.executable = str(executable)
        self.vacs_executable = str(vacs_executable) if vacs_executable else ""
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
        self.solve_heartbeats: List[Dict[str, Any]] = []
        self.last_open_dialog_diagnostics_path: Optional[str] = None
        self.last_import_diagnostics_path: Optional[str] = None
        self.last_solve_diagnostics_path: Optional[str] = None
        self.solve_context: Dict[str, Any] = {}
        self._import_report_candidate = ""
        self._import_report_stable_since = 0.0
        self.initial_akabak_pids = set(self._list_akabak_process_ids())
        self.initial_vacs_pids = set(self._list_vacs_process_ids())
        self.owned_akabak_pids: set[int] = set()
        self.owned_vacs_pids: set[int] = set()
        self._vacs_launch_process: Optional[Any] = None
        self._solve_main_handle = 0

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
        state = vars(window) if hasattr(window, "__dict__") else {}
        cached_handle = int(state.get("_wut_native_handle", 0) or 0)
        if cached_handle > 0:
            return cached_handle
        for criterion in reversed(list(state.get("criteria", []) or [])):
            if not isinstance(criterion, dict):
                continue
            criterion_handle = int(criterion.get("handle", 0) or 0)
            if criterion_handle > 0:
                return criterion_handle
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
        if os.name == "nt":
            parent_handle = self._window_handle(parent_window)
            native_rows = self._native_process_window_rows(
                process_id=int(self.session.process_id or 0),
                parent_handle=parent_handle,
            )
            matching_rows = [
                row
                for row in native_rows
                if int(row.get("native_handle", 0) or 0) != parent_handle
                and (
                    str(row.get("class_name", "") or "") == "#32770"
                    or str(row.get("class_name", "") or "").startswith("TForm_")
                )
                and (
                    not class_name_regex
                    or re.search(class_name_regex, str(row.get("class_name", "") or ""), re.IGNORECASE)
                )
                and (
                    not title_regex
                    or re.search(title_regex, str(row.get("title", "") or ""), re.IGNORECASE)
                )
            ]
            return self._uia_windows_from_native_rows(matching_rows)

        # Non-Windows fallback retained for tests and unsupported developer hosts.
        try:
            children = list(parent_window.children(control_type="Window"))
        except Exception:
            return []
        rows: List[Any] = []
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

    def _send_key_f4(self, hwnd: int) -> bool:
        if hwnd <= 0:
            return False
        user32 = self._user32()
        down = bool(user32.PostMessageW(hwnd, WM_KEYDOWN, VK_F4, 0))
        up = bool(user32.PostMessageW(hwnd, WM_KEYUP, VK_F4, 0))
        return bool(down and up)

    def _send_key_f7(self, hwnd: int) -> bool:
        if hwnd <= 0:
            return False
        user32 = self._user32()
        down = bool(user32.PostMessageW(hwnd, WM_KEYDOWN, VK_F7, 0))
        up = bool(user32.PostMessageW(hwnd, WM_KEYUP, VK_F7, 0))
        return bool(down and up)

    def _list_process_ids_by_image(self, image_name: str) -> List[int]:
        target = str(image_name or "").strip().lower()
        if not target:
            return []
        if os.name == "nt":
            return _native_process_ids_by_image(target)
        try:
            cp = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {target}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                errors="replace",
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

    def _native_menu_rows(self, main_handle: int) -> List[Dict[str, Any]]:
        hwnd = int(main_handle or 0)
        if hwnd <= 0 or os.name != "nt":
            return []
        user32 = self._user32()
        try:
            user32.GetMenu.restype = ctypes.c_void_p
            user32.GetSubMenu.restype = ctypes.c_void_p
            user32.GetMenuItemID.restype = ctypes.c_uint
            root_menu = int(user32.GetMenu(hwnd) or 0)
        except Exception:
            return []
        if root_menu <= 0:
            return []
        rows: List[Dict[str, Any]] = []

        def _walk(menu_handle: int, parent_path: List[str], depth: int) -> None:
            if depth > 4:
                return
            try:
                count = int(user32.GetMenuItemCount(menu_handle))
            except Exception:
                return
            for position in range(max(0, count)):
                buffer = ctypes.create_unicode_buffer(512)
                try:
                    user32.GetMenuStringW(menu_handle, position, buffer, len(buffer), MF_BYPOSITION)
                    title = str(buffer.value or "").strip()
                    submenu = int(user32.GetSubMenu(menu_handle, position) or 0)
                    command_id_raw = int(user32.GetMenuItemID(menu_handle, position))
                except Exception:
                    continue
                command_id = 0 if command_id_raw in {-1, 0xFFFFFFFF} else command_id_raw
                path = [*parent_path, title] if title else list(parent_path)
                rows.append(
                    {
                        "title": title,
                        "path": " -> ".join(item.replace("&", "") for item in path if item),
                        "command_id": command_id,
                        "depth": depth,
                    }
                )
                if submenu > 0:
                    _walk(submenu, path, depth + 1)

        _walk(root_menu, [], 0)
        return rows

    def _native_menu_command_enabled(self, main_handle: int, command_id: int) -> Optional[bool]:
        """Read one exact menu item's enabled bit without opening or invoking the menu."""

        hwnd = int(main_handle or 0)
        command = int(command_id or 0)
        if hwnd <= 0 or command <= 0 or os.name != "nt":
            return None
        user32 = self._user32()
        try:
            user32.GetMenu.restype = ctypes.c_void_p
            root_menu = int(user32.GetMenu(hwnd) or 0)
            if root_menu <= 0:
                return None
            state = int(user32.GetMenuState(root_menu, command, MF_BYCOMMAND)) & 0xFFFFFFFF
        except Exception:
            return None
        if state == 0xFFFFFFFF:
            return None
        return not bool(state & (MF_GRAYED | MF_DISABLED))

    def _trigger_solve_native(self, main_handle: int) -> Dict[str, Any]:
        menu_rows = self._native_menu_rows(main_handle)
        candidate = _solve_menu_candidate(menu_rows)
        if candidate is not None:
            command_id = int(candidate.get("command_id", 0) or 0)
            sent = self._send_message_timeout(main_handle, WM_COMMAND, command_id, 0)
            # A synchronous menu handler can enter a modal loop before it
            # returns. In that case SendMessageTimeout reports a timeout even
            # though the command was dispatched; never issue a second F4.
            return {
                "trigger": "hwnd_menu_command",
                "status": "sent" if sent else "dispatch_timed_out",
                "main_handle": int(main_handle),
                "command_id": command_id,
                "menu_path": str(candidate.get("path", "") or ""),
            }
        sent = self._send_key_f4(main_handle)
        return {
            "trigger": "hwnd_postmessage_f4",
            "status": "sent" if sent else "rejected",
            "main_handle": int(main_handle),
            "menu_candidates": [
                row
                for row in menu_rows
                if int(row.get("command_id", 0) or 0) > 0
                and (
                    85 <= int(row.get("command_id", 0) or 0) <= 115
                    or re.search(r"calculate|solve|berechnen|processing", str(row.get("path", "")), re.IGNORECASE)
                )
            ][:40],
        }

    def _trigger_vacs_reimport_native(self, main_handle: int) -> Dict[str, Any]:
        sent = self._send_key_f7(main_handle)
        return {
            "trigger": "hwnd_postmessage_f7",
            "status": "sent" if sent else "rejected",
            "main_handle": int(main_handle),
        }

    def _start_vacs_for_handoff(self, main_handle: int) -> Dict[str, Any]:
        """Request VACS through AKABAK's F7 handoff instead of starting it externally.

        VACS uses an in-process COM/RPC link to AKABAK.  A direct ``Popen`` can
        create a viewer that only receives the mesh or reports an unavailable
        RPC server.  F7 lets AKABAK create and bind the viewer itself.
        """

        existing = self._list_vacs_process_ids()
        if existing:
            return {"status": "already_running", "pids": existing, "method": "existing_vacs"}
        trigger = self._trigger_vacs_reimport_native(int(main_handle or 0))
        return {**trigger, "method": "akabak_f7"}

    def _refresh_owned_tool_process_ids(self) -> Dict[str, List[int]]:
        baseline_akabak = {int(pid) for pid in getattr(self, "initial_akabak_pids", set()) if int(pid) > 0}
        baseline_vacs = {int(pid) for pid in getattr(self, "initial_vacs_pids", set()) if int(pid) > 0}
        current_akabak = {int(pid) for pid in self._list_akabak_process_ids() if int(pid) > 0}
        current_vacs = {int(pid) for pid in self._list_vacs_process_ids() if int(pid) > 0}
        owned_akabak = set(getattr(self, "owned_akabak_pids", set()))
        owned_vacs = set(getattr(self, "owned_vacs_pids", set()))
        owned_akabak.update(current_akabak - baseline_akabak)
        owned_vacs.update(current_vacs - baseline_vacs)
        self.owned_akabak_pids = owned_akabak
        self.owned_vacs_pids = owned_vacs
        return {
            "akabak": sorted(owned_akabak),
            "vacs": sorted(owned_vacs),
        }

    def _terminate_owned_tool_processes(
        self,
        *,
        grace_s: float = 5.0,
        preserve_vacs: bool = False,
    ) -> Dict[str, Any]:
        """Wait briefly, then terminate only tool processes created this session."""

        owned = self._refresh_owned_tool_process_ids()
        deadline = time.monotonic() + max(0.0, float(grace_s))

        def _remaining() -> Dict[str, List[int]]:
            refreshed = self._refresh_owned_tool_process_ids()
            owned["akabak"] = sorted(set(owned["akabak"]) | set(refreshed["akabak"]))
            owned["vacs"] = sorted(set(owned["vacs"]) | set(refreshed["vacs"]))
            current_akabak = set(self._list_akabak_process_ids())
            current_vacs = set(self._list_vacs_process_ids())
            return {
                "akabak": sorted(set(owned["akabak"]) & current_akabak),
                "vacs": [] if preserve_vacs else sorted(set(owned["vacs"]) & current_vacs),
            }

        remaining = _remaining()
        # Observe the whole grace window even when initially clean: AKABAK can
        # spawn its worker process several seconds after the launcher exits.
        while time.monotonic() < deadline:
            time.sleep(0.1)
            remaining = _remaining()

        kill_results: List[Dict[str, Any]] = []
        for app_name, pids in remaining.items():
            for pid in pids:
                try:
                    completed = subprocess.run(
                        ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        errors="replace",
                        check=False,
                        timeout=5.0,
                    )
                    kill_results.append(
                        {
                            "app": app_name,
                            "pid": int(pid),
                            "returncode": int(completed.returncode),
                        }
                    )
                except Exception as exc:
                    kill_results.append({"app": app_name, "pid": int(pid), "error": repr(exc)})

        final_deadline = time.monotonic() + 2.0
        final_remaining = _remaining()
        while any(final_remaining.values()) and time.monotonic() < final_deadline:
            time.sleep(0.1)
            final_remaining = _remaining()
        return {
            "owned": owned,
            "forced": kill_results,
            "remaining": final_remaining,
        }

    def _process_top_level_windows(self, *, process_id: Optional[int] = None) -> List[Any]:
        pid = int(process_id or self.session.process_id or 0)
        if pid <= 0:
            return []
        if os.name == "nt":
            return self._uia_windows_from_native_rows(
                self._native_process_window_rows(process_id=pid)
            )
        try:
            from pywinauto import Desktop
        except Exception:
            return []
        try:
            return list(Desktop(backend="uia").windows(process=pid))
        except Exception:
            return []

    def _window_signature_row(self, window: Any) -> Dict[str, Any]:
        state = vars(window) if hasattr(window, "__dict__") else {}
        handle = self._window_handle(window)
        if handle > 0:
            try:
                is_visible = bool(self._user32().IsWindowVisible(handle))
            except Exception:
                is_visible = False
            return {
                "title": str(state.get("_wut_native_title") or self._native_window_text(handle)),
                "class_name": str(state.get("_wut_native_class_name") or self._native_window_class(handle)),
                "control_type": "native_hwnd",
                "automation_id": "",
                "native_handle": handle,
                "is_visible": is_visible,
            }
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

    def _native_window_text(self, hwnd: int, *, max_chars: int = 2048) -> str:
        if hwnd <= 0:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(max(2, int(max_chars)))
            self._user32().GetWindowTextW(hwnd, buffer, len(buffer))
            return str(buffer.value or "").strip()
        except Exception:
            return ""

    def _native_window_class(self, hwnd: int, *, max_chars: int = 256) -> str:
        if hwnd <= 0:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(max(2, int(max_chars)))
            self._user32().GetClassNameW(hwnd, buffer, len(buffer))
            return str(buffer.value or "").strip()
        except Exception:
            return ""

    def _native_vacs_window_metrics(self, process_id: int) -> List[Dict[str, Any]]:
        """Inspect VACS HWNDs without recursive COM/UIA traversal.

        Repeated ``pywinauto`` ``descendants()`` calls can raise an uncatchable
        Windows COM exception while VACS mutates its graph tree during a solve.
        Native HWND enumeration supplies the readiness metrics needed here and
        keeps the fragile UIA tree out of the high-frequency polling path.
        """
        pid = int(process_id or 0)
        if pid <= 0 or not hasattr(ctypes, "windll") or not hasattr(ctypes, "WINFUNCTYPE"):
            return []
        user32 = self._user32()
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        rows: List[Dict[str, Any]] = []

        def _top_level_callback(raw_hwnd: int, _lparam: int) -> int:
            hwnd = int(raw_hwnd or 0)
            owner_pid = ctypes.c_ulong(0)
            try:
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            except Exception:
                return 1
            if int(owner_pid.value) != pid:
                return 1

            controls_count = 0
            graph_keyword_hits = 0

            def _child_callback(raw_child_hwnd: int, _child_lparam: int) -> int:
                nonlocal controls_count, graph_keyword_hits
                child_hwnd = int(raw_child_hwnd or 0)
                controls_count += 1
                title = self._native_window_text(child_hwnd).lower()
                class_name = self._native_window_class(child_hwnd).lower()
                if any(token in title for token in VACS_GRAPH_KEYWORDS) or any(
                    token in class_name for token in VACS_GRAPH_CLASS_NAMES
                ):
                    graph_keyword_hits += 1
                return 1

            child_callback = callback_type(_child_callback)
            try:
                user32.EnumChildWindows(hwnd, child_callback, 0)
            except Exception:
                pass
            try:
                is_visible = bool(user32.IsWindowVisible(hwnd))
            except Exception:
                is_visible = False
            rows.append(
                {
                    "title": self._native_window_text(hwnd),
                    "class_name": self._native_window_class(hwnd),
                    "control_type": "native_hwnd",
                    "automation_id": "",
                    "native_handle": hwnd,
                    "is_visible": is_visible,
                    "controls_count": int(controls_count),
                    "graph_keyword_hits": int(graph_keyword_hits),
                }
            )
            return 1

        top_level_callback = callback_type(_top_level_callback)
        try:
            user32.EnumWindows(top_level_callback, 0)
        except Exception:
            return []
        return rows

    def _native_process_window_rows(
        self,
        *,
        process_id: int,
        parent_handle: int = 0,
    ) -> List[Dict[str, Any]]:
        """Enumerate process HWNDs without traversing the COM/UIA tree."""

        pid = int(process_id or 0)
        if pid <= 0 or not hasattr(ctypes, "windll") or not hasattr(ctypes, "WINFUNCTYPE"):
            return []
        user32 = self._user32()
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        handles: List[int] = []
        seen: set[int] = set()

        def _record(raw_hwnd: int) -> None:
            hwnd = int(raw_hwnd or 0)
            if hwnd <= 0 or hwnd in seen:
                return
            owner_pid = ctypes.c_ulong(0)
            try:
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            except Exception:
                return
            if int(owner_pid.value) != pid:
                return
            seen.add(hwnd)
            handles.append(hwnd)

        def _callback(raw_hwnd: int, _lparam: int) -> int:
            _record(raw_hwnd)
            return 1

        callback = callback_type(_callback)
        try:
            user32.EnumWindows(callback, 0)
        except Exception:
            pass
        if int(parent_handle or 0) > 0:
            child_callback = callback_type(_callback)
            try:
                user32.EnumChildWindows(int(parent_handle), child_callback, 0)
            except Exception:
                pass

        rows: List[Dict[str, Any]] = []
        for hwnd in handles:
            try:
                is_visible = bool(user32.IsWindowVisible(hwnd))
            except Exception:
                is_visible = False
            rows.append(
                {
                    "title": self._native_window_text(hwnd),
                    "class_name": self._native_window_class(hwnd),
                    "native_handle": hwnd,
                    "is_visible": is_visible,
                }
            )
        return rows

    def _native_descendant_window_rows(self, *, process_id: int, parent_handle: int) -> List[Dict[str, Any]]:
        """Return bounded native descendants for one exact process-owned parent HWND."""

        pid = int(process_id or 0)
        parent = int(parent_handle or 0)
        if pid <= 0 or parent <= 0 or not hasattr(ctypes, "windll") or not hasattr(ctypes, "WINFUNCTYPE"):
            return []
        user32 = self._user32()
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        rows: List[Dict[str, Any]] = []

        def _callback(raw_hwnd: int, _lparam: int) -> int:
            hwnd = int(raw_hwnd or 0)
            owner_pid = ctypes.c_ulong(0)
            try:
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            except Exception:
                return 1
            if int(owner_pid.value) != pid:
                return 1
            rows.append(
                {
                    "title": self._read_window_text_by_handle(hwnd, max_chars=4096),
                    "class_name": self._native_window_class(hwnd),
                    "native_handle": hwnd,
                }
            )
            return 1

        callback = callback_type(_callback)
        try:
            user32.EnumChildWindows(parent, callback, 0)
        except Exception:
            return []
        return rows[:256]

    def _dismiss_vacs_startup_editors(self, process_ids: Sequence[int]) -> List[Dict[str, Any]]:
        """Close only the two known VACS first-start RTF editors by exact content signatures."""

        actions: List[Dict[str, Any]] = []
        for pid in [int(item) for item in process_ids if int(item) > 0]:
            for row in self._native_process_window_rows(process_id=pid):
                hwnd = int(row.get("native_handle", 0) or 0)
                title = str(row.get("title", "") or "").strip()
                class_name = str(row.get("class_name", "") or "").strip().lower()
                if (
                    hwnd <= 0
                    or class_name != VACS_STARTUP_EDITOR_CLASS_NAME
                    or not VACS_STARTUP_EDITOR_TITLE_RE.fullmatch(title)
                ):
                    continue
                descendants = self._native_descendant_window_rows(process_id=pid, parent_handle=hwnd)
                content = " ".join(str(item.get("title", "") or "") for item in descendants).lower()
                signature = next(
                    (tokens for tokens in VACS_STARTUP_EDITOR_SIGNATURES if all(token in content for token in tokens)),
                    None,
                )
                if signature is None:
                    continue
                closed = self._send_message_timeout(hwnd, WM_CLOSE, timeout_ms=1000)
                actions.append(
                    {
                        "pid": pid,
                        "native_handle": hwnd,
                        "title": title,
                        "class_name": class_name,
                        "signature": list(signature),
                        "status": "close_sent" if closed else "close_rejected",
                    }
                )
        return actions

    def _uia_windows_from_native_rows(self, rows: Sequence[Dict[str, Any]]) -> List[Any]:
        if not rows:
            return []
        try:
            from pywinauto import Desktop
        except Exception:
            return []
        desktop = Desktop(backend="uia")
        windows: List[Any] = []
        for row in rows:
            hwnd = int(row.get("native_handle", 0) or 0)
            if hwnd <= 0:
                continue
            try:
                window = desktop.window(handle=hwnd)
                try:
                    setattr(window, "_wut_native_handle", hwnd)
                    setattr(window, "_wut_native_title", str(row.get("title", "") or ""))
                    setattr(window, "_wut_native_class_name", str(row.get("class_name", "") or ""))
                except Exception:
                    pass
                windows.append(window)
            except Exception:
                continue
        return windows

    def _vacs_ui_snapshot(self) -> Dict[str, Any]:
        pid_rows: Dict[str, Any] = {}
        max_controls = 0
        max_keyword_hits = 0
        vacs_pids = self._list_vacs_process_ids()
        for pid in vacs_pids:
            all_rows = self._native_vacs_window_metrics(pid)
            for metrics in all_rows:
                max_controls = max(max_controls, int(metrics.get("controls_count", 0)))
                max_keyword_hits = max(max_keyword_hits, int(metrics.get("graph_keyword_hits", 0)))
            # Helper/editor HWNDs often enumerate before the visible VACS forms.
            # Keep the strongest diagnostic rows, but compute readiness over all.
            diagnostic_rows = sorted(
                all_rows,
                key=lambda row: (
                    bool(row.get("is_visible")),
                    int(row.get("graph_keyword_hits", 0)),
                    int(row.get("controls_count", 0)),
                ),
                reverse=True,
            )[:8]
            pid_rows[str(pid)] = diagnostic_rows
        return {
            "pids": vacs_pids,
            "windows": pid_rows,
            "max_controls_count": int(max_controls),
            "max_graph_keyword_hits": int(max_keyword_hits),
            "snapshot_backend": "win32_hwnd",
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
        akabak_cpu_times_s = {
            str(pid): cpu_time
            for pid in akabak_pids
            if (cpu_time := _process_cpu_time_seconds(pid)) is not None
        }
        worker_pids = [pid for pid in akabak_pids if pid != main_pid]
        worker_cpu_times_s = {
            str(pid): akabak_cpu_times_s[str(pid)] for pid in worker_pids if str(pid) in akabak_cpu_times_s
        }
        return {
            "main_pid": main_pid,
            "akabak_pids": akabak_pids,
            "vacs_pids": vacs_pids,
            "worker_akabak_pids": worker_pids,
            "akabak_cpu_times_s": akabak_cpu_times_s,
            "worker_cpu_times_s": worker_cpu_times_s,
            "progress_window_present": bool(progress is not None),
            "solve_command_enabled": self._native_menu_command_enabled(
                int(getattr(self, "_solve_main_handle", 0) or 0),
                CALCULATE_ALL_COMMAND_ID,
            ),
            "vacs_ui": vacs_ui,
        }

    def _read_window_text_by_handle(self, hwnd: int, max_chars: int = 16384) -> str:
        if hwnd <= 0:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(max_chars)
            result = ctypes.c_size_t(0)
            ok = self._user32().SendMessageTimeoutW(
                hwnd,
                WM_GETTEXT,
                max_chars - 1,
                buffer,
                SMTO_ABORTIFHUNG,
                500,
                ctypes.byref(result),
            )
            if ok:
                value = str(buffer.value or "").strip()
                if value:
                    return value
        except Exception:
            pass
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
        return self._send_message_timeout(parent_hwnd, WM_COMMAND, wparam, control_hwnd)

    def _send_message_timeout(
        self,
        hwnd: int,
        message: int,
        wparam: Any = 0,
        lparam: Any = 0,
        *,
        timeout_ms: int = 1000,
    ) -> bool:
        """Send one cross-process window message without an unbounded wait."""

        target = int(hwnd or 0)
        if target <= 0:
            return False
        try:
            result = ctypes.c_size_t()
            sent = self._user32().SendMessageTimeoutW(
                target,
                int(message),
                wparam,
                lparam,
                SMTO_ABORTIFHUNG,
                max(1, int(timeout_ms)),
                ctypes.byref(result),
            )
            return bool(sent)
        except Exception:
            return False

    def _send_bm_click(self, control_hwnd: int, *, timeout_ms: int = 1000) -> bool:
        """Click one known button HWND without mouse input or unbounded UIA."""

        hwnd = int(control_hwnd or 0)
        if hwnd <= 0:
            return False
        return self._send_message_timeout(hwnd, BM_CLICK, timeout_ms=timeout_ms)

    def _post_native_mouse_click(self, control_hwnd: int) -> bool:
        """Post a window-local click without moving the real mouse cursor."""

        hwnd = int(control_hwnd or 0)
        if hwnd <= 0:
            return False
        try:
            user32 = self._user32()
            rect = _ClientRect()
            if not bool(user32.GetClientRect(hwnd, ctypes.byref(rect))):
                return False
            x = max(0, int(rect.right - rect.left) // 2)
            y = max(0, int(rect.bottom - rect.top) // 2)
            lparam = (y << 16) | (x & 0xFFFF)
            down = bool(user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam))
            # Delphi/Raize controls can discard an immediate up message while
            # they are still processing the pressed-state transition.
            time.sleep(0.05)
            up = bool(user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam))
            return bool(down and up)
        except Exception:
            return False

    def _post_native_text_entry(self, edit_hwnd: int, value: str) -> bool:
        """Enter text through one edit HWND so its owner receives edit events."""

        hwnd = int(edit_hwnd or 0)
        if hwnd <= 0:
            return False
        user32 = self._user32()
        try:
            result = ctypes.c_size_t()
            selected = user32.SendMessageTimeoutW(
                hwnd,
                EM_SETSEL,
                0,
                -1,
                SMTO_ABORTIFHUNG,
                1000,
                ctypes.byref(result),
            )
            cleared = user32.SendMessageTimeoutW(
                hwnd,
                WM_CLEAR,
                0,
                0,
                SMTO_ABORTIFHUNG,
                1000,
                ctypes.byref(result),
            )
            if not selected or not cleared:
                return False
            for character in str(value):
                accepted = user32.SendMessageTimeoutW(
                    hwnd,
                    WM_CHAR,
                    ord(character),
                    1,
                    SMTO_ABORTIFHUNG,
                    500,
                    ctypes.byref(result),
                )
                if not accepted:
                    return False
            return True
        except Exception:
            return False

    def _send_native_dialog_enter(self, dialog_hwnd: int, edit_hwnd: int) -> bool:
        """Send one real Enter key only after exact dialog/control focus validation."""

        dialog = int(dialog_hwnd or 0)
        edit = int(edit_hwnd or 0)
        if dialog <= 0 or edit <= 0 or os.name != "nt" or not hasattr(ctypes, "windll"):
            return False
        user32 = self._user32()
        kernel32 = ctypes.windll.kernel32
        try:
            if not bool(user32.IsWindow(dialog)) or not bool(user32.IsWindow(edit)):
                return False
            target_thread = int(user32.GetWindowThreadProcessId(dialog, None) or 0)
            current_thread = int(kernel32.GetCurrentThreadId() or 0)
            if target_thread <= 0 or current_thread <= 0:
                return False
            attached = target_thread != current_thread and bool(
                user32.AttachThreadInput(current_thread, target_thread, True)
            )
            if target_thread != current_thread and not attached:
                return False
            try:
                user32.SetForegroundWindow(dialog)
                user32.SetActiveWindow(dialog)
                user32.SetFocus(edit)
                if int(user32.GetFocus() or 0) != edit:
                    return False
                user32.keybd_event(VK_RETURN, 0, 0, 0)
                user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, target_thread, False)
            return True
        except Exception:
            return False

    def _record_watchdog_events(self, *, step: str, events: List[Dict[str, Any]]) -> None:
        if not events:
            return
        for item in events:
            row = {"step": str(step), **dict(item)}
            self.watchdog_events.append(row)

    def _window_title(self, control: Any) -> str:
        state = vars(control) if hasattr(control, "__dict__") else {}
        cached_title = str(state.get("_wut_native_title", "") or "").strip()
        if cached_title:
            return cached_title
        handle = self._window_handle(control)
        if handle > 0:
            native_title = self._native_window_text(handle)
            if native_title:
                return native_title
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
        root_handle = self._window_handle(root)
        if os.name == "nt" and root_handle > 0:
            for control in self._native_descendant_controls(root_handle):
                info = control.element_info
                if control_type and str(info.control_type) != control_type:
                    continue
                if automation_id and str(info.automation_id) != automation_id:
                    continue
                if class_name_regex and not re.search(class_name_regex, str(info.class_name), re.IGNORECASE):
                    continue
                if title_regex and not _title_matches_regex(title_regex, str(info.name)):
                    continue
                return control
            return None

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
            if title_regex and not _title_matches_regex(title_regex, info_title):
                continue
            return control
        return None

    def _native_descendant_controls(self, root_handle: int) -> List[_NativeHwndControl]:
        hwnd = int(root_handle or 0)
        if hwnd <= 0 or not hasattr(ctypes, "WINFUNCTYPE"):
            return []
        user32 = self._user32()
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        rows: List[_NativeHwndControl] = []

        def _callback(raw_child_hwnd: int, _lparam: int) -> int:
            child_hwnd = int(raw_child_hwnd or 0)
            try:
                control_id = int(user32.GetDlgCtrlID(child_hwnd) or 0)
            except Exception:
                control_id = 0
            rows.append(
                _NativeHwndControl(
                    user32=user32,
                    handle=child_hwnd,
                    title=self._native_window_text(child_hwnd),
                    class_name=self._native_window_class(child_hwnd),
                    control_id=control_id,
                )
            )
            return 1

        callback = callback_type(_callback)
        try:
            user32.EnumChildWindows(hwnd, callback, 0)
        except Exception:
            return []
        return rows

    def _find_open_dialog_controls(self, file_dialog: Any) -> Tuple[Optional[Any], Optional[Any]]:
        dialog_handle = self._window_handle(file_dialog)
        if os.name == "nt" and dialog_handle > 0:
            edit_handle = self._dialog_filename_edit_handle(dialog_handle)
            edit = None
            if edit_handle > 0:
                try:
                    edit_id = int(self._user32().GetDlgCtrlID(edit_handle) or 0)
                except Exception:
                    edit_id = 0
                edit = _NativeHwndControl(
                    user32=self._user32(),
                    handle=edit_handle,
                    title=self._native_window_text(edit_handle),
                    class_name=self._native_window_class(edit_handle),
                    control_id=edit_id,
                )
            button = self._find_first_control(
                file_dialog,
                control_type="Button",
                automation_id=str(IDOK),
            ) or self._find_first_control(
                file_dialog,
                control_type="Button",
                title_regex=r"(open|oeffnen|ok)",
            )
            return edit, button

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

    def _dialog_filename_edit_handle(self, dialog_handle: int) -> int:
        dialog_hwnd = int(dialog_handle or 0)
        if dialog_hwnd <= 0:
            return 0
        user32 = self._user32()
        try:
            container = int(user32.GetDlgItem(dialog_hwnd, OPEN_FILE_NAME_CONTROL_ID) or 0)
        except Exception:
            return 0
        if container <= 0:
            return 0
        if re.search(r"Edit", self._native_window_class(container), re.IGNORECASE):
            return container
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        edit_handle = 0

        def _callback(raw_hwnd: int, _lparam: int) -> int:
            nonlocal edit_handle
            hwnd = int(raw_hwnd or 0)
            if re.search(r"Edit", self._native_window_class(hwnd), re.IGNORECASE):
                edit_handle = hwnd
                return 0
            return 1

        callback = callback_type(_callback)
        try:
            user32.EnumChildWindows(container, callback, 0)
        except Exception:
            return 0
        return edit_handle

    def _dialog_has_filename_control(self, dialog_window: Any) -> bool:
        handle = self._window_handle(dialog_window)
        if handle > 0:
            if self._dialog_filename_edit_handle(handle) > 0:
                return True
            if os.name == "nt":
                # A known HWND must stay on the bounded Win32 path. Resolving
                # ``descendants()`` here can block indefinitely in UIA/COM.
                return False
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
        edit_handle = self._dialog_filename_edit_handle(dialog_handle)
        if edit_handle > 0:
            edit_value = self._read_window_text_by_handle(edit_handle)
            if edit_value:
                return edit_value
        try:
            container_handle = int(self._user32().GetDlgItem(dialog_handle, OPEN_FILE_NAME_CONTROL_ID) or 0)
        except Exception:
            container_handle = 0
        if container_handle > 0:
            container_value = self._read_window_text_by_handle(container_handle)
            if container_value:
                return container_value
        readback = ctypes.create_unicode_buffer(2048)
        self._user32().GetDlgItemTextW(dialog_handle, OPEN_FILE_NAME_CONTROL_ID, readback, 2047)
        return str(readback.value or "")

    def _write_dialog_filename_verified(self, *, dialog_handle: int, value: str) -> Dict[str, Any]:
        """Replace and verify the common-dialog filename without keyboard input.

        ``GetWindowTextW`` cannot reliably read an edit control owned by another
        process. Use the system ``WM_GETTEXT`` message via
        ``_read_window_text_by_handle`` and never submit the dialog until the
        exact absolute path can be read back.
        """

        user32 = self._user32()
        dialog_hwnd = int(dialog_handle or 0)
        target_value = str(value)
        try:
            container_handle = int(user32.GetDlgItem(dialog_hwnd, OPEN_FILE_NAME_CONTROL_ID) or 0)
        except Exception:
            container_handle = 0
        edit_handle = self._dialog_filename_edit_handle(dialog_hwnd)

        def _normalize(text: str) -> str:
            return str(text or "").strip().strip('"').replace("/", "\\").lower()

        expected = _normalize(target_value)

        def _readbacks() -> Dict[str, str]:
            values = {
                "edit": self._read_window_text_by_handle(edit_handle) if edit_handle > 0 else "",
                "container": self._read_window_text_by_handle(container_handle) if container_handle > 0 else "",
                "dialog": self._dialog_filename_readback(dialog_hwnd),
            }
            return values

        attempts: List[Dict[str, Any]] = []

        def _record(method: str, action: Any) -> Optional[Dict[str, Any]]:
            error = ""
            result: Any = None
            try:
                result = action()
            except Exception as exc:
                error = repr(exc)
            readbacks = _readbacks()
            if edit_handle > 0:
                verified = bool(expected) and _normalize(readbacks.get("edit", "")) == expected
            else:
                verified = bool(expected) and any(_normalize(item) == expected for item in readbacks.values())
            attempt = {
                "method": method,
                "result": bool(result),
                "readbacks": readbacks,
                "verified": verified,
                "error": error or None,
            }
            attempts.append(attempt)
            return attempt if verified else None

        text_pointer = ctypes.c_wchar_p(target_value)
        actions: List[Tuple[str, Any]] = []
        if dialog_hwnd > 0:
            def _set_common_dialog_text() -> Any:
                message_result = ctypes.c_size_t(0)
                return user32.SendMessageTimeoutW(
                    dialog_hwnd,
                    CDM_SETCONTROLTEXT,
                    OPEN_FILE_NAME_CONTROL_ID,
                    text_pointer,
                    SMTO_ABORTIFHUNG,
                    1000,
                    ctypes.byref(message_result),
                )

            actions.append(("CDM_SETCONTROLTEXT_id1148", _set_common_dialog_text))
            actions.append(
                (
                    "SetDlgItemTextW_id1148",
                    lambda: user32.SetDlgItemTextW(dialog_hwnd, OPEN_FILE_NAME_CONTROL_ID, text_pointer),
                )
            )
        for label, hwnd in (("edit", edit_handle), ("container", container_handle)):
            if hwnd <= 0:
                continue
            actions.append((f"SetWindowTextW_{label}", lambda hwnd=hwnd: user32.SetWindowTextW(hwnd, text_pointer)))

            def _send_text(target_hwnd: int = hwnd) -> Any:
                message_result = ctypes.c_size_t(0)
                ok = user32.SendMessageTimeoutW(
                    target_hwnd,
                    WM_SETTEXT,
                    0,
                    text_pointer,
                    SMTO_ABORTIFHUNG,
                    1000,
                    ctypes.byref(message_result),
                )
                return bool(ok)

            actions.append((f"SendMessageTimeoutW_WM_SETTEXT_{label}", _send_text))

        for method, action in actions:
            verified_attempt = _record(method, action)
            if verified_attempt is not None:
                return {
                    "verified": True,
                    "method": method,
                    "readbacks": verified_attempt["readbacks"],
                    "attempts": attempts,
                    "edit_handle": edit_handle,
                    "container_handle": container_handle,
                }

        return {
            "verified": False,
            "method": "",
            "readbacks": _readbacks(),
            "attempts": attempts,
            "edit_handle": edit_handle,
            "container_handle": container_handle,
        }

    def _edit_readback(self, edit_control: Optional[Any]) -> str:
        if edit_control is None:
            return ""
        if isinstance(edit_control, _NativeHwndControl):
            return self._read_window_text_by_handle(self._window_handle(edit_control))
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

        if os.name != "nt":
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
        # ``TRzDialogButtons`` is the interpreter's permanent Apply/Close
        # container, not a modal. Match only actual common-dialog windows.
        rows = self._child_windows(interpreter_window, class_name_regex=r"^(#32770|Dialog)$")
        if rows:
            return rows[0]
        return None

    def _modal_details(self, modal_window: Any) -> Dict[str, Any]:
        signature = self._window_signature_row(modal_window)
        details: Dict[str, Any] = {
            "title": str(signature.get("title", "") or ""),
            "class_name": str(signature.get("class_name", "") or ""),
            "message": "",
            "buttons": [],
        }
        messages: List[str] = []
        buttons: List[str] = []
        modal_handle = self._window_handle(modal_window)
        try:
            controls = (
                self._native_descendant_controls(modal_handle)
                if os.name == "nt" and modal_handle > 0
                else list(modal_window.descendants())
            )
            for control in controls:
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
            return self._send_bm_click(handle)
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

        if os.name == "nt":
            # A blind Enter is unsafe for AKABAK's VCL interpreter: focus can
            # remain on "Open ABEC Project" and reopen the file dialog after a
            # successful Start/Apply action. Native modal enumeration above is
            # authoritative; without a detected modal there is nothing to
            # confirm.
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
            main_handle = self._window_handle(main_window)
            process_id = int(self.session.process_id or 0)
            main_present = bool(main_handle > 0 and self._user32().IsWindow(main_handle))
            process_present = process_id in self._list_akabak_process_ids()
            if not main_present or not process_present:
                return True, {
                    "status": "akabak_exited_before_apply",
                    "main_present": main_present,
                    "process_present": process_present,
                    "process_id": process_id,
                }
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
        apply_enabled = True
        try:
            apply_enabled = bool(apply_button.is_enabled())
        except Exception:
            apply_enabled = True
        if not apply_enabled:
            return False, {"status": "waiting_apply_button_enabled"}

        report_text = self._read_interpreter_report_text(interpreter)
        report_normalized = str(report_text or "").strip()
        has_import_progress = bool(
            len(report_normalized) > len("Importing whole ABEC project")
            and re.search(r"(opening|loading|interpreting|completed|finished)", report_normalized, re.IGNORECASE)
        )
        now = time.monotonic()
        previous = str(getattr(self, "_import_report_candidate", "") or "")
        if report_normalized != previous:
            self._import_report_candidate = report_normalized
            self._import_report_stable_since = now
            return False, {
                "status": "waiting_import_report_stable",
                "report_chars": len(report_normalized),
                "has_import_progress": has_import_progress,
            }
        stable_since = float(getattr(self, "_import_report_stable_since", now) or now)
        stable_for_s = max(0.0, now - stable_since)
        if has_import_progress and stable_for_s >= 0.75:
            return True, {
                "status": "apply_ready",
                # Wait-state dictionaries are copied into persistent JSON
                # diagnostics.  Never leak a live UIA/native control wrapper
                # into that boundary: both pywinauto controls and the native
                # HWND adapter are intentionally not JSON serializable.
                "apply_button_handle": self._window_handle(apply_button),
                "report_chars": len(report_normalized),
                "report_stable_for_s": round(stable_for_s, 3),
            }
        return False, {
            "status": "waiting_import_report_complete",
            "report_chars": len(report_normalized),
            "report_stable_for_s": round(stable_for_s, 3),
            "has_import_progress": has_import_progress,
        }

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

    def _invoke_interpreter_button(
        self,
        *,
        interpreter_window: Any,
        title_regex: str,
        step: str,
        action_name: str,
        prefer_bm_click: bool = False,
    ) -> Dict[str, Any]:
        parent_handle = self._window_handle(interpreter_window)
        if os.name == "nt" and parent_handle > 0:
            native_matches = [
                row
                for row in self._native_process_window_rows(
                    process_id=int(self.session.process_id or 0),
                    parent_handle=parent_handle,
                )
                if int(row.get("native_handle", 0) or 0) != parent_handle
                and re.search(
                    r"TRzBitBtn|TRzMenuButton",
                    str(row.get("class_name", "") or ""),
                    re.IGNORECASE,
                )
                and _title_matches_regex(title_regex, str(row.get("title", "") or ""))
            ]
            self._require(
                bool(native_matches),
                f"Interpreter button for '{action_name}' not found by native HWND lookup.",
                step,
            )
            handle = int(native_matches[0].get("native_handle", 0) or 0)
            if prefer_bm_click and self._send_bm_click(handle):
                invoke_method = "native_bm_click"
            elif self._post_native_mouse_click(handle):
                invoke_method = "native_window_mouse_click"
            elif self._send_bm_click(handle):
                invoke_method = "native_bm_click"
            elif self._send_wm_command_click(parent_hwnd=parent_handle, control_hwnd=handle):
                invoke_method = "native_wm_command_click"
            else:
                self._require(False, f"Native interpreter button click failed for '{action_name}'.", step)
                invoke_method = ""
            return {
                "handle": handle,
                "parent_handle": parent_handle,
                "invoke_method": invoke_method,
                "action_name": action_name,
            }

        target = self._find_first_control(
            interpreter_window,
            class_name_regex=r"TRzBitBtn|TRzMenuButton",
            title_regex=title_regex,
        )
        self._require(target is not None, f"Interpreter button for '{action_name}' not found.", step)
        handle = self._window_handle(target)
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
        if not invoke_method and handle > 0 and self._send_bm_click(handle):
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
                    if close_hwnd > 0 and self._send_bm_click(close_hwnd):
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
            self._send_message_timeout(hwnd, WM_CLOSE)
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
        closed_startup_handles: List[int] = []
        latest_state: Dict[str, Any] = {}

        def _state() -> Tuple[bool, Dict[str, Any]]:
            nonlocal closed_handles, closed_startup_handles, latest_state
            windows = self._process_top_level_windows()
            rows = [self._window_signature_row(window) for window in windows]
            visible = [row for row in rows if bool(row.get("is_visible", False))]
            main_visible = [row for row in visible if int(row.get("native_handle", 0) or 0) == main_handle]
            all_extras = [row for row in visible if int(row.get("native_handle", 0) or 0) != main_handle]
            ignored_extras = [row for row in all_extras if _is_noninteractive_tool_window(row)]
            extras = [row for row in all_extras if not _is_noninteractive_tool_window(row)]
            interpreter_extras = [row for row in extras if self._is_interpreter_window_row(row)]
            startup_extras = [
                row
                for row in extras
                if re.fullmatch(
                    r"TForm_ExampleFiles",
                    str(row.get("class_name", "") or ""),
                    re.IGNORECASE,
                )
            ]

            for row in interpreter_extras:
                hwnd = int(row.get("native_handle", 0) or 0)
                if hwnd <= 0 or hwnd in closed_handles:
                    continue
                self._send_message_timeout(hwnd, WM_CLOSE)
                closed_handles.append(hwnd)

            for row in startup_extras:
                hwnd = int(row.get("native_handle", 0) or 0)
                if hwnd <= 0 or hwnd in closed_startup_handles:
                    continue
                self._send_message_timeout(hwnd, WM_CLOSE)
                closed_startup_handles.append(hwnd)
                self._log(
                    level="info",
                    step=step,
                    event="startup_modal_closed_after_import",
                    payload={"class_name": "TForm_ExampleFiles", "handle": hwnd},
                )

            if main_visible and not extras:
                latest_state = {
                    "status": "main_only_open",
                    "visible_window_count": len(visible),
                    "main_handle": main_handle,
                    "ignored_auxiliary_windows": ignored_extras[:6],
                    "closed_interpreter_handles": list(closed_handles),
                    "closed_startup_handles": list(closed_startup_handles),
                }
                return True, latest_state

            latest_state = {
                "status": "waiting_main_only",
                "visible_window_count": len(visible),
                "main_handle": main_handle,
                "extras": extras[:6],
                "ignored_auxiliary_windows": ignored_extras[:6],
                "closed_interpreter_handles": list(closed_handles),
                "closed_startup_handles": list(closed_startup_handles),
            }
            return False, latest_state

        try:
            return wait_until(
                predicate=_state,
                timeout_s=min(20.0, float(self.step_timeout_s)),
            )
        except TimeoutError as exc:
            self._log(level="error", step=step, event="import_window_close_timeout", payload=latest_state)
            raise RuntimeError(
                "AKABAK import window close assertion timed out: "
                + json.dumps(latest_state, ensure_ascii=False, sort_keys=True)
            ) from exc

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
            "solve_heartbeats": list(self.solve_heartbeats),
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
            payload["dialog_signature"] = self._window_signature_row(file_dialog)
        except Exception:
            payload["dialog_signature"] = {"handle": int(dialog_handle)}
        try:
            payload["process_windows"] = [
                self._window_signature_row(window) for window in self._process_top_level_windows()
            ]
        except Exception as exc:
            payload["process_windows_error"] = repr(exc)
        try:
            idok_handle = int(self._user32().GetDlgItem(dialog_handle, IDOK) or 0)
            payload["open_button"] = {
                "handle": idok_handle,
                "enabled": bool(self._user32().IsWindowEnabled(idok_handle)) if idok_handle > 0 else False,
                "visible": bool(self._user32().IsWindowVisible(idok_handle)) if idok_handle > 0 else False,
            }
        except Exception as exc:
            payload["open_button_error"] = repr(exc)

        try:
            lines: List[str] = []
            capture_controls = (
                self._native_descendant_controls(dialog_handle)
                if os.name == "nt" and dialog_handle > 0
                else list(file_dialog.descendants())
            )
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
            payload["interpreter_signature"] = self._window_signature_row(interpreter_window)
            payload["interpreter_button_states"] = self._interpreter_button_states(interpreter_window)
            payload["interpreter_report_text"] = self._read_interpreter_report_text(interpreter_window)
        else:
            payload["interpreter_signature"] = {"missing": True}

        for key, control in (("main_window", main_window), ("interpreter_window", interpreter_window)):
            if control is None:
                continue
            lines: List[str] = []
            try:
                control_handle = self._window_handle(control)
                children = (
                    self._native_descendant_controls(control_handle)
                    if os.name == "nt" and control_handle > 0
                    else list(control.descendants())
                )
                for child in children[:400]:
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

    def _visible_startup_window_rows(self, *, main_window: Any) -> List[Dict[str, Any]]:
        main_handle = self._window_handle(main_window)
        return [
            row
            for row in self._native_process_window_rows(
                process_id=int(self.session.process_id or 0),
                parent_handle=main_handle,
            )
            if int(row.get("native_handle", 0) or 0) != main_handle
            and bool(row.get("is_visible", False))
            and re.search(
                r"TForm_ExampleFiles",
                str(row.get("class_name", "") or ""),
                re.IGNORECASE,
            )
        ]

    def _dismiss_startup_windows(self, *, main_window: Any, step: str) -> None:
        if os.name == "nt":
            main_handle = self._window_handle(main_window)
            closed_handles: set[int] = set()

            def _startup_rows() -> List[Dict[str, Any]]:
                return self._visible_startup_window_rows(main_window=main_window)

            def _ready_state() -> Tuple[bool, Dict[str, Any]]:
                startup_rows = _startup_rows()
                for row in startup_rows:
                    hwnd = int(row.get("native_handle", 0) or 0)
                    if hwnd <= 0 or hwnd in closed_handles:
                        continue
                    self._send_message_timeout(hwnd, WM_CLOSE)
                    closed_handles.add(hwnd)
                    self._log(
                        level="info",
                        step=step,
                        event="startup_modal_closed",
                        payload={"class_name": "TForm_ExampleFiles", "handle": hwnd},
                    )
                visible = bool(main_handle > 0 and self._user32().IsWindowVisible(main_handle))
                enabled = bool(main_handle > 0 and self._user32().IsWindowEnabled(main_handle))
                ready = bool(visible and enabled and not startup_rows)
                return ready, {
                    "visible": visible,
                    "enabled": enabled,
                    "startup_window_count": len(startup_rows),
                    "closed_handles": sorted(closed_handles),
                }

            readiness = wait_until(
                predicate=_ready_state,
                timeout_s=min(20.0, float(getattr(self, "startup_timeout_s", 20.0))),
                initial_interval_s=0.05,
                max_interval_s=0.3,
            )
            self._log(level="info", step=step, event="main_window_ready", payload=readiness)
            return

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
            self._send_message_timeout(hwnd, WM_CLOSE)
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

        if os.name == "nt" and process_id > 0:
            native_rows = self._native_process_window_rows(
                process_id=process_id,
                parent_handle=interpreter_handle or main_handle,
            )
            for row in native_rows:
                handle = int(row.get("native_handle", 0) or 0)
                if handle <= 0 or handle in {main_handle, interpreter_handle}:
                    continue
                try:
                    control_id = int(self._user32().GetDlgCtrlID(handle) or 0)
                except Exception:
                    control_id = 0
                candidate = _NativeHwndControl(
                    user32=self._user32(),
                    handle=handle,
                    title=str(row.get("title", "") or ""),
                    class_name=str(row.get("class_name", "") or ""),
                    control_id=control_id,
                )
                if self._dialog_has_filename_control(candidate):
                    return candidate
            return None

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
                    class_name = self._native_window_class(handle)
                    if not class_name:
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
        result = ctypes.c_size_t()
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

    def _trigger_interpreter_open_button(self, *, main_window: Any, interpreter_window: Any, step: str) -> Any:
        # AKABAK may create its "Example Files" startup modal lazily after the
        # import command, even when the main window was already reported ready.
        # Close it immediately before clicking the interpreter button so the
        # window message is not silently discarded behind a modal owner.
        self._dismiss_startup_windows(main_window=main_window, step=step)
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
        self._log(level="info", step=step, event="interpreter_open_button_invoked", payload={"action": action})
        dialog = None
        try:
            transition = wait_until(
                predicate=lambda: self._open_dialog_or_startup_transition(main_window=main_window),
                timeout_s=min(2.0, float(self.step_timeout_s)),
                initial_interval_s=0.03,
                max_interval_s=0.2,
                backoff_factor=1.6,
            )
            dialog = transition.get("dialog")
            startup_rows = list(transition.get("startup_rows", []) or [])
            if dialog is None and startup_rows:
                self._dismiss_startup_windows(main_window=main_window, step=step)
                retry_action = self._invoke_interpreter_button(
                    interpreter_window=interpreter_window,
                    title_regex=r"open.*abec",
                    step=step,
                    action_name="open_abec_project_after_startup_modal",
                )
                action = {"initial": action, "retry": retry_action, "startup_modal_count": len(startup_rows)}
                self._log(
                    level="info",
                    step=step,
                    event="interpreter_open_button_retried_after_startup_modal",
                    payload={"action": action},
                )
        except TimeoutError:
            pass
        try:
            if dialog is None:
                dialog = wait_until(
                    predicate=lambda: (
                        self._find_open_file_dialog(main_window=main_window) is not None,
                        self._find_open_file_dialog(main_window=main_window),
                    ),
                    timeout_s=min(8.0, float(self.step_timeout_s)),
                )
        except TimeoutError:
            interpreter_handle = self._window_handle(interpreter_window)
            native_rows = self._native_process_window_rows(
                process_id=int(self.session.process_id or 0),
                parent_handle=interpreter_handle,
            )
            self._log(
                level="error",
                step=step,
                event="open_dialog_missing_after_interpreter_action",
                payload={"action": action, "native_rows": native_rows[:120]},
            )
            raise
        self._require(dialog is not None, "Open-file dialog did not appear after Open ABEC Project action.", step)
        self._log(level="info", step=step, event="interpreter_open_button_triggered", payload={"action": action})
        return dialog

    def _open_dialog_or_startup_transition(self, *, main_window: Any) -> Tuple[bool, Dict[str, Any]]:
        dialog = self._find_open_file_dialog(main_window=main_window)
        startup_rows = self._visible_startup_window_rows(main_window=main_window)
        return bool(dialog is not None or startup_rows), {
            "dialog": dialog,
            "startup_rows": startup_rows,
        }

    def _open_dialog_native_controls_ready(self, dialog_handle: int) -> Tuple[bool, Dict[str, int]]:
        hwnd = int(dialog_handle or 0)
        if hwnd <= 0 or not bool(self._user32().IsWindow(hwnd)):
            return False, {"dialog_handle": hwnd, "edit_handle": 0, "open_button_handle": 0}
        edit_handle = self._dialog_filename_edit_handle(hwnd)
        try:
            open_button_handle = int(self._user32().GetDlgItem(hwnd, IDOK) or 0)
        except Exception:
            open_button_handle = 0
        return bool(edit_handle > 0 and open_button_handle > 0), {
            "dialog_handle": hwnd,
            "edit_handle": edit_handle,
            "open_button_handle": open_button_handle,
        }

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
        if os.name == "nt" and dialog_handle > 0 and not bool(user32.IsWindow(dialog_handle)):
            self._log(
                level="info",
                step=step,
                event="stale_open_dialog_reopen",
                payload={"stale_handle": dialog_handle},
            )
            self._dismiss_startup_windows(main_window=main_window, step=step)
            interpreter = self._find_interpreter_window(main_window=main_window)
            self._require(interpreter is not None, "Interpreter unavailable while reopening stale file dialog.", step)
            file_dialog = self._trigger_interpreter_open_button(
                main_window=main_window,
                interpreter_window=interpreter,
                step=step,
            )
            dialog_handle = self._window_handle(file_dialog)
        self._require(dialog_handle > 0, "Open-file dialog handle unavailable.", step)
        if os.name == "nt":
            self._require(bool(user32.IsWindow(dialog_handle)), "Open-file dialog handle is stale after reopen.", step)
            wait_until(
                predicate=lambda: self._open_dialog_native_controls_ready(dialog_handle),
                timeout_s=min(4.0, float(self.step_timeout_s)),
                initial_interval_s=0.03,
                max_interval_s=0.2,
                backoff_factor=1.6,
            )
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
        confirmation_trace: List[Dict[str, Any]] = []
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
                "combo": self._read_window_text_by_handle(combo_handle) if combo_handle > 0 else "",
                "dialog": self._dialog_filename_readback(dialog_handle),
            }

        def _scoped_filename_readback_state() -> Tuple[bool, Dict[str, str]]:
            state = _readback_snapshot()
            return any(_path_matches(value) for value in state.values()), state

        def _sync_filename_model() -> Dict[str, Any]:
            details: Dict[str, Any] = {"attempted": False, "sent": False, "verified": False}
            if os.name != "nt" or edit_handle <= 0:
                return details
            details["attempted"] = True
            # Shell auto-complete can still be applying a just-selected file
            # filter. Wait briefly, then generate real edit notifications by
            # replacing the text through the exact inner Edit HWND.
            time.sleep(0.35)
            details["sent"] = self._post_native_text_entry(edit_handle, str(project_path))
            details["readback"] = _readback_snapshot()
            details["verified"] = bool(details["sent"]) and _path_matches(
                dict(details["readback"]).get("edit", "")
            )
            return details

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
            if os.name != "nt" and filename_edit is not None:
                if hasattr(filename_edit, "set_focus"):
                    actions.append(("edit_set_focus", lambda: filename_edit.set_focus()))
                if hasattr(filename_edit, "type_keys"):
                    actions.append(("edit_enter", lambda: filename_edit.type_keys("{ENTER}", set_foreground=True)))
            if os.name != "nt" and filename_combo is not None:
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

        def _confirm_by_scoped_input() -> str:
            """Click the exact Open HWND without requiring an active desktop."""

            if open_button_handle <= 0:
                confirmation_trace.append({"phase": "confirm_button", "status": "button_missing"})
                return ""
            try:
                if not bool(user32.IsWindowEnabled(open_button_handle)):
                    confirmation_trace.append({"phase": "confirm_button", "status": "button_disabled"})
                    return ""
                actions = [
                    (
                        "foreground_enter",
                        lambda: self._send_native_dialog_enter(dialog_handle, edit_handle),
                    ),
                    (
                        "post_wm_command_idok",
                        lambda: user32.PostMessageW(dialog_handle, WM_COMMAND, IDOK, open_button_handle),
                    ),
                    ("post_bm_click", lambda: user32.PostMessageW(open_button_handle, BM_CLICK, 0, 0)),
                    ("bounded_bm_click", lambda: self._send_bm_click(open_button_handle)),
                ]
                for method, action in actions:
                    accepted = bool(action())
                    closed = _wait_dialog_closed_with_fallback()
                    confirmation_trace.append(
                        {
                            "phase": "confirm_button",
                            "status": "closed" if closed else "still_open",
                            "method": method,
                            "accepted": accepted,
                        }
                    )
                    if closed:
                        return f"native_{method}"
            except Exception as exc:
                confirmation_trace.append({"phase": "confirm_button", "status": "error", "error": repr(exc)})
                return ""
            return ""

        def _rewrite_and_confirm_by_scoped_input() -> str:
            """Generate native edit notifications through the exact edit HWND.

            Re-apply the exact filename through the common-dialog controls and
            submit it asynchronously. Character-by-character ``WM_CHAR`` input
            races the shell dialog's auto-complete model and can rotate long
            paths while the cursor is being repositioned.
            """

            if edit_handle <= 0 or open_button_handle <= 0:
                confirmation_trace.append({"phase": "rewrite_confirm", "status": "control_missing"})
                return ""
            try:
                if not bool(user32.IsWindowEnabled(edit_handle)) or not bool(user32.IsWindowEnabled(open_button_handle)):
                    confirmation_trace.append({"phase": "rewrite_confirm", "status": "control_disabled"})
                    return ""
                rewrite_state = self._write_dialog_filename_verified(
                    dialog_handle=dialog_handle,
                    value=str(project_path),
                )
                if not bool(rewrite_state.get("verified", False)):
                    confirmation_trace.append(
                        {"phase": "rewrite_confirm", "status": "text_rejected", "write_state": rewrite_state}
                    )
                    return ""
                try:
                    readback = wait_until(
                        predicate=_scoped_filename_readback_state,
                        timeout_s=min(2.0, float(self.step_timeout_s)),
                        initial_interval_s=0.02,
                        max_interval_s=0.1,
                        backoff_factor=1.5,
                    )
                except TimeoutError:
                    confirmation_trace.append(
                        {
                            "phase": "rewrite_confirm",
                            "status": "readback_timeout",
                            "readback": _readback_snapshot(),
                        }
                    )
                    return ""
                confirm_method = _confirm_by_scoped_input()
                closed = bool(confirm_method)
                confirmation_trace.append(
                    {
                        "phase": "rewrite_confirm",
                        "status": "closed" if closed else "still_open",
                        "readback": readback,
                        "after_click_readback": _readback_snapshot(),
                        "confirm_method": confirm_method or None,
                    }
                )
                if closed:
                    return f"native_rewrite_then_{confirm_method}"
            except Exception as exc:
                confirmation_trace.append({"phase": "rewrite_confirm", "status": "error", "error": repr(exc)})
                return ""
            return ""

        def _confirm_open_dialog(*, prefer_uia: bool) -> str:
            actions: List[Tuple[str, Any]] = []

            if prefer_uia and os.name != "nt" and open_button is not None:
                if hasattr(open_button, "set_focus"):
                    actions.append(("uia_set_focus_open_button", lambda: open_button.set_focus()))
                if hasattr(open_button, "invoke"):
                    actions.append(("uia_invoke", lambda: open_button.invoke()))
                if hasattr(open_button, "click"):
                    actions.append(("uia_click", lambda: open_button.click()))

            actions.append(
                (
                    "wm_command_idok",
                    lambda: self._send_message_timeout(dialog_handle, WM_COMMAND, IDOK, open_button_handle),
                )
            )
            actions.append(
                (
                    "wm_command_idok_lparam0",
                    lambda: self._send_message_timeout(dialog_handle, WM_COMMAND, IDOK, 0),
                )
            )
            if open_button_handle > 0:
                actions.append(
                    (
                        "wm_command_bn_clicked_id",
                        lambda: self._send_wm_command_click(parent_hwnd=dialog_handle, control_hwnd=open_button_handle),
                    )
                )
                actions.append(("bm_click", lambda: self._send_bm_click(open_button_handle)))
            actions.append(
                (
                    "wm_command_bn_clicked",
                    lambda: self._send_message_timeout(
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

        file_type_state = _ensure_abec_file_type()
        file_type_state["strategy"] = "select_abec_filter_when_available"
        self._log(level="info", step=step, event="open_dialog_file_type", payload=file_type_state)

        # Tier A: fast path - write filename and confirm with Open button.
        try:
            filename_target = filename_edit or filename_combo
            set_method = ""
            write_state: Dict[str, Any] = {}
            if os.name == "nt":
                write_state = self._write_dialog_filename_verified(
                    dialog_handle=dialog_handle,
                    value=str(project_path),
                )
                set_method = str(write_state.get("method", "") or "")
            elif filename_target is not None:
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
            readback_before_submit = _readback_snapshot()
            readback_match = _path_matches(readback_before_submit.get("edit", "")) or _path_matches(
                readback_before_submit.get("dialog", "")
            )
            if write_state:
                readback_match = bool(write_state.get("verified", False))
            self._require(readback_match, "Open dialog filename write could not be verified in Tier A.", step)
            model_sync = _sync_filename_model()
            if os.name == "nt":
                self._require(
                    bool(model_sync.get("verified", False)),
                    "Open dialog filename model could not be synchronized in Tier A.",
                    step,
                )
                write_state["model_sync"] = model_sync
            path_written_once = True
            confirm_method = _confirm_by_scoped_input() if os.name == "nt" else ""
            if not confirm_method and os.name == "nt":
                confirm_method = _rewrite_and_confirm_by_scoped_input()
            if not confirm_method:
                confirm_method = _confirm_open_dialog(prefer_uia=True)
            if not confirm_method:
                confirm_method = _confirm_by_enter()
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
                    "write_state": write_state or None,
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
                    "confirmation_trace": list(confirmation_trace),
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
            write_state = self._write_dialog_filename_verified(
                dialog_handle=dialog_handle,
                value=str(project_path),
            )
            set_method = str(write_state.get("method", "") or "")
            self._require(bool(set_method), "Unable to write project path into Dateiname field (Tier B).", step)
            readback_before_submit = _readback_snapshot()
            readback_match = _path_matches(readback_before_submit.get("edit", "")) or _path_matches(
                readback_before_submit.get("dialog", "")
            )
            readback_match = bool(write_state.get("verified", False))
            self._require(readback_match, "Open dialog filename write could not be verified in Tier B.", step)
            model_sync = _sync_filename_model()
            if os.name == "nt":
                self._require(
                    bool(model_sync.get("verified", False)),
                    "Open dialog filename model could not be synchronized in Tier B.",
                    step,
                )
                write_state["model_sync"] = model_sync
            path_written_once = True
            confirm_method = _confirm_by_scoped_input() if os.name == "nt" else ""
            if not confirm_method and os.name == "nt":
                confirm_method = _rewrite_and_confirm_by_scoped_input()
            if not confirm_method:
                confirm_method = _confirm_open_dialog(prefer_uia=False)
            if not confirm_method:
                confirm_method = _confirm_by_enter()
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
                    "write_state": write_state,
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

        if path_written_once:
            diagnostics_path = self._write_open_dialog_diagnostics(
                step=step,
                file_dialog=file_dialog,
                dialog_handle=dialog_handle,
                project_path=project_path,
                attempts=attempts,
            )
            self.last_open_dialog_diagnostics_path = str(diagnostics_path) if diagnostics_path is not None else None
            raise RuntimeError(
                "ABEC open-file dialog did not reach a loaded-project signal after verified Win32 submission."
                + (f" diagnostics={self.last_open_dialog_diagnostics_path}" if self.last_open_dialog_diagnostics_path else "")
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
            main_handle = self._window_handle(main_window)
            if main_handle > 0:
                self._user32().SetForegroundWindow(main_handle)
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
                file_dialog = self._trigger_interpreter_open_button(
                    main_window=main_window,
                    interpreter_window=interpreter,
                    step=step,
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
            self._import_report_candidate = ""
            self._import_report_stable_since = time.monotonic()
            report_before_start = self._read_interpreter_report_text(interpreter)
            attempt_trace.append({"phase": "pre_start_report", "chars": len(report_before_start)})

            def _start_action_active() -> Tuple[bool, Dict[str, Any]]:
                interpreter_now = self._find_interpreter_window(main_window=main_window)
                if interpreter_now is None:
                    return True, {"status": "interpreter_closed"}
                start_button_now = self._find_first_control(
                    interpreter_now,
                    class_name_regex=r"TRzBitBtn",
                    title_regex=r"start\s+importing",
                )
                start_enabled = True
                if start_button_now is not None:
                    try:
                        start_enabled = bool(start_button_now.is_enabled())
                    except Exception:
                        start_enabled = True
                report_now = self._read_interpreter_report_text(interpreter_now)
                report_changed = bool(str(report_now or "").strip() != str(report_before_start or "").strip())
                active = bool(not start_enabled or report_changed)
                return active, {
                    "status": "active" if active else "unchanged",
                    "start_enabled": start_enabled,
                    "report_changed": report_changed,
                    "report_chars": len(report_now),
                }

            start_action = self._invoke_interpreter_button(
                interpreter_window=interpreter,
                title_regex=r"start\s+importing",
                step=step,
                action_name="start_importing",
            )
            attempt_trace.append({"phase": "start_importing", **start_action})
            attempt_trace.append(self._confirm_after_interpreter_action(main_window=main_window, step=step, phase="confirm_after_start"))

            try:
                apply_ready = wait_until(
                    predicate=lambda: self._import_apply_ready_state(main_window=main_window),
                    timeout_s=min(15.0, max(1.0, float(self.step_timeout_s))),
                    initial_interval_s=0.03,
                    max_interval_s=0.2,
                    backoff_factor=1.6,
                )
            except TimeoutError:
                active, activity = _start_action_active()
                attempt_trace.append({"phase": "start_importing_activity_after_mouse", **activity})
                if not active:
                    # A posted click can be lost while the VCL window is
                    # transitioning. Retry the same benign mouse gesture once;
                    # BM_CLICK/WM_COMMAND can re-enter the importer and has
                    # terminated AKABAK in real runs.
                    interpreter_retry = self._find_interpreter_window(main_window=main_window) or interpreter
                    retry_action = self._invoke_interpreter_button(
                        interpreter_window=interpreter_retry,
                        title_regex=r"start\s+importing",
                        step=step,
                        action_name="start_importing_retry",
                    )
                    attempt_trace.append({"phase": "start_importing_retry", **retry_action})
                apply_ready = wait_until(
                    predicate=lambda: self._import_apply_ready_state(main_window=main_window),
                    timeout_s=max(15.0, float(self.step_timeout_s)),
                )
            apply_status = str(apply_ready.get("status", "unknown"))
            attempt_trace.append({"phase": "wait_apply_ready", **apply_ready})
            if apply_status == "akabak_exited_before_apply":
                raise RuntimeError(f"AKABAK exited while importing the ABEC project: {apply_ready}")
            if apply_status == "interpreter_closed_before_apply":
                close_state = self._ensure_import_window_closed(main_window=main_window, step=step)
                attempt_trace.append({"phase": "ensure_main_only_after_auto_import", **close_state})
                self._log(
                    level="info",
                    step=step,
                    event="import_start_auto_closed_ok",
                    payload={"attempt_trace": attempt_trace},
                )
                return AkabakDriverResult(
                    ok=True,
                    status=self.state,
                    details={
                        "import_needed": True,
                        "import_mode": "start_importing_auto_closed",
                        "attempt_trace": attempt_trace,
                    },
                )
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

            # AKABAK applies the imported VCL model asynchronously. A short
            # settle barrier prevents closing the interpreter while its event
            # handler is still dereferencing the imported model.
            time.sleep(1.0)

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
        self._solve_main_handle = main_handle
        baseline = {
            "main_pid": int(self.session.process_id or 0),
            "main_handle": main_handle,
            "akabak_pids": self._list_akabak_process_ids(),
            "vacs_pids": self._list_vacs_process_ids(),
            "main_cpu_time_s": _process_cpu_time_seconds(int(self.session.process_id or 0)),
        }
        trigger_attempts: List[Dict[str, Any]] = []

        def _started_state() -> Tuple[bool, Dict[str, Any]]:
            if self.watchdog:
                # This predicate is already polled by ``wait_until``. One
                # bounded watchdog pass avoids turning a successfully handled
                # dialog into a false timeout while its window is closing.
                handled = self.watchdog.handle_once()
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
            new_akabak = _new_process_ids(list(snapshot.get("akabak_pids", []) or []), baseline_akabak)
            new_vacs = _new_process_ids(list(snapshot.get("vacs_pids", []) or []), baseline_vacs)
            snapshot["new_akabak_pids"] = new_akabak
            snapshot["new_vacs_pids"] = new_vacs
            baseline_main_cpu = baseline.get("main_cpu_time_s")
            current_main_cpu = dict(snapshot.get("akabak_cpu_times_s", {}) or {}).get(str(baseline["main_pid"]))
            if baseline_main_cpu is not None and current_main_cpu is not None:
                snapshot["main_cpu_growth_s"] = max(0.0, float(current_main_cpu) - float(baseline_main_cpu))
            else:
                snapshot["main_cpu_growth_s"] = 0.0
            if bool(snapshot.get("progress_window_present")):
                snapshot["start_signal"] = "progress_window_present"
                return True, snapshot
            if new_akabak:
                snapshot["start_signal"] = "akabak_worker_process_started"
                return True, snapshot
            if new_vacs:
                snapshot["start_signal"] = "vacs_process_started"
                return True, snapshot
            if float(snapshot.get("main_cpu_growth_s", 0.0) or 0.0) >= 0.25:
                snapshot["start_signal"] = "main_process_cpu_progress"
                return True, snapshot
            snapshot["start_signal"] = "not_started"
            return False, snapshot

        try:
            # Resolve the native HWND once and stay off UIA/COM on Windows.
            # Exact UIA wrappers can block indefinitely while AKABAK changes
            # its window tree during solve startup.
            if os.name == "nt":
                native_trigger = self._trigger_solve_native(main_handle)
                self._require(
                    native_trigger.get("status") in {"sent", "dispatch_timed_out"},
                    "Native solve trigger was rejected by AKABAK.",
                    step,
                )
                trigger_attempts.append(native_trigger)
            else:
                main_window.set_focus()
                main_window.type_keys("{F4}", set_foreground=True)
                trigger_attempts.append({"trigger": "uia_type_keys_f4", "status": "sent"})
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
                if os.name != "nt":
                    main_window.set_focus()
                    main_window.type_keys("{F4}", set_foreground=True)
                    trigger_attempts.append({"trigger": "uia_type_keys_f4_retry", "status": "sent"})
                else:
                    native_retry = self._trigger_solve_native(main_handle)
                    self._require(
                        native_retry.get("status") in {"sent", "dispatch_timed_out"},
                        "Native solve retry was rejected by AKABAK.",
                        step,
                    )
                    trigger_attempts.append({**native_retry, "trigger": f"{native_retry['trigger']}_retry"})
                started = wait_until(
                    predicate=_started_state,
                    timeout_s=min(30.0, float(self.step_timeout_s)),
                    initial_interval_s=0.08,
                    max_interval_s=0.45,
                    backoff_factor=1.8,
                )
                trigger_attempts.append({"trigger": "wait_tier_extended", "status": "started"})
            self.solve_context = {
                "baseline": baseline,
                "started": started,
                "trigger_attempts": trigger_attempts,
            }
            self.state = "running"
            self._log(
                level="info",
                step=step,
                event="solve_started",
                payload={"state": self.state, "trigger_attempts": trigger_attempts, "started": started},
            )
            return AkabakDriverResult(
                ok=True,
                status=self.state,
                details={
                    "started": started,
                    "trigger_attempts": trigger_attempts,
                },
            )
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

        baseline_akabak = {int(pid) for pid in self.solve_context.get("baseline", {}).get("akabak_pids", [])}
        baseline_vacs = {int(pid) for pid in self.solve_context.get("baseline", {}).get("vacs_pids", [])}
        start_vacs_ui = dict(start_snapshot.get("vacs_ui", {}))
        start_controls = int(start_vacs_ui.get("max_controls_count", 0) or 0)
        start_graph_hits = int(start_vacs_ui.get("max_graph_keyword_hits", 0) or 0)
        heartbeat_started = time.perf_counter()
        last_heartbeat_elapsed = -15.0
        vacs_graphless_since: Optional[float] = None
        vacs_reimport: Dict[str, Any] = {"triggered": False}
        vacs_launch: Dict[str, Any] = {"attempted": False}
        solver_activity_snapshot: Dict[str, Any] = dict(start_snapshot)
        solver_quiet_since: Optional[float] = None
        solver_numerically_complete = False
        solve_command_was_disabled = bool(start_snapshot.get("solve_command_enabled") is False)

        def _record_heartbeat(snapshot: Dict[str, Any]) -> None:
            nonlocal last_heartbeat_elapsed
            elapsed_s = float(time.perf_counter() - heartbeat_started)
            if elapsed_s - last_heartbeat_elapsed < 15.0:
                return
            row = _solve_heartbeat_payload(snapshot, elapsed_s=elapsed_s)
            self.solve_heartbeats.append(row)
            last_heartbeat_elapsed = elapsed_s
            self._log(level="info", step=step, event="solve_heartbeat", payload=row)

        def _completed() -> Tuple[bool, Dict[str, Any]]:
            nonlocal vacs_graphless_since, vacs_reimport, vacs_launch
            nonlocal solver_activity_snapshot, solver_quiet_since, solver_numerically_complete
            nonlocal solve_command_was_disabled
            if self.watchdog:
                handled = self.watchdog.handle_once()
                if handled:
                    self._record_watchdog_events(step=step, events=handled)
                    self._log(level="info", step=step, event="watchdog_handled", payload={"count": len(handled)})
            snapshot = self._solve_signal_snapshot()
            new_akabak = _new_process_ids(list(snapshot.get("akabak_pids", []) or []), baseline_akabak)
            new_vacs = _new_process_ids(list(snapshot.get("vacs_pids", []) or []), baseline_vacs)
            snapshot["new_akabak_pids"] = new_akabak
            snapshot["new_vacs_pids"] = new_vacs
            current_solve_enabled = snapshot.get("solve_command_enabled")
            if current_solve_enabled is False:
                solve_command_was_disabled = True
                # The native Calculate command is the authoritative busy
                # signal.  AKABAK can stay CPU-quiet for a few seconds after
                # F4 before disabling the command, so discard any premature
                # CPU-quiescence completion and allow a later, real F7
                # handoff after the command becomes enabled again.
                solver_numerically_complete = False
                solver_activity_snapshot = dict(snapshot)
                solver_quiet_since = None
                vacs_graphless_since = None
                vacs_reimport = {"triggered": False}
                vacs_launch = {"attempted": False}
                snapshot["status"] = "running_solve_command_disabled"
                _record_heartbeat(snapshot)
                return False, snapshot

            if not solver_numerically_complete and (snapshot.get("progress_window_present") or new_akabak):
                solver_activity_snapshot = dict(snapshot)
                solver_quiet_since = None
                snapshot["status"] = "running"
                _record_heartbeat(snapshot)
                return False, snapshot

            if (
                not solver_numerically_complete
                and solve_command_was_disabled
                and current_solve_enabled is True
            ):
                solver_numerically_complete = True
                snapshot["numerical_completion_signal"] = "calculate_command_reenabled"

            if not solver_numerically_complete:
                if current_solve_enabled is True and not solve_command_was_disabled:
                    activation_elapsed_s = max(0.0, float(time.perf_counter() - heartbeat_started))
                    snapshot["solver_activation_elapsed_s"] = round(activation_elapsed_s, 3)
                    if activation_elapsed_s < 8.0:
                        snapshot["status"] = "waiting_solver_activation"
                        _record_heartbeat(snapshot)
                        return False, snapshot
                main_pid = int(snapshot.get("main_pid", 0) or 0)
                current_cpu = dict(snapshot.get("akabak_cpu_times_s", {}) or {}).get(str(main_pid))
                previous_cpu = dict(solver_activity_snapshot.get("akabak_cpu_times_s", {}) or {}).get(str(main_pid))
                if current_cpu is not None and previous_cpu is not None:
                    now = time.perf_counter()
                    cpu_delta = max(0.0, float(current_cpu) - float(previous_cpu))
                    snapshot["main_cpu_delta_s"] = round(cpu_delta, 4)
                    if cpu_delta >= 0.05:
                        solver_activity_snapshot = dict(snapshot)
                        solver_quiet_since = now
                        snapshot["status"] = "running_main_process"
                        _record_heartbeat(snapshot)
                        return False, snapshot
                    if solver_quiet_since is None:
                        solver_quiet_since = now
                    quiet_s = max(0.0, now - solver_quiet_since)
                    snapshot["solver_quiet_s"] = round(quiet_s, 3)
                    if quiet_s < 2.0:
                        snapshot["status"] = "waiting_solver_quiescence"
                        _record_heartbeat(snapshot)
                        return False, snapshot
                    snapshot["numerical_completion_signal"] = "main_process_cpu_quiet"
                else:
                    snapshot["numerical_completion_signal"] = "no_progress_or_worker_process"
                solver_numerically_complete = True

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
                _record_heartbeat(snapshot)
                return True, snapshot

            if new_vacs or snapshot.get("vacs_pids"):
                if graphs_imported:
                    snapshot["status"] = "completed_vacs_graphs_imported"
                    _record_heartbeat(snapshot)
                    return True, snapshot
                if new_vacs:
                    startup_actions = self._dismiss_vacs_startup_editors(new_vacs)
                    if startup_actions:
                        snapshot["vacs_startup_editors"] = startup_actions
                        vacs_graphless_since = None
                        self._log(
                            level="info",
                            step=step,
                            event="vacs_startup_editors_closed",
                            payload={"actions": startup_actions},
                        )
                    now = time.perf_counter()
                    if vacs_graphless_since is None:
                        vacs_graphless_since = now
                    graphless_s = max(0.0, now - vacs_graphless_since)
                    snapshot["vacs_graphless_s"] = round(graphless_s, 3)
                    if graphless_s >= 3.0 and not bool(vacs_reimport.get("triggered")):
                        main_handle = int(self.solve_context.get("baseline", {}).get("main_handle", 0) or 0)
                        trigger = self._trigger_vacs_reimport_native(main_handle)
                        self._require(
                            trigger.get("status") == "sent",
                            "VACS F7 re-import trigger was rejected by AKABAK.",
                            step,
                        )
                        vacs_reimport = {
                            "triggered": True,
                            "reason": "new_vacs_without_graphs",
                            "graphless_s": round(graphless_s, 3),
                            **trigger,
                        }
                        self._log(level="info", step=step, event="vacs_reimport_triggered", payload=vacs_reimport)
                snapshot["vacs_reimport"] = dict(vacs_reimport)
                snapshot["status"] = "waiting_vacs_graph_import"
                _record_heartbeat(snapshot)
                return False, snapshot

            if not bool(vacs_launch.get("attempted")):
                main_handle = int(self.solve_context.get("baseline", {}).get("main_handle", 0) or 0)
                launch = self._start_vacs_for_handoff(main_handle)
                vacs_launch = {"attempted": True, **launch}
                snapshot["vacs_launch"] = dict(vacs_launch)
                self._require(
                    launch.get("status") in {"sent", "already_running"},
                    "AKABAK did not accept the VACS handoff trigger. "
                    f"status={launch.get('status')} main_handle={main_handle}",
                    step,
                )
                self._log(level="info", step=step, event="vacs_handoff_launch", payload=vacs_launch)
                snapshot["status"] = "launching_vacs_for_handoff"
                _record_heartbeat(snapshot)
                return False, snapshot

            snapshot["vacs_launch"] = dict(vacs_launch)
            snapshot["status"] = "waiting_vacs_after_solve_start"
            _record_heartbeat(snapshot)
            return False, snapshot

        completion_snapshot: Dict[str, Any]
        inactivity_timeout_s = max(1.0, float(timeout_s))
        hard_timeout_s = max(inactivity_timeout_s * 2.0, inactivity_timeout_s + 60.0)
        started_at = time.perf_counter()
        last_progress_at = started_at
        previous_snapshot = dict(start_snapshot)
        interval_s = 0.08
        extension_logged = False
        timeout_kind = ""
        last_snapshot: Dict[str, Any] = dict(start_snapshot)
        while True:
            completed, snapshot_value = _completed()
            completion_snapshot = dict(snapshot_value)
            last_snapshot = completion_snapshot
            now = time.perf_counter()
            if completed:
                break
            if _solve_snapshot_made_progress(previous_snapshot, completion_snapshot):
                last_progress_at = now
            previous_snapshot = completion_snapshot
            elapsed_s = max(0.0, now - started_at)
            idle_s = max(0.0, now - last_progress_at)
            if not extension_logged and elapsed_s >= inactivity_timeout_s and idle_s < inactivity_timeout_s:
                extension_logged = True
                self._log(
                    level="info",
                    step=step,
                    event="active_solve_grace_window",
                    payload={
                        "configured_timeout_s": inactivity_timeout_s,
                        "hard_timeout_s": hard_timeout_s,
                        "elapsed_s": elapsed_s,
                        "idle_s": idle_s,
                    },
                )
            if idle_s >= inactivity_timeout_s:
                timeout_kind = "solver_inactive"
                break
            if elapsed_s >= hard_timeout_s:
                timeout_kind = "hard_limit"
                break
            time.sleep(interval_s)
            interval_s = min(0.5, interval_s * 1.7)

        if timeout_kind:
            now = time.perf_counter()
            diagnostics_path = self._write_solve_diagnostics(
                step=step,
                reason="solve_completion_timeout",
                context={
                    "timeout_s": timeout_s,
                    "timeout_kind": timeout_kind,
                    "hard_timeout_s": hard_timeout_s,
                    "elapsed_s": max(0.0, now - started_at),
                    "idle_s": max(0.0, now - last_progress_at),
                    "start_snapshot": start_snapshot,
                    "last_snapshot": last_snapshot,
                },
            )
            self.last_solve_diagnostics_path = str(diagnostics_path) if diagnostics_path is not None else None
            self._log(
                level="error",
                step=step,
                event="timeout",
                payload={
                    "timeout_s": timeout_s,
                    "timeout_kind": timeout_kind,
                    "hard_timeout_s": hard_timeout_s,
                    "diagnostics_path": self.last_solve_diagnostics_path,
                },
            )
            raise TimeoutError(
                f"AKABAK solve did not complete ({timeout_kind}) within the "
                f"{int(inactivity_timeout_s)}s inactivity / {int(hard_timeout_s)}s hard limit."
                + (f" diagnostics={self.last_solve_diagnostics_path}" if self.last_solve_diagnostics_path else "")
            )
        self.state = "completed"
        self._log(
            level="info",
            step=step,
            event="completed",
            payload={"state": self.state, "completion": completion_snapshot},
        )
        return AkabakDriverResult(
            ok=True,
            status=self.state,
            details={"completion": completion_snapshot},
        )

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
            interpreter_handle = self._window_handle(interpreter)
            controls = (
                self._native_descendant_controls(interpreter_handle)
                if os.name == "nt" and interpreter_handle > 0
                else list(interpreter.descendants())
            )
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

    def close(self, *, preserve_vacs: bool = False) -> AkabakDriverResult:
        step = "close"
        if self.state == "closed":
            return AkabakDriverResult(ok=True, status=self.state, details={"idempotent": True})
        owned_before_close = self._refresh_owned_tool_process_ids()
        main_window = self.session.find_window(
            title_regex=AKABAK_MAIN_WINDOW.title_regex,
            class_name_regex=AKABAK_MAIN_WINDOW.class_name_regex,
        )
        if main_window is not None:
            main_handle = self._window_handle(main_window)
            if os.name == "nt" and main_handle > 0:
                try:
                    result = ctypes.c_size_t()
                    self._user32().SendMessageTimeoutW(
                        main_handle,
                        WM_CLOSE,
                        0,
                        0,
                        SMTO_ABORTIFHUNG,
                        1000,
                        ctypes.byref(result),
                    )
                except Exception:
                    pass
            else:
                try:
                    main_window.close()
                except Exception:
                    pass
        self.session.close()
        cleanup = self._terminate_owned_tool_processes(grace_s=5.0, preserve_vacs=preserve_vacs)
        self.state = "closed"
        details = {
            "owned_before_close": owned_before_close,
            "preserve_vacs": bool(preserve_vacs),
            "cleanup": cleanup,
        }
        self._log(level="info", step=step, event="closed", payload=details)
        return AkabakDriverResult(ok=not any(cleanup.get("remaining", {}).values()), status=self.state, details=details)
