"""Central versioned driver catalogue and immutable simulation snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import base64
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any
import uuid


DRIVER_SCHEMA_VERSION = 1
DRIVER_KINDS = {"compression_driver", "cone_driver", "generic_test", "future_unknown"}
DRIVER_ORIGINS = {"built_in", "user", "imported"}
TRUST_STATES = {"verified", "user_asserted", "unverified"}
ALLOWED_UNITS = {
    "1", "Hz", "m", "m2", "m3", "kg", "ohm", "H", "W", "V", "A",
    "N/A", "T*m", "m/N", "N*s/m", "Pa*s/m3", "kg/m4", "deg", "rad",
    "mm", "cm2", "g", "mH",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


@dataclass(frozen=True)
class DriverDefinition:
    driver_id: str
    manufacturer: str
    model: str
    variant: str = ""
    kind: str = "future_unknown"
    origin: str = "user"
    created_at: str = field(default_factory=_now)
    archived_at: str | None = None
    read_only: bool = False
    schema_version: int = DRIVER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.driver_id or not self.model.strip():
            raise ValueError("driver_id and model are required")
        if self.kind not in DRIVER_KINDS:
            raise ValueError(f"Unsupported driver kind: {self.kind}")
        if self.origin not in DRIVER_ORIGINS:
            raise ValueError(f"Unsupported driver origin: {self.origin}")


@dataclass(frozen=True)
class DriverRevision:
    revision_id: str
    driver_id: str
    revision_number: int
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    le_network_hash: str | None = None
    le_network_name: str | None = None
    network_description: dict[str, Any] = field(default_factory=dict)
    completeness: str = "incomplete"
    created_at: str = field(default_factory=_now)
    schema_version: int = DRIVER_SCHEMA_VERSION
    extensions: dict[str, Any] = field(default_factory=dict)
    revision_hash: str = ""

    def payload_without_hash(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("revision_hash", None)
        return payload

    def with_hash(self) -> "DriverRevision":
        return replace(self, revision_hash=_hash(self.payload_without_hash()))


@dataclass(frozen=True)
class DriverSnapshot:
    snapshot_id: str
    driver: dict[str, Any]
    revision: dict[str, Any]
    revision_hash: str
    le_network_hash: str | None
    le_network_base64: str | None
    created_at: str
    schema_version: int = DRIVER_SCHEMA_VERSION
    snapshot_hash: str = ""

    def payload_without_hash(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("snapshot_hash", None)
        return payload

    def with_hash(self) -> "DriverSnapshot":
        return replace(self, snapshot_hash=_hash(self.payload_without_hash()))

    def verify(self) -> bool:
        if self.revision_hash != _hash({key: value for key, value in self.revision.items() if key != "revision_hash"}):
            return False
        if self.le_network_base64 is not None and hashlib.sha256(base64.b64decode(self.le_network_base64)).hexdigest() != self.le_network_hash:
            return False
        return self.snapshot_hash == _hash(self.payload_without_hash())


@dataclass(frozen=True)
class ImportReport:
    ok: bool
    driver_id: str | None
    revision_id: str | None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeAssetPreview:
    source_path: str
    file_name: str
    size_bytes: int
    sha256: str


class DriverLibrary:
    def __init__(self, library_root: str | Path) -> None:
        self.root = Path(library_root)
        self.db_path = self.root / "library.sqlite"
        self.assets_root = self.root / "drivers" / "assets" / "sha256"
        self.root.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _open(self):
        with closing(self._connect()) as conn:
            with conn:
                yield conn

    def _init_schema(self) -> None:
        with self._open() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS driver_definitions (
                    driver_id TEXT PRIMARY KEY,
                    manufacturer TEXT NOT NULL,
                    model TEXT NOT NULL,
                    variant TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    archived_at TEXT,
                    read_only INTEGER NOT NULL DEFAULT 0,
                    schema_version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS driver_revisions (
                    revision_id TEXT PRIMARY KEY,
                    driver_id TEXT NOT NULL,
                    revision_number INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    revision_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(driver_id) REFERENCES driver_definitions(driver_id),
                    UNIQUE(driver_id, revision_number)
                );
                CREATE INDEX IF NOT EXISTS idx_driver_search
                    ON driver_definitions(kind, manufacturer, model, archived_at);
                CREATE INDEX IF NOT EXISTS idx_driver_revision_driver
                    ON driver_revisions(driver_id, revision_number DESC);
                """
            )

    @staticmethod
    def _validate_parameters(parameters: dict[str, dict[str, Any]]) -> list[str]:
        errors: list[str] = []
        for name, item in parameters.items():
            if not isinstance(item, dict):
                errors.append(f"parameters.{name} must be an object")
                continue
            unit = str(item.get("unit") or "")
            if not unit:
                errors.append(f"parameters.{name}.unit is required")
            elif unit not in ALLOWED_UNITS:
                errors.append(f"parameters.{name}.unit is unsupported: {unit}")
            value = item.get("value")
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                errors.append(f"parameters.{name}.value must be numeric or null")
        return errors

    def create_definition(self, definition: DriverDefinition, revision: DriverRevision) -> DriverRevision:
        if revision.driver_id != definition.driver_id:
            raise ValueError("Revision driver_id mismatch")
        errors = self._validate_parameters(revision.parameters)
        if errors:
            raise ValueError("; ".join(errors))
        revision = revision.with_hash()
        with self._open() as conn:
            conn.execute(
                "INSERT INTO driver_definitions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    definition.driver_id, definition.manufacturer, definition.model,
                    definition.variant, definition.kind, definition.origin,
                    definition.created_at, definition.archived_at,
                    int(definition.read_only), definition.schema_version,
                ),
            )
            conn.execute(
                "INSERT INTO driver_revisions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    revision.revision_id, revision.driver_id, revision.revision_number,
                    json.dumps(asdict(revision), ensure_ascii=False, sort_keys=True),
                    revision.revision_hash, revision.created_at,
                ),
            )
        return revision

    def get_definition(self, driver_id: str) -> DriverDefinition:
        with self._open() as conn:
            row = conn.execute("SELECT * FROM driver_definitions WHERE driver_id=?", (driver_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown driver: {driver_id}")
        return DriverDefinition(
            driver_id=row["driver_id"], manufacturer=row["manufacturer"], model=row["model"],
            variant=row["variant"], kind=row["kind"], origin=row["origin"],
            created_at=row["created_at"], archived_at=row["archived_at"],
            read_only=bool(row["read_only"]), schema_version=int(row["schema_version"]),
        )

    def get_revision(self, revision_id: str) -> DriverRevision:
        with self._open() as conn:
            row = conn.execute("SELECT payload_json FROM driver_revisions WHERE revision_id=?", (revision_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown driver revision: {revision_id}")
        return DriverRevision(**json.loads(row["payload_json"]))

    def list_definitions(self, *, query: str = "", kind: str | None = None, include_archived: bool = False) -> list[DriverDefinition]:
        clauses: list[str] = []
        values: list[Any] = []
        if not include_archived:
            clauses.append("archived_at IS NULL")
        if kind:
            clauses.append("kind=?")
            values.append(kind)
        if query.strip():
            clauses.append("lower(manufacturer || ' ' || model || ' ' || variant) LIKE ?")
            values.append(f"%{query.strip().lower()}%")
        sql = "SELECT driver_id FROM driver_definitions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY lower(manufacturer), lower(model), lower(variant)"
        with self._open() as conn:
            ids = [str(row[0]) for row in conn.execute(sql, values).fetchall()]
        return [self.get_definition(item) for item in ids]

    def revisions(self, driver_id: str) -> list[DriverRevision]:
        with self._open() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM driver_revisions WHERE driver_id=? ORDER BY revision_number", (driver_id,)
            ).fetchall()
        return [DriverRevision(**json.loads(row[0])) for row in rows]

    def create_revision(self, driver_id: str, *, parameters: dict[str, dict[str, Any]], provenance: dict[str, Any], le_network_hash: str | None = None, le_network_name: str | None = None, network_description: dict[str, Any] | None = None, completeness: str = "incomplete", extensions: dict[str, Any] | None = None) -> DriverRevision:
        definition = self.get_definition(driver_id)
        if definition.read_only:
            raise ValueError("Built-in drivers are read-only")
        errors = self._validate_parameters(parameters)
        if errors:
            raise ValueError("; ".join(errors))
        existing = self.revisions(driver_id)
        revision = DriverRevision(
            revision_id=f"DR-{uuid.uuid4()}", driver_id=driver_id,
            revision_number=(existing[-1].revision_number + 1 if existing else 1),
            parameters=dict(parameters), provenance=dict(provenance),
            le_network_hash=le_network_hash, le_network_name=le_network_name,
            network_description=dict(network_description or {}), completeness=completeness,
            extensions=dict(extensions or {}),
        ).with_hash()
        with self._open() as conn:
            conn.execute("INSERT INTO driver_revisions VALUES (?, ?, ?, ?, ?, ?)", (
                revision.revision_id, revision.driver_id, revision.revision_number,
                json.dumps(asdict(revision), ensure_ascii=False, sort_keys=True),
                revision.revision_hash, revision.created_at,
            ))
        return revision

    def duplicate(self, driver_id: str, *, model: str | None = None) -> tuple[DriverDefinition, DriverRevision]:
        source = self.get_definition(driver_id)
        latest = self.revisions(driver_id)[-1]
        duplicate = DriverDefinition(
            driver_id=f"D-{uuid.uuid4()}", manufacturer=source.manufacturer,
            model=model or f"{source.model} Copy", variant=source.variant,
            kind=source.kind, origin="user",
        )
        revision = replace(latest, revision_id=f"DR-{uuid.uuid4()}", driver_id=duplicate.driver_id, revision_number=1, created_at=_now(), revision_hash="")
        return duplicate, self.create_definition(duplicate, revision)

    def archive(self, driver_id: str) -> DriverDefinition:
        definition = self.get_definition(driver_id)
        if definition.read_only:
            raise ValueError("Built-in drivers cannot be archived")
        archived = replace(definition, archived_at=_now())
        with self._open() as conn:
            conn.execute("UPDATE driver_definitions SET archived_at=? WHERE driver_id=?", (archived.archived_at, driver_id))
        return archived

    @staticmethod
    def preview_le_asset(source: str | Path) -> LeAssetPreview:
        source_path = Path(source)
        if not source_path.exists():
            raise ValueError(f"LE network file does not exist: {source_path}")
        if not source_path.is_file():
            raise ValueError(f"LE network path is not a file: {source_path}")
        try:
            raw = source_path.read_bytes()
        except OSError as exc:
            raise ValueError(f"LE network file cannot be read: {source_path}") from exc
        if not raw:
            raise ValueError("LE network file is empty")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("LE network file must be readable UTF-8 text") from exc
        if not text.strip():
            raise ValueError("LE network file contains no network definition")
        digest = hashlib.sha256(raw).hexdigest()
        return LeAssetPreview(
            source_path=str(source_path.resolve()), file_name=source_path.name,
            size_bytes=len(raw), sha256=digest,
        )

    def store_le_asset(self, source: str | Path, *, expected_sha256: str | None = None) -> tuple[str, Path, str]:
        source_path = Path(source)
        preview = self.preview_le_asset(source_path)
        raw = source_path.read_bytes()
        digest = preview.sha256
        if expected_sha256 and digest != expected_sha256:
            raise ValueError("LE network file changed after preview; select it again")
        destination = self.assets_root / digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source_path, destination)
        text = raw.decode("utf-8-sig")
        return digest, destination, text

    def seed_generic25(self, source: str | Path) -> DriverRevision:
        try:
            return self.revisions("generic25")[-1]
        except (KeyError, IndexError):
            pass
        digest, _, _ = self.store_le_asset(source)
        definition = DriverDefinition(
            driver_id="generic25", manufacturer="ATH", model="Generic 25 mm",
            kind="generic_test", origin="built_in", read_only=True,
        )
        revision = DriverRevision(
            revision_id="generic25-r1", driver_id="generic25", revision_number=1,
            parameters={"exit_diameter": {"value": 0.025, "unit": "m"}},
            provenance={
                "source": str(Path(source)), "file_sha256": digest,
                "licence_note": "Installed ATH library asset; retained locally for execution.",
                "trust": "verified",
            },
            le_network_hash=digest, le_network_name=Path(source).name,
            completeness="simulation_ready",
        )
        return self.create_definition(definition, revision)

    def snapshot(self, revision_id: str) -> DriverSnapshot:
        revision = self.get_revision(revision_id)
        definition = self.get_definition(revision.driver_id)
        le_base64: str | None = None
        if revision.le_network_hash:
            asset = self.assets_root / revision.le_network_hash
            if not asset.exists():
                raise FileNotFoundError(f"LE asset is missing: {asset}")
            le_base64 = base64.b64encode(asset.read_bytes()).decode("ascii")
        return DriverSnapshot(
            snapshot_id=f"DS-{uuid.uuid4()}", driver=asdict(definition), revision=asdict(revision),
            revision_hash=revision.revision_hash, le_network_hash=revision.le_network_hash,
            le_network_base64=le_base64, created_at=_now(),
        ).with_hash()

    def export_json(self, driver_id: str) -> dict[str, Any]:
        revisions = self.revisions(driver_id)
        assets: dict[str, str] = {}
        for revision in revisions:
            if revision.le_network_hash:
                asset = self.assets_root / revision.le_network_hash
                if asset.exists():
                    assets[revision.le_network_hash] = base64.b64encode(asset.read_bytes()).decode("ascii")
        return {
            "schema": "wut.driver-library", "schema_version": DRIVER_SCHEMA_VERSION,
            "definition": asdict(self.get_definition(driver_id)),
            "revisions": [asdict(item) for item in revisions],
            "le_assets_base64": assets,
        }

    def import_json(self, payload: dict[str, Any]) -> ImportReport:
        errors: list[str] = []
        if payload.get("schema") != "wut.driver-library":
            errors.append("schema must be wut.driver-library")
        if int(payload.get("schema_version") or 0) != DRIVER_SCHEMA_VERSION:
            errors.append(f"unsupported schema_version: {payload.get('schema_version')}")
        definition_payload = payload.get("definition")
        revisions_payload = payload.get("revisions")
        if not isinstance(definition_payload, dict):
            errors.append("definition must be an object")
        if not isinstance(revisions_payload, list) or not revisions_payload:
            errors.append("revisions must be a non-empty array")
        if errors:
            return ImportReport(False, None, None, tuple(errors))
        try:
            definition = DriverDefinition(**definition_payload)
            if definition.origin == "built_in" or definition.read_only:
                definition = replace(definition, driver_id=f"D-{uuid.uuid4()}", origin="imported", read_only=False)
            else:
                definition = replace(definition, origin="imported")
            first_payload = dict(revisions_payload[0])
            assets_payload = payload.get("le_assets_base64") or {}
            if not isinstance(assets_payload, dict):
                raise ValueError("le_assets_base64 must be an object")
            for digest, encoded in assets_payload.items():
                raw = base64.b64decode(str(encoded), validate=True)
                if hashlib.sha256(raw).hexdigest() != str(digest):
                    raise ValueError(f"LE asset hash mismatch: {digest}")
                destination = self.assets_root / str(digest)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    destination.write_bytes(raw)
            first_payload.update(driver_id=definition.driver_id, revision_id=f"DR-{uuid.uuid4()}", revision_number=1, revision_hash="", created_at=_now())
            revision = DriverRevision(**first_payload)
            created = self.create_definition(definition, revision)
            for number, raw in enumerate(revisions_payload[1:], start=2):
                candidate = dict(raw)
                self.create_revision(
                    definition.driver_id,
                    parameters=dict(candidate.get("parameters") or {}),
                    provenance=dict(candidate.get("provenance") or {}),
                    le_network_hash=candidate.get("le_network_hash"),
                    le_network_name=candidate.get("le_network_name"),
                    network_description=dict(candidate.get("network_description") or {}),
                    completeness=str(candidate.get("completeness") or "incomplete"),
                    extensions=dict(candidate.get("extensions") or {}),
                )
            return ImportReport(True, definition.driver_id, created.revision_id)
        except (TypeError, ValueError, sqlite3.IntegrityError) as exc:
            return ImportReport(False, None, None, (str(exc),))
