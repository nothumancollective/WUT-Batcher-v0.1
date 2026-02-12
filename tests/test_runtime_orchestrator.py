from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from app.models import Batch, ParamSelection, Project, ProjectConstraints
from app.runtime_orchestrator import run_batch_pipeline


class RuntimeOrchestratorTests(unittest.TestCase):
    def test_pipeline_runs_ath_stage_and_writes_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime Test",
                root_path=str(projects_root / "P001"),
                constraints=ProjectConstraints(
                    project_id="P001",
                    fixed_params={"Length": 120},
                    limits={},
                    runner_mode="AthGuidePreview",
                ),
            )
            batch = Batch(
                batch_id="B001",
                project_id="P001",
                selected_params={"Throat.Diameter": ParamSelection(value=30.0)},
                sweep_mode="single",
                runner_mode="AthGuidePreview",
            )

            summary = run_batch_pipeline(
                project=project,
                batch=batch,
                projects_root=projects_root,
                ath_executable=sys.executable,
                ath_base_args=["-c", "print('Length=111 Width=222 Height=333')"],
                continue_on_error=True,
            )

            self.assertEqual(summary.project_id, "P001")
            self.assertEqual(summary.batch_id, "B001")
            self.assertEqual(summary.ath_dimension_rows, 1)
            self.assertEqual(len(summary.stage_results), 1)
            self.assertEqual(summary.stage_results[0].stage, "ath")
            self.assertEqual(summary.stage_results[0].status, "ok")
            self.assertEqual(len(summary.cleanup_results), 1)
            self.assertEqual(summary.cleanup_results[0]["reason"], "skipped_without_vacs_stage")

            project_root = Path(summary.project_root)
            project_db = project_root / "dataset" / "project.sqlite"
            self.assertTrue(project_db.exists())
            with closing(sqlite3.connect(str(project_db))) as conn:
                dims_count = conn.execute("SELECT COUNT(*) FROM ath_dimensions").fetchone()[0]
            self.assertEqual(dims_count, 1)


if __name__ == "__main__":
    unittest.main()
