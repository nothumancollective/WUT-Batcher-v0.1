"""Tidy dataset writers for version parameters and simulation exports."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from app.models import VersionSpec


VERSION_PARAMETER_COLUMNS = [
    "project_id",
    "batch_id",
    "version_id",
    "param_key",
    "param_value",
    "is_set",
    "created_at",
]

MEASUREMENT_COLUMNS = [
    "project_id",
    "batch_id",
    "version_id",
    "graph_type",
    "x_name",
    "x_unit",
    "x_value",
    "y_name",
    "y_unit",
    "y_value",
    "source_file",
    "created_at",
]

ATH_DIMENSION_COLUMNS = [
    "project_id",
    "batch_id",
    "version_id",
    "horn_length_mm",
    "horn_width_mm",
    "horn_height_mm",
    "raw_line",
    "source_file",
    "created_at",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float, bool, str)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _append_rows(path: Path, columns: Sequence[str], rows: Iterable[Dict[str, Any]]) -> int:
    buffered: List[Dict[str, Any]] = []
    for row in rows:
        entry = {column: row.get(column, "") for column in columns}
        buffered.append(entry)
    if not buffered:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        if write_header:
            writer.writeheader()
        writer.writerows(buffered)
    return len(buffered)


def _write_schema(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_parquet_from_csv(csv_path: Path, parquet_path: Path) -> bool:
    try:
        import pyarrow.csv as pa_csv
        import pyarrow.parquet as pa_parquet
    except Exception:
        return False

    if not csv_path.exists():
        return False
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa_csv.read_csv(str(csv_path))
    pa_parquet.write_table(table, str(parquet_path))
    return True


class TidyDatasetWriter:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)
        self.dataset_dir = self.project_root / "dataset"
        self.tables_dir = self.project_root / "tables"
        self.schema_path = self.dataset_dir / "schema.json"
        self.version_params_csv = self.dataset_dir / "version_parameters_tidy.csv"
        self.version_params_parquet = self.dataset_dir / "version_parameters_tidy.parquet"
        self.measurements_csv = self.dataset_dir / "measurements_tidy.csv"
        self.measurements_parquet = self.dataset_dir / "measurements_tidy.parquet"
        self.ath_dimensions_csv = self.dataset_dir / "ath_dimensions_tidy.csv"
        self.ath_dimensions_parquet = self.dataset_dir / "ath_dimensions_tidy.parquet"
        self.project_table_csv = self.tables_dir / "project_versions.csv"

        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.tables_dir.mkdir(parents=True, exist_ok=True)
        self._persist_schema()

    def _persist_schema(self) -> None:
        schema_payload = {
            "schema_version": "1.0",
            "files": {
                "version_parameters_tidy.csv": VERSION_PARAMETER_COLUMNS,
                "measurements_tidy.csv": MEASUREMENT_COLUMNS,
                "ath_dimensions_tidy.csv": ATH_DIMENSION_COLUMNS,
            },
        }
        _write_schema(self.schema_path, schema_payload)

    def write_version_parameters(self, versions: Sequence[VersionSpec]) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for version in versions:
            created_at = version.created_at or _now_iso()
            all_keys = set(version.parameters.keys()).union(version.unset_parameters)
            for key in sorted(all_keys):
                is_set = key in version.parameters
                value = version.parameters.get(key)
                rows.append(
                    {
                        "project_id": version.project_id,
                        "batch_id": version.batch_id,
                        "version_id": version.version_id,
                        "param_key": key,
                        "param_value": _normalize_value(value) if is_set else "",
                        "is_set": "1" if is_set else "0",
                        "created_at": created_at,
                    }
                )

        count = _append_rows(self.version_params_csv, VERSION_PARAMETER_COLUMNS, rows)
        parquet_written = _write_parquet_from_csv(self.version_params_csv, self.version_params_parquet)
        self._persist_schema()
        return {
            "rows_written": count,
            "csv_path": str(self.version_params_csv),
            "parquet_path": str(self.version_params_parquet) if parquet_written else None,
        }

    def write_measurements(self, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        normalized: List[Dict[str, Any]] = []
        for row in rows:
            created_at = str(row.get("created_at") or _now_iso())
            normalized.append(
                {
                    "project_id": str(row.get("project_id", "")),
                    "batch_id": str(row.get("batch_id", "")),
                    "version_id": str(row.get("version_id", "")),
                    "graph_type": str(row.get("graph_type", "")),
                    "x_name": str(row.get("x_name", "")),
                    "x_unit": str(row.get("x_unit", "")),
                    "x_value": _normalize_value(row.get("x_value")),
                    "y_name": str(row.get("y_name", "")),
                    "y_unit": str(row.get("y_unit", "")),
                    "y_value": _normalize_value(row.get("y_value")),
                    "source_file": str(row.get("source_file", "")),
                    "created_at": created_at,
                }
            )
        count = _append_rows(self.measurements_csv, MEASUREMENT_COLUMNS, normalized)
        parquet_written = _write_parquet_from_csv(self.measurements_csv, self.measurements_parquet)
        self._persist_schema()
        return {
            "rows_written": count,
            "csv_path": str(self.measurements_csv),
            "parquet_path": str(self.measurements_parquet) if parquet_written else None,
        }

    def write_ath_dimensions(self, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        normalized: List[Dict[str, Any]] = []
        for row in rows:
            created_at = str(row.get("created_at") or _now_iso())
            normalized.append(
                {
                    "project_id": str(row.get("project_id", "")),
                    "batch_id": str(row.get("batch_id", "")),
                    "version_id": str(row.get("version_id", "")),
                    "horn_length_mm": _normalize_value(row.get("horn_length_mm")),
                    "horn_width_mm": _normalize_value(row.get("horn_width_mm")),
                    "horn_height_mm": _normalize_value(row.get("horn_height_mm")),
                    "raw_line": str(row.get("raw_line", "")),
                    "source_file": str(row.get("source_file", "")),
                    "created_at": created_at,
                }
            )
        count = _append_rows(self.ath_dimensions_csv, ATH_DIMENSION_COLUMNS, normalized)
        parquet_written = _write_parquet_from_csv(self.ath_dimensions_csv, self.ath_dimensions_parquet)
        self._persist_schema()
        return {
            "rows_written": count,
            "csv_path": str(self.ath_dimensions_csv),
            "parquet_path": str(self.ath_dimensions_parquet) if parquet_written else None,
        }

    def write_project_table(self, versions: Sequence[VersionSpec]) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        all_param_keys = sorted({key for version in versions for key in version.parameters.keys()})
        columns = ["project_id", "batch_id", "version_id", "sequence_index", "status", "created_at"] + all_param_keys

        for version in versions:
            row: Dict[str, Any] = {
                "project_id": version.project_id,
                "batch_id": version.batch_id,
                "version_id": version.version_id,
                "sequence_index": str(version.sequence_index),
                "status": version.status,
                "created_at": version.created_at,
            }
            for key in all_param_keys:
                row[key] = _normalize_value(version.parameters.get(key))
            rows.append(row)

        count = _append_rows(self.project_table_csv, columns, rows)
        return {
            "rows_written": count,
            "csv_path": str(self.project_table_csv),
        }
