from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from app.driver_library import DriverDefinition, DriverRevision
from app.models import Batch
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


def _user_driver(service: OrchestratorService, tmp_path: Path, token: str) -> dict:
    source = tmp_path / f"{token}.le"
    source.write_text(f"System '{token}'\nDriver 'D1'\n", encoding="utf-8")
    return service.create_driver(
        definition=DriverDefinition(
            driver_id=f"D-{token}", manufacturer="Test", model=token,
            kind="compression_driver", origin="user",
        ).__dict__,
        revision=DriverRevision(
            revision_id=f"DR-{token}-1", driver_id=f"D-{token}", revision_number=1,
            provenance={"source": "test", "trust": "user_asserted"},
        ).__dict__,
        le_source_path=source,
    )


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
    assert loaded_first.driver_selection_mode == "geometry_default"
    assert loaded_first.driver_override_revision_id == ""
    assert loaded_first.driver_snapshot == {}
    resolution = service.resolve_batch_driver_selection(project.project_id, loaded_first)
    assert resolution["selection_source"] == "geometry_default"
    assert resolution["revision_id"] == revision["revision_id"]
    assert resolution["snapshot_hash"]

    summary = service.run_batch(project.project_id, first_batch.batch_id, dry_run=True)
    assert summary.run_status == "succeeded"
    project_root = service.repo.project_paths(project.project_id).project_dir
    version = json.loads((project_root / "versions" / first_batch.version_ids[0] / "version.json").read_text(encoding="utf-8"))
    assert version["geometry_id"] == first["geometry_id"]
    assert version["driver_snapshot"] == {}
    with sqlite3.connect(project_root / "db" / "project.sqlite") as conn:
        run_row = conn.execute("SELECT geometry_id FROM runs WHERE run_id=?", (summary.run_id,)).fetchone()
        snapshot_row = conn.execute(
            "SELECT geometry_id, revision_id, selection_source, snapshot_hash, le_network_hash, staged_le_hash "
            "FROM run_driver_snapshots WHERE run_id=?", (summary.run_id,)
        ).fetchone()
    assert run_row == (first["geometry_id"],)
    assert snapshot_row[0] == first["geometry_id"]
    assert snapshot_row[1] == revision["revision_id"]
    assert snapshot_row[2] == "geometry_default"
    assert snapshot_row[3]
    assert snapshot_row[4] == snapshot_row[5]


def test_batch_override_precedes_geometry_default_and_legacy_revision(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create_project("Driver priority", {"fixed_params": {"Length": 120.0}, "limits": {}})
    geometry = service.list_geometries(project.project_id)[0]
    default = _user_driver(service, tmp_path, "DEFAULT")
    override = _user_driver(service, tmp_path, "OVERRIDE")
    service.set_geometry_default_driver(project.project_id, geometry["geometry_id"], default["revision_id"])

    summary = service.create_batch(
        project_id=project.project_id, geometry_id=geometry["geometry_id"], batch_name="Override",
        selected_params={}, sweeps={}, sweep_mode="single", sim_export_params={},
        driver_selection_mode="explicit_override",
        driver_override_revision_id=override["revision_id"],
    )
    batch = service.repo.load_batch(project.project_id, summary.batch_id)
    resolved = service.resolve_batch_driver_selection(project.project_id, batch, require_runnable=True)
    assert resolved["selection_source"] == "batch_override"
    assert resolved["revision_id"] == override["revision_id"]

    service.set_geometry_default_driver(project.project_id, geometry["geometry_id"], None)
    legacy = Batch(
        batch_id="B-LEGACY", project_id=project.project_id, geometry_id=geometry["geometry_id"],
        driver_revision_id=default["revision_id"],
    )
    legacy_resolved = service.resolve_batch_driver_selection(project.project_id, legacy, require_runnable=True)
    assert legacy_resolved["selection_source"] == "legacy_batch_revision"
    assert legacy_resolved["revision_id"] == default["revision_id"]


def test_geometry_default_is_resolved_per_run_without_mutating_old_snapshot(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create_project("Run snapshot", {"fixed_params": {"Length": 120.0}, "limits": {}})
    geometry = service.list_geometries(project.project_id)[0]
    first = _user_driver(service, tmp_path, "FIRST")
    second = _user_driver(service, tmp_path, "SECOND")
    service.set_geometry_default_driver(project.project_id, geometry["geometry_id"], first["revision_id"])
    planned = service.create_batch(
        project_id=project.project_id, geometry_id=geometry["geometry_id"], batch_name="Default",
        selected_params={}, sweeps={}, sweep_mode="single", sim_export_params={},
    )

    service.set_geometry_default_driver(project.project_id, geometry["geometry_id"], second["revision_id"])
    run_second = service.run_batch(project.project_id, planned.batch_id, dry_run=True)
    service.set_geometry_default_driver(project.project_id, geometry["geometry_id"], first["revision_id"])
    run_first = service.run_batch(project.project_id, planned.batch_id, dry_run=True)

    project_root = service.repo.project_paths(project.project_id).project_dir
    with sqlite3.connect(project_root / "db" / "project.sqlite") as conn:
        rows = conn.execute(
            "SELECT run_id, revision_id, selection_source, snapshot_hash FROM run_driver_snapshots "
            "WHERE run_id IN (?, ?) ORDER BY run_id",
            (run_second.run_id, run_first.run_id),
        ).fetchall()
    by_run = {row[0]: row[1:] for row in rows}
    assert by_run[run_second.run_id][0] == second["revision_id"]
    assert by_run[run_first.run_id][0] == first["revision_id"]
    assert by_run[run_second.run_id][1] == "geometry_default"
    assert by_run[run_first.run_id][1] == "geometry_default"
    assert by_run[run_second.run_id][2] != by_run[run_first.run_id][2]
    stored = service.repo.load_batch(project.project_id, planned.batch_id)
    assert stored.driver_snapshot == {}
