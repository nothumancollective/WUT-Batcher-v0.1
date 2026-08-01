from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest

from app.analyzer.presets import ALGO_VERSION
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings
from app.tidy_dataset import TidyDatasetWriter


def _build_service(tmp_root: Path) -> OrchestratorService:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / "library"
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store)


def _source_hash(values: list[str]) -> str:
    raw = "|".join(sorted({str(item).strip() for item in values if str(item).strip()})) or "<missing>"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _iso_at(offset_seconds: int) -> str:
    base = datetime(2026, 2, 22, 10, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=int(offset_seconds))).replace(microsecond=0).isoformat()


def _write_run_with_cached_kpi(
    *,
    dataset: TidyDatasetWriter,
    project_id: str,
    batch_id: str,
    run_id: str,
    version_id: str,
    file_hash: str,
    created_at: str,
    aggregate: dict,
    data_level_type: str = "SPL",
) -> None:
    measurement = {
        "project_id": project_id,
        "batch_id": batch_id,
        "version_id": version_id,
        "run_id": run_id,
        "graph_id": None,
        "orientation": "H",
        "orientation_raw": 0.0,
        "norm_angle_deg": 0.0,
        "data_level_type": data_level_type,
        "data_base_unit": "dB",
        "data_absc_unit": "Hz",
        "freq_min_hz": 200.0,
        "freq_max_hz": 800.0,
        "freq_count": 3,
        "angle_min_deg": -30.0,
        "angle_max_deg": 30.0,
        "angle_step_deg": 30.0,
        "angle_count": 3,
        "angles_deg_json": json.dumps([-30.0, 0.0, 30.0]),
        "source_file": f"{run_id}_{version_id}_H.txt",
        "file_hash": file_hash,
        "export_meta_json": json.dumps({"fixture": True}),
        "created_at": created_at,
    }
    points = [
        {"freq_index": 0, "angle_index": 0, "freq_hz": 200.0, "angle_deg": -30.0, "re": 0.7, "im": 0.0},
        {"freq_index": 0, "angle_index": 1, "freq_hz": 200.0, "angle_deg": 0.0, "re": 1.0, "im": 0.0},
        {"freq_index": 0, "angle_index": 2, "freq_hz": 200.0, "angle_deg": 30.0, "re": 0.7, "im": 0.0},
    ]
    dataset.write_polar_measurement(measurement=measurement, points=points)
    kpi_payload = {
        "aggregate": dict(aggregate),
        "flags": {
            "jump": {"count": int(aggregate.get("flags_count") or 0)},
            "collapse": {"count": 0},
        },
    }
    dataset.write_analyzer_run_kpis(
        [
            {
                "project_id": project_id,
                "batch_id": batch_id,
                "run_id": run_id,
                "version_id": version_id,
                "stage_mode": "concept",
                "band_low_hz": 200.0,
                "band_high_hz": 800.0,
                "target_h_deg": 60.0,
                "target_v_deg": 60.0,
                "tol_deg": 5.0,
                "kpi_json": json.dumps(kpi_payload, ensure_ascii=False, sort_keys=True),
                "flags_json": json.dumps(kpi_payload.get("flags", {}), ensure_ascii=False, sort_keys=True),
                "score": float(aggregate.get("score_hint") or 0.0),
                "algo_version": ALGO_VERSION,
                "source_hash": _source_hash([file_hash]),
                "computed_at": created_at,
            }
        ]
    )


