from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.models import Batch, ParamSelection, Project, ProjectConstraints, SimExportSettings, SweepSpec
from app.runners import parse_ath_dimensions
from app.runtime_orchestrator import (
    StageExecution,
    _read_log_tail_text,
    _apply_sim_export_settings_to_cfg,
    _resolve_export_specs,
    _run_akabak_ui_driver_stage,
    _supports_uia_executable,
    _sync_generated_abec,
    run_batch_pipeline,
)


def _project_db_path(project_root: Path) -> Path:
    preferred = project_root / "db" / "project.sqlite"
    legacy = project_root / "dataset" / "project.sqlite"
    if preferred.exists() or not legacy.exists():
        return preferred
    return legacy


def _library_db_path(library_root: Path) -> Path:
    root = Path(library_root)
    if str(root.name).lower() == "projects":
        root = root.parent
    preferred = root / "library.sqlite"
    legacy = root / "global.sqlite"
    if preferred.exists() or not legacy.exists():
        return preferred
    return legacy


class RuntimeOrchestratorTests(unittest.TestCase):
    def test_uia_automation_requires_native_executable(self) -> None:
        self.assertTrue(_supports_uia_executable(r"C:\Program Files\RDTeam\AKABAK\AKABAK.exe"))
        self.assertFalse(_supports_uia_executable(r"C:\qa\akabak_fake.cmd"))
        self.assertFalse(_supports_uia_executable(None))

    def test_read_log_tail_limits_bytes_and_keeps_final_dimension_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "ath.stdout.log"
            prefix = "PREFIX_SENTINEL_START\n" + ("filler\n" * 8_000)
            suffix = "\n".join(
                [
                    "Device width x height = 270.97 x 270.97 mm (10.668 x 10.668\")",
                    "Device length =         140.00 mm (5.512\")",
                ]
            )
            log_path.write_text(prefix + suffix, encoding="utf-8")

            tail = _read_log_tail_text(log_path, max_bytes=512)

            self.assertNotIn("PREFIX_SENTINEL_START", tail)
            parsed = parse_ath_dimensions(tail)
            self.assertEqual(parsed.horn_length_mm, 140.0)
            self.assertEqual(parsed.horn_width_mm, 270.97)
            self.assertEqual(parsed.horn_height_mm, 270.97)

    def test_default_polar_export_specs_use_h_v_d_inclinations(self) -> None:
        specs = _resolve_export_specs({"auto_default_polar_exports": True})
        polar_specs = [spec for spec in list(specs) if str(getattr(spec, "graph_kind", "")).lower() == "polar"]
        self.assertEqual(len(polar_specs), 3)
        self.assertEqual(
            [int(dict(getattr(spec, "options", {}) or {}).get("inclination", -999)) for spec in polar_specs],
            [0, 90, 45],
        )
        self.assertEqual(
            [str(dict(getattr(spec, "options", {}) or {}).get("polar_name", "")) for spec in polar_specs],
            ["SPL_H", "SPL_V", "SPL_D"],
        )

    def test_resolve_export_specs_normalizes_legacy_h_and_d_inclinations(self) -> None:
        payload = {
            "export_specs": [
                {
                    "id": "adv_polar_1",
                    "tool": "vacs",
                    "graph_kind": "polar",
                    "variant": "main",
                    "format": "txt",
                    "options": {"polar_name": "Polars H", "inclination": 90},
                },
                {
                    "id": "adv_polar_2",
                    "tool": "vacs",
                    "graph_kind": "polar",
                    "variant": "main",
                    "format": "txt",
                    "options": {"polar_name": "Polars V", "inclination": 90},
                },
                {
                    "id": "adv_polar_3",
                    "tool": "vacs",
                    "graph_kind": "polar",
                    "variant": "main",
                    "format": "txt",
                    "options": {"polar_name": "Polars D", "inclination": 42},
                },
            ]
        }
        specs = _resolve_export_specs(payload)
        polar_specs = [spec for spec in specs if str(spec.graph_kind).lower() == "polar"]
        self.assertEqual(len(polar_specs), 3)
        self.assertEqual(
            [int(dict(spec.options or {}).get("inclination", -999)) for spec in polar_specs],
            [0, 90, 45],
        )

    def test_apply_sim_export_settings_injects_polar_block(self) -> None:
        base = "Output.ABECProject = 1\nOutput.STL = 0\n"
        spec = SimpleNamespace(
            graph_kind="polar",
            options={
                "polar_name": "SPL_V",
                "map_angle_range": [0, 90, 19],
                "distance_m": 2.0,
                "offset": 145,
                "inclination": 90,
            },
        )
        text = _apply_sim_export_settings_to_cfg(
            base,
            sim_export_settings={
                "freq_start_hz": 500.0,
                "freq_end_hz": 15000.0,
                "num_points": 16,
                "mesh_frequency": None,
                "simulation_mode": "free_standing",
            },
            export_specs=[spec],
        )
        self.assertIn("ABEC.SimType = 2", text)
        self.assertIn("ABEC.f1 = 500", text)
        self.assertIn("ABEC.f2 = 15000", text)
        self.assertIn("ABEC.NumFrequencies = 16", text)
        self.assertIn("ABEC.Polars:SPL_V = {", text)
        self.assertIn("MapAngleRange = 0,90,19", text)
        self.assertIn("Distance = 2", text)
        self.assertIn("Offset = 145", text)
        self.assertIn("Inclination = 90", text)

    def test_apply_sim_export_settings_keeps_h_v_d_specs(self) -> None:
        base = "Output.ABECProject = 1\nOutput.STL = 0\n"
        payload = {
            "freq_start_hz": 500.0,
            "freq_end_hz": 10000.0,
            "num_points": 12,
            "simulation_mode": "free_standing",
            "export_specs": [
                {
                    "id": "adv_polar_1",
                    "tool": "vacs",
                    "graph_kind": "polar",
                    "variant": "main",
                    "format": "txt",
                    "options": {
                        "polar_name": "SPL_H",
                        "map_angle_range": [-90, 90, 19],
                        "distance_m": 2.0,
                        "offset": 145,
                        "inclination": 0,
                    },
                },
                {
                    "id": "adv_polar_2",
                    "tool": "vacs",
                    "graph_kind": "polar",
                    "variant": "main",
                    "format": "txt",
                    "options": {
                        "polar_name": "SPL_V",
                        "map_angle_range": [-90, 90, 19],
                        "distance_m": 2.0,
                        "offset": 145,
                        "inclination": 90,
                    },
                },
                {
                    "id": "adv_polar_3",
                    "tool": "vacs",
                    "graph_kind": "polar",
                    "variant": "main",
                    "format": "txt",
                    "options": {
                        "polar_name": "SPL_D",
                        "map_angle_range": [-90, 90, 19],
                        "distance_m": 2.0,
                        "offset": 145,
                        "inclination": 45,
                    },
                },
            ],
        }
        specs = _resolve_export_specs(payload)
        text = _apply_sim_export_settings_to_cfg(base, sim_export_settings=payload, export_specs=specs)
        self.assertIn("ABEC.Polars:SPL_H = {", text)
        self.assertIn("ABEC.Polars:SPL_V = {", text)
        self.assertIn("ABEC.Polars:SPL_D = {", text)
        self.assertIn("Inclination = 0", text)
        self.assertIn("Inclination = 90", text)
        self.assertIn("Inclination = 45", text)

    def test_akabak_stage_preserves_vacs_for_export_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir) / "logs"
            abec_path = Path(tmp_dir) / "Project.abec"
            abec_path.write_text("stub", encoding="utf-8")

            class _FakeAkabakDriver:
                def __init__(self, *, executable: str, log_dir: Path) -> None:
                    self.watchdog_events: list[dict] = []
                    self.last_open_dialog_diagnostics_path = ""
                    self.last_import_diagnostics_path = ""
                    self.last_solve_diagnostics_path = ""

                def open_project(self, abec_project_path: Path):
                    return SimpleNamespace(ok=True, status="project_open")

                def import_if_needed(self):
                    return SimpleNamespace(ok=True, status="project_open")

                def run_solve(self):
                    return SimpleNamespace(ok=True, status="running")

                def wait_for_completion(self, timeout_s: int = 300, require_vacs_graph_import: bool = False):
                    return SimpleNamespace(ok=True, status="completed")

                def close(self):
                    return SimpleNamespace(ok=True, status="closed")

            with patch("app.runtime_orchestrator.AkabakDriver", _FakeAkabakDriver):
                with patch(
                    "app.runtime_orchestrator._list_vacs_process_ids",
                    side_effect=[[111], [222]],
                ):
                    with patch(
                        "app.runtime_orchestrator._terminate_process_ids",
                        return_value={"requested": [111], "terminated": [111], "failed": []},
                    ) as terminate_mock:
                        stage, payload, ok = _run_akabak_ui_driver_stage(
                            version_id="V001",
                            executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                            abec_project_path=abec_path,
                            version_logs_dir=logs_dir,
                            require_vacs_graph_import=True,
                            preserve_vacs_for_export=True,
                        )

            self.assertTrue(ok)
            self.assertEqual(stage.status, "ok")
            self.assertEqual(terminate_mock.call_count, 1)
            self.assertEqual(str(payload.get("summary_log")), str(stage.summary_log))
            summary_payload = json.loads(Path(stage.summary_log).read_text(encoding="utf-8-sig"))
            cleanup = dict(summary_payload.get("vacs_cleanup", {}) or {})
            self.assertEqual(cleanup.get("before_stage_pids"), [111])
            self.assertEqual(cleanup.get("after_stage_pids"), [222])
            post = dict(cleanup.get("post_stage", {}) or {})
            self.assertTrue(bool(post.get("skipped")))
            self.assertEqual(str(post.get("reason")), "preserve_for_vacs_export")

    def test_sync_generated_abec_copies_referenced_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_dir = root / "ath_out" / "ABEC_FreeStanding"
            source_dir.mkdir(parents=True, exist_ok=True)
            source_abec = source_dir / "Project.abec"
            source_abec.write_text(
                "\n".join(
                    [
                        "[Project]",
                        "Scriptname_InfoFile=",
                        "[Solving]",
                        "Scriptname_Solving=solving.txt",
                        "[LEScript]",
                        "Scriptname_LEScript=generic25.txt",
                        "[Observation]",
                        "C0=observation.txt",
                        "[MeshFiles]",
                        "C0=sample_mesh.msh,M1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (source_dir / "solving.txt").write_text("solve\n", encoding="utf-8")
            (source_dir / "observation.txt").write_text("observe\n", encoding="utf-8")
            (source_dir / "generic25.txt").write_text("driver\n", encoding="utf-8")
            (source_dir / "sample_mesh.msh").write_text("mesh\n", encoding="utf-8")

            target_abec = root / "project" / "versions" / "V001" / "abec" / "Project.abec"
            result = _sync_generated_abec(
                target_abec=target_abec,
                search_roots=[root / "ath_out"],
                logs_dir=root / "logs",
            )

            self.assertTrue(result.get("ok"))
            self.assertTrue(target_abec.exists())
            self.assertTrue((target_abec.parent / "solving.txt").exists())
            self.assertTrue((target_abec.parent / "observation.txt").exists())
            self.assertTrue((target_abec.parent / "generic25.txt").exists())
            self.assertTrue((target_abec.parent / "sample_mesh.msh").exists())
            self.assertEqual(result.get("sidecar_missing"), [])
            self.assertEqual(result.get("sidecar_copy_errors"), [])

    def test_sync_generated_abec_defers_repairable_le_driver_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_dir = root / "ath_out"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "Project.abec").write_text(
                "[LEScript]\nScriptname_LEScript=generic25.txt\n",
                encoding="utf-8",
            )
            target_abec = root / "project" / "abec" / "Project.abec"

            result = _sync_generated_abec(
                target_abec=target_abec,
                search_roots=[source_dir],
                logs_dir=root / "logs",
                deferred_sidecar_names=("generic25.txt",),
            )

            self.assertTrue(result.get("ok"))
            self.assertEqual(result.get("sidecar_missing"), [])
            self.assertEqual(result.get("sidecar_deferred"), ["generic25.txt"])
            self.assertFalse((target_abec.parent / "generic25.txt").exists())

    def test_pipeline_wires_post_ath_repair_with_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime LE Profile Test",
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
            repair_calls: list[dict] = []

            class _FakeRepairResult:
                ok = True
                status = "ok"
                diagnostics_path = ""
                abec_path = ""
                error = None

                def to_dict(self):
                    return {"status": "ok"}

            def _fake_repair(**kwargs):
                repair_calls.append(dict(kwargs))
                return _FakeRepairResult()

            fake_stage = StageExecution(
                version_id="V001",
                stage="akabak",
                status="ok",
                exit_code=0,
                timed_out=False,
                summary_log="fake",
            )
            ath_export_root = Path(tmp_dir) / "ath_export"
            ath_export_root.mkdir(parents=True, exist_ok=True)
            ath_script = (
                "from pathlib import Path; import sys; "
                f"root=Path(r'{str(ath_export_root)}'); "
                "cfg=Path(sys.argv[-1]); "
                "sub=root/cfg.stem/'ABEC_FreeStanding'; sub.mkdir(parents=True, exist_ok=True); "
                "(sub/'Project.abec').write_text('[LEScript]\\nScriptname_LEScript=\\n', encoding='utf-8'); "
                "print('Length=111 Width=222 Height=333')"
            )

            with patch("app.runtime_orchestrator.AkabakDriver", object()):
                with patch("app.runtime_orchestrator.repair_post_ath_le_binding", side_effect=_fake_repair):
                    with patch(
                        "app.runtime_orchestrator._assess_pre_akabak_le_driving_contract",
                        return_value={"ok": True, "violations": []},
                    ):
                        with patch(
                            "app.runtime_orchestrator._parse_abec_mesh_requirements",
                            return_value={"section_present": True, "required_mesh_files": [], "missing_mesh_files": []},
                        ):
                            with patch(
                                "app.runtime_orchestrator._run_akabak_ui_driver_stage",
                                return_value=(fake_stage, {"mode": "uia_driver", "summary_log": "fake", "exit_code": 0}, True),
                            ):
                                summary = run_batch_pipeline(
                                    project=project,
                                    batch=batch,
                                    projects_root=projects_root,
                                    ath_executable=sys.executable,
                                    ath_base_args=["-c", ath_script],
                                    akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                                    ath_export_root=ath_export_root,
                                    continue_on_error=True,
                                )

            self.assertEqual(summary.run_status, "succeeded")
            self.assertEqual(len(repair_calls), 1)
            self.assertNotIn("le_patch_profile", repair_calls[0])
            self.assertTrue(str(repair_calls[0].get("diagnostics_dir", "")).endswith("\\logs"))

    def test_pipeline_uses_akabak_ui_driver_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime AKABAK Driver Test",
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

            class _FakeAkabakDriver:
                calls: list[str] = []

                def __init__(self, *, executable: str, log_dir: Path) -> None:
                    _FakeAkabakDriver.calls.append("init")
                    self.executable = executable
                    self.log_dir = log_dir
                    self.watchdog_events: list[dict] = []
                    self.last_open_dialog_diagnostics_path = ""
                    self.last_import_diagnostics_path = ""
                    self.last_solve_diagnostics_path = ""

                def open_project(self, abec_project_path: Path):
                    _FakeAkabakDriver.calls.append("open_project")
                    return SimpleNamespace(ok=True, status="project_open")

                def import_if_needed(self):
                    _FakeAkabakDriver.calls.append("import_if_needed")
                    return SimpleNamespace(ok=True, status="project_open")

                def run_solve(self):
                    _FakeAkabakDriver.calls.append("run_solve")
                    return SimpleNamespace(ok=True, status="running")

                def wait_for_completion(self, timeout_s: int = 300):
                    _FakeAkabakDriver.calls.append("wait_for_completion")
                    return SimpleNamespace(ok=True, status="completed")

                def close(self):
                    _FakeAkabakDriver.calls.append("close")
                    return SimpleNamespace(ok=True, status="closed")

            with patch("app.runtime_orchestrator.AkabakDriver", _FakeAkabakDriver):
                summary = run_batch_pipeline(
                    project=project,
                    batch=batch,
                    projects_root=projects_root,
                    akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                    continue_on_error=True,
                )

            self.assertEqual(summary.run_status, "succeeded")
            self.assertEqual(len(summary.stage_results), 1)
            self.assertEqual(summary.stage_results[0].stage, "akabak")
            self.assertEqual(summary.stage_results[0].status, "ok")
            self.assertEqual(
                _FakeAkabakDriver.calls,
                ["init", "open_project", "import_if_needed", "run_solve", "wait_for_completion", "close"],
            )

            version_payload = json.loads(
                (Path(summary.project_root) / "versions" / summary.versions[0] / "version.json").read_text(encoding="utf-8-sig")
            )
            akabak_result = dict(version_payload.get("akabak_result", {}) or {})
            self.assertEqual(str(akabak_result.get("mode")), "uia_driver")

    def test_pipeline_skips_legacy_vacs_stage_without_export_specs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime Skip Legacy VACS Test",
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

            with patch("app.runtime_orchestrator.VacsRunner.run_export", side_effect=AssertionError("must_not_run")):
                summary = run_batch_pipeline(
                    project=project,
                    batch=batch,
                    projects_root=projects_root,
                    vacs_executable=sys.executable,
                    continue_on_error=True,
                )

            self.assertEqual(summary.run_status, "succeeded")
            self.assertEqual(len(summary.stage_results), 0)
            version_payload = json.loads(
                (Path(summary.project_root) / "versions" / summary.versions[0] / "version.json").read_text(encoding="utf-8-sig")
            )
            self.assertNotIn("vacs_result", version_payload)

    def test_pipeline_skips_akabak_stage_when_ath_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime ATH Fail Skip Test",
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

            with patch("app.runtime_orchestrator.AkabakDriver", object()):
                with patch(
                    "app.runtime_orchestrator._run_akabak_ui_driver_stage",
                    side_effect=AssertionError("must_not_run"),
                ):
                    summary = run_batch_pipeline(
                        project=project,
                        batch=batch,
                        projects_root=projects_root,
                        ath_executable=sys.executable,
                        ath_base_args=["-c", "import sys; sys.exit(1)"],
                        akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                        continue_on_error=True,
                    )

            self.assertEqual(summary.run_status, "failed")
            self.assertTrue(any(stage.stage == "ath" and stage.status == "failed" for stage in summary.stage_results))
            self.assertFalse(any(stage.stage == "akabak" for stage in summary.stage_results))

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

    def test_pipeline_always_writes_run_debug_log_and_persists_run_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime Run Log Persist Test",
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
                run_id="RUN_LOG_PERSIST",
            )

            run_log_path = Path(summary.run_debug_log_path)
            self.assertTrue(run_log_path.exists())
            self.assertEqual(run_log_path.parent, Path(summary.run_root))
            self.assertEqual(Path(summary.project_db_path), _project_db_path(Path(summary.project_root)))
            self.assertTrue(Path(summary.library_db_path).exists())
            lines = [line.strip() for line in run_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any('"event": "run_start"' in line for line in lines))
            self.assertTrue(any('"event": "run_end"' in line for line in lines))
            self.assertTrue(any('"event": "stage_start"' in line for line in lines))
            self.assertTrue(any('"event": "stage_end"' in line for line in lines))
            start_event = next(json.loads(line) for line in lines if '"event": "run_start"' in line)
            self.assertEqual(str(start_event.get("project_db_path") or ""), summary.project_db_path)
            self.assertEqual(str(start_event.get("library_db_path") or ""), summary.library_db_path)

            version_log_path = Path(summary.project_root) / "versions" / summary.versions[0] / "logs" / "pipeline.stage_debug.jsonl"
            self.assertTrue(version_log_path.exists())

            project_db = _project_db_path(Path(summary.project_root))
            with closing(sqlite3.connect(str(project_db))) as conn:
                row = conn.execute(
                    "SELECT run_root, run_debug_log_path FROM runs WHERE run_id = ?",
                    (summary.run_id,),
                ).fetchone()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(str(row[0] or ""), summary.run_root)
            self.assertEqual(str(row[1] or ""), summary.run_debug_log_path)

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
            project_db = _project_db_path(project_root)
            self.assertTrue(project_db.exists())
            with closing(sqlite3.connect(str(project_db))) as conn:
                dims_count = conn.execute("SELECT COUNT(*) FROM ath_dimensions").fetchone()[0]
                run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                run_status = conn.execute("SELECT status FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]
                version_dims = conn.execute(
                    "SELECT ath_length_mm, ath_width_mm, ath_height_mm FROM versions WHERE version_id = ?",
                    (summary.versions[0],),
                ).fetchone()
            library_db = _library_db_path(projects_root)
            self.assertTrue(library_db.exists())
            with closing(sqlite3.connect(str(library_db))) as conn:
                library_dims_count = conn.execute("SELECT COUNT(*) FROM ath_dimensions").fetchone()[0]
                library_version_dims = conn.execute(
                    "SELECT ath_length_mm, ath_width_mm, ath_height_mm FROM versions WHERE version_id = ?",
                    (summary.versions[0],),
                ).fetchone()
            self.assertEqual(dims_count, 1)
            self.assertEqual(int(run_count), 1)
            self.assertEqual(str(run_status), "succeeded")
            self.assertIsNotNone(version_dims)
            assert version_dims is not None
            self.assertAlmostEqual(float(version_dims[0]), 111.0, places=3)
            self.assertAlmostEqual(float(version_dims[1]), 222.0, places=3)
            self.assertAlmostEqual(float(version_dims[2]), 333.0, places=3)
            self.assertEqual(int(library_dims_count), 1)
            self.assertIsNotNone(library_version_dims)
            assert library_version_dims is not None
            self.assertAlmostEqual(float(library_version_dims[0]), 111.0, places=3)
            self.assertAlmostEqual(float(library_version_dims[1]), 222.0, places=3)
            self.assertAlmostEqual(float(library_version_dims[2]), 333.0, places=3)

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
            project_db = _project_db_path(project_root)
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
            with closing(sqlite3.connect(str(_project_db_path(project_root)))) as conn:
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
            project_db = _project_db_path(project_root)
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
                self.assertTrue(bool(kwargs.get("allow_graph_kind_fallback")))
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
            project_db = _project_db_path(Path(summary.project_root))
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
            project_db = _project_db_path(Path(summary.project_root))
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

    def test_pipeline_captures_vacs_system_exit_as_stage_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime VACS SystemExit Guard Test",
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
                        }
                    ]
                ),
            )

            def _boom(**_kwargs):
                raise SystemExit(1)

            with patch("app.runtime_orchestrator.run_vacs_export_specs", side_effect=_boom):
                summary = run_batch_pipeline(
                    project=project,
                    batch=batch,
                    projects_root=projects_root,
                    vacs_executable=sys.executable,
                    continue_on_error=True,
                )

            self.assertEqual(summary.run_status, "failed")
            vacs_stages = [stage for stage in list(summary.stage_results) if str(stage.stage) == "vacs"]
            self.assertEqual(len(vacs_stages), 1)
            self.assertEqual(str(vacs_stages[0].status), "failed")
            self.assertEqual(int(vacs_stages[0].exit_code), 1)

            version_payload = json.loads(
                (Path(summary.project_root) / "versions" / summary.versions[0] / "version.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            vacs_result = dict(version_payload.get("vacs_result", {}) or {})
            self.assertIn("SystemExit(1)", str(vacs_result.get("error", "")))

    def test_pipeline_skips_vacs_stage_when_akabak_stage_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project = Project(
                project_id="P001",
                name="Runtime Skip VACS On AKABAK Failure Test",
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
                        }
                    ]
                ),
            )

            failed_stage = StageExecution(
                version_id="V001",
                stage="akabak",
                status="failed",
                exit_code=1,
                timed_out=False,
                summary_log="akabak.failed.summary.json",
            )

            with patch("app.runtime_orchestrator.AkabakDriver", object()):
                with patch(
                    "app.runtime_orchestrator._run_akabak_ui_driver_stage",
                    return_value=(
                        failed_stage,
                        {"mode": "uia_driver", "summary_log": "akabak.failed.summary.json", "exit_code": 1},
                        False,
                    ),
                ):
                    with patch(
                        "app.runtime_orchestrator.run_vacs_export_specs",
                        side_effect=AssertionError("must_not_run_when_akabak_failed"),
                    ):
                        summary = run_batch_pipeline(
                            project=project,
                            batch=batch,
                            projects_root=projects_root,
                            akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                            vacs_executable=sys.executable,
                            continue_on_error=True,
                        )

            self.assertEqual(summary.run_status, "failed")
            self.assertTrue(any(stage.stage == "akabak" and stage.status == "failed" for stage in summary.stage_results))
            self.assertFalse(any(stage.stage == "vacs" for stage in summary.stage_results))
            run_log_path = Path(summary.run_debug_log_path)
            run_log_lines = [line.strip() for line in run_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any('"event": "stage_start"' in line and '"stage": "akabak"' in line for line in run_log_lines))
            self.assertTrue(any('"event": "stage_end"' in line and '"stage": "akabak"' in line for line in run_log_lines))
            self.assertTrue(any('"event": "run_end"' in line and '"error_summary": "akabak:akabak_failed"' in line for line in run_log_lines))

            with closing(sqlite3.connect(str(_project_db_path(Path(summary.project_root))))) as conn:
                row = conn.execute(
                    "SELECT status, error_summary FROM runs WHERE run_id = ?",
                    (summary.run_id,),
                ).fetchone()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(str(row[0]), "failed")
            self.assertEqual(str(row[1]), "akabak:akabak_failed")

    def test_sync_generated_abec_accepts_fresh_target_dir_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target_abec = root / "versions" / "V001" / "abec" / "Project.abec"
            target_abec.parent.mkdir(parents=True, exist_ok=True)
            target_abec.write_text("[ABEC]\n", encoding="utf-8")
            min_mtime_ns = int(time.time_ns()) - 5_000_000_000
            result = _sync_generated_abec(
                target_abec=target_abec,
                search_roots=(target_abec.parent,),
                logs_dir=target_abec.parent,
                min_mtime_ns=min_mtime_ns,
            )
            self.assertTrue(bool(result.get("ok")))
            self.assertEqual(str(result.get("error") or ""), "")
            self.assertEqual(Path(str(result.get("source_abec"))).resolve(), target_abec.resolve())

    def test_sync_generated_abec_rejects_stale_target_dir_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target_abec = root / "versions" / "V001" / "abec" / "Project.abec"
            target_abec.parent.mkdir(parents=True, exist_ok=True)
            target_abec.write_text("[ABEC]\n", encoding="utf-8")
            stale_time = int(time.time()) - 3600
            os.utime(target_abec, (stale_time, stale_time))
            min_mtime_ns = int(time.time_ns()) - 1_000_000
            result = _sync_generated_abec(
                target_abec=target_abec,
                search_roots=(target_abec.parent,),
                logs_dir=target_abec.parent,
                min_mtime_ns=min_mtime_ns,
            )
            self.assertFalse(bool(result.get("ok")))
            self.assertEqual(str(result.get("error") or ""), "generated_abec_missing")

    def test_sync_generated_abec_repairs_missing_mesh_reference_with_bem_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_dir = root / "ath_out" / "ABEC_FreeStanding"
            source_dir.mkdir(parents=True, exist_ok=True)
            source_abec = source_dir / "Project.abec"
            source_abec.write_text(
                "\n".join(
                    [
                        "[Project]",
                        "Scriptname_InfoFile=",
                        "[Solving]",
                        "Scriptname_Solving=solving.txt",
                        "[Observation]",
                        "C0=observation.txt",
                        "[MeshFiles]",
                        "C0=missing_mesh.msh,M1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (source_dir / "solving.txt").write_text("solve\n", encoding="utf-8")
            (source_dir / "observation.txt").write_text("observe\n", encoding="utf-8")
            (source_dir / "bem_mesh.msh").write_text("mesh\n", encoding="utf-8")

            target_abec = root / "project" / "versions" / "V001" / "abec" / "Project.abec"
            result = _sync_generated_abec(
                target_abec=target_abec,
                search_roots=[root / "ath_out"],
                logs_dir=root / "logs",
            )

            self.assertTrue(bool(result.get("ok")))
            self.assertEqual(list(result.get("sidecar_missing") or []), [])
            self.assertIn("missing_mesh.msh", list(result.get("mesh_fallback_repaired") or []))
            self.assertEqual(str(result.get("mesh_fallback_file") or ""), "bem_mesh.msh")
            text = target_abec.read_text(encoding="utf-8-sig")
            self.assertIn("C0=bem_mesh.msh,M1", text)
            self.assertTrue((target_abec.parent / "bem_mesh.msh").exists())

    def test_pipeline_marks_noop_when_no_versions_are_planned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            projects_root = Path(tmp_dir) / "projects"
            project_root = projects_root / "P001"
            project_root.mkdir(parents=True, exist_ok=True)
            project = Project(
                project_id="P001",
                name="Runtime Noop Plan Test",
                root_path=str(project_root),
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
            planning_summary = SimpleNamespace(project_root=str(project_root), version_ids=[])
            with patch("app.runtime_orchestrator.materialize_batch_plan", return_value=planning_summary):
                summary = run_batch_pipeline(
                    project=project,
                    batch=batch,
                    projects_root=projects_root,
                    continue_on_error=True,
                    dry_run=True,
                )

            self.assertEqual(summary.run_status, "noop")
            self.assertEqual(list(summary.versions), [])
            self.assertEqual(list(summary.stage_results), [])
            with closing(sqlite3.connect(str(_project_db_path(project_root)))) as conn:
                row = conn.execute(
                    "SELECT status, error_summary FROM runs ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(str(row[0]), "noop")
            self.assertIn("no_planned_versions", str(row[1] or ""))


if __name__ == "__main__":
    unittest.main()
