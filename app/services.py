"""Core application services used by CLI and GUI (UI-orchestrator only)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import hashlib
import os
import re
import statistics
import time
from contextlib import closing
from pathlib import Path
import sqlite3
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Mapping, Optional

from app.batch_orchestrator import PlanningSummary, materialize_batch_plan
from app.ath_driver_assets import repair_post_ath_le_binding
from app.compatibility_service import CompatibilityService
from app.constants import (
    ATH_PREVIEW_CFG_DIR,
    ATH_PREVIEW_CFG_NAME,
    ATH_PREVIEW_EXPORT_ROOT,
    PREVIEW_CACHE_APPDIR,
    PREVIEW_CACHE_KEEP_FILES,
    PREVIEW_CACHE_MAX_AGE_DAYS,
)
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


def _settings_hash(settings: UserSettings) -> str:
    payload = {
        "library_root": settings.library_root,
        "ath_exe": settings.ath_exe,
        "akabak_exe": settings.akabak_exe,
        "vacs_exe": settings.vacs_exe,
        "template_cfg": settings.template_cfg,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _detect_git_commit() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value or None


def _percentile(sorted_values: List[float], p: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = max(0.0, min(1.0, float(p))) * float(len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = rank - lower
    if lower == upper:
        return float(sorted_values[lower])
    return float(sorted_values[lower] + ((sorted_values[upper] - sorted_values[lower]) * fraction))


class PreviewGenerationCancelled(RuntimeError):
    """Raised when an in-flight preview generation is cancelled by the UI."""


_OUTPUT_ASSIGN_RE = re.compile(r"(?im)^[ \t]*({key})[ \t]*=.*$")


def _local_appdata_root() -> Path:
    raw = os.environ.get("LOCALAPPDATA", "")
    if raw.strip():
        return Path(raw).expanduser()
    return (Path.home() / "AppData" / "Local").expanduser()


def _preview_cache_dir() -> Path:
    path = _local_appdata_root()
    for part in PREVIEW_CACHE_APPDIR:
        path = path / str(part)
    return path


def _snapshot_subdirs(root: Path) -> Dict[str, int]:
    if not root.exists():
        return {}
    result: Dict[str, int] = {}
    for entry in root.iterdir():
        if entry.is_dir():
            result[entry.name] = int(entry.stat().st_mtime_ns)
    return result


def _detect_changed_export_dir(export_root: Path, before: Mapping[str, int]) -> Optional[Path]:
    if not export_root.exists():
        return None
    after = _snapshot_subdirs(export_root)
    created = [name for name in after.keys() if name not in before]
    if created:
        created.sort(key=lambda name: after[name], reverse=True)
        return export_root / created[0]
    changed = [name for name, mtime_ns in after.items() if int(mtime_ns) > int(before.get(name, -1))]
    if changed:
        changed.sort(key=lambda name: after[name], reverse=True)
        return export_root / changed[0]
    return None


def _best_mesh_cmd_for_preview(ath_executable: Path) -> str:
    candidate = ath_executable.parent / "gmsh.exe"
    if candidate.exists():
        return str(candidate)
    return ""


def _write_preview_runtime_cfg(cfg_dir: Path, *, export_root: Path, mesh_cmd: str) -> Path:
    cfg_dir.mkdir(parents=True, exist_ok=True)
    export_value = str(export_root).replace("\\", "/")
    ath_cfg = cfg_dir / "ath.cfg"
    ath_cfg.write_text(
        (
            f'OutputRootDir = "{export_value}"\n'
            f'MeshCmd = "{mesh_cmd}"\n'
            'GnuplotPath = ""\n'
        ),
        encoding="utf-8",
    )
    return ath_cfg


def _enforce_output_flag(cfg_text: str, *, key: str, value: int) -> str:
    normalized_key = str(key).strip()
    pattern = re.compile(_OUTPUT_ASSIGN_RE.pattern.format(key=re.escape(normalized_key)))
    replacement = f"{normalized_key} = {int(value)}"
    if pattern.search(cfg_text):
        return pattern.sub(replacement, cfg_text)
    text = cfg_text.rstrip()
    return f"{text}\n{replacement}\n"


def _pick_latest_stl(search_root: Path) -> Optional[Path]:
    candidates = [path for path in search_root.rglob("*.stl") if path.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda path: int(path.stat().st_mtime_ns), reverse=True)
    return candidates[0]


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    try:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
            return
        except Exception:
            pass
        proc.kill()
        proc.wait(timeout=2.0)
    except Exception:
        return


def _prune_preview_cache(cache_dir: Path, *, keep_last: int, max_age_days: int) -> Dict[str, int]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    keep = max(1, int(keep_last))
    max_age = max(0, int(max_age_days))
    now_s = float(time.time())
    age_limit_s = float(max_age) * 86400.0

    stl_files = [path for path in cache_dir.glob("horn_preview_*.stl") if path.is_file()]
    stl_files.sort(key=lambda path: int(path.stat().st_mtime_ns), reverse=True)

    deleted_retention = 0
    if len(stl_files) > keep:
        for stale in stl_files[keep:]:
            try:
                stale.unlink()
                deleted_retention += 1
            except Exception:
                continue

    deleted_age = 0
    if age_limit_s > 0:
        for candidate in list(cache_dir.glob("*")):
            if not candidate.is_file():
                continue
            try:
                age_s = now_s - float(candidate.stat().st_mtime)
            except Exception:
                continue
            if age_s <= age_limit_s:
                continue
            try:
                candidate.unlink()
                deleted_age += 1
            except Exception:
                continue

    remaining = len([path for path in cache_dir.glob("horn_preview_*.stl") if path.is_file()])
    return {
        "deleted_retention": int(deleted_retention),
        "deleted_age": int(deleted_age),
        "remaining_stl": int(remaining),
    }


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

    def cleanup_preview_cache(
        self,
        *,
        keep_last: int = PREVIEW_CACHE_KEEP_FILES,
        max_age_days: int = PREVIEW_CACHE_MAX_AGE_DAYS,
    ) -> Dict[str, Any]:
        cache_dir = _preview_cache_dir()
        stats = _prune_preview_cache(cache_dir, keep_last=keep_last, max_age_days=max_age_days)
        return {"cache_dir": str(cache_dir), **stats}

    def generate_preview_stl(
        self,
        *,
        project_id: str,
        selected_params: Dict[str, Any],
        sweep_mode: str = "single",
        run_id: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        process_handle_cb: Optional[Callable[[subprocess.Popen[str]], None]] = None,
    ) -> Dict[str, Any]:
        if cancel_check and bool(cancel_check()):
            raise PreviewGenerationCancelled("Preview request cancelled before start.")

        ath_exe = str(self.settings.ath_exe or "").strip()
        if not ath_exe:
            fallback = Path(ATH_PREVIEW_CFG_DIR) / "ath.exe"
            if fallback.exists():
                ath_exe = str(fallback)
        if not ath_exe:
            raise ValueError("ATH executable is not configured for preview generation.")

        ath_executable = Path(ath_exe).expanduser()
        if not ath_executable.exists():
            raise FileNotFoundError(f"ATH executable not found: {ath_executable}")

        project = self.repo.load_project(project_id)

        temp_batch = Batch(
            batch_id="B_PREVIEW",
            project_id=project_id,
            selected_params={
                str(key): ParamSelection(value=value)
                for key, value in dict(selected_params or {}).items()
                if str(key).strip()
            },
            sweeps={},
            sweep_mode=str(sweep_mode or "single"),
            runner_mode=project.constraints.runner_mode,
        )
        resolved = resolve_versions(project.constraints, temp_batch, strict=True)
        if not resolved.versions:
            raise RuntimeError("No resolvable version for current draft parameters.")
        version = resolved.versions[0]

        template_text = "; autogenerated template\n"
        if self.settings.template_cfg:
            template_text = Path(self.settings.template_cfg).read_text(encoding="utf-8")

        cfg_text = render_cfg_text(
            template_text=template_text,
            parameters=dict(version.parameters),
            version_id=str(version.version_id or "V_PREVIEW"),
            runner_mode=project.constraints.runner_mode,
            omit_keys=list(version.unset_parameters),
        )
        cfg_text = _enforce_output_flag(cfg_text, key="Output.STL", value=1)
        cfg_text = _enforce_output_flag(cfg_text, key="Output.ABECProject", value=0)

        cfg_hash = hashlib.sha1(cfg_text.encode("utf-8")).hexdigest()[:10]
        run_token = str(run_id or _now_iso().replace(":", "").replace("-", ""))

        cfg_dir = Path(ATH_PREVIEW_CFG_DIR)
        export_root = Path(ATH_PREVIEW_EXPORT_ROOT)
        cache_dir = _preview_cache_dir()
        logs_dir = cache_dir / "logs"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        export_root.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        cfg_path = cfg_dir / ATH_PREVIEW_CFG_NAME
        stdout_log = logs_dir / f"preview_{run_token}.stdout.log"
        stderr_log = logs_dir / f"preview_{run_token}.stderr.log"
        summary_log = logs_dir / f"preview_{run_token}.runner.log"

        before_snapshot = _snapshot_subdirs(export_root)
        cfg_path.write_text(cfg_text, encoding="utf-8")

        backup_path = cfg_dir / "ath.wut_preview.backup.cfg"
        runtime_cfg_path = cfg_dir / "ath.cfg"
        had_runtime_cfg = runtime_cfg_path.exists()
        if had_runtime_cfg:
            try:
                shutil.copy2(runtime_cfg_path, backup_path)
            except Exception:
                had_runtime_cfg = False

        mesh_cmd = _best_mesh_cmd_for_preview(ath_executable)
        _write_preview_runtime_cfg(cfg_dir, export_root=export_root, mesh_cmd=mesh_cmd)

        command = [str(ath_executable), str(cfg_path)]
        proc: Optional[subprocess.Popen[str]] = None
        stdout_text = ""
        stderr_text = ""
        started_at = _now_iso()
        exit_code = -1

        try:
            proc = subprocess.Popen(
                command,
                cwd=str(cfg_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if process_handle_cb is not None:
                process_handle_cb(proc)

            while True:
                if cancel_check and bool(cancel_check()):
                    _terminate_process(proc)
                    raise PreviewGenerationCancelled("Preview request cancelled.")
                try:
                    out, err = proc.communicate(timeout=0.20)
                    stdout_text = str(out or "")
                    stderr_text = str(err or "")
                    break
                except subprocess.TimeoutExpired:
                    continue

            exit_code = int(proc.returncode if proc.returncode is not None else -1)
        finally:
            finished_at = _now_iso()
            stdout_log.write_text(stdout_text, encoding="utf-8")
            stderr_log.write_text(stderr_text, encoding="utf-8")
            summary_log.write_text(
                json.dumps(
                    {
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "command": command,
                        "cfg_path": str(cfg_path),
                        "run_id": run_token,
                        "exit_code": exit_code,
                        "export_root": str(export_root),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            if had_runtime_cfg and backup_path.exists():
                try:
                    shutil.copy2(backup_path, runtime_cfg_path)
                except Exception:
                    pass
            elif (not had_runtime_cfg) and runtime_cfg_path.exists():
                try:
                    runtime_cfg_path.unlink()
                except Exception:
                    pass
            if backup_path.exists():
                try:
                    backup_path.unlink()
                except Exception:
                    pass

        if exit_code != 0:
            raise RuntimeError(f"ATH preview run failed (exit_code={exit_code}).")

        export_dir = _detect_changed_export_dir(export_root, before_snapshot)
        source_stl = _pick_latest_stl(export_dir) if export_dir is not None else None
        if source_stl is None:
            source_stl = _pick_latest_stl(export_root)
        if source_stl is None:
            raise RuntimeError(f"No STL artifact generated under {export_root}.")
        if source_stl.stat().st_size <= 0:
            raise RuntimeError(f"Generated STL is empty: {source_stl}")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target_stl = cache_dir / f"horn_preview_{stamp}_{cfg_hash}.stl"
        shutil.copy2(source_stl, target_stl)

        prune_stats = _prune_preview_cache(
            cache_dir,
            keep_last=PREVIEW_CACHE_KEEP_FILES,
            max_age_days=PREVIEW_CACHE_MAX_AGE_DAYS,
        )
        return {
            "ok": True,
            "run_id": run_token,
            "cfg_hash": cfg_hash,
            "cfg_path": str(cfg_path),
            "command": command,
            "export_root": str(export_root),
            "export_dir": None if export_dir is None else str(export_dir),
            "source_stl": str(source_stl),
            "cache_stl": str(target_stl),
            "cache_dir": str(cache_dir),
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
            "summary_log": str(summary_log),
            "retention": prune_stats,
        }

    def estimate_batch_runtime(
        self,
        *,
        project_id: str,
        selected_params: Dict[str, Any],
        sweeps: Dict[str, Dict[str, Any]],
        sweep_mode: str,
        batch_id: Optional[str] = None,
        validation_state: Optional[Dict[str, Any]] = None,
        sample_limit: int = 200,
    ) -> Dict[str, Any]:
        state = dict(validation_state or {})
        if not state:
            state = self.evaluate_batch_definition(
                project_id=project_id,
                selected_params=selected_params,
                sweeps=sweeps,
                sweep_mode=sweep_mode,
            )
        version_count_preview = int(state.get("version_count_preview", 0) or 0)
        project_paths = self.repo.project_paths(project_id, ensure=True)
        dataset = TidyDatasetWriter(project_paths.project_dir, library_root=self.settings.library_root)
        durations = dataset.list_recent_success_durations(limit=sample_limit, batch_id=batch_id)
        sample_count = len(durations)
        sorted_durations = sorted(float(item) for item in durations)
        median_seconds = float(statistics.median(sorted_durations)) if sorted_durations else None
        eta_seconds = None if median_seconds is None else float(max(version_count_preview, 0) * median_seconds)
        return {
            "version_count_preview": version_count_preview,
            "eta_seconds": eta_seconds,
            "median_seconds_per_version": median_seconds,
            "sample_count": sample_count,
            "basis_stats": {
                "sample_count": sample_count,
                "median_seconds": median_seconds,
                "p25_seconds": _percentile(sorted_durations, 0.25),
                "p75_seconds": _percentile(sorted_durations, 0.75),
            },
        }

    def list_versions(self, project_id: str, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
        project_paths = self.repo.project_paths(project_id, ensure=True)
        dataset = TidyDatasetWriter(project_paths.project_dir, library_root=self.settings.library_root)
        if batch_id:
            latest_success = dataset.latest_successful_run_per_version(batch_id)
            if latest_success:
                return [
                    {
                        "version_id": str(row["version_id"]),
                        "batch_id": batch_id,
                        "status": str(row["status"]),
                        "created_at": row["started_at"],
                        "finished_at": row["finished_at"],
                        "run_id": str(row["run_id"]),
                    }
                    for row in latest_success
                ]
        else:
            rows: List[Dict[str, Any]] = []
            for batch in self.repo.list_batches(project_id):
                latest_success = dataset.latest_successful_run_per_version(batch.batch_id)
                rows.extend(
                    {
                        "version_id": str(item["version_id"]),
                        "batch_id": batch.batch_id,
                        "status": str(item["status"]),
                        "created_at": item["started_at"],
                        "finished_at": item["finished_at"],
                        "run_id": str(item["run_id"]),
                    }
                    for item in latest_success
                )
            if rows:
                return sorted(rows, key=lambda item: (str(item["batch_id"]), str(item["version_id"])))

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
                "run_id": None,
            }
            for row in rows
        ]

    def list_runs(
        self,
        *,
        project_id: str,
        batch_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        project_paths = self.repo.project_paths(project_id, ensure=True)
        dataset = TidyDatasetWriter(project_paths.project_dir, library_root=self.settings.library_root)
        return dataset.list_runs(batch_id=batch_id, status=status)

    def pin_run(self, *, project_id: str, run_id: str, tag: Optional[str] = None) -> Dict[str, Any]:
        project_paths = self.repo.project_paths(project_id, ensure=True)
        dataset = TidyDatasetWriter(project_paths.project_dir, library_root=self.settings.library_root)
        return dataset.set_run_pin(run_id, pinned=True, tag=tag)

    def unpin_run(self, *, project_id: str, run_id: str) -> Dict[str, Any]:
        project_paths = self.repo.project_paths(project_id, ensure=True)
        dataset = TidyDatasetWriter(project_paths.project_dir, library_root=self.settings.library_root)
        return dataset.set_run_pin(run_id, pinned=False, tag=None)

    def cleanup_test_data(
        self,
        *,
        project_id: str,
        delete_exports: bool,
        dry_run: bool,
    ) -> Dict[str, Any]:
        project_paths = self.repo.project_paths(project_id, ensure=True)
        dataset = TidyDatasetWriter(project_paths.project_dir, library_root=self.settings.library_root)
        return dataset.cleanup_unpinned_runs(delete_exports=delete_exports, dry_run=dry_run)

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
                    "param_states": [
                        item for item in list(constraints.get("param_states", []) or []) if isinstance(item, dict)
                    ],
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
        selected_params: Dict[str, Any],
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
            git_commit=_detect_git_commit(),
            app_version="0.1-rebuild",
            settings_hash=_settings_hash(self.settings),
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
        le_driver_sync: Optional[Dict[str, Any]] = None
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
            sync_result = repair_post_ath_le_binding(
                abec_path=target_abec,
                ath_executable=self.settings.ath_exe,
            )
            le_driver_sync = sync_result.to_dict()
            if not sync_result.ok:
                raise RuntimeError(
                    "Failed post-ATH LE repair in ABEC export folder: "
                    f"status={sync_result.status} error={sync_result.error or 'n/a'}"
                )

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
            "le_driver_sync": le_driver_sync,
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
