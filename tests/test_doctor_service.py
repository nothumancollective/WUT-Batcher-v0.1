from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest

from app.doctor_service import run_doctor_checks
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


if __name__ == "__main__":
    unittest.main()
