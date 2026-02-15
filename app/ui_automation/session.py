"""UI Automation session abstraction (pywinauto primary, uiautomation fallback)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List, Optional

from app.ui_automation.waits import wait_until


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class WindowInfo:
    title: str
    class_name: str
    process_id: int
    process_name: str
    framework: str
    control_type: str
    automation_id: str
    handle: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "class_name": self.class_name,
            "process_id": self.process_id,
            "process_name": self.process_name,
            "framework": self.framework,
            "control_type": self.control_type,
            "automation_id": self.automation_id,
            "handle": self.handle,
        }


class UiaSessionError(RuntimeError):
    pass


class _InfoAdapter:
    def __init__(self, control: Any) -> None:
        self.name = str(getattr(control, "Name", "") or "")
        self.class_name = str(getattr(control, "ClassName", "") or "")
        self.process_id = int(getattr(control, "ProcessId", 0) or 0)
        self.framework_id = str(getattr(control, "FrameworkId", "") or "")
        self.control_type = str(getattr(control, "ControlTypeName", "") or "")
        self.automation_id = str(getattr(control, "AutomationId", "") or "")
        self.handle = int(getattr(control, "NativeWindowHandle", 0) or 0)


class UiaAutomationElementAdapter:
    def __init__(self, control: Any, auto_module: Any) -> None:
        self._control = control
        self._auto = auto_module
        self.element_info = _InfoAdapter(control)

    def window_text(self) -> str:
        return str(getattr(self._control, "Name", "") or "")

    def set_focus(self) -> None:
        try:
            self._control.SetFocus()
        except Exception:
            pass

    def type_keys(self, text: str, **_: Any) -> None:
        self._auto.SendKeys(str(text))

    def close(self) -> None:
        try:
            self._control.SendKeys("%{F4}")
        except Exception:
            self._auto.SendKeys("%{F4}")

    def exists(self, timeout: float = 0.0) -> bool:
        _ = timeout
        try:
            return bool(self._control.Exists(0))
        except Exception:
            return True

    def click_input(self) -> None:
        try:
            self._control.Click()
        except Exception:
            self._auto.SendKeys("{ENTER}")

    def children(self, control_type: Optional[str] = None) -> List["UiaAutomationElementAdapter"]:
        controls = []
        try:
            controls = list(self._control.GetChildren() or [])
        except Exception:
            controls = []
        wrapped = [UiaAutomationElementAdapter(control, self._auto) for control in controls]
        if not control_type:
            return wrapped
        return [
            item
            for item in wrapped
            if str(getattr(item.element_info, "control_type", "")).lower() == str(control_type).lower()
        ]

    def child_window(self, *, title: Optional[str] = None, control_type: Optional[str] = None):
        title_value = str(title or "").lower()
        control_type_value = str(control_type or "").lower()
        for child in self.children():
            child_title = str(child.window_text()).lower()
            child_type = str(getattr(child.element_info, "control_type", "")).lower()
            if title_value and child_title != title_value:
                continue
            if control_type_value and child_type != control_type_value:
                continue
            return child
        return _NullElementAdapter()


class _NullElementAdapter:
    def exists(self, timeout: float = 0.0) -> bool:
        _ = timeout
        return False

    def click_input(self) -> None:
        return None


class UiaSession:
    def __init__(
        self,
        *,
        executable: str | Path,
        app_name: str,
        startup_timeout_s: int = 20,
        allow_fallback: bool = True,
        prefer_start: bool = False,
    ) -> None:
        self.executable = str(executable)
        self.app_name = app_name
        self.startup_timeout_s = max(1, int(startup_timeout_s))
        self.allow_fallback = allow_fallback
        self.prefer_start = bool(prefer_start)
        self.process_id: Optional[int] = None
        self._app = None
        self.backend = "none"
        self.started_process = False

    def _import_pywinauto(self):
        try:
            from pywinauto import Application, Desktop
            from pywinauto.findwindows import ElementNotFoundError
        except Exception:
            return None
        return Application, Desktop, ElementNotFoundError

    def _import_uiautomation(self):
        try:
            import uiautomation as auto
        except Exception:
            return None
        return auto

    def _connect_or_start_pywinauto(self) -> bool:
        imported = self._import_pywinauto()
        if imported is None:
            return False
        Application, Desktop, _ = imported
        app = Application(backend="uia")
        exe_path = Path(self.executable)
        connected = False
        if self.prefer_start:
            try:
                app = Application(backend="uia").start(str(exe_path), timeout=self.startup_timeout_s)
                connected = True
                self.started_process = True
            except Exception:
                connected = False
        if not connected and exe_path.exists():
            try:
                app.connect(path=str(exe_path))
                connected = True
                self.started_process = False
            except Exception:
                connected = False
        if not connected:
            try:
                app = Application(backend="uia").start(str(exe_path), timeout=self.startup_timeout_s)
                connected = True
                self.started_process = True
            except Exception as exc:
                raise UiaSessionError(f"Unable to start {self.app_name}: {exc}") from exc
        else:
            if not self.prefer_start:
                self.started_process = False
        if not connected:
            return False
        self._app = app
        self.process_id = int(app.process)
        self.backend = "pywinauto-uia"
        # Warm-up call to ensure Desktop backend is ready.
        Desktop(backend="uia").windows(process=self.process_id)
        return True

    def _connect_or_start_uiautomation(self) -> bool:
        auto = self._import_uiautomation()
        if auto is None:
            return False
        exe_path = Path(self.executable)
        if not exe_path.exists():
            raise UiaSessionError(f"Executable not found: {exe_path}")
        process = subprocess.Popen([str(exe_path)], close_fds=True)
        self.process_id = int(process.pid)
        self._app = process
        self.backend = "uiautomation"
        self.started_process = True
        process_id = int(self.process_id or 0)

        def _window_ready():
            root = auto.GetRootControl()
            for control in root.GetChildren():
                try:
                    pid = int(getattr(control, "ProcessId", 0) or 0)
                except Exception:
                    continue
                if process_id and pid == process_id:
                    return True, None
            return False, None

        try:
            wait_until(
                predicate=_window_ready,
                timeout_s=min(float(self.startup_timeout_s), 10.0),
                initial_interval_s=0.1,
                max_interval_s=0.5,
            )
        except TimeoutError:
            pass
        return True

    def connect_or_start(self) -> None:
        self.started_process = False
        if self._connect_or_start_pywinauto():
            return
        if self.allow_fallback and self._connect_or_start_uiautomation():
            return
        raise UiaSessionError(
            "No UI Automation backend available. Install pywinauto (primary) or uiautomation (fallback)."
        )

    def _resolve_process_name(self, process_id: int) -> str:
        try:
            return Path(subprocess.check_output(["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {process_id}).Path"], text=True).strip()).name.lower()
        except Exception:
            return ""

    def list_top_windows(self) -> List[WindowInfo]:
        if self.process_id is None:
            raise UiaSessionError("Session is not connected.")
        if self.backend == "pywinauto-uia":
            return self._list_top_windows_pywinauto()
        if self.backend == "uiautomation":
            return self._list_top_windows_uiautomation()
        return []

    def _list_top_windows_pywinauto(self) -> List[WindowInfo]:
        imported = self._import_pywinauto()
        if imported is None:
            return []
        _, Desktop, _ = imported
        desktop = Desktop(backend="uia")
        process_id = int(self.process_id or 0)
        windows = desktop.windows(process=process_id)
        rows: List[WindowInfo] = []
        for wrapper in windows:
            info = wrapper.element_info
            rows.append(
                WindowInfo(
                    title=str(getattr(info, "name", "") or ""),
                    class_name=str(getattr(info, "class_name", "") or ""),
                    process_id=int(getattr(info, "process_id", process_id) or process_id),
                    process_name=self._resolve_process_name(int(getattr(info, "process_id", process_id) or process_id)),
                    framework=str(getattr(info, "framework_id", "") or ""),
                    control_type=str(getattr(info, "control_type", "") or ""),
                    automation_id=str(getattr(info, "automation_id", "") or ""),
                    handle=int(getattr(info, "handle", 0) or 0),
                )
            )
        return rows

    def _list_top_windows_uiautomation(self) -> List[WindowInfo]:
        auto = self._import_uiautomation()
        if auto is None:
            return []
        process_id = int(self.process_id or 0)
        root = auto.GetRootControl()
        rows: List[WindowInfo] = []
        for control in root.GetChildren():
            try:
                pid = int(getattr(control, "ProcessId", 0) or 0)
            except Exception:
                continue
            if process_id and pid != process_id:
                continue
            rows.append(
                WindowInfo(
                    title=str(getattr(control, "Name", "") or ""),
                    class_name=str(getattr(control, "ClassName", "") or ""),
                    process_id=pid,
                    process_name=self._resolve_process_name(pid),
                    framework=str(getattr(control, "FrameworkId", "") or ""),
                    control_type=str(getattr(control, "ControlTypeName", "") or ""),
                    automation_id=str(getattr(control, "AutomationId", "") or ""),
                    handle=int(getattr(control, "NativeWindowHandle", 0) or 0),
                )
            )
        return rows

    def _find_window_uiautomation(
        self,
        *,
        title_regex: Optional[str] = None,
        class_name_regex: Optional[str] = None,
    ):
        auto = self._import_uiautomation()
        if auto is None:
            return None
        process_id = int(self.process_id or 0)
        root = auto.GetRootControl()
        for control in root.GetChildren():
            try:
                pid = int(getattr(control, "ProcessId", 0) or 0)
            except Exception:
                continue
            if process_id and pid != process_id:
                continue
            title = str(getattr(control, "Name", "") or "")
            class_name = str(getattr(control, "ClassName", "") or "")
            if title_regex and not re.search(title_regex, title, re.IGNORECASE):
                continue
            if class_name_regex and not re.search(class_name_regex, class_name, re.IGNORECASE):
                continue
            return UiaAutomationElementAdapter(control, auto)
        return None

    def _walk_tree_dict(self, wrapper, *, max_depth: int, depth: int = 0) -> Dict[str, Any]:
        info = wrapper.element_info
        node = {
            "title": str(getattr(info, "name", "") or ""),
            "class_name": str(getattr(info, "class_name", "") or ""),
            "control_type": str(getattr(info, "control_type", "") or ""),
            "automation_id": str(getattr(info, "automation_id", "") or ""),
            "framework": str(getattr(info, "framework_id", "") or ""),
            "children": [],
        }
        if depth >= max_depth:
            return node
        try:
            children = wrapper.children()
        except Exception:
            children = []
        for child in children:
            node["children"].append(self._walk_tree_dict(child, max_depth=max_depth, depth=depth + 1))
        return node

    def dump_tree(
        self,
        *,
        output_txt: str | Path,
        output_json: str | Path,
        max_depth: int = 4,
    ) -> Dict[str, Any]:
        if self.process_id is None:
            raise UiaSessionError("Session is not connected.")
        output_txt_path = Path(output_txt)
        output_json_path = Path(output_json)
        output_txt_path.parent.mkdir(parents=True, exist_ok=True)
        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        payload: Dict[str, Any] = {
            "backend": self.backend,
            "app_name": self.app_name,
            "process_id": self.process_id,
            "generated_at": _now_iso(),
            "windows": [],
        }
        if self.backend == "pywinauto-uia":
            imported = self._import_pywinauto()
            if imported is None:
                raise UiaSessionError("pywinauto backend unavailable.")
            _, Desktop, _ = imported
            desktop = Desktop(backend="uia")
            windows = desktop.windows(process=int(self.process_id))
            text_chunks: List[str] = []
            for index, window in enumerate(windows, start=1):
                header = f"\n=== Window {index}: {window.window_text()} ===\n"
                text_chunks.append(header)
                capture = io.StringIO()
                with redirect_stdout(capture):
                    if hasattr(window, "print_control_identifiers"):
                        window.print_control_identifiers()
                    elif hasattr(window, "PrintControlIdentifiers"):
                        window.PrintControlIdentifiers()
                    else:
                        info = window.element_info
                        print(
                            f"title={getattr(info, 'name', '')} "
                            f"class={getattr(info, 'class_name', '')} "
                            f"type={getattr(info, 'control_type', '')}"
                        )
                text_chunks.append(capture.getvalue())
                payload["windows"].append(self._walk_tree_dict(window, max_depth=max_depth))
            output_txt_path.write_text("\n".join(text_chunks), encoding="utf-8")
            output_json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return {"txt_path": str(output_txt_path), "json_path": str(output_json_path), "window_count": len(windows)}

        windows = self.list_top_windows()
        payload["windows"] = [row.to_dict() for row in windows]
        output_txt_path.write_text(
            "\n".join(f"{row.title} | {row.class_name} | pid={row.process_id}" for row in windows),
            encoding="utf-8",
        )
        output_json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"txt_path": str(output_txt_path), "json_path": str(output_json_path), "window_count": len(windows)}

    def find_window(self, *, title_regex: Optional[str] = None, class_name_regex: Optional[str] = None):
        if self.backend == "pywinauto-uia":
            imported = self._import_pywinauto()
            if imported is not None:
                _, Desktop, _ = imported
                windows = Desktop(backend="uia").windows(process=int(self.process_id or 0))
                for window in windows:
                    info = window.element_info
                    title = str(getattr(info, "name", "") or "")
                    class_name = str(getattr(info, "class_name", "") or "")
                    if title_regex and not re.search(title_regex, title, re.IGNORECASE):
                        continue
                    if class_name_regex and not re.search(class_name_regex, class_name, re.IGNORECASE):
                        continue
                    return window
            if self.allow_fallback:
                return self._find_window_uiautomation(title_regex=title_regex, class_name_regex=class_name_regex)
            return None
        if self.backend == "uiautomation":
            return self._find_window_uiautomation(title_regex=title_regex, class_name_regex=class_name_regex)
        return None

    def close(self) -> None:
        if self.backend == "pywinauto-uia" and self._app is not None and bool(self.started_process):
            try:
                self._app.kill(soft=True)  # type: ignore[attr-defined]
                return
            except Exception:
                pass
            try:
                if self.process_id:
                    subprocess.run(
                        ["taskkill", "/PID", str(int(self.process_id)), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
            except Exception:
                pass
        if self.backend == "uiautomation" and self._app is not None:
            try:
                self._app.terminate()  # type: ignore[attr-defined]
            except Exception:
                pass
