from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from pywinauto import Desktop

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.vacs_export_enforcer import (
    BST_CHECKED,
    BST_UNCHECKED,
    REQUIRED_EXPORT_CONTROLS,
    Win32UiaExportDialogBackend,
    _state_label,
    find_export_dialog,
)


WM_COMMAND = 0x0111
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_F7 = 0x76
VACS_EXPORT_COMMAND_ID = 52


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _window_signature(window: Any) -> Dict[str, Any]:
    info = getattr(window, "element_info", None)
    return {
        "handle": _safe_int(getattr(info, "handle", 0), 0),
        "title": str(getattr(info, "name", "") or ""),
        "class_name": str(getattr(info, "class_name", "") or ""),
        "control_type": str(getattr(info, "control_type", "") or ""),
        "automation_id": str(getattr(info, "automation_id", "") or ""),
        "process_id": _safe_int(getattr(info, "process_id", 0), 0),
    }


def _running_vacs_pids() -> List[int]:
    rows: List[int] = []
    for image in ("VACSVIEWER_32.exe", "vacsviewer.exe"):
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except Exception:
            continue
        for line in (proc.stdout or "").splitlines():
            line = str(line).strip()
            if not line or line.lower().startswith("info:"):
                continue
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) < 2:
                continue
            pid = parts[1]
            if pid.isdigit():
                rows.append(int(pid))
    return sorted(set(rows))


def _find_main_window_for_pid(pid: int) -> Optional[Any]:
    try:
        windows = list(Desktop(backend="uia").windows(process=int(pid)))
    except Exception:
        return None
    for w in windows:
        sig = _window_signature(w)
        if str(sig.get("class_name", "")) == "TForm_DatMain":
            return w
    return None


def _find_graph_window_for_pid(pid: int) -> Optional[Any]:
    try:
        windows = list(Desktop(backend="uia").windows(process=int(pid)))
    except Exception:
        return None
    for w in windows:
        sig = _window_signature(w)
        if str(sig.get("class_name", "")) in {"TForm_DatGraph", "TForm_DatContour"}:
            return w
    return None


def _trigger_export_dialog(pid: int) -> List[Dict[str, Any]]:
    attempts: List[Dict[str, Any]] = []
    main = _find_main_window_for_pid(int(pid))
    main_handle = _safe_int(_window_signature(main).get("handle", 0), 0) if main is not None else 0
    graph = _find_graph_window_for_pid(int(pid))
    graph_handle = _safe_int(_window_signature(graph).get("handle", 0), 0) if graph is not None else 0

    if main_handle > 0:
        try:
            ctypes.windll.user32.SendMessageW(int(main_handle), WM_COMMAND, int(VACS_EXPORT_COMMAND_ID), 0)
            attempts.append({"method": "main_wm_command_52", "status": "ok", "main_handle": int(main_handle)})
        except Exception as exc:
            attempts.append({"method": "main_wm_command_52", "status": "error", "error": repr(exc), "main_handle": int(main_handle)})
    else:
        attempts.append({"method": "main_wm_command_52", "status": "skipped", "reason": "main_window_missing"})

    for label, handle in (("graph_f7", graph_handle), ("main_f7", main_handle)):
        if handle <= 0:
            attempts.append({"method": label, "status": "skipped", "reason": "handle_missing"})
            continue
        try:
            ctypes.windll.user32.PostMessageW(int(handle), WM_KEYDOWN, VK_F7, 0)
            ctypes.windll.user32.PostMessageW(int(handle), WM_KEYUP, VK_F7, 0)
            attempts.append({"method": label, "status": "ok", "handle": int(handle)})
        except Exception as exc:
            attempts.append({"method": label, "status": "error", "error": repr(exc), "handle": int(handle)})
    return attempts


def _restore_state(backend: Win32UiaExportDialogBackend, control: Any, target_state: int) -> Dict[str, Any]:
    details: List[Dict[str, Any]] = []
    current = backend.read_state(control)
    if current is None:
        return {"restored": False, "final_state": None, "attempts": details}
    if int(current) == int(target_state):
        return {"restored": True, "final_state": int(current), "attempts": details}

    for method in ("bm_setcheck", "bm_click", "uia_toggle", "uia_invoke"):
        try:
            after = backend.apply_method(control, method, int(target_state))
            details.append(
                {
                    "method": method,
                    "after_state": _state_label(after),
                    "success": bool(after is not None and int(after) == int(target_state)),
                }
            )
            if after is not None and int(after) == int(target_state):
                return {"restored": True, "final_state": int(after), "attempts": details}
        except Exception as exc:
            details.append({"method": method, "success": False, "error": repr(exc)})
    final = backend.read_state(control)
    return {"restored": bool(final is not None and int(final) == int(target_state)), "final_state": final, "attempts": details}


def _method_sequence_for_probe() -> Tuple[str, ...]:
    return ("bm_setcheck", "bm_click", "uia_toggle", "uia_invoke")


