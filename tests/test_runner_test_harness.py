from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.runner_test_db import RunnerTestDb
from app.runner_test_harness import (
    _assess_pre_akabak_le_driving_contract,
    _collect_validation_metrics,
    _diagnose_radimp,
    _patch_cfg_le_profile,
    _patch_observation_radimp_profile,
    _parse_abec_mesh_requirements,
    _resolve_meshcmd_rhs,
    _split_meshcmd_rhs,
    run_runner_test_le_proof_matrix,
    run_runner_test_radimp_3scope_matrix,
    run_runner_test_radimp_driving_matrix,
    run_runner_test_harness,
    run_runner_test_import_start_apply_only,
    run_runner_test_le_repair_import_only,
    run_runner_test_open_dialog_only,
)
from app.vacs_txt_parser import VacsGraph, VacsSeries, VacsSeriesPoint


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
    def test_repository_smoke_case_pins_stable_le_repair_profile(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        payload = json.loads((repo_root / "runner_test_cases" / "smoke_fast.json").read_text(encoding="utf-8"))

        self.assertEqual(
            payload.get("le_repair_profile"),
            "driver_drvgroup_def_driving_resistor",
        )

    def test_assess_pre_akabak_le_driving_contract_detects_expected_drvgroup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            solving = root / "solving.txt"
            observation = root / "observation.txt"
            le_script = root / "generic25.txt"
            abec.write_text(
                "[Project]\nScriptname_Solving=solving.txt\n[Observation]\nC0=observation.txt\n"
                "[LEScript]\nScriptname_LEScript=generic25.txt\n",
                encoding="utf-8",
            )
            solving.write_text("Driving \"S1001\"\n  RefElements=\"A\"; DrvGroup=1001;\n", encoding="utf-8")
            le_script.write_text(
                "Def_Driving \"Voltage source\" Value=1V IsRms\n"
                "System 'S1'\n  Resistor 'Rg' Node=1=2 R=1ohm\n"
                "  Driver 'D1' Def='Drv1' Node=2=0=10=20 DrvGroup=1001\n",
                encoding="utf-8",
            )
            observation.write_text(
                "Driving_Values\n  DrvType=Acceleration; Value=1.0\n  401 DrvGroup=1001 Weight=1\n\n"
                "Radiation_Impedance\n  RadImpType=Normalized\n  402 1001 1001 ID=8001\n",
                encoding="utf-8",
            )
            result = _assess_pre_akabak_le_driving_contract(abec_path=abec, expected_drvgroup="1001")
            self.assertTrue(result["ok"])
            self.assertIn("1001", result["solving_drvgroups"])
            self.assertEqual(result["le_driver_drvgroups"], ["1001"])
            self.assertTrue(result["le_has_def_driving"])
            self.assertTrue(result["le_has_resistor"])

    def test_assess_pre_akabak_le_driving_contract_rejects_radimp_only_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            abec.write_text(
                "[Project]\nScriptname_Solving=solving.txt\n[Observation]\nC0=observation.txt\n"
                "[LEScript]\nScriptname_LEScript=generic25.txt\n",
                encoding="utf-8",
            )
            (root / "solving.txt").write_text("Driving 'S1001' DrvGroup=1001\n", encoding="utf-8")
            (root / "observation.txt").write_text(
                "Driving_Values\n  401 DrvGroup=1001 Weight=1\n"
                "Radiation_Impedance\n  402 1001 1001 ID=8001\n",
                encoding="utf-8",
            )
            (root / "generic25.txt").write_text(
                "System 'S1'\n  Driver 'D1' Def='Drv1' Node=1=0=10=20\n"
                "  RadImp 'Throat' Node=20 DrvGroup=1001\n",
                encoding="utf-8",
            )

            result = _assess_pre_akabak_le_driving_contract(abec_path=abec, expected_drvgroup="1001")

            self.assertFalse(result["ok"])
            self.assertIn("expected_drvgroup_missing_on_le_driver", result["violations"])
            self.assertEqual(result["le_driver_drvgroups"], [])

    def test_assess_pre_akabak_le_driving_contract_flags_missing_radimp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            solving = root / "solving.txt"
            observation = root / "observation.txt"
            abec.write_text(
                "[Project]\nScriptname_Solving=solving.txt\n[Observation]\nC0=observation.txt\n",
                encoding="utf-8",
            )
            solving.write_text("Driving \"S1001\"\n  RefElements=\"A\"; DrvGroup=1001;\n", encoding="utf-8")
            observation.write_text(
                "Driving_Values\n  DrvType=Acceleration; Value=1.0\n  401 DrvGroup=1001 Weight=1\n",
                encoding="utf-8",
            )
            result = _assess_pre_akabak_le_driving_contract(abec_path=abec, expected_drvgroup="1001")
            self.assertFalse(result["ok"])
            self.assertIn("radimp_section_missing", result["violations"])

    def test_patch_cfg_le_profile_updates_le_voltage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cfg = root / "input.cfg"
            cfg.write_text("ABEC.AkabakMode = 1\nLE = generic25\nLE.Voltage = 1.0\n", encoding="utf-8")
            result = _patch_cfg_le_profile(cfg_path=cfg, profile="le_voltage_2p83")
            self.assertTrue(result.ok)
            self.assertTrue(result.changed)
            self.assertEqual(result.target_le_voltage, 2.83)
            patched = cfg.read_text(encoding="utf-8")
            self.assertIn("LE.Voltage = 2.83", patched)

    def test_patch_observation_radimp_profile_force_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            obs = root / "observation.txt"
            abec.write_text("[Observation]\nC0=observation.txt\n", encoding="utf-8")
            obs.write_text(
                "Radiation_Impedance\n"
                "  BodeType=Complex; GraphHeader=\"RadImp\"\n"
                "  Range_min=0; Range_max=2; RadImpType=Normalized\n"
                "  402 1001 1001 ID=8001\n",
                encoding="utf-8",
            )
            result = _patch_observation_radimp_profile(abec_path=abec, profile="force_absolute")
            self.assertTrue(result.ok)
            patched = obs.read_text(encoding="utf-8")
            self.assertIn("RadImpType=Absolute", patched)

    def test_patch_observation_radimp_profile_drop_radimptype(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            obs = root / "observation.txt"
            abec.write_text("[Observation]\nC0=observation.txt\n", encoding="utf-8")
            obs.write_text(
                "Radiation_Impedance\n"
                "  BodeType=Complex; GraphHeader=\"RadImp\"\n"
                "  Range_min=0; Range_max=2; RadImpType=Normalized\n"
                "  402 1001 1001 ID=8001\n",
                encoding="utf-8",
            )
            result = _patch_observation_radimp_profile(abec_path=abec, profile="drop_radimptype")
            self.assertTrue(result.ok)
            patched = obs.read_text(encoding="utf-8")
            self.assertNotIn("RadImpType=", patched)

    def test_patch_observation_profile_adds_idempotent_le_electrical_impedance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            obs = root / "observation.txt"
            abec.write_text("[Observation]\nC0=observation.txt\n", encoding="utf-8")
            obs.write_text(
                "Radiation_Impedance\n"
                "  RadImpType=Normalized\n"
                "  402 1001 1001 ID=8001\n",
                encoding="utf-8",
            )

            first = _patch_observation_radimp_profile(abec_path=abec, profile="le_electrical_impedance")
            second = _patch_observation_radimp_profile(abec_path=abec, profile="le_electrical_impedance")

            self.assertTrue(first.ok)
            self.assertEqual(first.status, "patched")
            self.assertEqual(second.status, "already_conformant")
            patched = obs.read_text(encoding="utf-8")
            self.assertEqual(patched.count("LE_Spectrum"), 1)
            self.assertIn("System='S1'; AnalysisType=Impedance", patched)
            self.assertIn("GraphHeader='DrvImp'; BodeType=Ampl_Phase; ID=2002", patched)

    def test_patch_observation_driving_profile_updates_drvtype_and_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            obs = root / "observation.txt"
            abec.write_text("[Observation]\nC0=observation.txt\n", encoding="utf-8")
            obs.write_text(
                "Driving_Values\n"
                "  DrvType=Acceleration; Value=1.0\n"
                "  401  DrvGroup=1001  Weight=1 Delay=0ms\n",
                encoding="utf-8",
            )
            from app.runner_test_harness import _patch_observation_driving_profile

            result = _patch_observation_driving_profile(abec_path=abec, profile="accel_2p83")
            self.assertTrue(result.ok)
            patched = obs.read_text(encoding="utf-8")
            self.assertIn("DrvType=Acceleration; Value=2.83", patched)

            result2 = _patch_observation_driving_profile(abec_path=abec, profile="velocity_1")
            self.assertTrue(result2.ok)
            patched2 = obs.read_text(encoding="utf-8")
            self.assertIn("DrvType=Velocity; Value=1.0", patched2)

    def test_collect_validation_metrics_accepts_normalized_radimp_zero_baseline(self) -> None:
        parsed = VacsGraph(
            graph_type="impedance",
            x_name="f",
            y_name="z",
            x_unit="Hz",
            y_unit="",
            series=[
                VacsSeries(
                    series_kind="curve",
                    angle_deg=None,
                    label="default",
                    points=[
                        VacsSeriesPoint(x_value=1000.0, y_value=0.0, y_imag=0.0),
                        VacsSeriesPoint(x_value=2000.0, y_value=0.0, y_imag=0.0),
                    ],
                    meta={},
                )
            ],
            export_meta={
                "metadata": {
                    "Data_LevelType": "Impedance10",
                    "Data_Legend": "Radiation_Impedance #5; ; Normalized",
                }
            },
        )
        validation = _collect_validation_metrics(parsed=parsed, expected_kind="impedance", file_size_bytes=512)
        self.assertEqual(validation["status"], "ok")
        self.assertTrue(validation["metrics"]["all_zero_allowed"])

    def test_diagnose_radimp_normalized_zero_baseline_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            obs = root / "observation.txt"
            abec.write_text("[Observation]\nC0=observation.txt\n", encoding="utf-8")
            obs.write_text(
                "Radiation_Impedance\n"
                "  RadImpType=Normalized\n"
                "  101 1001 1001 ID=101\n",
                encoding="utf-8",
            )
            diagnosis = _diagnose_radimp(
                abec_path=abec,
                export_diagnostics=[
                    {
                        "expected_kind": "impedance",
                        "parsed_graph_type": "impedance",
                        "series_count": 1,
                        "all_zero_series": 1,
                        "all_zero_allowed": True,
                        "graph_kind_match": True,
                    }
                ],
                watchdog_events=[],
            )
            self.assertEqual(diagnosis["status"], "ok")
            self.assertEqual(diagnosis["classification"], "radimp_normalized_zero_baseline")

    def test_diagnose_radimp_wrong_graph_exported_when_radimp_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            obs = root / "observation.txt"
            abec.write_text("[Observation]\nC0=observation.txt\n", encoding="utf-8")
            obs.write_text(
                "Radiation_Impedance\n"
                "  RadImpType=Absolute\n"
                "  101 1001 1001 ID=101\n",
                encoding="utf-8",
            )
            diagnosis = _diagnose_radimp(
                abec_path=abec,
                export_diagnostics=[
                    {
                        "expected_kind": "spl",
                        "parsed_graph_type": "spl",
                        "series_count": 1,
                        "all_zero_series": 0,
                        "all_zero_allowed": False,
                        "graph_kind_match": True,
                    }
                ],
                watchdog_events=[],
                expected_export_kinds=["impedance"],
            )
            self.assertEqual(diagnosis["status"], "failed")
            self.assertEqual(diagnosis["classification"], "wrong_graph_exported")

    def test_diagnose_radimp_all_zero_unclassified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            obs = root / "observation.txt"
            abec.write_text("[Observation]\nC0=observation.txt\n", encoding="utf-8")
            obs.write_text(
                "Radiation_Impedance\n"
                "  RadImpType=Absolute\n"
                "  101 1001 1001 ID=101\n",
                encoding="utf-8",
            )
            diagnosis = _diagnose_radimp(
                abec_path=abec,
                export_diagnostics=[
                    {
                        "expected_kind": "impedance",
                        "parsed_graph_type": "impedance",
                        "series_count": 1,
                        "all_zero_series": 1,
                        "all_zero_allowed": False,
                        "graph_kind_match": True,
                    }
                ],
                watchdog_events=[],
                expected_export_kinds=["impedance"],
            )
            self.assertEqual(diagnosis["status"], "failed")
            self.assertEqual(diagnosis["classification"], "radimp_all_zero_unclassified")

    def test_diagnose_radimp_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec = root / "Project.abec"
            obs = root / "observation.txt"
            abec.write_text("[Observation]\nC0=observation.txt\n", encoding="utf-8")
            obs.write_text(
                "Radiation_Impedance\n"
                "  RadImpType=Absolute\n"
                "  101 1001 1001 ID=101\n",
                encoding="utf-8",
            )
            diagnosis = _diagnose_radimp(
                abec_path=abec,
                export_diagnostics=[
                    {
                        "expected_kind": "impedance",
                        "parsed_graph_type": "impedance",
                        "series_count": 1,
                        "all_zero_series": 0,
                        "all_zero_allowed": False,
                        "graph_kind_match": True,
                    }
                ],
                watchdog_events=[],
                expected_export_kinds=["impedance"],
            )
            self.assertEqual(diagnosis["status"], "ok")
            self.assertEqual(diagnosis["classification"], "radimp_nonzero")

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
            self.assertEqual(db.count_rows("validations"), 3)
            self.assertEqual(db.count_rows("versions"), 1)
            self.assertEqual(db.count_rows("run_versions"), 1)

    def test_resource_harness_exposes_20_minute_solve_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cases_root = root / "cases"
            workspace_root = root / "workspace"
            _write_case(cases_root / "smoke_fast.json")

            summary = run_runner_test_harness(
                case_id="smoke_fast",
                repeats=1,
                keep_exports=True,
                test_profile="resource",
                workspace_root=workspace_root,
                cases_root=cases_root,
                dry_run=True,
            )

            self.assertTrue(summary["ok"])
            self.assertEqual(summary["simulation_timeout_minutes"], 20)
            self.assertEqual(summary["akabak_solve_timeout_s"], 20 * 60)

    def test_radimp_driving_matrix_dry_run_executes_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cases_root = root / "cases"
            workspace_root = root / "workspace"
            _write_case(cases_root / "smoke_fast.json")

            summary = run_runner_test_radimp_driving_matrix(
                case_id="smoke_fast",
                driving_profiles=["default", "accel_2p83"],
                repeats_per_profile=1,
                keep_exports=True,
                test_profile="fast",
                workspace_root=workspace_root,
                cases_root=cases_root,
                dry_run=True,
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["phase"], "phase_radimp_driving_matrix")
            self.assertEqual(len(summary["results"]), 2)
            self.assertEqual(summary["results"][0]["driving_observation_profile"], "default")
            self.assertEqual(summary["results"][1]["driving_observation_profile"], "accel_2p83")

    def test_radimp_3scope_matrix_dry_run_executes_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cases_root = root / "cases"
            workspace_root = root / "workspace"
            _write_case(cases_root / "smoke_fast.json")

            summary = run_runner_test_radimp_3scope_matrix(
                case_id="smoke_fast",
                cfg_profiles=["default", "le_voltage_2p83"],
                radimp_profiles=["default"],
                driving_profiles=["default", "accel_2p83"],
                repeats_per_combo=1,
                keep_exports=True,
                test_profile="fast",
                workspace_root=workspace_root,
                cases_root=cases_root,
                dry_run=True,
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["phase"], "phase_radimp_3scope_matrix")
            self.assertEqual(len(summary["results"]), 4)
            self.assertTrue(summary["randomize_order"])
            self.assertEqual(summary["random_seed"], 1337)

    def test_le_proof_matrix_dry_run_executes_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cases_root = root / "cases"
            workspace_root = root / "workspace"
            _write_case(cases_root / "smoke_fast.json")

            summary = run_runner_test_le_proof_matrix(
                case_id="smoke_fast",
                profiles=["control", "mut_electrical"],
                repeats_per_profile=2,
                keep_exports=True,
                test_profile="fast",
                workspace_root=workspace_root,
                cases_root=cases_root,
                random_seed=20260216,
                dry_run=True,
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["phase"], "phase_le_proof_matrix")
            self.assertEqual(summary["le_integration_diagnosis"], "le_active_inconclusive")
            self.assertEqual(len(summary["results"]), 4)
            self.assertEqual(summary["random_seed"], 20260216)

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

    def test_resolve_meshcmd_rhs_normalizes_bare_gmsh_from_ath_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ath_exe = root / "ath.exe"
            gmsh_exe = root / "gmsh.exe"
            ath_cfg = root / "ath.cfg"
            ath_exe.write_text("", encoding="utf-8")
            gmsh_exe.write_text("", encoding="utf-8")
            ath_cfg.write_text(f'MeshCmd = "{gmsh_exe}"\n', encoding="utf-8")

            meshcmd = _resolve_meshcmd_rhs(
                ath_executable=ath_exe,
                meshcmd_override=None,
            )

            self.assertEqual(meshcmd["source"], "ath_cfg")
            self.assertTrue(bool(meshcmd["meshcmd_executable_exists"]))
            self.assertTrue(bool(meshcmd["meshcmd_rhs_normalized"]))
            self.assertEqual(str(meshcmd["meshcmd_rhs_normalization_reason"]), "append_placeholder_for_gmsh")
            self.assertIn("%f -", str(meshcmd["meshcmd_rhs"]))

    def test_resolve_meshcmd_rhs_normalizes_bare_gmsh_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            gmsh_exe = root / "gmsh.exe"
            gmsh_exe.write_text("", encoding="utf-8")

            meshcmd = _resolve_meshcmd_rhs(
                ath_executable=None,
                meshcmd_override=str(gmsh_exe),
            )

            self.assertEqual(meshcmd["source"], "override")
            self.assertTrue(bool(meshcmd["meshcmd_executable_exists"]))
            self.assertTrue(bool(meshcmd["meshcmd_rhs_normalized"]))
            self.assertEqual(str(meshcmd["meshcmd_rhs_normalization_reason"]), "append_placeholder_for_gmsh")
            self.assertIn("%f -", str(meshcmd["meshcmd_rhs"]))

    def test_resolve_meshcmd_rhs_prefers_gmsh_next_to_ath(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ath_exe = root / "ath.exe"
            gmsh_exe = root / "gmsh.exe"
            ath_exe.write_text("", encoding="utf-8")
            gmsh_exe.write_text("", encoding="utf-8")

            meshcmd = _resolve_meshcmd_rhs(ath_executable=ath_exe, meshcmd_override=None)

            self.assertEqual(meshcmd["source"], "ath_sibling")
            self.assertEqual(Path(str(meshcmd["meshcmd_executable"])), gmsh_exe)
            self.assertIn("%f -", str(meshcmd["meshcmd_rhs"]))

    def test_split_meshcmd_rhs_preserves_quoted_program_files_path(self) -> None:
        executable, normalized = _split_meshcmd_rhs('"C:\\Program Files\\gmsh\\gmsh.exe %f -"')
        self.assertEqual(executable, r"C:\Program Files\gmsh\gmsh.exe")
        self.assertEqual(normalized, r"C:\Program Files\gmsh\gmsh.exe %f -")

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

    def test_import_start_apply_only_dry_run_writes_db_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace_root = root / "workspace"
            abec_path = root / "sample.abec"
            abec_path.write_text("ABEC_SAMPLE\n", encoding="utf-8")

            summary = run_runner_test_import_start_apply_only(
                akabak_executable=root / "akabak.exe",
                abec_path=abec_path,
                repeats=1,
                workspace_root=workspace_root,
                dry_run=True,
            )
            self.assertTrue(summary["ok"])
            self.assertTrue(summary["dry_run"])
            self.assertEqual(summary["phase"], "phase_import_start_apply_only")
            self.assertEqual(summary["mode"], "import_start_apply_only")
            self.assertEqual(len(summary["runs"]), 1)
            self.assertEqual(summary["runs"][0]["status"], "dry_run_completed")

            db = RunnerTestDb(Path(summary["db_path"]))
            self.assertEqual(db.count_rows("test_runs"), 1)
            self.assertEqual(db.count_rows("test_run_steps"), 3)
            self.assertEqual(db.count_rows("artifacts"), 1)
            self.assertEqual(db.count_rows("validations"), 1)
            self.assertEqual(db.count_rows("versions"), 1)
            self.assertEqual(db.count_rows("run_versions"), 1)

    def test_le_repair_import_only_dry_run_writes_db_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace_root = root / "workspace"
            abec_path = root / "sample.abec"
            abec_path.write_text("ABEC_SAMPLE\n", encoding="utf-8")

            summary = run_runner_test_le_repair_import_only(
                akabak_executable=root / "akabak.exe",
                abec_path=abec_path,
                repeats=1,
                workspace_root=workspace_root,
                dry_run=True,
            )
            self.assertTrue(summary["ok"])
            self.assertTrue(summary["dry_run"])
            self.assertEqual(summary["phase"], "phase_le_repair_import_only")
            self.assertEqual(summary["mode"], "le_repair_import_only")
            self.assertEqual(len(summary["runs"]), 1)
            self.assertEqual(summary["runs"][0]["status"], "dry_run_completed")

            db = RunnerTestDb(Path(summary["db_path"]))
            self.assertEqual(db.count_rows("test_runs"), 1)
            self.assertEqual(db.count_rows("test_run_steps"), 3)
            self.assertEqual(db.count_rows("artifacts"), 0)
            self.assertEqual(db.count_rows("validations"), 0)
            self.assertEqual(db.count_rows("versions"), 1)
            self.assertEqual(db.count_rows("run_versions"), 1)


if __name__ == "__main__":
    unittest.main()
