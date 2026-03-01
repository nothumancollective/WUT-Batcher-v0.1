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

            with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
                row = conn.execute(
                    "SELECT is_set FROM version_params WHERE version_id = ? AND param_name = ?",
                    ("V001", "Coverage.Angle"),
                ).fetchone()
                hash_row = conn.execute(
                    "SELECT version_config_hash FROM versions WHERE version_id = ?",
                    ("V001",),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 0)
            self.assertIsNotNone(hash_row)
            self.assertTrue(bool(hash_row[0]))

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

            with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
                pending = conn.execute("SELECT COUNT(*) FROM replication_queue WHERE status = 'pending'").fetchone()[0]
            self.assertEqual(pending, 1)

    def test_plan_bundle_is_written_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "projects" / "P001"
            project_root.mkdir(parents=True, exist_ok=True)
            writer = TidyDatasetWriter(project_root, library_root=project_root.parent)

            project = Project(
                project_id="P001",
                name="Bundle Test",
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
                parameters={"Length": 100},
                unset_parameters=["Coverage.Angle"],
            )

            result = writer.write_plan_bundle(project=project, batch=batch, versions=[version])
            self.assertEqual(result["version_count"], 1)
            with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
                project_count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
                batch_count = conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
                version_count = conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0]
            self.assertEqual(project_count, 1)
            self.assertEqual(batch_count, 1)
            self.assertEqual(version_count, 1)

    def test_write_compat_verification_results_persists_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "projects" / "P001"
            project_root.mkdir(parents=True, exist_ok=True)
            writer = TidyDatasetWriter(project_root, library_root=project_root.parent)
            result = writer.write_compat_verification_results(
                [
                    {
                        "project_id": "P001",
                        "fact_id": "output_flags_stl_abecproject",
                        "case_id": "output_flags",
                        "status": "pass",
                        "expected": {"require_stl": True},
                        "observed": {"stl_count": 1},
                        "details": {"runner": "stub"},
                    }
                ]
            )
            self.assertEqual(result["rows_written"], 1)
            with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
                count = conn.execute("SELECT COUNT(*) FROM compat_verification_results").fetchone()[0]
            self.assertEqual(int(count), 1)

    def test_migrates_legacy_graph_points_schema_to_series_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "projects"
            project_root = library_root / "P001"
            dataset_dir = project_root / "dataset"
            dataset_dir.mkdir(parents=True, exist_ok=True)
            legacy_db = dataset_dir / "project.sqlite"
            with closing(sqlite3.connect(str(legacy_db))) as conn:
                conn.executescript(
                    """
                    CREATE TABLE graphs (
                        graph_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        batch_id TEXT NOT NULL,
                        version_id TEXT NOT NULL,
                        graph_type TEXT,
                        x_name TEXT,
                        y_name TEXT,
                        x_unit TEXT,
                        y_unit TEXT,
                        source_file TEXT,
                        export_meta TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE graph_points (
                        graph_id TEXT NOT NULL,
                        point_index INTEGER NOT NULL,
                        x_value REAL,
                        y_value REAL,
                        PRIMARY KEY (graph_id, point_index)
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT INTO graphs (
                        graph_id, project_id, batch_id, version_id, graph_type,
                        x_name, y_name, x_unit, y_unit, source_file, export_meta, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "GLEGACY",
                        "P001",
                        "B001",
                        "V001",
                        "SPL",
                        "Frequency",
                        "SPL",
                        "Hz",
                        "dB",
                        "legacy.txt",
                        "{}",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    "INSERT INTO graph_points (graph_id, point_index, x_value, y_value) VALUES (?, ?, ?, ?)",
                    ("GLEGACY", 0, 100.0, 90.0),
                )
                conn.execute(
                    "INSERT INTO graph_points (graph_id, point_index, x_value, y_value) VALUES (?, ?, ?, ?)",
                    ("GLEGACY", 1, 200.0, 91.0),
                )
                conn.commit()

            TidyDatasetWriter(project_root, library_root=library_root)
            with closing(sqlite3.connect(str(legacy_db))) as conn:
                columns = [row[1] for row in conn.execute("PRAGMA table_info(graph_points)").fetchall()]
                series_count = conn.execute("SELECT COUNT(*) FROM graph_series").fetchone()[0]
                points_count = conn.execute("SELECT COUNT(*) FROM graph_points").fetchone()[0]
            self.assertIn("series_id", columns)
            self.assertIn("y_imag", columns)
            self.assertEqual(int(series_count), 1)
            self.assertEqual(int(points_count), 2)

    def test_migrates_legacy_batches_table_with_lineage_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "projects"
            project_root = library_root / "P001"
            db_dir = project_root / "db"
            db_dir.mkdir(parents=True, exist_ok=True)
            legacy_db = db_dir / "project.sqlite"
            with closing(sqlite3.connect(str(legacy_db))) as conn:
                conn.executescript(
                    """
                    CREATE TABLE projects (
                        project_id TEXT PRIMARY KEY,
                        project_name TEXT NOT NULL,
                        constraints_snapshot TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE batches (
                        project_id TEXT NOT NULL,
                        batch_id TEXT NOT NULL,
                        batch_name TEXT NOT NULL,
                        sweep_definitions TEXT,
                        sweep_mode TEXT,
                        sim_export_params TEXT,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (project_id, batch_id)
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT INTO batches (
                        project_id, batch_id, batch_name, sweep_definitions, sweep_mode, sim_export_params, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("P001", "B001", "Legacy Batch", "{}", "single", "{}", "2026-02-20T00:00:00+00:00"),
                )
                conn.commit()

            TidyDatasetWriter(project_root, library_root=library_root)
            with closing(sqlite3.connect(str(legacy_db))) as conn:
                columns = [str(row[1]) for row in conn.execute("PRAGMA table_info(batches)").fetchall()]
                row = conn.execute(
                    """
                    SELECT parent_batch_id, created_via, created_from_version_id
                    FROM batches
                    WHERE project_id = ? AND batch_id = ?
                    """,
                    ("P001", "B001"),
                ).fetchone()
            self.assertIn("parent_batch_id", columns)
            self.assertIn("created_via", columns)
            self.assertIn("created_from_version_id", columns)
            self.assertIsNotNone(row)
            assert row is not None
            self.assertIsNone(row[0])
            self.assertEqual(str(row[1]), "manual")
            self.assertIsNone(row[2])

    def test_list_batches_with_lineage_returns_provenance_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "projects" / "P001"
            project_root.mkdir(parents=True, exist_ok=True)
            writer = TidyDatasetWriter(project_root, library_root=project_root.parent)
            project = Project(
                project_id="P001",
                name="Lineage Test",
                root_path=str(project_root),
                constraints=ProjectConstraints(project_id="P001"),
            )
            parent_batch = Batch(
                batch_id="B001",
                project_id="P001",
                extra={"batch_name": "Parent"},
            )
            child_batch = Batch(
                batch_id="B002",
                project_id="P001",
                extra={
                    "batch_name": "Child",
                    "created_via": "iterate",
                    "parent_batch_id": "B001",
                    "created_from_version_id": "V010",
                },
            )
            writer.register_project(project)
            writer.register_batch(project, parent_batch)
            writer.register_batch(project, child_batch)

            rows = writer.list_batches_with_lineage(project_id="P001")
            self.assertEqual(len(rows), 2)
            rows_by_id = {str(row["batch_id"]): row for row in rows}
            self.assertIn("B001", rows_by_id)
            self.assertIn("B002", rows_by_id)
            self.assertEqual(str(rows_by_id["B001"]["created_via"]), "manual")
            self.assertIsNone(rows_by_id["B001"]["parent_batch_id"])
            self.assertEqual(str(rows_by_id["B002"]["created_via"]), "iterate")
            self.assertEqual(str(rows_by_id["B002"]["parent_batch_id"]), "B001")
            self.assertEqual(str(rows_by_id["B002"]["created_from_version_id"]), "V010")

    def test_federation_profile_is_bootstrapped_and_updatable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "projects" / "P001"
            project_root.mkdir(parents=True, exist_ok=True)
            writer = TidyDatasetWriter(project_root, library_root=project_root.parent)

            profile = writer.load_federation_profile()
            self.assertTrue(profile["installation_id"])
            self.assertTrue(profile["anonymous_user_id"])
            self.assertTrue(profile["dataset_namespace"])
            self.assertFalse(profile["allow_upload"])

            update = writer.update_federation_profile(
                allow_upload=True,
                consent_scope="project_and_global",
                consent_version="v1",
                consent_updated_at="2026-02-16T00:00:00+00:00",
            )
            self.assertTrue(update["profile"]["allow_upload"])
            self.assertEqual(update["profile"]["consent_scope"], "project_and_global")
            self.assertEqual(update["profile"]["consent_version"], "v1")

    def test_delete_runs_writes_federation_tombstones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "projects" / "P001"
            project_root.mkdir(parents=True, exist_ok=True)
            writer = TidyDatasetWriter(project_root, library_root=project_root.parent)

            writer.create_run(run_id="R001", project_id="P001", batch_id="B001", status="running")
            writer.cleanup_unpinned_runs(delete_exports=False, dry_run=False)

            with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
                row = conn.execute(
                    """
                    SELECT entity_type, entity_id, reason
                    FROM federation_tombstones
                    ORDER BY deleted_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "run")
            self.assertEqual(str(row[1]), "R001")
            self.assertEqual(str(row[2]), "cleanup_unpinned_runs")

    def test_write_polar_measurement_is_idempotent_for_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "projects" / "P001"
            project_root.mkdir(parents=True, exist_ok=True)
            writer = TidyDatasetWriter(project_root, library_root=project_root.parent)
            measurement = {
                "polar_id": "PTEST01",
                "project_id": "P001",
                "batch_id": "B001",
                "version_id": "V001",
                "run_id": "R001",
                "orientation": "H",
                "orientation_raw": 0.0,
                "norm_angle_deg": None,
                "data_level_type": "SoundPressure",
                "data_base_unit": "Pa",
                "data_absc_unit": "Hz",
                "freq_min_hz": 100.0,
                "freq_max_hz": 200.0,
                "freq_count": 2,
                "angle_min_deg": 0.0,
                "angle_max_deg": 30.0,
                "angle_step_deg": 30.0,
                "angle_count": 2,
                "angles_deg_json": "[0.0, 30.0]",
                "source_file": "sample.txt",
                "file_hash": "abc123",
                "export_meta_json": "{}",
            }
            points = [
                {"freq_index": 0, "angle_index": 0, "freq_hz": 100.0, "angle_deg": 0.0, "re": 1.0, "im": 0.1},
                {"freq_index": 0, "angle_index": 1, "freq_hz": 100.0, "angle_deg": 30.0, "re": 2.0, "im": 0.2},
                {"freq_index": 1, "angle_index": 0, "freq_hz": 200.0, "angle_deg": 0.0, "re": 1.1, "im": 0.11},
                {"freq_index": 1, "angle_index": 1, "freq_hz": 200.0, "angle_deg": 30.0, "re": 2.1, "im": 0.21},
            ]
            writer.write_polar_measurement(measurement=measurement, points=points)
            writer.write_polar_measurement(measurement=measurement, points=points)

            with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
                meas_count = conn.execute("SELECT COUNT(*) FROM polar_measurements").fetchone()[0]
                point_count = conn.execute("SELECT COUNT(*) FROM polar_points").fetchone()[0]
            self.assertEqual(int(meas_count), 1)
            self.assertEqual(int(point_count), 4)


if __name__ == "__main__":
    unittest.main()
