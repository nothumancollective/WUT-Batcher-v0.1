"""SQLite persistence for isolated runner test harness runs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Sequence


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _stable_graph_id(
    *,
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
    raw = "|".join(
        [project_id, batch_id, version_id, run_id or "", graph_type, variant, x_name, y_name, source_file]
    )
    return "G" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


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


class RunnerTestDb:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _open_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._open_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS versions (
                    version_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    resolved_parameters_snapshot TEXT,
                    version_config_hash TEXT,
                    duration_seconds REAL
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
                    error_summary TEXT
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
                    PRIMARY KEY (run_id, version_id)
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
                    PRIMARY KEY (run_id, version_id)
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
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS graph_series (
                    series_id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    series_kind TEXT,
                    angle_deg REAL,
                    label TEXT,
                    meta_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS graph_points (
                    series_id TEXT NOT NULL,
                    point_index INTEGER NOT NULL,
                    x_value REAL,
                    y_value REAL,
                    y_imag REAL,
                    PRIMARY KEY (series_id, point_index)
                );

                CREATE TABLE IF NOT EXISTS test_runs (
                    test_run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    git_commit TEXT,
                    machine_info TEXT,
                    tool_versions TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS test_cases (
                    case_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    constraints_json TEXT,
                    batch_settings_json TEXT,
                    export_specs_json TEXT
                );

                CREATE TABLE IF NOT EXISTS test_run_steps (
                    test_run_id TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    details_json TEXT,
                    error_json TEXT,
                    PRIMARY KEY (test_run_id, step_name, started_at)
                );

                CREATE TABLE IF NOT EXISTS ui_observations (
                    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_run_id TEXT NOT NULL,
                    app TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    window_signature_json TEXT,
                    control_dump_path TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha256 TEXT,
                    bytes INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS validations (
                    validation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_run_id TEXT NOT NULL,
                    validation_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metrics_json TEXT,
                    message TEXT
                );
                """
            )

    def upsert_test_case(
        self,
        *,
        case_id: str,
        name: str,
        description: str = "",
        constraints_json: Optional[Dict[str, Any]] = None,
        batch_settings_json: Optional[Dict[str, Any]] = None,
        export_specs_json: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        with self._open_conn() as conn:
            conn.execute(
                """
                INSERT INTO test_cases (
                    case_id, name, description, constraints_json, batch_settings_json, export_specs_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    constraints_json=excluded.constraints_json,
                    batch_settings_json=excluded.batch_settings_json,
                    export_specs_json=excluded.export_specs_json
                """,
                (
                    str(case_id),
                    str(name),
                    str(description),
                    _to_json(constraints_json or {}),
                    _to_json(batch_settings_json or {}),
                    _to_json(export_specs_json or []),
                ),
            )

    def create_test_run(
        self,
        *,
        test_run_id: str,
        status: str = "running",
        git_commit: Optional[str] = None,
        machine_info: Optional[Dict[str, Any]] = None,
        tool_versions: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> None:
        with self._open_conn() as conn:
            conn.execute(
                """
                INSERT INTO test_runs (
                    test_run_id, started_at, finished_at, status, git_commit, machine_info, tool_versions, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(test_run_id) DO UPDATE SET
                    status=excluded.status,
                    git_commit=excluded.git_commit,
                    machine_info=excluded.machine_info,
                    tool_versions=excluded.tool_versions,
                    notes=excluded.notes
                """,
                (
                    str(test_run_id),
                    _now_iso(),
                    None,
                    str(status),
                    git_commit,
                    _to_json(machine_info or {}),
                    _to_json(tool_versions or {}),
                    notes,
                ),
            )

    def finish_test_run(self, *, test_run_id: str, status: str, notes: Optional[str] = None) -> None:
        with self._open_conn() as conn:
            conn.execute(
                """
                UPDATE test_runs
                SET finished_at = ?, status = ?, notes = COALESCE(?, notes)
                WHERE test_run_id = ?
                """,
                (_now_iso(), str(status), notes, str(test_run_id)),
            )

    def add_test_run_step(
        self,
        *,
        test_run_id: str,
        step_name: str,
        status: str,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._open_conn() as conn:
            conn.execute(
                """
                INSERT INTO test_run_steps (
                    test_run_id, step_name, started_at, finished_at, status, details_json, error_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(test_run_id),
                    str(step_name),
                    str(started_at or _now_iso()),
                    finished_at,
                    str(status),
                    _to_json(details or {}),
                    _to_json(error or {}),
                ),
            )

    def add_ui_observation(
        self,
        *,
        test_run_id: str,
        app: str,
        window_signature: Optional[Dict[str, Any]] = None,
        control_dump_path: Optional[str] = None,
        notes: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        with self._open_conn() as conn:
            conn.execute(
                """
                INSERT INTO ui_observations (
                    test_run_id, app, timestamp, window_signature_json, control_dump_path, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(test_run_id),
                    str(app),
                    str(timestamp or _now_iso()),
                    _to_json(window_signature or {}),
                    control_dump_path,
                    notes,
                ),
            )

    def add_artifact(
        self,
        *,
        test_run_id: str,
        kind: str,
        path: str,
        sha256: Optional[str],
        bytes_size: Optional[int],
        created_at: Optional[str] = None,
    ) -> None:
        with self._open_conn() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (test_run_id, kind, path, sha256, bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(test_run_id),
                    str(kind),
                    str(path),
                    sha256,
                    int(bytes_size) if bytes_size is not None else None,
                    str(created_at or _now_iso()),
                ),
            )

    def add_validation(
        self,
        *,
        test_run_id: str,
        validation_name: str,
        status: str,
        metrics: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> None:
        with self._open_conn() as conn:
            conn.execute(
                """
                INSERT INTO validations (test_run_id, validation_name, status, metrics_json, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(test_run_id),
                    str(validation_name),
                    str(status),
                    _to_json(metrics or {}),
                    message,
                ),
            )

    def upsert_run(
        self,
        *,
        run_id: str,
        project_id: str,
        batch_id: str,
        status: str,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        git_commit: Optional[str] = None,
        app_version: Optional[str] = None,
        settings_hash: Optional[str] = None,
        error_summary: Optional[str] = None,
    ) -> None:
        with self._open_conn() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, project_id, batch_id, started_at, finished_at, status,
                    git_commit, app_version, settings_hash, error_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    finished_at=excluded.finished_at,
                    error_summary=excluded.error_summary
                """,
                (
                    str(run_id),
                    str(project_id),
                    str(batch_id),
                    str(started_at or _now_iso()),
                    finished_at,
                    str(status),
                    git_commit,
                    app_version,
                    settings_hash,
                    error_summary,
                ),
            )

    def upsert_version(
        self,
        *,
        version_id: str,
        project_id: str,
        batch_id: str,
        status: str,
        resolved_parameters_snapshot: Optional[Dict[str, Any]] = None,
        version_config_hash: Optional[str] = None,
        created_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ) -> None:
        with self._open_conn() as conn:
            conn.execute(
                """
                INSERT INTO versions (
                    version_id, project_id, batch_id, status, created_at, finished_at,
                    resolved_parameters_snapshot, version_config_hash, duration_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(version_id) DO UPDATE SET
                    status=excluded.status,
                    finished_at=excluded.finished_at,
                    duration_seconds=excluded.duration_seconds,
                    resolved_parameters_snapshot=excluded.resolved_parameters_snapshot,
                    version_config_hash=excluded.version_config_hash
                """,
                (
                    str(version_id),
                    str(project_id),
                    str(batch_id),
                    str(status),
                    str(created_at or _now_iso()),
                    finished_at,
                    _to_json(resolved_parameters_snapshot or {}),
                    version_config_hash,
                    duration_seconds,
                ),
            )

    def upsert_run_version(
        self,
        *,
        run_id: str,
        version_id: str,
        project_id: str,
        batch_id: str,
        status: str,
        duration_seconds: Optional[float] = None,
        finished_at: Optional[str] = None,
        error_summary: Optional[str] = None,
    ) -> None:
        with self._open_conn() as conn:
            conn.execute(
                """
                INSERT INTO run_versions (
                    run_id, version_id, project_id, batch_id, status, duration_seconds, created_at, finished_at, error_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, version_id) DO UPDATE SET
                    status=excluded.status,
                    duration_seconds=excluded.duration_seconds,
                    finished_at=excluded.finished_at,
                    error_summary=excluded.error_summary
                """,
                (
                    str(run_id),
                    str(version_id),
                    str(project_id),
                    str(batch_id),
                    str(status),
                    duration_seconds,
                    _now_iso(),
                    finished_at,
                    error_summary,
                ),
            )

    def upsert_ath_dimensions(
        self,
        *,
        run_id: str,
        version_id: str,
        project_id: str,
        batch_id: str,
        length_mm: Optional[float],
        width_mm: Optional[float],
        height_mm: Optional[float],
        raw_line: str,
        source_file: str,
    ) -> None:
        with self._open_conn() as conn:
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
                    source_file=excluded.source_file
                """,
                (
                    str(run_id),
                    str(version_id),
                    str(project_id),
                    str(batch_id),
                    length_mm,
                    width_mm,
                    height_mm,
                    str(raw_line),
                    str(source_file),
                    _now_iso(),
                ),
            )

    def write_measurements(self, rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
        if not rows:
            return {"graphs_written": 0, "series_written": 0, "points_written": 0}

        graphs: Dict[str, Dict[str, Any]] = {}
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
                or _stable_graph_id(
                    project_id=project_id,
                    batch_id=batch_id,
                    version_id=version_id,
                    run_id=run_id,
                    graph_type=graph_type,
                    variant=variant,
                    x_name=x_name,
                    y_name=y_name,
                    source_file=source_file,
                )
            )
            graph = graphs.setdefault(
                graph_id,
                {
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
                },
            )
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
            series = graph["series"].setdefault(
                series_id,
                {
                    "series_id": series_id,
                    "series_kind": series_kind,
                    "angle_deg": angle_value,
                    "label": label,
                    "meta_json": _to_json(row.get("series_meta", {})),
                    "created_at": str(row.get("created_at") or _now_iso()),
                    "points": [],
                },
            )
            point_index = row.get("point_index")
            if point_index is None:
                point_index = len(series["points"])
            series["points"].append(
                {
                    "point_index": int(point_index),
                    "x_value": row.get("x_value"),
                    "y_value": row.get("y_value"),
                    "y_imag": row.get("y_imag"),
                }
            )

        with self._open_conn() as conn:
            for graph in graphs.values():
                conn.execute(
                    """
                    INSERT INTO graphs (
                        graph_id, project_id, batch_id, version_id, run_id, graph_type, graph_kind, variant,
                        x_name, y_name, x_axis, y_axis, x_unit, y_unit, source_file, export_meta, meta_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(graph_id) DO UPDATE SET
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
                        meta_json=excluded.meta_json
                    """,
                    (
                        graph["graph_id"],
                        graph["project_id"],
                        graph["batch_id"],
                        graph["version_id"],
                        graph["run_id"],
                        graph["graph_type"],
                        graph["graph_kind"],
                        graph["variant"],
                        graph["x_name"],
                        graph["y_name"],
                        graph["x_axis"],
                        graph["y_axis"],
                        graph["x_unit"],
                        graph["y_unit"],
                        graph["source_file"],
                        graph["export_meta"],
                        graph["meta_json"],
                        graph["created_at"],
                    ),
                )
                for series in graph["series"].values():
                    conn.execute(
                        """
                        INSERT INTO graph_series (
                            series_id, graph_id, series_kind, angle_deg, label, meta_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(series_id) DO UPDATE SET
                            series_kind=excluded.series_kind,
                            angle_deg=excluded.angle_deg,
                            label=excluded.label,
                            meta_json=excluded.meta_json
                        """,
                        (
                            series["series_id"],
                            graph["graph_id"],
                            series["series_kind"],
                            series["angle_deg"],
                            series["label"],
                            series["meta_json"],
                            series["created_at"],
                        ),
                    )
                    for point in series["points"]:
                        conn.execute(
                            """
                            INSERT INTO graph_points (series_id, point_index, x_value, y_value, y_imag)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(series_id, point_index) DO UPDATE SET
                                x_value=excluded.x_value,
                                y_value=excluded.y_value,
                                y_imag=excluded.y_imag
                            """,
                            (
                                series["series_id"],
                                int(point["point_index"]),
                                point.get("x_value"),
                                point.get("y_value"),
                                point.get("y_imag"),
                            ),
                        )

        graph_count = len(graphs)
        series_count = sum(len(item["series"]) for item in graphs.values())
        point_count = sum(len(series["points"]) for item in graphs.values() for series in item["series"].values())
        return {"graphs_written": graph_count, "series_written": series_count, "points_written": point_count}

    def count_rows(self, table: str) -> int:
        with self._open_conn() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
            return int(row["c"]) if row else 0

    def list_test_runs(self) -> List[Dict[str, Any]]:
        with self._open_conn() as conn:
            rows = conn.execute(
                """
                SELECT test_run_id, started_at, finished_at, status, git_commit, machine_info, tool_versions, notes
                FROM test_runs
                ORDER BY started_at DESC
                """
            ).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "test_run_id": str(row["test_run_id"]),
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "status": str(row["status"]),
                    "git_commit": row["git_commit"],
                    "machine_info": json.loads(str(row["machine_info"] or "{}")),
                    "tool_versions": json.loads(str(row["tool_versions"] or "{}")),
                    "notes": row["notes"],
                }
            )
        return result
