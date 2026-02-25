"""Centralized Project Library metadata and path management.

This module is intentionally added as a standalone building block before runtime wiring.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import uuid


LIBRARY_SCHEMA_VERSION = 1
PROJECT_DISPLAY_PREFIX = "P"
LOGGER = logging.getLogger(__name__)
_SQLITE_TIMEOUT_SECONDS = 5.0
_SQLITE_BUSY_TIMEOUT_MS = 5000
_WINDOWS_INVALID_SEGMENT_CHARS_RE = re.compile(r'[<>:"|?*]')


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


@dataclass(frozen=True)
class LibraryRootChangeResult:
    ok: bool
    normalized_root: str
    manager: "StorageManager | None" = None
    state: "LibraryState | None" = None
    error_message: str | None = None


class StorageManager:
    """Authoritative Project Library root and ID allocator.

    Wiring into the broader application is handled in later phases.
    """

    def __init__(self, library_root: str | Path) -> None:
        requested_root = str(library_root)
        root = self.normalize_library_root(library_root)
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                "StorageManager init: requested_root=%s normalized_root=%s",
                requested_root,
                str(root),
            )
        self._paths = LibraryPaths(
            root=root,
            projects_dir=root / "projects",
            metadata_json=root / "library.json",
            index_db=root / "library.sqlite",
        )

    @property
    def paths(self) -> LibraryPaths:
        return self._paths

    @classmethod
    def try_set_library_root(cls, new_root: str | Path) -> LibraryRootChangeResult:
        normalized = ""
        try:
            normalized_path = cls.normalize_library_root(new_root)
            normalized = str(normalized_path)
            manager = cls(normalized_path)
            state = manager.ensure_library_root()
            return LibraryRootChangeResult(
                ok=True,
                normalized_root=str(manager.paths.root),
                manager=manager,
                state=state,
                error_message=None,
            )
        except Exception as exc:
            if LOGGER.isEnabledFor(logging.DEBUG):
                LOGGER.debug(
                    "try_set_library_root failed: requested_root=%s normalized_root=%s",
                    str(new_root),
                    normalized,
                    exc_info=True,
                )
            return LibraryRootChangeResult(
                ok=False,
                normalized_root=normalized,
                manager=None,
                state=None,
                error_message=cls._friendly_root_error_message(exc),
            )

    @staticmethod
    def normalize_library_root(library_root: str | Path) -> Path:
        raw = str(library_root or "")
        token = raw.strip()
        if not token:
            raise ValueError("Project Library Location cannot be empty.")
        token = token.rstrip(" .")
        if not token:
            raise ValueError("Project Library Location cannot end with only spaces or dots.")
        expanded = os.path.expanduser(token)
        candidate = Path(expanded)
        if os.name == "nt":
            StorageManager._validate_windows_segments(candidate)
        if not candidate.is_absolute():
            return (Path.cwd() / candidate).resolve(strict=False)
        return candidate.resolve(strict=False)

    def ensure_library_root(self) -> LibraryState:
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug("ensure_library_root start: root=%s", str(self._paths.root))
        self._paths.root.mkdir(parents=True, exist_ok=True)
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug("ensure_library_root mkdir root ok: %s", str(self._paths.root))
        self._paths.projects_dir.mkdir(parents=True, exist_ok=True)
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug("ensure_library_root mkdir projects ok: %s", str(self._paths.projects_dir))
        self._init_index_db(metadata_hint=self._read_metadata_json())
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug("ensure_library_root sqlite initialized: %s", str(self._paths.index_db))
        state = self.load_library_state()
        self._write_metadata_json(state)
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug("ensure_library_root metadata json written: %s", str(self._paths.metadata_json))
        return state

    def load_library_state(self) -> LibraryState:
        with closing(self._open_connection()) as conn:
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
        with closing(self._open_connection()) as conn:
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

    def _init_index_db(self, metadata_hint: dict[str, object] | None = None) -> None:
        hint = dict(metadata_hint or {})
        library_uid_hint = str(hint.get("library_uid") or "").strip() or _uuid4()
        schema_hint = self._coerce_int(hint.get("schema_version"), fallback=LIBRARY_SCHEMA_VERSION, minimum=1)
        created_at_hint = str(hint.get("created_at") or "").strip() or _utc_now_iso()
        counter_hint = self._coerce_int(hint.get("project_counter_next"), fallback=1, minimum=1)
        self._paths.index_db.parent.mkdir(parents=True, exist_ok=True)
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug("init_index_db open sqlite: %s", str(self._paths.index_db))
        with closing(self._open_connection()) as conn:
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
            self._meta_put_if_missing(conn, "library_uid", library_uid_hint)
            self._meta_put_if_missing(conn, "schema_version", str(schema_hint))
            self._meta_put_if_missing(conn, "created_at", created_at_hint)
            self._counter_put_if_missing(conn, "project_counter_next", counter_hint)
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

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._paths.index_db), timeout=_SQLITE_TIMEOUT_SECONDS)
        conn.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS}")
        return conn

    def _read_metadata_json(self) -> dict[str, object]:
        path = self._paths.metadata_json
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    @staticmethod
    def _coerce_int(value: object, *, fallback: int, minimum: int) -> int:
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except Exception:
            parsed = int(fallback)
        return max(int(minimum), int(parsed))

    @staticmethod
    def _validate_windows_segments(path: Path) -> None:
        parts = list(path.parts)
        if not parts:
            raise ValueError("Project Library Location is invalid.")
        start_index = 1 if path.is_absolute() else 0
        for segment in parts[start_index:]:
            token = str(segment or "")
            if not token:
                continue
            if token.rstrip(" .") != token:
                raise ValueError("Folder names in Project Library Location cannot end with spaces or dots.")
            if _WINDOWS_INVALID_SEGMENT_CHARS_RE.search(token):
                raise ValueError("Project Library Location contains invalid characters.")

    @staticmethod
    def _friendly_root_error_message(exc: Exception) -> str:
        if isinstance(exc, ValueError):
            return str(exc) or "Project Library Location is invalid."
        if isinstance(exc, FileExistsError):
            return "The selected Project Library Location is a file. Please choose a folder."
        if isinstance(exc, PermissionError):
            return "WUT Batcher cannot write to this folder. Choose a writable folder and try again."
        if isinstance(exc, sqlite3.OperationalError):
            detail = str(exc).strip().lower()
            if "locked" in detail or "busy" in detail:
                return (
                    "The Project Library database is currently in use. "
                    "Close other app instances and try again."
                )
            return "Could not initialize Project Library database. Check folder permissions and try again."
        if isinstance(exc, sqlite3.DatabaseError):
            return (
                "The Project Library database is unreadable or corrupted. "
                "Choose another folder or repair library.sqlite."
            )
        if isinstance(exc, OSError):
            return "Project Library Location is invalid or inaccessible. Choose another folder and try again."
        return "Could not switch Project Library Location. Please try again."

    @classmethod
    def user_error_message(cls, exc: Exception) -> str:
        return cls._friendly_root_error_message(exc)

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
