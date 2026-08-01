from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings


def _service(tmp_path: Path) -> OrchestratorService:
    tools = tmp_path / "tools"
    ath = tools / "ath.exe"
    ath.parent.mkdir(parents=True)
    ath.write_bytes(b"fixture executable marker")
    driver = tools / "lib" / "drivers" / "generic25.txt"
    driver.parent.mkdir(parents=True)
    driver.write_text("System 'S1'\nDriver 'D1'\n", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    store.save(UserSettings(library_root=str(tmp_path / "library"), ath_exe=str(ath)))
    return OrchestratorService(store)


def test_service_geometry_batch_snapshot_and_dry_run_persistence(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create_project("Multi Geometry", {"fixed_params": {"Length": 120.0}, "limits": {}})
    first = service.list_geometries(project.project_id)[0]
    generic = service.list_drivers(kind="generic_test")[0]
    revision = generic["latest_revision"]
    service.set_geometry_default_driver(project.project_id, first["geometry_id"], revision["revision_id"])
    second = service.create_geometry(project.project_id, name="Mid Geometry", role="mid_horn")
    service.set_geometry_default_driver(project.project_id, second["geometry_id"], revision["revision_id"])

    first_batch = service.create_batch(
        project_id=project.project_id, geometry_id=first["geometry_id"], batch_name="HF Batch",
        selected_params={}, sweeps={}, sweep_mode="single", sim_export_params={},
    )
    second_batch = service.create_batch(
        project_id=project.project_id, geometry_id=second["geometry_id"], batch_name="Mid Batch",
        selected_params={}, sweeps={}, sweep_mode="single", sim_export_params={},
    )
    assert first_batch.batch_id != second_batch.batch_id
    loaded_first = service.repo.load_batch(project.project_id, first_batch.batch_id)
    loaded_second = service.repo.load_batch(project.project_id, second_batch.batch_id)
    assert loaded_first.geometry_id == first["geometry_id"]
    assert loaded_second.geometry_id == second["geometry_id"]
    assert loaded_first.driver_snapshot["snapshot_hash"]
    assert loaded_first.driver_snapshot["revision_hash"] == revision["revision_hash"]

    summary = service.run_batch(project.project_id, first_batch.batch_id, dry_run=True)
    assert summary.run_status == "succeeded"
    project_root = service.repo.project_paths(project.project_id).project_dir
    version = json.loads((project_root / "versions" / first_batch.version_ids[0] / "version.json").read_text(encoding="utf-8"))
    assert version["geometry_id"] == first["geometry_id"]
    assert version["driver_snapshot"]["snapshot_hash"] == loaded_first.driver_snapshot["snapshot_hash"]
    with sqlite3.connect(project_root / "db" / "project.sqlite") as conn:
        run_row = conn.execute("SELECT geometry_id FROM runs WHERE run_id=?", (summary.run_id,)).fetchone()
        snapshot_row = conn.execute(
            "SELECT geometry_id, revision_id, snapshot_hash, le_network_hash, staged_le_hash "
            "FROM run_driver_snapshots WHERE run_id=?", (summary.run_id,)
        ).fetchone()
    assert run_row == (first["geometry_id"],)
    assert snapshot_row[0] == first["geometry_id"]
    assert snapshot_row[1] == revision["revision_id"]
    assert snapshot_row[2] == loaded_first.driver_snapshot["snapshot_hash"]
    assert snapshot_row[3] == snapshot_row[4]
