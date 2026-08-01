from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from app.doctor_service import _check_runner_dir, _check_zombies, run_doctor_checks, run_settings_doctor_checks
from app.models import AppConfig
from app.settings_store import UserSettings


class DoctorServiceTests(unittest.TestCase):
    def test_kill_zombies_refuses_name_wide_cleanup_without_ownership(self) -> None:
        with (
            patch("app.doctor_service.os.name", "nt"),
            patch("app.doctor_service._list_windows_processes", return_value={"akabak.exe"}),
            patch("app.doctor_service.subprocess.run") as run_mock,
        ):
            check = _check_zombies(kill_zombies=True)

        run_mock.assert_not_called()
        self.assertEqual(check.status, "warn")
        self.assertIn("Refused to terminate", check.detail)
        self.assertIn("exact PID ownership ledger", check.detail)

    def test_doctor_without_fix_does_not_touch_library_probe_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            projects_root = root / "projects"
            projects_root.mkdir()
            sentinel = projects_root / ".doctor_write_test"
            sentinel.write_text("owned by user", encoding="utf-8")

            report = run_doctor_checks(
                AppConfig(projects_root=str(projects_root)),
                config_path=None,
                fix=False,
                kill_zombies=False,
                report_path=root / "doctor.json",
                include_batch_results_root_check=False,
                include_ath_export_root_check=False,
            )

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "owned by user")
            write_check = next(item for item in report.checks if item.key == "Projects root_write")
            self.assertEqual(write_check.status, "ok")
            self.assertIn("active write test skipped", write_check.detail)

    def test_doctor_fix_uses_unique_probe_and_preserves_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            projects_root = root / "projects"
            projects_root.mkdir()
            sentinel = projects_root / ".doctor_write_test"
            sentinel.write_text("owned by user", encoding="utf-8")

            report = run_doctor_checks(
                AppConfig(projects_root=str(projects_root)),
                config_path=None,
                fix=True,
                kill_zombies=False,
                report_path=root / "doctor.json",
                include_batch_results_root_check=False,
                include_ath_export_root_check=False,
            )

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "owned by user")
            self.assertFalse(list(projects_root.glob(".doctor_write_test_*")))
            write_check = next(item for item in report.checks if item.key == "Projects root_write")
            self.assertEqual(write_check.status, "ok")
            self.assertEqual(write_check.detail, "Write test passed.")

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

    def test_settings_doctor_skips_obsolete_storage_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            settings_path = root / "config.json"
            settings_path.write_text("{}", encoding="utf-8")
            report = run_settings_doctor_checks(
                UserSettings(library_root=str(root / "library")),
                settings_path=settings_path,
                fix=True,
                report_path=root / "doctor.json",
            )
            keys = {check.key for check in report.checks}
            self.assertNotIn("batch_results_root_exists", keys)
            self.assertNotIn("ath_export_root_exists", keys)
            self.assertIn("Projects root_exists", keys)


if __name__ == "__main__":
    unittest.main()