class AnalyzerServicesAnalysesTests(unittest.TestCase):
    def test_normalized_peak_polars_are_visible_through_analyzer_service_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_analyzer_peak_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Analyzer Peak", {})
            paths = service.repo.project_paths(project.project_id, ensure=True)
            dataset = TidyDatasetWriter(paths.project_dir, library_root=service.settings.library_root)
            _write_run_with_cached_kpi(
                dataset=dataset,
                project_id=project.project_id,
                batch_id="B001",
                run_id="R001",
                version_id="V001",
                file_hash="hash_peak",
                created_at=_iso_at(5),
                aggregate={"flags_count": 0, "score_hint": 75.0},
                data_level_type="Peak",
            )

            projects = service.analyzer_list_polar_projects(
                source="project",
                project_id=project.project_id,
            )
            batches = service.analyzer_list_polar_batches(
                project_id=project.project_id,
                source="project",
            )
            runs = service.analyzer_list_polar_runs(
                project_id=project.project_id,
                batch_id="B001",
                source="project",
            )

            self.assertEqual(projects[0]["measurement_count"], 1)
            self.assertEqual(batches[0]["batch_id"], "B001")
            self.assertEqual(batches[0]["measurement_count"], 1)
            self.assertEqual(runs[0]["run_id"], "R001")
            self.assertEqual(runs[0]["planes"], ["H"])

    def test_analyzer_ui_pref_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_analyzer_ui_pref_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Analyzer Prefs", {})
            service.analyzer_set_ui_pref(
                project_id=project.project_id,
                pref_key="ath_visible_params",
                payload={"visible_keys": ["Throat.Profile", "GCurve.Type"]},
            )
            loaded = service.analyzer_get_ui_pref(
                project_id=project.project_id,
                pref_key="ath_visible_params",
            )
            self.assertEqual(
                list(loaded.get("visible_keys", []) or []),
                ["Throat.Profile", "GCurve.Type"],
            )

    def test_version_note_roundtrip_is_exposed_in_analyzer_runs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_analyzer_note_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Analyzer Notes", {})
            paths = service.repo.project_paths(project.project_id, ensure=True)
            dataset = TidyDatasetWriter(paths.project_dir, library_root=service.settings.library_root)
            _write_run_with_cached_kpi(
                dataset=dataset,
                project_id=project.project_id,
                batch_id="B001",
                run_id="R001",
                version_id="V001",
                file_hash="hash_note",
                created_at=_iso_at(10),
                aggregate={
                    "b_pc_oct": 2.0,
                    "e_bw": 1.0,
                    "e_cov": 0.8,
                    "r_spill": 0.12,
                    "flags_count": 0,
                    "flagged": False,
                    "insufficient_coverage": False,
                    "score_hint": 75.0,
                },
            )
            service.analyzer_set_version_note(
                project_id=project.project_id,
                batch_id="B001",
                version_id="V001",
                note_text="candidate looks stable",
            )
            rows = service.analyzer_list_polar_runs(
                project_id=project.project_id,
                batch_id="B001",
                source="project",
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(str(rows[0].get("version_note") or ""), "candidate looks stable")

    def test_analyzer_runs_fall_back_to_run_version_ath_dimensions_when_scope_keys_mismatch(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="wut_analyzer_dims_fallback_"))
        try:
            service = _build_service(tmp)
            project = service.create_project("Analyzer Dim Fallback", {})
            paths = service.repo.project_paths(project.project_id, ensure=True)
            dataset = TidyDatasetWriter(paths.project_dir, library_root=service.settings.library_root)
            _write_run_with_cached_kpi(
                dataset=dataset,
                project_id=project.project_id,
                batch_id="B001",
                run_id="R001",
                version_id="V001",
                file_hash="hash_dims",
                created_at=_iso_at(11),
                aggregate={
                    "b_pc_oct": 1.2,
                    "e_bw": 0.7,
                    "e_cov": 0.6,
                    "r_spill": 0.08,
                    "flags_count": 0,
                    "flagged": False,
                    "insufficient_coverage": False,
                    "score_hint": 82.0,
                },
            )
            project_db = paths.dataset_dir / "project.sqlite"
            with sqlite3.connect(str(project_db)) as conn:
                conn.execute(
                    """
                    INSERT INTO ath_dimensions (
                        run_id, version_id, project_id, batch_id, length_mm, width_mm, height_mm, raw_line, source_file, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "R001",
                        "V001",
                        "LEGACY_PROJECT",
                        "LEGACY_BATCH",
                        320.5,
                        280.1,
                        140.0,
                        "",
                        "legacy_ath.txt",
                        _iso_at(12),
                    ),
                )
                conn.commit()

            rows = service.analyzer_list_polar_runs(
                project_id=project.project_id,
                batch_id="B001",
                source="project",
            )
            self.assertEqual(len(rows), 1)
            self.assertAlmostEqual(float(rows[0].get("ath_length_mm") or 0.0), 320.5, places=3)
            self.assertAlmostEqual(float(rows[0].get("ath_width_mm") or 0.0), 280.1, places=3)
            self.assertAlmostEqual(float(rows[0].get("ath_height_mm") or 0.0), 140.0, places=3)
            del dataset
        finally:
            for _ in range(6):
                try:
                    shutil.rmtree(tmp)
                    break
                except PermissionError:
                    time.sleep(0.2)
            else:
                shutil.rmtree(tmp, ignore_errors=True)

    def test_save_load_analysis_roundtrip_and_ordering(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_analyzer_analysis_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Analyzer Analysis", {})

            saved_1 = service.analyzer_save_analysis(
                project_id=project.project_id,
                name="First",
                config={"config_version": 1, "stage_mode": "concept"},
                candidates=[
                    {"batch_id": "B001", "run_id": "R001", "version_id": "V001"},
                    {"batch_id": "B002", "run_id": "R010", "version_id": "V010"},
                ],
            )
            time.sleep(1.1)
            saved_2 = service.analyzer_save_analysis(
                project_id=project.project_id,
                name="Second",
                config={"config_version": 1, "stage_mode": "stabilization"},
                candidates=[
                    {"batch_id": "B003", "run_id": "R020", "version_id": "V020"},
                ],
            )
            listed = service.analyzer_list_analyses(project_id=project.project_id)
            self.assertGreaterEqual(len(listed), 2)
            self.assertEqual(str(listed[0].get("analysis_id")), str(saved_2.get("analysis_id")))

            loaded = service.analyzer_load_analysis(
                project_id=project.project_id,
                analysis_id=str(saved_1.get("analysis_id")),
            )
            self.assertIsInstance(loaded, dict)
            assert isinstance(loaded, dict)
            self.assertEqual(str(loaded.get("name")), "First")
            config = dict(loaded.get("config") or {})
            self.assertEqual(int(config.get("config_version") or 0), 1)
            candidates = list(loaded.get("candidates", []) or [])
            self.assertEqual(len(candidates), 2)

    def test_autopick_strategies_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_analyzer_autopick_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Analyzer AutoPick", {})
            paths = service.repo.project_paths(project.project_id, ensure=True)
            dataset = TidyDatasetWriter(paths.project_dir, library_root=service.settings.library_root)

            _write_run_with_cached_kpi(
                dataset=dataset,
                project_id=project.project_id,
                batch_id="B001",
                run_id="R001",
                version_id="V001",
                file_hash="hash_001",
                created_at=_iso_at(1),
                aggregate={
                    "b_pc_oct": 2.8,
                    "e_bw": 1.1,
                    "e_cov": 0.7,
                    "r_spill": 0.10,
                    "flags_count": 0,
                    "flagged": False,
                    "insufficient_coverage": False,
                    "score_hint": 80.0,
                },
            )
            _write_run_with_cached_kpi(
                dataset=dataset,
                project_id=project.project_id,
                batch_id="B001",
                run_id="R002",
                version_id="V002",
                file_hash="hash_002",
                created_at=_iso_at(2),
                aggregate={
                    "b_pc_oct": 1.5,
                    "e_bw": 0.5,
                    "e_cov": 1.3,
                    "r_spill": 0.22,
                    "flags_count": 0,
                    "flagged": False,
                    "insufficient_coverage": False,
                    "score_hint": 70.0,
                },
            )
            _write_run_with_cached_kpi(
                dataset=dataset,
                project_id=project.project_id,
                batch_id="B002",
                run_id="R010",
                version_id="V010",
                file_hash="hash_010",
                created_at=_iso_at(3),
                aggregate={
                    "b_pc_oct": 2.2,
                    "e_bw": 0.8,
                    "e_cov": 0.9,
                    "r_spill": 0.18,
                    "flags_count": 2,
                    "flagged": True,
                    "insufficient_coverage": False,
                    "score_hint": 60.0,
                },
            )

            auto_a = service.analyzer_autopick_candidates(
                project_id=project.project_id,
                batch_ids=["B001", "B002"],
                strategy="A",
                kpi_key="score",
                filters={"exclude_flags": False},
                top_n=5,
                stage_mode="concept",
                band_low_hz=200.0,
                band_high_hz=800.0,
                target_h_deg=60.0,
                target_v_deg=60.0,
                tol_deg=5.0,
                algo_version=ALGO_VERSION,
            )
            candidates_a = list(auto_a.get("candidates", []) or [])
            self.assertGreaterEqual(len(candidates_a), 2)
            self.assertEqual(str(candidates_a[0].get("run_id")), "R001")

            auto_b = service.analyzer_autopick_candidates(
                project_id=project.project_id,
                batch_ids=["B001", "B002"],
                strategy="B",
                kpi_key="e_bw",
                filters={"exclude_flags": False},
                top_n=5,
                stage_mode="concept",
                band_low_hz=200.0,
                band_high_hz=800.0,
                target_h_deg=60.0,
                target_v_deg=60.0,
                tol_deg=5.0,
                algo_version=ALGO_VERSION,
            )
            candidates_b = list(auto_b.get("candidates", []) or [])
            self.assertGreaterEqual(len(candidates_b), 2)
            self.assertEqual(str(candidates_b[0].get("run_id")), "R002")

            auto_c = service.analyzer_autopick_candidates(
                project_id=project.project_id,
                batch_ids=["B001", "B002"],
                strategy="C",
                kpi_key="score",
                filters={"exclude_flags": True, "exclude_missing_kpi": True},
                top_n=5,
                stage_mode="concept",
                band_low_hz=200.0,
                band_high_hz=800.0,
                target_h_deg=60.0,
                target_v_deg=60.0,
                tol_deg=5.0,
                algo_version=ALGO_VERSION,
            )
            candidates_c = list(auto_c.get("candidates", []) or [])
            self.assertTrue(all(not bool(item.get("kpi_flagged")) for item in candidates_c))
            self.assertLessEqual(len(candidates_c), 5)


if __name__ == "__main__":
    unittest.main()
