from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings
from app.speaker_assembly_domain import (
    GeometryInstance,
    SpeakerAssembly,
    SpeakerAssemblyRepository,
    SpatialTransform,
    ensure_project_assembly_schema,
    geometry_snapshot_hash,
)


def _service(tmp_path: Path) -> OrchestratorService:
    store = SettingsStore(tmp_path / "settings.json")
    store.save(UserSettings(library_root=str(tmp_path / "library")))
    return OrchestratorService(store)


def test_transform_is_finite_and_normalizes_fixed_axis_degrees() -> None:
    transform = SpatialTransform(
        translation_x_m=0.125,
        translation_y_m=-0.25,
        translation_z_m=1.5,
        rotation_x_deg=190,
        rotation_y_deg=-540,
        rotation_z_deg=360,
    )
    assert transform.translation_x_m == 0.125
    assert transform.rotation_x_deg == -170
    assert transform.rotation_y_deg == -180
    assert transform.rotation_z_deg == 0
    with pytest.raises(ValueError, match="finite"):
        SpatialTransform(translation_x_m=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        SpatialTransform(rotation_z_deg=float("inf"))


def test_instance_rejects_snapshot_tampering_and_invalid_arrangement() -> None:
    geometry = {"geometry_id": "G1", "project_id": "P1", "name": "Horn"}
    with pytest.raises(ValueError, match="hash mismatch"):
        GeometryInstance(
            instance_id="I1",
            geometry_id="G1",
            geometry_snapshot=geometry,
            geometry_snapshot_hash="0" * 64,
            name="Horn instance",
        )
    with pytest.raises(ValueError, match="arrangement"):
        GeometryInstance(
            instance_id="I1",
            geometry_id="G1",
            geometry_snapshot=geometry,
            geometry_snapshot_hash=geometry_snapshot_hash(geometry),
            name="Horn instance",
            arrangement="stacked",
        )


def test_assembly_serialization_preserves_extensions_and_order() -> None:
    geometry = {"geometry_id": "G1", "project_id": "P1", "name": "Horn"}
    item = GeometryInstance(
        instance_id="I1",
        geometry_id="G1",
        geometry_snapshot=geometry,
        geometry_snapshot_hash=geometry_snapshot_hash(geometry),
        name="Horn instance",
        arrangement="coaxial",
        transform=SpatialTransform(translation_z_m=0.2, rotation_y_deg=15),
        extensions={"future_source": "S1"},
    )
    assembly = SpeakerAssembly(
        assembly_id="SA1",
        project_id="P1",
        name="System",
        instances=(item,),
        extensions={"future_signal_chain": "SC1"},
    )
    payload = assembly.to_dict()
    payload["unknown_top_level"] = {"retained": True}
    loaded = SpeakerAssembly.from_dict(payload)
    assert loaded.instances[0].arrangement == "coaxial"
    assert loaded.instances[0].transform.translation_z_m == 0.2
    assert loaded.instances[0].extensions["future_source"] == "S1"
    assert loaded.extensions["unknown_top_level"] == {"retained": True}


def test_repository_crud_reorder_remove_archive_and_sql_round_trip(tmp_path: Path) -> None:
    project_root = tmp_path / "P1"
    db_path = project_root / "db" / "project.sqlite"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        ensure_project_assembly_schema(conn)
    repo = SpeakerAssemblyRepository(project_root, "P1")
    assembly = repo.create(name="Two-way", description="Prototype")
    g1 = {"geometry_id": "G1", "project_id": "P1", "name": "HF", "role": "hf_horn"}
    g2 = {"geometry_id": "G2", "project_id": "P1", "name": "MF", "role": "mid_horn"}
    assembly = repo.add_instance(
        assembly.assembly_id,
        geometry=g1,
        name="HF centre",
        arrangement="coaxial",
        transform={"translation_z_m": 0.125, "rotation_y_deg": 12.5},
    )
    assembly = repo.add_instance(
        assembly.assembly_id,
        geometry=g2,
        name="MF outer",
        arrangement="normal",
        transform={"translation_x_m": 0.35},
    )
    first_id, second_id = (item.instance_id for item in assembly.instances)
    assembly = repo.move_instance(assembly.assembly_id, second_id, 0)
    assert [item.instance_id for item in assembly.instances] == [second_id, first_id]
    assert [item.order_index for item in assembly.instances] == [0, 1]
    assembly = repo.update_instance(
        assembly.assembly_id,
        first_id,
        name="HF edited",
        transform={"translation_z_m": 0.2, "rotation_z_deg": 25},
    )
    assert next(item for item in assembly.instances if item.instance_id == first_id).name == "HF edited"
    assembly = repo.remove_instance(assembly.assembly_id, second_id)
    assert len(assembly.instances) == 1
    assert assembly.instances[0].order_index == 0

    loaded = repo.get(assembly.assembly_id)
    assert loaded.to_dict() == assembly.to_dict()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT arrangement, order_index, translation_z_m, rotation_z_deg, geometry_snapshot_hash "
            "FROM speaker_assembly_instances WHERE instance_id = ?",
            (first_id,),
        ).fetchone()
        assert row[:4] == ("coaxial", 0, 0.2, 25.0)
        assert row[4] == assembly.instances[0].geometry_snapshot_hash

    archived = repo.archive(assembly.assembly_id)
    assert archived.archived_at
    assert repo.list() == []
    assert repo.list(include_archived=True)[0].assembly_id == assembly.assembly_id
    with pytest.raises(ValueError, match="Archived"):
        repo.add_instance(archived.assembly_id, geometry=g2, name="Blocked")


