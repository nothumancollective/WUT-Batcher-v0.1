from contextlib import closing
import sqlite3
import tempfile
from pathlib import Path
import unittest

from app.models import Batch, Project, ProjectConstraints, SimExportSettings, VersionSpec
from app.runtime_orchestrator import _ingest_vacs_exports
from app.tidy_dataset import TidyDatasetWriter


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vacs"


class PolarImporterTests(unittest.TestCase):
    def _prepare_project(self) -> tuple[Path, TidyDatasetWriter, Project, Batch]:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        library_root = Path(tmp_dir.name) / "projects"
        project_root = library_root / "P001"
        project_root.mkdir(parents=True, exist_ok=True)

        writer = TidyDatasetWriter(project_root, library_root=library_root)
        project = Project(
            project_id="P001",
            name="Polar Import Test",
            root_path=str(project_root),
            constraints=ProjectConstraints(project_id="P001"),
        )
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            sim_export_settings=SimExportSettings(
                export_specs=[
                    {
                        "id": "polar_spec_1",
                        "tool": "vacs",
                        "graph_kind": "polar",
                        "variant": "main",
                        "format": "txt",
                        "options": {
                            "norm_angle": 35,
                        },
                        "output_name_template": "{version_id}_{graph_kind}_{export_id}.{format}",
                    }
                ]
            ),
        )
        version = VersionSpec(
            project_id="P001",
            batch_id="B001",
            version_id="V001",
            sweep_mode="single",
            sequence_index=1,
            parameters={"Length": 120},
        )
        writer.write_plan_bundle(project=project, batch=batch, versions=[version])
        writer.create_run(run_id="RUN001", project_id="P001", batch_id="B001", status="running")
        return project_root, writer, project, batch

    def test_import_writes_polar_tables_and_keeps_legacy_graphs(self) -> None:
        project_root, writer, project, batch = self._prepare_project()
        exports_dir = project_root / "versions" / "V001" / "exports" / "RUN001"
        exports_dir.mkdir(parents=True, exist_ok=True)

        source_file = FIXTURES / "result_v001polar_matrix_small.txt"
        target_file = exports_dir / "20260221_000000_01_Mic_Polar_-_BE_Spectrum_2.txt"
        target_file.write_text(source_file.read_text(encoding="utf-8-sig"), encoding="utf-8")

        vacs_summary = {
            "exports": [
                {
                    "spec": {
                        "id": "polar_spec_1",
                        "tool": "vacs",
                        "graph_kind": "polar",
                        "variant": "main",
                        "format": "txt",
                        "options": {"norm_angle": 35},
                    },
                    "entry": {"graph_kind": "polar", "graph_variant": "main", "format": "txt"},
                    "plugin_id": "test",
                    "output_path": str(target_file),
                    "details": {},
                }
            ]
        }

        ingest = _ingest_vacs_exports(
            writer=writer,
            project=project,
            batch=batch,
            run_id="RUN001",
            version_id="V001",
            exports_dir=exports_dir,
            vacs_export_summary=vacs_summary,
        )
        self.assertEqual(ingest.get("parse_errors"), [])
        self.assertEqual(int(ingest.get("polar_measurements_written", 0)), 1)
        self.assertEqual(int(ingest.get("polar_points_written", 0)), 6)

        project_db = project_root / "dataset" / "project.sqlite"
        global_db = project_root.parent / "global.sqlite"
        with closing(sqlite3.connect(str(project_db))) as conn:
            meas_count = conn.execute("SELECT COUNT(*) FROM polar_measurements").fetchone()[0]
            point_count = conn.execute("SELECT COUNT(*) FROM polar_points").fetchone()[0]
            row = conn.execute(
                """
                SELECT orientation, norm_angle_deg, freq_count, angle_count, polar_id
                FROM polar_measurements
                LIMIT 1
                """
            ).fetchone()
            point = conn.execute(
                """
                SELECT re, im
                FROM polar_points
                WHERE polar_id = ? AND freq_index = 0 AND angle_index = 1
                """,
                (str(row[4]),),
            ).fetchone()
            graph_count = conn.execute("SELECT COUNT(*) FROM graphs").fetchone()[0]
            legacy_points = conn.execute("SELECT COUNT(*) FROM graph_points").fetchone()[0]
        self.assertEqual(int(meas_count), 1)
        self.assertEqual(int(point_count), 6)
        self.assertEqual(str(row[0]), "D")
        self.assertEqual(float(row[1]), 35.0)
        self.assertEqual(int(row[2]), 2)
        self.assertEqual(int(row[3]), 3)
        self.assertEqual(float(point[0]), 2.0)
        self.assertEqual(float(point[1]), 0.2)
        self.assertEqual(int(graph_count), 1)
        self.assertEqual(int(legacy_points), 2)

        with closing(sqlite3.connect(str(global_db))) as conn:
            global_meas = conn.execute("SELECT COUNT(*) FROM polar_measurements").fetchone()[0]
            global_points = conn.execute("SELECT COUNT(*) FROM polar_points").fetchone()[0]
        self.assertEqual(int(global_meas), 1)
        self.assertEqual(int(global_points), 6)

    def test_import_deduplicates_same_file_identity(self) -> None:
        project_root, writer, project, batch = self._prepare_project()
        exports_dir = project_root / "versions" / "V001" / "exports" / "RUN001"
        exports_dir.mkdir(parents=True, exist_ok=True)
        source_file = FIXTURES / "result_v001polar_matrix_small.txt"
        target_file = exports_dir / "20260221_000000_01_Mic_Polar_-_BE_Spectrum_2.txt"
        target_file.write_text(source_file.read_text(encoding="utf-8-sig"), encoding="utf-8")
        vacs_summary = {
            "exports": [
                {
                    "spec": {"id": "polar_spec_1", "tool": "vacs", "graph_kind": "polar", "variant": "main", "format": "txt"},
                    "entry": {"graph_kind": "polar", "graph_variant": "main", "format": "txt"},
                    "plugin_id": "test",
                    "output_path": str(target_file),
                    "details": {},
                }
            ]
        }

        first = _ingest_vacs_exports(
            writer=writer,
            project=project,
            batch=batch,
            run_id="RUN001",
            version_id="V001",
            exports_dir=exports_dir,
            vacs_export_summary=vacs_summary,
        )
        second = _ingest_vacs_exports(
            writer=writer,
            project=project,
            batch=batch,
            run_id="RUN001",
            version_id="V001",
            exports_dir=exports_dir,
            vacs_export_summary=vacs_summary,
        )
        self.assertEqual(int(first.get("polar_measurements_written", 0)), 1)
        self.assertEqual(int(second.get("polar_measurements_written", 0)), 0)
        self.assertEqual(int(second.get("polar_duplicates_skipped", 0)), 1)

        project_db = project_root / "dataset" / "project.sqlite"
        with closing(sqlite3.connect(str(project_db))) as conn:
            meas_count = conn.execute("SELECT COUNT(*) FROM polar_measurements").fetchone()[0]
            point_count = conn.execute("SELECT COUNT(*) FROM polar_points").fetchone()[0]
        self.assertEqual(int(meas_count), 1)
        self.assertEqual(int(point_count), 6)


if __name__ == "__main__":
    unittest.main()
