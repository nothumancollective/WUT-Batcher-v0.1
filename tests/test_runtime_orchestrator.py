from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.models import Batch, ParamSelection, Project, ProjectConstraints, SimExportSettings, SweepSpec
from app.runtime_orchestrator import run_batch_pipeline


class RuntimeOrchestratorTests(unittest.TestCase):
    def test_pipeline_dry_run_records_version_runtime_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime Manifest Test",
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
                sweeps={"Coverage.Angle": SweepSpec(key="Coverage.Angle", start=40.0, end=50.0, steps=2)},
                sweep_mode="single",
                runner_mode="AthGuidePreview",
            )

            summary = run_batch_pipeline(
                project=project,
                batch=batch,
                projects_root=projects_root,
                dry_run=True,
                run_id="RUN_DETERMINISTIC",
            )

            self.assertEqual(summary.versions, ["V001", "V002"])
            for version_id in summary.versions:
                payload = json.loads(
                    (Path(summary.project_root) / "versions" / version_id / "version.json").read_text(encoding="utf-8-sig")
                )
                self.assertEqual(str(payload.get("run_id")), "RUN_DETERMINISTIC")
                self.assertIsInstance(payload.get("parameter_snapshot"), dict)
                params = dict(payload.get("parameter_snapshot", {}) or {})
                self.assertIn("Length", params)
                self.assertIn("Throat.Diameter", params)
                self.assertIn("Coverage.Angle", params)
                run_cfg_path = Path(str(payload.get("run_cfg_path")))
                self.assertTrue(run_cfg_path.exists())
                self.assertEqual(run_cfg_path.suffix.lower(), ".cfg")

    def test_pipeline_cleans_runtime_cfg_and_ath_export_subdir_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            ath_export_root = Path(tmp_dir) / "ath_export"
            ath_export_root.mkdir(parents=True, exist_ok=True)
            project = Project(
                project_id="P001",
                name="Runtime Cleanup Test",
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
            ath_script = (
                "from pathlib import Path; import sys; "
                f"root=Path(r'{str(ath_export_root)}'); "
                "cfg=Path(sys.argv[-1]); "
                "sub=root/cfg.stem; sub.mkdir(parents=True, exist_ok=True); "
                "(sub/'mesh.stl').write_text('solid m\\nendsolid m\\n', encoding='utf-8'); "
                "print('Length=111 Width=222 Height=333')"
            )

            summary = run_batch_pipeline(
                project=project,
                batch=batch,
                projects_root=projects_root,
                ath_executable=sys.executable,
                ath_base_args=["-c", ath_script],
                continue_on_error=True,
                ath_export_root=ath_export_root,
            )
            self.assertEqual(str(summary.run_status), "succeeded")
            version_payload = json.loads(
                (Path(summary.project_root) / "versions" / summary.versions[0] / "version.json").read_text(encoding="utf-8-sig")
            )
            run_cfg_path = Path(str(version_payload.get("run_cfg_path")))
            ath_export_dir = Path(str(version_payload.get("ath_export_dir")))
            self.assertFalse(run_cfg_path.exists())
            self.assertFalse(ath_export_dir.exists())

            cfg_cleanup = [
                row for row in summary.cleanup_results if row.get("artifact") == "cfg" and row.get("version_id") == summary.versions[0]
            ]
            export_cleanup = [
                row
                for row in summary.cleanup_results
                if row.get("artifact") == "ath_export_subdir" and row.get("version_id") == summary.versions[0]
            ]
            self.assertEqual(len(cfg_cleanup), 1)
            self.assertEqual(str(cfg_cleanup[0].get("reason")), "deleted")
            self.assertTrue(bool(cfg_cleanup[0].get("deleted")))
            self.assertEqual(len(export_cleanup), 1)
            self.assertEqual(str(export_cleanup[0].get("reason")), "deleted")
            self.assertTrue(bool(export_cleanup[0].get("deleted")))

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
            cfg_cleanup = [row for row in summary.cleanup_results if row.get("artifact") == "cfg"]
            export_cleanup = [row for row in summary.cleanup_results if row.get("artifact") == "ath_export_subdir"]
            self.assertEqual(len(cfg_cleanup), 1)
            self.assertTrue(bool(cfg_cleanup[0]["deleted"]))
            self.assertEqual(str(cfg_cleanup[0]["reason"]), "deleted")
            self.assertEqual(len(export_cleanup), 1)
            self.assertIn(str(export_cleanup[0]["reason"]), {"target_missing", "deleted", "ath_export_root_unset"})

            project_root = Path(summary.project_root)
            project_db = project_root / "dataset" / "project.sqlite"
            self.assertTrue(project_db.exists())
            with closing(sqlite3.connect(str(project_db))) as conn:
                dims_count = conn.execute("SELECT COUNT(*) FROM ath_dimensions").fetchone()[0]
                run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                run_status = conn.execute("SELECT status FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]
            self.assertEqual(dims_count, 1)
            self.assertEqual(int(run_count), 1)
            self.assertEqual(str(run_status), "succeeded")

    def test_pipeline_ingests_vacs_txt_into_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime VACS Test",
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
            vacs_script = (
                "from pathlib import Path; "
                "Path('Result_V001SPL.txt').write_text("
                "'Frequency [Hz];SPL [dB]\\n100;90,5\\n200;91,0\\n', encoding='utf-8'); "
                "print('exported')"
            )

            summary = run_batch_pipeline(
                project=project,
                batch=batch,
                projects_root=projects_root,
                vacs_executable=sys.executable,
                vacs_base_args=["-c", vacs_script],
                continue_on_error=True,
            )

            self.assertEqual(summary.project_id, "P001")
            self.assertEqual(summary.batch_id, "B001")
            self.assertEqual(len(summary.stage_results), 1)
            self.assertEqual(summary.stage_results[0].stage, "vacs")
            self.assertEqual(summary.stage_results[0].status, "ok")

            project_root = Path(summary.project_root)
            project_db = project_root / "dataset" / "project.sqlite"
            self.assertTrue(project_db.exists())
            with closing(sqlite3.connect(str(project_db))) as conn:
                graph_count = conn.execute("SELECT COUNT(*) FROM graphs").fetchone()[0]
                series_count = conn.execute("SELECT COUNT(*) FROM graph_series").fetchone()[0]
                point_count = conn.execute("SELECT COUNT(*) FROM graph_points").fetchone()[0]
                run_graph_count = conn.execute("SELECT COUNT(*) FROM graphs WHERE run_id IS NOT NULL").fetchone()[0]
            self.assertEqual(graph_count, 1)
            self.assertEqual(series_count, 1)
            self.assertEqual(point_count, 2)
            self.assertEqual(run_graph_count, 1)

    def test_pipeline_dry_run_keeps_ath_work_and_marks_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime DryRun Test",
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
                dry_run=True,
            )

            self.assertTrue(summary.dry_run)
            self.assertEqual(len(summary.stage_results), 1)
            self.assertEqual(summary.stage_results[0].stage, "dry_run")
            self.assertTrue(summary.cleanup_results)
            for row in summary.cleanup_results:
                if row.get("artifact") == "cfg":
                    self.assertEqual(str(row.get("reason")), "dry_run_no_delete")

            project_root = Path(summary.project_root)
            ath_work_dir = project_root / "versions" / summary.versions[0] / "ath_work"
            self.assertTrue(ath_work_dir.exists())
            with closing(sqlite3.connect(str(project_root / "dataset" / "project.sqlite"))) as conn:
                row = conn.execute(
                    "SELECT status FROM versions WHERE version_id = ?",
                    (summary.versions[0],),
                ).fetchone()
            self.assertEqual(str(row[0]), "dry_run_completed")

    def test_pipeline_ingests_polar_series_into_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime Polar Test",
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
            vacs_script = (
                "from pathlib import Path; "
                "Path('Result_V001POLAR.txt').write_text("
                "'GraphType=POLAR_SPL\\n'"
                "'Data_XName=Frequency\\n'"
                "'Data_XUnit=Hz\\n'"
                "'Data_YName=Pressure\\n'"
                "'Data_BaseUnit=Pa\\n'"
                "'StartString_Data=Data\\n'"
                "'EndString_Data=Data_End\\n'"
                "'Data\\n'"
                "'Series=Angle:0\\n'"
                "'100 1.0 0.1\\n'"
                "'200 1.1 0.2\\n'"
                "'Series=Angle:30\\n'"
                "'100 0.9 0.05\\n'"
                "'200 1.0 0.10\\n'"
                "'Data_End\\n', encoding='utf-8'); "
                "print('exported polar')"
            )

            summary = run_batch_pipeline(
                project=project,
                batch=batch,
                projects_root=projects_root,
                vacs_executable=sys.executable,
                vacs_base_args=["-c", vacs_script],
                continue_on_error=True,
            )
            self.assertEqual(summary.stage_results[0].stage, "vacs")
            self.assertEqual(summary.stage_results[0].status, "ok")

            project_root = Path(summary.project_root)
            project_db = project_root / "dataset" / "project.sqlite"
            with closing(sqlite3.connect(str(project_db))) as conn:
                graph_count = conn.execute("SELECT COUNT(*) FROM graphs").fetchone()[0]
                series_count = conn.execute("SELECT COUNT(*) FROM graph_series").fetchone()[0]
                point_count = conn.execute("SELECT COUNT(*) FROM graph_points").fetchone()[0]
                imag_count = conn.execute(
                    "SELECT COUNT(*) FROM graph_points WHERE y_imag IS NOT NULL"
                ).fetchone()[0]
            self.assertEqual(graph_count, 1)
            self.assertEqual(series_count, 2)
            self.assertEqual(point_count, 4)
            self.assertEqual(imag_count, 4)

    def test_pipeline_prefers_export_spec_mapping_for_graph_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime Mapped Ingest Test",
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
                sim_export_settings=SimExportSettings(
                    export_specs=[
                        {
                            "id": "spl_main",
                            "tool": "vacs",
                            "graph_kind": "spl",
                            "variant": "main",
                            "format": "txt",
                            "output_name_template": "mapped_spl.txt",
                        }
                    ]
                ),
            )

            def _fake_run_vacs_export_specs(**kwargs):
                export_dir = Path(str(kwargs["export_dir"]))
                output_file = export_dir / "mapped_spl.txt"
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_text(
                    "\n".join(
                        [
                            "GraphType=UnknownCurveName",
                            "Data_XName=Frequency",
                            "Data_XUnit=Hz",
                            "Data_YName=Level",
                            "Data_BaseUnit=dB",
                            "StartString_Data=Data",
                            "EndString_Data=Data_End",
                            "Data",
                            "100 90.0",
                            "200 91.0",
                            "Data_End",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return {
                    "executed": True,
                    "export_count": 1,
                    "exports": [
                        {
                            "spec": {
                                "id": "spl_main",
                                "tool": "vacs",
                                "graph_kind": "spl",
                                "variant": "main",
                                "format": "txt",
                            },
                            "entry": {"graph_kind": "spl", "graph_variant": "main", "format": "txt"},
                            "plugin_id": "fake",
                            "output_path": str(output_file),
                            "details": {"source": "fake"},
                        }
                    ],
                }

            with patch("app.runtime_orchestrator.run_vacs_export_specs", side_effect=_fake_run_vacs_export_specs):
                summary = run_batch_pipeline(
                    project=project,
                    batch=batch,
                    projects_root=projects_root,
                    vacs_executable=sys.executable,
                    continue_on_error=True,
                )

            self.assertEqual(summary.run_status, "succeeded")
            project_db = Path(summary.project_root) / "dataset" / "project.sqlite"
            with closing(sqlite3.connect(str(project_db))) as conn:
                row = conn.execute(
                    "SELECT graph_kind, variant, graph_type FROM graphs ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "spl")
            self.assertEqual(str(row[1]), "main")
            self.assertEqual(str(row[2]), "UnknownCurveName")

    def test_pipeline_marks_vacs_failed_on_graph_kind_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime Mapping Mismatch Test",
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
                sim_export_settings=SimExportSettings(
                    export_specs=[
                        {
                            "id": "spl_main",
                            "tool": "vacs",
                            "graph_kind": "spl",
                            "variant": "main",
                            "format": "txt",
                            "output_name_template": "mapped_spl.txt",
                        }
                    ]
                ),
            )

            def _fake_run_vacs_export_specs(**kwargs):
                export_dir = Path(str(kwargs["export_dir"]))
                output_file = export_dir / "mapped_spl.txt"
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_text(
                    "\n".join(
                        [
                            "GraphType=Impedance10",
                            "Data_LevelType=Impedance10",
                            "Data_Legend='Radiation_Impedance #5'",
                            "StartString_Data=Data",
                            "EndString_Data=Data_End",
                            "Data",
                            "1000 0.0 0.0",
                            "Data_End",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return {
                    "executed": True,
                    "export_count": 1,
                    "exports": [
                        {
                            "spec": {
                                "id": "spl_main",
                                "tool": "vacs",
                                "graph_kind": "spl",
                                "variant": "main",
                                "format": "txt",
                            },
                            "entry": {"graph_kind": "spl", "graph_variant": "main", "format": "txt"},
                            "plugin_id": "fake",
                            "output_path": str(output_file),
                            "details": {"source": "fake"},
                        }
                    ],
                }

            with patch("app.runtime_orchestrator.run_vacs_export_specs", side_effect=_fake_run_vacs_export_specs):
                summary = run_batch_pipeline(
                    project=project,
                    batch=batch,
                    projects_root=projects_root,
                    vacs_executable=sys.executable,
                    continue_on_error=True,
                )

            self.assertEqual(summary.run_status, "failed")
            project_db = Path(summary.project_root) / "dataset" / "project.sqlite"
            with closing(sqlite3.connect(str(project_db))) as conn:
                version_status = conn.execute(
                    "SELECT status FROM versions WHERE version_id = ?",
                    (summary.versions[0],),
                ).fetchone()[0]
                graph_count = conn.execute("SELECT COUNT(*) FROM graphs").fetchone()[0]
            self.assertEqual(str(version_status), "failed")
            self.assertEqual(int(graph_count), 0)

            version_payload = json.loads(
                (Path(summary.project_root) / "versions" / summary.versions[0] / "version.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            ingest = version_payload.get("vacs_export_ingest", {})
            self.assertTrue(bool(ingest.get("mapping_errors")))


if __name__ == "__main__":
    unittest.main()