def _probe_control(backend: Win32UiaExportDialogBackend, spec: Any) -> Dict[str, Any]:
    control, selector_used = backend.resolve_control(spec)
    if control is None:
        return {
            "purpose": spec.purpose,
            "selector_used": selector_used,
            "found": False,
            "before_state": None,
            "after_state": None,
            "settable": False,
            "attempts": [],
            "restore": {"restored": False, "final_state": None, "attempts": []},
            "reason": "control_not_found",
        }

    matched_control = {
        "handle": _safe_int(getattr(control, "handle", 0), 0),
        "class_name": str(getattr(control, "class_name", "") or ""),
        "control_type": str(getattr(control, "control_type", "") or ""),
        "automation_id": str(getattr(control, "automation_id", "") or ""),
        "title": str(getattr(control, "title", "") or ""),
        "text": str(getattr(control, "text", "") or ""),
        "ctrl_id": _safe_int(getattr(control, "ctrl_id", -1), -1),
        "checkbox_index": getattr(control, "checkbox_index", None),
        "win32_index": getattr(control, "win32_index", None),
    }

    before_state = backend.read_state(control)
    attempts: List[Dict[str, Any]] = []
    if before_state is None:
        return {
            "purpose": spec.purpose,
            "selector_used": selector_used,
            "matched_control": matched_control,
            "found": True,
            "before_state": None,
            "after_state": None,
            "settable": False,
            "attempts": [],
            "restore": {"restored": False, "final_state": None, "attempts": []},
            "reason": "state_unreadable",
        }

    toggled_target = BST_UNCHECKED if int(before_state) == int(BST_CHECKED) else BST_CHECKED
    settable = False
    last_state = before_state
    for method in _method_sequence_for_probe():
        if not backend.is_alive(control):
            attempts.append(
                {
                    "method": method,
                    "before_state": _state_label(last_state),
                    "after_state": "DISAPPEARED",
                    "success": False,
                    "error": "control_disappeared",
                }
            )
            continue

        ensure_original = _restore_state(backend, control, int(before_state))
        if not bool(ensure_original.get("restored")):
            attempts.append(
                {
                    "method": method,
                    "before_state": _state_label(before_state),
                    "after_state": "RESTORE_FAILED",
                    "success": False,
                    "error": "could_not_restore_original_before_attempt",
                }
            )
            continue

        before = backend.read_state(control)
        if before is None:
            attempts.append({"method": method, "before_state": "UNKNOWN", "after_state": "UNKNOWN", "success": False})
            continue
        try:
            after = backend.apply_method(control, method, int(toggled_target))
            success = bool(after is not None and int(after) != int(before))
            attempts.append(
                {
                    "method": method,
                    "before_state": _state_label(before),
                    "after_state": _state_label(after),
                    "success": bool(success),
                }
            )
            if success:
                settable = True
            last_state = after if after is not None else before
        except Exception as exc:
            attempts.append(
                {
                    "method": method,
                    "before_state": _state_label(before),
                    "after_state": "ERROR",
                    "success": False,
                    "error": repr(exc),
                }
            )
            last_state = before

    restore = _restore_state(backend, control, int(before_state))
    after_state = backend.read_state(control)
    return {
        "purpose": spec.purpose,
        "selector_used": selector_used,
        "matched_control": matched_control,
        "found": True,
        "before_state": before_state,
        "after_state": after_state,
        "settable": bool(settable),
        "attempts": attempts,
        "restore": restore,
        "reason": None if settable else "no_method_changed_state",
    }


