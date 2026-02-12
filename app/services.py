"""Core application services used by CLI and GUI (UI-orchestrator only)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import shutil
from typing import Any, Dict, List, Optional

from app.batch_orchestrator import PlanningSummary, materialize_batch_plan
from app.compatibility_service import CompatibilityService
from app.cfg_renderer import render_cfg_text
from app.models import Batch, ParamSelection, Project, ProjectConstraints, SweepSpec
from app.project_storage import ProjectRepository
from app.runtime_orchestrator import RuntimeSummary, run_batch_pipeline
from app.runners import AthRunner
from app.settings_store import SettingsStore, UserSettings
from app.tidy_dataset import TidyDatasetWriter
from app.version_resolver import resolve_versions


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _next_prefixed_id(existing_ids: List[str], prefix: str) -> str:
    max_num = 0
    for raw in existing_ids:
        value = str(raw).strip()
        if not value.startswith(prefix):
            continue
        tail = value[len(prefix) :]
        if tail.isdigit():
            max_num = max(max_num, int(tail))
    return f"{prefix}{max_num + 1:03d}"


ATH_STL_EXPORT_DIRECTIVE: Optional[str] = None


def _apply_stl_export_hook(cfg_text: str) -> tuple[str, bool]:
    if ATH_STL_EXPORT_DIRECTIVE:
        directive_line = ATH_STL_EXPORT_DIRECTIVE.strip()
        if directive_line and directive_line not in cfg_text:
            return (cfg_text.rstrip() + f"\n{directive_line}\n", False)
        return (cfg_text, False)

    block = (
        "\n; --- STL export hook (TODO) ---\n"
        "; TODO: Set ATH_STL_EXPORT_DIRECTIVE in app/services.py once verified.\n"
        "; Example placeholder (inactive): ; Export.STL = 1\n"
    )
    if "STL export hook (TODO)" in cfg_text:
        return (cfg_text, True)
    return (cfg_text + block, True)


def _select_generated_abec(export_dir: Path) -> Optional[Path]:
    candidates = [path for path in export_dir.rglob("*.abec") if path.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    return candidates[0]


def _is_executable_path(path: Optional[str]) -> bool:
    if not path:
        return False
    candidate = Path(path).expanduser()
    return candidate.exists() and candidate.is_file()


class OrchestratorService:
    def __init__(self, settings_store: SettingsStore | None = None) -> None:
        self.settings_store = settings_store or SettingsStore()
        self.settings = self.settings_store.load()
        self.repo = ProjectRepository(self.settings.library_root)
        self.compatibility = CompatibilityService()

    def reload_settings(self) -> UserSettings:
        self.settings = self.settings_store.load()
        self.repo = ProjectRepository(self.settings.library_root)
        return self.settings

    def save_settings(self, settings: UserSettings) -> Dict[str, Any]:
        self.settings_store.save(settings)
        self.settings = settings
        self.repo = ProjectRepository(self.settings.library_root)
        return {
            "saved": True,
            "path": str(self.settings_store.path),
            "validation": self.settings_store.validate(settings),
        }

    def validate_settings(self, settings: Optional[UserSettings] = None) -> Dict[str, str]:
        return self.settings_store.validate(settings or self.settings)

    def list_projects(self) -> List[Project]:
        return self.repo.list_projects()

    def compatibility_catalog_keys(self) -> List[str]:
        return list(self.compatibility.catalog_keys)

    def evaluate_project_constraints(self, constraints: Dict[str, Any]) -> Dict[str, Any]:
        return self.compatibility.evaluate_project_constraints(constraints)

    def evaluate_batch_definition(
        self,
        *,
        project_id: str,
        selected_params: Dict[str, Any],
        sweeps: Dict[str, Dict[str, Any]],
        sweep_mode: str,
    ) -> Dict[str, Any]:
        project = self.repo.load_project(project_id)
        return self.compatibility.evaluate_batch_definition(
            project.constraints,
            selected_params=selected_params,
            sweeps=sweeps,
            sweep_mode=sweep_mode,
        )

    def list_versions(self, project_id: str, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
        project_paths = self.repo.project_paths(project_id, ensure=True)
        project_db = project_paths.dataset_dir / "project.sqlite"
        if not project_db.exists():
            return []
        with closing(sqlite3.connect(str(project_db))) as conn:
            if batch_id:
                rows = conn.execute(
                    """
                    SELECT version_id, batch_id, status, created_at, finished_at
                    FROM versions
                    WHERE project_id = ? AND batch_id = ?
                    ORDER BY version_id
                    """,
                    (project_id, batch_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT version_id, batch_id, status, created_at, finished_at
                    FROM versions
                    WHERE project_id = ?
                    ORDER BY batch_id, version_id
                    """,
                    (project_id,),
                ).fetchall()
        return [
            {
                "version_id": str(row[0]),
                "batch_id": str(row[1]),
                "status": str(row[2]),
                "created_at": row[3],
                "finished_at": row[4],
            }
            for row in rows
        ]

    def sync_global_db(self, max_items_per_project: int = 100) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        total_processed = 0
        total_synced = 0
        total_failed = 0
        for project in self.repo.list_projects():
            writer = TidyDatasetWriter(
                self.repo.project_paths(project.project_id, ensure=True).project_dir,
                library_root=self.settings.library_root,
            )
            summary = writer.retry_pending_global_writes(max_items=max_items_per_project)
            results.append({"project_id": project.project_id, **summary})
            total_processed += int(summary.get("processed", 0))
            total_synced += int(summary.get("synced", 0))
            total_failed += int(summary.get("failed", 0))
        return {
            "projects": results,
            "processed": total_processed,
            "synced": total_synced,
            "failed": total_failed,
        }

    def create_project(self, project_name: str, constraints: Dict[str, Any]) -> Project:
        existing = self.repo.list_projects()
        project_id = _next_prefixed_id([project.project_id for project in existing], "P")
        project_root = self.repo.project_paths(project_id, ensure=False).project_dir
        project = Project(
            project_id=project_id,
            name=project_name.strip() or project_id,
            root_path=str(project_root),
            constraints=ProjectConstraints.from_dict(
                {
                    "project_id": project_id,
                    "fixed_params": dict(constraints.get("fixed_params", {}) or {}),
                    "limits": dict(constraints.get("limits", {}) or {}),
                    "runner_mode": str(constraints.get("runner_mode") or "AkabakImportFixedSource"),
                    "notes": constraints.get("notes"),
                }
            ),
        )
        self.repo.init_project(project)
        TidyDatasetWriter(project_root, library_root=self.settings.library_root).register_project(project)
        return project

    def create_batch(
        self,
        *,
        project_id: str,
        batch_name: str,
        selected_params: Dict[str, Optional[float]],
        sweeps: Dict[str, Dict[str, Any]],
        sweep_mode: str,
        sim_export_params: Dict[str, Any],
    ) -> PlanningSummary:
        project = self.repo.load_project(project_id)
        batches = self.repo.list_batches(project_id)
        batch_id = _next_prefixed_id([batch.batch_id for batch in batches], "B")
        locked_keys = set(self.compatibility.runner_locked_keys(project.constraints.runner_mode))

        selected: Dict[str, ParamSelection] = {}
        for key, value in selected_params.items():
            if str(key) in locked_keys:
                continue
            selected[str(key)] = ParamSelection(value=value)

        normalized_sweeps: Dict[str, SweepSpec] = {}
        for key, payload in sweeps.items():
            if str(key) in locked_keys:
                continue
            normalized_sweeps[str(key)] = SweepSpec.from_dict(dict(payload), key=str(key))

        batch = Batch(
            batch_id=batch_id,
            project_id=project_id,
            selected_params=selected,
            sweeps=normalized_sweeps,
            sweep_mode=sweep_mode if sweep_mode in {"single", "combined"} else "single",
            runner_mode=project.constraints.runner_mode,
            extra={"batch_name": batch_name.strip() or batch_id},
        )

        sim_settings = dict(sim_export_params or {})
        if sim_settings:
            batch.sim_export_settings = batch.sim_export_settings.from_dict(sim_settings)

        return materialize_batch_plan(project, batch, projects_root=self.settings.library_root)

    def resolve_versions(self, project_id: str, batch_id: str) -> Dict[str, Any]:
        project = self.repo.load_project(project_id)
        batch = self.repo.load_batch(project_id, batch_id)
        existing_ids = self.repo.existing_version_ids(project_id)
        resolved = resolve_versions(project.constraints, batch, existing_version_ids=existing_ids, strict=False)
        return {
            "version_count": len(resolved.versions),
            "versions": [asdict(version) for version in resolved.versions],
            "issues": [issue.to_dict() for issue in resolved.issues],
        }

    def run_batch(
        self,
        project_id: str,
        batch_id: str,
        *,
        continue_on_error: bool = True,
        dry_run: Optional[bool] = None,
    ) -> RuntimeSummary:
        project = self.repo.load_project(project_id)
        batch = self.repo.load_batch(project_id, batch_id)
        if dry_run is None:
            tools = [self.settings.ath_exe, self.settings.akabak_exe, self.settings.vacs_exe]
            dry_run = not all(_is_executable_path(path) for path in tools)
        return run_batch_pipeline(
            project=project,
            batch=batch,
            projects_root=self.settings.library_root,
            template_cfg_path=self.settings.template_cfg,
            ath_executable=self.settings.ath_exe if not dry_run else None,
            akabak_executable=self.settings.akabak_exe if not dry_run else None,
            vacs_executable=self.settings.vacs_exe if not dry_run else None,
            continue_on_error=continue_on_error,
            dry_run=bool(dry_run),
        )

    def export_version(
        self,
        *,
        project_id: str,
        batch_id: str,
        version_id: str,
        export_stl: bool,
        export_abec: bool,
    ) -> Dict[str, Any]:
        project = self.repo.load_project(project_id)
        project_paths = self.repo.project_paths(project_id, ensure=True)
        dataset = TidyDatasetWriter(project_paths.project_dir, library_root=self.settings.library_root)
        set_params, unset_params = dataset.reconstruct_cfg_parameters(version_id)
        metadata = dataset.load_version_metadata(version_id)

        export_dir = project_paths.project_dir / "exports" / batch_id / version_id
        export_dir.mkdir(parents=True, exist_ok=True)
        logs_dir = export_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        template_text = "; autogenerated template\n"
        if self.settings.template_cfg:
            template_text = Path(self.settings.template_cfg).read_text(encoding="utf-8")

        cfg_text = render_cfg_text(
            template_text=template_text,
            parameters=set_params,
            version_id=version_id,
            runner_mode=project.constraints.runner_mode,
            omit_keys=unset_params,
        )
        stl_todo_added = False
        if export_stl:
            cfg_text, stl_todo_added = _apply_stl_export_hook(cfg_text)

        cfg_path = export_dir / f"{version_id}_export.cfg"
        cfg_path.write_text(cfg_text, encoding="utf-8")

        if (export_stl or export_abec) and not self.settings.ath_exe:
            raise ValueError("ATH executable is required for STL/ABEC export regeneration but is not configured.")

        ath_result: Optional[Dict[str, Any]] = None
        if (export_stl or export_abec) and self.settings.ath_exe:
            runner = AthRunner(self.settings.ath_exe)
            result = runner.run_cfg(
                cfg_path,
                version_logs_dir=logs_dir,
                workdir=export_dir,
            )
            ath_result = {
                "ok": result.ok,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "stdout_log": result.stdout_log,
                "stderr_log": result.stderr_log,
                "summary_log": result.summary_log,
            }
            if not result.ok:
                raise RuntimeError(f"ATH export run failed for {version_id} (exit_code={result.exit_code})")

        exported_abec: Optional[str] = None
        abec_source: Optional[str] = None
        if export_abec:
            target_abec = export_dir / "Project.abec"
            generated = _select_generated_abec(export_dir)
            if generated is None:
                raise RuntimeError(
                    f"ABEC export requested for {version_id}, but no .abec artifact was generated in {export_dir}."
                )
            if generated.resolve() != target_abec.resolve():
                shutil.copy2(generated, target_abec)
            abec_source = str(generated)
            exported_abec = str(target_abec)

        exported_stl: List[str] = []
        if export_stl:
            for candidate in export_dir.glob("*.stl"):
                exported_stl.append(str(candidate))

        manifest = {
            "project_id": project_id,
            "batch_id": batch_id,
            "version_id": version_id,
            "created_at": _now_iso(),
            "export_dir": str(export_dir),
            "cfg_path": str(cfg_path),
            "unset_params": unset_params,
            "param_count": len(set_params),
            "ath_result": ath_result,
            "exported_abec": exported_abec,
            "exported_abec_source": abec_source,
            "exported_stl": exported_stl,
            "stl_export_todo": stl_todo_added,
            "stl_directive": ATH_STL_EXPORT_DIRECTIVE,
            "stl_todo_note": (
                "Exact ATH STL export directive is not yet known; TODO placeholder appended to CFG."
                if stl_todo_added
                else None
            ),
            "version_metadata": metadata,
        }
        manifest_path = export_dir / "export_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return manifest
