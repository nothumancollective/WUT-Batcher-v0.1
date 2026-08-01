"""Geometry aggregate and additive legacy migration primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Iterable
import uuid


GEOMETRY_SCHEMA_VERSION = 1
GEOMETRY_ROLES = {"hf_horn", "mid_horn", "waveguide"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def legacy_geometry_id(project_id: str) -> str:
    token = hashlib.sha256(str(project_id).encode("utf-8")).hexdigest()[:12]
    return f"GLEGACY-{token}"


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _write_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Geometry:
    geometry_id: str
    project_id: str
    name: str
    description: str = ""
    role: str = "hf_horn"
    ath_template: str | None = None
    ath_parameters: dict[str, Any] = field(default_factory=dict)
    default_driver_revision_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    archived_at: str | None = None
    schema_version: int = GEOMETRY_SCHEMA_VERSION
    legacy: bool = False
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.geometry_id.strip() or not self.project_id.strip():
            raise ValueError("geometry_id and project_id are required")
        if not self.name.strip():
            raise ValueError("Geometry name is required")
        if self.role not in GEOMETRY_ROLES and not self.role.startswith("future_"):
            raise ValueError(f"Unsupported geometry role: {self.role}")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Geometry":
        known = {item.name for item in cls.__dataclass_fields__.values()}
        extensions = dict(payload.get("extensions") or {})
        extensions.update({key: value for key, value in payload.items() if key not in known})
        return cls(
            geometry_id=str(payload.get("geometry_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            role=str(payload.get("role") or "hf_horn"),
            ath_template=(str(payload["ath_template"]) if payload.get("ath_template") else None),
            ath_parameters=dict(payload.get("ath_parameters") or {}),
            default_driver_revision_id=(
                str(payload["default_driver_revision_id"]) if payload.get("default_driver_revision_id") else None
            ),
            created_at=str(payload.get("created_at") or utc_now()),
            updated_at=str(payload.get("updated_at") or utc_now()),
            archived_at=(str(payload["archived_at"]) if payload.get("archived_at") else None),
            schema_version=int(payload.get("schema_version") or GEOMETRY_SCHEMA_VERSION),
            legacy=bool(payload.get("legacy", False)),
            extensions=extensions,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GeometryRepository:
    def __init__(self, project_root: str | Path, project_id: str) -> None:
        self.project_root = Path(project_root)
        self.project_id = str(project_id)
        self.geometries_dir = self.project_root / "geometries"

    def _path(self, geometry_id: str) -> Path:
        return self.geometries_dir / str(geometry_id) / "geometry.json"

    def _sync_db(self, item: Geometry) -> None:
        db_path = next((path for path in (self.project_root / "db" / "project.sqlite", self.project_root / "dataset" / "project.sqlite") if path.exists()), None)
        if db_path is None:
            return
        with closing(sqlite3.connect(db_path)) as conn:
            with conn:
                ensure_project_geometry_schema(conn)
                conn.execute(
                """INSERT INTO geometries
                (geometry_id, project_id, name, description, role, ath_template,
                 ath_parameters_json, default_driver_revision_id, schema_version,
                 legacy, created_at, updated_at, archived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(geometry_id) DO UPDATE SET
                    name=excluded.name, description=excluded.description,
                    role=excluded.role, ath_template=excluded.ath_template,
                    ath_parameters_json=excluded.ath_parameters_json,
                    default_driver_revision_id=excluded.default_driver_revision_id,
                    updated_at=excluded.updated_at, archived_at=excluded.archived_at""",
                    (
                    item.geometry_id, item.project_id, item.name, item.description,
                    item.role, item.ath_template, json.dumps(item.ath_parameters, sort_keys=True),
                    item.default_driver_revision_id, item.schema_version, int(item.legacy),
                    item.created_at, item.updated_at, item.archived_at,
                    ),
                )

    def list(self, *, include_archived: bool = False) -> list[Geometry]:
        if not self.geometries_dir.exists():
            return []
        result: list[Geometry] = []
        for path in sorted(self.geometries_dir.glob("*/geometry.json")):
            try:
                item = Geometry.from_dict(_read_object(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if item.project_id != self.project_id:
                continue
            if item.archived_at and not include_archived:
                continue
            result.append(item)
        return result

    def get(self, geometry_id: str) -> Geometry:
        path = self._path(geometry_id)
        if not path.exists():
            raise KeyError(f"Unknown geometry: {geometry_id}")
        item = Geometry.from_dict(_read_object(path))
        if item.project_id != self.project_id:
            raise ValueError("Geometry belongs to a different project")
        return item

    def create(
        self,
        *,
        name: str,
        description: str = "",
        role: str = "hf_horn",
        ath_template: str | None = None,
        ath_parameters: dict[str, Any] | None = None,
        default_driver_revision_id: str | None = None,
        geometry_id: str | None = None,
        legacy: bool = False,
    ) -> Geometry:
        item = Geometry(
            geometry_id=geometry_id or f"G-{uuid.uuid4()}",
            project_id=self.project_id,
            name=name.strip(),
            description=description,
            role=role,
            ath_template=ath_template,
            ath_parameters=dict(ath_parameters or {}),
            default_driver_revision_id=default_driver_revision_id,
            legacy=legacy,
        )
        path = self._path(item.geometry_id)
        if path.exists():
            raise ValueError(f"Geometry already exists: {item.geometry_id}")
        _write_object(path, item.to_dict())
        self._sync_db(item)
        return item

    def update(self, geometry_id: str, **changes: Any) -> Geometry:
        current = self.get(geometry_id)
        forbidden = {"geometry_id", "project_id", "created_at", "legacy", "schema_version"}
        rejected = forbidden.intersection(changes)
        if rejected:
            raise ValueError(f"Immutable geometry fields: {', '.join(sorted(rejected))}")
        updated = replace(current, **changes, updated_at=utc_now())
        _write_object(self._path(geometry_id), updated.to_dict())
        self._sync_db(updated)
        return updated

    def duplicate(self, geometry_id: str, *, name: str | None = None) -> Geometry:
        source = self.get(geometry_id)
        return self.create(
            name=(name or f"{source.name} Copy"),
            description=source.description,
            role=source.role,
            ath_template=source.ath_template,
            ath_parameters=source.ath_parameters,
            default_driver_revision_id=source.default_driver_revision_id,
        )

    def archive(self, geometry_id: str) -> Geometry:
        item = self.get(geometry_id)
        if item.legacy:
            raise ValueError("The legacy geometry cannot be archived")
        return self.update(geometry_id, archived_at=utc_now())


def ensure_project_geometry_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS geometries (
            geometry_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL,
            ath_template TEXT,
            ath_parameters_json TEXT NOT NULL DEFAULT '{}',
            default_driver_revision_id TEXT,
            schema_version INTEGER NOT NULL,
            legacy INTEGER NOT NULL DEFAULT 0 CHECK (legacy IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_geometries_project_archive
            ON geometries(project_id, archived_at);
        CREATE TABLE IF NOT EXISTS run_driver_snapshots (
            run_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            geometry_id TEXT NOT NULL,
            driver_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            le_network_hash TEXT,
            staged_le_hash TEXT,
            snapshot_json TEXT NOT NULL,
            staged_le_path TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, version_id)
        );
        CREATE INDEX IF NOT EXISTS idx_run_driver_geometry
            ON run_driver_snapshots(project_id, geometry_id, revision_id);
        """
    )
    snapshot_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(run_driver_snapshots)").fetchall()}
    if "staged_le_hash" not in snapshot_columns:
        conn.execute("ALTER TABLE run_driver_snapshots ADD COLUMN staged_le_hash TEXT")
    for table in ("batches", "versions", "runs", "run_versions", "graphs", "polar_measurements"):
        columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if columns and "geometry_id" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN geometry_id TEXT")


