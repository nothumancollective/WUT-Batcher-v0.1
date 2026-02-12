from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.models import AppConfig, Batch, Project
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def _json_default(obj: Any):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def _default_project_root(config: AppConfig, project_id: str) -> Path:
    return config.projects_root_path / f"Project_{project_id}"


def cmd_doctor(args: argparse.Namespace) -> int:
    import app.doctor_service as doctor_service

    config = AppConfig.load(args.config)
    report = doctor_service.run_doctor_checks(
        config,
        config_path=Path(args.config) if args.config else None,
        fix=args.fix,
        kill_zombies=args.kill_zombies,
        report_path=Path(args.report_path) if args.report_path else None,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, default=_json_default))
    return 0


def cmd_batch_job_count(args: argparse.Namespace) -> int:
    import app.batch_planner as batch_planner

    batch = Batch.load(args.batch_json)
    constraints: Dict[str, Any] = {}
    if args.constraints_json:
        constraints = _read_json(Path(args.constraints_json))

    count = batch_planner.compute_job_count(batch, constraints)
    print(count)
    return 0


def cmd_dataset_build_or_update(args: argparse.Namespace, *, rebuild: bool) -> int:
    import app.dataset_pipeline as dataset_pipeline

    config = AppConfig.load(args.config)
    project_root = _default_project_root(config, args.project_id)
    manifest_path = Path(args.manifest_path) if args.manifest_path else (project_root / "dataset_manifest.json")

    summary = dataset_pipeline.run_dataset_import(
        project_id=args.project_id,
        project_root=project_root,
        manifest_path=manifest_path,
        rebuild=rebuild,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=_json_default))
    return 0


def cmd_dataset_sync_global(args: argparse.Namespace) -> int:
    settings_store = SettingsStore()
    settings = settings_store.load()
    if args.library_root:
        settings = UserSettings(
            library_root=args.library_root,
            ath_exe=settings.ath_exe,
            akabak_exe=settings.akabak_exe,
            vacs_exe=settings.vacs_exe,
            template_cfg=settings.template_cfg,
        )
        settings_store.save(settings)
    service = OrchestratorService(settings_store=settings_store)
    summary = service.sync_global_db(max_items_per_project=args.max_items_per_project)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=_json_default))
    return 0


def cmd_plan_materialize(args: argparse.Namespace) -> int:
    from app.batch_orchestrator import materialize_batch_plan

    project = Project.from_dict(_read_json(Path(args.project_json)))
    batch = Batch.from_dict(_read_json(Path(args.batch_json)))
    summary = materialize_batch_plan(
        project=project,
        batch=batch,
        projects_root=args.projects_root or "projects",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=_json_default))
    return 0


def cmd_run_pipeline(args: argparse.Namespace) -> int:
    from app.runtime_orchestrator import run_batch_pipeline

    project = Project.from_dict(_read_json(Path(args.project_json)))
    batch = Batch.from_dict(_read_json(Path(args.batch_json)))
    summary = run_batch_pipeline(
        project=project,
        batch=batch,
        projects_root=args.projects_root or "projects",
        template_cfg_path=args.template_cfg,
        ath_executable=args.ath_exe,
        akabak_executable=args.akabak_exe,
        vacs_executable=args.vacs_exe,
        continue_on_error=args.continue_on_error,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=_json_default))
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from app.gui import launch_gui

    return int(launch_gui())


