"""Modal dialog watchdog and recovery for deterministic UI automation runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence


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
            ]
        )

    def _import_pywinauto(self):
        try:
            from pywinauto import Desktop
        except Exception:
            return None
        return Desktop

    def _candidate_dialogs(self) -> List[Any]:
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

    def _capture_debug_artifacts(self, *, window, reason: str) -> Dict[str, Any]:
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
        }
        debug_path = self.output_dir / f"unknown_dialog_{stamp}.json"
        debug_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        screenshot_path = None
        return {"debug_path": str(debug_path), "screenshot_path": screenshot_path, "payload": payload}

    def _click_action(self, *, window, action: str) -> bool:
        normalized = str(action).lower().strip()
        button_titles = {
            "ok": ("OK", "Ok", "Yes", "Ja", "Continue", "Fortfahren"),
            "cancel": ("Cancel", "No"),
            "close": ("Close", "Cancel", "No"),
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
            if matched_rule is None:
                debug = self._capture_debug_artifacts(window=window, reason="unknown_modal_dialog")
                raise UnknownDialogError(
                    f"Unknown modal dialog detected: {title}. Debug: {debug['debug_path']}"
                )
            self._click_action(window=window, action=matched_rule.action)
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