def _render_markdown_report(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# VACS Export Setter Probe Report")
    lines.append("")
    lines.append(f"- Generated at: `{payload.get('generated_at')}`")
    lines.append(f"- Dialog found: `{bool(payload.get('dialog_found'))}`")
    lines.append(f"- Process ID: `{payload.get('process_id')}`")
    if payload.get("dialog_signature"):
        lines.append(f"- Dialog signature: `{json.dumps(payload.get('dialog_signature', {}), ensure_ascii=False)}`")
    lines.append("")
    lines.append("## Control Settable Classification")
    lines.append("")
    lines.append("| ControlPurpose | Found | BeforeState | Settable | Reason |")
    lines.append("|---|---|---|---|---|")
    for row in list(payload.get("controls", []) or []):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("purpose", "")),
                    "yes" if bool(row.get("found")) else "no",
                    _state_label(row.get("before_state")),
                    "SETTABLE" if bool(row.get("settable")) else "NON-SETTABLE",
                    str(row.get("reason") or ""),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Matched Controls")
    lines.append("")
    lines.append("| ControlPurpose | Handle | ClassName | ControlType | AutomationId | CtrlId | CheckboxIndex | Win32Index | Title/Text |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for row in list(payload.get("controls", []) or []):
        matched = dict(row.get("matched_control") or {})
        title = str(matched.get("title", "") or "")
        text = str(matched.get("text", "") or "")
        combined = (title + " / " + text).strip(" /")
        if len(combined) > 80:
            combined = combined[:77] + "..."
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("purpose", "")),
                    str(matched.get("handle", "")),
                    str(matched.get("class_name", "")),
                    str(matched.get("control_type", "")),
                    str(matched.get("automation_id", "")),
                    str(matched.get("ctrl_id", "")),
                    str(matched.get("checkbox_index", "")),
                    str(matched.get("win32_index", "")),
                    combined.replace("|", "/"),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Method Attempt Table")
    lines.append("")
    lines.append("| ControlPurpose | SelectorUsed | MethodAttempted | BeforeState | AfterState | Success |")
    lines.append("|---|---|---|---|---|---|")
    for row in list(payload.get("controls", []) or []):
        attempts = list(row.get("attempts", []) or [])
        if not attempts:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("purpose", "")),
                        str(row.get("selector_used", "")),
                        "none",
                        _state_label(row.get("before_state")),
                        _state_label(row.get("after_state")),
                        "false",
                    ]
                )
                + " |"
            )
            continue
        for attempt in attempts:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("purpose", "")),
                        str(row.get("selector_used", "")),
                        str(attempt.get("method", "")),
                        str(attempt.get("before_state", "")),
                        str(attempt.get("after_state", "")),
                        "true" if bool(attempt.get("success")) else "false",
                    ]
                )
                + " |"
            )
    lines.append("")
    if payload.get("trigger_attempts"):
        lines.append("## Dialog Trigger Attempts")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(payload.get("trigger_attempts", []), indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_reports(payload: Dict[str, Any], markdown_path: Path, json_path: Path) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_render_markdown_report(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_probe(args: argparse.Namespace) -> Dict[str, Any]:
    process_id = _safe_int(getattr(args, "process_id", 0), 0) or None
    vacs_exe = str(getattr(args, "vacs_exe", "") or "").strip()
    attach_only = bool(getattr(args, "attach_only", False))
    dialog_timeout_s = float(getattr(args, "dialog_timeout_s", 3.0) or 3.0)

    payload: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "dialog_found": False,
        "process_id": process_id,
        "dialog_signature": None,
        "controls": [],
        "trigger_attempts": [],
        "errors": [],
    }

    started_proc = None
    try:
        if process_id is None:
            pids = _running_vacs_pids()
            if pids:
                process_id = int(pids[0])
                payload["process_id"] = process_id
        if process_id is None and (not attach_only) and vacs_exe:
            try:
                started_proc = subprocess.Popen([vacs_exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                process_id = int(started_proc.pid)
                payload["process_id"] = process_id
                time.sleep(0.8)
            except Exception as exc:
                payload["errors"].append({"stage": "start_vacs", "error": repr(exc)})

        dialog = find_export_dialog(process_id=process_id, timeout_s=dialog_timeout_s)
        if dialog is None and not attach_only and process_id is not None:
            payload["trigger_attempts"] = _trigger_export_dialog(process_id)
            dialog = find_export_dialog(process_id=process_id, timeout_s=dialog_timeout_s)

        if dialog is None:
            payload["dialog_found"] = False
            payload["errors"].append({"stage": "find_dialog", "error": "export_dialog_not_found"})
            for spec in REQUIRED_EXPORT_CONTROLS:
                payload["controls"].append(
                    {
                        "purpose": spec.purpose,
                        "selector_used": "dialog_missing",
                        "found": False,
                        "before_state": None,
                        "after_state": None,
                        "settable": False,
                        "attempts": [],
                        "restore": {"restored": False, "final_state": None, "attempts": []},
                        "reason": "dialog_not_found",
                    }
                )
            return payload

        payload["dialog_found"] = True
        payload["dialog_signature"] = _window_signature(dialog)
        backend = Win32UiaExportDialogBackend(dialog)
        for spec in REQUIRED_EXPORT_CONTROLS:
            try:
                row = _probe_control(backend, spec)
            except Exception as exc:
                row = {
                    "purpose": spec.purpose,
                    "selector_used": "probe_exception",
                    "found": False,
                    "before_state": None,
                    "after_state": None,
                    "settable": False,
                    "attempts": [],
                    "restore": {"restored": False, "final_state": None, "attempts": []},
                    "reason": "probe_exception",
                    "error": repr(exc),
                }
            payload["controls"].append(row)
        return payload
    finally:
        if started_proc is not None:
            try:
                started_proc.terminate()
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe whether VACS export dialog controls are programmatically settable.")
    parser.add_argument("--process-id", type=int, default=0, help="Attach to this VACS process id.")
    parser.add_argument(
        "--vacs-exe",
        default=r"C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe",
        help="VACS executable path (used only when starting a process).",
    )
    parser.add_argument("--attach-only", action="store_true", help="Do not try to trigger/open export dialog.")
    parser.add_argument("--dialog-timeout-s", type=float, default=3.0, help="Timeout waiting for export dialog.")
    parser.add_argument("--report-md", default="docs/vacs_export_setter_probe_report.md")
    parser.add_argument("--report-json", default="docs/vacs_export_setter_probe_report.json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = run_probe(args)
    report_md = Path(str(args.report_md)).resolve()
    report_json = Path(str(args.report_json)).resolve()
    _write_reports(payload, report_md, report_json)
    print(json.dumps({"ok": bool(payload.get("dialog_found")), "report_md": str(report_md), "report_json": str(report_json)}, ensure_ascii=False))
    return 0 if bool(payload.get("dialog_found")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
