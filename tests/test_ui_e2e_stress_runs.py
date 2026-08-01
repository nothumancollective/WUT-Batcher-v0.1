from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import BatchRunDefaultsDialog, GuiController
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QTimer = None  # type: ignore[assignment]
    QMessageBox = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_fake_toolchain(root: Path) -> dict[str, str]:
    tools_dir = root / "tools"
    ath_script = tools_dir / "ath_fake.py"
    akabak_script = tools_dir / "akabak_fake.py"
    vacs_script = tools_dir / "vacs_fake.py"
    ath_cmd = tools_dir / "ath_fake.cmd"
    akabak_cmd = tools_dir / "akabak_fake.cmd"
    vacs_cmd = tools_dir / "vacs_fake.cmd"

    _write_executable(
        ath_script,
        """
from pathlib import Path
import sys

cfg_path = Path(sys.argv[-1]).expanduser().resolve()
print("Length=111 Width=222 Height=333")

try:
    version_dir = cfg_path.parent.parent
    abec_path = version_dir / "abec" / "Project.abec"
    abec_path.parent.mkdir(parents=True, exist_ok=True)
    abec_path.write_text(
        "[Project]\\n"
        "Scriptname_Solving=solving.txt\\n"
        "[Observation]\\n"
        "C0=observation.txt\\n"
        "[LEScript]\\n"
        "Scriptname_LEScript=generic25.txt\\n",
        encoding="utf-8",
    )
    (abec_path.parent / "solving.txt").write_text(
        'Driving "S1001"\\n  RefElements="A"; DrvGroup=1001;\\n',
        encoding="utf-8",
    )
    (abec_path.parent / "observation.txt").write_text(
        "Driving_Values\\n"
        "  DrvType=Acceleration; Value=1.0\\n"
        "  401 DrvGroup=1001 Weight=1\\n\\n"
        "Radiation_Impedance\\n"
        "  RadImpType=Normalized\\n"
        "  402 1001 1001 ID=8001\\n",
        encoding="utf-8",
    )
except Exception:
    pass

try:
    export_dir = Path(r"C:\\Horns") / cfg_path.stem
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "mesh.stl").write_text(
        "solid mesh\\n"
        "facet normal 0 0 1\\n"
        "  outer loop\\n"
        "    vertex 0 0 0\\n"
        "    vertex 1 0 0\\n"
        "    vertex 0 1 0\\n"
        "  endloop\\n"
        "endfacet\\n"
        "endsolid mesh\\n",
        encoding="utf-8",
    )
except Exception:
    pass
""".strip()
        + "\n",
    )
    _write_executable(
        akabak_script,
        """
import sys
print("AKABAK OK", sys.argv[-1] if len(sys.argv) > 1 else "")
""".strip()
        + "\n",
    )
    _write_executable(
        vacs_script,
        """
from pathlib import Path
import sys

_ = sys.argv[-1] if len(sys.argv) > 1 else ""
target = Path.cwd() / "Result_V001SPL.txt"
target.write_text("Frequency [Hz];SPL [dB]\\n100;90,5\\n200;91,0\\n", encoding="utf-8")
print("VACS OK", str(target))
""".strip()
        + "\n",
    )
    _write_executable(ath_cmd, '@echo off\r\npython "%~dp0\\ath_fake.py" %*\r\n')
    _write_executable(akabak_cmd, '@echo off\r\npython "%~dp0\\akabak_fake.py" %*\r\n')
    _write_executable(vacs_cmd, '@echo off\r\npython "%~dp0\\vacs_fake.py" %*\r\n')

    drivers_dir = tools_dir / "lib" / "drivers"
    drivers_dir.mkdir(parents=True, exist_ok=True)
    _write_executable(
        drivers_dir / "generic25.txt",
        "Def_Driver 'D1'\nDriver 'D1'\n",
    )
    return {
        "ath_exe": str(ath_cmd),
        "akabak_exe": str(akabak_cmd),
        "vacs_exe": str(vacs_cmd),
    }


