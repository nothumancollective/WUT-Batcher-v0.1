from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from app.analyzer.presets import ALGO_VERSION
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings
from app.tidy_dataset import TidyDatasetWriter


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _build_service(tmp_root: Path) -> OrchestratorService:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / "library"
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store)


def _build_points(freqs: list[float], angles: list[float], bw_deg: float) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    half = max(float(bw_deg) * 0.5, 1.0)
    for f_idx, freq in enumerate(freqs):
        for a_idx, angle in enumerate(angles):
            attenuation_db = min((abs(angle) / half) * 6.0, 30.0)
            db = -attenuation_db
            magnitude = 10.0 ** (db / 20.0)
            rows.append(
                {
                    "freq_index": int(f_idx),
                    "angle_index": int(a_idx),
                    "freq_hz": float(freq),
                    "angle_deg": float(angle),
                    "re": float(magnitude),
                    "im": 0.0,
                }
            )
    return rows


def _write_synthetic_run(
    *,
    dataset: TidyDatasetWriter,
    project_id: str,
    batch_id: str,
    run_id: str,
    version_id: str,
    hash_seed: str,
) -> None:
    freqs = [200.0, 400.0, 800.0, 1600.0]
    angles = [-90.0, -60.0, -45.0, -30.0, -15.0, 0.0, 15.0, 30.0, 45.0, 60.0, 90.0]
    points = _build_points(freqs=freqs, angles=angles, bw_deg=60.0)
    for orientation in ("H", "V"):
        measurement = {
            "project_id": str(project_id),
            "batch_id": str(batch_id),
            "version_id": str(version_id),
            "run_id": str(run_id),
            "graph_id": None,
            "orientation": orientation,
            "orientation_raw": 0.0,
            "norm_angle_deg": 0.0,
            "data_level_type": "SPL",
            "data_base_unit": "dB",
            "data_absc_unit": "Hz",
            "freq_min_hz": min(freqs),
            "freq_max_hz": max(freqs),
            "freq_count": len(freqs),
            "angle_min_deg": min(angles),
            "angle_max_deg": max(angles),
            "angle_step_deg": 15.0,
            "angle_count": len(angles),
            "angles_deg_json": json.dumps(angles),
            "source_file": f"{run_id}_{version_id}_{orientation}.txt",
            "file_hash": f"{hash_seed}_{orientation}",
            "export_meta_json": json.dumps({"fixture": True}),
            "created_at": _now_iso(),
        }
        dataset.write_polar_measurement(measurement=measurement, points=points)


class AnalyzerKpiServiceTests(unittest.TestCase):
    def test_compute_and_cache_skip_logic_for_batch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_kpi_service_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Analyzer KPI", {})
            paths = service.repo.project_paths(project.project_id, ensure=True)
            dataset = TidyDatasetWriter(paths.project_dir, library_root=service.settings.library_root)

            _write_synthetic_run(
                dataset=dataset,
                project_id=project.project_id,
                batch_id="B001",
                run_id="R001",
                version_id="V001",
                hash_seed="hash_run_1",
            )
            _write_synthetic_run(
                dataset=dataset,
                project_id=project.project_id,
                batch_id="B001",
                run_id="R002",
                version_id="V002",
                hash_seed="hash_run_2",
            )

            summary_1 = service.analyzer_compute_batch_kpis(
                project_id=project.project_id,
                batch_id="B001",
                target_h_deg=60.0,
                target_v_deg=60.0,
                tol_deg=5.0,
                band_low_hz=200.0,
                band_high_hz=1600.0,
                stage_mode="shaping",
                algo_version=ALGO_VERSION,
            )
            self.assertEqual(int(summary_1.get("computed") or 0), 2)
            self.assertEqual(int(summary_1.get("skipped_cached") or 0), 0)
            self.assertFalse(bool(summary_1.get("canceled")))

            summary_2 = service.analyzer_compute_batch_kpis(
                project_id=project.project_id,
                batch_id="B001",
                target_h_deg=60.0,
                target_v_deg=60.0,
                tol_deg=5.0,
                band_low_hz=200.0,
                band_high_hz=1600.0,
                stage_mode="shaping",
                algo_version=ALGO_VERSION,
            )
            self.assertEqual(int(summary_2.get("computed") or 0), 0)
            self.assertEqual(int(summary_2.get("skipped_cached") or 0), 2)

            rows = service.analyzer_list_batch_review_runs(
                project_id=project.project_id,
                batch_id="B001",
                source="project",
                stage_mode="shaping",
                band_low_hz=200.0,
                band_high_hz=1600.0,
                target_h_deg=60.0,
                target_v_deg=60.0,
                tol_deg=5.0,
                algo_version=ALGO_VERSION,
            )
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row.get("kpi_score") is not None for row in rows))

            summary_3 = service.analyzer_compute_batch_kpis(
                project_id=project.project_id,
                batch_id="B001",
                target_h_deg=60.0,
                target_v_deg=60.0,
                tol_deg=5.0,
                band_low_hz=200.0,
                band_high_hz=1600.0,
                stage_mode="shaping",
                algo_version=f"{ALGO_VERSION}-bump",
            )
            self.assertEqual(int(summary_3.get("computed") or 0), 2)

    def test_presets_include_200hz_default_scoring_band(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_kpi_presets_") as tmp:
            service = _build_service(Path(tmp))
            presets = service.analyzer_presets()
            default_band_id = str(presets.get("default_band_preset_id") or "")
            bands = list(presets.get("band_presets", []) or [])
            by_id = {str(item.get("id")): item for item in bands if isinstance(item, dict)}
            self.assertIn(default_band_id, by_id)
            default_band = dict(by_id[default_band_id])
            self.assertGreaterEqual(float(default_band.get("low_hz") or 0.0), 200.0)


if __name__ == "__main__":
    unittest.main()

