"""Project-local SpeakerAssembly aggregate and additive storage schema."""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterable
import uuid


SPEAKER_ASSEMBLY_SCHEMA_VERSION = 1
INSTANCE_ARRANGEMENTS = {"normal", "coaxial"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def geometry_snapshot_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _write_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _finite(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number")
    return number


def _normalized_degrees(value: Any, field_name: str) -> float:
    number = _finite(value, field_name)
    normalized = (number + 180.0) % 360.0 - 180.0
    return 0.0 if normalized == -0.0 else normalized


@dataclass(frozen=True)
class SpatialTransform:
    translation_x_m: float = 0.0
    translation_y_m: float = 0.0
    translation_z_m: float = 0.0
    rotation_x_deg: float = 0.0
    rotation_y_deg: float = 0.0
    rotation_z_deg: float = 0.0

    def __post_init__(self) -> None:
        for name in ("translation_x_m", "translation_y_m", "translation_z_m"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        for name in ("rotation_x_deg", "rotation_y_deg", "rotation_z_deg"):
            object.__setattr__(self, name, _normalized_degrees(getattr(self, name), name))

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SpatialTransform":
        data = dict(payload or {})
        translation = dict(data.get("translation_m") or {})
        rotation = dict(data.get("rotation_deg") or {})
        return cls(
            translation_x_m=data.get("translation_x_m", translation.get("x", 0.0)),
            translation_y_m=data.get("translation_y_m", translation.get("y", 0.0)),
            translation_z_m=data.get("translation_z_m", translation.get("z", 0.0)),
            rotation_x_deg=data.get("rotation_x_deg", rotation.get("x", 0.0)),
            rotation_y_deg=data.get("rotation_y_deg", rotation.get("y", 0.0)),
            rotation_z_deg=data.get("rotation_z_deg", rotation.get("z", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GeometryInstance:
    instance_id: str
    geometry_id: str
    geometry_snapshot: dict[str, Any]
    geometry_snapshot_hash: str
    name: str
    description: str = ""
    arrangement: str = "normal"
    transform: SpatialTransform = field(default_factory=SpatialTransform)
    order_index: int = 0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.instance_id.strip() or not self.geometry_id.strip():
            raise ValueError("instance_id and geometry_id are required")
        if not self.name.strip():
            raise ValueError("Geometry instance name is required")
        if self.arrangement not in INSTANCE_ARRANGEMENTS:
            raise ValueError(f"Unsupported instance arrangement: {self.arrangement}")
        if int(self.order_index) < 0:
            raise ValueError("order_index must be non-negative")
        actual_hash = geometry_snapshot_hash(dict(self.geometry_snapshot))
        if self.geometry_snapshot_hash != actual_hash:
            raise ValueError("Geometry snapshot hash mismatch")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GeometryInstance":
        known = {item.name for item in cls.__dataclass_fields__.values()}
        extensions = dict(payload.get("extensions") or {})
        extensions.update({key: value for key, value in payload.items() if key not in known})
        snapshot = dict(payload.get("geometry_snapshot") or {})
        return cls(
            instance_id=str(payload.get("instance_id") or ""),
            geometry_id=str(payload.get("geometry_id") or snapshot.get("geometry_id") or ""),
            geometry_snapshot=snapshot,
            geometry_snapshot_hash=str(payload.get("geometry_snapshot_hash") or geometry_snapshot_hash(snapshot)),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            arrangement=str(payload.get("arrangement") or "normal"),
            transform=SpatialTransform.from_dict(dict(payload.get("transform") or {})),
            order_index=int(payload.get("order_index") or 0),
            created_at=str(payload.get("created_at") or utc_now()),
            updated_at=str(payload.get("updated_at") or utc_now()),
            extensions=extensions,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["transform"] = self.transform.to_dict()
        return payload


@dataclass(frozen=True)
class SpeakerAssembly:
    assembly_id: str
    project_id: str
    name: str
    description: str = ""
    instances: tuple[GeometryInstance, ...] = ()
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    archived_at: str | None = None
    schema_version: int = SPEAKER_ASSEMBLY_SCHEMA_VERSION
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.assembly_id.strip() or not self.project_id.strip():
            raise ValueError("assembly_id and project_id are required")
        if not self.name.strip():
            raise ValueError("SpeakerAssembly name is required")
        ids = [item.instance_id for item in self.instances]
        if len(ids) != len(set(ids)):
            raise ValueError("Geometry instance IDs must be unique")
        indexes = [item.order_index for item in self.instances]
        if indexes != list(range(len(indexes))):
            raise ValueError("Geometry instance order must be compact and deterministic")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SpeakerAssembly":
        known = {item.name for item in cls.__dataclass_fields__.values()}
        extensions = dict(payload.get("extensions") or {})
        extensions.update({key: value for key, value in payload.items() if key not in known})
        instances = tuple(
            sorted(
                (GeometryInstance.from_dict(dict(item)) for item in list(payload.get("instances") or [])),
                key=lambda item: item.order_index,
            )
        )
        return cls(
            assembly_id=str(payload.get("assembly_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            instances=instances,
            created_at=str(payload.get("created_at") or utc_now()),
            updated_at=str(payload.get("updated_at") or utc_now()),
            archived_at=str(payload["archived_at"]) if payload.get("archived_at") else None,
            schema_version=int(payload.get("schema_version") or SPEAKER_ASSEMBLY_SCHEMA_VERSION),
            extensions=extensions,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["instances"] = [item.to_dict() for item in self.instances]
        return payload


def ensure_project_assembly_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS speaker_assemblies (
            assembly_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_speaker_assemblies_project_archive
            ON speaker_assemblies(project_id, archived_at);

        CREATE TABLE IF NOT EXISTS speaker_assembly_instances (
            instance_id TEXT PRIMARY KEY,
            assembly_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            geometry_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            arrangement TEXT NOT NULL CHECK (arrangement IN ('normal', 'coaxial')),
            order_index INTEGER NOT NULL CHECK (order_index >= 0),
            translation_x_m REAL NOT NULL,
            translation_y_m REAL NOT NULL,
            translation_z_m REAL NOT NULL,
            rotation_x_deg REAL NOT NULL,
            rotation_y_deg REAL NOT NULL,
            rotation_z_deg REAL NOT NULL,
            geometry_snapshot_hash TEXT NOT NULL,
            geometry_snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (assembly_id) REFERENCES speaker_assemblies(assembly_id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_speaker_assembly_instance_order
            ON speaker_assembly_instances(assembly_id, order_index);
        CREATE INDEX IF NOT EXISTS idx_speaker_assembly_instance_geometry
            ON speaker_assembly_instances(project_id, geometry_id);
        """
    )


class SpeakerAssemblyRepository:
    def __init__(self, project_root: str | Path, project_id: str) -> None:
        self.project_root = Path(project_root)
        self.project_id = str(project_id)
        self.assemblies_dir = self.project_root / "assemblies"

    def _path(self, assembly_id: str) -> Path:
        return self.assemblies_dir / str(assembly_id) / "assembly.json"

    def _db_path(self) -> Path | None:
        return next(
            (
                path
                for path in (
                    self.project_root / "db" / "project.sqlite",
                    self.project_root / "dataset" / "project.sqlite",
                )
                if path.exists()
            ),
            None,
        )

    def _sync_db(self, assembly: SpeakerAssembly) -> None:
        db_path = self._db_path()
        if db_path is None:
            return
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            with conn:
                ensure_project_assembly_schema(conn)
                conn.execute(
                    """INSERT INTO speaker_assemblies
                    (assembly_id, project_id, name, description, schema_version,
                     created_at, updated_at, archived_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(assembly_id) DO UPDATE SET
                        name=excluded.name, description=excluded.description,
                        schema_version=excluded.schema_version,
                        updated_at=excluded.updated_at, archived_at=excluded.archived_at""",
                    (
                        assembly.assembly_id,
                        assembly.project_id,
                        assembly.name,
                        assembly.description,
                        assembly.schema_version,
                        assembly.created_at,
                        assembly.updated_at,
                        assembly.archived_at,
                    ),
                )
                conn.execute("DELETE FROM speaker_assembly_instances WHERE assembly_id = ?", (assembly.assembly_id,))
                for item in assembly.instances:
                    transform = item.transform
                    conn.execute(
                        """INSERT INTO speaker_assembly_instances
                        (instance_id, assembly_id, project_id, geometry_id, name,
                         description, arrangement, order_index, translation_x_m,
                         translation_y_m, translation_z_m, rotation_x_deg,
                         rotation_y_deg, rotation_z_deg, geometry_snapshot_hash,
                         geometry_snapshot_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item.instance_id,
                            assembly.assembly_id,
                            assembly.project_id,
                            item.geometry_id,
                            item.name,
                            item.description,
                            item.arrangement,
                            item.order_index,
                            transform.translation_x_m,
                            transform.translation_y_m,
                            transform.translation_z_m,
                            transform.rotation_x_deg,
                            transform.rotation_y_deg,
                            transform.rotation_z_deg,
                            item.geometry_snapshot_hash,
                            _canonical_json(item.geometry_snapshot),
                            item.created_at,
                            item.updated_at,
                        ),
                    )

    def _save(self, assembly: SpeakerAssembly) -> SpeakerAssembly:
        _write_object(self._path(assembly.assembly_id), assembly.to_dict())
        self._sync_db(assembly)
        return assembly

    def list(self, *, include_archived: bool = False) -> list[SpeakerAssembly]:
        if not self.assemblies_dir.exists():
            return []
        result: list[SpeakerAssembly] = []
        for path in sorted(self.assemblies_dir.glob("*/assembly.json")):
            try:
                item = SpeakerAssembly.from_dict(_read_object(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if item.project_id != self.project_id:
                continue
            if item.archived_at and not include_archived:
                continue
            result.append(item)
        return result

    def get(self, assembly_id: str) -> SpeakerAssembly:
        path = self._path(assembly_id)
        if not path.exists():
            raise KeyError(f"Unknown SpeakerAssembly: {assembly_id}")
        item = SpeakerAssembly.from_dict(_read_object(path))
        if item.project_id != self.project_id:
            raise ValueError("SpeakerAssembly belongs to a different project")
        return item

    def create(self, *, name: str, description: str = "", assembly_id: str | None = None) -> SpeakerAssembly:
        item = SpeakerAssembly(
            assembly_id=assembly_id or f"SA-{uuid.uuid4()}",
            project_id=self.project_id,
            name=name.strip(),
            description=description,
        )
        if self._path(item.assembly_id).exists():
            raise ValueError(f"SpeakerAssembly already exists: {item.assembly_id}")
        return self._save(item)

    def update(self, assembly_id: str, **changes: Any) -> SpeakerAssembly:
        current = self.get(assembly_id)
        forbidden = {"assembly_id", "project_id", "instances", "created_at", "schema_version"}
        rejected = forbidden.intersection(changes)
        if rejected:
            raise ValueError(f"Immutable SpeakerAssembly fields: {', '.join(sorted(rejected))}")
        return self._save(replace(current, **changes, updated_at=utc_now()))

    def archive(self, assembly_id: str) -> SpeakerAssembly:
        return self.update(assembly_id, archived_at=utc_now())

    @staticmethod
    def _compact(instances: Iterable[GeometryInstance]) -> tuple[GeometryInstance, ...]:
        return tuple(replace(item, order_index=index) for index, item in enumerate(instances))

    def add_instance(
        self,
        assembly_id: str,
        *,
        geometry: dict[str, Any],
        name: str,
        description: str = "",
        arrangement: str = "normal",
        transform: SpatialTransform | dict[str, Any] | None = None,
        instance_id: str | None = None,
    ) -> SpeakerAssembly:
        current = self.get(assembly_id)
        if current.archived_at:
            raise ValueError("Archived SpeakerAssembly cannot be edited")
        snapshot = dict(geometry)
        geometry_id = str(snapshot.get("geometry_id") or "")
        if str(snapshot.get("project_id") or "") != self.project_id:
            raise ValueError("Geometry belongs to a different project")
        item = GeometryInstance(
            instance_id=instance_id or f"SAI-{uuid.uuid4()}",
            geometry_id=geometry_id,
            geometry_snapshot=snapshot,
            geometry_snapshot_hash=geometry_snapshot_hash(snapshot),
            name=name.strip(),
            description=description,
            arrangement=arrangement,
            transform=transform if isinstance(transform, SpatialTransform) else SpatialTransform.from_dict(transform),
            order_index=len(current.instances),
        )
        return self._save(replace(current, instances=(*current.instances, item), updated_at=utc_now()))

    def update_instance(
        self,
        assembly_id: str,
        instance_id: str,
        *,
        geometry: dict[str, Any] | None = None,
        **changes: Any,
    ) -> SpeakerAssembly:
        current = self.get(assembly_id)
        if current.archived_at:
            raise ValueError("Archived SpeakerAssembly cannot be edited")
        index = next((idx for idx, item in enumerate(current.instances) if item.instance_id == instance_id), None)
        if index is None:
            raise KeyError(f"Unknown Geometry instance: {instance_id}")
        item = current.instances[index]
        forbidden = {"instance_id", "created_at", "order_index", "geometry_snapshot_hash"}
        rejected = forbidden.intersection(changes)
        if rejected:
            raise ValueError(f"Immutable Geometry instance fields: {', '.join(sorted(rejected))}")
        if "transform" in changes and not isinstance(changes["transform"], SpatialTransform):
            changes["transform"] = SpatialTransform.from_dict(changes["transform"])
        if geometry is not None:
            snapshot = dict(geometry)
            if str(snapshot.get("project_id") or "") != self.project_id:
                raise ValueError("Geometry belongs to a different project")
            changes["geometry_id"] = str(snapshot.get("geometry_id") or "")
            changes["geometry_snapshot"] = snapshot
            changes["geometry_snapshot_hash"] = geometry_snapshot_hash(snapshot)
        updated = replace(item, **changes, updated_at=utc_now())
        items = list(current.instances)
        items[index] = updated
        return self._save(replace(current, instances=tuple(items), updated_at=utc_now()))

    def move_instance(self, assembly_id: str, instance_id: str, new_index: int) -> SpeakerAssembly:
        current = self.get(assembly_id)
        if current.archived_at:
            raise ValueError("Archived SpeakerAssembly cannot be edited")
        items = list(current.instances)
        index = next((idx for idx, item in enumerate(items) if item.instance_id == instance_id), None)
        if index is None:
            raise KeyError(f"Unknown Geometry instance: {instance_id}")
        item = items.pop(index)
        target = max(0, min(int(new_index), len(items)))
        items.insert(target, item)
        return self._save(replace(current, instances=self._compact(items), updated_at=utc_now()))

    def remove_instance(self, assembly_id: str, instance_id: str) -> SpeakerAssembly:
        current = self.get(assembly_id)
        if current.archived_at:
            raise ValueError("Archived SpeakerAssembly cannot be edited")
        items = [item for item in current.instances if item.instance_id != instance_id]
        if len(items) == len(current.instances):
            raise KeyError(f"Unknown Geometry instance: {instance_id}")
        return self._save(replace(current, instances=self._compact(items), updated_at=utc_now()))
