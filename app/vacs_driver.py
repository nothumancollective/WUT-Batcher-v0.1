"""Deterministic VACS UIA driver using versioned export recipes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional

from app.ui_automation.recipes import load_vacs_export_recipes, recipe_index_by_id
from app.ui_automation.session import UiaSession
from app.ui_automation.step_logger import StructuredStepLogger
from app.ui_automation.watchdog import ModalDialogWatchdog
from app.ui_contracts.window_signatures import VACS_EXPORT_DIALOG, VACS_MAIN_WINDOW


@dataclass(frozen=True)
class VacsDriverResult:
    ok: bool
    status: str
    details: Dict[str, Any]


class VacsDriver:
    def __init__(
        self,
        *,
        executable: str | Path,
        log_dir: str | Path,
        startup_timeout_s: int = 20,
    ) -> None:
        self.executable = str(executable)
        self.log_dir = Path(log_dir)
        self.state = "init"
        self.current_results: Optional[str] = None
        self.current_graph: Optional[str] = None
        self.session = UiaSession(
            executable=self.executable,
            app_name="vacs",
            startup_timeout_s=startup_timeout_s,
            allow_fallback=True,
        )
        self.logger = StructuredStepLogger(self.log_dir / "vacs_driver.log.jsonl")
        recipes = load_vacs_export_recipes()
        self.recipes = recipe_index_by_id(recipes)
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
        self.session.connect_or_start()
        self.watchdog = ModalDialogWatchdog(
            process_id=self.session.process_id,
            output_dir=self.log_dir / "watchdog",
            capture_screenshot=True,
            global_timeout_s=300,
        )
        window = self.session.find_window(
            title_regex=VACS_MAIN_WINDOW.title_regex,
            class_name_regex=VACS_MAIN_WINDOW.class_name_regex,
        )
        self._require(window is not None, "VACS main window was not found.", step)
        self.state = "ready"
        self._log(
            level="info",
            step=step,
            event="connected",
            payload={"process_id": self.session.process_id, "backend": self.session.backend},
        )

    def open_results(self, project_or_abec_path: str | Path) -> VacsDriverResult:
        step = "open_results"
        target = str(Path(project_or_abec_path).resolve())
        self._connect()
        if self.state in {"results_open", "graph_open"} and self.current_results == target:
            return VacsDriverResult(ok=True, status=self.state, details={"idempotent": True, "target": target})

        self._require(Path(target).exists(), f"Results input not found: {target}", step)
        window = self.session.find_window(
            title_regex=VACS_MAIN_WINDOW.title_regex,
            class_name_regex=VACS_MAIN_WINDOW.class_name_regex,
        )
        self._require(window is not None, "VACS main window is unavailable.", step)

        try:
            window.set_focus()
            window.type_keys("^o")
            time.sleep(0.5)
            dialog = self.session.find_window(
                title_regex=r"(Open|Import|Project|ABEC)",
                class_name_regex=r"(#32770|Dialog)",
            )
            if dialog is not None:
                dialog.type_keys(target, with_spaces=True, set_foreground=True)
                dialog.type_keys("{ENTER}")
        except Exception as exc:
            raise RuntimeError(f"Failed opening results in VACS: {exc}") from exc

        if self.watchdog:
            handled = self.watchdog.run_watch(step_name=step, timeout_s=5)
            if handled:
                self._log(level="info", step=step, event="watchdog_handled", payload={"count": len(handled)})

        self.current_results = target
        self.state = "results_open"
        self._log(level="info", step=step, event="results_open", payload={"target": target})
        return VacsDriverResult(ok=True, status=self.state, details={"target": target})

    def open_graph(self, graph_type: str) -> VacsDriverResult:
        step = "open_graph"
        self._connect()
        self._require(self.state in {"results_open", "graph_open"}, "Results must be open before graph selection.", step)
        window = self.session.find_window(
            title_regex=VACS_MAIN_WINDOW.title_regex,
            class_name_regex=VACS_MAIN_WINDOW.class_name_regex,
        )
        self._require(window is not None, "VACS main window is unavailable.", step)
        try:
            window.set_focus()
            # Menu navigation contract: Alt+G opens graph menu in known builds.
            window.type_keys("%g")
            window.type_keys(str(graph_type))
            window.type_keys("{ENTER}")
        except Exception as exc:
            raise RuntimeError(f"Failed selecting graph '{graph_type}': {exc}") from exc
        self.current_graph = str(graph_type)
        self.state = "graph_open"
        self._log(level="info", step=step, event="graph_open", payload={"graph_type": graph_type})
        return VacsDriverResult(ok=True, status=self.state, details={"graph_type": graph_type})

    def _apply_recipe_settings(self, recipe: Dict[str, Any], *, export_profile: Dict[str, Any]) -> None:
        dialog = self.session.find_window(
            title_regex=VACS_EXPORT_DIALOG.title_regex,
            class_name_regex=VACS_EXPORT_DIALOG.class_name_regex,
        )
        if dialog is None:
            return
        required = list(recipe.get("required_settings", []) or [])
        for setting in required:
            key = str(setting.get("key", "")).strip()
            if not key:
                continue
            value = export_profile.get(key, setting.get("default"))
            if value is None:
                continue
            try:
                dialog.type_keys(str(value), with_spaces=True, set_foreground=True)
                dialog.type_keys("{TAB}")
            except Exception:
                continue

    def export_txt(self, export_profile: Dict[str, Any]) -> VacsDriverResult:
        step = "export_txt"
        self._connect()
        self._require(self.state == "graph_open", "Graph must be open before export.", step)
        graph_type = str(export_profile.get("graph_type") or self.current_graph or "").strip()
        self._require(bool(graph_type), "Export profile requires graph_type.", step)

        recipe_id = str(export_profile.get("recipe_id", "")).strip()
        recipe = self.recipes.get(recipe_id) if recipe_id else None
        if recipe is None:
            for candidate in self.recipes.values():
                if str(candidate.get("graph_type", "")).lower() == graph_type.lower():
                    recipe = candidate
                    break
        self._require(recipe is not None, f"No VACS export recipe found for graph '{graph_type}'.", step)

        window = self.session.find_window(
            title_regex=VACS_MAIN_WINDOW.title_regex,
            class_name_regex=VACS_MAIN_WINDOW.class_name_regex,
        )
        self._require(window is not None, "VACS main window is unavailable.", step)

        output_file = str(export_profile.get("output_file", "")).strip()
        self._require(bool(output_file), "Export profile requires output_file path.", step)
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            window.set_focus()
            window.type_keys("^s")
            time.sleep(0.5)
            self._apply_recipe_settings(recipe, export_profile=export_profile)
            dialog = self.session.find_window(
                title_regex=VACS_EXPORT_DIALOG.title_regex,
                class_name_regex=VACS_EXPORT_DIALOG.class_name_regex,
            )
            if dialog is not None:
                dialog.type_keys(str(output_path), with_spaces=True, set_foreground=True)
                dialog.type_keys("{ENTER}")
        except Exception as exc:
            raise RuntimeError(f"Failed exporting VACS TXT: {exc}") from exc

        if self.watchdog:
            handled = self.watchdog.run_watch(step_name=step, timeout_s=8)
            if handled:
                self._log(level="info", step=step, event="watchdog_handled", payload={"count": len(handled)})

        file_pattern = str(recipe.get("expected_output", {}).get("file_pattern", r".*\.txt$"))
        exported = [path for path in output_path.parent.glob("*") if re.search(file_pattern, path.name, re.IGNORECASE)]
        self._require(bool(exported), f"Export file pattern not satisfied: {file_pattern}", step)
        self._log(
            level="info",
            step=step,
            event="export_ok",
            payload={"recipe_id": recipe.get("recipe_id"), "output_file": str(output_path), "matches": len(exported)},
        )
        return VacsDriverResult(
            ok=True,
            status=self.state,
            details={"recipe_id": recipe.get("recipe_id"), "output_file": str(output_path), "matches": len(exported)},
        )

    def close(self) -> VacsDriverResult:
        step = "close"
        if self.state == "closed":
            return VacsDriverResult(ok=True, status=self.state, details={"idempotent": True})
        window = self.session.find_window(
            title_regex=VACS_MAIN_WINDOW.title_regex,
            class_name_regex=VACS_MAIN_WINDOW.class_name_regex,
        )
        if window is not None:
            try:
                window.close()
            except Exception:
                pass
        self.session.close()
        self.state = "closed"
        self._log(level="info", step=step, event="closed", payload={})
        return VacsDriverResult(ok=True, status=self.state, details={})
