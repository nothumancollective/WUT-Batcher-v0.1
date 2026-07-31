"""Project storage layout and persistence for the rebuild architecture."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from app.feature_flags import use_project_library_storage
from app.models import Batch, Project, VersionSpec
from app.version_resolver import allocate_version_ids


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


@dataclass(frozen=True)
class ProjectPaths:
    projects_root: Path
    project_dir: Path
    project_json: Path
    batches_dir: Path
    versions_dir: Path
    dataset_dir: Path
    tables_dir: Path
    logs_dir: Path


@dataclass(frozen=True)
class BatchPaths:
    batch_dir: Path
    batch_json: Path


@dataclass(frozen=True)
class VersionPaths:
    version_dir: Path
    version_json: Path
    cfg_dir: Path
    cfg_file: Path
    abec_dir: Path
    abec_file: Path
    ath_work_dir: Path
    exports_dir: Path
    logs_dir: Path
    log_file: Path

    def as_dict(self) -> Dict[str, str]:
        return {
            "version_dir": str(self.version_dir),
            "version_json": str(self.version_json),
            "cfg_dir": str(self.cfg_dir),
            "cfg_file": str(self.cfg_file),
            "abec_dir": str(self.abec_dir),
            "abec_file": str(self.abec_file),
            "ath_work_dir": str(self.ath_work_dir),
            "exports_dir": str(self.exports_dir),
            "logs_dir": str(self.logs_dir),
            "log_file": str(self.log_file),
        }


def resolve_project_paths(projects_root: Path, project_id: str, *, ensure: bool = False) -> ProjectPaths:
    project_dir = projects_root / project_id
    if use_project_library_storage():
        preferred_dataset = project_dir / "db"
        legacy_dataset = project_dir / "dataset"
        if ensure or preferred_dataset.exists() or not legacy_dataset.exists():
            dataset_dir = preferred_dataset
        else:
            dataset_dir = legacy_dataset
        preferred_logs = project_dir / "logs"
        legacy_logs = project_dir / "_logs"
        if ensure or preferred_logs.exists() or not legacy_logs.exists():
            logs_dir = preferred_logs
        else:
            logs_dir = legacy_logs
    else:
        dataset_dir = project_dir / "dataset"
        logs_dir = project_dir / "_logs"
    paths = ProjectPaths(
        projects_root=projects_root,
        project_dir=project_dir,
        project_json=project_dir / "project.json",
        batches_dir=project_dir / "batches",
        versions_dir=project_dir / "versions",
        dataset_dir=dataset_dir,
        tables_dir=project_dir / "tables",
        logs_dir=logs_dir,
    )
    if ensure:
        for path in (
            paths.projects_root,
            paths.project_dir,
            paths.batches_dir,
            paths.versions_dir,
            paths.dataset_dir,
            paths.tables_dir,
            paths.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
    return paths


def resolve_batch_paths(project_paths: ProjectPaths, batch_id: str, *, ensure: bool = False) -> BatchPaths:
    batch_dir = project_paths.batches_dir / batch_id
    paths = BatchPaths(
        batch_dir=batch_dir,
        batch_json=batch_dir / "batch.json",
    )
    if ensure:
        paths.batch_dir.mkdir(parents=True, exist_ok=True)
    return paths


def resolve_version_paths(project_paths: ProjectPaths, version_id: str, *, ensure: bool = False) -> VersionPaths:
    version_dir = project_paths.versions_dir / version_id
    paths = VersionPaths(
        version_dir=version_dir,
        version_json=version_dir / "version.json",
        cfg_dir=version_dir / "cfg",
        cfg_file=version_dir / "cfg" / "input.cfg",
        abec_dir=version_dir / "abec",
        abec_file=version_dir / "abec" / "Project.abec",
        ath_work_dir=version_dir / "ath_work",
        exports_dir=version_dir / "exports",
        logs_dir=version_dir / "logs",
        log_file=version_dir / "logs" / "version.log",
    )
    if ensure:
        for path in (
            paths.version_dir,
            paths.cfg_dir,
            paths.abec_dir,
            paths.ath_work_dir,
            paths.exports_dir,
            paths.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
    return paths


class ProjectRepository:
    def __init__(self, projects_root: str | Path = "projects") -> None:
        self.projects_root = Path(projects_root)

    def project_paths(self, project_id: str, *, ensure: bool = False) -> ProjectPaths:
        return resolve_project_paths(self.projects_root, project_id, ensure=ensure)

    def list_projects(self) -> List[Project]:
        if not self.projects_root.exists():
            return []
        projects: List[Project] = []
        for entry in sorted(self.projects_root.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            project_json = entry / "project.json"
            if not project_json.exists():
                continue
            try:
                projects.append(Project.from_dict(_read_json(project_json)))
            except Exception:
                continue
        return projects

    def load_project(self, project_id: str) -> Project:
        paths = self.project_paths(project_id, ensure=False)
        if not paths.project_json.exists():
            raise FileNotFoundError(f"Project not found: {paths.project_json}")
        return Project.from_dict(_read_json(paths.project_json))

    def init_project(self, project: Project | Dict[str, Any]) -> ProjectPaths:
        project_model = project if isinstance(project, Project) else Project.from_dict(project)
        paths = self.project_paths(project_model.project_id, ensure=True)

        if paths.project_json.exists():
            existing = Project.from_dict(_read_json(paths.project_json))
            if existing.constraints.to_dict() != project_model.constraints.to_dict():
                raise ValueError(
                    "Project constraints are immutable and already persisted; refusing overwrite with different values."
                )
        _write_json(paths.project_json, project_model.to_dict())
        return paths

    def save_batch(self, project_id: str, batch: Batch | Dict[str, Any]) -> BatchPaths:
        batch_model = batch if isinstance(batch, Batch) else Batch.from_dict(batch)
        paths = self.project_paths(project_id, ensure=True)
        batch_paths = resolve_batch_paths(paths, batch_model.batch_id, ensure=True)
        _write_json(batch_paths.batch_json, batch_model.to_dict())
        return batch_paths

    def list_batches(self, project_id: str) -> List[Batch]:
        paths = self.project_paths(project_id, ensure=False)
        if not paths.batches_dir.exists():
            return []
        batches: List[Batch] = []
        for entry in sorted(paths.batches_dir.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            batch_json = entry / "batch.json"
            if not batch_json.exists():
                continue
            try:
                batches.append(Batch.from_dict(_read_json(batch_json)))
            except Exception:
                continue
        return batches

    def load_batch(self, project_id: str, batch_id: str) -> Batch:
        paths = self.project_paths(project_id, ensure=False)
        batch_json = paths.batches_dir / batch_id / "batch.json"
        if not batch_json.exists():
            raise FileNotFoundError(f"Batch not found: {batch_json}")
        return Batch.from_dict(_read_json(batch_json))

    def existing_version_ids(self, project_id: str) -> List[str]:
        paths = self.project_paths(project_id, ensure=False)
        if not paths.versions_dir.exists():
            return []
        return sorted(entry.name for entry in paths.versions_dir.iterdir() if entry.is_dir())

    def list_versions(self, project_id: str, *, batch_id: str | None = None) -> List[VersionSpec]:
        paths = self.project_paths(project_id, ensure=False)
        if not paths.versions_dir.exists():
            return []
        versions: List[VersionSpec] = []
        for entry in sorted(paths.versions_dir.iterdir(), key=lambda item: item.name):
            version_json = entry / "version.json"
            if not entry.is_dir() or not version_json.exists():
                continue
            try:
                version = VersionSpec.from_dict(_read_json(version_json))
            except Exception:
                continue
            if batch_id is not None and version.batch_id != str(batch_id):
                continue
            versions.append(version)
        return versions

    def allocate_project_version_ids(self, project_id: str, count: int) -> List[str]:
        existing = self.existing_version_ids(project_id)
        return allocate_version_ids(count, existing)

    def materialize_versions(
        self,
        project_id: str,
        batch_id: str,
        versions: Sequence[VersionSpec],
        *,
        cfg_placeholder_text: str = "; cfg placeholder generated by WUT Batcher\n",
    ) -> List[VersionSpec]:
        project_paths = self.project_paths(project_id, ensure=True)
        materialized: List[VersionSpec] = []

        for version in versions:
            if version.project_id and version.project_id != project_id:
                raise ValueError(f"Version project mismatch for {version.version_id}: {version.project_id} != {project_id}")
            if version.batch_id and version.batch_id != batch_id:
                raise ValueError(f"Version batch mismatch for {version.version_id}: {version.batch_id} != {batch_id}")

            version_paths = resolve_version_paths(project_paths, version.version_id, ensure=True)
            if not version_paths.cfg_file.exists():
                version_paths.cfg_file.write_text(cfg_placeholder_text, encoding="utf-8")
            if not version_paths.abec_file.exists():
                version_paths.abec_file.write_text("", encoding="utf-8")
            if not version_paths.log_file.exists():
                version_paths.log_file.write_text("", encoding="utf-8")

            payload = version.to_dict()
            payload["paths"] = version_paths.as_dict()
            _write_json(version_paths.version_json, payload)

            version.paths = version_paths.as_dict()
            materialized.append(version)

        return materialized
