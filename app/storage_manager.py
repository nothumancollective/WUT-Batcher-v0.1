"""Centralized Project Library metadata and path management.

This module is intentionally added as a standalone building block before runtime wiring.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


LIBRARY_SCHEMA_VERSION = 1
PROJECT_DISPLAY_PREFIX = "P"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _uuid4() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class LibraryPaths:
    root: Path
    projects_dir: Path
    metadata_json: Path
    index_db: Path


@dataclass(frozen=True)
class LibraryState:
    library_uid: str
    schema_version: int
    created_at: str
    project_counter_next: int


@dataclass(frozen=True)
class ProjectIdentity:
    display_number: str
    project_uid: str

    @property
    def folder_name(self) -> str:
        return f"{self.display_number}__{self.project_uid}"


class StorageManager:
    """Authoritative Project Library root and ID allocator.

    Wiring into the broader application is handled in later phases.
    """

    def __init__(self, library_root: str | Path) -> None:
        root = Path(library_root).expanduser()
        if not root.is_absolute():
            root = (Path.cwd() / root).resolve()
        else:
            root = root.resolve()
        self._paths = LibraryPaths(
            root=root,
            projects_dir=root / "projects",
            metadata_json=root / "library.json",
            index_db=root / "library.sqlite",
        )

    @property
    def paths(self) -> LibraryPaths:
        return self._paths

    def ensure_library_root(self) -> LibraryState:
        self._paths.root.mkdir(parents=True, exist_ok=True)
        self._paths.projects_dir.mkdir(parents=True, exist_ok=True)
        self._init_index_db()
        state = self.load_library_state()
        self._write_metadata_json(state)
        return state

    def load_library_state(self) -> LibraryState:
        with closing(sqlite3.connect(str(self._paths.index_db))) as conn:
            conn.row_factory = sqlite3.Row
            library_uid = self._meta_get(conn, "library_uid")
            schema_version_raw = self._meta_get(conn, "schema_version")
            created_at = self._meta_get(conn, "created_at")
            counter_raw = self._counter_get(conn, "project_counter_next")

        schema_version = int(schema_version_raw or LIBRARY_SCHEMA_VERSION)
        counter = max(1, int(counter_raw or 1))
        return LibraryState(
            library_uid=str(library_uid or ""),
            schema_version=schema_version,
            created_at=str(created_at or ""),
            project_counter_next=counter,
        )

    def allocate_project_identity(self) -> ProjectIdentity:
        self.ensure_library_root()
        with closing(sqlite3.connect(str(self._paths.index_db))) as conn:
            conn.row_factory = sqlite3.Row
            current = self._counter_get(conn, "project_counter_next")
            current_value = max(1, int(current or 1))
            next_value = current_value + 1
            conn.execute(
                """
                INSERT INTO library_counters(counter_key, next_value)
                VALUES (?, ?)
                ON CONFLICT(counter_key) DO UPDATE SET next_value = excluded.next_value
                """,
                ("project_counter_next", int(next_value)),
            )
            conn.commit()

        display = f"{PROJECT_DISPLAY_PREFIX}{current_value:04d}"
        return ProjectIdentity(display_number=display, project_uid=_uuid4())

    def _init_index_db(self) -> None:
        self._paths.index_db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(self._paths.index_db))) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS library_meta (
                    meta_key TEXT PRIMARY KEY,
                    meta_value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS library_counters (
                    counter_key TEXT PRIMARY KEY,
                    next_value INTEGER NOT NULL
                )
                """
            )
            self._meta_put_if_missing(conn, "library_uid", _uuid4())
            self._meta_put_if_missing(conn, "schema_version", str(LIBRARY_SCHEMA_VERSION))
            self._meta_put_if_missing(conn, "created_at", _utc_now_iso())
            self._counter_put_if_missing(conn, "project_counter_next", 1)
            conn.commit()

    @staticmethod
    def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute(
            "SELECT meta_value FROM library_meta WHERE meta_key = ?",
            (str(key),),
        ).fetchone()
        if row is None:
            return None
        return str(row[0])

    @staticmethod
    def _counter_get(conn: sqlite3.Connection, key: str) -> int | None:
        row = conn.execute(
            "SELECT next_value FROM library_counters WHERE counter_key = ?",
            (str(key),),
        ).fetchone()
        if row is None:
            return None
        return int(row[0])

    @staticmethod
    def _meta_put_if_missing(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            """
            INSERT INTO library_meta(meta_key, meta_value)
            VALUES (?, ?)
            ON CONFLICT(meta_key) DO NOTHING
            """,
            (str(key), str(value)),
        )

    @staticmethod
    def _counter_put_if_missing(conn: sqlite3.Connection, key: str, value: int) -> None:
        conn.execute(
            """
            INSERT INTO library_counters(counter_key, next_value)
            VALUES (?, ?)
            ON CONFLICT(counter_key) DO NOTHING
            """,
            (str(key), int(value)),
        )

    def _write_metadata_json(self, state: LibraryState) -> None:
        payload = {
            "library_uid": str(state.library_uid),
            "schema_version": int(state.schema_version),
            "created_at": str(state.created_at),
            "project_counter_next": int(state.project_counter_next),
        }
        self._paths.metadata_json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
