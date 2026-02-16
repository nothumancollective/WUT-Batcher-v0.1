from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings
from app.tidy_dataset import TidyDatasetWriter


class EtaEstimatorTests(unittest.TestCase):
    def test_estimate_batch_runtime_uses_median_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "projects"
            settings_path = Path(tmp_dir) / "settings.json"
            store = SettingsStore(settings_path)
            store.save(UserSettings(library_root=str(library_root)))
            service = OrchestratorService(settings_store=store)

            project = service.create_project("ETA Test", {"fixed_params": {"Length": 200}, "limits": {}})
            batch = service.create_batch(
                project_id=project.project_id,
                batch_name="B ETA",
                selected_params={},
                sweeps={"Throat.Diameter": {"start": 20, "end": 30, "steps": 3}},
                sweep_mode="single",
                sim_export_params={},
            )
            version_id = str(batch.version_ids[0])
            paths = service.repo.project_paths(project.project_id, ensure=True)
            dataset = TidyDatasetWriter(paths.project_dir, library_root=str(library_root))

            for index, duration in enumerate((10.0, 30.0, 50.0), start=1):
                run_id = f"R{index:03d}"
                dataset.create_run(
                    run_id=run_id,
                    project_id=project.project_id,
                    batch_id=batch.batch_id,
                    status="succeeded",
                )
                dataset.write_run_versions(
                    [
                        {
                            "run_id": run_id,
                            "version_id": version_id,
                            "project_id": project.project_id,
                            "batch_id": batch.batch_id,
                            "status": "success",
                            "duration_seconds": duration,
                        }
                    ]
                )

            estimate = service.estimate_batch_runtime(
                project_id=project.project_id,
                selected_params={},
                sweeps={"Throat.Diameter": {"start": 20, "end": 30, "steps": 3}},
                sweep_mode="single",
            )
            self.assertEqual(int(estimate.get("sample_count", -1)), 3)
            self.assertEqual(float(estimate.get("median_seconds_per_version", -1.0)), 30.0)
            self.assertEqual(int(estimate.get("version_count_preview", -1)), 3)
            self.assertEqual(float(estimate.get("eta_seconds", -1.0)), 90.0)


if __name__ == "__main__":
    unittest.main()
