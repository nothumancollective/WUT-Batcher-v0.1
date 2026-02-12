from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.batch_orchestrator import materialize_batch_plan
from app.models import Batch, ParamSelection, Project, ProjectConstraints
from app.tidy_dataset import TidyDatasetWriter


class ProjectStorageAndTidyTests(unittest.TestCase):
    def test_materialize_plan_and_write_tidy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"

            project = Project(
                project_id="P001",
                name="Test Project",
                root_path=str(projects_root / "P001"),
                constraints=ProjectConstraints(
                    project_id="P001",
                    fixed_params={"Length": 100},
                    limits={},
                    runner_mode="AthGuidePreview",
                ),
            )
            batch = Batch(
                batch_id="B001",
                project_id="P001",
                selected_params={"Throat.Diameter": ParamSelection(value=25.0)},
                sweep_mode="single",
                runner_mode="AthGuidePreview",
            )

            summary = materialize_batch_plan(project, batch, projects_root=projects_root)
            self.assertEqual(summary.version_count, 1)

            project_root = projects_root / "P001"
            self.assertTrue((project_root / "project.json").exists())
            self.assertTrue((project_root / "batches" / "B001" / "batch.json").exists())
            self.assertTrue((project_root / "versions" / "V001" / "version.json").exists())
            self.assertTrue((project_root / "versions" / "V001" / "cfg" / "input.cfg").exists())
            self.assertTrue((project_root / "dataset" / "project.sqlite").exists())
            self.assertTrue((projects_root / "global.sqlite").exists())
            self.assertTrue((project_root / "tables" / "project_versions.csv").exists())

            writer = TidyDatasetWriter(project_root)
            measurement_result = writer.write_measurements(
                [
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "version_id": "V001",
                        "graph_type": "SPL",
                        "x_name": "Frequency",
                        "x_unit": "Hz",
                        "x_value": 1000.0,
                        "y_name": "Level",
                        "y_unit": "dB",
                        "y_value": 95.2,
                        "source_file": "exports/Result_V001B.txt",
                    }
                ]
            )
            ath_result = writer.write_ath_dimensions(
                [
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "version_id": "V001",
                        "horn_length_mm": 320.5,
                        "horn_width_mm": 280.1,
                        "horn_height_mm": 140.0,
                        "raw_line": "Length=320.5 Width=280.1 Height=140.0",
                        "source_file": "logs/ath.stdout.log",
                    }
                ]
            )

            self.assertEqual(measurement_result["rows_written"], 1)
            self.assertEqual(ath_result["rows_written"], 1)
            self.assertTrue((project_root / "dataset" / "schema.json").exists())

            project_db = project_root / "dataset" / "project.sqlite"
            with closing(sqlite3.connect(str(project_db))) as conn:
                counts = {
                    "projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                    "batches": conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0],
                    "versions": conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0],
                    "version_params": conn.execute("SELECT COUNT(*) FROM version_params").fetchone()[0],
                    "ath_dimensions": conn.execute("SELECT COUNT(*) FROM ath_dimensions").fetchone()[0],
                    "graphs": conn.execute("SELECT COUNT(*) FROM graphs").fetchone()[0],
                    "graph_points": conn.execute("SELECT COUNT(*) FROM graph_points").fetchone()[0],
                }
            self.assertEqual(counts["projects"], 1)
            self.assertEqual(counts["batches"], 1)
            self.assertEqual(counts["versions"], 1)
            self.assertGreaterEqual(counts["version_params"], 1)
            self.assertEqual(counts["ath_dimensions"], 1)
            self.assertEqual(counts["graphs"], 1)
            self.assertEqual(counts["graph_points"], 1)


if __name__ == "__main__":
    unittest.main()
