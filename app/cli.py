from __future__ import annotations

import argparse
from contextlib import closing
import dataclasses
import json
import os
from pathlib import Path
import sqlite3
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


def _is_executable_path(path: Optional[str]) -> bool:
    if not path:
        return False
    candidate = Path(path).expanduser()
    return candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK)


def _status_rows_for_versions(db_path: Path, version_ids: list[str]) -> list[tuple[str, str]]:
    if not version_ids:
        return []
    placeholders = ", ".join("?" for _ in version_ids)
    with closing(sqlite3.connect(str(db_path))) as conn:
        rows = conn.execute(
            f"SELECT version_id, status FROM versions WHERE version_id IN ({placeholders}) ORDER BY version_id",
            tuple(version_ids),
        ).fetchall()
    return [(str(row[0]), str(row[1])) for row in rows]


def _table_count_for_versions(db_path: Path, table: str, version_ids: list[str]) -> int:
    if not version_ids:
        return 0
    placeholders = ", ".join("?" for _ in version_ids)
    with closing(sqlite3.connect(str(db_path))) as conn:
        if table in {"graphs", "ath_dimensions"}:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE version_id IN ({placeholders})",
                tuple(version_ids),
            ).fetchone()
            return int(row[0]) if row else 0
        if table == "graph_points":
            row = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM graph_points gp
                JOIN graph_series gs ON gs.series_id = gp.series_id
                JOIN graphs g ON g.graph_id = gs.graph_id
                WHERE g.version_id IN ({placeholders})
                """,
                tuple(version_ids),
            ).fetchone()
            return int(row[0]) if row else 0
    return 0


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


def cmd_run_sample(args: argparse.Namespace) -> int:
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

    tool_paths = {
        "ath": service.settings.ath_exe,
        "akabak": service.settings.akabak_exe,
        "vacs": service.settings.vacs_exe,
    }
    tool_ready = {key: _is_executable_path(value) for key, value in tool_paths.items()}
    all_tools_ready = all(tool_ready.values())
    if args.real and not all_tools_ready:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "real_run_requested_but_tools_unavailable",
                    "tool_paths": tool_paths,
                    "tool_ready": tool_ready,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 2

    dry_run = bool(args.dry_run or (not args.real and not all_tools_ready))

    if args.project_id:
        project = service.repo.load_project(args.project_id)
    else:
        project = service.create_project(
            args.project_name,
            {
                "fixed_params": {"Length": 120},
                "limits": {},
                "runner_mode": "AkabakImportFixedSource",
            },
        )

    if args.batch_id:
        batch_id = args.batch_id
        service.repo.load_batch(project.project_id, batch_id)
    else:
        batch_summary = service.create_batch(
            project_id=project.project_id,
            batch_name=args.batch_name,
            selected_params={"Throat.Diameter": 30.0, "Coverage.Angle": None},
            sweeps={},
            sweep_mode="single",
            sim_export_params={},
        )
        batch_id = batch_summary.batch_id

    summary = service.run_batch(
        project.project_id,
        batch_id,
        continue_on_error=False,
        dry_run=dry_run,
    )

    project_paths = service.repo.project_paths(project.project_id, ensure=True)
    db_path = project_paths.dataset_dir / "project.sqlite"
    version_ids = list(summary.versions)
    expected_status = "dry_run_completed" if dry_run else "success"
    status_rows = _status_rows_for_versions(db_path, version_ids)
    statuses_ok = bool(status_rows) and all(status == expected_status for _, status in status_rows)

    ath_dims_count = _table_count_for_versions(db_path, "ath_dimensions", version_ids)
    graph_count = _table_count_for_versions(db_path, "graphs", version_ids)
    graph_points_count = _table_count_for_versions(db_path, "graph_points", version_ids)

    cleanup_ok = False
    if dry_run:
        cleanup_ok = bool(summary.cleanup_results) and all(
            result.get("reason") == "dry_run_no_delete" for result in summary.cleanup_results
        )
    else:
        cleanup_ok = bool(summary.cleanup_results) and all(
            bool(result.get("deleted")) and result.get("reason") == "deleted" for result in summary.cleanup_results
        )

    artifacts_ok = True
    artifact_issues: list[str] = []
    for version_id in version_ids:
        version_dir = project_paths.versions_dir / version_id
        cfg_path = version_dir / "cfg" / "input.cfg"
        logs_dir = version_dir / "logs"
        if not cfg_path.exists():
            artifacts_ok = False
            artifact_issues.append(f"{version_id}: missing cfg file")
        if not logs_dir.exists():
            artifacts_ok = False
            artifact_issues.append(f"{version_id}: missing logs directory")

    checks = [
        {"name": "version_status", "ok": statuses_ok, "detail": f"expected={expected_status}, rows={status_rows}"},
        {"name": "ath_dimensions", "ok": dry_run or ath_dims_count > 0, "detail": f"count={ath_dims_count}"},
        {"name": "graphs", "ok": dry_run or graph_count > 0, "detail": f"count={graph_count}"},
        {"name": "graph_points", "ok": dry_run or graph_points_count > 0, "detail": f"count={graph_points_count}"},
        {"name": "cleanup_guarded", "ok": cleanup_ok, "detail": json.dumps(summary.cleanup_results, ensure_ascii=False)},
        {
            "name": "artifacts_present",
            "ok": artifacts_ok,
            "detail": "; ".join(artifact_issues) if artifact_issues else "cfg/log paths present",
        },
    ]
    ok = all(bool(check["ok"]) for check in checks)
    payload = {
        "ok": ok,
        "mode": "dry-run" if dry_run else "real",
        "project_id": project.project_id,
        "batch_id": batch_id,
        "version_ids": version_ids,
        "tool_paths": tool_paths,
        "tool_ready": tool_ready,
        "checks": checks,
        "runtime_summary": dataclasses.asdict(summary),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
    return 0 if ok else 3


def cmd_gui(args: argparse.Namespace) -> int:
    from app.gui import launch_gui

    return int(launch_gui())


def cmd_theme_preview(args: argparse.Namespace) -> int:
    from ui.theme_preview import launch_preview

    return int(launch_preview())


def cmd_compat_verify(args: argparse.Namespace) -> int:
    from app.compat_verification import run_compat_verification

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

    project_id = args.project_id or "P_COMPAT"
    project_root = service.repo.project_paths(project_id, ensure=True).project_dir
    ath_exe = args.ath_exe or service.settings.ath_exe
    mode = "full" if args.all_cases else str(args.mode)
    summary = run_compat_verification(
        project_root=project_root,
        project_id=project_id,
        ath_executable=ath_exe,
        ath_base_args=args.ath_base_args or [],
        timeout_s=args.timeout_s,
        gmsh_path=args.gmsh_path,
        persist_sql=not args.no_sql,
        only_hypothesis=bool(args.hypothesis_only),
        mode=mode,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=_json_default))
    return 0 if int(summary["status_counts"].get("fail", 0)) == 0 else 3


def _inspect_ui_tool(
    *,
    tool_name: str,
    executable: Optional[str],
    output_dir: str,
    timeout_s: int,
    dry_run: bool,
) -> Dict[str, Any]:
    from app.ui_automation.inspector import inspect_tool_ui

    if not executable:
        raise ValueError(f"{tool_name} executable path is not configured.")
    return inspect_tool_ui(
        tool_name=tool_name,
        executable=executable,
        output_root=output_dir,
        startup_timeout_s=timeout_s,
        dry_run=dry_run,
    )


def cmd_ui_inspect_akabak(args: argparse.Namespace) -> int:
    settings_store = SettingsStore()
    settings = settings_store.load()
    payload = _inspect_ui_tool(
        tool_name="akabak",
        executable=args.akabak_exe or settings.akabak_exe,
        output_dir=args.output_dir,
        timeout_s=args.timeout_s,
        dry_run=args.dry_run,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
    return 0 if "error" not in payload else 3


def cmd_ui_inspect_vacs(args: argparse.Namespace) -> int:
    settings_store = SettingsStore()
    settings = settings_store.load()
    payload = _inspect_ui_tool(
        tool_name="vacs",
        executable=args.vacs_exe or settings.vacs_exe,
        output_dir=args.output_dir,
        timeout_s=args.timeout_s,
        dry_run=args.dry_run,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
    return 0 if "error" not in payload else 3


def cmd_vacs_discover_graphs(args: argparse.Namespace) -> int:
    from app.ui_automation.inspector import inspect_tool_ui
    from app.ui_automation.recipes import load_vacs_export_recipes
    from app.vacs_graph_catalog import discover_graph_catalog

    settings_store = SettingsStore()
    settings = settings_store.load()
    vacs_exe = args.vacs_exe or settings.vacs_exe
    inspect_summary = None
    if not args.dry_run and vacs_exe:
        inspect_summary = inspect_tool_ui(
            tool_name="vacs",
            executable=vacs_exe,
            output_root=args.ui_maps_output,
            startup_timeout_s=args.timeout_s,
            dry_run=False,
        )

    recipes = load_vacs_export_recipes()
    catalog = discover_graph_catalog(
        vacs_version=args.vacs_version,
        output_root=args.catalog_root,
        recipes=recipes,
        inspect_summary=inspect_summary,
    )
    payload = {
        "ok": True,
        "vacs_version": args.vacs_version,
        "catalog_path": catalog["catalog_path"],
        "entry_count": catalog["entry_count"],
        "inspect_summary": inspect_summary,
        "recipes_loaded": len(recipes),
        "dry_run": bool(args.dry_run),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
    return 0


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

    p_sample = sub.add_parser("run-sample", help="Run and verify a minimal one-version sample batch.")
    p_sample.add_argument("--project-id", help="Use existing project id. If omitted, create a sample project.")
    p_sample.add_argument("--batch-id", help="Use existing batch id. If omitted, create a sample batch.")
    p_sample.add_argument("--project-name", default="Sample Project", help="Name for auto-created sample project")
    p_sample.add_argument("--batch-name", default="Sample Batch", help="Name for auto-created sample batch")
    p_sample.add_argument("--library-root", help="Override library root in settings before run")
    mode_group = p_sample.add_mutually_exclusive_group()
    mode_group.add_argument("--real", action="store_true", help="Require real ATH/AKABAK/VACS execution")
    mode_group.add_argument("--dry-run", action="store_true", help="Force deterministic dry-run")
    p_sample.set_defaults(func=cmd_run_sample)

    p_theme = sub.add_parser("theme", help="Theme tooling.")
    sub_theme = p_theme.add_subparsers(dest="theme_cmd", required=True)

    p_theme_preview = sub_theme.add_parser("preview", help="Open visual preview window for current theme.")
    p_theme_preview.set_defaults(func=cmd_theme_preview)

    p_compat = sub.add_parser("compat", help="Compatibility verification tooling.")
    sub_compat = p_compat.add_subparsers(dest="compat_cmd", required=True)

    p_compat_verify = sub_compat.add_parser(
        "verify",
        help="Run semantic fact verification harness and persist results.",
    )
    p_compat_verify.add_argument("--project-id", help="Project id for storing verification results")
    p_compat_verify.add_argument("--library-root", help="Override library root in settings")
    p_compat_verify.add_argument("--ath-exe", help="Override ATH executable path")
    p_compat_verify.add_argument(
        "--ath-base-args",
        nargs="*",
        help="Optional ATH command prefix args (useful for harness stubs).",
    )
    p_compat_verify.add_argument("--gmsh-path", help="Optional gmsh directory prepended to PATH for ATH runs")
    p_compat_verify.add_argument("--timeout-s", type=int, default=120, help="Per-case timeout in seconds")
    p_compat_verify.add_argument(
        "--mode",
        choices=["quick", "full"],
        default="quick",
        help="Verification profile: quick (5-10 deterministic cases) or full (all cases).",
    )
    p_compat_verify.add_argument("--all-cases", action="store_true", help="Legacy alias for --mode full")
    p_compat_verify.add_argument(
        "--hypothesis-only",
        action="store_true",
        help="Skip cases that already have ath_doc evidence and run only hypothesis-backed facts.",
    )
    p_compat_verify.add_argument("--no-sql", action="store_true", help="Disable SQL persistence for results")
    p_compat_verify.set_defaults(func=cmd_compat_verify)

    p_ui = sub.add_parser("ui", help="UI automation inspection utilities.")
    sub_ui = p_ui.add_subparsers(dest="ui_cmd", required=True)

    p_ui_inspect_akabak = sub_ui.add_parser(
        "inspect-akabak",
        help="Start/connect AKABAK and dump top-level windows + UIA tree to ui_maps/",
    )
    p_ui_inspect_akabak.add_argument("--akabak-exe", help="Override AKABAK executable path")
    p_ui_inspect_akabak.add_argument("--output-dir", default="ui_maps", help="Directory for inspector artifacts")
    p_ui_inspect_akabak.add_argument("--timeout-s", type=int, default=20, help="Startup/connect timeout in seconds")
    p_ui_inspect_akabak.add_argument("--dry-run", action="store_true", help="Write planned outputs without launching tools")
    p_ui_inspect_akabak.set_defaults(func=cmd_ui_inspect_akabak)

    p_ui_inspect_vacs = sub_ui.add_parser(
        "inspect-vacs",
        help="Start/connect VACS and dump top-level windows + UIA tree to ui_maps/",
    )
    p_ui_inspect_vacs.add_argument("--vacs-exe", help="Override VACS executable path")
    p_ui_inspect_vacs.add_argument("--output-dir", default="ui_maps", help="Directory for inspector artifacts")
    p_ui_inspect_vacs.add_argument("--timeout-s", type=int, default=20, help="Startup/connect timeout in seconds")
    p_ui_inspect_vacs.add_argument("--dry-run", action="store_true", help="Write planned outputs without launching tools")
    p_ui_inspect_vacs.set_defaults(func=cmd_ui_inspect_vacs)

    p_vacs = sub.add_parser("vacs", help="VACS graph catalog and export mapping tools.")
    sub_vacs = p_vacs.add_subparsers(dest="vacs_cmd", required=True)

    p_vacs_discover = sub_vacs.add_parser(
        "discover-graphs",
        help="Best-effort discovery and graph catalog skeleton generation for a VACS version.",
    )
    p_vacs_discover.add_argument("--vacs-exe", help="Override VACS executable path")
    p_vacs_discover.add_argument("--vacs-version", default="default", help="VACS version label for catalog folder")
    p_vacs_discover.add_argument(
        "--catalog-root",
        default="ui_maps/vacs",
        help="Graph catalog root folder (<root>/<vacs_version>/graph_catalog.json)",
    )
    p_vacs_discover.add_argument(
        "--ui-maps-output",
        default="ui_maps",
        help="Output folder for optional UI inspection artifacts.",
    )
    p_vacs_discover.add_argument("--timeout-s", type=int, default=20, help="Inspector startup/connect timeout")
    p_vacs_discover.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate catalog skeleton from recipes without launching VACS.",
    )
    p_vacs_discover.set_defaults(func=cmd_vacs_discover_graphs)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