@unittest.skipIf(QApplication is None or QTimer is None, "PySide6 is required")
class UiE2EStressRunsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _pump(self, seconds: float) -> None:
        end = time.perf_counter() + max(seconds, 0.0)
        while time.perf_counter() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def _wait_until(self, predicate, *, timeout_s: float, label: str) -> None:
        end = time.perf_counter() + timeout_s
        while time.perf_counter() < end:
            self.app.processEvents()
            if bool(predicate()):
                return
            time.sleep(0.02)
        raise TimeoutError(f"Timeout waiting for {label}")

    def _click_button(self, root, text: str) -> None:
        buttons = [btn for btn in root.findChildren(QPushButton) if str(btn.text()).strip() == text]
        self.assertTrue(buttons, f"Button '{text}' not found")
        buttons[0].click()
        self._pump(0.05)

    def _set_project_constraints(self, controller: GuiController, *, project_name: str) -> None:
        main = controller.main_window
        page = main.project_page
        page.project_name.setText(project_name)
        form = page.constraints_form

        values = {
            "Throat.Profile": 1,
            "Throat.Diameter": 25.4,
            "Throat.Angle": 7.0,
            "Term.s": 0.5,
            "Term.n": 4.0,
            "Term.q": 0.996,
            "Morph.TargetShape": 0,
            "Mesh.ThroatResolution": 4.0,
            "Mesh.MouthResolution": 4.0,
            "Mesh.Quadrants": 4,
            "Mesh.LengthSegments": 20,
            "Mesh.AngularSegments": 32,
        }
        for key, value in values.items():
            editor = form.editor_for_key(key)
            self.assertIsNotNone(editor, key)
            self.assertTrue(hasattr(editor, "set_value"), key)
            editor.set_value(value)  # type: ignore[attr-defined]
            self._pump(0.03)
        page.create_btn.click()
        self._wait_until(lambda: main.current_project is not None and main.stack.currentWidget() is main.dashboard_page, timeout_s=6.0, label="project creation")

    def _configure_batch_with_sweeps(self, controller: GuiController, *, batch_name: str) -> None:
        main = controller.main_window
        main.dashboard_page.new_batch_btn.click()
        self._wait_until(lambda: main.stack.currentWidget() is main.batch_page, timeout_s=3.0, label="batch page visible")

        page = main.batch_page
        form = page.parameter_form
        page.batch_name.setText(batch_name)

        # Variable parameters (not fixed on project page) in this stress scenario.
        for key, value in {"Length": 100.0, "Coverage.Angle": 45.0}.items():
            row = form._rows.get(key)  # type: ignore[attr-defined]
            self.assertIsNotNone(row, key)
            form._set_editor_value(row, value)  # type: ignore[attr-defined]
            form._on_field_edited(key)  # type: ignore[attr-defined]
            self._pump(0.03)

        for key, start, end in (
            ("Length", 100.0, 110.0),
            ("Coverage.Angle", 45.0, 50.0),
        ):
            toggle = form.sweep_toggle_for_key(key)
            self.assertIsNotNone(toggle, f"sweep toggle missing for {key}")
            self.assertTrue(toggle.isEnabled(), f"sweep toggle disabled for {key}")
            if not toggle.isChecked():
                toggle.click()
            inputs = form.sweep_inputs_for_key(key)
            self.assertIsNotNone(inputs, f"sweep inputs missing for {key}")
            inputs["start"].setText(str(start))
            inputs["end"].setText(str(end))
            inputs["steps"].setText("2")
            self._pump(0.03)

    def _wait_for_preview_refresh(self, controller: GuiController) -> tuple[str, str]:
        page = controller.main_window.batch_page
        self._wait_until(
            lambda: (page.preview_panel.last_preview_path() is not None) and (not page.preview_panel._busy),  # type: ignore[attr-defined]
            timeout_s=18.0,
            label="first preview mesh",
        )
        first = str(page.preview_panel.last_preview_path())
        inputs = page.parameter_form.sweep_inputs_for_key("Coverage.Angle")
        self.assertIsNotNone(inputs)
        inputs["end"].setText("55")
        self._wait_until(
            lambda: (page.preview_panel.last_preview_path() is not None)
            and (str(page.preview_panel.last_preview_path()) != first)
            and (not page.preview_panel._busy),  # type: ignore[attr-defined]
            timeout_s=18.0,
            label="updated preview mesh",
        )
        second = str(page.preview_panel.last_preview_path())
        return first, second

    def _run_batch_via_ui(self, controller: GuiController) -> dict:
        main = controller.main_window
        page = main.batch_page

        autoclick = QTimer()

        def _auto_dialogs() -> None:
            for widget in list(self.app.topLevelWidgets()):
                if isinstance(widget, BatchRunDefaultsDialog):
                    self._click_button(widget, "Use defaults")
                elif isinstance(widget, QMessageBox):
                    buttons = list(widget.buttons())
                    if buttons:
                        buttons[0].click()

        autoclick.timeout.connect(_auto_dialogs)
        autoclick.start(50)
        try:
            page.run_btn.click()
            self._wait_until(
                lambda: str(main.status_message.text()).startswith(
                    ("Run finished for ", "Run failed for ", "Nothing to run for ")
                ),
                timeout_s=25.0,
                label="terminal run status",
            )
        finally:
            autoclick.stop()

        summary = json.loads(str(main.last_status_detail))
        self.assertEqual(str(summary.get("run_status")), "succeeded")
        self.assertEqual(str(main.run_page.mode_label.text()), "Mode: real")
        return summary

    def _validate_run_persistence_and_cleanup(self, summary: dict) -> None:
        run_id = str(summary["run_id"])
        versions = [str(item) for item in list(summary.get("versions", []) or [])]
        self.assertTrue(versions)
        project_root = Path(str(summary["project_root"]))
        project_db = Path(str(summary["project_db_path"]))
        global_db = Path(str(summary["library_db_path"]))
        self.assertTrue(project_db.exists())
        self.assertTrue(global_db.exists())

        for db_path in (project_db, global_db):
            with sqlite3.connect(str(db_path)) as conn:
                run_row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
                self.assertIsNotNone(run_row)
                self.assertEqual(str(run_row[0]), "succeeded")
                rv_count = conn.execute("SELECT COUNT(*) FROM run_versions WHERE run_id = ?", (run_id,)).fetchone()[0]
                self.assertEqual(int(rv_count), len(versions))
                success_count = conn.execute(
                    "SELECT COUNT(*) FROM run_versions WHERE run_id = ? AND status = 'success'",
                    (run_id,),
                ).fetchone()[0]
                self.assertEqual(int(success_count), len(versions))

        cleanup_rows = list(summary.get("cleanup_results", []) or [])
        cfg_rows = [row for row in cleanup_rows if str(row.get("artifact")) == "cfg"]
        export_rows = [row for row in cleanup_rows if str(row.get("artifact")) == "ath_export_subdir"]
        self.assertEqual(len(cfg_rows), len(versions))
        self.assertEqual(len(export_rows), len(versions))
        self.assertTrue(all(bool(row.get("deleted")) and str(row.get("reason")) == "deleted" for row in cfg_rows))
        self.assertTrue(
            all(
                str(row.get("reason")) in {"deleted", "target_missing", "ath_export_root_unset"}
                for row in export_rows
            )
        )

        for version_id in versions:
            payload = json.loads((project_root / "versions" / version_id / "version.json").read_text(encoding="utf-8-sig"))
            run_cfg_path = Path(str(payload.get("run_cfg_path", "")))
            if run_cfg_path:
                self.assertFalse(run_cfg_path.exists())
            ath_export_dir = str(payload.get("ath_export_dir", "")).strip()
            if ath_export_dir:
                self.assertFalse(Path(ath_export_dir).exists())

    def test_three_full_ui_runs_are_stable(self) -> None:
        tmp_dir = tempfile.mkdtemp(prefix="wut_ui_e2e_")
        root = Path(tmp_dir)
        try:
            tools = _build_fake_toolchain(root)
            template_cfg = root / "template.cfg"
            template_cfg.write_text("; qa template\nLength = 80\n", encoding="utf-8")

            settings_path = root / "settings.json"
            store = SettingsStore(settings_path)
            store.save(
                UserSettings(
                    library_root=str(root / "library"),
                    template_cfg=str(template_cfg),
                    ath_exe=tools["ath_exe"],
                    akabak_exe=tools["akabak_exe"],
                    vacs_exe=tools["vacs_exe"],
                )
            )
            service = OrchestratorService(settings_store=store)
            controller = GuiController(service)
            controller.show_project_manager()
            self._wait_until(lambda: controller.project_manager.isVisible(), timeout_s=4.0, label="project manager visible")

            for run_index in range(1, 4):
                if run_index > 1:
                    controller.main_window.home_button.click()
                    self._wait_until(
                        lambda: controller.project_manager.isVisible() and not controller.main_window.isVisible(),
                        timeout_s=4.0,
                        label=f"project manager visible for cycle {run_index}",
                    )
                self._click_button(controller.project_manager, "New Project")
                self._wait_until(
                    lambda: controller.main_window.isVisible() and controller.main_window.stack.currentWidget() is controller.main_window.project_page,
                    timeout_s=4.0,
                    label=f"project page cycle {run_index}",
                )

                self._set_project_constraints(controller, project_name=f"QA__E2E__{run_index}")
                self._configure_batch_with_sweeps(controller, batch_name=f"QA__Batch__{run_index}")
                first, second = self._wait_for_preview_refresh(controller)
                self.assertNotEqual(first, second)
                summary = self._run_batch_via_ui(controller)
                self._validate_run_persistence_and_cleanup(summary)

            controller.main_window._stop_preview_worker()  # type: ignore[attr-defined]
            controller.main_window.close()
            controller.project_manager.close()
            controller.main_window.deleteLater()
            controller.project_manager.deleteLater()
            self._pump(0.3)
            del controller
            del service
        finally:
            for _ in range(6):
                try:
                    shutil.rmtree(root)
                    break
                except PermissionError:
                    time.sleep(0.25)
            else:
                shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
