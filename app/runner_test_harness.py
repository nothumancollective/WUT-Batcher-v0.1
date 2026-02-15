"""Isolated runner test harness (phase-2 skeleton, dry-run only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.cfg_renderer import render_cfg_text
from app.models import Batch, ParamSelection, Project, ProjectConstraints, SweepSpec
from app.runner_test_db import RunnerTestDb
from app.runner_test_workspace import RunnerTestWorkspace, resolve_runner_test_workspace
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


def _version_config_hash(parameters: Dict[str, Any], unset_parameters: List[str]) -> str:
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


def _build_project_and_batch(case_payload: Dict[str, Any]) -> Tuple[Project, Batch]:
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
        root_path=str(Path.cwd() / "runner_test_workspace"),
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
    repeats: int,
    keep_exports: bool,
    test_profile: str,
    workspace_root: str | Path = "runner_test_workspace",
    cases_root: str | Path = "runner_test_cases",
    template_cfg_path: Optional[str | Path] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    workspace = resolve_runner_test_workspace(workspace_root)
    db = RunnerTestDb(workspace.db_path)
    case_payload = _load_case_payload(case_id, cases_root=cases_root)
    project, batch = _build_project_and_batch(case_payload)

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
        db.create_test_run(
            test_run_id=test_run_id,
            status="running",
            git_commit=_detect_git_commit(),
            machine_info=_collect_machine_info(),
            tool_versions={},
            notes=f"case={case_id}; profile={test_profile}; keep_exports={str(bool(keep_exports)).lower()}",
        )
        db.add_test_run_step(
            test_run_id=test_run_id,
            step_name="preflight",
            status="ok",
            details={"dry_run": bool(dry_run), "workspace": workspace.to_dict()},
        )

        resolved = resolve_versions(project.constraints, batch, existing_version_ids=(), strict=False)
        fatal = [issue.to_dict() for issue in resolved.issues if issue.severity == "fatal"]
        if fatal:
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="generate_cfg",
                status="failed",
                details={"issues": [issue.to_dict() for issue in resolved.issues]},
                error={"fatal_issues": fatal},
            )
            db.finish_test_run(
                test_run_id=test_run_id,
                status="failed",
                notes="compatibility precheck failed before tool launch",
            )
            runs.append(
                RunnerTestHarnessRun(
                    test_run_id=test_run_id,
                    status="failed",
                    case_id=case_id,
                    version_id=None,
                    cfg_path=None,
                    notes="compatibility precheck failed",
                )
            )
            continue

        if not resolved.versions:
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="generate_cfg",
                status="failed",
                error={"message": "No versions resolved for test case."},
            )
            db.finish_test_run(
                test_run_id=test_run_id,
                status="failed",
                notes="no resolved versions",
            )
            runs.append(
                RunnerTestHarnessRun(
                    test_run_id=test_run_id,
                    status="failed",
                    case_id=case_id,
                    version_id=None,
                    cfg_path=None,
                    notes="no resolved versions",
                )
            )
            continue

        version = resolved.versions[0]
        template_text = "; autogenerated cfg template\n"
        if template_cfg_path:
            template_text = Path(template_cfg_path).read_text(encoding="utf-8")
        cfg_text = render_cfg_text(
            template_text=template_text,
            parameters=version.parameters,
            version_id=version.version_id,
            runner_mode=version.sim_export_settings.get("runner_mode", batch.runner_mode) or batch.runner_mode,
            omit_keys=version.unset_parameters,
        )
        cfg_path = workspace.cfg_dir / f"{test_run_id}_{version.version_id}.cfg"
        cfg_path.write_text(cfg_text, encoding="utf-8")
        cfg_sha = _sha256_file(cfg_path)

        db.upsert_run(
            run_id=test_run_id,
            project_id=project.project_id,
            batch_id=batch.batch_id,
            status="dry_run_completed" if dry_run else "pending_execution",
            started_at=_now_iso(),
        )
        db.upsert_version(
            version_id=version.version_id,
            project_id=project.project_id,
            batch_id=batch.batch_id,
            status="cfg_generated",
            resolved_parameters_snapshot=version.to_dict(),
            version_config_hash=_version_config_hash(version.parameters, version.unset_parameters),
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
            details={
                "version_id": version.version_id,
                "cfg_path": str(cfg_path),
                "cfg_sha256": cfg_sha,
                "test_profile": test_profile,
            },
        )
        db.add_test_run_step(
            test_run_id=test_run_id,
            step_name="toolchain_execution",
            status="skipped",
            details={"reason": "phase_2_skeleton_dry_run_only"},
        )
        db.finish_test_run(
            test_run_id=test_run_id,
            status="dry_run_completed" if dry_run else "pending_execution",
            notes="stopped before launching ATH/AKABAK/VACS in skeleton mode",
        )
        runs.append(
            RunnerTestHarnessRun(
                test_run_id=test_run_id,
                status="dry_run_completed" if dry_run else "pending_execution",
                case_id=case_id,
                version_id=version.version_id,
                cfg_path=str(cfg_path),
                notes="skeleton run completed",
            )
        )

    return {
        "ok": all(run.status in {"dry_run_completed", "pending_execution"} for run in runs),
        "phase": "phase2_commit4_skeleton",
        "case_id": case_id,
        "repeats": effective_repeats,
        "keep_exports": bool(keep_exports),
        "test_profile": test_profile,
        "workspace": workspace.to_dict(),
        "db_path": str(workspace.db_path),
        "dry_run": bool(dry_run),
        "runs": [run.to_dict() for run in runs],
    }
