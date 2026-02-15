"""Deterministic AKABAK UIA driver (pywinauto primary, no pixel scanning)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from app.ui_automation.session import UiaSession, UiaSessionError
from app.ui_automation.step_logger import StructuredStepLogger
from app.ui_automation.waits import wait_until
from app.ui_automation.watchdog import ModalDialogWatchdog
from app.ui_contracts.window_signatures import AKABAK_MAIN_WINDOW, AKABAK_SOLVE_PROGRESS


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

        self._log(level="info", step=step, event="action_open_shortcut", payload={"project": project_path})
        try:
            main_window.set_focus()
            main_window.type_keys("^o")
            file_dialog = None

            def _dialog_ready():
                dialog = self.session.find_window(
                    title_regex=r"(Open|Import|ABEC)",
                    class_name_regex=r"(#32770|Dialog)",
                )
                return (dialog is not None, dialog)

            try:
                file_dialog = wait_until(
                    predicate=_dialog_ready,
                    timeout_s=min(float(self.step_timeout_s), 5.0),
                )
            except TimeoutError:
                file_dialog = None
            if file_dialog is not None:
                file_dialog.type_keys(project_path, with_spaces=True, set_foreground=True)
                file_dialog.type_keys("{ENTER}")
            else:
                self._log(
                    level="warn",
                    step=step,
                    event="dialog_not_found",
                    payload={"note": "Ctrl+O sent but no file dialog detected."},
                )
        except Exception as exc:
            raise RuntimeError(f"Failed to open project in AKABAK: {exc}") from exc

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
        self._log(level="info", step=step, event="idempotent_noop", payload={"state": self.state})
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