@dataclass(frozen=True)
class GeometryMigrationReport:
    project_id: str
    geometry_id: str
    dry_run: bool
    changed_files: tuple[str, ...]
    unchanged_files: tuple[str, ...]
    database_changes: tuple[str, ...]
    warnings: tuple[str, ...]
    backup_dir: str | None
    completed: bool


def migrate_legacy_project(
    project_root: str | Path,
    *,
    dry_run: bool = True,
    backup_root: str | Path | None = None,
) -> GeometryMigrationReport:
    root = Path(project_root)
    project_json = root / "project.json"
    project = _read_object(project_json)
    project_id = str(project.get("project_id") or root.name)
    geometry_id = legacy_geometry_id(project_id)
    repo = GeometryRepository(root, project_id)
    changed: list[Path] = []
    unchanged: list[Path] = []
    targets: list[tuple[Path, dict[str, Any]]] = []

    if not repo._path(geometry_id).exists():
        geometry = Geometry(
            geometry_id=geometry_id,
            project_id=project_id,
            name="Legacy Geometry",
            description="Compatibility geometry for pre-geometry project data.",
            role="hf_horn",
            ath_template=str(project.get("constraints", {}).get("template_cfg") or "") or None,
            ath_parameters=dict(project.get("constraints", {}).get("fixed_params") or {}),
            legacy=True,
        )
        targets.append((repo._path(geometry_id), geometry.to_dict()))

    for pattern in ("batches/*/batch.json", "versions/*/version.json"):
        for path in sorted(root.glob(pattern)):
            payload = _read_object(path)
            existing = str(payload.get("geometry_id") or "")
            if existing:
                unchanged.append(path)
                continue
            payload["geometry_id"] = geometry_id
            targets.append((path, payload))

    changed.extend(path for path, _ in targets)
    db_path = next((candidate for candidate in (root / "db" / "project.sqlite", root / "dataset" / "project.sqlite") if candidate.exists()), None)
    db_changes = ("ensure geometry tables/columns", f"assign null rows to {geometry_id}") if db_path else ()
    backup_dir: Path | None = None
    if not dry_run:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = Path(backup_root) if backup_root else root / "migration_backups" / f"geometry-v1-{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for path, _ in targets:
            if path.exists():
                destination = backup_dir / path.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
        if db_path:
            destination = backup_dir / db_path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_path, destination)
        for path, payload in targets:
            _write_object(path, payload)
        if db_path:
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    ensure_project_geometry_schema(conn)
                    geometry = Geometry.from_dict(_read_object(repo._path(geometry_id)))
                    conn.execute(
                    """INSERT OR IGNORE INTO geometries
                    (geometry_id, project_id, name, description, role, ath_template,
                     ath_parameters_json, default_driver_revision_id, schema_version,
                     legacy, created_at, updated_at, archived_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                        geometry.geometry_id, geometry.project_id, geometry.name,
                        geometry.description, geometry.role, geometry.ath_template,
                        json.dumps(geometry.ath_parameters, sort_keys=True),
                        geometry.default_driver_revision_id, geometry.schema_version,
                        1, geometry.created_at, geometry.updated_at, geometry.archived_at,
                        ),
                    )
                    for table in ("batches", "versions", "runs", "run_versions", "graphs", "polar_measurements"):
                        columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                        if "geometry_id" in columns:
                            conn.execute(f"UPDATE {table} SET geometry_id=? WHERE geometry_id IS NULL OR geometry_id=''", (geometry_id,))

    return GeometryMigrationReport(
        project_id=project_id,
        geometry_id=geometry_id,
        dry_run=dry_run,
        changed_files=tuple(str(path) for path in changed),
        unchanged_files=tuple(str(path) for path in unchanged),
        database_changes=db_changes,
        warnings=(),
        backup_dir=str(backup_dir) if backup_dir else None,
        completed=(not dry_run),
    )
