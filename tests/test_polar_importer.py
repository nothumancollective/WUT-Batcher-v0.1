from contextlib import closing
import sqlite3
import tempfile
from pathlib import Path
import unittest

from app.models import Batch, Project, ProjectConstraints, SimExportSettings, VersionSpec
from app.polar_txt_parser import PolarTxtParseError
from app.runtime_orchestrator import _ingest_vacs_exports, _resolve_norm_angle_deg
from app.tidy_dataset import TidyDatasetWriter


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vacs"


class PolarImporterTests(unittest.TestCase):
    @staticmethod
    def _batch_with_plane_norms(*, h: float, v: float, d: float) -> Batch:
        return Batch(
            batch_id="B001",
            project_id="P001",
            sim_export_settings=SimExportSettings(
                export_specs=[
                    {
                        "id": "polar_h",
                        "tool": "vacs",
                        "graph_kind": "polar",
                        "options": {"polar_name": "SPL_H", "inclination": 0, "norm_angle": h},
                    },
                    {
                        "id": "polar_v",
                        "tool": "vacs",
                        "graph_kind": "polar",
                        "options": {"polar_name": "SPL_V", "inclination": 90, "norm_angle": v},
                    },
                    {
                        "id": "polar_d",
                        "tool": "vacs",
                        "graph_kind": "polar",
                        "options": {"polar_name": "SPL_D", "inclination": 45, "norm_angle": d},
                    },
                ]
            ),
        )

    def test_external_export_norm_angle_matches_source_orientation(self) -> None:
        value, policy = _resolve_norm_angle_deg(
            batch=self._batch_with_plane_norms(h=10, v=20, d=30),
            contract={"spec": {"id": "external_any_01"}, "details": {"source_orientation_token": "V"}},
            metadata={},
        )
        self.assertEqual(value, 20.0)
        self.assertEqual(policy.get("source"), "batch.orientation_norm_angle")
        self.assertEqual(policy.get("orientation"), "V")

    def test_external_export_norm_angle_uses_unambiguous_common_value(self) -> None:
        value, policy = _resolve_norm_angle_deg(
            batch=self._batch_with_plane_norms(h=20, v=20, d=20),
            contract={"spec": {"id": "external_any_01"}, "details": {}},
            metadata={},
        )
        self.assertEqual(value, 20.0)
        self.assertEqual(policy.get("source"), "batch.common_polar_norm_angle")

    def test_external_export_norm_angle_rejects_ambiguous_plane_values(self) -> None:
        value, policy = _resolve_norm_angle_deg(
            batch=self._batch_with_plane_norms(h=10, v=20, d=30),
            contract={"spec": {"id": "external_any_01"}, "details": {}},
            metadata={},
        )
        self.assertIsNone(value)
        self.assertEqual(policy.get("source"), "none")

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

    def test_zero_valued_spl_export_is_rejected_before_ingest(self) -> None:
        project_root, writer, project, batch = self._prepare_project()
        exports_dir = project_root / "versions" / "V001" / "exports" / "RUN001"
        exports_dir.mkdir(parents=True, exist_ok=True)
        output_file = exports_dir / "zero_spl.txt"
        output_file.write_text(
            "\n".join(
                [
                    "GraphType=SoundPressure",
                    "Data_LevelType=SoundPressure",
                    "Data_Legend='Sound pressure'",
                    "StartString_Data=Data",
                    "EndString_Data=Data_End",
                    "Data",
                    "1000 0.0 0.0",
                    "2000 0.0 0.0",
                    "Data_End",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        vacs_summary = {
            "exports": [
                {
                    "spec": {"id": "spl", "graph_kind": "spl", "variant": "main", "format": "txt"},
                    "entry": {"graph_kind": "spl", "graph_variant": "main", "format": "txt"},
                    "plugin_id": "test",
                    "output_path": str(output_file),
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
        self.assertTrue(ingest.get("quality_errors"))
        self.assertEqual(int(ingest.get("rows_prepared", 0)), 0)
        with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM graphs").fetchone()[0], 0)

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

        project_db = writer.project_db_path
        global_db = writer.global_db_path
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

    def test_external_export_persists_plane_specific_norm_angle(self) -> None:
        project_root, writer, project, _batch = self._prepare_project()
        batch = self._batch_with_plane_norms(h=10, v=20, d=30)
        exports_dir = project_root / "versions" / "V001" / "exports" / "RUN001"
        exports_dir.mkdir(parents=True, exist_ok=True)
        source_file = FIXTURES / "result_v001polar_matrix_small.txt"
        target_file = exports_dir / "V001_anygraph_01_Mic_Polar_D.txt"
        target_file.write_text(source_file.read_text(encoding="utf-8-sig"), encoding="utf-8")
        vacs_summary = {
            "exports": [
                {
                    "spec": {"id": "external_any_01", "graph_kind": "polar", "variant": "external_01"},
                    "entry": {"graph_kind": "polar", "graph_variant": "external_01", "format": "txt"},
                    "plugin_id": "external_vacs_export_save_all",
                    "output_path": str(target_file),
                    "details": {"source_orientation_token": "D"},
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
        with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
            row = conn.execute(
                "SELECT orientation, norm_angle_deg, export_meta_json FROM polar_measurements LIMIT 1"
            ).fetchone()
        self.assertEqual(str(row[0]), "D")
        self.assertEqual(float(row[1]), 30.0)
        self.assertIn('"source": "batch.orientation_norm_angle"', str(row[2]))

    def test_contract_backed_normalized_peak_polar_is_written(self) -> None:
        project_root, writer, project, batch = self._prepare_project()
        exports_dir = project_root / "versions" / "V001" / "exports" / "RUN001"
        exports_dir.mkdir(parents=True, exist_ok=True)
        source_text = (FIXTURES / "result_v001polar_matrix_small.txt").read_text(encoding="utf-8-sig")
        target_file = exports_dir / "V001_anygraph_01_Mic_Polar_-_BE_Spectrum_2_D.txt"
        target_file.write_text(
            source_text.replace("Data_LevelType=SoundPressure", "Data_LevelType=Peak").replace(
                "Data_BaseUnit=Pa", "Data_BaseUnit=''"
            ),
            encoding="utf-8",
        )
        vacs_summary = {
            "exports": [
                {
                    "spec": {"id": "external_any_01", "graph_kind": "polar", "variant": "external_01"},
                    "entry": {"graph_kind": "polar", "graph_variant": "external_01", "format": "txt"},
                    "plugin_id": "external_vacs_export_save_all",
                    "output_path": str(target_file),
                    "details": {"source_orientation_token": "D", "source_title": "Mic Polar - BE_Spectrum #2"},
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
        with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
            row = conn.execute(
                "SELECT orientation, data_level_type, data_base_unit FROM polar_measurements LIMIT 1"
            ).fetchone()
        self.assertEqual(tuple(row), ("D", "Peak", ""))

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

        project_db = writer.project_db_path
        with closing(sqlite3.connect(str(project_db))) as conn:
            meas_count = conn.execute("SELECT COUNT(*) FROM polar_measurements").fetchone()[0]
            point_count = conn.execute("SELECT COUNT(*) FROM polar_points").fetchone()[0]
        self.assertEqual(int(meas_count), 1)
        self.assertEqual(int(point_count), 6)

    def test_import_format_b_abscissa_writes_expected_counts(self) -> None:
        project_root, writer, project, batch = self._prepare_project()
        exports_dir = project_root / "versions" / "V001" / "exports" / "RUN001"
        exports_dir.mkdir(parents=True, exist_ok=True)
        source_file = FIXTURES / "result_v001polar_matrix_small_abscissa.txt"
        target_file = exports_dir / "20260221_000000_01_Mic_Polar_-_BE_Spectrum_3.txt"
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

        project_db = writer.project_db_path
        with closing(sqlite3.connect(str(project_db))) as conn:
            meas = conn.execute(
                """
                SELECT orientation, freq_count, angle_count, polar_id
                FROM polar_measurements
                LIMIT 1
                """
            ).fetchone()
            point_count = conn.execute(
                "SELECT COUNT(*) FROM polar_points WHERE polar_id = ?",
                (str(meas[3]),),
            ).fetchone()[0]
        self.assertEqual(str(meas[0]), "H")
        self.assertEqual(int(meas[1]), 2)
        self.assertEqual(int(meas[2]), 3)
        self.assertEqual(int(point_count), 6)

    def test_complex_impedance_export_is_not_written_as_polar_measurement(self) -> None:
        project_root, writer, project, batch = self._prepare_project()
        exports_dir = project_root / "versions" / "V001" / "exports" / "RUN001"
        exports_dir.mkdir(parents=True, exist_ok=True)
        output_file = exports_dir / "radiation_impedance.txt"
        output_file.write_text(
            "\n".join(
                [
                    "SourceDesc=VACS_Data_Text",
                    "StartString_Data=Data",
                    "EndString_Data=Data_End",
                    "Data_Format=Complex",
                    "Data_Domain=Frequency",
                    "Data_LevelType=Impedance10",
                    "Data_AbscUnit=Hz",
                    "Data_Legend='Radiation_Impedance #5; ; Normalized'",
                    "Param_Coord_x1=1",
                    "Param_Coord_x2=90",
                    "Param_Coord_x3=0",
                    "Param_Coord_Type=Spherical",
                    "Data",
                    "400 1.0 0.1",
                    "800 1.5 0.2",
                    "Data_End",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        vacs_summary = {
            "exports": [
                {
                    "spec": {
                        "id": "radimp",
                        "tool": "vacs",
                        "graph_kind": "impedance",
                        "variant": "main",
                        "format": "txt",
                    },
                    "entry": {"graph_kind": "impedance", "graph_variant": "main", "format": "txt"},
                    "plugin_id": "test",
                    "output_path": str(output_file),
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
        self.assertEqual(int(ingest.get("polar_measurements_written", 0)), 0)
        with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM polar_measurements").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM graphs").fetchone()[0], 1)

    def test_import_fails_fast_on_missing_required_headers(self) -> None:
        project_root, writer, project, batch = self._prepare_project()
        exports_dir = project_root / "versions" / "V001" / "exports" / "RUN001"
        exports_dir.mkdir(parents=True, exist_ok=True)
        bad_file = exports_dir / "bad_missing_param_coords.txt"
        bad_file.write_text(
            "\n".join(
                [
                    "StartString_Data=Data",
                    "EndString_Data=Data_End",
                    "Data_Format=Complex",
                    "Data_Domain=Frequency",
                    "Data",
                    "100 1.0 0.1 2.0 0.2",
                    "Data_End",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        vacs_summary = {
            "exports": [
                {
                    "spec": {
                        "id": "polar_spec_1",
                        "tool": "vacs",
                        "graph_kind": "polar",
                        "variant": "main",
                        "format": "txt",
                    },
                    "entry": {"graph_kind": "polar", "graph_variant": "main", "format": "txt"},
                    "plugin_id": "test",
                    "output_path": str(bad_file),
                    "details": {},
                }
            ]
        }
        with self.assertRaises(PolarTxtParseError) as ctx:
            _ingest_vacs_exports(
                writer=writer,
                project=project,
                batch=batch,
                run_id="RUN001",
                version_id="V001",
                exports_dir=exports_dir,
                vacs_export_summary=vacs_summary,
            )
        self.assertEqual(ctx.exception.error_code, "MISSING_HEADER")
        self.assertIn("Export of Parameters", ctx.exception.reason)
        self.assertIn("Param_Coord_x2", ctx.exception.reason)
        self.assertIn("Param_Coord_x3", ctx.exception.reason)


if __name__ == "__main__":
    unittest.main()
