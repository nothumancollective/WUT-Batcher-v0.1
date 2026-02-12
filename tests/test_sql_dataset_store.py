from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.models import Batch, Project, ProjectConstraints, VersionSpec
from app.tidy_dataset import TidyDatasetWriter


class SqlDatasetStoreTests(unittest.TestCase):
    def test_unset_params_are_persisted_and_reconstructed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "projects" / "P001"
            project_root.mkdir(parents=True, exist_ok=True)
            writer = TidyDatasetWriter(project_root, library_root=project_root.parent)

            project = Project(
                project_id="P001",
                name="Dataset Test",
                root_path=str(project_root),
                constraints=ProjectConstraints(project_id="P001", fixed_params={"Length": 100}, limits={}),
            )
            batch = Batch(batch_id="B001", project_id="P001")
            version = VersionSpec(
                project_id="P001",
                batch_id="B001",
                version_id="V001",
                sweep_mode="single",
                sequence_index=1,
                parameters={"Length": 100, "Throat.Diameter": 25.0},
                unset_parameters=["Coverage.Angle"],
            )

            writer.register_project(project)
            writer.register_batch(project, batch)
            writer.write_versions(project, batch, [version])

            params, unset = writer.reconstruct_cfg_parameters("V001")
            self.assertIn("Length", params)
            self.assertIn("Throat.Diameter", params)
            self.assertIn("Coverage.Angle", unset)

            with closing(sqlite3.connect(str(project_root / "dataset" / "project.sqlite"))) as conn:
                row = conn.execute(
                    "SELECT is_set FROM version_params WHERE version_id = ? AND param_name = ?",
                    ("V001", "Coverage.Angle"),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 0)

    def test_global_write_failure_is_queued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "projects"
            project_root = library_root / "P001"
            project_root.mkdir(parents=True, exist_ok=True)
            writer = TidyDatasetWriter(project_root, library_root=library_root)

            # Force global DB open failure by pointing to a directory.
            writer.global_db_path = library_root

            project = Project(
                project_id="P001",
                name="Queue Test",
                root_path=str(project_root),
                constraints=ProjectConstraints(project_id="P001"),
            )
            result = writer.register_project(project)
            self.assertFalse(result["global_synced"])
            self.assertIsNotNone(result["queued_retry"])

            with closing(sqlite3.connect(str(project_root / "dataset" / "project.sqlite"))) as conn:
                pending = conn.execute("SELECT COUNT(*) FROM replication_queue WHERE status = 'pending'").fetchone()[0]
            self.assertEqual(pending, 1)


if __name__ == "__main__":
    unittest.main()