def test_service_captures_immutable_geometry_snapshot_and_rejects_foreign_or_archived(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create_project("Assembly service", {"fixed_params": {}, "limits": {}})
    geometry = service.list_geometries(project.project_id)[0]
    second = service.create_geometry(project.project_id, name="Second", role="mid_horn")
    assembly = service.create_speaker_assembly(project.project_id, name="System")
    assembly = service.add_speaker_assembly_instance(
        project.project_id,
        assembly["assembly_id"],
        geometry_id=geometry["geometry_id"],
        name="Primary",
        arrangement="normal",
        transform={"translation_x_m": 0.1},
    )
    original_snapshot = dict(assembly["instances"][0]["geometry_snapshot"])
    original_hash = assembly["instances"][0]["geometry_snapshot_hash"]
    service.update_geometry(project.project_id, geometry["geometry_id"], name="Renamed live geometry")
    reloaded = service.get_speaker_assembly(project.project_id, assembly["assembly_id"])
    assert reloaded["instances"][0]["geometry_snapshot"] == original_snapshot
    assert reloaded["instances"][0]["geometry_snapshot_hash"] == original_hash

    reloaded = service.update_speaker_assembly_instance(
        project.project_id,
        assembly["assembly_id"],
        reloaded["instances"][0]["instance_id"],
        geometry_id=second["geometry_id"],
        arrangement="coaxial",
    )
    assert reloaded["instances"][0]["geometry_id"] == second["geometry_id"]
    assert reloaded["instances"][0]["geometry_snapshot"]["name"] == "Second"
    assert reloaded["instances"][0]["geometry_snapshot_hash"] != original_hash

    service.archive_geometry(project.project_id, second["geometry_id"])
    with pytest.raises(ValueError, match="Archived Geometry"):
        service.add_speaker_assembly_instance(
            project.project_id,
            assembly["assembly_id"],
            geometry_id=second["geometry_id"],
            name="Archived source",
        )

    other_project = service.create_project("Other", {"fixed_params": {}, "limits": {}})
    other_geometry = service.list_geometries(other_project.project_id)[0]
    with pytest.raises(KeyError):
        service.add_speaker_assembly_instance(
            project.project_id,
            assembly["assembly_id"],
            geometry_id=other_geometry["geometry_id"],
            name="Foreign source",
        )


def test_additive_schema_is_idempotent_and_legacy_project_remains_unchanged(tmp_path: Path) -> None:
    project_root = tmp_path / "P-LEGACY"
    project_root.mkdir()
    legacy_project = project_root / "project.json"
    original = {"project_id": "P-LEGACY", "project_name": "Legacy", "constraints": {}}
    legacy_project.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
    db_path = project_root / "db" / "project.sqlite"
    db_path.parent.mkdir()
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE legacy_payload (id TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO legacy_payload VALUES ('A', 'untouched')")
        ensure_project_assembly_schema(conn)
        ensure_project_assembly_schema(conn)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"speaker_assemblies", "speaker_assembly_instances"}.issubset(tables)
        assert conn.execute("SELECT value FROM legacy_payload WHERE id='A'").fetchone()[0] == "untouched"
    assert json.loads(legacy_project.read_text(encoding="utf-8")) == original
    assert not (project_root / "assemblies").exists()
