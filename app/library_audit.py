"""Strictly read-only structural audit for WUT Project Library roots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


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
    }