def cmd_theme_preview(args: argparse.Namespace) -> int:
    from ui.theme_preview import launch_preview

    return int(launch_preview())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="batch-software")
    parser.add_argument("--config", default="app_config.json", help="Path to app_config.json (optional).")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Run environment checks.")
    p_doctor.add_argument("--fix", action="store_true", help="Attempt non-destructive fixes (mkdir/write tests).")
    p_doctor.add_argument("--kill-zombies", action="store_true", help="Attempt to kill stuck tool processes.")
    p_doctor.add_argument("--report-path", help="Write doctor_report.json to this path.")
    p_doctor.set_defaults(func=cmd_doctor)

    p_batch = sub.add_parser("batch", help="Batch utilities.")
    sub_batch = p_batch.add_subparsers(dest="batch_cmd", required=True)

    p_job = sub_batch.add_parser("job-count", help="Compute job_count from batch.json + constraints.json.")
    p_job.add_argument("--batch-json", required=True, help="Path to batch.json")
    p_job.add_argument("--constraints-json", help="Path to constraints.json (optional)")
    p_job.set_defaults(func=cmd_batch_job_count)

    p_dataset = sub.add_parser("dataset", help="Dataset import utilities.")
    sub_dataset = p_dataset.add_subparsers(dest="dataset_cmd", required=True)

    p_build = sub_dataset.add_parser("build", help="(Re)build dataset.sqlite from Result_*.txt files.")
    p_build.add_argument("--project-id", required=True, help="Project id like P001")
    p_build.add_argument("--manifest-path", help="Override dataset_manifest.json path")
    p_build.set_defaults(func=lambda a: cmd_dataset_build_or_update(a, rebuild=True))

    p_update = sub_dataset.add_parser("update", help="Incrementally update dataset.sqlite based on manifest.")
    p_update.add_argument("--project-id", required=True, help="Project id like P001")
    p_update.add_argument("--manifest-path", help="Override dataset_manifest.json path")
    p_update.set_defaults(func=lambda a: cmd_dataset_build_or_update(a, rebuild=False))

    p_sync = sub_dataset.add_parser("sync-global", help="Replay pending project DB writes into global.sqlite.")
    p_sync.add_argument("--library-root", help="Override library root containing project folders")
    p_sync.add_argument("--max-items-per-project", type=int, default=100, help="Retry limit per project")
    p_sync.set_defaults(func=cmd_dataset_sync_global)

    p_plan = sub.add_parser("plan", help="Project/batch planning utilities.")
    sub_plan = p_plan.add_subparsers(dest="plan_cmd", required=True)

    p_materialize = sub_plan.add_parser(
        "materialize",
        help="Resolve versions from project+batch and materialize project structure and tidy metadata outputs.",
    )
    p_materialize.add_argument("--project-json", required=True, help="Path to project.json payload")
    p_materialize.add_argument("--batch-json", required=True, help="Path to batch.json payload")
    p_materialize.add_argument(
        "--projects-root",
        help="Root folder that contains project folders in format projects/<project_id>/...",
    )
    p_materialize.set_defaults(func=cmd_plan_materialize)

    p_run = sub.add_parser("run", help="Runtime execution utilities.")
    sub_run = p_run.add_subparsers(dest="run_cmd", required=True)

    p_pipeline = sub_run.add_parser(
        "pipeline",
        help="Run staged ATH->AKABAK->VACS pipeline for all resolved versions.",
    )
    p_pipeline.add_argument("--project-json", required=True, help="Path to project.json payload")
    p_pipeline.add_argument("--batch-json", required=True, help="Path to batch.json payload")
    p_pipeline.add_argument("--projects-root", help="Root folder for projects/<project_id>/...")
    p_pipeline.add_argument("--template-cfg", help="Path to ATH template CFG file")
    p_pipeline.add_argument("--ath-exe", help="ATH executable path")
    p_pipeline.add_argument("--akabak-exe", help="AKABAK executable path")
    p_pipeline.add_argument("--vacs-exe", help="VACS executable path")
    p_pipeline.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue with next stages/versions when a stage fails.",
    )
    p_pipeline.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip external tool invocations and run deterministic CFG/SQL/cleanup-guard flow only.",
    )
    p_pipeline.set_defaults(func=cmd_run_pipeline)

    p_gui = sub.add_parser("gui", help="Launch PySide6 orchestrator GUI.")
    p_gui.set_defaults(func=cmd_gui)

    p_theme = sub.add_parser("theme", help="Theme tooling.")
    sub_theme = p_theme.add_subparsers(dest="theme_cmd", required=True)

    p_theme_preview = sub_theme.add_parser("preview", help="Open visual preview window for current theme.")
    p_theme_preview.set_defaults(func=cmd_theme_preview)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
