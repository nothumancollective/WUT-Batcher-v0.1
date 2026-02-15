from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.runner_test_db import RunnerTestDb
from app.runner_test_harness import (
    _parse_abec_mesh_requirements,
    run_runner_test_harness,
    run_runner_test_open_dialog_only,
)


def _write_case(path: Path) -> None:
    payload = {
        "case_id": "smoke_fast",
        "name": "Smoke Fast",
        "description": "Minimal dry-run harness case",
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
            "sim_export_settings": {
                "export_specs": [
                    {
                        "id": "spl_1",
                        "tool": "vacs",
                        "graph_kind": "spl",
                        "format": "txt",
                    }
                ]
            },
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class RunnerTestHarnessTests(unittest.TestCase):
    def test_harness_skeleton_writes_cfg_and_db_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cases_root = root / "cases"
            workspace_root = root / "workspace"
            _write_case(cases_root / "smoke_fast.json")

            summary = run_runner_test_harness(
                case_id="smoke_fast",
                repeats=1,
                keep_exports=True,
                test_profile="fast",
                workspace_root=workspace_root,
                cases_root=cases_root,
                dry_run=True,
            )
            self.assertTrue(summary["ok"])
            self.assertTrue(summary["dry_run"])
            self.assertEqual(len(summary["runs"]), 1)
            run = summary["runs"][0]
            self.assertEqual(run["status"], "dry_run_completed")
            cfg_path = Path(str(run["cfg_path"]))
            self.assertFalse(cfg_path.exists())

            db = RunnerTestDb(Path(summary["db_path"]))
            self.assertEqual(db.count_rows("test_runs"), 1)
            self.assertEqual(db.count_rows("test_cases"), 1)
            self.assertEqual(db.count_rows("test_run_steps"), 5)
            self.assertEqual(db.count_rows("artifacts"), 1)
            self.assertEqual(db.count_rows("validations"), 1)
            self.assertEqual(db.count_rows("versions"), 1)
            self.assertEqual(db.count_rows("run_versions"), 1)

    def test_parse_abec_mesh_requirements_detects_missing_mesh_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            abec.write_text(
                "[Project]\n"
                "Scriptname_Solving=solving.txt\n"
                "[MeshFiles]\n"
                "C0=ath.msh,M1\n"
                "C1=sub\\mesh2.msh,M2\n",
                encoding="utf-8",
            )
            (root / "ath.msh").write_text("mesh", encoding="utf-8")
            parsed = _parse_abec_mesh_requirements(abec)
            self.assertTrue(parsed["section_present"])
            self.assertEqual(len(parsed["required_mesh_files"]), 2)
            self.assertEqual(len(parsed["missing_mesh_files"]), 1)

    def test_open_dialog_only_dry_run_writes_db_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace_root = root / "workspace"
            abec_path = root / "sample.abec"
            abec_path.write_text("ABEC_SAMPLE\n", encoding="utf-8")

            summary = run_runner_test_open_dialog_only(
                akabak_executable=root / "akabak.exe",
                abec_path=abec_path,
                repeats=1,
                workspace_root=workspace_root,
                dry_run=True,
            )
            self.assertTrue(summary["ok"])
            self.assertTrue(summary["dry_run"])
            self.assertEqual(summary["phase"], "phase_open_dialog_only")
            self.assertEqual(len(summary["runs"]), 1)
            self.assertEqual(summary["runs"][0]["status"], "dry_run_completed")

            db = RunnerTestDb(Path(summary["db_path"]))
            self.assertEqual(db.count_rows("test_runs"), 1)
            self.assertEqual(db.count_rows("test_run_steps"), 3)
            self.assertEqual(db.count_rows("artifacts"), 1)
            self.assertEqual(db.count_rows("validations"), 1)
            self.assertEqual(db.count_rows("versions"), 1)
            self.assertEqual(db.count_rows("run_versions"), 1)


if __name__ == "__main__":
    unittest.main()
