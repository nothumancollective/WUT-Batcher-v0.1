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

from app.models import Batch, Project, VersionSpec


SCHEMA_VERSION = "2.1"


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
    graph_type: str,
    x_name: str,
    y_name: str,
    source_file: str,
) -> str:
    raw = "|".join([project_id, batch_id, version_id, graph_type, x_name, y_name, source_file])
    return "G" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


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
                    version_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    length_mm REAL,
                    width_mm REAL,
                    height_mm REAL,
                    raw_line TEXT,
                    source_file TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (version_id) REFERENCES versions(version_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS graphs (
                    graph_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    graph_type TEXT,
                    x_name TEXT,
                    y_name TEXT,
                    x_unit TEXT,
                    y_unit TEXT,
                    source_file TEXT,
                    export_meta TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (version_id) REFERENCES versions(version_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS graph_points (
                    graph_id TEXT NOT NULL,
                    point_index INTEGER NOT NULL,
                    x_value REAL,
                    y_value REAL,
                    PRIMARY KEY (graph_id, point_index),
                    FOREIGN KEY (graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
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

                CREATE INDEX IF NOT EXISTS idx_batches_project ON batches(project_id);
                CREATE INDEX IF NOT EXISTS idx_versions_project_batch ON versions(project_id, batch_id);
                CREATE INDEX IF NOT EXISTS idx_version_params_project_batch ON version_params(project_id, batch_id);
                CREATE INDEX IF NOT EXISTS idx_graphs_version ON graphs(version_id);
                CREATE INDEX IF NOT EXISTS idx_graph_points_graph ON graph_points(graph_id);
                CREATE INDEX IF NOT EXISTS idx_replication_queue_status ON replication_queue(status, queue_id);
                CREATE INDEX IF NOT EXISTS idx_compat_results_project_fact ON compat_verification_results(project_id, fact_id);
                """
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
                "graphs",
                "graph_points",
                "compat_verification_results",
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
        elif operation == "insert_compat_verification":
            self._op_insert_compat_verification(conn, payload)
        elif operation == "update_version_status":
            self._op_update_version_status(conn, payload)
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
                    resolved_parameters_snapshot, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(version_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    project_name=excluded.project_name,
                    batch_id=excluded.batch_id,
                    batch_name=excluded.batch_name,
                    resolved_parameters_snapshot=excluded.resolved_parameters_snapshot,
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
            length_mm = row.get("length_mm")
            width_mm = row.get("width_mm")
            height_mm = row.get("height_mm")
            conn.execute(
                """
                INSERT INTO ath_dimensions (
                    version_id, project_id, batch_id, length_mm, width_mm, height_mm, raw_line, source_file, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(version_id) DO UPDATE SET
                    length_mm=excluded.length_mm,
                    width_mm=excluded.width_mm,
                    height_mm=excluded.height_mm,
                    raw_line=excluded.raw_line,
                    source_file=excluded.source_file,
                    created_at=excluded.created_at
                """,
                (
                    version_id,
                    str(row["project_id"]),
                    str(row["batch_id"]),
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
            conn.execute(
                """
                INSERT INTO graphs (
                    graph_id, project_id, batch_id, version_id, graph_type,
                    x_name, y_name, x_unit, y_unit, source_file, export_meta, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(graph_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    batch_id=excluded.batch_id,
                    version_id=excluded.version_id,
                    graph_type=excluded.graph_type,
                    x_name=excluded.x_name,
                    y_name=excluded.y_name,
                    x_unit=excluded.x_unit,
                    y_unit=excluded.y_unit,
                    source_file=excluded.source_file,
                    export_meta=excluded.export_meta,
                    created_at=excluded.created_at
                """,
                (
                    graph_id,
                    str(graph["project_id"]),
                    str(graph["batch_id"]),
                    str(graph["version_id"]),
                    str(graph.get("graph_type", "")),
                    str(graph.get("x_name", "")),
                    str(graph.get("y_name", "")),
                    str(graph.get("x_unit", "")),
                    str(graph.get("y_unit", "")),
                    str(graph.get("source_file", "")),
                    graph.get("export_meta"),
                    str(graph.get("created_at") or _now_iso()),
                ),
            )
            conn.execute("DELETE FROM graph_points WHERE graph_id = ?", (graph_id,))
            for point in graph.get("points", []):
                conn.execute(
                    """
                    INSERT INTO graph_points (graph_id, point_index, x_value, y_value)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        graph_id,
                        int(point["point_index"]),
                        float(point["x_value"]) if point.get("x_value") is not None else None,
                        float(point["y_value"]) if point.get("y_value") is not None else None,
                    ),
                )

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
        finished_at: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        tool_versions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"version_id": version_id, "status": status}
        if finished_at is not None:
            payload["finished_at"] = finished_at
        if duration_seconds is not None:
            payload["duration_seconds"] = duration_seconds
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
        ordered_ids: List[str] = []
        for row in rows:
            project_id = str(row["project_id"])
            batch_id = str(row["batch_id"])
            version_id = str(row["version_id"])
            graph_type = str(row.get("graph_type", ""))
            x_name = str(row.get("x_name", "x"))
            y_name = str(row.get("y_name", "y"))
            source_file = str(row.get("source_file", ""))
            graph_id = str(
                row.get("graph_id")
                or _stable_graph_id(project_id, batch_id, version_id, graph_type, x_name, y_name, source_file)
            )
            if graph_id not in graphs:
                graphs[graph_id] = {
                    "graph_id": graph_id,
                    "project_id": project_id,
                    "batch_id": batch_id,
                    "version_id": version_id,
                    "graph_type": graph_type,
                    "x_name": x_name,
                    "y_name": y_name,
                    "x_unit": str(row.get("x_unit", "")),
                    "y_unit": str(row.get("y_unit", "")),
                    "source_file": source_file,
                    "export_meta": _to_json(row.get("export_meta", {})),
                    "created_at": str(row.get("created_at") or _now_iso()),
                    "points": [],
                }
                ordered_ids.append(graph_id)
            point_index = row.get("point_index")
            if point_index is None:
                point_index = len(graphs[graph_id]["points"])
            graphs[graph_id]["points"].append(
                {
                    "point_index": int(point_index),
                    "x_value": row.get("x_value"),
                    "y_value": row.get("y_value"),
                }
            )

        payload = {"graphs": [graphs[graph_id] for graph_id in ordered_ids]}
        result = self._dual_write("upsert_graphs", payload)
        point_count = sum(len(graphs[graph_id]["points"]) for graph_id in ordered_ids)
        return {**result, "rows_written": point_count, "graphs_written": len(ordered_ids)}

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
                       resolved_parameters_snapshot, ath_length_mm, ath_width_mm, ath_height_mm
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
            "ath_length_mm": row["ath_length_mm"],
            "ath_width_mm": row["ath_width_mm"],
            "ath_height_mm": row["ath_height_mm"],
        }
