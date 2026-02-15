"""Isolated runner test harness for ATH -> AKABAK -> VACS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.akabak_driver import AkabakDriver
from app.cfg_renderer import render_cfg_text
from app.export_specs import parse_export_specs
from app.models import Batch, ParamSelection, Project, ProjectConstraints, SweepSpec
from app.runner_test_db import RunnerTestDb
from app.runner_test_profiles import apply_runner_test_profile
from app.runner_test_workspace import RunnerTestWorkspace, resolve_runner_test_workspace
from app.runners import AthRunner, parse_ath_dimensions
from app.safe_cleanup import (
    guarded_delete_file_in_workspace,
    guarded_delete_tree_in_workspace,
)
from app.ui_automation.discover import discover_app_ui
from app.vacs_export_pipeline import VacsExportPipelineError, run_vacs_export_specs
from app.vacs_txt_parser import VacsGraph, parse_vacs_txt_file
from app.version_resolver import resolve_versions


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _version_config_hash(parameters: Dict[str, Any], unset_parameters: Sequence[str]) -> str:
    payload: Dict[str, Any] = {}
    for key in sorted(set(parameters.keys()).union(set(unset_parameters))):
        if key in parameters:
            payload[str(key)] = {"is_set": 1, "value": parameters[key]}
        else:
            payload[str(key)] = {"is_set": 0, "value": None}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object payload: {path}")
    return payload


def _load_case_payload(case_id: str, *, cases_root: str | Path = "runner_test_cases") -> Dict[str, Any]:
    path = Path(cases_root) / f"{case_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Runner test case not found: {path}")
    payload = _load_json(path)
    payload.setdefault("case_id", case_id)
    payload.setdefault("_path", str(path))
    return payload


def _as_selected_params(payload: Dict[str, Any]) -> Dict[str, ParamSelection]:
    selected: Dict[str, ParamSelection] = {}
    for key, value in dict(payload or {}).items():
        if isinstance(value, dict):
            selected[str(key)] = ParamSelection.from_dict(value, key=str(key))
            continue
        selected[str(key)] = ParamSelection(value=None if value is None else float(value))
    return selected


def _as_sweeps(payload: Dict[str, Any]) -> Dict[str, SweepSpec]:
    sweeps: Dict[str, SweepSpec] = {}
    for key, value in dict(payload or {}).items():
        if not isinstance(value, dict):
            continue
        sweeps[str(key)] = SweepSpec.from_dict(value, key=str(key))
    return sweeps


def _build_project_and_batch(case_payload: Dict[str, Any], workspace: RunnerTestWorkspace) -> Tuple[Project, Batch]:
    constraints_payload = dict(case_payload.get("constraints", {}) or {})
    batch_payload = dict(case_payload.get("batch_settings", {}) or {})
    project_id = str(case_payload.get("project_id", "P_RUNNER_TEST"))
    batch_id = str(case_payload.get("batch_id", "B_RUNNER_TEST"))
    project_name = str(case_payload.get("project_name", "Runner Test Project"))

    constraints = ProjectConstraints(
        project_id=project_id,
        runner_mode=str(constraints_payload.get("runner_mode", "AkabakImportFixedSource")),
        fixed_params=dict(constraints_payload.get("fixed_params", {}) or {}),
        limits=dict(constraints_payload.get("limits", {}) or {}),
        notes=constraints_payload.get("notes"),
    )
    project = Project(
        project_id=project_id,
        name=project_name,
        root_path=str(workspace.root),
        constraints=constraints,
    )
    batch = Batch(
        batch_id=batch_id,
        project_id=project_id,
        selected_params=_as_selected_params(dict(batch_payload.get("selected_params", {}) or {})),
        sweeps=_as_sweeps(dict(batch_payload.get("sweeps", {}) or {})),
        sweep_mode=str(batch_payload.get("sweep_mode", "single")),
        runner_mode=str(batch_payload.get("runner_mode", constraints.runner_mode)),
    )
    sim_payload = dict(batch_payload.get("sim_export_settings", {}) or {})
    if sim_payload:
        batch.sim_export_settings = batch.sim_export_settings.from_dict(sim_payload)
    return project, batch


def _collect_machine_info() -> Dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "node": platform.node(),
        "processor": platform.processor(),
    }


def _detect_git_commit() -> Optional[str]:
    try:
        value = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    commit = value.strip()
    return commit or None


def _capture_ui_observation(
    *,
    db: RunnerTestDb,
    test_run_id: str,
    app: str,
    workspace: RunnerTestWorkspace,
    notes: str,
    pid: Optional[int],
    executable: Optional[str],
) -> Optional[Dict[str, Any]]:
    try:
        payload = discover_app_ui(
            app=app,
            executable=executable,
            pid=pid,
            output_root=workspace.logs_dir / test_run_id / "ui_discover",
            startup_timeout_s=10,
            max_depth=2,
        )
    except Exception as exc:
        db.add_ui_observation(
            test_run_id=test_run_id,
            app=app,
            window_signature={"error": str(exc), "pid": pid},
            control_dump_path=None,
            notes=f"{notes}; ui_discover_failed",
        )
        return None

    db.add_ui_observation(
        test_run_id=test_run_id,
        app=app,
        window_signature={
            "pid": payload.get("pid"),
            "window_count": payload.get("window_count"),
            "windows": list(payload.get("windows", []) or [])[:10],
        },
        control_dump_path=str(payload.get("tree_path") or ""),
        notes=notes,
    )
    return payload


def _normalize_token(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _graph_kind_matches(expected_kind: str, parsed_type: str) -> bool:
    expected = _normalize_token(expected_kind)
    observed = _normalize_token(parsed_type)
    if not expected or not observed:
        return False
    aliases = {
        "spl": {"spl"},
        "impedance": {"impedance", "imp"},
        "imp": {"impedance", "imp"},
        "polar": {"polar", "polarspl", "polarpressurecomplex"},
    }
    expected_aliases = aliases.get(expected, {expected})
    observed_aliases = aliases.get(observed, {observed})
    if expected_aliases.intersection(observed_aliases):
        return True
    return expected in observed or observed in expected


def _collect_validation_metrics(
    *,
    parsed: VacsGraph,
    expected_kind: str,
    file_size_bytes: int,
    min_file_bytes: int = 32,
    min_points: int = 2,
) -> Dict[str, Any]:
    point_count = sum(len(series.points) for series in parsed.series)
    invalid_values = 0
    monotonic_failures = 0
    all_zero_series = 0
    for series in parsed.series:
        xs = [point.x_value for point in series.points]
        ys = [point.y_value for point in series.points]
        if any(xs[index] > xs[index + 1] for index in range(0, max(0, len(xs) - 1))):
            monotonic_failures += 1
        for point in series.points:
            values = [point.x_value, point.y_value]
            if point.y_imag is not None:
                values.append(point.y_imag)
            for value in values:
                if not math.isfinite(float(value)):
                    invalid_values += 1
        if ys and all(abs(float(value)) <= 1e-12 for value in ys):
            all_zero_series += 1

    graph_match = _graph_kind_matches(expected_kind, parsed.graph_type)
    status = "ok"
    message = "validation passed"
    if file_size_bytes < min_file_bytes:
        status = "failed"
        message = f"export file too small ({file_size_bytes}B < {min_file_bytes}B)"
    elif point_count < min_points:
        status = "failed"
        message = f"point count too low ({point_count} < {min_points})"
    elif monotonic_failures > 0:
        status = "failed"
        message = "x-axis is not monotonic in one or more series"
    elif invalid_values > 0:
        status = "failed"
        message = "NaN/inf detected in exported data"
    elif all_zero_series == len(parsed.series):
        status = "failed"
        message = "all series are zero-valued"
    elif not graph_match:
        status = "failed"
        message = f"graph kind mismatch: expected {expected_kind}, parsed {parsed.graph_type}"

    return {
        "status": status,
        "message": message,
        "metrics": {
            "file_size_bytes": file_size_bytes,
            "point_count": point_count,
            "series_count": len(parsed.series),
            "monotonic_failures": monotonic_failures,
            "invalid_values": invalid_values,
            "all_zero_series": all_zero_series,
            "expected_kind": expected_kind,
            "parsed_graph_type": parsed.graph_type,
            "graph_kind_match": graph_match,
        },
    }


def _rows_from_graph(
    *,
    parsed: VacsGraph,
    project_id: str,
    batch_id: str,
    run_id: str,
    version_id: str,
    source_path: Path,
    expected_kind: str,
    spec_payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    variant = str(spec_payload.get("variant") or "default")
    for series in parsed.series:
        for point_index, point in enumerate(series.points):
            rows.append(
                {
                    "project_id": project_id,
                    "batch_id": batch_id,
                    "run_id": run_id,
                    "version_id": version_id,
                    "graph_type": parsed.graph_type,
                    "graph_kind": expected_kind,
                    "variant": variant,
                    "x_name": parsed.x_name,
                    "y_name": parsed.y_name,
                    "x_axis": parsed.x_name,
                    "y_axis": parsed.y_name,
                    "x_unit": parsed.x_unit,
                    "y_unit": parsed.y_unit,
                    "series_kind": series.series_kind,
                    "angle_deg": series.angle_deg,
                    "series_label": series.label,
                    "series_meta": series.meta,
                    "x_value": point.x_value,
                    "y_value": point.y_value,
                    "y_imag": point.y_imag,
                    "point_index": point_index,
                    "source_file": str(source_path),
                    "export_meta": {
                        **dict(parsed.export_meta),
                        "expected_graph_kind": expected_kind,
                        "spec": spec_payload,
                    },
                    "meta_json": dict(parsed.export_meta),
                }
            )
    return rows


def _locate_abec_file(ath_run_dir: Path) -> Optional[Path]:
    candidates = sorted(path for path in ath_run_dir.rglob("*.abec") if path.is_file())
    if not candidates:
        return None
    candidates.sort(key=lambda item: (len(item.parts), len(item.name)))
    return candidates[0]


def _is_pid_alive(pid: int) -> bool:
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return False
    return str(pid) in (proc.stdout or "")


def _kill_pid(pid: int) -> bool:
    try:
        proc = subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return False
    return proc.returncode == 0


class HarnessProcessTracker:
    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = ledger_path
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> List[Dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        try:
            payload = json.loads(self.ledger_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _save(self, rows: List[Dict[str, Any]]) -> None:
        self.ledger_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def register(self, *, run_id: str, app: str, pid: Optional[int], started_by_harness: bool) -> None:
        if not pid or not started_by_harness:
            return
        rows = self._load()
        rows = [row for row in rows if int(row.get("pid", 0)) != int(pid)]
        rows.append(
            {
                "run_id": str(run_id),
                "app": str(app),
                "pid": int(pid),
                "started_by_harness": True,
                "recorded_at": _now_iso(),
            }
        )
        self._save(rows)

    def unregister(self, *, pid: Optional[int]) -> None:
        if not pid:
            return
        rows = self._load()
        rows = [row for row in rows if int(row.get("pid", 0)) != int(pid)]
        self._save(rows)

    def kill_stale(self) -> List[Dict[str, Any]]:
        rows = self._load()
        results: List[Dict[str, Any]] = []
        kept: List[Dict[str, Any]] = []
        for row in rows:
            pid = int(row.get("pid", 0) or 0)
            if pid <= 0:
                continue
            alive = _is_pid_alive(pid)
            killed = False
            if alive:
                killed = _kill_pid(pid)
            results.append(
                {
                    "run_id": row.get("run_id"),
                    "app": row.get("app"),
                    "pid": pid,
                    "alive": alive,
                    "killed": killed,
                }
            )
            if alive and not killed:
                kept.append(row)
        self._save(kept)
        return results


@dataclass(frozen=True)
class RunnerTestHarnessRun:
    test_run_id: str
    status: str
    case_id: str
    version_id: Optional[str]
    cfg_path: Optional[str]
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_run_id": self.test_run_id,
            "status": self.status,
            "case_id": self.case_id,
            "version_id": self.version_id,
            "cfg_path": self.cfg_path,
            "notes": self.notes,
        }


def run_runner_test_harness(
    *,
    case_id: str,
    repeats: int = 1,
    keep_exports: bool = True,
    test_profile: str = "fast",
    workspace_root: str | Path = "runner_test_workspace",
    cases_root: str | Path = "runner_test_cases",
    template_cfg_path: Optional[str | Path] = None,
    ath_executable: Optional[str | Path] = None,
    akabak_executable: Optional[str | Path] = None,
    vacs_executable: Optional[str | Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    workspace = resolve_runner_test_workspace(workspace_root)
    db = RunnerTestDb(workspace.db_path)
    tracker = HarnessProcessTracker(workspace.logs_dir / "process_ledger.json")
    case_payload = _load_case_payload(case_id, cases_root=cases_root)
    project, batch = _build_project_and_batch(case_payload, workspace)

    db.upsert_test_case(
        case_id=str(case_payload.get("case_id", case_id)),
        name=str(case_payload.get("name", case_id)),
        description=str(case_payload.get("description", "")),
        constraints_json=dict(case_payload.get("constraints", {}) or {}),
        batch_settings_json=dict(case_payload.get("batch_settings", {}) or {}),
        export_specs_json=list(batch.sim_export_settings.to_dict().get("export_specs", []) or []),
    )

    runs: List[RunnerTestHarnessRun] = []
    effective_repeats = max(1, int(repeats))
    for _ in range(effective_repeats):
        test_run_id = str(uuid.uuid4())
        run_status = "failed"
        notes = "run failed"
        version_id: Optional[str] = None
        cfg_path: Optional[Path] = None
        ath_run_dir: Optional[Path] = None
        exports_run_dir: Optional[Path] = None
        started_pids: List[int] = []

        db.create_test_run(
            test_run_id=test_run_id,
            status="running",
            git_commit=_detect_git_commit(),
            machine_info=_collect_machine_info(),
            tool_versions={
                "ath_executable": str(ath_executable) if ath_executable else None,
                "akabak_executable": str(akabak_executable) if akabak_executable else None,
                "vacs_executable": str(vacs_executable) if vacs_executable else None,
                "test_profile": test_profile,
            },
            notes=f"case={case_id}; keep_exports={str(bool(keep_exports)).lower()}",
        )

        try:
            preflight_started = _now_iso()
            stale_kill_results = tracker.kill_stale()
            missing_tools = []
            if not dry_run:
                required = {
                    "ath_executable": ath_executable,
                    "akabak_executable": akabak_executable,
                    "vacs_executable": vacs_executable,
                }
                for key, value in required.items():
                    if not value:
                        missing_tools.append(f"{key}:missing")
                        continue
                    candidate = Path(str(value)).expanduser()
                    if not candidate.exists() or not candidate.is_file():
                        missing_tools.append(f"{key}:not_found:{candidate}")
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="preflight",
                status="ok" if not missing_tools else "failed",
                started_at=preflight_started,
                finished_at=_now_iso(),
                details={
                    "dry_run": bool(dry_run),
                    "workspace": workspace.to_dict(),
                    "stale_process_cleanup": stale_kill_results,
                },
                error={"missing_tools": missing_tools} if missing_tools else {},
            )
            if missing_tools:
                notes = "preflight missing tools"
                raise RuntimeError("missing required executables for non-dry run")

            resolve_started = _now_iso()
            resolved = resolve_versions(project.constraints, batch, existing_version_ids=(), strict=False)
            fatal = [issue.to_dict() for issue in resolved.issues if issue.severity == "fatal"]
            if fatal or not resolved.versions:
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="resolve_case",
                    status="failed",
                    started_at=resolve_started,
                    finished_at=_now_iso(),
                    details={"issues": [issue.to_dict() for issue in resolved.issues]},
                    error={"fatal_issues": fatal, "version_count": len(resolved.versions)},
                )
                notes = "compatibility precheck failed"
                raise RuntimeError("case resolution failed")

            version = resolved.versions[0]
            version_id = version.version_id
            effective_params, effective_sim_settings, profile_meta = apply_runner_test_profile(
                profile_id=test_profile,
                parameters=version.parameters,
                sim_export_settings=version.sim_export_settings,
            )
            db.add_validation(
                test_run_id=test_run_id,
                validation_name="test_profile_applied",
                status="ok",
                metrics=profile_meta,
                message="runner test profile applied in harness context",
            )
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="resolve_case",
                status="ok",
                started_at=resolve_started,
                finished_at=_now_iso(),
                details={
                    "resolved_version_id": version.version_id,
                    "version_count": len(resolved.versions),
                    "issues": [issue.to_dict() for issue in resolved.issues],
                    "profile_meta": profile_meta,
                },
            )

            cfg_started = _now_iso()
            template_text = "; autogenerated cfg template\n"
            if template_cfg_path:
                template_text = Path(template_cfg_path).read_text(encoding="utf-8")
            cfg_text = render_cfg_text(
                template_text=template_text,
                parameters=effective_params,
                version_id=version.version_id,
                runner_mode=batch.runner_mode,
                omit_keys=version.unset_parameters,
            )
            cfg_path = workspace.cfg_dir / f"{test_run_id}_{version.version_id}.cfg"
            cfg_path.write_text(cfg_text, encoding="utf-8")
            cfg_sha = _sha256_file(cfg_path)
            db.upsert_run(
                run_id=test_run_id,
                project_id=project.project_id,
                batch_id=batch.batch_id,
                status="cfg_generated",
                started_at=_now_iso(),
            )
            db.upsert_version(
                version_id=version.version_id,
                project_id=project.project_id,
                batch_id=batch.batch_id,
                status="cfg_generated",
                resolved_parameters_snapshot={
                    **version.to_dict(),
                    "effective_parameters": effective_params,
                    "effective_sim_export_settings": effective_sim_settings,
                },
                version_config_hash=_version_config_hash(effective_params, version.unset_parameters),
            )
            db.upsert_run_version(
                run_id=test_run_id,
                version_id=version.version_id,
                project_id=project.project_id,
                batch_id=batch.batch_id,
                status="cfg_generated",
            )
            db.add_artifact(
                test_run_id=test_run_id,
                kind="cfg",
                path=str(cfg_path),
                sha256=cfg_sha,
                bytes_size=cfg_path.stat().st_size,
            )
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="generate_cfg",
                status="ok",
                started_at=cfg_started,
                finished_at=_now_iso(),
                details={
                    "version_id": version.version_id,
                    "cfg_path": str(cfg_path),
                    "cfg_sha256": cfg_sha,
                },
            )

            if dry_run:
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="toolchain_execution",
                    status="skipped",
                    details={"reason": "dry_run"},
                )
                run_status = "dry_run_completed"
                notes = "dry run completed"
            else:
                toolchain_started = time.perf_counter()
                ath_step_started = _now_iso()
                ath_run_dir = workspace.ath_out_dir / f"{test_run_id}_{version.version_id}"
                ath_run_dir.mkdir(parents=True, exist_ok=True)
                ath_work_cfg = ath_run_dir / "ath.cfg"
                ath_work_cfg.write_text(cfg_text, encoding="utf-8")
                ath_logs_dir = workspace.logs_dir / test_run_id / "ath"
                ath_runner = AthRunner(str(ath_executable))
                ath_result = ath_runner.run_cfg(
                    ath_work_cfg,
                    version_logs_dir=ath_logs_dir,
                    workdir=ath_run_dir,
                )
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="ath",
                    status="ok" if ath_result.ok else "failed",
                    started_at=ath_step_started,
                    finished_at=_now_iso(),
                    details={
                        "exit_code": ath_result.exit_code,
                        "timed_out": ath_result.timed_out,
                        "summary_log": ath_result.summary_log,
                        "stdout_log": ath_result.stdout_log,
                        "stderr_log": ath_result.stderr_log,
                        "work_cfg_path": str(ath_work_cfg),
                    },
                )
                if not ath_result.ok:
                    notes = "ATH stage failed"
                    raise RuntimeError("ATH stage failed")

                ath_stdout = Path(ath_result.stdout_log).read_text(encoding="utf-8", errors="replace")
                dims = parse_ath_dimensions(ath_stdout)
                if dims.raw_line:
                    db.upsert_ath_dimensions(
                        run_id=test_run_id,
                        version_id=version.version_id,
                        project_id=project.project_id,
                        batch_id=batch.batch_id,
                        length_mm=dims.horn_length_mm,
                        width_mm=dims.horn_width_mm,
                        height_mm=dims.horn_height_mm,
                        raw_line=dims.raw_line,
                        source_file=ath_result.stdout_log,
                    )

                abec_path = _locate_abec_file(ath_run_dir)
                if abec_path is None:
                    notes = "ABEC output missing after ATH"
                    raise RuntimeError(f"ABEC file not found below {ath_run_dir}")
                db.add_artifact(
                    test_run_id=test_run_id,
                    kind="abec",
                    path=str(abec_path),
                    sha256=_sha256_file(abec_path),
                    bytes_size=abec_path.stat().st_size,
                )

                akabak_step_started = _now_iso()
                akabak_driver = AkabakDriver(
                    executable=str(akabak_executable),
                    log_dir=workspace.logs_dir / test_run_id / "akabak",
                )
                akabak_pid_registered = False

                def _register_akabak_pid() -> None:
                    nonlocal akabak_pid_registered
                    if akabak_pid_registered:
                        return
                    pid_local = int(akabak_driver.session.process_id or 0)
                    started_local = bool(getattr(akabak_driver.session, "started_process", False))
                    if pid_local > 0 and started_local:
                        tracker.register(
                            run_id=test_run_id,
                            app="akabak",
                            pid=pid_local,
                            started_by_harness=True,
                        )
                        started_pids.append(pid_local)
                        akabak_pid_registered = True

                try:
                    akabak_driver.open_project(abec_path)
                    _register_akabak_pid()
                    akabak_driver.import_if_needed()
                    akabak_driver.run_solve()
                    akabak_driver.wait_for_completion(timeout_s=600)
                    windows = [item.to_dict() for item in akabak_driver.session.list_top_windows()]
                    db.add_ui_observation(
                        test_run_id=test_run_id,
                        app="akabak",
                        window_signature={
                            "window_count": len(windows),
                            "windows": windows[:10],
                        },
                        control_dump_path=None,
                        notes="post_solve_window_snapshot",
                    )
                except Exception:
                    _register_akabak_pid()
                    pid = int(akabak_driver.session.process_id or 0)
                    _capture_ui_observation(
                        db=db,
                        test_run_id=test_run_id,
                        app="akabak",
                        workspace=workspace,
                        notes="akabak_stage_exception",
                        pid=pid if pid > 0 else None,
                        executable=str(akabak_executable) if akabak_executable else None,
                    )
                    raise
                finally:
                    try:
                        akabak_driver.close()
                    except Exception:
                        pass
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="akabak",
                    status="ok",
                    started_at=akabak_step_started,
                    finished_at=_now_iso(),
                    details={"abec_path": str(abec_path)},
                )

                vacs_step_started = _now_iso()
                effective_batch_payload = batch.to_dict()
                effective_batch_payload["sim_export_settings"] = effective_sim_settings
                effective_batch = Batch.from_dict(effective_batch_payload)
                export_specs = parse_export_specs(effective_batch.sim_export_settings.to_dict())
                if not export_specs:
                    notes = "no export specs configured for VACS stage"
                    raise RuntimeError("no export specs configured")

                exports_run_dir = workspace.exports_dir / test_run_id
                exports_run_dir.mkdir(parents=True, exist_ok=True)
                try:
                    vacs_summary = run_vacs_export_specs(
                        executable=str(vacs_executable),
                        vacs_version=str(
                            effective_batch.sim_export_settings.to_dict().get("vacs_version", "default") or "default"
                        ),
                        project_id=project.project_id,
                        batch_id=batch.batch_id,
                        version_id=version.version_id,
                        abec_path=abec_path,
                        export_specs=export_specs,
                        export_dir=exports_run_dir,
                        log_dir=workspace.logs_dir / test_run_id / "vacs",
                    )
                except Exception:
                    _capture_ui_observation(
                        db=db,
                        test_run_id=test_run_id,
                        app="vacs",
                        workspace=workspace,
                        notes="vacs_stage_exception",
                        pid=None,
                        executable=str(vacs_executable) if vacs_executable else None,
                    )
                    raise
                driver_info = dict(vacs_summary.get("driver", {}) or {})
                pid = int(driver_info.get("process_id") or 0)
                started = bool(driver_info.get("started_process", False))
                if pid > 0 and started:
                    tracker.register(
                        run_id=test_run_id,
                        app="vacs",
                        pid=pid,
                        started_by_harness=True,
                    )
                    started_pids.append(pid)

                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="vacs_export",
                    status="ok" if bool(vacs_summary.get("executed")) else "failed",
                    started_at=vacs_step_started,
                    finished_at=_now_iso(),
                    details=vacs_summary,
                )
                if not bool(vacs_summary.get("executed")):
                    notes = "VACS export stage did not execute"
                    raise RuntimeError("VACS export stage failed")

                export_items = list(vacs_summary.get("exports", []) or [])
                if not export_items:
                    notes = "VACS export produced no files"
                    raise RuntimeError("no exported files")

                ingest_rows: List[Dict[str, Any]] = []
                validation_failed = False
                for export_item in export_items:
                    output_path = Path(str(export_item.get("output_path", ""))).resolve()
                    spec_payload = dict(export_item.get("spec", {}) or {})
                    expected_kind = str(spec_payload.get("graph_kind", "unknown"))
                    if not output_path.exists():
                        db.add_validation(
                            test_run_id=test_run_id,
                            validation_name=f"export_file_exists:{expected_kind}",
                            status="failed",
                            metrics={"output_path": str(output_path)},
                            message="export output file missing",
                        )
                        validation_failed = True
                        continue
                    file_size = output_path.stat().st_size
                    db.add_artifact(
                        test_run_id=test_run_id,
                        kind=f"export_txt:{expected_kind}",
                        path=str(output_path),
                        sha256=_sha256_file(output_path),
                        bytes_size=file_size,
                    )
                    try:
                        parsed = parse_vacs_txt_file(output_path, default_graph_type=expected_kind)
                    except ValueError as exc:
                        db.add_validation(
                            test_run_id=test_run_id,
                            validation_name=f"parse:{expected_kind}",
                            status="failed",
                            metrics={"output_path": str(output_path)},
                            message=str(exc),
                        )
                        validation_failed = True
                        continue

                    validation = _collect_validation_metrics(
                        parsed=parsed,
                        expected_kind=expected_kind,
                        file_size_bytes=file_size,
                    )
                    db.add_validation(
                        test_run_id=test_run_id,
                        validation_name=f"export_quality:{expected_kind}",
                        status=str(validation["status"]),
                        metrics=dict(validation["metrics"]),
                        message=str(validation["message"]),
                    )
                    if validation["status"] != "ok":
                        validation_failed = True
                    ingest_rows.extend(
                        _rows_from_graph(
                            parsed=parsed,
                            project_id=project.project_id,
                            batch_id=batch.batch_id,
                            run_id=test_run_id,
                            version_id=version.version_id,
                            source_path=output_path,
                            expected_kind=expected_kind,
                            spec_payload=spec_payload,
                        )
                    )

                ingest_step_started = _now_iso()
                ingest_result = db.write_measurements(ingest_rows)
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="ingest",
                    status="ok" if ingest_rows else "failed",
                    started_at=ingest_step_started,
                    finished_at=_now_iso(),
                    details={"rows": len(ingest_rows), "result": ingest_result},
                )
                if validation_failed or not ingest_rows:
                    notes = "validation failed after export"
                    raise RuntimeError("validation failed")

                run_status = "succeeded"
                notes = f"toolchain completed in {time.perf_counter() - toolchain_started:.2f}s"

            db.upsert_run(
                run_id=test_run_id,
                project_id=project.project_id,
                batch_id=batch.batch_id,
                status=run_status,
                finished_at=_now_iso(),
                error_summary=None if run_status in {"succeeded", "dry_run_completed"} else notes,
            )
            if version_id:
                db.upsert_run_version(
                    run_id=test_run_id,
                    version_id=version_id,
                    project_id=project.project_id,
                    batch_id=batch.batch_id,
                    status="success" if run_status == "succeeded" else run_status,
                    finished_at=_now_iso(),
                    error_summary=None if run_status in {"succeeded", "dry_run_completed"} else notes,
                )
                db.upsert_version(
                    version_id=version_id,
                    project_id=project.project_id,
                    batch_id=batch.batch_id,
                    status="success" if run_status == "succeeded" else run_status,
                    finished_at=_now_iso(),
                )
        except (VacsExportPipelineError, Exception) as exc:
            if run_status not in {"succeeded", "dry_run_completed"}:
                run_status = "failed"
            notes = str(exc)
            db.upsert_run(
                run_id=test_run_id,
                project_id=project.project_id,
                batch_id=batch.batch_id,
                status="failed",
                finished_at=_now_iso(),
                error_summary=str(exc),
            )
            if version_id:
                db.upsert_run_version(
                    run_id=test_run_id,
                    version_id=version_id,
                    project_id=project.project_id,
                    batch_id=batch.batch_id,
                    status="failed",
                    finished_at=_now_iso(),
                    error_summary=str(exc),
                )
                db.upsert_version(
                    version_id=version_id,
                    project_id=project.project_id,
                    batch_id=batch.batch_id,
                    status="failed",
                    finished_at=_now_iso(),
                )
        finally:
            cleanup_started = _now_iso()
            cleanup_rows: List[Dict[str, Any]] = []
            if cfg_path is not None:
                result = guarded_delete_file_in_workspace(
                    cfg_path.resolve(),
                    workspace_root=workspace.root,
                    expected_parent_name="cfg",
                    perform_delete=True,
                    deny_paths=(workspace.root.parent, Path.home()),
                )
                cleanup_rows.append({"kind": "cfg", "result": result.__dict__})
            if ath_run_dir is not None and ath_run_dir.exists():
                result = guarded_delete_tree_in_workspace(
                    ath_run_dir.resolve(),
                    workspace_root=workspace.root,
                    expected_parent_name="ath_out",
                    expected_dir_name=ath_run_dir.name,
                    perform_delete=True,
                    deny_paths=(workspace.root.parent, Path.home()),
                )
                cleanup_rows.append({"kind": "ath_out", "result": result.__dict__})
            if exports_run_dir is not None and exports_run_dir.exists() and not keep_exports:
                result = guarded_delete_tree_in_workspace(
                    exports_run_dir.resolve(),
                    workspace_root=workspace.root,
                    expected_parent_name="exports",
                    expected_dir_name=exports_run_dir.name,
                    perform_delete=True,
                    deny_paths=(workspace.root.parent, Path.home()),
                )
                cleanup_rows.append({"kind": "exports", "result": result.__dict__})
            process_cleanup_rows: List[Dict[str, Any]] = []
            for pid in sorted(set(started_pids)):
                alive = _is_pid_alive(pid)
                killed = False
                if alive:
                    killed = _kill_pid(pid)
                tracker.unregister(pid=pid)
                process_cleanup_rows.append(
                    {
                        "pid": int(pid),
                        "alive_before_cleanup": bool(alive),
                        "killed": bool(killed),
                    }
                )
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="safe_clean",
                status="ok",
                started_at=cleanup_started,
                finished_at=_now_iso(),
                details={
                    "cleanup_results": cleanup_rows,
                    "keep_exports": bool(keep_exports),
                    "process_cleanup": process_cleanup_rows,
                },
            )
            db.finish_test_run(test_run_id=test_run_id, status=run_status, notes=notes)
            runs.append(
                RunnerTestHarnessRun(
                    test_run_id=test_run_id,
                    status=run_status,
                    case_id=case_id,
                    version_id=version_id,
                    cfg_path=str(cfg_path) if cfg_path else None,
                    notes=notes,
                )
            )

    ok = all(run.status in {"succeeded", "dry_run_completed"} for run in runs)
    return {
        "ok": ok,
        "phase": "phase2_commit5_e2e",
        "case_id": case_id,
        "repeats": effective_repeats,
        "keep_exports": bool(keep_exports),
        "test_profile": test_profile,
        "workspace": workspace.to_dict(),
        "db_path": str(workspace.db_path),
        "dry_run": bool(dry_run),
        "runs": [run.to_dict() for run in runs],
    }


def run_runner_test_open_dialog_only(
    *,
    akabak_executable: str | Path,
    abec_path: str | Path,
    repeats: int = 1,
    workspace_root: str | Path = "runner_test_workspace",
    dry_run: bool = False,
) -> Dict[str, Any]:
    workspace = resolve_runner_test_workspace(workspace_root)
    db = RunnerTestDb(workspace.db_path)
    tracker = HarnessProcessTracker(workspace.logs_dir / "process_ledger.json")

    abec_input = Path(abec_path).expanduser().resolve()
    akabak_input = Path(akabak_executable).expanduser().resolve()
    effective_repeats = max(1, int(repeats))
    runs: List[RunnerTestHarnessRun] = []

    for _ in range(effective_repeats):
        test_run_id = str(uuid.uuid4())
        version_id = f"OPEN_DIALOG_{test_run_id[:8]}"
        run_status = "failed"
        notes = "open-dialog-only failed"
        started_pids: List[int] = []

        db.create_test_run(
            test_run_id=test_run_id,
            status="running",
            git_commit=_detect_git_commit(),
            machine_info=_collect_machine_info(),
            tool_versions={
                "akabak_executable": str(akabak_input),
                "abec_path": str(abec_input),
                "mode": "open_dialog_only",
            },
            notes=f"open_dialog_only repeats={effective_repeats}",
        )

        try:
            preflight_started = _now_iso()
            stale_kill_results = tracker.kill_stale()
            missing_inputs: List[str] = []
            if not dry_run:
                if not akabak_input.exists() or not akabak_input.is_file():
                    missing_inputs.append(f"akabak_executable:not_found:{akabak_input}")
                if not abec_input.exists() or not abec_input.is_file():
                    missing_inputs.append(f"abec_path:not_found:{abec_input}")
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="preflight",
                status="ok" if not missing_inputs else "failed",
                started_at=preflight_started,
                finished_at=_now_iso(),
                details={
                    "dry_run": bool(dry_run),
                    "workspace": workspace.to_dict(),
                    "stale_process_cleanup": stale_kill_results,
                    "akabak_executable": str(akabak_input),
                    "abec_path": str(abec_input),
                },
                error={"missing_inputs": missing_inputs} if missing_inputs else {},
            )
            if missing_inputs:
                notes = "preflight missing inputs"
                raise RuntimeError("missing inputs for open-dialog-only harness")

            db.upsert_run(
                run_id=test_run_id,
                project_id="P_RUNNER_TEST",
                batch_id="B_RUNNER_TEST",
                status="running",
            )
            db.upsert_version(
                version_id=version_id,
                project_id="P_RUNNER_TEST",
                batch_id="B_RUNNER_TEST",
                status="running",
                finished_at=None,
            )
            db.upsert_run_version(
                run_id=test_run_id,
                version_id=version_id,
                project_id="P_RUNNER_TEST",
                batch_id="B_RUNNER_TEST",
                status="running",
                finished_at=None,
            )

            db.add_artifact(
                test_run_id=test_run_id,
                kind="abec_input",
                path=str(abec_input),
                sha256=_sha256_file(abec_input) if abec_input.exists() and abec_input.is_file() else None,
                bytes_size=abec_input.stat().st_size if abec_input.exists() and abec_input.is_file() else None,
            )

            if dry_run:
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="open_dialog_only",
                    status="skipped",
                    started_at=_now_iso(),
                    finished_at=_now_iso(),
                    details={"reason": "dry_run"},
                )
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="open_dialog_close",
                    status="skipped",
                    metrics={"reason": "dry_run"},
                    message="open dialog flow skipped in dry-run mode",
                )
                run_status = "dry_run_completed"
                notes = "open-dialog-only dry run completed"
            else:
                open_started = _now_iso()
                akabak_driver = AkabakDriver(
                    executable=str(akabak_input),
                    log_dir=workspace.logs_dir / test_run_id / "akabak",
                )
                step_error: Optional[Exception] = None
                akabak_pid_registered = False

                def _register_akabak_pid() -> None:
                    nonlocal akabak_pid_registered
                    if akabak_pid_registered:
                        return
                    pid_local = int(akabak_driver.session.process_id or 0)
                    started_local = bool(getattr(akabak_driver.session, "started_process", False))
                    if pid_local > 0 and started_local:
                        tracker.register(
                            run_id=test_run_id,
                            app="akabak",
                            pid=pid_local,
                            started_by_harness=True,
                        )
                        started_pids.append(pid_local)
                        akabak_pid_registered = True

                try:
                    open_result = akabak_driver.open_project(str(abec_input))
                    _register_akabak_pid()
                    windows = [item.to_dict() for item in akabak_driver.session.list_top_windows()]
                    db.add_ui_observation(
                        test_run_id=test_run_id,
                        app="akabak",
                        window_signature={"windows": windows[:10], "window_count": len(windows)},
                        control_dump_path=None,
                        notes="open_dialog_only_post_open",
                    )
                    db.add_validation(
                        test_run_id=test_run_id,
                        validation_name="open_dialog_close",
                        status="ok",
                        metrics={
                            "driver_status": open_result.status,
                            "window_count": len(windows),
                            "abec_path": str(abec_input),
                        },
                        message="open dialog closed and project open step completed",
                    )
                    run_status = "succeeded"
                    notes = "open-dialog-only completed"
                except Exception as exc:
                    step_error = exc
                    _register_akabak_pid()
                    pid = int(akabak_driver.session.process_id or 0)
                    _capture_ui_observation(
                        db=db,
                        test_run_id=test_run_id,
                        app="akabak",
                        workspace=workspace,
                        notes="open_dialog_only_exception",
                        pid=pid if pid > 0 else None,
                        executable=str(akabak_input),
                    )
                    db.add_validation(
                        test_run_id=test_run_id,
                        validation_name="open_dialog_close",
                        status="failed",
                        metrics={"abec_path": str(abec_input)},
                        message=str(exc),
                    )
                    run_status = "failed"
                    notes = str(exc)
                finally:
                    try:
                        akabak_driver.close()
                    except Exception:
                        pass

                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="open_dialog_only",
                    status="ok" if step_error is None else "failed",
                    started_at=open_started,
                    finished_at=_now_iso(),
                    details={"abec_path": str(abec_input)},
                    error={"error": str(step_error)} if step_error is not None else {},
                )
                if step_error is not None:
                    raise RuntimeError(str(step_error))

            db.upsert_run(
                run_id=test_run_id,
                project_id="P_RUNNER_TEST",
                batch_id="B_RUNNER_TEST",
                status=run_status,
                finished_at=_now_iso(),
                error_summary=None if run_status in {"succeeded", "dry_run_completed"} else notes,
            )
            db.upsert_run_version(
                run_id=test_run_id,
                version_id=version_id,
                project_id="P_RUNNER_TEST",
                batch_id="B_RUNNER_TEST",
                status="success" if run_status == "succeeded" else run_status,
                finished_at=_now_iso(),
                error_summary=None if run_status in {"succeeded", "dry_run_completed"} else notes,
            )
            db.upsert_version(
                version_id=version_id,
                project_id="P_RUNNER_TEST",
                batch_id="B_RUNNER_TEST",
                status="success" if run_status == "succeeded" else run_status,
                finished_at=_now_iso(),
            )
        except Exception as exc:
            run_status = "failed"
            notes = str(exc)
            db.upsert_run(
                run_id=test_run_id,
                project_id="P_RUNNER_TEST",
                batch_id="B_RUNNER_TEST",
                status="failed",
                finished_at=_now_iso(),
                error_summary=str(exc),
            )
            db.upsert_run_version(
                run_id=test_run_id,
                version_id=version_id,
                project_id="P_RUNNER_TEST",
                batch_id="B_RUNNER_TEST",
                status="failed",
                finished_at=_now_iso(),
                error_summary=str(exc),
            )
            db.upsert_version(
                version_id=version_id,
                project_id="P_RUNNER_TEST",
                batch_id="B_RUNNER_TEST",
                status="failed",
                finished_at=_now_iso(),
            )
        finally:
            cleanup_started = _now_iso()
            process_cleanup_rows: List[Dict[str, Any]] = []
            for pid in sorted(set(started_pids)):
                alive = _is_pid_alive(pid)
                killed = False
                if alive:
                    killed = _kill_pid(pid)
                tracker.unregister(pid=pid)
                process_cleanup_rows.append(
                    {
                        "pid": int(pid),
                        "alive_before_cleanup": bool(alive),
                        "killed": bool(killed),
                    }
                )
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="safe_clean",
                status="ok",
                started_at=cleanup_started,
                finished_at=_now_iso(),
                details={
                    "cleanup_results": [],
                    "process_cleanup": process_cleanup_rows,
                },
            )
            db.finish_test_run(test_run_id=test_run_id, status=run_status, notes=notes)
            runs.append(
                RunnerTestHarnessRun(
                    test_run_id=test_run_id,
                    status=run_status,
                    case_id="open_dialog_only",
                    version_id=version_id,
                    cfg_path=None,
                    notes=notes,
                )
            )

    ok = all(run.status in {"succeeded", "dry_run_completed"} for run in runs)
    return {
        "ok": ok,
        "phase": "phase_open_dialog_only",
        "mode": "open_dialog_only",
        "repeats": effective_repeats,
        "workspace": workspace.to_dict(),
        "db_path": str(workspace.db_path),
        "dry_run": bool(dry_run),
        "akabak_executable": str(akabak_input),
        "abec_path": str(abec_input),
        "runs": [run.to_dict() for run in runs],
    }
