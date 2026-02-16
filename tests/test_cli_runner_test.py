from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def _write_case(path: Path) -> None:
    payload = {
        "case_id": "smoke_fast",
        "name": "Smoke Fast",
        "project_id": "PTEST",
        "batch_id": "BTEST",
        "constraints": {
            "runner_mode": "AkabakImportFixedSource",
            "fixed_params": {"Length": 120},
            "limits": {},
        },
        "batch_settings": {
            "selected_params": {"Throat.Diameter": 30.0},
            "sweeps": {},
            "sweep_mode": "single",
            "sim_export_settings": {"export_specs": []},
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class CliRunnerTestTests(unittest.TestCase):
    @staticmethod
    def _isolated_env(tmp_dir: str) -> dict[str, str]:
        env = dict(os.environ)
        env["USERPROFILE"] = tmp_dir
        env["HOME"] = tmp_dir
        return env

    def test_runner_test_run_command_executes_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cases_root = root / "cases"
            workspace_root = root / "workspace"
            _write_case(cases_root / "smoke_fast.json")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runner-test",
                    "run",
                    "--case",
                    "smoke_fast",
                    "--cases-root",
                    str(cases_root),
                    "--workspace-root",
                    str(workspace_root),
                    "--strict-nonzero-radimp",
                    "--dry-run",
                ],
                env=self._isolated_env(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["phase"], "phase2_commit5_e2e")
            self.assertEqual(len(payload["runs"]), 1)
            self.assertTrue(payload["strict_nonzero_radimp"])

    def test_runner_test_open_dialog_only_command_executes_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace_root = root / "workspace"
            abec_path = root / "sample.abec"
            abec_path.write_text("ABEC_SAMPLE\n", encoding="utf-8")
            akabak_path = root / "akabak.exe"
            akabak_path.write_text("stub\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runner-test",
                    "open-dialog-only",
                    "--abec-path",
                    str(abec_path),
                    "--akabak-exe",
                    str(akabak_path),
                    "--workspace-root",
                    str(workspace_root),
                    "--dry-run",
                ],
                env=self._isolated_env(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["phase"], "phase_open_dialog_only")
            self.assertEqual(payload["mode"], "open_dialog_only")
            self.assertEqual(len(payload["runs"]), 1)

    def test_runner_test_import_start_apply_only_command_executes_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace_root = root / "workspace"
            abec_path = root / "sample.abec"
            abec_path.write_text("ABEC_SAMPLE\n", encoding="utf-8")
            akabak_path = root / "akabak.exe"
            akabak_path.write_text("stub\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runner-test",
                    "import-start-apply-only",
                    "--abec-path",
                    str(abec_path),
                    "--akabak-exe",
                    str(akabak_path),
                    "--workspace-root",
                    str(workspace_root),
                    "--dry-run",
                ],
                env=self._isolated_env(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["phase"], "phase_import_start_apply_only")
            self.assertEqual(payload["mode"], "import_start_apply_only")
            self.assertEqual(len(payload["runs"]), 1)

    def test_runner_test_le_repair_import_only_command_executes_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace_root = root / "workspace"
            abec_path = root / "sample.abec"
            abec_path.write_text("ABEC_SAMPLE\n", encoding="utf-8")
            akabak_path = root / "akabak.exe"
            akabak_path.write_text("stub\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runner-test",
                    "le-repair-import-only",
                    "--abec-path",
                    str(abec_path),
                    "--akabak-exe",
                    str(akabak_path),
                    "--workspace-root",
                    str(workspace_root),
                    "--dry-run",
                ],
                env=self._isolated_env(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["phase"], "phase_le_repair_import_only")
            self.assertEqual(payload["mode"], "le_repair_import_only")
            self.assertEqual(len(payload["runs"]), 1)

    def test_runner_test_radimp_driving_matrix_command_executes_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cases_root = root / "cases"
            workspace_root = root / "workspace"
            _write_case(cases_root / "smoke_fast.json")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runner-test",
                    "radimp-driving-matrix",
                    "--case",
                    "smoke_fast",
                    "--profiles",
                    "default,accel_2p83",
                    "--cases-root",
                    str(cases_root),
                    "--workspace-root",
                    str(workspace_root),
                    "--strict-nonzero-radimp",
                    "--dry-run",
                ],
                env=self._isolated_env(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["phase"], "phase_radimp_driving_matrix")
            self.assertEqual(len(payload["results"]), 2)
            self.assertTrue(payload["strict_nonzero_radimp"])

    def test_runner_test_radimp_3scope_matrix_command_executes_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cases_root = root / "cases"
            workspace_root = root / "workspace"
            _write_case(cases_root / "smoke_fast.json")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runner-test",
                    "radimp-3scope-matrix",
                    "--case",
                    "smoke_fast",
                    "--cfg-profiles",
                    "default,le_voltage_2p83",
                    "--radimp-profiles",
                    "default",
                    "--driving-profiles",
                    "default,accel_2p83",
                    "--matrix-seed",
                    "20260216",
                    "--strict-nonzero-radimp",
                    "--cases-root",
                    str(cases_root),
                    "--workspace-root",
                    str(workspace_root),
                    "--dry-run",
                ],
                env=self._isolated_env(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["phase"], "phase_radimp_3scope_matrix")
            self.assertEqual(len(payload["results"]), 4)
            self.assertEqual(payload["random_seed"], 20260216)
            self.assertTrue(payload["strict_nonzero_radimp"])

    def test_runner_test_le_proof_matrix_command_executes_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cases_root = root / "cases"
            workspace_root = root / "workspace"
            _write_case(cases_root / "smoke_fast.json")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runner-test",
                    "le-proof-matrix",
                    "--case",
                    "smoke_fast",
                    "--profiles",
                    "control,mut_electrical",
                    "--repeats-per-profile",
                    "1",
                    "--matrix-seed",
                    "20260216",
                    "--cases-root",
                    str(cases_root),
                    "--workspace-root",
                    str(workspace_root),
                    "--dry-run",
                ],
                env=self._isolated_env(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["phase"], "phase_le_proof_matrix")
            self.assertEqual(len(payload["results"]), 2)
            self.assertEqual(payload["random_seed"], 20260216)
            self.assertFalse(payload["strict_le_proof"])


if __name__ == "__main__":
    unittest.main()
