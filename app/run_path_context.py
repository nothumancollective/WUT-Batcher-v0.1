"""Deterministic runner path context for one pipeline run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.project_storage import ProjectPaths, VersionPaths, resolve_project_paths, resolve_version_paths


@dataclass(frozen=True)
class ToolPathContext:
    ath_executable: Optional[str]
    akabak_executable: Optional[str]
    vacs_executable: Optional[str]


@dataclass(frozen=True)
class VersionRunPaths:
    version_id: str
    project_paths: ProjectPaths
    version_paths: VersionPaths
    run_cfg_path: Path
    ath_export_dir: Optional[Path]
    run_exports_dir: Path

    @property
    def version_json(self) -> Path:
        return self.version_paths.version_json

    @property
    def cfg_path(self) -> Path:
        return self.version_paths.cfg_file

    @property
    def ath_work_dir(self) -> Path:
        return self.version_paths.ath_work_dir

    @property
    def logs_dir(self) -> Path:
        return self.version_paths.logs_dir

    @property
    def abec_path(self) -> Path:
        return self.version_paths.abec_file

    @property
    def export_dir(self) -> Path:
        return self.run_exports_dir

    def abec_sync_roots(self) -> tuple[Path, ...]:
        rows = [self.ath_export_dir, self.ath_work_dir, self.abec_path.parent]
        return tuple(path for path in rows if path is not None)


@dataclass(frozen=True)
class RunPathContext:
    app_root: Path
    library_root: Optional[Path]
    project_root: Path
    run_id: str
    run_root: Path
    ath_export_root: Optional[Path]
    tools: ToolPathContext
    project_paths: ProjectPaths

    @classmethod
    def build(
        cls,
        *,
        project_root: Path,
        run_id: str,
        library_root: Optional[Path],
        ath_export_root: Optional[Path],
        ath_executable: Optional[str],
        akabak_executable: Optional[str],
        vacs_executable: Optional[str],
    ) -> "RunPathContext":
        root = Path(project_root).expanduser().resolve()
        project_paths = resolve_project_paths(root.parent, root.name, ensure=False)
        run_root = root / "runs" / str(run_id)
        run_root.mkdir(parents=True, exist_ok=True)
        return cls(
            app_root=Path(__file__).resolve().parents[1],
            library_root=Path(library_root).expanduser().resolve() if library_root is not None else None,
            project_root=root,
            run_id=str(run_id),
            run_root=run_root,
            ath_export_root=Path(ath_export_root).expanduser().resolve() if ath_export_root is not None else None,
            tools=ToolPathContext(
                ath_executable=str(ath_executable) if ath_executable else None,
                akabak_executable=str(akabak_executable) if akabak_executable else None,
                vacs_executable=str(vacs_executable) if vacs_executable else None,
            ),
            project_paths=project_paths,
        )

    def run_debug_log_path(self) -> Path:
        return self.run_root / "pipeline.stage_debug.jsonl"

    def version(self, version_id: str, *, cfg_basename: str) -> VersionRunPaths:
        token = str(version_id)
        version_paths = resolve_version_paths(self.project_paths, token, ensure=False)
        run_cfg_path = version_paths.cfg_dir / f"{cfg_basename}.cfg"
        ath_export_dir = None
        if self.ath_export_root is not None:
            ath_export_dir = self.ath_export_root / run_cfg_path.stem
        run_exports_dir = version_paths.exports_dir / str(self.run_id)
        return VersionRunPaths(
            version_id=token,
            project_paths=self.project_paths,
            version_paths=version_paths,
            run_cfg_path=run_cfg_path,
            ath_export_dir=ath_export_dir,
            run_exports_dir=run_exports_dir,
        )
