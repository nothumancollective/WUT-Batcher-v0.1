"""Modal dialog watchdog and recovery for deterministic UI automation runs."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence


BM_CLICK = 0x00F5
WM_COMMAND = 0x0111
WM_GETTEXT = 0x000D
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_RETURN = 0x0D
SMTO_ABORTIFHUNG = 0x0002


def _bounded_uia_dialog_snapshot(handle: int, *, timeout_s: float = 5.0) -> Dict[str, Any]:
    """Read DirectUI accessibility text in an isolated, time-bounded process."""

    hwnd = int(handle or 0)
    if hwnd <= 0:
        return {"status": "invalid_handle", "children": []}
    script = (
        "import json,sys\n"
        "from pywinauto import Desktop\n"
        "w=Desktop(backend='uia').window(handle=int(sys.argv[1]))\n"
        "rows=[]\n"
        "for c in w.descendants():\n"
        " i=c.element_info\n"
        " rows.append({'title':str(getattr(i,'name','') or ''),"
        "'class_name':str(getattr(i,'class_name','') or ''),"
        "'control_type':str(getattr(i,'control_type','') or ''),"
        "'automation_id':str(getattr(i,'automation_id','') or '')})\n"
        "print(json.dumps(rows, ensure_ascii=False))\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(hwnd)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.5, float(timeout_s)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "children": []}
    except Exception as exc:
        return {"status": "error", "error": repr(exc), "children": []}
    try:
        children = json.loads(str(completed.stdout or "[]"))
    except Exception:
        children = []
    return {
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "stderr": str(completed.stderr or "")[-2000:],
        "children": children if isinstance(children, list) else [],
    }


@dataclass(frozen=True)
class _NativeElementInfo:
    handle: int
    name: str
    class_name: str
    control_type: str
    automation_id: str = ""


class _NativeWindow:
    """Small HWND adapter used by the watchdog on Windows.

    Keeping modal polling on Win32 handles avoids an unbounded COM/UIA tree
    traversal while AKABAK is transitioning between interpreter and solver.
    """

    def __init__(self, *, user32: Any, handle: int, title: str, class_name: str) -> None:
        self._user32 = user32
        self.element_info = _NativeElementInfo(
            handle=int(handle),
            name=str(title or ""),
            class_name=str(class_name or ""),
            control_type="Button" if re.search(r"button|btn", class_name, re.IGNORECASE) else "Text",
        )

    def window_text(self) -> str:
        return str(self.element_info.name or "")

    def children(self, *, control_type: Optional[str] = None) -> List["_NativeWindow"]:
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        rows: List[_NativeWindow] = []

        def _text(hwnd: int) -> str:
            buffer = ctypes.create_unicode_buffer(2048)
            result = ctypes.c_size_t(0)
            ok = self._user32.SendMessageTimeoutW(
                hwnd,
                WM_GETTEXT,
                len(buffer) - 1,
                buffer,
                SMTO_ABORTIFHUNG,
                500,
                ctypes.byref(result),
            )
            if not ok:
                self._user32.GetWindowTextW(hwnd, buffer, len(buffer))
            return str(buffer.value or "")

        def _class(hwnd: int) -> str:
            buffer = ctypes.create_unicode_buffer(256)
            self._user32.GetClassNameW(hwnd, buffer, len(buffer))
            return str(buffer.value or "")

        def _callback(raw_hwnd: int, _lparam: int) -> int:
            hwnd = int(raw_hwnd or 0)
            child = _NativeWindow(user32=self._user32, handle=hwnd, title=_text(hwnd), class_name=_class(hwnd))
            if not control_type or child.element_info.control_type == control_type:
                rows.append(child)
            return 1

        callback = callback_type(_callback)
        self._user32.EnumChildWindows(int(self.element_info.handle), callback, 0)
        return rows

    def child_window(self, *, title: str, control_type: str) -> "_NativeQuery":
        matches = [
            child
            for child in self.children(control_type=control_type)
            if child.window_text().strip().lower() == str(title or "").strip().lower()
        ]
        return _NativeQuery(matches[0] if matches else None, parent_handle=int(self.element_info.handle))

    def type_keys(self, keys: str) -> None:
        if str(keys).upper() != "{ENTER}":
            raise ValueError(f"Unsupported native watchdog key sequence: {keys}")
        hwnd = int(self.element_info.handle)
        self._user32.PostMessageW(hwnd, WM_KEYDOWN, VK_RETURN, 0)
        self._user32.PostMessageW(hwnd, WM_KEYUP, VK_RETURN, 0)


class _NativeQuery:
    def __init__(self, window: Optional[_NativeWindow], *, parent_handle: int = 0) -> None:
        self._window = window
        self._parent_handle = int(parent_handle or 0)

    def exists(self, timeout: float = 0.0) -> bool:
        _ = timeout
        return self._window is not None

    def invoke(self) -> None:
        if self._window is None:
            raise RuntimeError("Native watchdog control does not exist.")
        result = ctypes.c_size_t()
        ok = self._window._user32.SendMessageTimeoutW(
            int(self._window.element_info.handle),
            BM_CLICK,
            0,
            0,
            SMTO_ABORTIFHUNG,
            1000,
            ctypes.byref(result),
        )
        if ok and self._parent_handle > 0:
            deadline = time.monotonic() + 0.25
            while time.monotonic() < deadline:
                if not bool(self._window._user32.IsWindow(self._parent_handle)):
                    return
                time.sleep(0.025)
        if self._parent_handle > 0:
            control_id = int(self._window._user32.GetDlgCtrlID(int(self._window.element_info.handle)) or 1)
            posted = bool(
                self._window._user32.PostMessageW(
                    self._parent_handle,
                    WM_COMMAND,
                    control_id & 0xFFFF,
                    int(self._window.element_info.handle),
                )
            )
            if posted:
                return
        if not ok:
            raise RuntimeError("Native watchdog button did not accept BM_CLICK or WM_COMMAND.")

    def type_keys(self, keys: str) -> None:
        if self._window is None:
            raise RuntimeError("Native watchdog control does not exist.")
        self._window.type_keys(keys)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class DialogRule:
    rule_id: str
    title_regex: str
    message_regex: str
    action: str = "ok"
    notes: str = ""

    def matches(self, *, title: str, message: str) -> bool:
        return bool(re.search(self.title_regex, title, re.IGNORECASE)) and bool(
            re.search(self.message_regex, message, re.IGNORECASE)
        )


class UnknownDialogError(RuntimeError):
    pass


class ModalDialogWatchdog:
    def __init__(
        self,
        *,
        process_id: Optional[int],
        output_dir: str | Path,
        whitelist_rules: Sequence[DialogRule] | None = None,
        capture_screenshot: bool = False,
        poll_interval_s: float = 0.5,
        global_timeout_s: int = 180,
    ) -> None:
        self.process_id = process_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.poll_interval_s = max(0.1, float(poll_interval_s))
        self.global_timeout_s = max(1, int(global_timeout_s))
        self.capture_screenshot = capture_screenshot
        self.whitelist_rules = list(
            whitelist_rules
            or [
                DialogRule(
                    rule_id="allow_generic_ok",
                    title_regex=r"(warning|notice|confirm|akabak|vacs)",
                    message_regex=r"(proceed|continue|overwrite|already exists|ok)",
                    action="ok",
                    notes="Known confirmation prompts can be accepted.",
                ),
                DialogRule(
                    rule_id="edge_length_not_defined_continue",
                    title_regex=r"(warning|confirm|akabak|question|hinweis|achtung)",
                    message_regex=r"(edge\s*length|kantenl(ä|ae)nge|not\s*defined|undefined)",
                    action="ok",
                    notes="Edge-length/mesh warning should be acknowledged with Yes/OK in harness runs.",
                ),
                DialogRule(
                    rule_id="vacs_com_registration_missing_continue",
                    title_regex=r"^(error|fehler|akabak)$",
                    message_regex=(
                        r"cannot\s+locate\s+vacs(?:\.exe|viewer\.exe).*"
                        r"(?:com\s+service|regserver)"
                    ),
                    action="ok",
                    notes=(
                        "AKABAK can still complete the solve and create VACS through its F7 handoff; "
                        "this exact registration warning is distinct from VACS first-start editors."
                    ),
                ),
                DialogRule(
                    rule_id="cancel_project_save_as",
                    title_regex=r"^(save\s+as|speichern\s+unter)$",
                    message_regex=r".*",
                    action="cancel",
                    notes="Discard the transient AKABAK project-save dialog after a completed ABEC import.",
                ),
                DialogRule(
                    rule_id="discard_imported_project_changes",
                    title_regex=r"^(akabak|warning|warnung)$",
                    message_regex=r"((save|speichern).*(project|projekt)|(project|projekt).*(save|speichern))",
                    action="discard",
                    notes="Do not persist the temporary project created by a batch import.",
                ),
            ]
        )

    def _import_pywinauto(self):
        try:
            from pywinauto import Desktop
        except Exception:
            return None
        return Desktop

    def _candidate_dialogs(self) -> List[Any]:
        if os.name == "nt":
            return self._candidate_dialogs_native()
        Desktop = self._import_pywinauto()
        if Desktop is None:
            return []
        desktop = Desktop(backend="uia")
        rows = []
        for window in desktop.windows():
            info = window.element_info
            process_id = int(getattr(info, "process_id", 0) or 0)
            if self.process_id and process_id != int(self.process_id):
                continue
            class_name = str(getattr(info, "class_name", "") or "")
            title = str(getattr(info, "name", "") or "")
            if class_name == "#32770" or re.search(r"(dialog|message)", class_name, re.IGNORECASE):
                rows.append(window)
                continue
            if re.search(r"(warning|error|confirm|message)", title, re.IGNORECASE):
                rows.append(window)
        return rows

    def _candidate_dialogs_native(self) -> List[Any]:
        process_id = int(self.process_id or 0)
        if process_id <= 0 or not hasattr(ctypes, "windll") or not hasattr(ctypes, "WINFUNCTYPE"):
            return []
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        rows: List[Any] = []

        def _text(hwnd: int) -> str:
            buffer = ctypes.create_unicode_buffer(2048)
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            return str(buffer.value or "")

        def _class(hwnd: int) -> str:
            buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buffer, len(buffer))
            return str(buffer.value or "")

        def _callback(raw_hwnd: int, _lparam: int) -> int:
            hwnd = int(raw_hwnd or 0)
            owner_pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            if int(owner_pid.value) != process_id or not bool(user32.IsWindowVisible(hwnd)):
                return 1
            class_name = _class(hwnd)
            title = _text(hwnd)
            is_dialog_class = class_name == "#32770" or bool(
                re.search(r"(dialog|message)", class_name, re.IGNORECASE)
            )
            is_dialog_title = bool(
                re.search(r"(warning|warnung|error|fehler|confirm|best.*tig|message|meldung)", title, re.IGNORECASE)
            )
            if is_dialog_class or is_dialog_title:
                rows.append(_NativeWindow(user32=user32, handle=hwnd, title=title, class_name=class_name))
            return 1

        callback = callback_type(_callback)
        user32.EnumWindows(callback, 0)
        return rows

    def _window_message(self, window) -> str:
        try:
            children = window.children(control_type="Text")
        except Exception:
            children = []
        texts = []
        for child in children:
            try:
                text = child.window_text()
            except Exception:
                text = ""
            if text:
                texts.append(text)
        if texts:
            return " ".join(texts)
        try:
            return window.window_text()
        except Exception:
            return ""

    def _capture_debug_artifacts(
        self,
        *,
        window,
        reason: str,
        uia_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        title = ""
        class_name = ""
        automation_id = ""
        control_type = ""
        try:
            info = window.element_info
            title = str(getattr(info, "name", "") or "")
            class_name = str(getattr(info, "class_name", "") or "")
            automation_id = str(getattr(info, "automation_id", "") or "")
            control_type = str(getattr(info, "control_type", "") or "")
        except Exception:
            pass

        payload = {
            "captured_at": _now_iso(),
            "reason": reason,
            "title": title,
            "class_name": class_name,
            "automation_id": automation_id,
            "control_type": control_type,
            "process_id": self.process_id,
            "message": self._window_message(window),
        }
        try:
            payload["children"] = [
                {
                    "title": child.window_text(),
                    "class_name": str(getattr(child.element_info, "class_name", "") or ""),
                    "control_type": str(getattr(child.element_info, "control_type", "") or ""),
                    "native_handle": int(getattr(child.element_info, "handle", 0) or 0),
                }
                for child in window.children()
            ]
        except Exception:
            payload["children"] = []
        handle = int(getattr(getattr(window, "element_info", None), "handle", 0) or 0)
        payload["uia_snapshot"] = uia_snapshot or _bounded_uia_dialog_snapshot(handle)
        debug_path = self.output_dir / f"unknown_dialog_{stamp}.json"
        debug_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        screenshot_path = None
        return {"debug_path": str(debug_path), "screenshot_path": screenshot_path, "payload": payload}

    def _click_action(self, *, window, action: str) -> bool:
        normalized = str(action).lower().strip()
        button_titles = {
            "ok": ("OK", "Ok", "Yes", "Ja", "Continue", "Fortfahren"),
            "cancel": ("Cancel", "Abbrechen", "No", "Nein"),
            "discard": ("No", "Nein", "Don't Save", "Nicht speichern"),
            "close": ("Close", "Schließen", "Cancel", "Abbrechen", "No", "Nein"),
        }
        expected = button_titles.get(normalized, ("OK",))
        for caption in expected:
            try:
                button = window.child_window(title=caption, control_type="Button")
                if button.exists(timeout=0.2):
                    try:
                        button.invoke()
                    except Exception:
                        button.type_keys("{ENTER}")
                    return True
            except Exception:
                continue
        if normalized in {"cancel", "discard"}:
            # Never let Enter accept a default save action when the intended
            # non-persisting button could not be identified exactly.
            return False
        try:
            window.type_keys("{ENTER}")
            return True
        except Exception:
            return False

    def handle_once(self) -> List[Dict[str, Any]]:
        handled: List[Dict[str, Any]] = []
        for window in self._candidate_dialogs():
            try:
                title = window.window_text()
            except Exception:
                title = ""
            message = self._window_message(window)
            matched_rule = None
            for rule in self.whitelist_rules:
                if rule.matches(title=title, message=message):
                    matched_rule = rule
                    break
            uia_snapshot: Optional[Dict[str, Any]] = None
            if matched_rule is None:
                handle = int(getattr(getattr(window, "element_info", None), "handle", 0) or 0)
                uia_snapshot = _bounded_uia_dialog_snapshot(handle)
                accessible_text = " ".join(
                    str(child.get("title", "") or "").strip()
                    for child in list(uia_snapshot.get("children", []) or [])
                    if isinstance(child, dict) and str(child.get("title", "") or "").strip()
                )
                if accessible_text:
                    message = f"{message} {accessible_text}".strip()
                    for rule in self.whitelist_rules:
                        if rule.matches(title=title, message=message):
                            matched_rule = rule
                            break
            if matched_rule is None:
                debug = self._capture_debug_artifacts(
                    window=window,
                    reason="unknown_modal_dialog",
                    uia_snapshot=uia_snapshot,
                )
                raise UnknownDialogError(
                    f"Unknown modal dialog detected: {title}. Debug: {debug['debug_path']}"
                )
            clicked = self._click_action(window=window, action=matched_rule.action)
            if not clicked:
                debug = self._capture_debug_artifacts(
                    window=window,
                    reason=f"matched_dialog_action_failed:{matched_rule.rule_id}",
                    uia_snapshot=uia_snapshot,
                )
                raise UnknownDialogError(
                    f"Matched modal dialog could not be handled safely: {title}. Debug: {debug['debug_path']}"
                )
            handled.append(
                {
                    "handled_at": _now_iso(),
                    "rule_id": matched_rule.rule_id,
                    "title": title,
                    "message": message[:500],
                    "action": matched_rule.action,
                }
            )
        return handled

    def run_watch(self, *, step_name: str, timeout_s: Optional[int] = None) -> List[Dict[str, Any]]:
        effective_timeout = min(self.global_timeout_s, timeout_s or self.global_timeout_s)
        started = time.perf_counter()
        handled: List[Dict[str, Any]] = []
        while True:
            if (time.perf_counter() - started) > effective_timeout:
                raise TimeoutError(f"Watchdog timeout in step '{step_name}' after {effective_timeout}s.")
            new = self.handle_once()
            if new:
                handled.extend(new)
                time.sleep(self.poll_interval_s)
                continue
            break
        return handled
