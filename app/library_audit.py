"""Strictly read-only structural audit for WUT Project Library roots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.batch_orchestrator import _version_plan_signature
from app.models import VersionSpec


PROJECT_FOLDER_RE = re.compile(
    r"^(?P<display>P\d{4,})__(?P<uid>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$"
)
LIBRARY_MARKERS = ("library.json", "library.sqlite", "projects")


@dataclass(frozen=True)
class LibraryAuditIssue:
    severity: str
    code: str
    path: str
    detail: str


def _read_json(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "JSON root is not an object."
    return payload, None


def _count_dirs(path: Path) -> int:
    if not path.is_dir():
        return 0
    try:
        return sum(1 for item in path.iterdir() if item.is_dir())
    except OSError:
        return 0


def _dir_has_entries(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        return next(path.iterdir(), None) is not None
    except OSError:
        return False


def _version_run_counts(project_db: Optional[Path]) -> Dict[str, int]:
    if project_db is None or not project_db.is_file():
        return {}
    connection: Optional[sqlite3.Connection] = None
    try:
        connection = sqlite3.connect(f"file:{project_db.as_posix()}?mode=ro", uri=True)
        rows = connection.execute(
            "SELECT version_id, COUNT(DISTINCT run_id) FROM run_versions GROUP BY version_id"
        ).fetchall()
        return {str(version_id): int(count) for version_id, count in rows}
    except sqlite3.DatabaseError:
        return {}
    finally:
        if connection is not None:
            connection.close()


def _duplicate_version_plans(project_dir: Path, project_db: Optional[Path]) -> Tuple[List[Dict[str, Any]], List[LibraryAuditIssue]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    issues: List[LibraryAuditIssue] = []
    run_counts = _version_run_counts(project_db)
    versions_dir = project_dir / "versions"
    try:
        version_dirs = sorted((item for item in versions_dir.iterdir() if item.is_dir()), key=lambda item: item.name)
    except OSError:
        return [], issues
    for version_dir in version_dirs:
        manifest_path = version_dir / "version.json"
        if not manifest_path.is_file():
            continue
        payload, error = _read_json(manifest_path)
        if error or payload is None:
            issues.append(
                LibraryAuditIssue(
                    "warn",
                    "invalid_version_manifest",
                    str(manifest_path),
                    error or "Version manifest is not readable.",
                )
            )
            continue
        try:
            version = VersionSpec.from_dict(payload)
            signature = json.dumps(
                _version_plan_signature(version),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        except Exception as exc:
            issues.append(LibraryAuditIssue("warn", "invalid_version_manifest", str(manifest_path), str(exc)))
            continue
        version_id = str(payload.get("version_id") or version_dir.name)
        groups.setdefault(signature, []).append(
            {
                "version_id": version_id,
                "batch_id": str(payload.get("batch_id") or ""),
                "sequence_index": int(payload.get("sequence_index", 0) or 0),
                "run_count": int(run_counts.get(version_id, 0)),
                "has_exports": _dir_has_entries(version_dir / "exports"),
                "path": str(version_dir),
            }
        )

    duplicates: List[Dict[str, Any]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda row: row["version_id"])
        duplicates.append(
            {
                "batch_id": members[0]["batch_id"],
                "sequence_index": members[0]["sequence_index"],
                "version_ids": [row["version_id"] for row in members],
                "members": members,
            }
        )
        issues.append(
            LibraryAuditIssue(
                "warn",
                "duplicate_version_plan",
                str(project_dir / "versions"),
                "Equivalent immutable version plan is materialized more than once: "
                + ", ".join(row["version_id"] for row in members)
                + ". Retained because run/export histories may differ.",
            )
        )
    duplicates.sort(key=lambda row: (row["batch_id"], row["sequence_index"], row["version_ids"]))
    return duplicates, issues


def _run_dir_counts(path: Path) -> Tuple[int, int]:
    if not path.is_dir():
        return 0, 0
    try:
        names = [item.name for item in path.iterdir() if item.is_dir()]
    except OSError:
        return 0, 0
    auxiliary = sum(1 for name in names if name.lower().startswith("ath_"))
    return len(names) - auxiliary, auxiliary


def _project_audit(project_dir: Path) -> Tuple[Dict[str, Any], List[LibraryAuditIssue]]:
    issues: List[LibraryAuditIssue] = []
    match = PROJECT_FOLDER_RE.match(project_dir.name)
    display_number = str(match.group("display")) if match else ""
    project_uid = str(match.group("uid")) if match else ""
    if match is None:
        issues.append(
            LibraryAuditIssue(
                severity="warn",
                code="noncanonical_project_folder",
                path=str(project_dir),
                detail="Expected <P-number>__<UUID> project folder naming.",
            )
        )

    manifest_path = project_dir / "project.json"
    manifest: Optional[Dict[str, Any]] = None
    if not manifest_path.is_file():
        issues.append(
            LibraryAuditIssue("error", "missing_project_manifest", str(manifest_path), "project.json is missing.")
        )
    else:
        manifest, manifest_error = _read_json(manifest_path)
        if manifest_error:
            issues.append(
                LibraryAuditIssue("error", "invalid_project_manifest", str(manifest_path), manifest_error)
            )

    if manifest is not None and match is not None:
        manifest_display = str(manifest.get("display_number") or manifest.get("project_id") or "").strip()
        manifest_uid = str(manifest.get("project_uid") or "").strip()
        if manifest_display and manifest_display != display_number:
            issues.append(
                LibraryAuditIssue(
                    "error",
                    "project_display_mismatch",
                    str(manifest_path),
                    f"Folder uses {display_number}, manifest uses {manifest_display}.",
                )
            )
        if manifest_uid and manifest_uid.lower() != project_uid.lower():
            issues.append(
                LibraryAuditIssue(
                    "error",
                    "project_uid_mismatch",
                    str(manifest_path),
                    "Folder UUID and manifest project_uid differ.",
                )
            )

    preferred_db = project_dir / "db" / "project.sqlite"
    legacy_db = project_dir / "dataset" / "project.sqlite"
    if not preferred_db.is_file() and not legacy_db.is_file():
        issues.append(
            LibraryAuditIssue(
                "warn",
                "missing_project_db",
                str(project_dir),
                "No db/project.sqlite (or legacy dataset/project.sqlite) found.",
            )
        )
    if preferred_db.is_file() and legacy_db.is_file():
        issues.append(
            LibraryAuditIssue(
                "error",
                "parallel_project_databases",
                str(project_dir),
                "Both preferred and legacy project.sqlite files exist; authority is ambiguous.",
            )
        )
    elif legacy_db.is_file():
        issues.append(
            LibraryAuditIssue(
                "warn",
                "legacy_project_database",
                str(legacy_db),
                "Legacy dataset/project.sqlite is in use.",
            )
        )

    authoritative_db = preferred_db if preferred_db.is_file() else (legacy_db if legacy_db.is_file() else None)
    duplicate_version_plans, duplicate_issues = _duplicate_version_plans(project_dir, authoritative_db)
    issues.extend(duplicate_issues)

    run_count, auxiliary_run_dir_count = _run_dir_counts(project_dir / "runs")
    return (
        {
            "folder": project_dir.name,
            "path": str(project_dir),
            "display_number": display_number or None,
            "project_uid": project_uid or None,
            "manifest_ok": manifest is not None,
            "database_path": str(preferred_db if preferred_db.is_file() else legacy_db) if (preferred_db.is_file() or legacy_db.is_file()) else None,
            "batch_count": _count_dirs(project_dir / "batches"),
            "version_count": _count_dirs(project_dir / "versions"),
            "run_count": run_count,
            "auxiliary_run_dir_count": auxiliary_run_dir_count,
            "export_batch_count": _count_dirs(project_dir / "exports"),
            "duplicate_version_plan_count": len(duplicate_version_plans),
            "duplicate_version_plans": duplicate_version_plans,
        },
        issues,
    )


def discover_library_candidates(parent: Path, *, active_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """List sibling folders that look like libraries; never initialize them."""

    if not parent.is_dir():
        return []
    active_key = str(active_root.resolve()).lower() if active_root is not None else ""
    rows: List[Dict[str, Any]] = []
    try:
        candidates: Iterable[Path] = sorted(
            (item for item in parent.iterdir() if item.is_dir()),
            key=lambda item: item.name.lower(),
        )
    except OSError:
        return []
    for candidate in candidates:
        markers = [marker for marker in LIBRARY_MARKERS if (candidate / marker).exists()]
        direct_project_count = 0
        try:
            direct_project_count = sum(
                1
                for item in candidate.iterdir()
                if item.is_dir() and (PROJECT_FOLDER_RE.match(item.name) or item.name.lower().startswith("project_p"))
            )
        except OSError:
            direct_project_count = 0
        if not markers and not direct_project_count:
            continue
        try:
            candidate_key = str(candidate.resolve()).lower()
            modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            candidate_key = str(candidate).lower()
            modified = None
        canonical_project_count = _count_dirs(candidate / "projects")
        layout = "canonical" if set(LIBRARY_MARKERS).issubset(set(markers)) else "partial_library"
        if direct_project_count and not markers:
            layout = "detached_projects_container"
            markers = ["project_folders"]
        rows.append(
            {
                "path": str(candidate),
                "active": bool(active_key and candidate_key == active_key),
                "layout": layout,
                "markers": markers,
                "project_count": canonical_project_count or direct_project_count,
                "modified_at": modified,
            }
        )
    return rows


def audit_library_root(root: str | Path, *, scan_siblings: bool = False) -> Dict[str, Any]:
    library_root = Path(root).expanduser().resolve(strict=False)
    issues: List[LibraryAuditIssue] = []
    projects: List[Dict[str, Any]] = []

    if not library_root.is_dir():
        issues.append(LibraryAuditIssue("error", "missing_library_root", str(library_root), "Library root is missing."))
    else:
        metadata_path = library_root / "library.json"
        index_path = library_root / "library.sqlite"
        projects_path = library_root / "projects"
        if not metadata_path.is_file():
            issues.append(LibraryAuditIssue("error", "missing_library_metadata", str(metadata_path), "library.json is missing."))
        else:
            _metadata, metadata_error = _read_json(metadata_path)
            if metadata_error:
                issues.append(LibraryAuditIssue("error", "invalid_library_metadata", str(metadata_path), metadata_error))
        if not index_path.is_file():
            issues.append(LibraryAuditIssue("error", "missing_library_index", str(index_path), "library.sqlite is missing."))
        if (library_root / "global.sqlite").exists():
            issues.append(
                LibraryAuditIssue(
                    "error",
                    "parallel_library_indexes",
                    str(library_root),
                    "Both library.sqlite and legacy global.sqlite exist in this root.",
                )
            )
        if not projects_path.is_dir():
            issues.append(LibraryAuditIssue("error", "missing_projects_dir", str(projects_path), "projects/ is missing."))
        else:
            try:
                project_dirs = sorted((item for item in projects_path.iterdir() if item.is_dir()), key=lambda item: item.name)
            except OSError as exc:
                project_dirs = []
                issues.append(LibraryAuditIssue("error", "projects_unreadable", str(projects_path), str(exc)))
            for project_dir in project_dirs:
                project_row, project_issues = _project_audit(project_dir)
                projects.append(project_row)
                issues.extend(project_issues)

    siblings = discover_library_candidates(library_root.parent, active_root=library_root) if scan_siblings else []
    detached_indexes: List[Dict[str, Any]] = []
    if scan_siblings and library_root.parent.is_dir():
        for name in ("library.sqlite", "global.sqlite"):
            candidate = library_root.parent / name
            if not candidate.is_file():
                continue
            try:
                size_bytes = int(candidate.stat().st_size)
                modified_at = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc).isoformat()
            except OSError:
                size_bytes = 0
                modified_at = None
            detached_indexes.append(
                {
                    "path": str(candidate),
                    "size_bytes": size_bytes,
                    "modified_at": modified_at,
                    "detail": "Database index is outside any marked library root; authority is not inferred.",
                }
            )
    severity_counts = {
        severity: sum(1 for issue in issues if issue.severity == severity)
        for severity in ("error", "warn", "info")
    }
    return {
        "read_only": True,
        "library_root": str(library_root),
        "status": "error" if severity_counts["error"] else ("warn" if severity_counts["warn"] else "ok"),
        "severity_counts": severity_counts,
        "project_count": len(projects),
        "projects": projects,
        "issues": [asdict(issue) for issue in issues],
        "sibling_candidates": siblings,
        "detached_index_candidates": detached_indexes,
    }
