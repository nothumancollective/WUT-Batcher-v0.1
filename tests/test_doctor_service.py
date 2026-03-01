from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest

from app.doctor_service import _check_runner_dir, run_doctor_checks
from app.models import AppConfig


class DoctorServiceTests(unittest.TestCase):
    def test_tool_paths_override_marks_executable_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            exe_path = root / "ath_stub.cmd"
            exe_path.write_text("@echo off\r\necho ATH stub\r\n", encoding="utf-8")
            config = AppConfig(projects_root=str(root / "projects"))
            report = run_doctor_checks(
                config,
                config_path=None,
                fix=True,
                kill_zombies=False,
                report_path=root / "doctor.json",
                tool_paths={"ath_exe": str(exe_path)},
            )
            check = next(item for item in report.checks if item.key == "ath_exe")
            expected = "ok" if os.name == "nt" else "warn"
            self.assertEqual(check.status, expected)

    def test_missing_tool_path_is_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = AppConfig(projects_root=str(root / "projects"))
            report = run_doctor_checks(
                config,
                config_path=None,
                fix=True,
                kill_zombies=False,
                report_path=root / "doctor.json",
                tool_paths={"ath_exe": str(root / "missing_ath.exe")},
            )
            check = next(item for item in report.checks if item.key == "ath_exe")
            expected = "fail" if os.name == "nt" else "warn"
            self.assertEqual(check.status, expected)

    def test_gui_settings_can_skip_legacy_export_root_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_path = root / "settings.json"
            config_path.write_text('{"library_root": "' + str(root / "projects").replace("\\", "\\\\") + '"}', encoding="utf-8")
            report = run_doctor_checks(
                AppConfig(projects_root=str(root / "projects")),
                config_path=config_path,
                fix=True,
                kill_zombies=False,
                report_path=root / "doctor.json",
                include_batch_results_root_check=False,
                include_ath_export_root_check=False,
            )
            check_keys = {item.key for item in report.checks}
            self.assertIn("config_path", check_keys)
            self.assertNotIn("batch_results_root_exists", check_keys)
            self.assertNotIn("ath_export_root_exists", check_keys)
            config_check = next(item for item in report.checks if item.key == "config_path")
            self.assertEqual(config_check.status, "ok")

    def test_runner_dir_check_accepts_integrated_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "app").mkdir(parents=True, exist_ok=True)
            (root / "app" / "runtime_orchestrator.py").write_text("# runtime\n", encoding="utf-8")
            check = _check_runner_dir(root)
            self.assertEqual(check.status, "ok")
            self.assertIn("integrated runtime", check.detail.lower())


if __name__ == "__main__":
    unittest.main()
