from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from app.geometry_domain import GeometryRepository, legacy_geometry_id, migrate_legacy_project
from app.sql_dataset_store import SqlDatasetStore


def _legacy_project(tmp_path: Path) -> Path:
    root = tmp_path / "library" / "projects" / "P0001__fixture"
    (root / "batches" / "B001").mkdir(parents=True)
    (root / "versions" / "V001").mkdir(parents=True)
    (root / "project.json").write_text(json.dumps({
        "project_id": "P0001__fixture", "name": "Legacy", "constraints": {"fixed_params": {"Length": 100.0}}
    }), encoding="utf-8")
    (root / "batches" / "B001" / "batch.json").write_text(json.dumps({
        "batch_id": "B001", "project_id": "P0001__fixture"
    }), encoding="utf-8")
    (root / "versions" / "V001" / "version.json").write_text(json.dumps({
        "version_id": "V001", "project_id": "P0001__fixture", "batch_id": "B001"
    }), encoding="utf-8")
    SqlDatasetStore(root, library_root=root.parents[1])
    return root


def test_geometry_crud_duplicate_archive_and_legacy_guard(tmp_path: Path) -> None:
    repo = GeometryRepository(tmp_path, "P1")
    legacy = repo.create(name="Legacy Geometry", geometry_id=legacy_geometry_id("P1"), legacy=True)
    horn = repo.create(name="HF One", role="hf_horn", ath_parameters={"Length": 120.0})
    renamed = repo.update(horn.geometry_id, name="HF Main", description="long text " * 20)
    duplicate = repo.duplicate(horn.geometry_id)

    assert renamed.name == "HF Main"
    assert duplicate.geometry_id != horn.geometry_id
    assert duplicate.ath_parameters == horn.ath_parameters
    assert len(repo.list()) == 3
    repo.archive(duplicate.geometry_id)
    assert len(repo.list()) == 2
    assert len(repo.list(include_archived=True)) == 3
    with pytest.raises(ValueError, match="legacy geometry"):
        repo.archive(legacy.geometry_id)


def test_legacy_migration_dry_run_write_backup_and_idempotence(tmp_path: Path) -> None:
    root = _legacy_project(tmp_path)
    batch_path = root / "batches" / "B001" / "batch.json"
    before = batch_path.read_bytes()

    preview = migrate_legacy_project(root, dry_run=True)
    assert preview.dry_run is True
    assert len(preview.changed_files) == 3
    assert batch_path.read_bytes() == before
    assert not (root / "geometries").exists()

    backup = tmp_path / "backup"
    applied = migrate_legacy_project(root, dry_run=False, backup_root=backup)
    expected = legacy_geometry_id("P0001__fixture")
    assert applied.completed is True
    assert applied.geometry_id == expected
    assert (backup / "batches" / "B001" / "batch.json").read_bytes() == before
    assert (backup / "db" / "project.sqlite").exists()
    assert json.loads(batch_path.read_text(encoding="utf-8"))["geometry_id"] == expected
    assert json.loads((root / "versions" / "V001" / "version.json").read_text(encoding="utf-8"))["geometry_id"] == expected

    second = migrate_legacy_project(root, dry_run=True)
    assert second.changed_files == ()
    assert len(second.unchanged_files) == 2
    assert len(GeometryRepository(root, "P0001__fixture").list(include_archived=True)) == 1

    with sqlite3.connect(root / "db" / "project.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM geometries").fetchone()[0] == 1
        assert "geometry_id" in {row[1] for row in conn.execute("PRAGMA table_info(versions)")}
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_partial_migration_repairs_only_missing_assignment(tmp_path: Path) -> None:
    root = _legacy_project(tmp_path)
    migrate_legacy_project(root, dry_run=False, backup_root=tmp_path / "first")
    batch_path = root / "batches" / "B001" / "batch.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch.pop("geometry_id")
    batch_path.write_text(json.dumps(batch), encoding="utf-8")

    report = migrate_legacy_project(root, dry_run=False, backup_root=tmp_path / "repair")
    assert report.changed_files == (str(batch_path),)
    assert json.loads(batch_path.read_text(encoding="utf-8"))["geometry_id"] == report.geometry_id
