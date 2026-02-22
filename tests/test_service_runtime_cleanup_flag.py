from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings


class ServiceRuntimeCleanupFlagTests(unittest.TestCase):
    def test_run_batch_forwards_runtime_cleanup_flag_from_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "projects"
            settings_path = Path(tmp_dir) / "settings.json"
            store = SettingsStore(settings_path)
            store.save(
                UserSettings(
                    library_root=str(library_root),
                    runtime_cleanup_enabled=False,
                )
            )
            service = OrchestratorService(settings_store=store)
            project = service.create_project("Cleanup toggle project", {"fixed_params": {"Length": 100}, "limits": {}})
            batch_summary = service.create_batch(
                project_id=project.project_id,
                batch_name="Cleanup toggle batch",
                selected_params={"Throat.Diameter": 30.0},
                sweeps={},
                sweep_mode="single",
                sim_export_params={},
            )
            expected_summary = object()
            with patch("app.services.run_batch_pipeline", return_value=expected_summary) as pipeline_mock:
                result = service.run_batch(
                    project.project_id,
                    batch_summary.batch_id,
                    continue_on_error=True,
                    dry_run=True,
                )

            self.assertIs(result, expected_summary)
            self.assertEqual(bool(pipeline_mock.call_args.kwargs.get("runtime_cleanup_enabled", True)), False)


if __name__ == "__main__":
    unittest.main()
