"""SQL-first dataset storage (project SQLite + global SQLite)."""

from __future__ import annotations

import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

from app.models import Batch, Project, VersionSpec


SCHEMA_VERSION = "2.5"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _serialize_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    return _to_json(value)


def _deserialize_value(value: Optional[str]) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _stable_graph_id(
    project_id: str,
    batch_id: str,
    version_id: str,
    run_id: Optional[str],
    graph_type: str,
    variant: str,
    x_name: str,
    y_name: str,
    source_file: str,
) -> str:
    raw = "|".join([project_id, batch_id, version_id, run_id or "", graph_type, variant, x_name, y_name, source_file])
    return "G" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _canonical_effective_params(
    parameters: Dict[str, Any],
    unset_parameters: Sequence[str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    keys = sorted(set(parameters.keys()).union(set(unset_parameters)))
    for key in keys:
        if key in parameters:
            payload[str(key)] = {"is_set": 1, "value": parameters[key]}
        else:
            payload[str(key)] = {"is_set": 0, "value": None}
    return payload


def _version_config_hash(
    parameters: Dict[str, Any],
    unset_parameters: Sequence[str],
) -> str:
    canonical = _to_json(_canonical_effective_params(parameters, unset_parameters))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stable_series_id(
    graph_id: str,
    *,
    series_kind: str,
    angle_deg: Optional[float],
    label: str,
) -> str:
    angle_token = "" if angle_deg is None else f"{float(angle_deg):.6f}"
    raw = "|".join([graph_id, series_kind, angle_token, label])
    return "S" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _stable_polar_id(
    *,
    project_id: str,
    batch_id: str,
    version_id: str,
    run_id: Optional[str],
    orientation: str,
    file_hash: str,
) -> str:
    raw = "|".join([project_id, batch_id, version_id, run_id or "", orientation, file_hash])
    return "P" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class SqlDatasetStore:
    def __init__(
        self,
        project_root: str | Path,
        *,
        library_root: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.library_root = Path(library_root) if library_root is not None else self.project_root.parent
        self.dataset_dir = self.project_root / "dataset"
        self.tables_dir = self.project_root / "tables"
        self.project_db_path = self.dataset_dir / "project.sqlite"
        self.global_db_path = self.library_root / "global.sqlite"
        self.schema_path = self.dataset_dir / "schema.json"
        self.project_table_csv = self.tables_dir / "project_versions.csv"

        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.tables_dir.mkdir(parents=True, exist_ok=True)

        self._init_db(self.project_db_path)
        self._init_db(self.global_db_path)
        self.persist_schema_descriptor()

    def _connect(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _open_conn(self, path: Path):
        conn = self._connect(path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._open_conn(path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    project_name TEXT NOT NULL,
                    constraints_snapshot TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS batches (
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    batch_name TEXT NOT NULL,
                    sweep_definitions TEXT,
                    sweep_mode TEXT,
                    sim_export_params TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, batch_id),
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS versions (
                    version_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    project_name TEXT,
                    batch_id TEXT NOT NULL,
                    batch_name TEXT,
                    resolved_parameters_snapshot TEXT,
                    version_config_hash TEXT,
                    status TEXT NOT NULL,
                    duration_seconds REAL,
                    ath_length_mm REAL,
                    ath_width_mm REAL,
                    ath_height_mm REAL,
                    tool_versions TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY (project_id, batch_id) REFERENCES batches(project_id, batch_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS version_params (
                    version_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    param_name TEXT NOT NULL,
                    value TEXT,
                    unit TEXT,
                    is_set INTEGER NOT NULL CHECK (is_set IN (0, 1)),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (version_id, param_name),
                    FOREIGN KEY (version_id) REFERENCES versions(version_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS ath_dimensions (
                    run_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    length_mm REAL,
                    width_mm REAL,
                    height_mm REAL,
                    raw_line TEXT,
                    source_file TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, version_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
                    FOREIGN KEY (version_id) REFERENCES versions(version_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    git_commit TEXT,
                    app_version TEXT,
                    settings_hash TEXT,
                    error_summary TEXT,
                    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
                    tag TEXT
                );

                CREATE TABLE IF NOT EXISTS run_versions (
                    run_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_seconds REAL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    error_summary TEXT,
                    PRIMARY KEY (run_id, version_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
                    FOREIGN KEY (version_id) REFERENCES versions(version_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS graphs (
                    graph_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    run_id TEXT,
                    graph_type TEXT,
                    graph_kind TEXT,
                    variant TEXT,
                    x_name TEXT,
                    y_name TEXT,
                    x_axis TEXT,
                    y_axis TEXT,
                    x_unit TEXT,
                    y_unit TEXT,
                    source_file TEXT,
                    export_meta TEXT,
                    meta_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (version_id) REFERENCES versions(version_id) ON DELETE CASCADE,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS graph_series (
                    series_id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    series_kind TEXT,
                    angle_deg REAL,
                    label TEXT,
                    meta_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS graph_points (
                    series_id TEXT NOT NULL,
                    point_index INTEGER NOT NULL,
                    x_value REAL,
                    y_value REAL,
                    y_imag REAL,
                    PRIMARY KEY (series_id, point_index),
                    FOREIGN KEY (series_id) REFERENCES graph_series(series_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS polar_measurements (
                    polar_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    run_id TEXT,
                    graph_id TEXT,
                    orientation TEXT NOT NULL,
                    orientation_raw REAL,
                    norm_angle_deg REAL,
                    data_level_type TEXT,
                    data_base_unit TEXT,
                    data_absc_unit TEXT,
                    freq_min_hz REAL,
                    freq_max_hz REAL,
                    freq_count INTEGER NOT NULL,
                    angle_min_deg REAL,
                    angle_max_deg REAL,
                    angle_step_deg REAL,
                    angle_count INTEGER NOT NULL,
                    angles_deg_json TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    export_meta_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS polar_points (
                    polar_id TEXT NOT NULL,
                    freq_index INTEGER NOT NULL,
                    angle_index INTEGER NOT NULL,
                    freq_hz REAL NOT NULL,
                    angle_deg REAL NOT NULL,
                    re REAL NOT NULL,
                    im REAL NOT NULL,
                    PRIMARY KEY (polar_id, freq_index, angle_index),
                    FOREIGN KEY (polar_id) REFERENCES polar_measurements(polar_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS replication_queue (
                    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS compat_verification_results (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    fact_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    expected_json TEXT,
                    observed_json TEXT,
                    details_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS federation_profile (
                    installation_id TEXT PRIMARY KEY,
                    anonymous_user_id TEXT NOT NULL,
                    dataset_namespace TEXT NOT NULL,
                    allow_upload INTEGER NOT NULL DEFAULT 0 CHECK (allow_upload IN (0, 1)),
                    consent_scope TEXT NOT NULL DEFAULT 'unset',
                    consent_version TEXT,
                    consent_updated_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS federation_sync_state (
                    stream_name TEXT PRIMARY KEY,
                    last_cursor TEXT,
                    last_synced_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS federation_export_jobs (
                    export_id TEXT PRIMARY KEY,
                    installation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    item_counts_json TEXT,
                    payload_sha256 TEXT,
                    payload_bytes INTEGER,
                    error_summary TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS federation_tombstones (
                    tombstone_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    reason TEXT,
                    deleted_at TEXT NOT NULL,
                    uploaded_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_batches_project ON batches(project_id);
                CREATE INDEX IF NOT EXISTS idx_versions_project_batch ON versions(project_id, batch_id);
                CREATE INDEX IF NOT EXISTS idx_version_params_project_batch ON version_params(project_id, batch_id);
                CREATE INDEX IF NOT EXISTS idx_graphs_version ON graphs(version_id);
                CREATE INDEX IF NOT EXISTS idx_runs_project_batch ON runs(project_id, batch_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_run_versions_batch_status ON run_versions(project_id, batch_id, status);
                CREATE INDEX IF NOT EXISTS idx_polar_meas_version ON polar_measurements(version_id);
                CREATE INDEX IF NOT EXISTS idx_polar_meas_run ON polar_measurements(run_id);
                CREATE INDEX IF NOT EXISTS idx_polar_meas_batch ON polar_measurements(project_id, batch_id);
                CREATE INDEX IF NOT EXISTS idx_polar_meas_orientation ON polar_measurements(orientation);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_polar_meas_identity ON
                polar_measurements(project_id, version_id, coalesce(run_id, ''), orientation, file_hash);
                CREATE INDEX IF NOT EXISTS idx_polar_points_polar_freq ON polar_points(polar_id, freq_hz);
                CREATE INDEX IF NOT EXISTS idx_polar_points_polar_angle_freq ON polar_points(polar_id, angle_index, freq_hz);
                CREATE INDEX IF NOT EXISTS idx_polar_points_polar_angle ON polar_points(polar_id, angle_deg);
                CREATE INDEX IF NOT EXISTS idx_replication_queue_status ON replication_queue(status, queue_id);
                CREATE INDEX IF NOT EXISTS idx_compat_results_project_fact ON compat_verification_results(project_id, fact_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_federation_tombstones_entity
                ON federation_tombstones(entity_type, entity_id, deleted_at);
                """
            )
            self._migrate_schema(conn)

    def _table_columns(self, conn: sqlite3.Connection, table_name: str) -> List[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [str(row["name"]) for row in rows]

    def _ensure_graphs_columns(self, conn: sqlite3.Connection) -> None:
        columns = set(self._table_columns(conn, "graphs"))
        missing = []
        for name, sql_type in (
            ("run_id", "TEXT"),
            ("graph_kind", "TEXT"),
            ("variant", "TEXT"),
            ("x_axis", "TEXT"),
            ("y_axis", "TEXT"),
            ("meta_json", "TEXT"),
        ):
            if name not in columns:
                missing.append((name, sql_type))
        for name, sql_type in missing:
            conn.execute(f"ALTER TABLE graphs ADD COLUMN {name} {sql_type}")

    def _ensure_versions_columns(self, conn: sqlite3.Connection) -> None:
        columns = set(self._table_columns(conn, "versions"))
        if "version_config_hash" not in columns:
            conn.execute("ALTER TABLE versions ADD COLUMN version_config_hash TEXT")

    def _migrate_ath_dimensions_schema(self, conn: sqlite3.Connection) -> None:
        columns = self._table_columns(conn, "ath_dimensions")
        if not columns:
            return
        column_names = [str(name) for name in columns]
        pk_columns = [str(row["name"]) for row in conn.execute("PRAGMA table_info(ath_dimensions)").fetchall() if int(row["pk"]) > 0]
        if pk_columns == ["run_id", "version_id"]:
            return

        select_cols = [name for name in ("run_id", "version_id", "project_id", "batch_id", "length_mm", "width_mm", "height_mm", "raw_line", "source_file", "created_at") if name in column_names]
        select_sql = ", ".join(select_cols)
        old_rows = conn.execute(f"SELECT {select_sql} FROM ath_dimensions").fetchall()

        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE ath_dimensions_new (
                run_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                length_mm REAL,
                width_mm REAL,
                height_mm REAL,
                raw_line TEXT,
                source_file TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (run_id, version_id),
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
                FOREIGN KEY (version_id) REFERENCES versions(version_id) ON DELETE CASCADE
            )
            """
        )
        for row in old_rows:
            run_id = str(row["run_id"]) if "run_id" in row.keys() and row["run_id"] else "legacy"
            conn.execute(
                """
                INSERT INTO ath_dimensions_new (
                    run_id, version_id, project_id, batch_id, length_mm, width_mm, height_mm, raw_line, source_file, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(row["version_id"]),
                    str(row["project_id"]),
                    str(row["batch_id"]),
                    float(row["length_mm"]) if row["length_mm"] is not None else None,
                    float(row["width_mm"]) if row["width_mm"] is not None else None,
                    float(row["height_mm"]) if row["height_mm"] is not None else None,
                    str(row["raw_line"]) if row["raw_line"] is not None else "",
                    str(row["source_file"]) if row["source_file"] is not None else "",
                    str(row["created_at"]) if row["created_at"] is not None else _now_iso(),
                ),
            )
        conn.execute("DROP TABLE ath_dimensions")
        conn.execute("ALTER TABLE ath_dimensions_new RENAME TO ath_dimensions")
        conn.execute("PRAGMA foreign_keys = ON")

    def _ensure_runs_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                git_commit TEXT,
                app_version TEXT,
                settings_hash TEXT,
                error_summary TEXT,
                pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
                tag TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_versions (
                run_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_seconds REAL,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                error_summary TEXT,
                PRIMARY KEY (run_id, version_id),
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
                FOREIGN KEY (version_id) REFERENCES versions(version_id) ON DELETE CASCADE
            )
            """
        )

    def _migrate_graph_points_schema(self, conn: sqlite3.Connection) -> None:
        columns = set(self._table_columns(conn, "graph_points"))
        if not columns:
            return

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS graph_series (
                series_id TEXT PRIMARY KEY,
                graph_id TEXT NOT NULL,
                series_kind TEXT,
                angle_deg REAL,
                label TEXT,
                meta_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
            )
            """
        )

        if "series_id" in columns:
            if "y_imag" not in columns:
                conn.execute("ALTER TABLE graph_points ADD COLUMN y_imag REAL")
            return

        if "graph_id" not in columns:
            return

        old_rows = conn.execute(
            "SELECT graph_id, point_index, x_value, y_value FROM graph_points ORDER BY graph_id, point_index"
        ).fetchall()
        graph_created_at = {
            str(row["graph_id"]): str(row["created_at"])
            for row in conn.execute("SELECT graph_id, created_at FROM graphs").fetchall()
        }

        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE graph_points_new (
                series_id TEXT NOT NULL,
                point_index INTEGER NOT NULL,
                x_value REAL,
                y_value REAL,
                y_imag REAL,
                PRIMARY KEY (series_id, point_index),
                FOREIGN KEY (series_id) REFERENCES graph_series(series_id) ON DELETE CASCADE
            )
            """
        )

        series_cache: Dict[str, str] = {}
        for row in old_rows:
            graph_id = str(row["graph_id"])
            series_id = series_cache.get(graph_id)
            if series_id is None:
                series_id = _stable_series_id(
                    graph_id,
                    series_kind="curve",
                    angle_deg=None,
                    label="default",
                )
                series_cache[graph_id] = series_id
                conn.execute(
                    """
                    INSERT OR IGNORE INTO graph_series (
                        series_id, graph_id, series_kind, angle_deg, label, meta_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        series_id,
                        graph_id,
                        "curve",
                        None,
                        "default",
                        _to_json({}),
                        graph_created_at.get(graph_id, _now_iso()),
                    ),
                )
            conn.execute(
                """
                INSERT INTO graph_points_new (series_id, point_index, x_value, y_value, y_imag)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    series_id,
                    int(row["point_index"]),
                    float(row["x_value"]) if row["x_value"] is not None else None,
                    float(row["y_value"]) if row["y_value"] is not None else None,
                    None,
                ),
            )

        conn.execute("DROP TABLE graph_points")
        conn.execute("ALTER TABLE graph_points_new RENAME TO graph_points")
        conn.execute("PRAGMA foreign_keys = ON")

    def _ensure_federation_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS federation_profile (
                installation_id TEXT PRIMARY KEY,
                anonymous_user_id TEXT NOT NULL,
                dataset_namespace TEXT NOT NULL,
                allow_upload INTEGER NOT NULL DEFAULT 0 CHECK (allow_upload IN (0, 1)),
                consent_scope TEXT NOT NULL DEFAULT 'unset',
                consent_version TEXT,
                consent_updated_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS federation_sync_state (
                stream_name TEXT PRIMARY KEY,
                last_cursor TEXT,
                last_synced_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS federation_export_jobs (
                export_id TEXT PRIMARY KEY,
                installation_id TEXT NOT NULL,
                status TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                item_counts_json TEXT,
                payload_sha256 TEXT,
                payload_bytes INTEGER,
                error_summary TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS federation_tombstones (
                tombstone_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                reason TEXT,
                deleted_at TEXT NOT NULL,
                uploaded_at TEXT
            );
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_federation_tombstones_entity "
            "ON federation_tombstones(entity_type, entity_id, deleted_at)"
        )

        row = conn.execute("SELECT installation_id FROM federation_profile LIMIT 1").fetchone()
        if row is not None:
            return
        installation_id = str(uuid.uuid4())
        anonymous_user_id = "U" + hashlib.sha256(installation_id.encode("utf-8")).hexdigest()[:16]
        dataset_namespace = "NS" + hashlib.sha256((installation_id + "|dataset").encode("utf-8")).hexdigest()[:16]
        now = _now_iso()
        conn.execute(
            """
            INSERT INTO federation_profile (
                installation_id, anonymous_user_id, dataset_namespace, allow_upload, consent_scope,
                consent_version, consent_updated_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                installation_id,
                anonymous_user_id,
                dataset_namespace,
                0,
                "unset",
                None,
                None,
                now,
                now,
            ),
        )

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        self._ensure_runs_tables(conn)
        self._ensure_versions_columns(conn)
        self._migrate_ath_dimensions_schema(conn)
        self._ensure_graphs_columns(conn)
        self._migrate_graph_points_schema(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS polar_measurements (
                polar_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                run_id TEXT,
                graph_id TEXT,
                orientation TEXT NOT NULL,
                orientation_raw REAL,
                norm_angle_deg REAL,
                data_level_type TEXT,
                data_base_unit TEXT,
                data_absc_unit TEXT,
                freq_min_hz REAL,
                freq_max_hz REAL,
                freq_count INTEGER NOT NULL,
                angle_min_deg REAL,
                angle_max_deg REAL,
                angle_step_deg REAL,
                angle_count INTEGER NOT NULL,
                angles_deg_json TEXT NOT NULL,
                source_file TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                export_meta_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS polar_points (
                polar_id TEXT NOT NULL,
                freq_index INTEGER NOT NULL,
                angle_index INTEGER NOT NULL,
                freq_hz REAL NOT NULL,
                angle_deg REAL NOT NULL,
                re REAL NOT NULL,
                im REAL NOT NULL,
                PRIMARY KEY (polar_id, freq_index, angle_index),
                FOREIGN KEY (polar_id) REFERENCES polar_measurements(polar_id) ON DELETE CASCADE
            )
            """
        )
        self._ensure_federation_tables(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_project_batch ON runs(project_id, batch_id, started_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_versions_batch_status ON run_versions(project_id, batch_id, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_graphs_version_kind ON graphs(version_id, graph_kind)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_graphs_run_version_kind_variant ON "
            "graphs(run_id, version_id, graph_kind, variant) WHERE run_id IS NOT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_graph_series_graph_angle ON graph_series(graph_id, angle_deg)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_graph_series_graph_angle_label ON "
            "graph_series(graph_id, angle_deg, label)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_graph_points_series_x ON graph_points(series_id, x_value)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_polar_meas_version ON polar_measurements(version_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_polar_meas_run ON polar_measurements(run_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_polar_meas_batch ON polar_measurements(project_id, batch_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_polar_meas_orientation ON polar_measurements(orientation)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_polar_meas_identity ON "
            "polar_measurements(project_id, version_id, coalesce(run_id, ''), orientation, file_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_polar_points_polar_freq ON polar_points(polar_id, freq_hz)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_polar_points_polar_angle_freq ON polar_points(polar_id, angle_index, freq_hz)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_polar_points_polar_angle ON polar_points(polar_id, angle_deg)"
        )

    def persist_schema_descriptor(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "primary_storage": "sqlite",
            "project_db": str(self.project_db_path),
            "global_db": str(self.global_db_path),
            "tables": [
                "projects",
                "batches",
                "versions",
                "version_params",
                "ath_dimensions",
                "runs",
                "run_versions",
                "graphs",
                "graph_series",
                "graph_points",
                "polar_measurements",
                "polar_points",
                "compat_verification_results",
                "federation_profile",
                "federation_sync_state",
                "federation_export_jobs",
                "federation_tombstones",
            ],
        }
        self.schema_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _queue_retry(self, operation: str, payload: Dict[str, Any], error: str) -> None:
        now = _now_iso()
        with self._open_conn(self.project_db_path) as conn:
            conn.execute(
                """
                INSERT INTO replication_queue (
                    operation, payload_json, status, retry_count, last_error, created_at, updated_at
                ) VALUES (?, ?, 'pending', 0, ?, ?, ?)
                """,
                (operation, _to_json(payload), error, now, now),
            )

    def _apply_operation(self, conn: sqlite3.Connection, operation: str, payload: Dict[str, Any]) -> None:
        if operation == "upsert_project":
            self._op_upsert_project(conn, payload)
        elif operation == "upsert_batch":
            self._op_upsert_batch(conn, payload)
        elif operation == "upsert_versions":
            self._op_upsert_versions(conn, payload)
        elif operation == "upsert_plan_bundle":
            self._op_upsert_plan_bundle(conn, payload)
        elif operation == "upsert_ath_dimensions":
            self._op_upsert_ath_dimensions(conn, payload)
        elif operation == "upsert_graphs":
            self._op_upsert_graphs(conn, payload)
        elif operation == "upsert_polar_measurement":
            self._op_upsert_polar_measurement(conn, payload)
        elif operation == "insert_polar_points_chunk":
            self._op_insert_polar_points_chunk(conn, payload)
        elif operation == "upsert_run":
            self._op_upsert_run(conn, payload)
        elif operation == "update_run":
            self._op_update_run(conn, payload)
        elif operation == "set_run_pin":
            self._op_set_run_pin(conn, payload)
        elif operation == "upsert_run_versions":
            self._op_upsert_run_versions(conn, payload)
        elif operation == "delete_runs":
            self._op_delete_runs(conn, payload)
        elif operation == "insert_compat_verification":
            self._op_insert_compat_verification(conn, payload)
        elif operation == "update_version_status":
            self._op_update_version_status(conn, payload)
        elif operation == "update_federation_profile":
            self._op_update_federation_profile(conn, payload)
        elif operation == "upsert_federation_sync_state":
            self._op_upsert_federation_sync_state(conn, payload)
        elif operation == "upsert_federation_export_job":
            self._op_upsert_federation_export_job(conn, payload)
        elif operation == "insert_federation_tombstones":
            self._op_insert_federation_tombstones(conn, payload)
        else:
            raise ValueError(f"Unsupported operation: {operation}")

    def _dual_write(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._open_conn(self.project_db_path) as project_conn:
            self._apply_operation(project_conn, operation, payload)

        synced = True
        queue_id: Optional[int] = None
        try:
            with self._open_conn(self.global_db_path) as global_conn:
                self._apply_operation(global_conn, operation, payload)
        except sqlite3.Error as exc:
            synced = False
            self._queue_retry(operation, payload, str(exc))
            with self._open_conn(self.project_db_path) as conn:
                row = conn.execute("SELECT MAX(queue_id) AS queue_id FROM replication_queue").fetchone()
                if row is not None and row["queue_id"] is not None:
                    queue_id = int(row["queue_id"])

        return {
            "project_db_path": str(self.project_db_path),
            "global_db_path": str(self.global_db_path),
            "global_synced": synced,
            "queued_retry": queue_id,
        }

    def _op_upsert_project(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        now = _now_iso()
        conn.execute(
            """
            INSERT INTO projects (project_id, project_name, constraints_snapshot, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                project_name=excluded.project_name,
                constraints_snapshot=excluded.constraints_snapshot,
                updated_at=excluded.updated_at
            """,
            (
                str(payload["project_id"]),
                str(payload.get("project_name", "")),
                payload.get("constraints_snapshot"),
                str(payload.get("created_at") or now),
                now,
            ),
        )

    def _op_upsert_batch(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO batches (
                project_id, batch_id, batch_name, sweep_definitions, sweep_mode, sim_export_params, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, batch_id) DO UPDATE SET
                batch_name=excluded.batch_name,
                sweep_definitions=excluded.sweep_definitions,
                sweep_mode=excluded.sweep_mode,
                sim_export_params=excluded.sim_export_params
            """,
            (
                str(payload["project_id"]),
                str(payload["batch_id"]),
                str(payload.get("batch_name", payload["batch_id"])),
                payload.get("sweep_definitions"),
                str(payload.get("sweep_mode", "single")),
                payload.get("sim_export_params"),
                str(payload.get("created_at") or _now_iso()),
            ),
        )

    def _op_upsert_versions(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        project_id = str(payload["project_id"])
        project_name = str(payload.get("project_name", ""))
        batch_id = str(payload["batch_id"])
        batch_name = str(payload.get("batch_name", batch_id))
        for version in payload.get("versions", []):
            version_id = str(version["version_id"])
            created_at = str(version.get("created_at") or _now_iso())
            conn.execute(
                """
                INSERT INTO versions (
                    version_id, project_id, project_name, batch_id, batch_name,
                    resolved_parameters_snapshot, version_config_hash, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(version_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    project_name=excluded.project_name,
                    batch_id=excluded.batch_id,
                    batch_name=excluded.batch_name,
                    resolved_parameters_snapshot=excluded.resolved_parameters_snapshot,
                    version_config_hash=excluded.version_config_hash,
                    status=excluded.status,
                    created_at=excluded.created_at
                """,
                (
                    version_id,
                    project_id,
                    project_name,
                    batch_id,
                    batch_name,
                    version.get("resolved_parameters_snapshot"),
                    version.get("version_config_hash"),
                    str(version.get("status", "planned")),
                    created_at,
                ),
            )
            conn.execute("DELETE FROM version_params WHERE version_id = ?", (version_id,))
            for row in version.get("params", []):
                conn.execute(
                    """
                    INSERT INTO version_params (
                        version_id, project_id, batch_id, param_name, value, unit, is_set, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        project_id,
                        batch_id,
                        str(row["param_name"]),
                        row.get("value"),
                        row.get("unit"),
                        int(row.get("is_set", 0)),
                        created_at,
                    ),
                )

    def _op_upsert_plan_bundle(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        project_payload = payload.get("project")
        batch_payload = payload.get("batch")
        versions_payload = payload.get("versions")
        if not isinstance(project_payload, dict):
            raise ValueError("upsert_plan_bundle requires object payload['project']")
        if not isinstance(batch_payload, dict):
            raise ValueError("upsert_plan_bundle requires object payload['batch']")
        if not isinstance(versions_payload, dict):
            raise ValueError("upsert_plan_bundle requires object payload['versions']")

        self._op_upsert_project(conn, project_payload)
        self._op_upsert_batch(conn, batch_payload)
        self._op_upsert_versions(conn, versions_payload)

    def _op_upsert_ath_dimensions(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        for row in payload.get("rows", []):
            version_id = str(row["version_id"])
            run_id_value = str(row.get("run_id") or "legacy").strip() or "legacy"
            project_id = str(row["project_id"])
            batch_id = str(row["batch_id"])
            conn.execute(
                """
                INSERT OR IGNORE INTO runs (
                    run_id, project_id, batch_id, started_at, status, pinned
                ) VALUES (?, ?, ?, ?, 'succeeded', 0)
                """,
                (run_id_value, project_id, batch_id, str(row.get("created_at") or _now_iso())),
            )
            length_mm = row.get("length_mm")
            width_mm = row.get("width_mm")
            height_mm = row.get("height_mm")
            conn.execute(
                """
                INSERT INTO ath_dimensions (
                    run_id, version_id, project_id, batch_id, length_mm, width_mm, height_mm, raw_line, source_file, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, version_id) DO UPDATE SET
                    length_mm=excluded.length_mm,
                    width_mm=excluded.width_mm,
                    height_mm=excluded.height_mm,
                    raw_line=excluded.raw_line,
                    source_file=excluded.source_file,
                    created_at=excluded.created_at
                """,
                (
                    run_id_value,
                    version_id,
                    project_id,
                    batch_id,
                    float(length_mm) if length_mm is not None else None,
                    float(width_mm) if width_mm is not None else None,
                    float(height_mm) if height_mm is not None else None,
                    str(row.get("raw_line", "")),
                    str(row.get("source_file", "")),
                    str(row.get("created_at") or _now_iso()),
                ),
            )
            conn.execute(
                """
                UPDATE versions
                SET ath_length_mm = ?, ath_width_mm = ?, ath_height_mm = ?
                WHERE version_id = ?
                """,
                (
                    float(length_mm) if length_mm is not None else None,
                    float(width_mm) if width_mm is not None else None,
                    float(height_mm) if height_mm is not None else None,
                    version_id,
                ),
            )

    def _op_upsert_graphs(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        for graph in payload.get("graphs", []):
            graph_id = str(graph["graph_id"])
            raw_run_id = graph.get("run_id")
            run_id_value = str(raw_run_id).strip() if raw_run_id is not None else ""
            if run_id_value:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO runs (
                        run_id, project_id, batch_id, started_at, status, pinned
                    ) VALUES (?, ?, ?, ?, 'succeeded', 0)
                    """,
                    (
                        run_id_value,
                        str(graph["project_id"]),
                        str(graph["batch_id"]),
                        str(graph.get("created_at") or _now_iso()),
                    ),
                )
            conn.execute(
                """
                INSERT INTO graphs (
                    graph_id, project_id, batch_id, version_id, run_id, graph_type, graph_kind, variant,
                    x_name, y_name, x_axis, y_axis, x_unit, y_unit, source_file, export_meta, meta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(graph_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    batch_id=excluded.batch_id,
                    version_id=excluded.version_id,
                    run_id=excluded.run_id,
                    graph_type=excluded.graph_type,
                    graph_kind=excluded.graph_kind,
                    variant=excluded.variant,
                    x_name=excluded.x_name,
                    y_name=excluded.y_name,
                    x_axis=excluded.x_axis,
                    y_axis=excluded.y_axis,
                    x_unit=excluded.x_unit,
                    y_unit=excluded.y_unit,
                    source_file=excluded.source_file,
                    export_meta=excluded.export_meta,
                    meta_json=excluded.meta_json,
                    created_at=excluded.created_at
                """,
                (
                    graph_id,
                    str(graph["project_id"]),
                    str(graph["batch_id"]),
                    str(graph["version_id"]),
                    run_id_value or None,
                    str(graph.get("graph_type", "")),
                    str(graph.get("graph_kind", graph.get("graph_type", ""))),
                    str(graph.get("variant", "default")),
                    str(graph.get("x_name", "")),
                    str(graph.get("y_name", "")),
                    str(graph.get("x_axis", graph.get("x_name", ""))),
                    str(graph.get("y_axis", graph.get("y_name", ""))),
                    str(graph.get("x_unit", "")),
                    str(graph.get("y_unit", "")),
                    str(graph.get("source_file", "")),
                    graph.get("export_meta"),
                    graph.get("meta_json"),
                    str(graph.get("created_at") or _now_iso()),
                ),
            )
            conn.execute("DELETE FROM graph_series WHERE graph_id = ?", (graph_id,))

            series_rows = list(graph.get("series", []))
            if not series_rows and graph.get("points"):
                series_rows = [
                    {
                        "series_id": _stable_series_id(
                            graph_id,
                            series_kind="curve",
                            angle_deg=None,
                            label="default",
                        ),
                        "series_kind": "curve",
                        "angle_deg": None,
                        "label": "default",
                        "meta_json": _to_json({}),
                        "created_at": str(graph.get("created_at") or _now_iso()),
                        "points": list(graph.get("points", [])),
                    }
                ]

            for series in series_rows:
                series_id = str(
                    series.get("series_id")
                    or _stable_series_id(
                        graph_id,
                        series_kind=str(series.get("series_kind", "curve")),
                        angle_deg=float(series["angle_deg"]) if series.get("angle_deg") is not None else None,
                        label=str(series.get("label", "default")),
                    )
                )
                conn.execute(
                    """
                    INSERT INTO graph_series (
                        series_id, graph_id, series_kind, angle_deg, label, meta_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(series_id) DO UPDATE SET
                        graph_id=excluded.graph_id,
                        series_kind=excluded.series_kind,
                        angle_deg=excluded.angle_deg,
                        label=excluded.label,
                        meta_json=excluded.meta_json,
                        created_at=excluded.created_at
                    """,
                    (
                        series_id,
                        graph_id,
                        str(series.get("series_kind", "curve")),
                        float(series["angle_deg"]) if series.get("angle_deg") is not None else None,
                        str(series.get("label", "default")),
                        series.get("meta_json", _to_json({})),
                        str(series.get("created_at") or graph.get("created_at") or _now_iso()),
                    ),
                )
                for point in series.get("points", []):
                    conn.execute(
                        """
                        INSERT INTO graph_points (series_id, point_index, x_value, y_value, y_imag)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            series_id,
                            int(point["point_index"]),
                            float(point["x_value"]) if point.get("x_value") is not None else None,
                            float(point["y_value"]) if point.get("y_value") is not None else None,
                            float(point["y_imag"]) if point.get("y_imag") is not None else None,
                        ),
                    )

    def _op_upsert_polar_measurement(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
        raw_run_id = row.get("run_id")
        run_id_value = str(raw_run_id).strip() if raw_run_id is not None else ""
        if run_id_value:
            conn.execute(
                """
                INSERT OR IGNORE INTO runs (
                    run_id, project_id, batch_id, started_at, status, pinned
                ) VALUES (?, ?, ?, ?, 'succeeded', 0)
                """,
                (
                    run_id_value,
                    str(row["project_id"]),
                    str(row["batch_id"]),
                    str(row.get("created_at") or _now_iso()),
                ),
            )
        conn.execute(
            """
            INSERT INTO polar_measurements (
                polar_id, project_id, batch_id, version_id, run_id, graph_id, orientation, orientation_raw,
                norm_angle_deg, data_level_type, data_base_unit, data_absc_unit, freq_min_hz, freq_max_hz,
                freq_count, angle_min_deg, angle_max_deg, angle_step_deg, angle_count, angles_deg_json,
                source_file, file_hash, export_meta_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(polar_id) DO UPDATE SET
                project_id=excluded.project_id,
                batch_id=excluded.batch_id,
                version_id=excluded.version_id,
                run_id=excluded.run_id,
                graph_id=excluded.graph_id,
                orientation=excluded.orientation,
                orientation_raw=excluded.orientation_raw,
                norm_angle_deg=excluded.norm_angle_deg,
                data_level_type=excluded.data_level_type,
                data_base_unit=excluded.data_base_unit,
                data_absc_unit=excluded.data_absc_unit,
                freq_min_hz=excluded.freq_min_hz,
                freq_max_hz=excluded.freq_max_hz,
                freq_count=excluded.freq_count,
                angle_min_deg=excluded.angle_min_deg,
                angle_max_deg=excluded.angle_max_deg,
                angle_step_deg=excluded.angle_step_deg,
                angle_count=excluded.angle_count,
                angles_deg_json=excluded.angles_deg_json,
                source_file=excluded.source_file,
                file_hash=excluded.file_hash,
                export_meta_json=excluded.export_meta_json,
                created_at=excluded.created_at
            """,
            (
                str(row["polar_id"]),
                str(row["project_id"]),
                str(row["batch_id"]),
                str(row["version_id"]),
                run_id_value or None,
                str(row.get("graph_id", "") or "") or None,
                str(row["orientation"]),
                float(row["orientation_raw"]) if row.get("orientation_raw") is not None else None,
                float(row["norm_angle_deg"]) if row.get("norm_angle_deg") is not None else None,
                str(row.get("data_level_type", "") or ""),
                str(row.get("data_base_unit", "") or ""),
                str(row.get("data_absc_unit", "") or ""),
                float(row["freq_min_hz"]) if row.get("freq_min_hz") is not None else None,
                float(row["freq_max_hz"]) if row.get("freq_max_hz") is not None else None,
                int(row["freq_count"]),
                float(row["angle_min_deg"]) if row.get("angle_min_deg") is not None else None,
                float(row["angle_max_deg"]) if row.get("angle_max_deg") is not None else None,
                float(row["angle_step_deg"]) if row.get("angle_step_deg") is not None else None,
                int(row["angle_count"]),
                str(row["angles_deg_json"]),
                str(row["source_file"]),
                str(row["file_hash"]),
                row.get("export_meta_json"),
                str(row.get("created_at") or _now_iso()),
            ),
        )

    def _op_insert_polar_points_chunk(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        rows = [item for item in list(payload.get("rows", []) or []) if isinstance(item, dict)]
        if not rows:
            return
        values: List[Tuple[Any, ...]] = []
        for row in rows:
            values.append(
                (
                    str(row["polar_id"]),
                    int(row["freq_index"]),
                    int(row["angle_index"]),
                    float(row["freq_hz"]),
                    float(row["angle_deg"]),
                    float(row["re"]),
                    float(row["im"]),
                )
            )
        conn.executemany(
            """
            INSERT OR IGNORE INTO polar_points (
                polar_id, freq_index, angle_index, freq_hz, angle_deg, re, im
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    def _op_upsert_run(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, project_id, batch_id, started_at, finished_at, status,
                git_commit, app_version, settings_hash, error_summary, pinned, tag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                project_id=excluded.project_id,
                batch_id=excluded.batch_id,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                status=excluded.status,
                git_commit=excluded.git_commit,
                app_version=excluded.app_version,
                settings_hash=excluded.settings_hash,
                error_summary=excluded.error_summary,
                pinned=excluded.pinned,
                tag=excluded.tag
            """,
            (
                str(payload["run_id"]),
                str(payload["project_id"]),
                str(payload["batch_id"]),
                str(payload.get("started_at") or _now_iso()),
                payload.get("finished_at"),
                str(payload.get("status", "planned")),
                payload.get("git_commit"),
                payload.get("app_version"),
                payload.get("settings_hash"),
                payload.get("error_summary"),
                int(payload.get("pinned", 0)),
                payload.get("tag"),
            ),
        )

    def _op_update_run(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        fields: List[str] = []
        values: List[Any] = []
        for key in ("status", "finished_at", "error_summary", "git_commit", "app_version", "settings_hash"):
            if key in payload:
                fields.append(f"{key} = ?")
                values.append(payload[key])
        if not fields:
            return
        values.append(str(payload["run_id"]))
        conn.execute(f"UPDATE runs SET {', '.join(fields)} WHERE run_id = ?", tuple(values))

    def _op_set_run_pin(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        conn.execute(
            "UPDATE runs SET pinned = ?, tag = ? WHERE run_id = ?",
            (
                int(payload.get("pinned", 0)),
                payload.get("tag"),
                str(payload["run_id"]),
            ),
        )

    def _op_upsert_run_versions(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        for row in payload.get("rows", []):
            conn.execute(
                """
                INSERT INTO run_versions (
                    run_id, version_id, project_id, batch_id, status, duration_seconds,
                    created_at, finished_at, error_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, version_id) DO UPDATE SET
                    status=excluded.status,
                    duration_seconds=excluded.duration_seconds,
                    finished_at=excluded.finished_at,
                    error_summary=excluded.error_summary
                """,
                (
                    str(row["run_id"]),
                    str(row["version_id"]),
                    str(row["project_id"]),
                    str(row["batch_id"]),
                    str(row.get("status", "planned")),
                    row.get("duration_seconds"),
                    str(row.get("created_at") or _now_iso()),
                    row.get("finished_at"),
                    row.get("error_summary"),
                ),
            )

    def _op_delete_runs(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        run_ids = [str(item) for item in list(payload.get("run_ids", []))]
        if not run_ids:
            return
        now = _now_iso()
        tombstones = [
            {
                "entity_type": "run",
                "entity_id": run_id,
                "reason": "cleanup_unpinned_runs",
                "deleted_at": now,
            }
            for run_id in run_ids
        ]
        placeholders = ", ".join("?" for _ in run_ids)
        conn.execute(f"DELETE FROM ath_dimensions WHERE run_id IN ({placeholders})", tuple(run_ids))
        conn.execute(f"DELETE FROM graphs WHERE run_id IN ({placeholders})", tuple(run_ids))
        conn.execute(f"DELETE FROM polar_measurements WHERE run_id IN ({placeholders})", tuple(run_ids))
        conn.execute(f"DELETE FROM run_versions WHERE run_id IN ({placeholders})", tuple(run_ids))
        conn.execute(f"DELETE FROM runs WHERE run_id IN ({placeholders})", tuple(run_ids))
        self._op_insert_federation_tombstones(conn, {"rows": tombstones})

    def _op_update_version_status(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        fields = ["status = ?"]
        values: List[Any] = [str(payload["status"])]
        if "duration_seconds" in payload:
            fields.append("duration_seconds = ?")
            values.append(payload["duration_seconds"])
        if "finished_at" in payload:
            fields.append("finished_at = ?")
            values.append(payload["finished_at"])
        if "tool_versions" in payload:
            fields.append("tool_versions = ?")
            values.append(payload["tool_versions"])
        values.append(str(payload["version_id"]))
        conn.execute(f"UPDATE versions SET {', '.join(fields)} WHERE version_id = ?", tuple(values))
        run_id = payload.get("run_id")
        if run_id:
            conn.execute(
                """
                INSERT INTO run_versions (
                    run_id, version_id, project_id, batch_id, status, duration_seconds, created_at, finished_at, error_summary
                )
                SELECT ?, v.version_id, v.project_id, v.batch_id, ?, ?, ?, ?, ?
                FROM versions v
                WHERE v.version_id = ?
                ON CONFLICT(run_id, version_id) DO UPDATE SET
                    status=excluded.status,
                    duration_seconds=excluded.duration_seconds,
                    finished_at=excluded.finished_at,
                    error_summary=excluded.error_summary
                """,
                (
                    str(run_id),
                    str(payload["status"]),
                    payload.get("duration_seconds"),
                    str(payload.get("created_at") or _now_iso()),
                    payload.get("finished_at"),
                    payload.get("error_summary"),
                    str(payload["version_id"]),
                ),
            )

    def _op_update_federation_profile(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        row = conn.execute("SELECT installation_id FROM federation_profile LIMIT 1").fetchone()
        if row is None:
            self._ensure_federation_tables(conn)
            row = conn.execute("SELECT installation_id FROM federation_profile LIMIT 1").fetchone()
            if row is None:
                raise RuntimeError("federation_profile bootstrap failed")
        installation_id = str(row["installation_id"])

        fields: List[str] = []
        values: List[Any] = []
        if "allow_upload" in payload:
            fields.append("allow_upload = ?")
            values.append(1 if bool(payload.get("allow_upload")) else 0)
        if "consent_scope" in payload:
            fields.append("consent_scope = ?")
            values.append(str(payload.get("consent_scope") or "unset"))
        if "consent_version" in payload:
            fields.append("consent_version = ?")
            values.append(payload.get("consent_version"))
        if "consent_updated_at" in payload:
            fields.append("consent_updated_at = ?")
            values.append(payload.get("consent_updated_at"))
        fields.append("updated_at = ?")
        values.append(str(payload.get("updated_at") or _now_iso()))
        values.append(installation_id)
        conn.execute(f"UPDATE federation_profile SET {', '.join(fields)} WHERE installation_id = ?", tuple(values))

    def _op_upsert_federation_sync_state(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO federation_sync_state (stream_name, last_cursor, last_synced_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(stream_name) DO UPDATE SET
                last_cursor=excluded.last_cursor,
                last_synced_at=excluded.last_synced_at,
                updated_at=excluded.updated_at
            """,
            (
                str(payload["stream_name"]),
                payload.get("last_cursor"),
                payload.get("last_synced_at"),
                str(payload.get("updated_at") or _now_iso()),
            ),
        )

    def _op_upsert_federation_export_job(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        profile = conn.execute("SELECT installation_id FROM federation_profile LIMIT 1").fetchone()
        installation_id = str(payload.get("installation_id") or "")
        if not installation_id and profile is not None:
            installation_id = str(profile["installation_id"])
        conn.execute(
            """
            INSERT INTO federation_export_jobs (
                export_id, installation_id, status, schema_version, item_counts_json, payload_sha256, payload_bytes,
                error_summary, created_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(export_id) DO UPDATE SET
                status=excluded.status,
                item_counts_json=excluded.item_counts_json,
                payload_sha256=excluded.payload_sha256,
                payload_bytes=excluded.payload_bytes,
                error_summary=excluded.error_summary,
                finished_at=excluded.finished_at
            """,
            (
                str(payload["export_id"]),
                installation_id,
                str(payload.get("status", "pending")),
                str(payload.get("schema_version", SCHEMA_VERSION)),
                payload.get("item_counts_json"),
                payload.get("payload_sha256"),
                payload.get("payload_bytes"),
                payload.get("error_summary"),
                str(payload.get("created_at") or _now_iso()),
                payload.get("finished_at"),
            ),
        )

    def _op_insert_federation_tombstones(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        for row in list(payload.get("rows", []) or []):
            if not isinstance(row, dict):
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO federation_tombstones (
                    tombstone_id, entity_type, entity_id, reason, deleted_at, uploaded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row.get("tombstone_id") or uuid.uuid4()),
                    str(row.get("entity_type", "")),
                    str(row.get("entity_id", "")),
                    str(row.get("reason", "")),
                    str(row.get("deleted_at") or _now_iso()),
                    row.get("uploaded_at"),
                ),
            )

    def _op_insert_compat_verification(self, conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        for row in payload.get("rows", []):
            conn.execute(
                """
                INSERT INTO compat_verification_results (
                    project_id, fact_id, case_id, status, expected_json, observed_json, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row.get("project_id", self.project_root.name)),
                    str(row["fact_id"]),
                    str(row["case_id"]),
                    str(row["status"]),
                    row.get("expected_json"),
                    row.get("observed_json"),
                    row.get("details_json"),
                    str(row.get("created_at") or _now_iso()),
                ),
            )

    def retry_pending_global_writes(self, max_items: int = 100) -> Dict[str, Any]:
        with self._open_conn(self.project_db_path) as conn:
            rows = conn.execute(
                """
                SELECT queue_id, operation, payload_json, retry_count
                FROM replication_queue
                WHERE status = 'pending'
                ORDER BY queue_id ASC
                LIMIT ?
                """,
                (max_items,),
            ).fetchall()

        processed = 0
        synced = 0
        failed = 0
        for row in rows:
            processed += 1
            queue_id = int(row["queue_id"])
            operation = str(row["operation"])
            payload = json.loads(str(row["payload_json"]))
            retry_count = int(row["retry_count"])
            try:
                with self._open_conn(self.global_db_path) as conn:
                    self._apply_operation(conn, operation, payload)
                with self._open_conn(self.project_db_path) as conn:
                    conn.execute(
                        "UPDATE replication_queue SET status = 'synced', updated_at = ? WHERE queue_id = ?",
                        (_now_iso(), queue_id),
                    )
                synced += 1
            except sqlite3.Error as exc:
                with self._open_conn(self.project_db_path) as conn:
                    conn.execute(
                        """
                        UPDATE replication_queue
                        SET retry_count = ?, last_error = ?, updated_at = ?
                        WHERE queue_id = ?
                        """,
                        (retry_count + 1, str(exc), _now_iso(), queue_id),
                    )
                failed += 1

        return {"processed": processed, "synced": synced, "failed": failed}

    def load_federation_profile(self) -> Dict[str, Any]:
        with self._open_conn(self.project_db_path) as conn:
            row = conn.execute(
                """
                SELECT installation_id, anonymous_user_id, dataset_namespace, allow_upload,
                       consent_scope, consent_version, consent_updated_at, created_at, updated_at
                FROM federation_profile
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            raise RuntimeError("federation_profile not initialized")
        return {
            "installation_id": str(row["installation_id"]),
            "anonymous_user_id": str(row["anonymous_user_id"]),
            "dataset_namespace": str(row["dataset_namespace"]),
            "allow_upload": bool(int(row["allow_upload"])),
            "consent_scope": str(row["consent_scope"]),
            "consent_version": row["consent_version"],
            "consent_updated_at": row["consent_updated_at"],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def update_federation_profile(
        self,
        *,
        allow_upload: Optional[bool] = None,
        consent_scope: Optional[str] = None,
        consent_version: Optional[str] = None,
        consent_updated_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if allow_upload is not None:
            payload["allow_upload"] = 1 if bool(allow_upload) else 0
        if consent_scope is not None:
            payload["consent_scope"] = str(consent_scope)
        if consent_version is not None:
            payload["consent_version"] = str(consent_version)
        if consent_updated_at is not None:
            payload["consent_updated_at"] = str(consent_updated_at)
        payload["updated_at"] = _now_iso()
        result = self._dual_write("update_federation_profile", payload)
        return {**result, "profile": self.load_federation_profile()}

    def update_federation_sync_state(
        self,
        *,
        stream_name: str,
        last_cursor: Optional[str],
        last_synced_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "stream_name": str(stream_name),
            "last_cursor": last_cursor,
            "last_synced_at": last_synced_at,
            "updated_at": _now_iso(),
        }
        return self._dual_write("upsert_federation_sync_state", payload)

    def record_federation_export_job(
        self,
        *,
        export_id: str,
        status: str,
        item_counts: Optional[Dict[str, Any]] = None,
        payload_sha256: Optional[str] = None,
        payload_bytes: Optional[int] = None,
        error_summary: Optional[str] = None,
        finished_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "export_id": str(export_id),
            "status": str(status),
            "schema_version": SCHEMA_VERSION,
            "item_counts_json": _to_json(item_counts or {}),
            "payload_sha256": payload_sha256,
            "payload_bytes": payload_bytes,
            "error_summary": error_summary,
            "created_at": _now_iso(),
            "finished_at": finished_at,
        }
        return self._dual_write("upsert_federation_export_job", payload)

    def register_project(self, project: Project) -> Dict[str, Any]:
        payload = {
            "project_id": project.project_id,
            "project_name": project.name,
            "constraints_snapshot": _to_json(project.constraints.to_dict()),
            "created_at": _now_iso(),
        }
        result = self._dual_write("upsert_project", payload)
        self.persist_schema_descriptor()
        return result

    def register_batch(self, project: Project, batch: Batch, *, batch_name: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "project_id": project.project_id,
            "batch_id": batch.batch_id,
            "batch_name": batch_name or str(batch.extra.get("batch_name") or batch.batch_id),
            "sweep_definitions": _to_json({key: spec.to_dict() for key, spec in batch.sweeps.items()}),
            "sweep_mode": batch.sweep_mode,
            "sim_export_params": _to_json(batch.sim_export_settings.to_dict()),
            "created_at": _now_iso(),
        }
        return self._dual_write("upsert_batch", payload)

    def write_versions(
        self,
        project: Project,
        batch: Batch,
        versions: Sequence[VersionSpec],
        *,
        batch_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for version in versions:
            params: List[Dict[str, Any]] = []
            all_keys = sorted(set(version.parameters.keys()).union(version.unset_parameters))
            for key in all_keys:
                is_set = 1 if key in version.parameters else 0
                params.append(
                    {
                        "param_name": key,
                        "value": _serialize_value(version.parameters.get(key)) if is_set else None,
                        "unit": None,
                        "is_set": is_set,
                    }
                )
            rows.append(
                {
                    "version_id": version.version_id,
                    "status": version.status,
                    "created_at": version.created_at or _now_iso(),
                    "resolved_parameters_snapshot": _to_json(version.to_dict()),
                    "version_config_hash": _version_config_hash(version.parameters, version.unset_parameters),
                    "params": params,
                }
            )

        payload = {
            "project_id": project.project_id,
            "project_name": project.name,
            "batch_id": batch.batch_id,
            "batch_name": batch_name or str(batch.extra.get("batch_name") or batch.batch_id),
            "versions": rows,
        }
        result = self._dual_write("upsert_versions", payload)
        return {**result, "version_count": len(rows)}

    def write_plan_bundle(
        self,
        *,
        project: Project,
        batch: Batch,
        versions: Sequence[VersionSpec],
        batch_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = _now_iso()
        project_payload = {
            "project_id": project.project_id,
            "project_name": project.name,
            "constraints_snapshot": _to_json(project.constraints.to_dict()),
            "created_at": now,
        }
        batch_payload = {
            "project_id": project.project_id,
            "batch_id": batch.batch_id,
            "batch_name": batch_name or str(batch.extra.get("batch_name") or batch.batch_id),
            "sweep_definitions": _to_json({key: spec.to_dict() for key, spec in batch.sweeps.items()}),
            "sweep_mode": batch.sweep_mode,
            "sim_export_params": _to_json(batch.sim_export_settings.to_dict()),
            "created_at": now,
        }

        version_rows: List[Dict[str, Any]] = []
        for version in versions:
            params: List[Dict[str, Any]] = []
            all_keys = sorted(set(version.parameters.keys()).union(version.unset_parameters))
            for key in all_keys:
                is_set = 1 if key in version.parameters else 0
                params.append(
                    {
                        "param_name": key,
                        "value": _serialize_value(version.parameters.get(key)) if is_set else None,
                        "unit": None,
                        "is_set": is_set,
                    }
                )
            version_rows.append(
                {
                    "version_id": version.version_id,
                    "status": version.status,
                    "created_at": version.created_at or now,
                    "resolved_parameters_snapshot": _to_json(version.to_dict()),
                    "version_config_hash": _version_config_hash(version.parameters, version.unset_parameters),
                    "params": params,
                }
            )
        versions_payload = {
            "project_id": project.project_id,
            "project_name": project.name,
            "batch_id": batch.batch_id,
            "batch_name": batch_name or str(batch.extra.get("batch_name") or batch.batch_id),
            "versions": version_rows,
        }

        payload = {
            "project": project_payload,
            "batch": batch_payload,
            "versions": versions_payload,
        }
        result = self._dual_write("upsert_plan_bundle", payload)
        self.persist_schema_descriptor()
        return {**result, "version_count": len(version_rows)}

    def update_version_status(
        self,
        version_id: str,
        *,
        status: str,
        run_id: Optional[str] = None,
        finished_at: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        error_summary: Optional[str] = None,
        tool_versions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"version_id": version_id, "status": status}
        if run_id is not None:
            payload["run_id"] = run_id
        if finished_at is not None:
            payload["finished_at"] = finished_at
        if duration_seconds is not None:
            payload["duration_seconds"] = duration_seconds
        if error_summary is not None:
            payload["error_summary"] = error_summary
        if tool_versions is not None:
            payload["tool_versions"] = _to_json(tool_versions)
        return self._dual_write("update_version_status", payload)

    def write_ath_dimensions(self, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        payload_rows: List[Dict[str, Any]] = []
        for row in rows:
            payload_rows.append(
                {
                    "project_id": str(row["project_id"]),
                    "batch_id": str(row["batch_id"]),
                    "version_id": str(row["version_id"]),
                    "run_id": row.get("run_id"),
                    "length_mm": row.get("horn_length_mm"),
                    "width_mm": row.get("horn_width_mm"),
                    "height_mm": row.get("horn_height_mm"),
                    "raw_line": str(row.get("raw_line", "")),
                    "source_file": str(row.get("source_file", "")),
                    "created_at": str(row.get("created_at") or _now_iso()),
                }
            )
        result = self._dual_write("upsert_ath_dimensions", {"rows": payload_rows})
        return {**result, "rows_written": len(payload_rows)}

    def write_measurements(self, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        graphs: Dict[str, Dict[str, Any]] = {}
        ordered_graph_ids: List[str] = []
        ordered_series_ids: List[str] = []
        for row in rows:
            project_id = str(row["project_id"])
            batch_id = str(row["batch_id"])
            version_id = str(row["version_id"])
            run_id = str(row.get("run_id", "")).strip() or None
            graph_type = str(row.get("graph_type", row.get("graph_kind", "")))
            variant = str(row.get("variant", "default"))
            x_name = str(row.get("x_name", "x"))
            y_name = str(row.get("y_name", "y"))
            source_file = str(row.get("source_file", ""))
            graph_id = str(
                row.get("graph_id")
                or _stable_graph_id(project_id, batch_id, version_id, run_id, graph_type, variant, x_name, y_name, source_file)
            )
            if graph_id not in graphs:
                graphs[graph_id] = {
                    "graph_id": graph_id,
                    "project_id": project_id,
                    "batch_id": batch_id,
                    "version_id": version_id,
                    "run_id": run_id,
                    "graph_type": graph_type,
                    "graph_kind": str(row.get("graph_kind", graph_type)),
                    "variant": variant,
                    "x_name": x_name,
                    "y_name": y_name,
                    "x_axis": str(row.get("x_axis", x_name)),
                    "y_axis": str(row.get("y_axis", y_name)),
                    "x_unit": str(row.get("x_unit", "")),
                    "y_unit": str(row.get("y_unit", "")),
                    "source_file": source_file,
                    "export_meta": _to_json(row.get("export_meta", {})),
                    "meta_json": _to_json(row.get("meta_json", row.get("export_meta", {}))),
                    "created_at": str(row.get("created_at") or _now_iso()),
                    "series": {},
                }
                ordered_graph_ids.append(graph_id)

            series_kind = str(row.get("series_kind", "curve"))
            angle_deg = row.get("angle_deg")
            angle_value = float(angle_deg) if angle_deg is not None else None
            label = str(row.get("series_label", row.get("label", "default")))
            series_id = str(
                row.get("series_id")
                or _stable_series_id(
                    graph_id,
                    series_kind=series_kind,
                    angle_deg=angle_value,
                    label=label,
                )
            )
            graph_series = graphs[graph_id]["series"]
            if series_id not in graph_series:
                graph_series[series_id] = {
                    "series_id": series_id,
                    "series_kind": series_kind,
                    "angle_deg": angle_value,
                    "label": label,
                    "meta_json": _to_json(row.get("series_meta", {})),
                    "created_at": str(row.get("created_at") or _now_iso()),
                    "points": [],
                }
                ordered_series_ids.append(series_id)

            point_index = row.get("point_index")
            if point_index is None:
                point_index = len(graph_series[series_id]["points"])
            graph_series[series_id]["points"].append(
                {
                    "point_index": int(point_index),
                    "x_value": row.get("x_value"),
                    "y_value": row.get("y_value"),
                    "y_imag": row.get("y_imag"),
                }
            )

        graph_payload: List[Dict[str, Any]] = []
        for graph_id in ordered_graph_ids:
            graph = graphs[graph_id]
            series_map = graph.pop("series")
            graph["series"] = [series_map[series_id] for series_id in ordered_series_ids if series_id in series_map]
            graph_payload.append(graph)

        payload = {"graphs": graph_payload}
        result = self._dual_write("upsert_graphs", payload)
        point_count = sum(
            len(series["points"])
            for graph in graph_payload
            for series in graph.get("series", [])
        )
        series_count = sum(len(graph.get("series", [])) for graph in graph_payload)
        return {
            **result,
            "rows_written": point_count,
            "graphs_written": len(graph_payload),
            "series_written": series_count,
        }

    def find_polar_measurement_id(
        self,
        *,
        project_id: str,
        version_id: str,
        run_id: Optional[str],
        orientation: str,
        file_hash: str,
    ) -> Optional[str]:
        run_token = str(run_id or "").strip()
        with self._open_conn(self.project_db_path) as conn:
            row = conn.execute(
                """
                SELECT polar_id
                FROM polar_measurements
                WHERE project_id = ?
                  AND version_id = ?
                  AND coalesce(run_id, '') = ?
                  AND orientation = ?
                  AND file_hash = ?
                LIMIT 1
                """,
                (
                    str(project_id),
                    str(version_id),
                    run_token,
                    str(orientation),
                    str(file_hash),
                ),
            ).fetchone()
        if row is None:
            return None
        return str(row["polar_id"])

    def write_polar_measurement(
        self,
        *,
        measurement: Dict[str, Any],
        points: Sequence[Dict[str, Any]],
        point_chunk_size: int = 10_000,
    ) -> Dict[str, Any]:
        chunk_size = max(int(point_chunk_size), 1)
        run_id_value = str(measurement.get("run_id", "") or "").strip()
        project_id = str(measurement["project_id"])
        batch_id = str(measurement["batch_id"])
        version_id = str(measurement["version_id"])
        orientation = str(measurement["orientation"])
        file_hash = str(measurement["file_hash"])
        polar_id = str(
            measurement.get("polar_id")
            or _stable_polar_id(
                project_id=project_id,
                batch_id=batch_id,
                version_id=version_id,
                run_id=run_id_value or None,
                orientation=orientation,
                file_hash=file_hash,
            )
        )
        measurement_payload = {
            "polar_id": polar_id,
            "project_id": project_id,
            "batch_id": batch_id,
            "version_id": version_id,
            "run_id": run_id_value or None,
            "graph_id": measurement.get("graph_id"),
            "orientation": orientation,
            "orientation_raw": measurement.get("orientation_raw"),
            "norm_angle_deg": measurement.get("norm_angle_deg"),
            "data_level_type": measurement.get("data_level_type"),
            "data_base_unit": measurement.get("data_base_unit"),
            "data_absc_unit": measurement.get("data_absc_unit"),
            "freq_min_hz": measurement.get("freq_min_hz"),
            "freq_max_hz": measurement.get("freq_max_hz"),
            "freq_count": int(measurement["freq_count"]),
            "angle_min_deg": measurement.get("angle_min_deg"),
            "angle_max_deg": measurement.get("angle_max_deg"),
            "angle_step_deg": measurement.get("angle_step_deg"),
            "angle_count": int(measurement["angle_count"]),
            "angles_deg_json": str(measurement["angles_deg_json"]),
            "source_file": str(measurement["source_file"]),
            "file_hash": file_hash,
            "export_meta_json": measurement.get("export_meta_json"),
            "created_at": str(measurement.get("created_at") or _now_iso()),
        }
        metadata_result = self._dual_write("upsert_polar_measurement", {"row": measurement_payload})

        point_rows: List[Dict[str, Any]] = []
        for row in points:
            point_rows.append(
                {
                    "polar_id": polar_id,
                    "freq_index": int(row["freq_index"]),
                    "angle_index": int(row["angle_index"]),
                    "freq_hz": float(row["freq_hz"]),
                    "angle_deg": float(row["angle_deg"]),
                    "re": float(row["re"]),
                    "im": float(row["im"]),
                }
            )

        global_synced = bool(metadata_result.get("global_synced"))
        queued_retries: List[int] = []
        queued_retry = metadata_result.get("queued_retry")
        if queued_retry is not None:
            queued_retries.append(int(queued_retry))
        chunks_written = 0
        for start in range(0, len(point_rows), chunk_size):
            chunk = point_rows[start : start + chunk_size]
            if not chunk:
                continue
            chunk_result = self._dual_write("insert_polar_points_chunk", {"rows": chunk})
            chunks_written += 1
            global_synced = global_synced and bool(chunk_result.get("global_synced"))
            chunk_queue_id = chunk_result.get("queued_retry")
            if chunk_queue_id is not None:
                queued_retries.append(int(chunk_queue_id))

        return {
            "project_db_path": str(self.project_db_path),
            "global_db_path": str(self.global_db_path),
            "global_synced": global_synced,
            "queued_retry": queued_retries[-1] if queued_retries else None,
            "queued_retries": queued_retries,
            "polar_id": polar_id,
            "points_written": len(point_rows),
            "chunks_written": chunks_written,
        }

    def write_compat_verification_results(self, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        payload_rows: List[Dict[str, Any]] = []
        for row in rows:
            payload_rows.append(
                {
                    "project_id": str(row.get("project_id", self.project_root.name)),
                    "fact_id": str(row["fact_id"]),
                    "case_id": str(row["case_id"]),
                    "status": str(row["status"]),
                    "expected_json": _to_json(row.get("expected", {})),
                    "observed_json": _to_json(row.get("observed", {})),
                    "details_json": _to_json(row.get("details", {})),
                    "created_at": str(row.get("created_at") or _now_iso()),
                }
            )
        result = self._dual_write("insert_compat_verification", {"rows": payload_rows})
        return {**result, "rows_written": len(payload_rows)}

    def create_run(
        self,
        *,
        run_id: str,
        project_id: str,
        batch_id: str,
        started_at: Optional[str] = None,
        status: str = "running",
        git_commit: Optional[str] = None,
        app_version: Optional[str] = None,
        settings_hash: Optional[str] = None,
        error_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "run_id": run_id,
            "project_id": project_id,
            "batch_id": batch_id,
            "started_at": started_at or _now_iso(),
            "status": status,
            "git_commit": git_commit,
            "app_version": app_version,
            "settings_hash": settings_hash,
            "error_summary": error_summary,
            "pinned": 0,
            "tag": None,
        }
        return self._dual_write("upsert_run", payload)

    def update_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        finished_at: Optional[str] = None,
        error_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"run_id": run_id}
        if status is not None:
            payload["status"] = status
        if finished_at is not None:
            payload["finished_at"] = finished_at
        if error_summary is not None:
            payload["error_summary"] = error_summary
        return self._dual_write("update_run", payload)

    def write_run_versions(self, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        payload_rows: List[Dict[str, Any]] = []
        for row in rows:
            payload_rows.append(
                {
                    "run_id": str(row["run_id"]),
                    "version_id": str(row["version_id"]),
                    "project_id": str(row["project_id"]),
                    "batch_id": str(row["batch_id"]),
                    "status": str(row.get("status", "planned")),
                    "duration_seconds": row.get("duration_seconds"),
                    "created_at": str(row.get("created_at") or _now_iso()),
                    "finished_at": row.get("finished_at"),
                    "error_summary": row.get("error_summary"),
                }
            )
        result = self._dual_write("upsert_run_versions", {"rows": payload_rows})
        return {**result, "rows_written": len(payload_rows)}

    def set_run_pin(self, run_id: str, *, pinned: bool, tag: Optional[str] = None) -> Dict[str, Any]:
        return self._dual_write(
            "set_run_pin",
            {
                "run_id": run_id,
                "pinned": 1 if pinned else 0,
                "tag": tag,
            },
        )

    def list_runs(
        self,
        *,
        batch_id: Optional[str] = None,
        status: Optional[str] = None,
        pinned: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        where = ["project_id = ?"]
        values: List[Any] = [self.project_root.name]
        if batch_id:
            where.append("batch_id = ?")
            values.append(batch_id)
        if status:
            where.append("status = ?")
            values.append(status)
        if pinned is not None:
            where.append("pinned = ?")
            values.append(1 if pinned else 0)
        query = (
            "SELECT run_id, project_id, batch_id, started_at, finished_at, status, "
            "git_commit, app_version, settings_hash, error_summary, pinned, tag "
            f"FROM runs WHERE {' AND '.join(where)} ORDER BY started_at DESC"
        )
        with self._open_conn(self.project_db_path) as conn:
            rows = conn.execute(query, tuple(values)).fetchall()
        return [
            {
                "run_id": str(row["run_id"]),
                "project_id": str(row["project_id"]),
                "batch_id": str(row["batch_id"]),
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "status": str(row["status"]),
                "git_commit": row["git_commit"],
                "app_version": row["app_version"],
                "settings_hash": row["settings_hash"],
                "error_summary": row["error_summary"],
                "pinned": bool(row["pinned"]),
                "tag": row["tag"],
            }
            for row in rows
        ]

    def list_recent_success_durations(
        self,
        *,
        limit: int = 200,
        batch_id: Optional[str] = None,
    ) -> List[float]:
        max_rows = max(int(limit), 1)
        where = [
            "rv.project_id = ?",
            "r.project_id = ?",
            "r.status = 'succeeded'",
            "rv.status = 'success'",
            "rv.duration_seconds IS NOT NULL",
        ]
        values: List[Any] = [self.project_root.name, self.project_root.name]
        if batch_id:
            where.append("rv.batch_id = ?")
            values.append(str(batch_id))
        with self._open_conn(self.project_db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT rv.duration_seconds
                FROM run_versions rv
                JOIN runs r ON r.run_id = rv.run_id
                WHERE {' AND '.join(where)}
                ORDER BY COALESCE(rv.finished_at, r.finished_at, r.started_at) DESC
                LIMIT ?
                """,
                tuple(values + [max_rows]),
            ).fetchall()
        durations: List[float] = []
        for row in rows:
            value = row["duration_seconds"]
            if value is None:
                continue
            try:
                duration = float(value)
            except Exception:
                continue
            if duration >= 0.0:
                durations.append(duration)
        return durations

    def latest_successful_run_per_version(self, batch_id: str) -> List[Dict[str, Any]]:
        with self._open_conn(self.project_db_path) as conn:
            rows = conn.execute(
                """
                WITH ranked AS (
                    SELECT
                        rv.version_id,
                        rv.run_id,
                        rv.status AS version_status,
                        r.started_at,
                        r.finished_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY rv.version_id
                            ORDER BY r.started_at DESC, r.run_id DESC
                        ) AS rn
                    FROM run_versions rv
                    JOIN runs r ON r.run_id = rv.run_id
                    WHERE rv.project_id = ? AND rv.batch_id = ?
                      AND r.status = 'succeeded'
                      AND rv.status IN ('success', 'dry_run_completed')
                )
                SELECT version_id, run_id, version_status, started_at, finished_at
                FROM ranked
                WHERE rn = 1
                ORDER BY version_id
                """,
                (self.project_root.name, batch_id),
            ).fetchall()
        return [
            {
                "version_id": str(row["version_id"]),
                "run_id": str(row["run_id"]),
                "status": str(row["version_status"]),
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
            for row in rows
        ]

    def _resolve_project_local_path(self, raw: str) -> Path:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        return candidate.resolve()

    def _is_within_project_root(self, path: Path) -> bool:
        root = self.project_root.resolve()
        return path == root or root in path.parents

    def cleanup_unpinned_runs(
        self,
        *,
        delete_exports: bool,
        dry_run: bool,
    ) -> Dict[str, Any]:
        with self._open_conn(self.project_db_path) as conn:
            runs = conn.execute(
                """
                SELECT run_id
                FROM runs
                WHERE project_id = ? AND pinned = 0
                ORDER BY started_at
                """,
                (self.project_root.name,),
            ).fetchall()
        run_ids = [str(row["run_id"]) for row in runs]
        if not run_ids:
            return {
                "project_id": self.project_root.name,
                "dry_run": dry_run,
                "deleted": False,
                "run_ids": [],
                "counts": {
                    "runs": 0,
                    "run_versions": 0,
                    "ath_dimensions": 0,
                    "graphs": 0,
                    "graph_series": 0,
                    "graph_points": 0,
                    "files": 0,
                },
                "deleted_files": [],
                "audit_log": None,
            }

        placeholders = ", ".join("?" for _ in run_ids)
        with self._open_conn(self.project_db_path) as conn:
            counts_row = conn.execute(
                f"""
                SELECT
                    (SELECT COUNT(*) FROM runs WHERE run_id IN ({placeholders})) AS runs_count,
                    (SELECT COUNT(*) FROM run_versions WHERE run_id IN ({placeholders})) AS run_versions_count,
                    (SELECT COUNT(*) FROM ath_dimensions WHERE run_id IN ({placeholders})) AS ath_dimensions_count,
                    (SELECT COUNT(*) FROM graphs WHERE run_id IN ({placeholders})) AS graphs_count,
                    (SELECT COUNT(*) FROM graph_series gs
                        JOIN graphs g ON g.graph_id = gs.graph_id
                        WHERE g.run_id IN ({placeholders})) AS graph_series_count,
                    (SELECT COUNT(*) FROM graph_points gp
                        JOIN graph_series gs ON gs.series_id = gp.series_id
                        JOIN graphs g ON g.graph_id = gs.graph_id
                        WHERE g.run_id IN ({placeholders})) AS graph_points_count
                """,
                tuple(run_ids + run_ids + run_ids + run_ids + run_ids + run_ids),
            ).fetchone()
            file_rows = conn.execute(
                f"""
                SELECT DISTINCT source_file
                FROM graphs
                WHERE run_id IN ({placeholders}) AND source_file IS NOT NULL AND source_file != ''
                ORDER BY source_file
                """,
                tuple(run_ids),
            ).fetchall()

        export_files: List[Path] = []
        skipped_files: List[Dict[str, str]] = []
        for row in file_rows:
            raw = str(row["source_file"])
            try:
                resolved = self._resolve_project_local_path(raw)
            except Exception:
                skipped_files.append({"path": raw, "reason": "resolve_failed"})
                continue
            if not self._is_within_project_root(resolved):
                skipped_files.append({"path": raw, "reason": "outside_project_root"})
                continue
            export_files.append(resolved)

        deleted_files: List[str] = []
        if delete_exports and not dry_run:
            for path in export_files:
                if path.exists() and path.is_file():
                    path.unlink()
                    deleted_files.append(str(path))

        deleted_rows = False
        if not dry_run:
            self._dual_write("delete_runs", {"run_ids": run_ids})
            deleted_rows = True

        counts = {
            "runs": int(counts_row["runs_count"]) if counts_row else 0,
            "run_versions": int(counts_row["run_versions_count"]) if counts_row else 0,
            "ath_dimensions": int(counts_row["ath_dimensions_count"]) if counts_row else 0,
            "graphs": int(counts_row["graphs_count"]) if counts_row else 0,
            "graph_series": int(counts_row["graph_series_count"]) if counts_row else 0,
            "graph_points": int(counts_row["graph_points_count"]) if counts_row else 0,
            "files": len(export_files),
        }

        audit_payload = {
            "project_id": self.project_root.name,
            "created_at": _now_iso(),
            "dry_run": dry_run,
            "delete_exports": delete_exports,
            "run_ids": run_ids,
            "counts": counts,
            "deleted_rows": deleted_rows,
            "deleted_files": deleted_files,
            "skipped_files": skipped_files,
        }
        audit_dir = self.project_root / "logs"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / f"cleanup_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        audit_path.write_text(json.dumps(audit_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        return {
            "project_id": self.project_root.name,
            "dry_run": dry_run,
            "delete_exports": delete_exports,
            "deleted": deleted_rows,
            "run_ids": run_ids,
            "counts": counts,
            "deleted_files": deleted_files,
            "skipped_files": skipped_files,
            "audit_log": str(audit_path),
        }

    def write_project_table(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        query_project_id = project_id or self.project_root.name
        with self._open_conn(self.project_db_path) as conn:
            versions = conn.execute(
                """
                SELECT version_id, project_id, project_name, batch_id, batch_name, status, created_at, finished_at,
                       ath_length_mm, ath_width_mm, ath_height_mm
                FROM versions
                WHERE project_id = ?
                ORDER BY batch_id, version_id
                """,
                (query_project_id,),
            ).fetchall()
            param_rows = conn.execute(
                """
                SELECT version_id, param_name, value, is_set
                FROM version_params
                WHERE project_id = ?
                ORDER BY version_id, param_name
                """,
                (query_project_id,),
            ).fetchall()

        param_keys = sorted({str(row["param_name"]) for row in param_rows})
        params_by_version: Dict[str, Dict[str, Any]] = {}
        for row in param_rows:
            version_id = str(row["version_id"])
            by_key = params_by_version.setdefault(version_id, {})
            if int(row["is_set"]) == 1:
                by_key[str(row["param_name"])] = _deserialize_value(row["value"])
            else:
                by_key[str(row["param_name"])] = "<unset>"

        columns = [
            "project_id",
            "project_name",
            "batch_id",
            "batch_name",
            "version_id",
            "status",
            "created_at",
            "finished_at",
            "ath_length_mm",
            "ath_width_mm",
            "ath_height_mm",
            *param_keys,
        ]
        self.project_table_csv.parent.mkdir(parents=True, exist_ok=True)
        with self.project_table_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for version in versions:
                row = {
                    "project_id": version["project_id"],
                    "project_name": version["project_name"],
                    "batch_id": version["batch_id"],
                    "batch_name": version["batch_name"],
                    "version_id": version["version_id"],
                    "status": version["status"],
                    "created_at": version["created_at"],
                    "finished_at": version["finished_at"],
                    "ath_length_mm": version["ath_length_mm"],
                    "ath_width_mm": version["ath_width_mm"],
                    "ath_height_mm": version["ath_height_mm"],
                }
                for key in param_keys:
                    row[key] = params_by_version.get(str(version["version_id"]), {}).get(key, "")
                writer.writerow(row)
        return {"rows_written": len(versions), "csv_path": str(self.project_table_csv)}

    def load_version_parameter_states(self, version_id: str) -> List[Dict[str, Any]]:
        with self._open_conn(self.project_db_path) as conn:
            rows = conn.execute(
                """
                SELECT param_name, value, unit, is_set
                FROM version_params
                WHERE version_id = ?
                ORDER BY param_name
                """,
                (version_id,),
            ).fetchall()
        return [
            {
                "param_name": str(row["param_name"]),
                "value": _deserialize_value(row["value"]) if int(row["is_set"]) == 1 else None,
                "unit": row["unit"],
                "is_set": bool(row["is_set"]),
            }
            for row in rows
        ]

    def reconstruct_cfg_parameters(self, version_id: str) -> Tuple[Dict[str, Any], List[str]]:
        set_params: Dict[str, Any] = {}
        unset_params: List[str] = []
        for row in self.load_version_parameter_states(version_id):
            if row["is_set"]:
                set_params[str(row["param_name"])] = row["value"]
            else:
                unset_params.append(str(row["param_name"]))
        return set_params, sorted(unset_params)

    def load_version_metadata(self, version_id: str) -> Dict[str, Any]:
        with self._open_conn(self.project_db_path) as conn:
            row = conn.execute(
                """
                SELECT version_id, project_id, project_name, batch_id, batch_name, status, created_at, finished_at,
                       resolved_parameters_snapshot, version_config_hash, ath_length_mm, ath_width_mm, ath_height_mm
                FROM versions
                WHERE version_id = ?
                """,
                (version_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Version not found in project DB: {version_id}")
        return {
            "version_id": row["version_id"],
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "batch_id": row["batch_id"],
            "batch_name": row["batch_name"],
            "status": row["status"],
            "created_at": row["created_at"],
            "finished_at": row["finished_at"],
            "resolved_parameters_snapshot": row["resolved_parameters_snapshot"],
            "version_config_hash": row["version_config_hash"],
            "ath_length_mm": row["ath_length_mm"],
            "ath_width_mm": row["ath_width_mm"],
            "ath_height_mm": row["ath_height_mm"],
        }
