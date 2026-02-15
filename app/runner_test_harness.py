"""Isolated runner test harness for ATH -> AKABAK -> VACS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.akabak_driver import AkabakDriver, AkabakDriverResult
from app.ath_driver_assets import repair_post_ath_le_binding
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


def _resolve_case_template_cfg(
    *,
    case_payload: Dict[str, Any],
    template_cfg_path: Optional[str | Path],
) -> Optional[Path]:
    if template_cfg_path:
        return Path(str(template_cfg_path)).expanduser().resolve()
    candidate = str(case_payload.get("template_cfg", "") or "").strip()
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    if path.is_absolute():
        return path
    case_path = Path(str(case_payload.get("_path", "") or "")).expanduser()
    if case_path.exists():
        return (case_path.parent / path).resolve()
    return path.resolve()


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


def _probe_executable(path_value: Optional[str | Path]) -> Dict[str, Any]:
    if not path_value:
        return {
            "path": None,
            "resolved_path": None,
            "exists": False,
            "is_file": False,
            "is_executable": False,
            "size_bytes": None,
            "mtime_utc": None,
        }

    candidate = Path(str(path_value)).expanduser()
    try:
        resolved = candidate.resolve()
    except Exception:
        resolved = candidate.absolute()
    exists = bool(resolved.exists())
    is_file = bool(resolved.is_file())
    stat = resolved.stat() if exists and is_file else None
    return {
        "path": str(path_value),
        "resolved_path": str(resolved),
        "exists": exists,
        "is_file": is_file,
        "is_executable": bool(os.access(resolved, os.X_OK)) if exists and is_file else False,
        "size_bytes": int(stat.st_size) if stat is not None else None,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
        if stat is not None
        else None,
    }


def _probe_directory(path_value: Optional[str | Path]) -> Dict[str, Any]:
    if not path_value:
        return {
            "path": None,
            "resolved_path": None,
            "configured": False,
            "exists": False,
            "is_dir": False,
            "is_writable": False,
        }
    candidate = Path(str(path_value)).expanduser()
    try:
        resolved = candidate.resolve()
    except Exception:
        resolved = candidate.absolute()
    exists = bool(resolved.exists())
    is_dir = bool(resolved.is_dir()) if exists else False
    return {
        "path": str(path_value),
        "resolved_path": str(resolved),
        "configured": True,
        "exists": exists,
        "is_dir": is_dir,
        "is_writable": bool(os.access(resolved, os.W_OK)) if exists and is_dir else False,
    }


def _split_meshcmd_rhs(rhs_value: str) -> Tuple[str, str]:
    rhs = str(rhs_value or "").strip()
    if not rhs:
        return "", ""
    if rhs.startswith('"') and rhs.endswith('"') and len(rhs) >= 2:
        rhs = rhs[1:-1].strip()
    if "%f" in rhs:
        exe_candidate = rhs.split("%f", 1)[0].strip().rstrip('"').rstrip("'").strip()
    else:
        exe_candidate = rhs.split(" ", 1)[0].strip().rstrip('"').rstrip("'").strip()
    return exe_candidate, rhs


def _ath_cfg_from_executable(ath_executable: Optional[str | Path]) -> Optional[Path]:
    if not ath_executable:
        return None
    candidate = Path(str(ath_executable)).expanduser()
    try:
        candidate = candidate.resolve()
    except Exception:
        candidate = candidate.absolute()
    ath_cfg = candidate.parent / "ath.cfg"
    if ath_cfg.exists() and ath_cfg.is_file():
        return ath_cfg
    return None


def _resolve_meshcmd_rhs(
    *,
    ath_executable: Optional[str | Path],
    meshcmd_override: Optional[str],
) -> Dict[str, Any]:
    if meshcmd_override:
        exe_path, normalized = _split_meshcmd_rhs(str(meshcmd_override))
        exists = bool(exe_path and Path(exe_path).exists())
        return {
            "source": "override",
            "meshcmd_rhs": normalized,
            "meshcmd_executable": exe_path,
            "meshcmd_executable_exists": exists,
            "ath_cfg_source": None,
        }

    ath_cfg = _ath_cfg_from_executable(ath_executable)
    if ath_cfg is not None:
        text = ath_cfg.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"(?im)^\s*MeshCmd\s*=\s*(.+?)\s*$", text)
        if match:
            rhs = str(match.group(1) or "").strip()
            exe_path, normalized = _split_meshcmd_rhs(rhs)
            if exe_path and Path(exe_path).exists():
                return {
                    "source": "ath_cfg",
                    "meshcmd_rhs": normalized,
                    "meshcmd_executable": exe_path,
                    "meshcmd_executable_exists": True,
                    "ath_cfg_source": str(ath_cfg),
                }

    fallback_candidates = [
        Path(r"C:\Program Files\gmsh\gmsh.exe"),
        Path(r"C:\Programme\gmsh\gmsh.exe"),
    ]
    for candidate in fallback_candidates:
        if candidate.exists() and candidate.is_file():
            return {
                "source": "fallback",
                "meshcmd_rhs": f"{candidate} %f -",
                "meshcmd_executable": str(candidate),
                "meshcmd_executable_exists": True,
                "ath_cfg_source": str(ath_cfg) if ath_cfg is not None else None,
            }

    return {
        "source": "missing",
        "meshcmd_rhs": "",
        "meshcmd_executable": None,
        "meshcmd_executable_exists": False,
        "ath_cfg_source": str(ath_cfg) if ath_cfg is not None else None,
    }


def _write_local_ath_runtime_cfg(
    *,
    ath_work_dir: Path,
    ath_executable: Optional[str | Path],
    output_root_dir: str,
    meshcmd_override: Optional[str] = None,
) -> Dict[str, Any]:
    ath_work_dir.mkdir(parents=True, exist_ok=True)
    output_root_path = Path(str(output_root_dir))
    if not output_root_path.is_absolute():
        (ath_work_dir / output_root_path).mkdir(parents=True, exist_ok=True)
    meshcmd = _resolve_meshcmd_rhs(ath_executable=ath_executable, meshcmd_override=meshcmd_override)
    lines = [f'OutputRootDir = "{output_root_dir}"']
    rhs = str(meshcmd.get("meshcmd_rhs", "") or "").strip()
    if rhs:
        lines.append(f'MeshCmd = "{rhs}"')
    runtime_cfg_path = ath_work_dir / "ath.cfg"
    runtime_cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "path": str(runtime_cfg_path),
        "output_root_dir": output_root_dir,
        "meshcmd": meshcmd,
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


def _parse_abec_mesh_requirements(abec_path: Path) -> Dict[str, Any]:
    section = ""
    mesh_refs: List[str] = []
    for raw_line in abec_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = str(raw_line).strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section != "meshfiles":
            continue
        if "=" not in line:
            continue
        _, rhs = line.split("=", 1)
        rhs_clean = rhs.strip()
        if not rhs_clean:
            continue
        mesh_ref = rhs_clean.split(",", 1)[0].strip()
        if mesh_ref:
            mesh_refs.append(mesh_ref)

    required = []
    missing = []
    base = abec_path.parent
    for ref in sorted(set(mesh_refs)):
        target = (base / ref).resolve()
        row = {"mesh_ref": ref, "path": str(target), "exists": bool(target.exists() and target.is_file())}
        required.append(row)
        if not row["exists"]:
            missing.append(row)
    return {
        "section_present": bool(mesh_refs),
        "required_mesh_files": required,
        "missing_mesh_files": missing,
    }


def _parse_abec_section_entries(abec_path: Path, section_name: str) -> List[str]:
    section = ""
    values: List[str] = []
    section_token = str(section_name or "").strip().lower()
    for raw_line in abec_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = str(raw_line).strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section != section_token or "=" not in line:
            continue
        _, rhs = line.split("=", 1)
        rhs_value = str(rhs).strip()
        if rhs_value:
            values.append(rhs_value.split(",", 1)[0].strip())
    return values


def _resolve_observation_files(abec_path: Path) -> List[Path]:
    rows = _parse_abec_section_entries(abec_path, "Observation")
    base = abec_path.parent
    files: List[Path] = []
    if rows:
        for item in rows:
            path = (base / item).resolve()
            if path.exists() and path.is_file():
                files.append(path)
    fallback = (base / "observation.txt").resolve()
    if fallback.exists() and fallback.is_file() and all(fallback != item for item in files):
        files.append(fallback)
    return files


def _read_le_script_binding_value(abec_path: Path) -> str:
    section = ""
    for raw_line in abec_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = str(raw_line).strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section != "lescript" or "=" not in line:
            continue
        lhs, rhs = line.split("=", 1)
        if str(lhs).strip().lower() != "scriptname_lescript":
            continue
        return str(rhs).strip()
    return ""


def _is_radimp_kind(token: str) -> bool:
    normalized = _normalize_token(token)
    return normalized in {"imp", "impedance", "radimp", "radiationimpedance"}


def _diagnose_radimp(
    *,
    abec_path: Path,
    export_diagnostics: Sequence[Dict[str, Any]],
    watchdog_events: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    observation_files = _resolve_observation_files(abec_path)
    observation_meta: List[Dict[str, Any]] = []
    observation_has_radimp = False
    observation_radimp_normalized = False
    for file_path in observation_files:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        has_radimp = bool(re.search(r"\bradimp\b", content, re.IGNORECASE))
        has_normalized = bool(re.search(r"radimptype\s*=\s*normalized", content, re.IGNORECASE))
        if has_radimp:
            observation_has_radimp = True
        if has_normalized:
            observation_radimp_normalized = True
        observation_meta.append(
            {
                "path": str(file_path),
                "has_radimp": has_radimp,
                "has_radimp_normalized": has_normalized,
            }
        )

    muted_seen = False
    for event in watchdog_events:
        text = f"{event.get('title', '')} {event.get('message', '')}".lower()
        if "muted" in text:
            muted_seen = True
            break

    radimp_exports: List[Dict[str, Any]] = []
    for row in export_diagnostics:
        expected_kind = str(row.get("expected_kind", "") or "")
        parsed_kind = str(row.get("parsed_graph_type", "") or "")
        if _is_radimp_kind(expected_kind) or _is_radimp_kind(parsed_kind):
            radimp_exports.append(row)

    radimp_requested = any(_is_radimp_kind(str(row.get("expected_kind", "") or "")) for row in export_diagnostics)
    all_zero = False
    wrong_kind = False
    if radimp_exports:
        all_zero = all(
            int(item.get("series_count", 0) or 0) > 0
            and int(item.get("all_zero_series", 0) or 0) >= int(item.get("series_count", 0) or 0)
            for item in radimp_exports
        )
        wrong_kind = any(not bool(item.get("graph_kind_match", True)) for item in radimp_exports)

    classification = "radimp_not_requested"
    message = "no radimp export requested in this run"
    status = "ok"
    if muted_seen:
        classification = "sources_muted_dialog_seen"
        message = "AKABAK watchdog captured a muted-sources style dialog"
        status = "failed"
    elif radimp_exports and all_zero:
        classification = "solve_succeeded_radimp_all_zero"
        message = "radimp export exists but all series are zero-valued"
        status = "failed"
    elif radimp_requested and (not observation_has_radimp or wrong_kind):
        classification = "observation_misconfigured_or_wrong_export"
        message = "radimp observation missing/ambiguous or export graph kind mismatch"
        status = "failed"
    elif radimp_requested:
        classification = "radimp_nonzero_or_not_flagged"
        message = "radimp requested; no all-zero signature detected"
        status = "ok"

    return {
        "status": status,
        "classification": classification,
        "message": message,
        "metrics": {
            "abec_path": str(abec_path),
            "observation_files": observation_meta,
            "observation_has_radimp": observation_has_radimp,
            "observation_radimp_normalized": observation_radimp_normalized,
            "radimp_requested": radimp_requested,
            "radimp_export_count": len(radimp_exports),
            "radimp_all_zero": all_zero,
            "radimp_wrong_kind": wrong_kind,
            "watchdog_event_count": len(list(watchdog_events)),
            "muted_dialog_seen": muted_seen,
        },
    }


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
    resolved_template_cfg = _resolve_case_template_cfg(case_payload=case_payload, template_cfg_path=template_cfg_path)
    project, batch = _build_project_and_batch(case_payload, workspace)
    ath_export_root_hint = str(case_payload.get("ath_export_root", "") or "").strip() or None

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
        tool_probe = {
            "ath_executable": _probe_executable(ath_executable),
            "akabak_executable": _probe_executable(akabak_executable),
            "vacs_executable": _probe_executable(vacs_executable),
        }
        export_root_probe = _probe_directory(ath_export_root_hint)

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
                "template_cfg": str(resolved_template_cfg) if resolved_template_cfg else None,
                "ath_export_root_hint": ath_export_root_hint,
                "tool_probe": tool_probe,
                "export_root_probe": export_root_probe,
            },
            notes=f"case={case_id}; keep_exports={str(bool(keep_exports)).lower()}",
        )

        try:
            preflight_started = _now_iso()
            stale_kill_results = tracker.kill_stale()
            missing_tools = []
            if not dry_run:
                for key, probe in tool_probe.items():
                    if not probe.get("path"):
                        missing_tools.append(f"{key}:missing")
                        continue
                    if not bool(probe.get("exists")) or not bool(probe.get("is_file")):
                        missing_tools.append(f"{key}:not_found:{probe.get('resolved_path')}")
                if bool(export_root_probe.get("configured")):
                    if not bool(export_root_probe.get("exists")):
                        missing_tools.append(
                            f"ath_export_root:not_found:{export_root_probe.get('resolved_path')}"
                        )
                    elif not bool(export_root_probe.get("is_dir")):
                        missing_tools.append(
                            f"ath_export_root:not_directory:{export_root_probe.get('resolved_path')}"
                        )
                    elif not bool(export_root_probe.get("is_writable")):
                        missing_tools.append(
                            f"ath_export_root:not_writable:{export_root_probe.get('resolved_path')}"
                        )
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
                    "tool_probe": tool_probe,
                    "ath_export_root_hint": ath_export_root_hint,
                    "export_root_probe": export_root_probe,
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
            if resolved_template_cfg is not None:
                template_text = resolved_template_cfg.read_text(encoding="utf-8")
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
                ath_project_cfg = ath_run_dir / "input.cfg"
                ath_project_cfg.write_text(cfg_text, encoding="utf-8")
                ath_runtime_cfg = _write_local_ath_runtime_cfg(
                    ath_work_dir=ath_run_dir,
                    ath_executable=ath_executable,
                    output_root_dir="ath",
                    meshcmd_override=str(case_payload.get("ath_mesh_cmd", "") or "").strip() or None,
                )
                ath_logs_dir = workspace.logs_dir / test_run_id / "ath"
                ath_runner = AthRunner(str(ath_executable))
                ath_result = ath_runner.run_cfg(
                    ath_project_cfg,
                    version_logs_dir=ath_logs_dir,
                    workdir=ath_run_dir,
                )
                runtime_cfg_path = Path(str(ath_runtime_cfg["path"]))
                if runtime_cfg_path.exists() and runtime_cfg_path.is_file():
                    db.add_artifact(
                        test_run_id=test_run_id,
                        kind="ath_runtime_cfg",
                        path=str(runtime_cfg_path),
                        sha256=_sha256_file(runtime_cfg_path),
                        bytes_size=runtime_cfg_path.stat().st_size,
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
                        "work_cfg_path": str(ath_project_cfg),
                        "runtime_cfg": ath_runtime_cfg,
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
                driver_sync_started = _now_iso()
                repair_diagnostics_dir = workspace.logs_dir / test_run_id / "le_repair"
                driver_sync = repair_post_ath_le_binding(
                    abec_path=abec_path,
                    ath_executable=ath_executable,
                    diagnostics_dir=repair_diagnostics_dir,
                )
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="post_ath_le_repair",
                    status="ok" if driver_sync.ok else "failed",
                    started_at=driver_sync_started,
                    finished_at=_now_iso(),
                    details=driver_sync.to_dict(),
                    error={} if driver_sync.ok else {"error": driver_sync.error or driver_sync.status},
                )
                for artifact_kind, artifact_path in (
                    ("le_driver", driver_sync.script_path),
                    ("abec_before_patch", driver_sync.before_snapshot_path),
                    ("abec_after_patch", driver_sync.after_snapshot_path),
                    ("le_repair_summary", driver_sync.diagnostics_path),
                ):
                    if not artifact_path:
                        continue
                    target_file = Path(artifact_path)
                    if not (target_file.exists() and target_file.is_file()):
                        continue
                    db.add_artifact(
                        test_run_id=test_run_id,
                        kind=artifact_kind,
                        path=str(target_file),
                        sha256=_sha256_file(target_file),
                        bytes_size=target_file.stat().st_size,
                    )
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="post_ath_le_repair_assertions",
                    status="ok" if driver_sync.ok else "failed",
                    metrics={
                        "script_exists": driver_sync.script_exists,
                        "binding_non_empty": driver_sync.binding_non_empty,
                        "binding_matches_expected": driver_sync.binding_matches_expected,
                        "binding_value": driver_sync.binding_value,
                        "expected_script_filename": driver_sync.expected_script_filename,
                        "abec_path": driver_sync.abec_path,
                        "script_path": driver_sync.script_path,
                    },
                    message="post-ATH LE repair assertions passed"
                    if driver_sync.ok
                    else f"post-ATH LE repair assertion failed: {driver_sync.error or driver_sync.status}",
                )
                if not driver_sync.ok:
                    notes = "post-ATH LE repair failed"
                    raise RuntimeError(
                        "post_ath_le_repair_failed: "
                        f"status={driver_sync.status} error={driver_sync.error or 'n/a'}"
                    )

                guard_started = _now_iso()
                mesh_guard = _parse_abec_mesh_requirements(abec_path)
                mesh_missing = list(mesh_guard.get("missing_mesh_files", []) or [])
                ath_stderr = Path(ath_result.stderr_log).read_text(encoding="utf-8", errors="replace")
                ath_text = f"{ath_stdout}\n{ath_stderr}".lower()
                mesh_missing_classification = "none"
                if mesh_missing:
                    if "nothing defined for meshcmd" in ath_text:
                        mesh_missing_classification = "mesher_missing_meshcmd"
                    elif "gmsh" in ath_text and ("not found" in ath_text or "no such file" in ath_text):
                        mesh_missing_classification = "mesher_executable_missing"
                    elif "gmsh" in ath_text and ("error" in ath_text or "failed" in ath_text):
                        mesh_missing_classification = "mesher_execution_failed"
                    else:
                        mesh_missing_classification = "ath_output_mesh_artifact_missing"
                gmsh_hint = {
                    "ath_stdout_mentions_gmsh": "gmsh" in ath_stdout.lower(),
                    "mesh_missing_classification": mesh_missing_classification,
                    "ath_stderr_log": ath_result.stderr_log,
                    "ath_stdout_log": ath_result.stdout_log,
                }
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="pre_akabak_mesh_artifacts",
                    status="ok" if not mesh_missing else "failed",
                    metrics={**mesh_guard, **gmsh_hint},
                    message=(
                        "mesh artifact precheck passed"
                        if not mesh_missing
                        else f"required mesh artifact missing before AKABAK ({mesh_missing_classification})"
                    ),
                )
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="pre_akabak_guard",
                    status="ok" if not mesh_missing else "failed",
                    started_at=guard_started,
                    finished_at=_now_iso(),
                    details={**mesh_guard, **gmsh_hint},
                    error={"missing_mesh_files": mesh_missing} if mesh_missing else {},
                )
                if mesh_missing:
                    notes = "pre-akabak guard failed: mesh artifact missing"
                    missing_str = ", ".join(str(item.get("path")) for item in mesh_missing)
                    raise RuntimeError(
                        "pre_akabak_guard_missing_mesh_artifact: "
                        + mesh_missing_classification
                        + ": "
                        + missing_str
                    )

                akabak_step_started = _now_iso()
                akabak_driver = AkabakDriver(
                    executable=str(akabak_executable),
                    log_dir=workspace.logs_dir / test_run_id / "akabak",
                )
                akabak_pid_registered = False
                akabak_watchdog_events: List[Dict[str, Any]] = []

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
                    akabak_watchdog_events = list(getattr(akabak_driver, "watchdog_events", []) or [])
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
                    akabak_watchdog_events = list(getattr(akabak_driver, "watchdog_events", []) or [])
                    _register_akabak_pid()
                    pid = int(akabak_driver.session.process_id or 0)
                    diagnostics_paths = [
                        str(getattr(akabak_driver, "last_open_dialog_diagnostics_path", "") or "").strip(),
                        str(getattr(akabak_driver, "last_import_diagnostics_path", "") or "").strip(),
                    ]
                    for diagnostics_path in [item for item in diagnostics_paths if item]:
                        diag_file = Path(diagnostics_path)
                        if diag_file.exists() and diag_file.is_file():
                            db.add_artifact(
                                test_run_id=test_run_id,
                                kind="akabak_failure_diagnostics",
                                path=str(diag_file),
                                sha256=_sha256_file(diag_file),
                                bytes_size=diag_file.stat().st_size,
                            )
                            db.add_ui_observation(
                                test_run_id=test_run_id,
                                app="akabak",
                                window_signature={"diagnostics_path": str(diag_file)},
                                control_dump_path=str(diag_file),
                                notes="akabak_failure_dump",
                            )
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
                    details={"abec_path": str(abec_path), "watchdog_events": akabak_watchdog_events},
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
                export_diagnostics: List[Dict[str, Any]] = []
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
                    export_diagnostics.append(
                        {
                            **dict(validation.get("metrics", {}) or {}),
                            "expected_kind": expected_kind,
                            "parsed_graph_type": parsed.graph_type,
                            "output_path": str(output_path),
                        }
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

                radimp_diagnosis = _diagnose_radimp(
                    abec_path=abec_path,
                    export_diagnostics=export_diagnostics,
                    watchdog_events=akabak_watchdog_events,
                )
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="radimp_diagnosis",
                    status=str(radimp_diagnosis["status"]),
                    metrics=dict(radimp_diagnosis["metrics"]),
                    message=str(radimp_diagnosis["message"]),
                )
                if radimp_diagnosis["status"] != "ok":
                    validation_failed = True

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
                    diagnostics_path = str(getattr(akabak_driver, "last_open_dialog_diagnostics_path", "") or "").strip()
                    if diagnostics_path:
                        diag_file = Path(diagnostics_path)
                        if diag_file.exists() and diag_file.is_file():
                            db.add_artifact(
                                test_run_id=test_run_id,
                                kind="akabak_open_dialog_diagnostics",
                                path=str(diag_file),
                                sha256=_sha256_file(diag_file),
                                bytes_size=diag_file.stat().st_size,
                            )
                            db.add_ui_observation(
                                test_run_id=test_run_id,
                                app="akabak",
                                window_signature={"diagnostics_path": str(diag_file)},
                                control_dump_path=str(diag_file),
                                notes="open_dialog_only_failure_dump",
                            )
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
                        metrics={"abec_path": str(abec_input), "diagnostics_path": diagnostics_path or None},
                        message=str(exc),
                    )
                    run_status = "failed"
                    notes = str(exc)
                finally:
                    try:
                        akabak_driver.close()
                    except Exception:
                        pass

                diagnostics_path = str(getattr(akabak_driver, "last_open_dialog_diagnostics_path", "") or "").strip()
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="open_dialog_only",
                    status="ok" if step_error is None else "failed",
                    started_at=open_started,
                    finished_at=_now_iso(),
                    details={"abec_path": str(abec_input), "diagnostics_path": diagnostics_path or None},
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


def run_runner_test_import_start_apply_only(
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
        version_id = f"IMPORT_APPLY_{test_run_id[:8]}"
        run_status = "failed"
        notes = "import-start-apply-only failed"
        started_pids: List[int] = []

        db.create_test_run(
            test_run_id=test_run_id,
            status="running",
            git_commit=_detect_git_commit(),
            machine_info=_collect_machine_info(),
            tool_versions={
                "akabak_executable": str(akabak_input),
                "abec_path": str(abec_input),
                "mode": "import_start_apply_only",
            },
            notes=f"import_start_apply_only repeats={effective_repeats}",
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
                raise RuntimeError("missing inputs for import-start-apply-only harness")

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
                    step_name="import_start_apply_only",
                    status="skipped",
                    started_at=_now_iso(),
                    finished_at=_now_iso(),
                    details={"reason": "dry_run"},
                )
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="import_start_apply_postcondition",
                    status="skipped",
                    metrics={"reason": "dry_run"},
                    message="import start/apply flow skipped in dry-run mode",
                )
                run_status = "dry_run_completed"
                notes = "import-start-apply-only dry run completed"
            else:
                akabak_driver = AkabakDriver(
                    executable=str(akabak_input),
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

                def _persist_driver_diagnostics(step_note: str) -> List[str]:
                    diagnostics_paths = [
                        str(getattr(akabak_driver, "last_open_dialog_diagnostics_path", "") or "").strip(),
                        str(getattr(akabak_driver, "last_import_diagnostics_path", "") or "").strip(),
                    ]
                    persisted: List[str] = []
                    for diagnostics_path in [item for item in diagnostics_paths if item]:
                        diag_file = Path(diagnostics_path)
                        if not (diag_file.exists() and diag_file.is_file()):
                            continue
                        db.add_artifact(
                            test_run_id=test_run_id,
                            kind="akabak_failure_diagnostics",
                            path=str(diag_file),
                            sha256=_sha256_file(diag_file),
                            bytes_size=diag_file.stat().st_size,
                        )
                        db.add_ui_observation(
                            test_run_id=test_run_id,
                            app="akabak",
                            window_signature={"diagnostics_path": str(diag_file)},
                            control_dump_path=str(diag_file),
                            notes=step_note,
                        )
                        persisted.append(str(diag_file))
                    return persisted

                try:
                    open_started = _now_iso()
                    open_error: Optional[Exception] = None
                    open_result: Optional[AkabakDriverResult] = None
                    try:
                        open_result = akabak_driver.open_project(str(abec_input))
                        _register_akabak_pid()
                    except Exception as exc:
                        open_error = exc
                        _register_akabak_pid()
                        pid = int(akabak_driver.session.process_id or 0)
                        persisted = _persist_driver_diagnostics("import_start_apply_open_failure_dump")
                        _capture_ui_observation(
                            db=db,
                            test_run_id=test_run_id,
                            app="akabak",
                            workspace=workspace,
                            notes="import_start_apply_open_exception",
                            pid=pid if pid > 0 else None,
                            executable=str(akabak_input),
                        )
                        db.add_validation(
                            test_run_id=test_run_id,
                            validation_name="import_start_apply_postcondition",
                            status="failed",
                            metrics={
                                "phase": "open_project",
                                "abec_path": str(abec_input),
                                "diagnostics_paths": persisted,
                            },
                            message=str(exc),
                        )
                    finally:
                        db.add_test_run_step(
                            test_run_id=test_run_id,
                            step_name="open_project",
                            status="ok" if open_error is None else "failed",
                            started_at=open_started,
                            finished_at=_now_iso(),
                            details={
                                "abec_path": str(abec_input),
                                "driver_status": open_result.status if open_result is not None else None,
                            },
                            error={"error": str(open_error)} if open_error is not None else {},
                        )
                    if open_error is not None:
                        raise RuntimeError(str(open_error))

                    import_started = _now_iso()
                    import_error: Optional[Exception] = None
                    import_result: Optional[AkabakDriverResult] = None
                    persisted_paths: List[str] = []
                    try:
                        import_result = akabak_driver.import_if_needed()
                        le_signal = akabak_driver.detect_le_script_binding_signal(expected_script_name="generic25.txt")
                        le_binding_value = _read_le_script_binding_value(abec_input)
                        windows = [item.to_dict() for item in akabak_driver.session.list_top_windows()]
                        db.add_ui_observation(
                            test_run_id=test_run_id,
                            app="akabak",
                            window_signature={"windows": windows[:10], "window_count": len(windows)},
                            control_dump_path=None,
                            notes="import_start_apply_post_import",
                        )
                        db.add_validation(
                            test_run_id=test_run_id,
                            validation_name="import_start_apply_postcondition",
                            status="ok",
                            metrics={
                                "driver_status": import_result.status,
                                "details": import_result.details,
                                "abec_path": str(abec_input),
                                "le_script_signal": le_signal,
                                "le_script_binding_value": le_binding_value,
                                "diagnostics_path": str(
                                    getattr(akabak_driver, "last_import_diagnostics_path", "") or ""
                                ).strip()
                                or None,
                            },
                            message=(
                                "import start/apply completed with postcondition signal"
                                if bool(le_signal.get("ok"))
                                else "import completed; interpreter UI tree did not expose explicit LE script text"
                            ),
                        )
                        run_status = "succeeded"
                        notes = "import-start-apply-only completed"
                    except Exception as exc:
                        import_error = exc
                        _register_akabak_pid()
                        pid = int(akabak_driver.session.process_id or 0)
                        persisted_paths = _persist_driver_diagnostics("import_start_apply_failure_dump")
                        _capture_ui_observation(
                            db=db,
                            test_run_id=test_run_id,
                            app="akabak",
                            workspace=workspace,
                            notes="import_start_apply_exception",
                            pid=pid if pid > 0 else None,
                            executable=str(akabak_input),
                        )
                        db.add_validation(
                            test_run_id=test_run_id,
                            validation_name="import_start_apply_postcondition",
                            status="failed",
                            metrics={
                                "phase": "import_start_apply",
                                "abec_path": str(abec_input),
                                "diagnostics_paths": persisted_paths,
                            },
                            message=str(exc),
                        )
                        run_status = "failed"
                        notes = str(exc)
                    finally:
                        db.add_test_run_step(
                            test_run_id=test_run_id,
                            step_name="import_start_apply",
                            status="ok" if import_error is None else "failed",
                            started_at=import_started,
                            finished_at=_now_iso(),
                            details={
                                "abec_path": str(abec_input),
                                "driver_status": import_result.status if import_result is not None else None,
                                "driver_details": import_result.details if import_result is not None else {},
                                "diagnostics_paths": persisted_paths,
                            },
                            error={"error": str(import_error)} if import_error is not None else {},
                        )
                    if import_error is not None:
                        raise RuntimeError(str(import_error))
                finally:
                    try:
                        akabak_driver.close()
                    except Exception:
                        pass

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
                    case_id="import_start_apply_only",
                    version_id=version_id,
                    cfg_path=None,
                    notes=notes,
                )
            )

    ok = all(run.status in {"succeeded", "dry_run_completed"} for run in runs)
    return {
        "ok": ok,
        "phase": "phase_import_start_apply_only",
        "mode": "import_start_apply_only",
        "repeats": effective_repeats,
        "workspace": workspace.to_dict(),
        "db_path": str(workspace.db_path),
        "dry_run": bool(dry_run),
        "akabak_executable": str(akabak_input),
        "abec_path": str(abec_input),
        "runs": [run.to_dict() for run in runs],
    }


def run_runner_test_le_repair_import_only(
    *,
    akabak_executable: str | Path,
    repeats: int = 1,
    workspace_root: str | Path = "runner_test_workspace",
    dry_run: bool = False,
    ath_executable: str | Path | None = None,
    ath_cfg_path: str | Path | None = None,
    abec_path: str | Path | None = None,
    reuse_export_dir: str | Path | None = None,
) -> Dict[str, Any]:
    workspace = resolve_runner_test_workspace(workspace_root)
    db = RunnerTestDb(workspace.db_path)
    tracker = HarnessProcessTracker(workspace.logs_dir / "process_ledger.json")

    akabak_input = Path(akabak_executable).expanduser().resolve()
    ath_input = Path(str(ath_executable)).expanduser().resolve() if ath_executable else None
    ath_cfg_input = Path(str(ath_cfg_path)).expanduser().resolve() if ath_cfg_path else None
    abec_input = Path(str(abec_path)).expanduser().resolve() if abec_path else None
    reuse_export_input = Path(str(reuse_export_dir)).expanduser().resolve() if reuse_export_dir else None

    effective_repeats = max(1, int(repeats))
    runs: List[RunnerTestHarnessRun] = []

    for _ in range(effective_repeats):
        test_run_id = str(uuid.uuid4())
        version_id = f"LE_REPAIR_{test_run_id[:8]}"
        run_status = "failed"
        notes = "le-repair-import-only failed"
        started_pids: List[int] = []
        ath_run_dir: Optional[Path] = None
        resolved_abec: Optional[Path] = None

        db.create_test_run(
            test_run_id=test_run_id,
            status="running",
            git_commit=_detect_git_commit(),
            machine_info=_collect_machine_info(),
            tool_versions={
                "akabak_executable": str(akabak_input),
                "ath_executable": str(ath_input) if ath_input else None,
                "ath_cfg_path": str(ath_cfg_input) if ath_cfg_input else None,
                "abec_path": str(abec_input) if abec_input else None,
                "reuse_export_dir": str(reuse_export_input) if reuse_export_input else None,
                "mode": "le_repair_import_only",
            },
            notes=f"le_repair_import_only repeats={effective_repeats}",
        )

        try:
            preflight_started = _now_iso()
            stale_kill_results = tracker.kill_stale()
            missing_inputs: List[str] = []
            if not dry_run:
                if not akabak_input.exists() or not akabak_input.is_file():
                    missing_inputs.append(f"akabak_executable:not_found:{akabak_input}")
                if ath_cfg_input and (not ath_cfg_input.exists() or not ath_cfg_input.is_file()):
                    missing_inputs.append(f"ath_cfg_path:not_found:{ath_cfg_input}")
                if ath_cfg_input and (ath_input is None or not ath_input.exists() or not ath_input.is_file()):
                    missing_inputs.append(f"ath_executable:not_found:{ath_input}")
                if reuse_export_input and (not reuse_export_input.exists() or not reuse_export_input.is_dir()):
                    missing_inputs.append(f"reuse_export_dir:not_found:{reuse_export_input}")
                if not ath_cfg_input and not reuse_export_input and (abec_input is None or not abec_input.exists() or not abec_input.is_file()):
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
                    "ath_executable": str(ath_input) if ath_input else None,
                    "ath_cfg_path": str(ath_cfg_input) if ath_cfg_input else None,
                    "abec_path": str(abec_input) if abec_input else None,
                    "reuse_export_dir": str(reuse_export_input) if reuse_export_input else None,
                },
                error={"missing_inputs": missing_inputs} if missing_inputs else {},
            )
            if missing_inputs:
                notes = "preflight missing inputs"
                raise RuntimeError("missing inputs for le-repair-import-only harness")

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

            if dry_run:
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="le_repair_import_only",
                    status="skipped",
                    started_at=_now_iso(),
                    finished_at=_now_iso(),
                    details={"reason": "dry_run"},
                )
                run_status = "dry_run_completed"
                notes = "le-repair-import-only dry run completed"
            else:
                if ath_cfg_input is not None:
                    ath_step_started = _now_iso()
                    ath_run_dir = workspace.ath_out_dir / f"{test_run_id}_{version_id}"
                    ath_run_dir.mkdir(parents=True, exist_ok=True)
                    ath_project_cfg = ath_run_dir / "input.cfg"
                    ath_project_cfg.write_text(
                        ath_cfg_input.read_text(encoding="utf-8", errors="replace"),
                        encoding="utf-8",
                    )
                    ath_runtime_cfg = _write_local_ath_runtime_cfg(
                        ath_work_dir=ath_run_dir,
                        ath_executable=ath_input,
                        output_root_dir="ath",
                    )
                    ath_logs_dir = workspace.logs_dir / test_run_id / "ath"
                    ath_runner = AthRunner(str(ath_input))
                    ath_result = ath_runner.run_cfg(
                        ath_project_cfg,
                        version_logs_dir=ath_logs_dir,
                        workdir=ath_run_dir,
                    )
                    runtime_cfg_path = Path(str(ath_runtime_cfg["path"]))
                    if runtime_cfg_path.exists() and runtime_cfg_path.is_file():
                        db.add_artifact(
                            test_run_id=test_run_id,
                            kind="ath_runtime_cfg",
                            path=str(runtime_cfg_path),
                            sha256=_sha256_file(runtime_cfg_path),
                            bytes_size=runtime_cfg_path.stat().st_size,
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
                            "work_cfg_path": str(ath_project_cfg),
                            "runtime_cfg": ath_runtime_cfg,
                        },
                    )
                    if not ath_result.ok:
                        raise RuntimeError("ATH stage failed in le-repair-import-only")
                    resolved_abec = _locate_abec_file(ath_run_dir)
                elif reuse_export_input is not None:
                    resolved_abec = _locate_abec_file(reuse_export_input)
                else:
                    resolved_abec = abec_input

                if resolved_abec is None or not resolved_abec.exists() or not resolved_abec.is_file():
                    raise RuntimeError("unable to resolve ABEC file for le-repair-import-only")
                db.add_artifact(
                    test_run_id=test_run_id,
                    kind="abec_input",
                    path=str(resolved_abec),
                    sha256=_sha256_file(resolved_abec),
                    bytes_size=resolved_abec.stat().st_size,
                )

                repair_started = _now_iso()
                repair_result = repair_post_ath_le_binding(
                    abec_path=resolved_abec,
                    ath_executable=ath_input,
                    diagnostics_dir=workspace.logs_dir / test_run_id / "le_repair",
                )
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="post_ath_le_repair",
                    status="ok" if repair_result.ok else "failed",
                    started_at=repair_started,
                    finished_at=_now_iso(),
                    details=repair_result.to_dict(),
                    error={} if repair_result.ok else {"error": repair_result.error or repair_result.status},
                )
                for artifact_kind, artifact_path in (
                    ("le_driver", repair_result.script_path),
                    ("abec_before_patch", repair_result.before_snapshot_path),
                    ("abec_after_patch", repair_result.after_snapshot_path),
                    ("le_repair_summary", repair_result.diagnostics_path),
                ):
                    if not artifact_path:
                        continue
                    path = Path(artifact_path)
                    if not (path.exists() and path.is_file()):
                        continue
                    db.add_artifact(
                        test_run_id=test_run_id,
                        kind=artifact_kind,
                        path=str(path),
                        sha256=_sha256_file(path),
                        bytes_size=path.stat().st_size,
                    )
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="post_ath_le_repair_assertions",
                    status="ok" if repair_result.ok else "failed",
                    metrics={
                        "script_exists": repair_result.script_exists,
                        "binding_non_empty": repair_result.binding_non_empty,
                        "binding_matches_expected": repair_result.binding_matches_expected,
                        "binding_value": repair_result.binding_value,
                        "expected_script_filename": repair_result.expected_script_filename,
                        "abec_path": repair_result.abec_path,
                    },
                    message="post-ATH LE repair assertions passed"
                    if repair_result.ok
                    else f"post-ATH LE repair failed: {repair_result.error or repair_result.status}",
                )
                if not repair_result.ok:
                    raise RuntimeError(f"post_ath_le_repair_failed:{repair_result.error or repair_result.status}")

                import_started = _now_iso()
                akabak_driver = AkabakDriver(
                    executable=str(akabak_input),
                    log_dir=workspace.logs_dir / test_run_id / "akabak",
                )
                import_error: Optional[Exception] = None
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
                    akabak_driver.open_project(str(resolved_abec))
                    _register_akabak_pid()
                    import_result = akabak_driver.import_if_needed()
                    le_signal = akabak_driver.detect_le_script_binding_signal(expected_script_name="generic25.txt")
                    le_binding_value = _read_le_script_binding_value(resolved_abec)
                    db.add_validation(
                        test_run_id=test_run_id,
                        validation_name="import_start_apply_postcondition",
                        status="ok",
                        metrics={
                            "abec_path": str(resolved_abec),
                            "driver_status": import_result.status,
                            "driver_details": import_result.details,
                            "le_script_signal": le_signal,
                            "le_script_binding_value": le_binding_value,
                        },
                        message=(
                            "LE signal detected in interpreter UI tree after Start Importing -> Apply"
                            if bool(le_signal.get("ok"))
                            else "import completed and LE binding set in Project.abec; interpreter UI tree did not expose script text"
                        ),
                    )
                    run_status = "succeeded"
                    notes = "le-repair-import-only completed"
                except Exception as exc:
                    import_error = exc
                    _register_akabak_pid()
                    pid = int(akabak_driver.session.process_id or 0)
                    _capture_ui_observation(
                        db=db,
                        test_run_id=test_run_id,
                        app="akabak",
                        workspace=workspace,
                        notes="le_repair_import_only_exception",
                        pid=pid if pid > 0 else None,
                        executable=str(akabak_input),
                    )
                    notes = str(exc)
                    run_status = "failed"
                finally:
                    db.add_test_run_step(
                        test_run_id=test_run_id,
                        step_name="import_start_apply",
                        status="ok" if import_error is None else "failed",
                        started_at=import_started,
                        finished_at=_now_iso(),
                        details={"abec_path": str(resolved_abec)},
                        error={"error": str(import_error)} if import_error is not None else {},
                    )
                    try:
                        akabak_driver.close()
                    except Exception:
                        pass
                if import_error is not None:
                    raise RuntimeError(str(import_error))

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
            cleanup_rows: List[Dict[str, Any]] = []
            if ath_run_dir is not None:
                cleanup = guarded_delete_tree_in_workspace(
                    ath_run_dir,
                    workspace_root=workspace.root,
                    expected_dir_name=ath_run_dir.name,
                    perform_delete=True,
                )
                cleanup_rows.append(cleanup.to_dict())
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
                details={"cleanup_results": cleanup_rows, "process_cleanup": process_cleanup_rows},
            )
            db.finish_test_run(test_run_id=test_run_id, status=run_status, notes=notes)
            runs.append(
                RunnerTestHarnessRun(
                    test_run_id=test_run_id,
                    status=run_status,
                    case_id="le_repair_import_only",
                    version_id=version_id,
                    cfg_path=str(ath_cfg_input) if ath_cfg_input else None,
                    notes=notes,
                )
            )

    ok = all(run.status in {"succeeded", "dry_run_completed"} for run in runs)
    return {
        "ok": ok,
        "phase": "phase_le_repair_import_only",
        "mode": "le_repair_import_only",
        "repeats": effective_repeats,
        "workspace": workspace.to_dict(),
        "db_path": str(workspace.db_path),
        "dry_run": bool(dry_run),
        "akabak_executable": str(akabak_input),
        "ath_executable": str(ath_input) if ath_input else None,
        "ath_cfg_path": str(ath_cfg_input) if ath_cfg_input else None,
        "abec_path": str(abec_input) if abec_input else None,
        "reuse_export_dir": str(reuse_export_input) if reuse_export_input else None,
        "runs": [run.to_dict() for run in runs],
    }
