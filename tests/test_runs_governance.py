from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.models import Batch, Project, ProjectConstraints, VersionSpec
from app.tidy_dataset import TidyDatasetWriter


class RunsGovernanceTests(unittest.TestCase):
    def _setup_writer(self, root: Path) -> tuple[TidyDatasetWriter, Project, Batch, VersionSpec]:
        project_root = root / "projects" / "P001"
        project_root.mkdir(parents=True, exist_ok=True)
        writer = TidyDatasetWriter(project_root, library_root=project_root.parent)
        project = Project(
            project_id="P001",
            name="Runs Governance Test",
            root_path=str(project_root),
            constraints=ProjectConstraints(project_id="P001", fixed_params={"Length": 120}, limits={}),
        )
        batch = Batch(batch_id="B001", project_id="P001")
        version = VersionSpec(
            project_id="P001",
            batch_id="B001",
            version_id="V001",
            sweep_mode="single",
            sequence_index=1,
            parameters={"Length": 120},
            unset_parameters=["Coverage.Angle"],
        )
        writer.register_project(project)
        writer.register_batch(project, batch)
        writer.write_versions(project, batch, [version])
        return writer, project, batch, version

    def _add_run(
        self,
        *,
        writer: TidyDatasetWriter,
        project: Project,
        batch: Batch,
        version: VersionSpec,
        run_id: str,
        started_at: str,
        status: str,
        pinned: bool,
        graph_kind: str = "SPL",
        source_file: str = "",
    ) -> None:
        writer.create_run(
            run_id=run_id,
            project_id=project.project_id,
            batch_id=batch.batch_id,
            started_at=started_at,
            status=status,
            app_version="test",
            settings_hash="hash",
        )
        writer.write_run_versions(
            [
                {
                    "run_id": run_id,
                    "project_id": project.project_id,
                    "batch_id": batch.batch_id,
                    "version_id": version.version_id,
                    "status": "success" if status == "succeeded" else "failed",
                }
            ]
        )
        writer.set_run_pin(run_id, pinned=pinned, tag="baseline" if pinned else None)
        writer.write_measurements(
            [
                {
                    "project_id": project.project_id,
                    "batch_id": batch.batch_id,
                    "version_id": version.version_id,
                    "run_id": run_id,
                    "graph_kind": graph_kind,
                    "graph_type": graph_kind,
                    "variant": "default",
                    "x_name": "Frequency",
                    "x_unit": "Hz",
                    "x_value": 1000.0,
                    "y_name": "Level",
                    "y_unit": "dB",
                    "y_value": 95.2,
                    "source_file": source_file,
                }
            ]
        )

    def test_latest_successful_run_per_version_excludes_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            writer, project, batch, version = self._setup_writer(root)
            self._add_run(
                writer=writer,
                project=project,
                batch=batch,
                version=version,
                run_id="R001",
                started_at="2026-02-10T10:00:00+00:00",
                status="succeeded",
                pinned=False,
            )
            self._add_run(
                writer=writer,
                project=project,
                batch=batch,
                version=version,
                run_id="R002",
                started_at="2026-02-10T11:00:00+00:00",
                status="failed",
                pinned=False,
            )
            rows = writer.latest_successful_run_per_version(batch.batch_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["run_id"], "R001")

    def test_cleanup_deletes_only_unpinned_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            writer, project, batch, version = self._setup_writer(root)
            project_root = Path(project.root_path)
            for index, run_id in enumerate(("R001", "R002", "R003", "R004", "R005"), start=1):
                export_file = project_root / "versions" / version.version_id / "exports" / run_id / "Result.txt"
                export_file.parent.mkdir(parents=True, exist_ok=True)
                export_file.write_text("x;y\n1;2\n", encoding="utf-8")
                self._add_run(
                    writer=writer,
                    project=project,
                    batch=batch,
                    version=version,
                    run_id=run_id,
                    started_at=f"2026-02-10T1{index}:00:00+00:00",
                    status="succeeded",
                    pinned=run_id in {"R001", "R002"},
                    source_file=str(export_file),
                )

            result = writer.cleanup_unpinned_runs(delete_exports=False, dry_run=False)
            self.assertTrue(bool(result["deleted"]))
            self.assertEqual(set(result["run_ids"]), {"R003", "R004", "R005"})

            db_path = project_root / "dataset" / "project.sqlite"
            with closing(sqlite3.connect(str(db_path))) as conn:
                run_ids = [str(row[0]) for row in conn.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()]
                graph_count = conn.execute("SELECT COUNT(*) FROM graphs").fetchone()[0]
            self.assertEqual(run_ids, ["R001", "R002"])
            self.assertEqual(int(graph_count), 2)

    def test_cleanup_dry_run_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            writer, project, batch, version = self._setup_writer(root)
            self._add_run(
                writer=writer,
                project=project,
                batch=batch,
                version=version,
                run_id="R001",
                started_at="2026-02-10T10:00:00+00:00",
                status="succeeded",
                pinned=False,
            )
            result = writer.cleanup_unpinned_runs(delete_exports=True, dry_run=True)
            self.assertFalse(bool(result["deleted"]))
            db_path = Path(project.root_path) / "dataset" / "project.sqlite"
            with closing(sqlite3.connect(str(db_path))) as conn:
                run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            self.assertEqual(int(run_count), 1)

    def test_cleanup_export_deletion_stays_inside_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            writer, project, batch, version = self._setup_writer(root)
            project_root = Path(project.root_path)
            inside_file = project_root / "versions" / version.version_id / "exports" / "R001" / "inside.txt"
            inside_file.parent.mkdir(parents=True, exist_ok=True)
            inside_file.write_text("data", encoding="utf-8")
            outside_file = root / "outside.txt"
            outside_file.write_text("data", encoding="utf-8")

            self._add_run(
                writer=writer,
                project=project,
                batch=batch,
                version=version,
                run_id="R001",
                started_at="2026-02-10T10:00:00+00:00",
                status="succeeded",
                pinned=False,
                graph_kind="SPL",
                source_file=str(inside_file),
            )
            self._add_run(
                writer=writer,
                project=project,
                batch=batch,
                version=version,
                run_id="R001",
                started_at="2026-02-10T10:00:00+00:00",
                status="succeeded",
                pinned=False,
                graph_kind="IMP",
                source_file=str(outside_file),
            )

            result = writer.cleanup_unpinned_runs(delete_exports=True, dry_run=False)
            self.assertFalse(inside_file.exists())
            self.assertTrue(outside_file.exists())
            skipped = list(result.get("skipped_files", []))
            self.assertTrue(any(item.get("reason") == "outside_project_root" for item in skipped))


if __name__ == "__main__":
    unittest.main()

