from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings


class ServiceExportTests(unittest.TestCase):
    def test_export_uses_sql_params_and_omits_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "projects"
            template_cfg = Path(tmp_dir) / "template.cfg"
            template_cfg.write_text(
                "Length = 80\nThroat.Diameter = 10\nCoverage.Angle = 90\n",
                encoding="utf-8",
            )

            settings_path = Path(tmp_dir) / "settings.json"
            store = SettingsStore(settings_path)
            store.save(
                UserSettings(
                    library_root=str(library_root),
                    template_cfg=str(template_cfg),
                )
            )
            service = OrchestratorService(settings_store=store)

            project = service.create_project("Export Test", {"fixed_params": {"Length": 120}, "limits": {}})
            summary = service.create_batch(
                project_id=project.project_id,
                batch_name="B Export",
                selected_params={"Throat.Diameter": 30.0, "Coverage.Angle": None},
                sweeps={},
                sweep_mode="single",
                sim_export_params={},
            )

            manifest = service.export_version(
                project_id=project.project_id,
                batch_id=summary.batch_id,
                version_id=summary.version_ids[0],
                export_stl=False,
                export_abec=False,
            )

            cfg_path = Path(manifest["cfg_path"])
            cfg_text = cfg_path.read_text(encoding="utf-8")
            self.assertIn("Throat.Diameter", cfg_text)
            self.assertNotIn("Coverage.Angle", cfg_text)
            self.assertIn("Coverage.Angle", manifest["unset_params"])

    def test_sync_global_db_returns_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "projects"
            settings_path = Path(tmp_dir) / "settings.json"
            store = SettingsStore(settings_path)
            store.save(UserSettings(library_root=str(library_root)))
            service = OrchestratorService(settings_store=store)
            service.create_project("Sync Test", {"fixed_params": {"Length": 100}, "limits": {}})
            summary = service.sync_global_db(max_items_per_project=10)
            self.assertIn("processed", summary)
            self.assertIn("synced", summary)
            self.assertIn("failed", summary)

    def test_run_batch_auto_uses_dry_run_when_tools_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "projects"
            settings_path = Path(tmp_dir) / "settings.json"
            store = SettingsStore(settings_path)
            store.save(UserSettings(library_root=str(library_root)))
            service = OrchestratorService(settings_store=store)
            project = service.create_project("Dry run project", {"fixed_params": {"Length": 100}, "limits": {}})
            batch_summary = service.create_batch(
                project_id=project.project_id,
                batch_name="Dry run batch",
                selected_params={"Throat.Diameter": 30.0},
                sweeps={},
                sweep_mode="single",
                sim_export_params={},
            )
            summary = service.run_batch(project.project_id, batch_summary.batch_id, continue_on_error=True)
            self.assertTrue(summary.dry_run)


if __name__ == "__main__":
    unittest.main()
