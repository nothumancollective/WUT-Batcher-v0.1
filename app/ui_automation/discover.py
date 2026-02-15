"""UI discovery utilities for PID-scoped window/control dumps."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.ui_automation.session import UiaSession


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _node_from_wrapper(wrapper, *, depth: int, max_depth: int) -> Dict[str, Any]:
    info = wrapper.element_info
    node = {
        "title": str(getattr(info, "name", "") or ""),
        "class_name": str(getattr(info, "class_name", "") or ""),
        "control_type": str(getattr(info, "control_type", "") or ""),
        "automation_id": str(getattr(info, "automation_id", "") or ""),
        "handle": int(getattr(info, "handle", 0) or 0),
        "children": [],
    }
    if depth >= max_depth:
        return node
    try:
        children = wrapper.children()
    except Exception:
        children = []
    for child in children:
        node["children"].append(_node_from_wrapper(child, depth=depth + 1, max_depth=max_depth))
    return node


def discover_app_ui(
    *,
    app: str,
    executable: Optional[str],
    pid: Optional[int],
    output_root: str | Path,
    startup_timeout_s: int = 20,
    max_depth: int = 2,
) -> Dict[str, Any]:
    app_name = str(app).strip().lower()
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = _now_stamp()
    summary_path = output_dir / f"{app_name}_discover_{stamp}.json"
    tree_path = output_dir / f"{app_name}_discover_tree_{stamp}.json"

    active_pid = int(pid or 0)
    session_backend = "none"
    started_process = False

    session: Optional[UiaSession] = None
    if active_pid <= 0:
        if not executable:
            raise ValueError("Executable is required when --pid is not provided.")
        session = UiaSession(
            executable=executable,
            app_name=app_name,
            startup_timeout_s=startup_timeout_s,
            allow_fallback=True,
        )
        session.connect_or_start()
        active_pid = int(session.process_id or 0)
        session_backend = str(session.backend)
        started_process = bool(session.started_process)

    try:
        from pywinauto import Desktop
    except Exception as exc:
        payload = {
            "app": app_name,
            "error": f"pywinauto unavailable: {exc}",
            "pid": active_pid,
            "summary_path": str(summary_path),
            "tree_path": str(tree_path),
        }
        summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload

    desktop = Desktop(backend="uia")
    windows = desktop.windows(process=active_pid) if active_pid > 0 else []
    window_rows: List[Dict[str, Any]] = []
    tree_rows: List[Dict[str, Any]] = []
    for window in windows:
        info = window.element_info
        row = {
            "title": str(getattr(info, "name", "") or ""),
            "class_name": str(getattr(info, "class_name", "") or ""),
            "control_type": str(getattr(info, "control_type", "") or ""),
            "automation_id": str(getattr(info, "automation_id", "") or ""),
            "handle": int(getattr(info, "handle", 0) or 0),
            "process_id": int(getattr(info, "process_id", active_pid) or active_pid),
        }
        window_rows.append(row)
        tree_rows.append(_node_from_wrapper(window, depth=0, max_depth=max_depth))

    payload = {
        "app": app_name,
        "pid": active_pid,
        "backend": session_backend,
        "started_process": started_process,
        "window_count": len(window_rows),
        "windows": window_rows,
        "summary_path": str(summary_path),
        "tree_path": str(tree_path),
    }
    summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tree_path.write_text(json.dumps({"app": app_name, "pid": active_pid, "windows": tree_rows}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if session is not None:
        session.close()
    return payload
