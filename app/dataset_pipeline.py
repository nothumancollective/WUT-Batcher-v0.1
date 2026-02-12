"""
Reconstructed from recovery artifacts
Confidence Level: MEDIUM
Sources used:
- C:/Work/Batch-Software/recovered/pyc_recovery/disassembly/app_dataset_pipeline_py.preferred.pydisasm.txt
- C:/Work/Rebuild/docs/Runner_Stability_Investigation_2026-02-11.md
- C:/Work/Rebuild/RecoveredDocs/WUT_BatchSoftware_Update_Roadmap_Codex.md
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


RESULT_FILE_RE = re.compile(r"^Result_(V\d+)([A-Za-z]+)(?:\.txt)?$", re.IGNORECASE)
INDEX_FILE_RE = re.compile(r"^Result_(V\d+)_index(?:\.txt)?$", re.IGNORECASE)
DEVICE_FILE_RE = re.compile(r"^(V\d+)_D(?:\..+)?$", re.IGNORECASE)
BATCH_DIR_RE = re.compile(r"^Batch_(.+)$")
NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:[\.,]\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


@dataclass
class VersionArtifacts:
    version_id: str
    batch_id: str
    outputs: Dict[str, Path]
    device_file: Optional[Path] = None
    index_file: Optional[Path] = None


@dataclass
class ImportSummary:
    total_versions: int
    imported_versions: int
    skipped_versions: int
    partial_versions: int
    failed_versions: int
    measurement_rows: int
    metadata_rows: int


@dataclass
class ParsedMeasurementRow:
    freq_hz: float
    value: Optional[float]
    phase: Optional[float]
    real: Optional[float]
    imag: Optional[float]
    unit: Optional[str]


@dataclass
class ParsedResultFile:
    rows: List[ParsedMeasurementRow]
    metadata: Dict[str, str]
    params: Dict[str, str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(path: Path) -> Dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "sha256": _file_sha256(path),
    }


def _pick_newer(existing: Optional[Path], candidate: Path) -> Path:
    if existing is None:
        return candidate
    return candidate if candidate.stat().st_mtime_ns >= existing.stat().st_mtime_ns else existing


def _artifact_key(batch_id: str, version_id: str) -> str:
    return f"{batch_id}:{version_id}"


def discover_artifacts(project_root: Path) -> Tuple[List[VersionArtifacts], List[str]]:
    batches_root = project_root / "batches"
    if not batches_root.exists():
        return [], []

    collected: Dict[Tuple[str, str], VersionArtifacts] = {}
    batch_ids: List[str] = []

    for batch_dir in sorted(p for p in batches_root.iterdir() if p.is_dir()):
        match = BATCH_DIR_RE.match(batch_dir.name)
        if not match:
            continue

        batch_id = match.group(1)
        batch_ids.append(batch_id)

        result_dirs = [batch_dir / "Resultate", batch_dir / "results"]
        for result_dir in result_dirs:
            if not result_dir.exists():
                continue
            for file_path in result_dir.iterdir():
                if not file_path.is_file():
                    continue

                result_match = RESULT_FILE_RE.match(file_path.name)
                if result_match:
                    version_id = result_match.group(1).upper()
                    output_key = result_match.group(2).upper()
                    artifact_key = (batch_id, version_id)
                    artifact = collected.get(artifact_key)
                    if artifact is None:
                        artifact = VersionArtifacts(version_id=version_id, batch_id=batch_id, outputs={})
                        collected[artifact_key] = artifact
                    artifact.outputs[output_key] = _pick_newer(artifact.outputs.get(output_key), file_path)
                    continue

                index_match = INDEX_FILE_RE.match(file_path.name)
                if index_match:
                    version_id = index_match.group(1).upper()
                    artifact_key = (batch_id, version_id)
                    artifact = collected.get(artifact_key)
                    if artifact is None:
                        artifact = VersionArtifacts(version_id=version_id, batch_id=batch_id, outputs={})
                        collected[artifact_key] = artifact
                    artifact.index_file = _pick_newer(artifact.index_file, file_path)
                    continue

                device_match = DEVICE_FILE_RE.match(file_path.name)
                if device_match:
                    version_id = device_match.group(1).upper()
                    artifact_key = (batch_id, version_id)
                    artifact = collected.get(artifact_key)
                    if artifact is None:
                        artifact = VersionArtifacts(version_id=version_id, batch_id=batch_id, outputs={})
                        collected[artifact_key] = artifact
                    artifact.device_file = _pick_newer(artifact.device_file, file_path)

    artifacts = sorted(collected.values(), key=lambda item: (item.batch_id, item.version_id))
    return artifacts, sorted(set(batch_ids))


def parse_result_rows(path: Path) -> List[Tuple[float, float]]:
    parsed = parse_result_file(path)
    rows: List[Tuple[float, float]] = []
    for row in parsed.rows:
        if row.value is None:
            continue
        rows.append((row.freq_hz, row.value))
    return rows


def _strip_quoted(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2:
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (
            cleaned.startswith("'") and cleaned.endswith("'")
        ):
            return cleaned[1:-1]
    return cleaned


def parse_result_file(path: Path) -> ParsedResultFile:
    metadata: Dict[str, str] = {}
    params: Dict[str, str] = {}
    rows: List[ParsedMeasurementRow] = []

    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        lines = handle.readlines()

    for line in lines:
        stripped = line.strip()
        if not stripped or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        value = _strip_quoted(raw_value)
        if not key:
            continue
        metadata[key] = value
        if key.startswith("Param_"):
            params[key] = value

    start_token = metadata.get("StartString_Data", "Data")
    end_token = metadata.get("EndString_Data", "Data_End")
    data_format = metadata.get("Data_Format", "").strip().lower()
    unit = metadata.get("Data_BaseUnit")

    in_data = False
    saw_data_marker = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == start_token:
            in_data = True
            saw_data_marker = True
            continue
        if stripped == end_token and in_data:
            in_data = False
            break
        if not in_data:
            continue

        numbers = NUMBER_RE.findall(stripped)
        if len(numbers) < 2:
            continue

        try:
            freq_hz = float(numbers[0].replace(",", "."))

            parsed_numbers: List[float] = []
            for token in numbers[1:]:
                try:
                    parsed_numbers.append(float(token.replace(",", ".")))
                except ValueError:
                    parsed_numbers.append(float("nan"))

            second = parsed_numbers[0] if len(parsed_numbers) >= 1 else None
            third = parsed_numbers[1] if len(parsed_numbers) >= 2 else None

            value = second
            phase = None
            real = None
            imag = None

            if "complex" in data_format:
                real = second
                imag = third
                value = second
            elif "phase" in data_format:
                value = second
                phase = third
            else:
                value = second
                if len(parsed_numbers) >= 2:
                    phase = third

            rows.append(
                ParsedMeasurementRow(
                    freq_hz=freq_hz,
                    value=value,
                    phase=phase,
                    real=real,
                    imag=imag,
                    unit=unit,
                )
            )
        except ValueError:
            continue

    if not saw_data_marker:
        for line in lines:
            numbers = NUMBER_RE.findall(line)
            if len(numbers) < 2:
                continue
            try:
                freq_hz = float(numbers[0].replace(",", "."))
                value = float(numbers[1].replace(",", "."))
            except ValueError:
                continue

            rows.append(
                ParsedMeasurementRow(
                    freq_hz=freq_hz,
                    value=value,
                    phase=None,
                    real=None,
                    imag=None,
                    unit=unit,
                )
            )

    return ParsedResultFile(rows=rows, metadata=metadata, params=params)


def _create_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS versions (
            project_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            status TEXT NOT NULL,
            output_a_path TEXT,
            output_b_path TEXT,
            output_c_path TEXT,
            output_d_path TEXT,
            imported_at TEXT NOT NULL,
            PRIMARY KEY (project_id, batch_id, version_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS measurements (
            project_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            output_key TEXT NOT NULL,
            freq_hz REAL NOT NULL,
            value REAL NOT NULL,
            phase REAL,
            real REAL,
            imag REAL,
            unit TEXT,
            PRIMARY KEY (project_id, batch_id, version_id, output_key, freq_hz)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS measurement_meta (
            project_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            output_key TEXT NOT NULL,
            graph_caption TEXT,
            data_legend TEXT,
            data_format TEXT,
            data_domain TEXT,
            data_level_type TEXT,
            absc_unit TEXT,
            base_unit TEXT,
            bode_type TEXT,
            source_desc TEXT,
            params_json TEXT,
            PRIMARY KEY (project_id, batch_id, version_id, output_key)
        )
        """
    )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_pk_columns(connection: sqlite3.Connection, table_name: str) -> List[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    indexed = sorted((row[5], row[1]) for row in rows if row[5] > 0)
    return [column_name for _, column_name in indexed]


def _schema_is_compatible(connection: sqlite3.Connection) -> bool:
    if _table_exists(connection, "versions") and _table_pk_columns(connection, "versions") != [
        "project_id",
        "batch_id",
        "version_id",
    ]:
        return False

    if _table_exists(connection, "measurements") and _table_pk_columns(connection, "measurements") != [
        "project_id",
        "batch_id",
        "version_id",
        "output_key",
        "freq_hz",
    ]:
        return False

    return True


def _normalize_manifest(payload: object, project_id: str) -> Dict[str, object]:
    manifest: Dict[str, object] = {
        "schema_version": "1.0",
        "project_id": project_id,
        "created_at": _now_iso(),
        "batch_ids": [],
        "import_index": [],
    }

    if isinstance(payload, dict):
        manifest.update(payload)

    raw_batch_ids = manifest.get("batch_ids")
    if not isinstance(raw_batch_ids, list):
        raw_batch_ids = []
    manifest["batch_ids"] = [str(value) for value in raw_batch_ids if str(value).strip()]

    raw_import_index = manifest.get("import_index")
    if isinstance(raw_import_index, list):
        import_entries = [entry for entry in raw_import_index if isinstance(entry, dict)]
    elif isinstance(raw_import_index, dict):
        import_entries = [entry for entry in raw_import_index.values() if isinstance(entry, dict)]
    else:
        import_entries = []
    manifest["import_index"] = import_entries

    if manifest.get("created_at") is None:
        manifest["created_at"] = _now_iso()
    manifest["project_id"] = str(manifest.get("project_id") or project_id)
    manifest["schema_version"] = str(manifest.get("schema_version") or "1.0")
    return manifest


def _load_manifest(path: Path, project_id: str) -> Dict[str, object]:
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return _normalize_manifest(payload, project_id)
    return _normalize_manifest({}, project_id)


def _write_manifest(path: Path, manifest: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)


def _files_signature(artifact: VersionArtifacts) -> Dict[str, Dict[str, object]]:
    signatures: Dict[str, Dict[str, object]] = {}
    for key, file_path in sorted(artifact.outputs.items()):
        signatures[key] = _fingerprint(file_path)
    if artifact.index_file is not None:
        signatures["_index"] = _fingerprint(artifact.index_file)
    if artifact.device_file is not None:
        signatures["D"] = _fingerprint(artifact.device_file)
    return signatures


def _parse_index_suffixes(index_file: Path) -> List[str]:
    suffixes: List[str] = []
    with index_file.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.lower().startswith("suffix"):
                continue
            if line.startswith("-"):
                continue
            if "\t" not in line:
                continue

            maybe_suffix = line.split("\t", 1)[0].strip().upper()
            if not re.fullmatch(r"[A-Z]+", maybe_suffix):
                continue
            suffixes.append(maybe_suffix)

    seen = set()
    ordered: List[str] = []
    for suffix in suffixes:
        if suffix in seen:
            continue
        seen.add(suffix)
        ordered.append(suffix)
    return ordered


def _is_unchanged(existing_entry: Dict, signatures: Dict[str, Dict[str, object]]) -> bool:
    existing_files = existing_entry.get("files")
    if not isinstance(existing_files, dict):
        return False

    if set(existing_files.keys()) != set(signatures.keys()):
        return False

    for key, new_fp in signatures.items():
        old_fp = existing_files.get(key)
        if not isinstance(old_fp, dict):
            return False
        for fp_key in ("mtime_ns", "size", "sha256"):
            if old_fp.get(fp_key) != new_fp.get(fp_key):
                return False
    return True


def _upsert_version(
    connection: sqlite3.Connection,
    project_id: str,
    artifact: VersionArtifacts,
    status: str,
    imported_at: str,
) -> None:
    output_paths = {key: str(path) for key, path in artifact.outputs.items()}
    if artifact.device_file is not None:
        output_paths["D"] = str(artifact.device_file)

    connection.execute(
        """
        INSERT INTO versions (
            project_id, batch_id, version_id, status,
            output_a_path, output_b_path, output_c_path, output_d_path, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, batch_id, version_id) DO UPDATE SET
            status=excluded.status,
            output_a_path=excluded.output_a_path,
            output_b_path=excluded.output_b_path,
            output_c_path=excluded.output_c_path,
            output_d_path=excluded.output_d_path,
            imported_at=excluded.imported_at
        """,
        (
            project_id,
            artifact.batch_id,
            artifact.version_id,
            status,
            output_paths.get("A"),
            output_paths.get("B"),
            output_paths.get("C"),
            output_paths.get("D"),
            imported_at,
        ),
    )


def _replace_measurements(
    connection: sqlite3.Connection,
    project_id: str,
    batch_id: str,
    version_id: str,
    rows: Iterable[Tuple[str, float, Optional[float], Optional[float], Optional[float], Optional[float], Optional[str]]],
) -> int:
    connection.execute(
        "DELETE FROM measurements WHERE project_id = ? AND batch_id = ? AND version_id = ?",
        (project_id, batch_id, version_id),
    )

    count = 0
    for output_key, freq_hz, value, phase, real, imag, unit in rows:
        connection.execute(
            """
            INSERT INTO measurements (
                project_id, batch_id, version_id, output_key, freq_hz, value, phase, real, imag, unit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, batch_id, version_id, output_key, freq_hz) DO UPDATE SET
                value=excluded.value,
                phase=excluded.phase,
                real=excluded.real,
                imag=excluded.imag,
                unit=excluded.unit
            """,
            (project_id, batch_id, version_id, output_key, freq_hz, value, phase, real, imag, unit),
        )
        count += 1
    return count


def _replace_measurement_meta(
    connection: sqlite3.Connection,
    project_id: str,
    batch_id: str,
    version_id: str,
    metadata_by_output: Dict[str, Dict[str, str]],
    params_by_output: Dict[str, Dict[str, str]],
) -> int:
    connection.execute(
        "DELETE FROM measurement_meta WHERE project_id = ? AND batch_id = ? AND version_id = ?",
        (project_id, batch_id, version_id),
    )

    count = 0
    for output_key in sorted(metadata_by_output.keys()):
        metadata = metadata_by_output.get(output_key, {})
        params = params_by_output.get(output_key, {})
        connection.execute(
            """
            INSERT INTO measurement_meta (
                project_id, batch_id, version_id, output_key,
                graph_caption, data_legend, data_format, data_domain, data_level_type,
                absc_unit, base_unit, bode_type, source_desc, params_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, batch_id, version_id, output_key) DO UPDATE SET
                graph_caption=excluded.graph_caption,
                data_legend=excluded.data_legend,
                data_format=excluded.data_format,
                data_domain=excluded.data_domain,
                data_level_type=excluded.data_level_type,
                absc_unit=excluded.absc_unit,
                base_unit=excluded.base_unit,
                bode_type=excluded.bode_type,
                source_desc=excluded.source_desc,
                params_json=excluded.params_json
            """,
            (
                project_id,
                batch_id,
                version_id,
                output_key,
                metadata.get("Graph_Caption"),
                metadata.get("Data_Legend"),
                metadata.get("Data_Format"),
                metadata.get("Data_Domain"),
                metadata.get("Data_LevelType"),
                metadata.get("Data_AbscUnit"),
                metadata.get("Data_BaseUnit"),
                metadata.get("Graph_BodeType"),
                metadata.get("SourceDesc"),
                json.dumps(params, sort_keys=True) if params else None,
            ),
        )
        count += 1
    return count


def _import_one_version(
    connection: sqlite3.Connection,
    project_id: str,
    artifact: VersionArtifacts,
) -> Tuple[str, int, int]:
    measurement_rows: List[Tuple[str, float, Optional[float], Optional[float], Optional[float], Optional[float], Optional[str]]] = []
    parse_fail_keys: List[str] = []
    metadata_by_output: Dict[str, Dict[str, str]] = {}
    params_by_output: Dict[str, Dict[str, str]] = {}

    if artifact.index_file is not None and artifact.index_file.exists():
        expected_keys = set(_parse_index_suffixes(artifact.index_file))
    else:
        expected_keys = set(artifact.outputs.keys())

    parse_keys = sorted(expected_keys) if expected_keys else sorted(artifact.outputs.keys())
    for output_key in parse_keys:
        output_file = artifact.outputs.get(output_key)
        if output_file is None:
            continue

        parsed = parse_result_file(output_file)
        metadata_by_output[output_key] = parsed.metadata
        params_by_output[output_key] = parsed.params

        if not parsed.rows:
            parse_fail_keys.append(output_key)
            continue

        for row in parsed.rows:
            measurement_rows.append(
                (
                    output_key,
                    row.freq_hz,
                    row.value,
                    row.phase,
                    row.real,
                    row.imag,
                    row.unit,
                )
            )

    found_keys = set(artifact.outputs.keys())
    missing_expected = (expected_keys - found_keys) if expected_keys else set()

    if not measurement_rows:
        status = "fail"
    elif missing_expected or parse_fail_keys:
        status = "partial"
    else:
        status = "ok"

    imported_at = _now_iso()
    _upsert_version(
        connection=connection,
        project_id=project_id,
        artifact=artifact,
        status=status,
        imported_at=imported_at,
    )
    row_count = _replace_measurements(
        connection=connection,
        project_id=project_id,
        batch_id=artifact.batch_id,
        version_id=artifact.version_id,
        rows=measurement_rows,
    )
    metadata_rows = _replace_measurement_meta(
        connection=connection,
        project_id=project_id,
        batch_id=artifact.batch_id,
        version_id=artifact.version_id,
        metadata_by_output=metadata_by_output,
        params_by_output=params_by_output,
    )
    return status, row_count, metadata_rows


def run_dataset_import(
    project_id: str,
    project_root: Path,
    manifest_path: Path,
    rebuild: bool,
) -> ImportSummary:
    dataset_dir = project_root / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    db_path = dataset_dir / "dataset.sqlite"
    effective_rebuild = rebuild

    artifacts, discovered_batch_ids = discover_artifacts(project_root)
    manifest = _load_manifest(manifest_path, project_id=project_id)

    existing_index: Dict[str, Dict] = {}
    legacy_index: Dict[str, Dict] = {}
    for entry in manifest.get("import_index", []):
        if not isinstance(entry, dict) or not entry.get("version_id"):
            continue
        version_id = str(entry.get("version_id"))
        batch_id = str(entry.get("batch_id", "")).strip()
        if batch_id:
            existing_index[_artifact_key(batch_id, version_id)] = entry
        else:
            legacy_index[version_id] = entry

    if db_path.exists() and not rebuild:
        probe = sqlite3.connect(str(db_path))
        try:
            if not _schema_is_compatible(probe):
                effective_rebuild = True
        finally:
            probe.close()

    if effective_rebuild and db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(str(db_path))
    try:
        _create_tables(connection)

        imported_versions = 0
        skipped_versions = 0
        partial_versions = 0
        failed_versions = 0
        measurement_rows_total = 0
        metadata_rows_total = 0

        new_index: Dict[str, Dict] = {}
        for artifact in artifacts:
            signatures = _files_signature(artifact)
            index_key = _artifact_key(artifact.batch_id, artifact.version_id)
            old_entry = existing_index.get(index_key) or legacy_index.get(artifact.version_id)

            if not effective_rebuild and old_entry is not None and _is_unchanged(old_entry, signatures):
                skipped_versions += 1
                new_index[index_key] = old_entry
                continue

            status, measurement_rows, metadata_rows = _import_one_version(
                connection=connection,
                project_id=project_id,
                artifact=artifact,
            )
            imported_versions += 1
            measurement_rows_total += measurement_rows
            metadata_rows_total += metadata_rows

            if status == "partial":
                partial_versions += 1
            if status == "fail":
                failed_versions += 1

            new_index[index_key] = {
                "version_id": artifact.version_id,
                "batch_id": artifact.batch_id,
                "files": signatures,
                "imported_at": _now_iso(),
                "schema_version": "1.0",
                "status": status,
            }

        if not effective_rebuild:
            for index_key, entry in existing_index.items():
                if index_key not in new_index:
                    new_index[index_key] = entry
            for version_id, entry in legacy_index.items():
                legacy_key = version_id
                batch_id = str(entry.get("batch_id", "")).strip()
                if batch_id:
                    legacy_key = _artifact_key(batch_id, version_id)
                if legacy_key not in new_index:
                    new_index[legacy_key] = entry

        connection.commit()

        batch_ids = sorted(set(manifest.get("batch_ids", [])).union(discovered_batch_ids))
        if effective_rebuild:
            batch_ids = discovered_batch_ids

        manifest["batch_ids"] = batch_ids
        manifest["import_index"] = sorted(
            new_index.values(),
            key=lambda entry: (str(entry.get("batch_id", "")), str(entry.get("version_id", ""))),
        )
        manifest["schema_version"] = "1.0"
        if manifest.get("created_at") is None:
            manifest["created_at"] = _now_iso()
        _write_manifest(manifest_path, manifest)

        return ImportSummary(
            total_versions=len(artifacts),
            imported_versions=imported_versions,
            skipped_versions=skipped_versions,
            partial_versions=partial_versions,
            failed_versions=failed_versions,
            measurement_rows=measurement_rows_total,
            metadata_rows=metadata_rows_total,
        )
    finally:
        connection.close()
