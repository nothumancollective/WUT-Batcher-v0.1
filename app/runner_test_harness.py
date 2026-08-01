"""Isolated runner test harness for ATH -> AKABAK -> VACS."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import sqlite3
import subprocess
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.akabak_driver import AkabakDriver, AkabakDriverResult
from app.ath_driver_assets import (
    LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING_RESISTOR,
    LE_PATCH_PROFILE_MUT_ELECTRICAL,
    LE_PATCH_PROFILE_MUT_MOTOR,
    repair_post_ath_le_binding,
)
from app.cfg_renderer import render_cfg_text
from app.export_specs import ExportSpec, parse_export_specs
from app.models import Batch, ParamSelection, Project, ProjectConstraints, SweepSpec
from app.runner_test_db import RunnerTestDb
from app.runner_test_profiles import apply_runner_test_profile, get_runner_test_profile
from app.runner_test_workspace import RunnerTestWorkspace, resolve_runner_test_workspace
from app.runners import AthRunner, parse_ath_dimensions
from app.safe_cleanup import (
    guarded_delete_file_in_workspace,
    guarded_delete_tree_in_workspace,
)
from app.le_driver_registry import load_le_driver_registry
from app.runtime_orchestrator import (
    _apply_sim_export_settings_to_cfg,
    _serialize_native_tool_pipeline,
    _to_windows_short_path,
)
from app.ui_automation.waits import wait_until
from app.ui_automation.discover import discover_app_ui
from app.ui_automation.session import UiaSession
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


@dataclass(frozen=True)
class ObservationPatchResult:
    status: str
    profile: str
    observation_files: List[str]
    changed_files: int
    radimp_entries_seen: int
    diagnostics_path: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in {"not_requested", "already_conformant", "patched"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "profile": self.profile,
            "observation_files": list(self.observation_files),
            "changed_files": int(self.changed_files),
            "radimp_entries_seen": int(self.radimp_entries_seen),
            "diagnostics_path": self.diagnostics_path,
            "error": self.error,
        }


@dataclass(frozen=True)
class ObservationDrivingPatchResult:
    status: str
    profile: str
    observation_files: List[str]
    changed_files: int
    driving_sections_seen: int
    diagnostics_path: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in {"not_requested", "already_conformant", "patched"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "profile": self.profile,
            "observation_files": list(self.observation_files),
            "changed_files": int(self.changed_files),
            "driving_sections_seen": int(self.driving_sections_seen),
            "diagnostics_path": self.diagnostics_path,
            "error": self.error,
        }


@dataclass(frozen=True)
class CfgLeProfilePatchResult:
    status: str
    profile: str
    cfg_path: str
    changed: bool
    target_le_voltage: Optional[float]
    detected_le_voltage_before: Optional[float]
    detected_le_voltage_after: Optional[float]
    diagnostics_path: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in {"not_requested", "already_conformant", "patched"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "profile": self.profile,
            "cfg_path": self.cfg_path,
            "changed": bool(self.changed),
            "target_le_voltage": self.target_le_voltage,
            "detected_le_voltage_before": self.detected_le_voltage_before,
            "detected_le_voltage_after": self.detected_le_voltage_after,
            "diagnostics_path": self.diagnostics_path,
            "error": self.error,
        }


def _copy_artifact_snapshot(
    *,
    source_path: str | Path,
    snapshot_root: str | Path,
    snapshot_name: str,
) -> Optional[Path]:
    source = Path(str(source_path)).expanduser()
    if not source.exists() or not source.is_file():
        return None
    root = Path(str(snapshot_root)).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    target = root / snapshot_name
    target.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return target


def _write_directory_snapshot(
    *,
    root_path: str | Path,
    output_path: str | Path,
    max_entries: int = 1000,
) -> Optional[Path]:
    root = Path(str(root_path)).expanduser()
    if not root.exists() or not root.is_dir():
        return None
    out = Path(str(output_path)).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    entries: List[Dict[str, Any]] = []
    count = 0
    for path in sorted(root.rglob("*")):
        if count >= max_entries:
            break
        try:
            rel = str(path.relative_to(root)).replace("\\", "/")
        except Exception:
            rel = str(path)
        item = {
            "relative_path": rel,
            "is_dir": bool(path.is_dir()),
            "is_file": bool(path.is_file()),
        }
        if path.is_file():
            try:
                item["bytes"] = int(path.stat().st_size)
            except Exception:
                item["bytes"] = None
        entries.append(item)
        count += 1
    payload = {
        "root": str(root),
        "entry_count": len(entries),
        "truncated": bool(count >= max_entries),
        "entries": entries,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def _normalize_radimp_observation_profile(profile: Optional[str]) -> str:
    value = str(profile or "").strip().lower()
    if not value:
        return "default"
    aliases = {
        "default": "default",
        "normalized": "default",
        "force_absolute": "force_absolute",
        "absolute": "force_absolute",
        "drop_radimptype": "drop_radimptype",
        "remove_radimptype": "drop_radimptype",
        "le_electrical_impedance": "le_electrical_impedance",
        "drvimp": "le_electrical_impedance",
    }
    return aliases.get(value, value)


def _normalize_driving_observation_profile(profile: Optional[str]) -> str:
    value = str(profile or "").strip().lower()
    if not value:
        return "default"
    aliases = {
        "default": "default",
        "accel_1": "default",
        "accel_2p83": "accel_2p83",
        "accel_10": "accel_10",
        "accel_0p1": "accel_0p1",
        "velocity_1": "velocity_1",
        "displacement_1": "displacement_1",
    }
    return aliases.get(value, value)


def _normalize_cfg_le_profile(profile: Optional[str]) -> str:
    value = str(profile or "").strip().lower()
    if not value:
        return "default"
    aliases = {
        "default": "default",
        "le_voltage_1": "default",
        "le_voltage_1p0": "default",
        "le_voltage_2p83": "le_voltage_2p83",
        "2p83": "le_voltage_2p83",
        "le_voltage_10": "le_voltage_10",
        "10": "le_voltage_10",
        "le_voltage_0p1": "le_voltage_0p1",
        "0p1": "le_voltage_0p1",
    }
    return aliases.get(value, value)


def _version_config_hash(parameters: Dict[str, Any], unset_parameters: Sequence[str]) -> str:
    payload: Dict[str, Any] = {}
    for key in sorted(set(parameters.keys()).union(set(unset_parameters))):
        if key in parameters:
            payload[str(key)] = {"is_set": 1, "value": parameters[key]}
        else:
            payload[str(key)] = {"is_set": 0, "value": None}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_polar_export_specs_for_harness() -> List[ExportSpec]:
    base_options = {
        "map_angle_range": [0, 90, 19],
        "distance_m": 2.0,
    }
    return [
        ExportSpec(
            id="default_polar_spl_h",
            tool="vacs",
            graph_kind="polar",
            variant="main",
            format="txt",
            options={**base_options, "polar_name": "SPL_H", "offset": 145, "inclination": 0},
            output_name_template="{version_id}_{graph_kind}_{export_id}.{format}",
        ),
        ExportSpec(
            id="default_polar_spl_v",
            tool="vacs",
            graph_kind="polar",
            variant="main",
            format="txt",
            options={**base_options, "polar_name": "SPL_V", "offset_from_length_mm": 40, "inclination": 90},
            output_name_template="{version_id}_{graph_kind}_{export_id}.{format}",
        ),
        ExportSpec(
            id="default_polar_spl_d",
            tool="vacs",
            graph_kind="polar",
            variant="main",
            format="txt",
            options={**base_options, "polar_name": "SPL_D", "offset_from_length_mm": 40, "inclination": 45},
            output_name_template="{version_id}_{graph_kind}_{export_id}.{format}",
        ),
    ]


def _resolve_export_specs_for_harness(sim_export_payload: Dict[str, Any]) -> List[ExportSpec]:
    specs = parse_export_specs(sim_export_payload)
    if specs:
        return specs
    if bool(sim_export_payload.get("auto_default_polar_exports", False)):
        return _default_polar_export_specs_for_harness()
    return []


def _enforce_free_standing_for_tests(sim_export_settings: Dict[str, Any]) -> Tuple[Dict[str, Any], str, bool]:
    merged = dict(sim_export_settings or {})
    profile_sim_mode = str(merged.get("simulation_mode", "free_standing") or "free_standing").strip().lower()
    if profile_sim_mode not in {"free_standing", "infinite_baffle"}:
        profile_sim_mode = "free_standing"
    forced = bool(profile_sim_mode != "free_standing")
    merged["simulation_mode"] = "free_standing"
    return merged, profile_sim_mode, forced


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
    # MeshCmd values are frequently quoted as one ATH string while the
    # executable itself may also contain spaces. Split at the executable
    # suffix instead of the first whitespace so Program Files paths survive.
    match = re.match(r"(?is)^[\"']?(?P<exe>.+?\.exe)[\"']?(?P<args>\s+.*)?$", rhs)
    if match:
        exe_candidate = str(match.group("exe") or "").strip().strip('"').strip("'")
        args = str(match.group("args") or "").strip().rstrip('"').rstrip("'").strip()
        normalized = " ".join(item for item in (exe_candidate, args) if item)
        return exe_candidate, normalized
    if rhs.startswith('"') and rhs.endswith('"') and len(rhs) >= 2:
        rhs = rhs[1:-1].strip()
    exe_candidate = rhs.split(" ", 1)[0].strip().rstrip('"').rstrip("'").strip()
    return exe_candidate, rhs


def _normalize_meshcmd_rhs(
    *,
    meshcmd_executable: str,
    meshcmd_rhs: str,
) -> Dict[str, Any]:
    executable = str(meshcmd_executable or "").strip()
    rhs = str(meshcmd_rhs or "").strip()
    normalized = rhs
    changed = False
    reason = ""
    try:
        name = Path(executable).name.lower()
    except Exception:
        name = ""
    runtime_executable = _to_windows_short_path(executable)
    if runtime_executable and runtime_executable != executable and normalized:
        normalized = normalized.replace(executable, runtime_executable, 1)
        changed = True
        reason = "short_path_for_whitespace"
    # ATH often forwards the current .geo via "%f". Bare gmsh.exe opens GUI and can stall runs.
    if name == "gmsh.exe" and normalized and "%f" not in normalized.lower():
        normalized = f"{runtime_executable or executable} %f -".strip()
        changed = True
        reason = "+".join(item for item in (reason, "append_placeholder_for_gmsh") if item)
    return {
        "meshcmd_rhs": normalized,
        "normalized": changed,
        "reason": reason,
    }


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
        normalized_info = _normalize_meshcmd_rhs(meshcmd_executable=exe_path, meshcmd_rhs=normalized)
        normalized_rhs = str(normalized_info.get("meshcmd_rhs", normalized) or "").strip()
        exists = bool(exe_path and Path(exe_path).exists())
        return {
            "source": "override",
            "meshcmd_rhs": normalized_rhs,
            "meshcmd_executable": exe_path,
            "meshcmd_executable_exists": exists,
            "meshcmd_rhs_normalized": bool(normalized_info.get("normalized")),
            "meshcmd_rhs_normalization_reason": str(normalized_info.get("reason", "") or ""),
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
                normalized_info = _normalize_meshcmd_rhs(meshcmd_executable=exe_path, meshcmd_rhs=normalized)
                normalized_rhs = str(normalized_info.get("meshcmd_rhs", normalized) or "").strip()
                return {
                    "source": "ath_cfg",
                    "meshcmd_rhs": normalized_rhs,
                    "meshcmd_executable": exe_path,
                    "meshcmd_executable_exists": True,
                    "meshcmd_rhs_normalized": bool(normalized_info.get("normalized")),
                    "meshcmd_rhs_normalization_reason": str(normalized_info.get("reason", "") or ""),
                    "ath_cfg_source": str(ath_cfg),
                }

    if ath_executable:
        sibling = Path(str(ath_executable)).expanduser().parent / "gmsh.exe"
        if sibling.exists() and sibling.is_file():
            rhs = f"{sibling} %f -"
            normalized_info = _normalize_meshcmd_rhs(meshcmd_executable=str(sibling), meshcmd_rhs=rhs)
            return {
                "source": "ath_sibling",
                "meshcmd_rhs": str(normalized_info.get("meshcmd_rhs", rhs) or "").strip(),
                "meshcmd_executable": str(sibling),
                "meshcmd_executable_exists": True,
                "meshcmd_rhs_normalized": bool(normalized_info.get("normalized")),
                "meshcmd_rhs_normalization_reason": str(normalized_info.get("reason", "") or ""),
                "ath_cfg_source": str(ath_cfg) if ath_cfg is not None else None,
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
                "meshcmd_rhs_normalized": False,
                "meshcmd_rhs_normalization_reason": "",
                "ath_cfg_source": str(ath_cfg) if ath_cfg is not None else None,
            }

    return {
        "source": "missing",
        "meshcmd_rhs": "",
        "meshcmd_executable": None,
        "meshcmd_executable_exists": False,
        "meshcmd_rhs_normalized": False,
        "meshcmd_rhs_normalization_reason": "",
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
    if os.name == "nt" and int(pid or 0) > 0:
        try:
            session = UiaSession(
                executable=str(executable or ""),
                app_name=str(app),
                startup_timeout_s=1,
                allow_fallback=False,
            )
            session.process_id = int(pid or 0)
            session.backend = "pywinauto-uia"
            window_rows = [row.to_dict() for row in session.list_top_windows()]
            payload = {
                "app": str(app),
                "pid": int(pid or 0),
                "backend": "win32_hwnd",
                "window_count": len(window_rows),
                "windows": window_rows,
                "tree_path": None,
            }
            db.add_ui_observation(
                test_run_id=test_run_id,
                app=app,
                window_signature={
                    "pid": payload["pid"],
                    "window_count": payload["window_count"],
                    "windows": window_rows[:10],
                    "snapshot_backend": "win32_hwnd",
                },
                control_dump_path=None,
                notes=f"{notes}; native_hwnd_snapshot",
            )
            return payload
        except Exception as exc:
            db.add_ui_observation(
                test_run_id=test_run_id,
                app=app,
                window_signature={"error": str(exc), "pid": pid, "snapshot_backend": "win32_hwnd"},
                control_dump_path=None,
                notes=f"{notes}; native_snapshot_failed",
            )
            return None

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
        "spl": {"spl", "soundpressure", "soundpressurelevel", "sound"},
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
    export_metadata = dict(parsed.export_meta.get("metadata", {}) or {})
    data_level_type = str(export_metadata.get("Data_LevelType", "") or "")
    data_legend = str(export_metadata.get("Data_Legend", "") or "")
    data_radimp_type = str(export_metadata.get("RadImpType", "") or "")
    radimp_normalized_hint = "normalized" in data_legend.lower() or data_radimp_type.lower() == "normalized"
    all_zero_allowed = bool(_is_radimp_kind(expected_kind) and radimp_normalized_hint and data_level_type.lower().startswith("impedance"))

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
        if all_zero_allowed:
            status = "ok"
            message = "all-zero accepted for normalized radimp baseline"
        else:
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
            "all_zero_allowed": all_zero_allowed,
            "radimp_normalized_hint": radimp_normalized_hint,
            "expected_kind": expected_kind,
            "parsed_graph_type": parsed.graph_type,
            "graph_kind_match": graph_match,
            "data_level_type": data_level_type,
            "data_legend": data_legend,
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


def _resolve_solving_files(abec_path: Path) -> List[Path]:
    section = ""
    solving_refs: List[str] = []
    for raw_line in abec_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = str(raw_line).strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section != "project" or "=" not in line:
            continue
        lhs, rhs = line.split("=", 1)
        if str(lhs).strip().lower() != "scriptname_solving":
            continue
        ref = str(rhs).strip()
        if ref:
            solving_refs.append(ref.split(",", 1)[0].strip())
    files: List[Path] = []
    base = abec_path.parent
    for item in solving_refs:
        path = (base / item).resolve()
        if path.exists() and path.is_file():
            files.append(path)
    fallback = (base / "solving.txt").resolve()
    if fallback.exists() and fallback.is_file() and all(fallback != item for item in files):
        files.append(fallback)
    return files


def _resolve_le_script_files(abec_path: Path) -> List[Path]:
    rows = _parse_abec_section_entries(abec_path, "lescript")
    base = abec_path.parent
    files: List[Path] = []
    for item in rows:
        path = (base / item).resolve()
        if path.exists() and path.is_file():
            files.append(path)
    fallback = (base / "generic25.txt").resolve()
    if fallback.exists() and fallback.is_file() and all(fallback != item for item in files):
        files.append(fallback)
    return files


def _extract_drvgroups_from_text(content: str) -> List[str]:
    groups = re.findall(r"\bDrvGroup\s*=\s*([0-9]+)\b", str(content), flags=re.IGNORECASE)
    ordered: List[str] = []
    seen: set[str] = set()
    for item in groups:
        token = str(item).strip()
        if token and token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def _extract_le_driver_drvgroups(content: str) -> List[str]:
    groups: List[str] = []
    for raw_line in str(content).splitlines():
        if not re.match(r"^\s*Driver\s+", raw_line, flags=re.IGNORECASE):
            continue
        match = re.search(r"\bDrvGroup\s*=\s*([0-9]+)\b", raw_line, flags=re.IGNORECASE)
        if match and match.group(1) not in groups:
            groups.append(match.group(1))
    return groups


def _extract_radimp_groups_from_observation(content: str) -> Dict[str, Any]:
    in_radimp = False
    pairs: List[List[str]] = []
    flat_groups: List[str] = []
    for raw_line in str(content).splitlines():
        line = str(raw_line).strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if re.match(r"^\s*Radiation_Impedance\s*$", line, flags=re.IGNORECASE):
            in_radimp = True
            continue
        if in_radimp and re.match(r"^[A-Za-z_]+\s*$", line):
            in_radimp = False
        if not in_radimp:
            continue
        match = re.match(r"^\s*\d+\s+([0-9]+)\s+([0-9]+)\b", line)
        if not match:
            continue
        g1 = str(match.group(1))
        g2 = str(match.group(2))
        pairs.append([g1, g2])
        flat_groups.append(g1)
        flat_groups.append(g2)
    unique_groups: List[str] = []
    seen: set[str] = set()
    for item in flat_groups:
        if item not in seen:
            seen.add(item)
            unique_groups.append(item)
    return {"pairs": pairs, "groups": unique_groups}


def _assess_pre_akabak_le_driving_contract(
    *,
    abec_path: Path,
    expected_drvgroup: Optional[str],
) -> Dict[str, Any]:
    solving_files = _resolve_solving_files(abec_path)
    observation_files = _resolve_observation_files(abec_path)
    le_script_files = _resolve_le_script_files(abec_path)
    solving_groups: List[str] = []
    le_driver_groups: List[str] = []
    le_has_def_driving = False
    le_has_resistor = False
    observation_driving_groups: List[str] = []
    observation_radimp_pairs: List[List[str]] = []
    observation_radimp_groups: List[str] = []
    observation_has_radimp_section = False

    for path in solving_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in _extract_drvgroups_from_text(text):
            if token not in solving_groups:
                solving_groups.append(token)

    for path in le_script_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in _extract_le_driver_drvgroups(text):
            if token not in le_driver_groups:
                le_driver_groups.append(token)
        le_has_def_driving = le_has_def_driving or bool(
            re.search(r"^\s*Def_Driving\b", text, flags=re.IGNORECASE | re.MULTILINE)
        )
        le_has_resistor = le_has_resistor or bool(
            re.search(r"^\s*Resistor\s+", text, flags=re.IGNORECASE | re.MULTILINE)
        )

    for path in observation_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*Radiation_Impedance\s*$", text, flags=re.IGNORECASE | re.MULTILINE):
            observation_has_radimp_section = True
        for token in _extract_drvgroups_from_text(text):
            if token not in observation_driving_groups:
                observation_driving_groups.append(token)
        radimp_info = _extract_radimp_groups_from_observation(text)
        for pair in list(radimp_info.get("pairs", []) or []):
            if pair not in observation_radimp_pairs:
                observation_radimp_pairs.append(pair)
        for token in list(radimp_info.get("groups", []) or []):
            if token not in observation_radimp_groups:
                observation_radimp_groups.append(token)

    expected = str(expected_drvgroup or "").strip()
    violations: List[str] = []
    if not solving_files:
        violations.append("solving_file_missing")
    if not observation_files:
        violations.append("observation_file_missing")
    if not le_script_files:
        violations.append("le_script_file_missing")
    if not observation_has_radimp_section:
        violations.append("radimp_section_missing")
    if observation_has_radimp_section and not observation_radimp_pairs:
        violations.append("radimp_entries_missing")
    if expected:
        if expected not in solving_groups:
            violations.append("expected_drvgroup_missing_in_solving")
        if expected not in le_driver_groups:
            violations.append("expected_drvgroup_missing_on_le_driver")
        if expected not in observation_driving_groups:
            violations.append("expected_drvgroup_missing_in_observation_driving")
        if expected not in observation_radimp_groups:
            violations.append("expected_drvgroup_missing_in_radimp_entries")

    return {
        "ok": not violations,
        "violations": violations,
        "expected_drvgroup": expected or None,
        "solving_files": [str(path) for path in solving_files],
        "observation_files": [str(path) for path in observation_files],
        "le_script_files": [str(path) for path in le_script_files],
        "solving_drvgroups": solving_groups,
        "le_driver_drvgroups": le_driver_groups,
        "le_has_def_driving": le_has_def_driving,
        "le_has_resistor": le_has_resistor,
        "observation_driving_drvgroups": observation_driving_groups,
        "observation_radimp_pairs": observation_radimp_pairs,
        "observation_radimp_groups": observation_radimp_groups,
        "observation_has_radimp_section": observation_has_radimp_section,
    }


def _patch_cfg_le_profile(
    *,
    cfg_path: Path,
    profile: Optional[str],
    diagnostics_dir: Optional[Path] = None,
) -> CfgLeProfilePatchResult:
    canonical = _normalize_cfg_le_profile(profile)
    profile_map: Dict[str, Optional[float]] = {
        "default": None,
        "le_voltage_2p83": 2.83,
        "le_voltage_10": 10.0,
        "le_voltage_0p1": 0.1,
    }
    if canonical not in profile_map:
        return CfgLeProfilePatchResult(
            status="invalid_profile",
            profile=canonical,
            cfg_path=str(cfg_path),
            changed=False,
            target_le_voltage=None,
            detected_le_voltage_before=None,
            detected_le_voltage_after=None,
            error=f"unsupported cfg LE profile: {canonical}",
        )

    if not cfg_path.exists() or not cfg_path.is_file():
        return CfgLeProfilePatchResult(
            status="cfg_missing",
            profile=canonical,
            cfg_path=str(cfg_path),
            changed=False,
            target_le_voltage=profile_map.get(canonical),
            detected_le_voltage_before=None,
            detected_le_voltage_after=None,
            error="cfg file not found",
        )

    text_before = cfg_path.read_text(encoding="utf-8", errors="replace")
    line_pattern = re.compile(r"(?im)^(\s*LE\.Voltage\s*=\s*)([^;\r\n]+)(\s*(?:[;#].*)?)$")
    before_match = line_pattern.search(text_before)
    detected_before: Optional[float] = None
    if before_match:
        try:
            detected_before = float(str(before_match.group(2)).strip())
        except Exception:
            detected_before = None

    target = profile_map[canonical]
    if canonical == "default":
        return CfgLeProfilePatchResult(
            status="not_requested",
            profile=canonical,
            cfg_path=str(cfg_path),
            changed=False,
            target_le_voltage=target,
            detected_le_voltage_before=detected_before,
            detected_le_voltage_after=detected_before,
        )

    new_value = f"{float(target):.6g}"
    if before_match:
        text_after = line_pattern.sub(lambda m: f"{m.group(1)}{new_value}{m.group(3)}", text_before, count=1)
    else:
        suffix = "" if text_before.endswith("\n") else "\n"
        text_after = f"{text_before}{suffix}LE.Voltage = {new_value}\n"

    changed = text_after != text_before
    if changed:
        cfg_path.write_text(text_after, encoding="utf-8")
    detected_after: Optional[float] = None
    after_match = line_pattern.search(text_after)
    if after_match:
        try:
            detected_after = float(str(after_match.group(2)).strip())
        except Exception:
            detected_after = None

    diagnostics_path = None
    if diagnostics_dir is not None:
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        diagnostics_file = diagnostics_dir / "cfg_le_patch_summary.json"
        diagnostics_file.write_text(
            json.dumps(
                {
                    "profile": canonical,
                    "cfg_path": str(cfg_path),
                    "target_le_voltage": target,
                    "detected_le_voltage_before": detected_before,
                    "detected_le_voltage_after": detected_after,
                    "changed": bool(changed),
                    "sha256_before": hashlib.sha256(text_before.encode("utf-8", errors="replace")).hexdigest(),
                    "sha256_after": hashlib.sha256(text_after.encode("utf-8", errors="replace")).hexdigest(),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        diagnostics_path = str(diagnostics_file)

    return CfgLeProfilePatchResult(
        status="patched" if changed else "already_conformant",
        profile=canonical,
        cfg_path=str(cfg_path),
        changed=bool(changed),
        target_le_voltage=target,
        detected_le_voltage_before=detected_before,
        detected_le_voltage_after=detected_after,
        diagnostics_path=diagnostics_path,
    )


def _patch_observation_radimp_profile(
    *,
    abec_path: Path,
    profile: Optional[str],
    diagnostics_dir: Optional[Path] = None,
) -> ObservationPatchResult:
    canonical = _normalize_radimp_observation_profile(profile)
    observation_files = _resolve_observation_files(abec_path)
    if canonical == "default":
        return ObservationPatchResult(
            status="not_requested",
            profile=canonical,
            observation_files=[str(path) for path in observation_files],
            changed_files=0,
            radimp_entries_seen=0,
        )
    if canonical not in {"force_absolute", "drop_radimptype", "le_electrical_impedance"}:
        return ObservationPatchResult(
            status="invalid_profile",
            profile=canonical,
            observation_files=[str(path) for path in observation_files],
            changed_files=0,
            radimp_entries_seen=0,
            error=f"unsupported radimp observation profile: {canonical}",
        )
    if not observation_files:
        return ObservationPatchResult(
            status="observation_missing",
            profile=canonical,
            observation_files=[],
            changed_files=0,
            radimp_entries_seen=0,
            error="observation files not found",
        )

    changed_files = 0
    radimp_entries = 0
    diagnostics_payload: Dict[str, Any] = {"profile": canonical, "files": []}

    section_line = re.compile(r"^\s*Radiation_Impedance\s*$", flags=re.IGNORECASE)
    radimp_type_line = re.compile(r"(\bRadImpType\s*=\s*)([^;\r\n]+)", flags=re.IGNORECASE)

    try:
        for obs_file in observation_files:
            original_text = obs_file.read_text(encoding="utf-8", errors="replace")
            if canonical == "le_electrical_impedance":
                already_present = bool(
                    re.search(
                        r"(?im)^\s*LE_Spectrum\s*$(?s:.*?)\bAnalysisType\s*=\s*Impedance\b",
                        original_text,
                    )
                )
                new_text = original_text
                if not already_present:
                    separator = "" if original_text.endswith("\n\n") else ("\n" if original_text.endswith("\n") else "\n\n")
                    new_text = (
                        original_text
                        + separator
                        + "LE_Spectrum\n"
                        + "  System='S1'; AnalysisType=Impedance\n"
                        + "  Range_min=0; Range_max=50\n"
                        + "  GraphHeader='DrvImp'; BodeType=Ampl_Phase; ID=2002\n"
                    )
                    obs_file.write_text(new_text, encoding="utf-8")
                    changed_files += 1
                diagnostics_payload["files"].append(
                    {
                        "path": str(obs_file),
                        "changed": not already_present,
                        "radimp_entries_seen": 0,
                        "le_electrical_impedance_present": True,
                        "sha256_before": hashlib.sha256(original_text.encode("utf-8", errors="replace")).hexdigest(),
                        "sha256_after": hashlib.sha256(new_text.encode("utf-8", errors="replace")).hexdigest(),
                    }
                )
                continue
            lines = original_text.splitlines()
            in_radimp_block = False
            block_has_type = False
            local_radimp_entries = 0
            updated_lines: List[str] = []
            file_changed = False

            for index, line in enumerate(lines):
                stripped = str(line).strip()
                if section_line.match(line):
                    if in_radimp_block and canonical == "force_absolute" and not block_has_type:
                        updated_lines.append("  RadImpType=Absolute")
                        file_changed = True
                    in_radimp_block = True
                    block_has_type = False
                    updated_lines.append(line)
                    continue
                if in_radimp_block and stripped and not stripped.startswith("//") and not stripped.startswith(";"):
                    if re.match(r"^[A-Za-z_]+\s*$", stripped):
                        if canonical == "force_absolute" and not block_has_type:
                            updated_lines.append("  RadImpType=Absolute")
                            file_changed = True
                        in_radimp_block = False
                        block_has_type = False
                if in_radimp_block and radimp_type_line.search(line):
                    local_radimp_entries += 1
                    if canonical == "force_absolute":
                        replaced = radimp_type_line.sub(r"\1Absolute", line, count=1)
                        if replaced != line:
                            file_changed = True
                        block_has_type = True
                        updated_lines.append(replaced)
                        continue
                    if canonical == "drop_radimptype":
                        replaced = radimp_type_line.sub("", line, count=1)
                        replaced = re.sub(r";\s*;", ";", replaced)
                        replaced = replaced.rstrip()
                        if replaced != line:
                            file_changed = True
                        if replaced.strip():
                            updated_lines.append(replaced)
                        continue
                updated_lines.append(line)
                if in_radimp_block and "RadImpType" in line:
                    block_has_type = True

                if index == len(lines) - 1 and in_radimp_block and canonical == "force_absolute" and not block_has_type:
                    updated_lines.append("  RadImpType=Absolute")
                    file_changed = True

            radimp_entries += local_radimp_entries
            new_text = "\n".join(updated_lines)
            if original_text.endswith("\n"):
                new_text += "\n"
            if file_changed:
                obs_file.write_text(new_text, encoding="utf-8")
                changed_files += 1

            diagnostics_payload["files"].append(
                {
                    "path": str(obs_file),
                    "changed": bool(file_changed),
                    "radimp_entries_seen": int(local_radimp_entries),
                    "sha256_before": hashlib.sha256(original_text.encode("utf-8", errors="replace")).hexdigest(),
                    "sha256_after": hashlib.sha256(new_text.encode("utf-8", errors="replace")).hexdigest(),
                }
            )

        status = "patched" if changed_files > 0 else "already_conformant"
        diagnostics_path = None
        if diagnostics_dir is not None:
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            diagnostics_path = diagnostics_dir / "observation_patch_summary.json"
            diagnostics_path.write_text(json.dumps(diagnostics_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return ObservationPatchResult(
            status=status,
            profile=canonical,
            observation_files=[str(path) for path in observation_files],
            changed_files=changed_files,
            radimp_entries_seen=radimp_entries,
            diagnostics_path=str(diagnostics_path) if diagnostics_path else None,
        )
    except Exception as exc:
        return ObservationPatchResult(
            status="patch_failed",
            profile=canonical,
            observation_files=[str(path) for path in observation_files],
            changed_files=changed_files,
            radimp_entries_seen=radimp_entries,
            diagnostics_path=None,
            error=str(exc),
        )


def _patch_observation_driving_profile(
    *,
    abec_path: Path,
    profile: Optional[str],
    diagnostics_dir: Optional[Path] = None,
) -> ObservationDrivingPatchResult:
    canonical = _normalize_driving_observation_profile(profile)
    observation_files = _resolve_observation_files(abec_path)
    if canonical == "default":
        return ObservationDrivingPatchResult(
            status="not_requested",
            profile=canonical,
            observation_files=[str(path) for path in observation_files],
            changed_files=0,
            driving_sections_seen=0,
        )
    profile_map = {
        "accel_2p83": ("Acceleration", "2.83"),
        "accel_10": ("Acceleration", "10.0"),
        "accel_0p1": ("Acceleration", "0.1"),
        "velocity_1": ("Velocity", "1.0"),
        "displacement_1": ("Displacement", "1.0"),
    }
    if canonical not in profile_map:
        return ObservationDrivingPatchResult(
            status="invalid_profile",
            profile=canonical,
            observation_files=[str(path) for path in observation_files],
            changed_files=0,
            driving_sections_seen=0,
            error=f"unsupported driving observation profile: {canonical}",
        )
    if not observation_files:
        return ObservationDrivingPatchResult(
            status="observation_missing",
            profile=canonical,
            observation_files=[],
            changed_files=0,
            driving_sections_seen=0,
            error="observation files not found",
        )

    target_drv_type, target_value = profile_map[canonical]
    changed_files = 0
    driving_sections = 0
    diagnostics_payload: Dict[str, Any] = {"profile": canonical, "files": []}
    driving_header = re.compile(
        r"(\bDrvType\s*=\s*)([^;]+)(\s*;\s*Value\s*=\s*)([^;\r\n]+)",
        flags=re.IGNORECASE,
    )

    try:
        for obs_file in observation_files:
            original_text = obs_file.read_text(encoding="utf-8", errors="replace")
            lines = original_text.splitlines()
            in_driving = False
            file_changed = False
            sections_seen_local = 0
            updated_lines: List[str] = []
            for line in lines:
                stripped = str(line).strip()
                if re.match(r"^\s*Driving_Values\s*$", line, flags=re.IGNORECASE):
                    in_driving = True
                    sections_seen_local += 1
                    updated_lines.append(line)
                    continue
                if in_driving and stripped and re.match(r"^[A-Za-z_]+\s*$", stripped):
                    in_driving = False
                if in_driving and "DrvType" in line and "Value" in line:
                    replaced = driving_header.sub(
                        lambda match: f"{match.group(1)}{target_drv_type}{match.group(3)}{target_value}",
                        line,
                        count=1,
                    )
                    if replaced != line:
                        file_changed = True
                    updated_lines.append(replaced)
                    continue
                updated_lines.append(line)
            driving_sections += sections_seen_local
            new_text = "\n".join(updated_lines)
            if original_text.endswith("\n"):
                new_text += "\n"
            if file_changed:
                obs_file.write_text(new_text, encoding="utf-8")
                changed_files += 1
            diagnostics_payload["files"].append(
                {
                    "path": str(obs_file),
                    "changed": bool(file_changed),
                    "driving_sections_seen": int(sections_seen_local),
                    "target_drv_type": target_drv_type,
                    "target_value": target_value,
                    "sha256_before": hashlib.sha256(original_text.encode("utf-8", errors="replace")).hexdigest(),
                    "sha256_after": hashlib.sha256(new_text.encode("utf-8", errors="replace")).hexdigest(),
                }
            )

        status = "patched" if changed_files > 0 else "already_conformant"
        diagnostics_path = None
        if diagnostics_dir is not None:
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            diagnostics_path = diagnostics_dir / "driving_patch_summary.json"
            diagnostics_path.write_text(json.dumps(diagnostics_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return ObservationDrivingPatchResult(
            status=status,
            profile=canonical,
            observation_files=[str(path) for path in observation_files],
            changed_files=changed_files,
            driving_sections_seen=driving_sections,
            diagnostics_path=str(diagnostics_path) if diagnostics_path else None,
        )
    except Exception as exc:
        return ObservationDrivingPatchResult(
            status="patch_failed",
            profile=canonical,
            observation_files=[str(path) for path in observation_files],
            changed_files=changed_files,
            driving_sections_seen=driving_sections,
            diagnostics_path=None,
            error=str(exc),
        )


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
    solve_completed: bool = True,
    export_stage_executed: bool = True,
    expected_export_kinds: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    observation_files = _resolve_observation_files(abec_path)
    observation_meta: List[Dict[str, Any]] = []
    observation_has_radimp = False
    observation_radimp_normalized = False
    for file_path in observation_files:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        has_radimp = bool(re.search(r"(radimp|radiation[_\s-]*impedance)", content, re.IGNORECASE))
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

    requested_kinds = [str(row.get("expected_kind", "") or "") for row in export_diagnostics]
    if expected_export_kinds:
        requested_kinds.extend(str(item or "") for item in expected_export_kinds)
    radimp_requested = any(_is_radimp_kind(item) for item in requested_kinds)
    all_zero = False
    wrong_kind = False
    if radimp_exports:
        all_zero = all(
            int(item.get("series_count", 0) or 0) > 0
            and int(item.get("all_zero_series", 0) or 0) >= int(item.get("series_count", 0) or 0)
            for item in radimp_exports
        )
        wrong_kind = any(not bool(item.get("graph_kind_match", True)) for item in radimp_exports)
    all_zero_allowed = bool(radimp_exports) and all(bool(item.get("all_zero_allowed", False)) for item in radimp_exports)

    classification = "radimp_not_requested"
    message = "no radimp export requested in this run"
    status = "ok"
    if muted_seen:
        classification = "sources_muted_dialog_seen"
        message = "AKABAK watchdog captured a muted-sources style dialog"
        status = "failed"
    elif not solve_completed:
        classification = "solve_not_completed_or_no_results"
        message = "solve completion signal missing before RadImp evaluation"
        status = "failed"
    elif radimp_requested and not export_stage_executed:
        classification = "solve_not_completed_or_no_results"
        message = "export stage was not executed after solve"
        status = "failed"
    elif radimp_requested and not radimp_exports:
        classification = "wrong_graph_exported"
        message = "requested RadImp export but no RadImp graph was exported"
        status = "failed"
    elif wrong_kind:
        classification = "wrong_graph_exported"
        message = "exported graph metadata does not match requested RadImp graph kind"
        status = "failed"
    elif radimp_exports and all_zero and all_zero_allowed and observation_radimp_normalized:
        classification = "radimp_normalized_zero_baseline"
        message = "radimp export is normalized and zero-valued baseline (accepted)"
        status = "ok"
    elif radimp_exports and all_zero:
        classification = "radimp_all_zero_unclassified"
        message = "radimp export exists but all series are zero-valued"
        status = "failed"
    elif radimp_requested and not observation_has_radimp:
        classification = "wrong_graph_exported"
        message = "radimp requested but observation file has no Radiation_Impedance section"
        status = "failed"
    elif radimp_requested and radimp_exports:
        classification = "radimp_nonzero"
        message = "radimp requested; non-zero RadImp signature detected"
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
            "radimp_all_zero_allowed": all_zero_allowed,
            "radimp_wrong_kind": wrong_kind,
            "solve_completed": bool(solve_completed),
            "export_stage_executed": bool(export_stage_executed),
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


def _list_processes_by_image(image_name: str) -> List[Dict[str, Any]]:
    image = str(image_name or "").strip()
    if not image:
        return []
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return []
    lines = [line.strip() for line in str(proc.stdout or "").splitlines() if line.strip()]
    rows: List[Dict[str, Any]] = []
    for row in csv.reader(lines):
        if len(row) < 2:
            continue
        image_cell = str(row[0] or "").strip()
        pid_cell = str(row[1] or "").strip()
        if not image_cell or image_cell.lower() != image.lower():
            continue
        if not pid_cell.isdigit():
            continue
        rows.append(
            {
                "image": image_cell,
                "pid": int(pid_cell),
            }
        )
    return rows


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

    def owned_pids(self) -> List[int]:
        rows = self._load()
        pids = {
            int(row.get("pid", 0))
            for row in rows
            if int(row.get("pid", 0) or 0) > 0 and bool(row.get("started_by_harness", False))
        }
        return sorted(pids)

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


def _detect_unmanaged_tool_processes(tracker: HarnessProcessTracker) -> Dict[str, Any]:
    owned_pids = set(int(pid) for pid in tracker.owned_pids())
    scan_specs: List[Tuple[str, str]] = [
        ("akabak", "AKABAK.exe"),
        ("vacs", "VACSVIEWER_32.exe"),
        ("vacs", "VACSVIEWER.exe"),
    ]
    running_by_pid: Dict[int, Dict[str, Any]] = {}
    for app, image_name in scan_specs:
        for row in _list_processes_by_image(image_name):
            pid = int(row.get("pid", 0) or 0)
            if pid <= 0:
                continue
            if pid in running_by_pid:
                continue
            running_by_pid[pid] = {
                "app": app,
                "image": str(row.get("image", image_name) or image_name),
                "pid": pid,
                "owned_by_harness": pid in owned_pids,
            }
    running_processes = sorted(running_by_pid.values(), key=lambda item: (str(item.get("app", "")), int(item.get("pid", 0))))
    unmanaged_processes = [row for row in running_processes if not bool(row.get("owned_by_harness"))]
    return {
        "owned_pids": sorted(owned_pids),
        "running_processes": running_processes,
        "unmanaged_processes": unmanaged_processes,
        "blocked": bool(unmanaged_processes),
    }


def _list_running_vacs_pids() -> List[int]:
    rows: List[Dict[str, Any]] = []
    rows.extend(_list_processes_by_image("VACSVIEWER_32.exe"))
    rows.extend(_list_processes_by_image("VACSVIEWER.exe"))
    pids = {int(row.get("pid", 0)) for row in rows if int(row.get("pid", 0) or 0) > 0}
    return sorted(pids)


def _wait_for_unmanaged_processes_to_clear(
    tracker: HarnessProcessTracker,
    *,
    timeout_s: float = 8.0,
) -> Dict[str, Any]:
    latest_scan = _detect_unmanaged_tool_processes(tracker)
    if not bool(latest_scan.get("blocked")):
        return latest_scan

    def _predicate() -> Tuple[bool, Dict[str, Any]]:
        nonlocal latest_scan
        latest_scan = _detect_unmanaged_tool_processes(tracker)
        return (not bool(latest_scan.get("blocked")), latest_scan)

    try:
        wait_until(
            predicate=_predicate,
            timeout_s=float(timeout_s),
            initial_interval_s=0.2,
            max_interval_s=1.0,
            backoff_factor=1.5,
        )
    except TimeoutError:
        pass
    return latest_scan


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


class HarnessManualInterferenceError(RuntimeError):
    """Raised when unmanaged manual tool interaction blocks deterministic harness execution."""


@_serialize_native_tool_pipeline
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
    le_repair_profile: Optional[str] = None,
    cfg_le_profile: Optional[str] = None,
    radimp_observation_profile: Optional[str] = None,
    driving_observation_profile: Optional[str] = None,
    strict_nonzero_radimp: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    selected_profile = get_runner_test_profile(test_profile)
    simulation_timeout_minutes = max(1, int(selected_profile.simulation_timeout_minutes))
    akabak_solve_timeout_s = simulation_timeout_minutes * 60
    workspace = resolve_runner_test_workspace(workspace_root)
    db = RunnerTestDb(workspace.db_path)
    tracker = HarnessProcessTracker(workspace.logs_dir / "process_ledger.json")
    case_payload = _load_case_payload(case_id, cases_root=cases_root)
    resolved_template_cfg = _resolve_case_template_cfg(case_payload=case_payload, template_cfg_path=template_cfg_path)
    project, batch = _build_project_and_batch(case_payload, workspace)
    ath_export_root_hint = str(case_payload.get("ath_export_root", "") or "").strip() or None
    case_le_repair_profile = str(case_payload.get("le_repair_profile", "") or "").strip() or None
    effective_le_repair_profile = str(le_repair_profile or case_le_repair_profile or "").strip() or None
    case_cfg_le_profile = str(case_payload.get("cfg_le_profile", "") or "").strip() or None
    effective_cfg_le_profile = str(cfg_le_profile or case_cfg_le_profile or "").strip() or None
    case_radimp_profile = str(case_payload.get("radimp_observation_profile", "") or "").strip() or None
    effective_radimp_profile = str(radimp_observation_profile or case_radimp_profile or "").strip() or None
    case_driving_profile = str(case_payload.get("driving_observation_profile", "") or "").strip() or None
    effective_driving_profile = str(driving_observation_profile or case_driving_profile or "").strip() or None
    effective_le_driver_tag = str(case_payload.get("le_driver_tag", "D1") or "D1").strip() or "D1"
    effective_le_drvgroup = str(case_payload.get("le_drvgroup", "1001") or "1001").strip() or "1001"
    try:
        effective_le_voltage_vrms = float(case_payload.get("le_voltage_vrms", 1.0))
    except Exception:
        effective_le_voltage_vrms = 1.0

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
                "simulation_timeout_minutes": simulation_timeout_minutes,
                "template_cfg": str(resolved_template_cfg) if resolved_template_cfg else None,
                "ath_export_root_hint": ath_export_root_hint,
                "le_repair_profile": effective_le_repair_profile,
                "cfg_le_profile": effective_cfg_le_profile,
                "radimp_observation_profile": effective_radimp_profile,
                "driving_observation_profile": effective_driving_profile,
                "le_driver_tag": effective_le_driver_tag,
                "le_drvgroup": effective_le_drvgroup,
                "le_voltage_vrms": effective_le_voltage_vrms,
                "tool_probe": tool_probe,
                "export_root_probe": export_root_probe,
            },
            notes=f"case={case_id}; keep_exports={str(bool(keep_exports)).lower()}",
        )

        try:
            preflight_started = _now_iso()
            stale_kill_results = tracker.kill_stale()
            process_scan = _wait_for_unmanaged_processes_to_clear(tracker)
            missing_tools = []
            preflight_blockers: List[str] = []
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
                if bool(process_scan.get("blocked")):
                    preflight_blockers.append("unmanaged_tool_processes_running")
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="preflight",
                status="ok" if not missing_tools and not preflight_blockers else "failed",
                started_at=preflight_started,
                finished_at=_now_iso(),
                details={
                    "dry_run": bool(dry_run),
                    "workspace": workspace.to_dict(),
                    "stale_process_cleanup": stale_kill_results,
                    "process_scan": process_scan,
                    "tool_probe": tool_probe,
                    "ath_export_root_hint": ath_export_root_hint,
                    "export_root_probe": export_root_probe,
                },
                error={
                    "missing_tools": missing_tools,
                    "preflight_blockers": preflight_blockers,
                    "unmanaged_processes": list(process_scan.get("unmanaged_processes", []) or []),
                }
                if missing_tools or preflight_blockers
                else {},
            )
            if missing_tools:
                notes = "preflight missing tools"
                raise RuntimeError("missing required executables for non-dry run")
            if preflight_blockers:
                notes = "preflight blocked by unmanaged tool processes"
                raise HarnessManualInterferenceError(
                    "unmanaged AKABAK/VACS process detected; close manual tool windows and retry"
                )

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
            effective_sim_settings, profile_sim_mode, forced_by_harness_guard = _enforce_free_standing_for_tests(
                effective_sim_settings
            )
            requested_sim_mode = str(version.sim_export_settings.get("simulation_mode", "free_standing") or "free_standing")
            effective_sim_mode = str(effective_sim_settings.get("simulation_mode", "free_standing") or "free_standing").strip().lower()
            forced_free_standing = bool(
                requested_sim_mode.strip().lower() == "infinite_baffle"
                or forced_by_harness_guard
            )
            db.add_validation(
                test_run_id=test_run_id,
                validation_name="test_profile_applied",
                status="ok",
                metrics=profile_meta,
                message="runner test profile applied in harness context",
            )
            db.add_validation(
                test_run_id=test_run_id,
                validation_name="simulation_mode_guard",
                status="ok",
                metrics={
                    "requested_simulation_mode": requested_sim_mode,
                    "profile_effective_simulation_mode": profile_sim_mode,
                    "effective_simulation_mode": effective_sim_mode,
                    "forced_free_standing": forced_free_standing,
                    "reason": "infinite_baffle_position_not_defined_in_test_flow",
                },
                message="simulation mode forced to free_standing for test runs"
                if forced_free_standing
                else "simulation mode accepted for test run",
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
            cfg_export_specs = _resolve_export_specs_for_harness(effective_sim_settings)
            cfg_text = _apply_sim_export_settings_to_cfg(
                cfg_text,
                sim_export_settings=effective_sim_settings,
                export_specs=cfg_export_specs,
                runtime_parameters=effective_params,
            )
            cfg_path = workspace.cfg_dir / f"{test_run_id}_{version.version_id}.cfg"
            cfg_path.write_text(cfg_text, encoding="utf-8")
            cfg_patch = _patch_cfg_le_profile(
                cfg_path=cfg_path,
                profile=effective_cfg_le_profile,
                diagnostics_dir=workspace.logs_dir / test_run_id / "cfg_patch",
            )
            if cfg_patch.diagnostics_path:
                patch_diag_file = Path(cfg_patch.diagnostics_path)
                if patch_diag_file.exists() and patch_diag_file.is_file():
                    db.add_artifact(
                        test_run_id=test_run_id,
                        kind="cfg_patch_summary",
                        path=str(patch_diag_file),
                        sha256=_sha256_file(patch_diag_file),
                        bytes_size=patch_diag_file.stat().st_size,
                    )
            db.add_validation(
                test_run_id=test_run_id,
                validation_name="cfg_le_profile_applied",
                status="ok" if cfg_patch.ok else "failed",
                metrics=cfg_patch.to_dict(),
                message="cfg LE profile patch applied"
                if cfg_patch.ok
                else f"cfg LE profile patch failed: {cfg_patch.error or cfg_patch.status}",
            )
            if not cfg_patch.ok:
                notes = "cfg LE profile patch failed"
                raise RuntimeError(
                    "cfg_le_profile_patch_failed: "
                    f"status={cfg_patch.status} error={cfg_patch.error or 'n/a'}"
                )
            cfg_text = cfg_path.read_text(encoding="utf-8", errors="replace")
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
                    "cfg_le_profile": cfg_patch.to_dict(),
                    "cfg_export_specs_count": int(len(cfg_export_specs)),
                    "effective_simulation_mode": str(effective_sim_settings.get("simulation_mode", "")),
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
                    le_patch_profile=effective_le_repair_profile,
                    le_driver_tag=effective_le_driver_tag,
                    le_drvgroup_value=effective_le_drvgroup,
                    le_voltage_vrms=effective_le_voltage_vrms,
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
                        "driver_patch_status": driver_sync.driver_patch.status,
                        "driver_patch_profile": driver_sync.driver_patch.profile,
                        "driver_line_changed": driver_sync.driver_patch.driver_line_changed,
                        "def_driving_changed": driver_sync.driver_patch.def_driving_changed,
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
                observation_patch_started = _now_iso()
                observation_patch = _patch_observation_radimp_profile(
                    abec_path=abec_path,
                    profile=effective_radimp_profile,
                    diagnostics_dir=workspace.logs_dir / test_run_id / "observation_patch",
                )
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="post_ath_observation_patch",
                    status="ok" if observation_patch.ok else "failed",
                    started_at=observation_patch_started,
                    finished_at=_now_iso(),
                    details=observation_patch.to_dict(),
                    error={} if observation_patch.ok else {"error": observation_patch.error or observation_patch.status},
                )
                if observation_patch.diagnostics_path:
                    patch_diag_file = Path(observation_patch.diagnostics_path)
                    if patch_diag_file.exists() and patch_diag_file.is_file():
                        db.add_artifact(
                            test_run_id=test_run_id,
                            kind="observation_patch_summary",
                            path=str(patch_diag_file),
                            sha256=_sha256_file(patch_diag_file),
                            bytes_size=patch_diag_file.stat().st_size,
                        )
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="post_ath_observation_patch_assertions",
                    status="ok" if observation_patch.ok else "failed",
                    metrics={
                        "profile": observation_patch.profile,
                        "status": observation_patch.status,
                        "changed_files": observation_patch.changed_files,
                        "radimp_entries_seen": observation_patch.radimp_entries_seen,
                        "observation_files": observation_patch.observation_files,
                    },
                    message="post-ATH observation patch assertions passed"
                    if observation_patch.ok
                    else f"post-ATH observation patch failed: {observation_patch.error or observation_patch.status}",
                )
                if not observation_patch.ok:
                    notes = "post-ATH observation patch failed"
                    raise RuntimeError(
                        "post_ath_observation_patch_failed: "
                        f"status={observation_patch.status} error={observation_patch.error or 'n/a'}"
                    )
                driving_patch_started = _now_iso()
                driving_patch = _patch_observation_driving_profile(
                    abec_path=abec_path,
                    profile=effective_driving_profile,
                    diagnostics_dir=workspace.logs_dir / test_run_id / "driving_patch",
                )
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="post_ath_driving_patch",
                    status="ok" if driving_patch.ok else "failed",
                    started_at=driving_patch_started,
                    finished_at=_now_iso(),
                    details=driving_patch.to_dict(),
                    error={} if driving_patch.ok else {"error": driving_patch.error or driving_patch.status},
                )
                if driving_patch.diagnostics_path:
                    driving_diag_file = Path(driving_patch.diagnostics_path)
                    if driving_diag_file.exists() and driving_diag_file.is_file():
                        db.add_artifact(
                            test_run_id=test_run_id,
                            kind="driving_patch_summary",
                            path=str(driving_diag_file),
                            sha256=_sha256_file(driving_diag_file),
                            bytes_size=driving_diag_file.stat().st_size,
                        )
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="post_ath_driving_patch_assertions",
                    status="ok" if driving_patch.ok else "failed",
                    metrics={
                        "profile": driving_patch.profile,
                        "status": driving_patch.status,
                        "changed_files": driving_patch.changed_files,
                        "driving_sections_seen": driving_patch.driving_sections_seen,
                        "observation_files": driving_patch.observation_files,
                    },
                    message="post-ATH driving patch assertions passed"
                    if driving_patch.ok
                    else f"post-ATH driving patch failed: {driving_patch.error or driving_patch.status}",
                )
                if not driving_patch.ok:
                    notes = "post-ATH driving patch failed"
                    raise RuntimeError(
                        "post_ath_driving_patch_failed: "
                        f"status={driving_patch.status} error={driving_patch.error or 'n/a'}"
                    )
                le_guard_started = _now_iso()
                le_contract = _assess_pre_akabak_le_driving_contract(
                    abec_path=abec_path,
                    expected_drvgroup=effective_le_drvgroup,
                )
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="pre_akabak_le_driving_contract",
                    status="ok" if bool(le_contract.get("ok")) else "failed",
                    metrics=le_contract,
                    message="pre-AKABAK LE/Driving contract passed"
                    if bool(le_contract.get("ok"))
                    else "pre-AKABAK LE/Driving contract failed",
                )
                db.add_test_run_step(
                    test_run_id=test_run_id,
                    step_name="pre_akabak_le_driving_guard",
                    status="ok" if bool(le_contract.get("ok")) else "failed",
                    started_at=le_guard_started,
                    finished_at=_now_iso(),
                    details=le_contract,
                    error={}
                    if bool(le_contract.get("ok"))
                    else {"violations": list(le_contract.get("violations", []) or [])},
                )
                if not bool(le_contract.get("ok")):
                    notes = "pre-akabak LE/Driving contract failed"
                    raise RuntimeError(
                        "pre_akabak_le_driving_contract_failed: "
                        + ",".join(str(item) for item in list(le_contract.get("violations", []) or []))
                    )

                ath_input_dir = abec_path.parent
                ath_snapshot_dir = workspace.logs_dir / test_run_id / "ath_input_snapshot"
                snapshot_targets = (
                    ("ath_input_project", ath_input_dir / "Project.abec", "Project.abec"),
                    ("ath_input_solving", ath_input_dir / "solving.txt", "solving.txt"),
                    ("ath_input_observation", ath_input_dir / "observation.txt", "observation.txt"),
                    (
                        "ath_input_le_script",
                        ath_input_dir / str(driver_sync.expected_script_filename),
                        str(driver_sync.expected_script_filename),
                    ),
                )
                for artifact_kind, source_file, snapshot_name in snapshot_targets:
                    snapshot = _copy_artifact_snapshot(
                        source_path=source_file,
                        snapshot_root=ath_snapshot_dir,
                        snapshot_name=snapshot_name,
                    )
                    if snapshot is None:
                        continue
                    db.add_artifact(
                        test_run_id=test_run_id,
                        kind=artifact_kind,
                        path=str(snapshot),
                        sha256=_sha256_file(snapshot),
                        bytes_size=snapshot.stat().st_size,
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
                    vacs_executable=str(vacs_executable) if vacs_executable else None,
                )
                akabak_pid_registered = False
                akabak_watchdog_events: List[Dict[str, Any]] = []
                akabak_stage_succeeded = False

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
                    try:
                        akabak_driver.wait_for_completion(
                            timeout_s=akabak_solve_timeout_s,
                            require_vacs_graph_import=True,
                        )
                    except TypeError:
                        akabak_driver.wait_for_completion(timeout_s=akabak_solve_timeout_s)
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
                    akabak_stage_succeeded = True
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
                        akabak_driver.close(preserve_vacs=akabak_stage_succeeded)
                    except TypeError:
                        # Compatibility for test doubles and older injected drivers.
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
                for vacs_pid in _list_running_vacs_pids():
                    tracker.register(
                        run_id=test_run_id,
                        app="vacs",
                        pid=int(vacs_pid),
                        started_by_harness=True,
                    )
                    started_pids.append(int(vacs_pid))
                results_dir = abec_path.parent / "Results"
                if results_dir.exists() and results_dir.is_dir():
                    results_snapshot_dir = workspace.logs_dir / test_run_id / "akabak_results_snapshot"
                    for result_file in sorted(results_dir.glob("*.txt")):
                        snapshot = _copy_artifact_snapshot(
                            source_path=result_file,
                            snapshot_root=results_snapshot_dir,
                            snapshot_name=result_file.name,
                        )
                        if snapshot is None:
                            continue
                        db.add_artifact(
                            test_run_id=test_run_id,
                            kind="akabak_result_txt",
                            path=str(snapshot),
                            sha256=_sha256_file(snapshot),
                            bytes_size=snapshot.stat().st_size,
                        )
                abec_tree_snapshot = _write_directory_snapshot(
                    root_path=abec_path.parent,
                    output_path=workspace.logs_dir / test_run_id / "akabak_results_snapshot" / "abec_tree.json",
                )
                if abec_tree_snapshot and abec_tree_snapshot.exists():
                    db.add_artifact(
                        test_run_id=test_run_id,
                        kind="abec_tree_snapshot",
                        path=str(abec_tree_snapshot),
                        sha256=_sha256_file(abec_tree_snapshot),
                        bytes_size=abec_tree_snapshot.stat().st_size,
                    )

                vacs_step_started = _now_iso()
                effective_batch_payload = batch.to_dict()
                effective_batch_payload["sim_export_settings"] = effective_sim_settings
                effective_batch = Batch.from_dict(effective_batch_payload)
                sim_export_payload = effective_batch.sim_export_settings.to_dict()
                export_specs = _resolve_export_specs_for_harness(sim_export_payload)
                if not export_specs:
                    notes = "no export specs configured for VACS stage"
                    raise RuntimeError("no export specs configured")

                exports_run_dir = workspace.exports_dir / test_run_id
                exports_run_dir.mkdir(parents=True, exist_ok=True)
                vacs_pids_before = set(_list_running_vacs_pids())
                for observed_pid in sorted(vacs_pids_before):
                    tracker.register(
                        run_id=test_run_id,
                        app="vacs",
                        pid=int(observed_pid),
                        started_by_harness=True,
                    )
                    started_pids.append(int(observed_pid))
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
                        akabak_executable=str(akabak_executable) if akabak_executable else None,
                        allow_graph_kind_fallback=True,
                    )
                except Exception:
                    vacs_pids_after = set(_list_running_vacs_pids())
                    leaked_vacs_pids = sorted(pid for pid in vacs_pids_after if pid not in vacs_pids_before)
                    for leaked_pid in leaked_vacs_pids:
                        tracker.register(
                            run_id=test_run_id,
                            app="vacs",
                            pid=leaked_pid,
                            started_by_harness=True,
                        )
                        started_pids.append(leaked_pid)
                    _capture_ui_observation(
                        db=db,
                        test_run_id=test_run_id,
                        app="vacs",
                        workspace=workspace,
                        notes="vacs_stage_exception",
                        pid=None,
                        executable=str(vacs_executable) if vacs_executable else None,
                    )
                    db.add_test_run_step(
                        test_run_id=test_run_id,
                        step_name="vacs_export",
                        status="failed",
                        started_at=vacs_step_started,
                        finished_at=_now_iso(),
                        details={
                            "leaked_vacs_pids": leaked_vacs_pids,
                            "vacs_pids_before": sorted(vacs_pids_before),
                            "vacs_pids_after": sorted(vacs_pids_after),
                        },
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
                vacs_pids_after_success = set(_list_running_vacs_pids())
                for discovered_pid in sorted(pid for pid in vacs_pids_after_success if pid not in vacs_pids_before):
                    tracker.register(
                        run_id=test_run_id,
                        app="vacs",
                        pid=int(discovered_pid),
                        started_by_harness=True,
                    )
                    started_pids.append(int(discovered_pid))

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
                    radimp_diagnosis = _diagnose_radimp(
                        abec_path=abec_path,
                        export_diagnostics=[],
                        watchdog_events=akabak_watchdog_events,
                        solve_completed=True,
                        export_stage_executed=bool(vacs_summary.get("executed")),
                        expected_export_kinds=[str(spec.graph_kind or "") for spec in export_specs],
                    )
                    db.add_validation(
                        test_run_id=test_run_id,
                        validation_name="radimp_diagnosis",
                        status=str(radimp_diagnosis["status"]),
                        metrics=dict(radimp_diagnosis["metrics"]),
                        message=str(radimp_diagnosis["message"]),
                    )
                    notes = "VACS export produced no files"
                    raise RuntimeError("no exported files")

                ingest_rows: List[Dict[str, Any]] = []
                validation_failed = False
                export_diagnostics: List[Dict[str, Any]] = []
                requested_export_kinds = {
                    str(spec.graph_kind or "").strip().lower()
                    for spec in list(export_specs or [])
                    if str(spec.graph_kind or "").strip()
                }
                for export_item in export_items:
                    output_path = Path(str(export_item.get("output_path", ""))).resolve()
                    spec_payload = dict(export_item.get("spec", {}) or {})
                    expected_kind = str(spec_payload.get("graph_kind", "unknown"))
                    expected_kind_norm = str(expected_kind).strip().lower()
                    details_payload = dict(export_item.get("details", {}) or {})
                    mapping_mode = str(details_payload.get("mapping_mode", "")).strip().lower()
                    is_unrequested_any_graph_fallback = bool(
                        mapping_mode == "any_graph"
                        and expected_kind_norm
                        and expected_kind_norm not in requested_export_kinds
                    )
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
                    validation_status = str(validation["status"])
                    validation_message = str(validation["message"])
                    validation_metrics = dict(validation.get("metrics", {}) or {})
                    if is_unrequested_any_graph_fallback and validation_status != "ok":
                        validation_metrics["fallback_unrequested_any_graph"] = True
                        validation_metrics["original_status"] = validation_status
                        validation_metrics["original_message"] = validation_message
                        validation_status = "ok"
                        validation_message = (
                            "accepted any-graph fallback export for unrequested graph kind"
                        )
                    export_diagnostics.append(
                        {
                            **validation_metrics,
                            "expected_kind": expected_kind,
                            "parsed_graph_type": parsed.graph_type,
                            "output_path": str(output_path),
                        }
                    )
                    db.add_validation(
                        test_run_id=test_run_id,
                        validation_name=f"export_quality:{expected_kind}",
                        status=validation_status,
                        metrics=validation_metrics,
                        message=validation_message,
                    )
                    if validation_status != "ok":
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
                    solve_completed=True,
                    export_stage_executed=bool(vacs_summary.get("executed")),
                    expected_export_kinds=[str(spec.graph_kind or "") for spec in export_specs],
                )
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="radimp_diagnosis",
                    status=str(radimp_diagnosis["status"]),
                    metrics=dict(radimp_diagnosis["metrics"]),
                    message=str(radimp_diagnosis["message"]),
                )
                if strict_nonzero_radimp:
                    nonzero_ok = str(radimp_diagnosis.get("classification") or "") == "radimp_nonzero"
                    db.add_validation(
                        test_run_id=test_run_id,
                        validation_name="strict_nonzero_radimp",
                        status="ok" if nonzero_ok else "failed",
                        metrics={
                            "strict_nonzero_radimp": True,
                            "radimp_classification": str(radimp_diagnosis.get("classification") or ""),
                            "radimp_status": str(radimp_diagnosis.get("status") or ""),
                        },
                        message="strict non-zero RadImp gate passed"
                        if nonzero_ok
                        else "strict non-zero RadImp gate failed (RadImp is still zero or unavailable)",
                    )
                    if not nonzero_ok:
                        validation_failed = True
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
        except HarnessManualInterferenceError as exc:
            run_status = "aborted"
            notes = str(exc) or "manual tool interference detected"
            db.upsert_run(
                run_id=test_run_id,
                project_id=project.project_id,
                batch_id=batch.batch_id,
                status="aborted",
                finished_at=_now_iso(),
                error_summary=str(exc),
            )
            if version_id:
                db.upsert_run_version(
                    run_id=test_run_id,
                    version_id=version_id,
                    project_id=project.project_id,
                    batch_id=batch.batch_id,
                    status="aborted",
                    finished_at=_now_iso(),
                    error_summary=str(exc),
                )
                db.upsert_version(
                    version_id=version_id,
                    project_id=project.project_id,
                    batch_id=batch.batch_id,
                    status="aborted",
                    finished_at=_now_iso(),
                )
        except (VacsExportPipelineError, Exception) as exc:
            if isinstance(exc, VacsExportPipelineError):
                exc_text = str(exc)
                lower_text = exc_text.lower()
                if "could not map graph_kind='impedance'" in lower_text or "graph_kind='impedance'" in lower_text:
                    diagnosis_class = "wrong_graph_exported"
                    diagnosis_message = "RadImp graph mapping failed in VACS export stage"
                else:
                    diagnosis_class = "solve_not_completed_or_no_results"
                    diagnosis_message = "RadImp evaluation failed before ingest due to export-stage failure"
                db.add_validation(
                    test_run_id=test_run_id,
                    validation_name="radimp_diagnosis",
                    status="failed",
                    metrics={
                        "classification": diagnosis_class,
                        "error_summary": exc_text,
                        "exception_type": type(exc).__name__,
                    },
                    message=diagnosis_message,
                )
                if strict_nonzero_radimp:
                    db.add_validation(
                        test_run_id=test_run_id,
                        validation_name="strict_nonzero_radimp",
                        status="failed",
                        metrics={
                            "strict_nonzero_radimp": True,
                            "radimp_classification": diagnosis_class,
                            "radimp_status": "failed",
                        },
                        message="strict non-zero RadImp gate failed due to export-stage error",
                    )
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
        "simulation_timeout_minutes": simulation_timeout_minutes,
        "akabak_solve_timeout_s": akabak_solve_timeout_s,
        "le_repair_profile": effective_le_repair_profile,
        "cfg_le_profile": effective_cfg_le_profile,
        "radimp_observation_profile": effective_radimp_profile,
        "driving_observation_profile": effective_driving_profile,
        "strict_nonzero_radimp": bool(strict_nonzero_radimp),
        "le_driver_tag": effective_le_driver_tag,
        "le_drvgroup": effective_le_drvgroup,
        "le_voltage_vrms": effective_le_voltage_vrms,
        "workspace": workspace.to_dict(),
        "db_path": str(workspace.db_path),
        "dry_run": bool(dry_run),
        "runs": [run.to_dict() for run in runs],
    }


def _read_run_validations(db_path: Path, test_run_id: str) -> Dict[str, Dict[str, Any]]:
    if not db_path.exists():
        return {}
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        rows = cur.execute(
            "select validation_name,status,message,metrics_json from validations where test_run_id=?",
            (test_run_id,),
        ).fetchall()
        payload: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            metrics: Dict[str, Any] = {}
            try:
                metrics = json.loads(str(row["metrics_json"] or "{}"))
            except Exception:
                metrics = {}
            payload[str(row["validation_name"])] = {
                "status": str(row["status"] or ""),
                "message": str(row["message"] or ""),
                "metrics": metrics,
            }
        return payload
    finally:
        con.close()


def _read_run_artifacts(db_path: Path, test_run_id: str, *, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    if not db_path.exists():
        return []
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        if kind:
            rows = cur.execute(
                "select kind,path,sha256,bytes,created_at from artifacts where test_run_id=? and kind=? order by artifact_id",
                (test_run_id, kind),
            ).fetchall()
        else:
            rows = cur.execute(
                "select kind,path,sha256,bytes,created_at from artifacts where test_run_id=? order by artifact_id",
                (test_run_id,),
            ).fetchall()
        payload: List[Dict[str, Any]] = []
        for row in rows:
            payload.append(
                {
                    "kind": str(row["kind"] or ""),
                    "path": str(row["path"] or ""),
                    "sha256": str(row["sha256"] or "") or None,
                    "bytes": int(row["bytes"] or 0) if row["bytes"] is not None else None,
                    "created_at": str(row["created_at"] or ""),
                }
            )
        return payload
    finally:
        con.close()


def _safe_median(values: Sequence[float]) -> Optional[float]:
    filtered = [float(item) for item in values if item is not None and math.isfinite(float(item))]
    if not filtered:
        return None
    filtered.sort()
    mid = len(filtered) // 2
    if len(filtered) % 2 == 1:
        return float(filtered[mid])
    return float((filtered[mid - 1] + filtered[mid]) / 2.0)


def _read_run_curve_vectors(
    db_path: Path,
    test_run_id: str,
    *,
    graph_kinds: Sequence[str] = ("spl", "impedance"),
) -> Dict[str, Dict[str, List[Tuple[float, float]]]]:
    if not db_path.exists():
        return {}
    kind_filter = [str(item).strip().lower() for item in graph_kinds if str(item).strip()]
    if not kind_filter:
        return {}
    placeholders = ",".join("?" for _ in kind_filter)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"""
            select
                g.graph_kind as graph_kind,
                g.variant as variant,
                gs.series_kind as series_kind,
                gs.label as series_label,
                gs.angle_deg as angle_deg,
                gp.point_index as point_index,
                gp.x_value as x_value,
                gp.y_value as y_value,
                gp.y_imag as y_imag
            from graphs g
            join graph_series gs on gs.graph_id = g.graph_id
            join graph_points gp on gp.series_id = gs.series_id
            where g.run_id = ?
              and lower(coalesce(g.graph_kind, '')) in ({placeholders})
            order by g.graph_kind, g.variant, gs.series_kind, gs.label, gs.angle_deg, gp.point_index
            """,
            [test_run_id, *kind_filter],
        ).fetchall()
    finally:
        con.close()

    payload: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}
    for row in rows:
        graph_kind = str(row["graph_kind"] or "").strip().lower()
        variant = str(row["variant"] or "default").strip() or "default"
        series_kind = str(row["series_kind"] or "").strip() or "curve"
        label = str(row["series_label"] or "").strip() or "default"
        angle = row["angle_deg"]
        angle_token = "" if angle is None else f"{float(angle):.6f}"
        key = "|".join([variant, series_kind, label, angle_token])
        x_value = float(row["x_value"] or 0.0)
        y_value = float(row["y_value"] or 0.0)
        y_imag = row["y_imag"]
        if y_imag is not None:
            value = math.sqrt((y_value * y_value) + (float(y_imag) * float(y_imag)))
        else:
            value = y_value
        kind_payload = payload.setdefault(graph_kind, {})
        series_payload = kind_payload.setdefault(key, [])
        series_payload.append((x_value, float(value)))
    return payload


def _compute_run_pair_effect_size(
    db_path: Path,
    *,
    baseline_run_id: str,
    candidate_run_id: str,
) -> Dict[str, Any]:
    baseline = _read_run_curve_vectors(db_path, baseline_run_id)
    candidate = _read_run_curve_vectors(db_path, candidate_run_id)
    metrics: Dict[str, Any] = {
        "baseline_run_id": baseline_run_id,
        "candidate_run_id": candidate_run_id,
    }
    for graph_kind in ("spl", "impedance"):
        baseline_kind = baseline.get(graph_kind, {})
        candidate_kind = candidate.get(graph_kind, {})
        common_keys = sorted(set(baseline_kind.keys()).intersection(set(candidate_kind.keys())))
        weighted_sum = 0.0
        compared_points = 0
        compared_series = 0
        skipped_series = 0
        for key in common_keys:
            series_a = baseline_kind.get(key, [])
            series_b = candidate_kind.get(key, [])
            paired_points = min(len(series_a), len(series_b))
            if paired_points <= 0:
                continue
            sum_sq = 0.0
            used_points = 0
            for index in range(paired_points):
                x_a, val_a = series_a[index]
                x_b, val_b = series_b[index]
                x_scale = max(1.0, abs(float(x_a)), abs(float(x_b)))
                if abs(float(x_a) - float(x_b)) > (1e-6 * x_scale):
                    skipped_series += 1
                    used_points = 0
                    break
                delta = float(val_b) - float(val_a)
                sum_sq += delta * delta
                used_points += 1
            if used_points <= 0:
                continue
            series_rms = math.sqrt(sum_sq / float(used_points))
            weighted_sum += series_rms * series_rms * float(used_points)
            compared_points += used_points
            compared_series += 1
        delta_rms = None
        if compared_points > 0:
            delta_rms = math.sqrt(weighted_sum / float(compared_points))
        metrics[f"{graph_kind}_delta_rms"] = delta_rms
        metrics[f"{graph_kind}_compared_series"] = compared_series
        metrics[f"{graph_kind}_compared_points"] = compared_points
        metrics[f"{graph_kind}_skipped_series"] = skipped_series
    return metrics


def _normalize_le_proof_profile(value: str) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return "control"
    aliases = {
        "control": "control",
        "baseline": "control",
        "default": "control",
        "mut_electrical": "mut_electrical",
        "electrical": "mut_electrical",
        "mutation_electrical": "mut_electrical",
        "mut_motor": "mut_motor",
        "motor": "mut_motor",
        "mutation_motor": "mut_motor",
    }
    return aliases.get(token, token)


def _map_le_proof_to_patch_profile(profile: str) -> str:
    normalized = _normalize_le_proof_profile(profile)
    if normalized == "control":
        return LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING_RESISTOR
    if normalized == "mut_electrical":
        return LE_PATCH_PROFILE_MUT_ELECTRICAL
    if normalized == "mut_motor":
        return LE_PATCH_PROFILE_MUT_MOTOR
    return normalized


def run_runner_test_radimp_driving_matrix(
    *,
    case_id: str,
    driving_profiles: Sequence[str] | None = None,
    repeats_per_profile: int = 1,
    keep_exports: bool = True,
    test_profile: str = "fast",
    workspace_root: str | Path = "runner_test_workspace",
    cases_root: str | Path = "runner_test_cases",
    template_cfg_path: Optional[str | Path] = None,
    ath_executable: Optional[str | Path] = None,
    akabak_executable: Optional[str | Path] = None,
    vacs_executable: Optional[str | Path] = None,
    le_repair_profile: Optional[str] = None,
    radimp_observation_profile: Optional[str] = None,
    strict_nonzero_radimp: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    default_profiles = ["default", "accel_2p83", "accel_10", "velocity_1", "displacement_1"]
    profile_list = [str(item).strip() for item in (driving_profiles or default_profiles) if str(item).strip()]
    if not profile_list:
        profile_list = list(default_profiles)

    matrix_rows: List[Dict[str, Any]] = []
    all_ok = True
    db_path = resolve_runner_test_workspace(workspace_root).db_path
    for profile in profile_list:
        summary = run_runner_test_harness(
            case_id=case_id,
            repeats=max(1, int(repeats_per_profile)),
            keep_exports=bool(keep_exports),
            test_profile=test_profile,
            workspace_root=workspace_root,
            cases_root=cases_root,
            template_cfg_path=template_cfg_path,
            ath_executable=ath_executable,
            akabak_executable=akabak_executable,
            vacs_executable=vacs_executable,
            le_repair_profile=le_repair_profile,
            radimp_observation_profile=radimp_observation_profile,
            driving_observation_profile=profile,
            strict_nonzero_radimp=bool(strict_nonzero_radimp),
            dry_run=bool(dry_run),
        )
        runs = list(summary.get("runs", []) or [])
        run_outcomes: List[Dict[str, Any]] = []
        for run in runs:
            run_id = str(run.get("test_run_id") or "")
            validations = _read_run_validations(db_path, run_id) if run_id else {}
            radimp_diag = validations.get("radimp_diagnosis", {})
            export_imp = validations.get("export_quality:impedance", {})
            run_outcomes.append(
                {
                    "test_run_id": run_id,
                    "status": str(run.get("status") or ""),
                    "notes": str(run.get("notes") or ""),
                    "radimp_diagnosis": radimp_diag,
                    "export_quality_impedance": export_imp,
                }
            )
        row_ok = bool(summary.get("ok", False))
        all_ok = all_ok and row_ok
        matrix_rows.append(
            {
                "driving_observation_profile": profile,
                "ok": row_ok,
                "summary": summary,
                "run_outcomes": run_outcomes,
            }
        )

    return {
        "ok": all_ok,
        "phase": "phase_radimp_driving_matrix",
        "case_id": case_id,
        "profiles": profile_list,
        "repeats_per_profile": max(1, int(repeats_per_profile)),
        "workspace": resolve_runner_test_workspace(workspace_root).to_dict(),
        "db_path": str(db_path),
        "dry_run": bool(dry_run),
        "strict_nonzero_radimp": bool(strict_nonzero_radimp),
        "results": matrix_rows,
    }


def run_runner_test_le_proof_matrix(
    *,
    case_id: str,
    profiles: Sequence[str] | None = None,
    repeats_per_profile: int = 3,
    keep_exports: bool = True,
    test_profile: str = "fast",
    workspace_root: str | Path = "runner_test_workspace",
    cases_root: str | Path = "runner_test_cases",
    template_cfg_path: Optional[str | Path] = None,
    ath_executable: Optional[str | Path] = None,
    akabak_executable: Optional[str | Path] = None,
    vacs_executable: Optional[str | Path] = None,
    cfg_le_profile: Optional[str] = None,
    radimp_observation_profile: Optional[str] = None,
    driving_observation_profile: Optional[str] = None,
    strict_le_proof: bool = False,
    randomize_order: bool = True,
    random_seed: int = 1337,
    dry_run: bool = False,
) -> Dict[str, Any]:
    registry_specs = [item.to_dict() for item in load_le_driver_registry()]
    case_payload: Dict[str, Any] = {}
    try:
        case_payload = _load_case_payload(case_id, cases_root=cases_root)
    except Exception:
        case_payload = {}

    le_proof_payload = dict(case_payload.get("le_proof", {}) or {})
    payload_profiles = le_proof_payload.get("mutation_profiles")
    default_profiles = ["control", "mut_electrical", "mut_motor"]
    if isinstance(payload_profiles, list):
        parsed_default_profiles = [str(item).strip() for item in payload_profiles if str(item).strip()]
        if parsed_default_profiles:
            default_profiles = parsed_default_profiles
    profile_list = [str(item).strip() for item in (profiles or default_profiles) if str(item).strip()]
    if not profile_list:
        profile_list = list(default_profiles)
    profile_list = [_normalize_le_proof_profile(item) for item in profile_list]

    repeats = max(1, int(repeats_per_profile))
    schedule: List[Dict[str, Any]] = []
    for profile in profile_list:
        for repeat_index in range(0, repeats):
            schedule.append({"profile": profile, "repeat_index": repeat_index + 1})
    if bool(randomize_order):
        shuffler = random.Random(int(random_seed))
        shuffler.shuffle(schedule)

    workspace = resolve_runner_test_workspace(workspace_root)
    db_path = workspace.db_path
    db = RunnerTestDb(db_path)

    matrix_id = str(uuid.uuid4())
    matrix_logs = workspace.logs_dir / "le_proof_matrix" / matrix_id
    matrix_logs.mkdir(parents=True, exist_ok=True)

    run_rows: List[Dict[str, Any]] = []
    run_index = 0
    all_ok = True
    for item in schedule:
        run_index += 1
        logical_profile = str(item["profile"])
        repeat_index = int(item["repeat_index"])
        patch_profile = _map_le_proof_to_patch_profile(logical_profile)
        summary = run_runner_test_harness(
            case_id=case_id,
            repeats=1,
            keep_exports=bool(keep_exports),
            test_profile=test_profile,
            workspace_root=workspace_root,
            cases_root=cases_root,
            template_cfg_path=template_cfg_path,
            ath_executable=ath_executable,
            akabak_executable=akabak_executable,
            vacs_executable=vacs_executable,
            le_repair_profile=patch_profile,
            cfg_le_profile=cfg_le_profile,
            radimp_observation_profile=radimp_observation_profile,
            driving_observation_profile=driving_observation_profile,
            strict_nonzero_radimp=False,
            dry_run=bool(dry_run),
        )
        runs = list(summary.get("runs", []) or [])
        run = dict(runs[0]) if runs else {}
        test_run_id = str(run.get("test_run_id") or "")
        validations = _read_run_validations(db_path, test_run_id) if test_run_id else {}
        run_status = str(run.get("status") or "")
        row_ok = bool(summary.get("ok", False))
        all_ok = all_ok and row_ok
        run_rows.append(
            {
                "matrix_index": run_index,
                "profile": logical_profile,
                "repeat_index": repeat_index,
                "le_patch_profile": patch_profile,
                "test_run_id": test_run_id,
                "run_status": run_status,
                "ok": row_ok,
                "summary": summary,
                "validations": validations,
            }
        )

    control_rows = [row for row in run_rows if row.get("profile") == "control"]
    mutation_rows = [row for row in run_rows if row.get("profile") != "control"]
    control_run_ids = [
        str(row.get("test_run_id") or "")
        for row in control_rows
        if str(row.get("run_status") or "") in {"succeeded", "dry_run_completed"} and str(row.get("test_run_id") or "")
    ]

    control_spl_valid = 0
    for row in control_rows:
        validations = dict(row.get("validations", {}) or {})
        spl = validations.get("export_quality:spl", {})
        spl_metrics = dict(spl.get("metrics", {}) or {})
        if str(spl.get("status") or "") == "ok" and int(spl_metrics.get("series_count", 0) or 0) > int(
            spl_metrics.get("all_zero_series", 0) or 0
        ):
            control_spl_valid += 1

    pair_metrics_rows: List[Dict[str, Any]] = []
    control_noise_floor = {"spl_delta_rms": 0.0, "impedance_delta_rms": 0.0}
    if len(control_run_ids) >= 2 and not dry_run:
        for index, base_run_id in enumerate(control_run_ids):
            for candidate_run_id in control_run_ids[index + 1 :]:
                pair_metrics = _compute_run_pair_effect_size(
                    db_path=db_path,
                    baseline_run_id=base_run_id,
                    candidate_run_id=candidate_run_id,
                )
                pair_metrics["kind"] = "control_pair"
                pair_metrics_rows.append(pair_metrics)
        for metric_name in ("spl_delta_rms", "impedance_delta_rms"):
            metric_values = [
                float(item[metric_name]) for item in pair_metrics_rows if item.get(metric_name) is not None
            ]
            control_noise_floor[metric_name] = max(metric_values) if metric_values else 0.0

    absolute_min_floor = {
        "spl_delta_rms": float(le_proof_payload.get("absolute_min_floor_spl", 0.25) or 0.25),
        "impedance_delta_rms": float(le_proof_payload.get("absolute_min_floor_impedance", 0.05) or 0.05),
    }
    threshold_policy = {
        key: max(5.0 * float(control_noise_floor.get(key, 0.0) or 0.0), float(absolute_min_floor[key]))
        for key in ("spl_delta_rms", "impedance_delta_rms")
    }

    mutation_run_effects: Dict[str, Dict[str, Any]] = {}
    profile_aggregate: Dict[str, Dict[str, Any]] = {}
    for row in mutation_rows:
        test_run_id = str(row.get("test_run_id") or "")
        if not test_run_id or dry_run or not control_run_ids:
            mutation_run_effects[test_run_id] = {
                "profile": row.get("profile"),
                "test_run_id": test_run_id,
                "comparisons": [],
                "effect_size": {"spl_delta_rms": None, "impedance_delta_rms": None},
                "threshold_pass": {"spl_delta_rms": False, "impedance_delta_rms": False},
            }
            continue
        comparisons: List[Dict[str, Any]] = []
        for baseline_run_id in control_run_ids:
            metrics = _compute_run_pair_effect_size(
                db_path=db_path,
                baseline_run_id=baseline_run_id,
                candidate_run_id=test_run_id,
            )
            metrics["kind"] = "mutation_vs_control"
            metrics["profile"] = str(row.get("profile") or "")
            comparisons.append(metrics)
            pair_metrics_rows.append(metrics)
        spl_values = [float(item["spl_delta_rms"]) for item in comparisons if item.get("spl_delta_rms") is not None]
        imp_values = [
            float(item["impedance_delta_rms"]) for item in comparisons if item.get("impedance_delta_rms") is not None
        ]
        spl_effect = _safe_median(spl_values)
        imp_effect = _safe_median(imp_values)
        effect_size = {"spl_delta_rms": spl_effect, "impedance_delta_rms": imp_effect}
        threshold_pass = {
            "spl_delta_rms": spl_effect is not None and spl_effect >= threshold_policy["spl_delta_rms"],
            "impedance_delta_rms": imp_effect is not None and imp_effect >= threshold_policy["impedance_delta_rms"],
        }
        mutation_run_effects[test_run_id] = {
            "profile": row.get("profile"),
            "test_run_id": test_run_id,
            "comparisons": comparisons,
            "effect_size": effect_size,
            "threshold_pass": threshold_pass,
        }

        profile_name = str(row.get("profile") or "")
        aggregate = profile_aggregate.setdefault(
            profile_name,
            {
                "run_ids": [],
                "spl_delta_values": [],
                "impedance_delta_values": [],
            },
        )
        aggregate["run_ids"].append(test_run_id)
        if spl_effect is not None:
            aggregate["spl_delta_values"].append(float(spl_effect))
        if imp_effect is not None:
            aggregate["impedance_delta_values"].append(float(imp_effect))

    profile_effects: Dict[str, Dict[str, Any]] = {}
    any_metric_above_threshold = False
    for profile_name, aggregate in profile_aggregate.items():
        spl_profile_effect = _safe_median(aggregate.get("spl_delta_values", []))
        imp_profile_effect = _safe_median(aggregate.get("impedance_delta_values", []))
        pass_map = {
            "spl_delta_rms": spl_profile_effect is not None and spl_profile_effect >= threshold_policy["spl_delta_rms"],
            "impedance_delta_rms": imp_profile_effect is not None
            and imp_profile_effect >= threshold_policy["impedance_delta_rms"],
        }
        if any(pass_map.values()):
            any_metric_above_threshold = True
        profile_effects[profile_name] = {
            "profile": profile_name,
            "run_ids": list(aggregate.get("run_ids", [])),
            "effect_size": {
                "spl_delta_rms": spl_profile_effect,
                "impedance_delta_rms": imp_profile_effect,
            },
            "threshold_pass": pass_map,
        }

    if dry_run:
        le_integration_diagnosis = "le_active_inconclusive"
    elif not control_run_ids or control_spl_valid <= 0:
        le_integration_diagnosis = "le_proof_invalid"
    elif any_metric_above_threshold:
        le_integration_diagnosis = "le_active_confirmed"
    elif mutation_rows:
        le_integration_diagnosis = "le_active_not_evidenced"
    else:
        le_integration_diagnosis = "le_active_inconclusive"

    report_payload = {
        "matrix_id": matrix_id,
        "case_id": case_id,
        "le_driver_registry": registry_specs,
        "profiles": profile_list,
        "repeats_per_profile": repeats,
        "randomize_order": bool(randomize_order),
        "random_seed": int(random_seed),
        "control_run_ids": control_run_ids,
        "control_spl_valid_runs": control_spl_valid,
        "control_noise_floor": control_noise_floor,
        "absolute_min_floor": absolute_min_floor,
        "threshold_policy": threshold_policy,
        "profile_effects": profile_effects,
        "le_integration_diagnosis": le_integration_diagnosis,
    }
    report_path = matrix_logs / "le_proof_comparison_report.json"
    report_path.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    curve_diff_path = matrix_logs / "le_proof_curve_diff.csv"
    with curve_diff_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "kind",
                "profile",
                "baseline_run_id",
                "candidate_run_id",
                "spl_delta_rms",
                "spl_compared_series",
                "spl_compared_points",
                "spl_skipped_series",
                "impedance_delta_rms",
                "impedance_compared_series",
                "impedance_compared_points",
                "impedance_skipped_series",
            ],
        )
        writer.writeheader()
        for row in pair_metrics_rows:
            writer.writerow(
                {
                    "kind": str(row.get("kind") or ""),
                    "profile": str(row.get("profile") or ""),
                    "baseline_run_id": str(row.get("baseline_run_id") or ""),
                    "candidate_run_id": str(row.get("candidate_run_id") or ""),
                    "spl_delta_rms": row.get("spl_delta_rms"),
                    "spl_compared_series": row.get("spl_compared_series"),
                    "spl_compared_points": row.get("spl_compared_points"),
                    "spl_skipped_series": row.get("spl_skipped_series"),
                    "impedance_delta_rms": row.get("impedance_delta_rms"),
                    "impedance_compared_series": row.get("impedance_compared_series"),
                    "impedance_compared_points": row.get("impedance_compared_points"),
                    "impedance_skipped_series": row.get("impedance_skipped_series"),
                }
            )

    for row in run_rows:
        test_run_id = str(row.get("test_run_id") or "")
        if not test_run_id:
            continue
        profile = str(row.get("profile") or "")
        effect_row = mutation_run_effects.get(test_run_id, {})
        effect_size = dict(effect_row.get("effect_size", {}) or {})
        threshold_pass = dict(effect_row.get("threshold_pass", {}) or {})
        db.add_validation(
            test_run_id=test_run_id,
            validation_name="le_proof_noise_floor",
            status="ok" if control_run_ids and not dry_run else "skipped",
            metrics={
                "profile": profile,
                "control_run_ids": control_run_ids,
                "control_noise_floor": control_noise_floor,
                "absolute_min_floor": absolute_min_floor,
                "threshold_policy": threshold_policy,
            },
            message="LE proof noise floor computed"
            if control_run_ids and not dry_run
            else "LE proof noise floor unavailable (dry-run or missing controls)",
        )
        db.add_validation(
            test_run_id=test_run_id,
            validation_name="le_proof_effect_size",
            status="ok" if profile != "control" and effect_size else "skipped",
            metrics={
                "profile": profile,
                "effect_size": effect_size,
                "threshold_pass": threshold_pass,
                "threshold_policy": threshold_policy,
            },
            message="LE proof effect size computed for mutation profile"
            if profile != "control" and effect_size
            else "LE proof effect size not applicable for control profile",
        )
        diagnosis_status = "ok" if le_integration_diagnosis == "le_active_confirmed" else "failed"
        if le_integration_diagnosis == "le_active_inconclusive":
            diagnosis_status = "skipped"
        db.add_validation(
            test_run_id=test_run_id,
            validation_name="le_integration_diagnosis",
            status=diagnosis_status,
            metrics={
                "profile": profile,
                "diagnosis": le_integration_diagnosis,
                "profile_effects": profile_effects,
                "strict_le_proof": bool(strict_le_proof),
            },
            message=f"LE integration diagnosis: {le_integration_diagnosis}",
        )
        for artifact_path, artifact_kind in (
            (report_path, "le_proof_comparison_report"),
            (curve_diff_path, "le_proof_curve_diff"),
        ):
            if artifact_path.exists() and artifact_path.is_file():
                db.add_artifact(
                    test_run_id=test_run_id,
                    kind=artifact_kind,
                    path=str(artifact_path),
                    sha256=_sha256_file(artifact_path),
                    bytes_size=artifact_path.stat().st_size,
                )
        if profile != "control":
            le_driver_artifacts = _read_run_artifacts(db_path, test_run_id, kind="le_driver")
            if le_driver_artifacts:
                source_path = Path(str(le_driver_artifacts[-1].get("path") or ""))
                if source_path.exists() and source_path.is_file():
                    db.add_artifact(
                        test_run_id=test_run_id,
                        kind="le_mutated_driver",
                        path=str(source_path),
                        sha256=_sha256_file(source_path),
                        bytes_size=source_path.stat().st_size,
                    )

    strict_gate_ok = le_integration_diagnosis == "le_active_confirmed"
    ok = all_ok and (strict_gate_ok or not bool(strict_le_proof))
    return {
        "ok": ok,
        "phase": "phase_le_proof_matrix",
        "matrix_id": matrix_id,
        "case_id": case_id,
        "le_driver_registry": registry_specs,
        "profiles": profile_list,
        "repeats_per_profile": repeats,
        "randomize_order": bool(randomize_order),
        "random_seed": int(random_seed),
        "strict_le_proof": bool(strict_le_proof),
        "workspace": workspace.to_dict(),
        "db_path": str(db_path),
        "dry_run": bool(dry_run),
        "le_integration_diagnosis": le_integration_diagnosis,
        "control_noise_floor": control_noise_floor,
        "threshold_policy": threshold_policy,
        "profile_effects": profile_effects,
        "report_artifact": str(report_path),
        "curve_diff_artifact": str(curve_diff_path),
        "results": run_rows,
    }


def run_runner_test_radimp_3scope_matrix(
    *,
    case_id: str,
    cfg_profiles: Sequence[str] | None = None,
    radimp_profiles: Sequence[str] | None = None,
    driving_profiles: Sequence[str] | None = None,
    repeats_per_combo: int = 1,
    keep_exports: bool = True,
    test_profile: str = "fast",
    workspace_root: str | Path = "runner_test_workspace",
    cases_root: str | Path = "runner_test_cases",
    template_cfg_path: Optional[str | Path] = None,
    ath_executable: Optional[str | Path] = None,
    akabak_executable: Optional[str | Path] = None,
    vacs_executable: Optional[str | Path] = None,
    le_repair_profile: Optional[str] = None,
    strict_nonzero_radimp: bool = False,
    randomize_order: bool = True,
    random_seed: int = 1337,
    dry_run: bool = False,
) -> Dict[str, Any]:
    default_cfg_profiles = ["default", "le_voltage_2p83", "le_voltage_10"]
    default_radimp_profiles = ["default", "force_absolute"]
    default_driving_profiles = ["default", "accel_2p83"]
    cfg_profile_list = [str(item).strip() for item in (cfg_profiles or default_cfg_profiles) if str(item).strip()]
    radimp_profile_list = [str(item).strip() for item in (radimp_profiles or default_radimp_profiles) if str(item).strip()]
    driving_profile_list = [str(item).strip() for item in (driving_profiles or default_driving_profiles) if str(item).strip()]
    if not cfg_profile_list:
        cfg_profile_list = list(default_cfg_profiles)
    if not radimp_profile_list:
        radimp_profile_list = list(default_radimp_profiles)
    if not driving_profile_list:
        driving_profile_list = list(default_driving_profiles)

    combo_rows: List[Tuple[str, str, str]] = []
    for cfg_profile in cfg_profile_list:
        for radimp_profile in radimp_profile_list:
            for driving_profile in driving_profile_list:
                combo_rows.append((cfg_profile, radimp_profile, driving_profile))
    if bool(randomize_order):
        shuffler = random.Random(int(random_seed))
        shuffler.shuffle(combo_rows)

    db_path = resolve_runner_test_workspace(workspace_root).db_path
    all_ok = True
    matrix_rows: List[Dict[str, Any]] = []
    for cfg_profile, radimp_profile, driving_profile in combo_rows:
                summary = run_runner_test_harness(
                    case_id=case_id,
                    repeats=max(1, int(repeats_per_combo)),
                    keep_exports=bool(keep_exports),
                    test_profile=test_profile,
                    workspace_root=workspace_root,
                    cases_root=cases_root,
                    template_cfg_path=template_cfg_path,
                    ath_executable=ath_executable,
                    akabak_executable=akabak_executable,
                    vacs_executable=vacs_executable,
                    le_repair_profile=le_repair_profile,
                    cfg_le_profile=cfg_profile,
                    radimp_observation_profile=radimp_profile,
                    driving_observation_profile=driving_profile,
                    strict_nonzero_radimp=bool(strict_nonzero_radimp),
                    dry_run=bool(dry_run),
                )
                runs = list(summary.get("runs", []) or [])
                run_outcomes: List[Dict[str, Any]] = []
                for run in runs:
                    run_id = str(run.get("test_run_id") or "")
                    validations = _read_run_validations(db_path, run_id) if run_id else {}
                    run_outcomes.append(
                        {
                            "test_run_id": run_id,
                            "status": str(run.get("status") or ""),
                            "notes": str(run.get("notes") or ""),
                            "cfg_le_profile_applied": validations.get("cfg_le_profile_applied", {}),
                            "radimp_diagnosis": validations.get("radimp_diagnosis", {}),
                            "export_quality_impedance": validations.get("export_quality:impedance", {}),
                        }
                    )
                row_ok = bool(summary.get("ok", False))
                all_ok = all_ok and row_ok
                matrix_rows.append(
                    {
                        "cfg_le_profile": cfg_profile,
                        "radimp_observation_profile": radimp_profile,
                        "driving_observation_profile": driving_profile,
                        "ok": row_ok,
                        "summary": summary,
                        "run_outcomes": run_outcomes,
                    }
                )

    return {
        "ok": all_ok,
        "phase": "phase_radimp_3scope_matrix",
        "case_id": case_id,
        "cfg_profiles": cfg_profile_list,
        "radimp_profiles": radimp_profile_list,
        "driving_profiles": driving_profile_list,
        "repeats_per_combo": max(1, int(repeats_per_combo)),
        "randomize_order": bool(randomize_order),
        "random_seed": int(random_seed),
        "strict_nonzero_radimp": bool(strict_nonzero_radimp),
        "workspace": resolve_runner_test_workspace(workspace_root).to_dict(),
        "db_path": str(db_path),
        "dry_run": bool(dry_run),
        "results": matrix_rows,
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
            process_scan = _wait_for_unmanaged_processes_to_clear(tracker)
            missing_inputs: List[str] = []
            preflight_blockers: List[str] = []
            if not dry_run:
                if not akabak_input.exists() or not akabak_input.is_file():
                    missing_inputs.append(f"akabak_executable:not_found:{akabak_input}")
                if not abec_input.exists() or not abec_input.is_file():
                    missing_inputs.append(f"abec_path:not_found:{abec_input}")
                if bool(process_scan.get("blocked")):
                    preflight_blockers.append("unmanaged_tool_processes_running")
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="preflight",
                status="ok" if not missing_inputs and not preflight_blockers else "failed",
                started_at=preflight_started,
                finished_at=_now_iso(),
                details={
                    "dry_run": bool(dry_run),
                    "workspace": workspace.to_dict(),
                    "stale_process_cleanup": stale_kill_results,
                    "process_scan": process_scan,
                    "akabak_executable": str(akabak_input),
                    "abec_path": str(abec_input),
                },
                error={
                    "missing_inputs": missing_inputs,
                    "preflight_blockers": preflight_blockers,
                    "unmanaged_processes": list(process_scan.get("unmanaged_processes", []) or []),
                }
                if missing_inputs or preflight_blockers
                else {},
            )
            if missing_inputs:
                notes = "preflight missing inputs"
                raise RuntimeError("missing inputs for open-dialog-only harness")
            if preflight_blockers:
                notes = "preflight blocked by unmanaged tool processes"
                raise RuntimeError("unmanaged AKABAK/VACS process detected; close manual tool windows and retry")

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
            process_scan = _wait_for_unmanaged_processes_to_clear(tracker)
            missing_inputs: List[str] = []
            preflight_blockers: List[str] = []
            if not dry_run:
                if not akabak_input.exists() or not akabak_input.is_file():
                    missing_inputs.append(f"akabak_executable:not_found:{akabak_input}")
                if not abec_input.exists() or not abec_input.is_file():
                    missing_inputs.append(f"abec_path:not_found:{abec_input}")
                if bool(process_scan.get("blocked")):
                    preflight_blockers.append("unmanaged_tool_processes_running")
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="preflight",
                status="ok" if not missing_inputs and not preflight_blockers else "failed",
                started_at=preflight_started,
                finished_at=_now_iso(),
                details={
                    "dry_run": bool(dry_run),
                    "workspace": workspace.to_dict(),
                    "stale_process_cleanup": stale_kill_results,
                    "process_scan": process_scan,
                    "akabak_executable": str(akabak_input),
                    "abec_path": str(abec_input),
                },
                error={
                    "missing_inputs": missing_inputs,
                    "preflight_blockers": preflight_blockers,
                    "unmanaged_processes": list(process_scan.get("unmanaged_processes", []) or []),
                }
                if missing_inputs or preflight_blockers
                else {},
            )
            if missing_inputs:
                notes = "preflight missing inputs"
                raise RuntimeError("missing inputs for import-start-apply-only harness")
            if preflight_blockers:
                notes = "preflight blocked by unmanaged tool processes"
                raise RuntimeError("unmanaged AKABAK/VACS process detected; close manual tool windows and retry")

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
    le_repair_profile: Optional[str] = None,
    le_driver_tag: str = "D1",
    le_drvgroup: str = "1001",
    le_voltage_vrms: float = 1.0,
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
                "le_repair_profile": str(le_repair_profile or "").strip() or None,
                "le_driver_tag": str(le_driver_tag),
                "le_drvgroup": str(le_drvgroup),
                "le_voltage_vrms": float(le_voltage_vrms),
                "mode": "le_repair_import_only",
            },
            notes=f"le_repair_import_only repeats={effective_repeats}",
        )

        try:
            preflight_started = _now_iso()
            stale_kill_results = tracker.kill_stale()
            process_scan = _wait_for_unmanaged_processes_to_clear(tracker)
            missing_inputs: List[str] = []
            preflight_blockers: List[str] = []
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
                if bool(process_scan.get("blocked")):
                    preflight_blockers.append("unmanaged_tool_processes_running")
            db.add_test_run_step(
                test_run_id=test_run_id,
                step_name="preflight",
                status="ok" if not missing_inputs and not preflight_blockers else "failed",
                started_at=preflight_started,
                finished_at=_now_iso(),
                details={
                    "dry_run": bool(dry_run),
                    "workspace": workspace.to_dict(),
                    "stale_process_cleanup": stale_kill_results,
                    "process_scan": process_scan,
                    "akabak_executable": str(akabak_input),
                    "ath_executable": str(ath_input) if ath_input else None,
                    "ath_cfg_path": str(ath_cfg_input) if ath_cfg_input else None,
                    "abec_path": str(abec_input) if abec_input else None,
                    "reuse_export_dir": str(reuse_export_input) if reuse_export_input else None,
                },
                error={
                    "missing_inputs": missing_inputs,
                    "preflight_blockers": preflight_blockers,
                    "unmanaged_processes": list(process_scan.get("unmanaged_processes", []) or []),
                }
                if missing_inputs or preflight_blockers
                else {},
            )
            if missing_inputs:
                notes = "preflight missing inputs"
                raise RuntimeError("missing inputs for le-repair-import-only harness")
            if preflight_blockers:
                notes = "preflight blocked by unmanaged tool processes"
                raise RuntimeError("unmanaged AKABAK/VACS process detected; close manual tool windows and retry")

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
                    le_patch_profile=le_repair_profile,
                    le_driver_tag=le_driver_tag,
                    le_drvgroup_value=le_drvgroup,
                    le_voltage_vrms=float(le_voltage_vrms),
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
        "le_repair_profile": str(le_repair_profile or "").strip() or None,
        "le_driver_tag": str(le_driver_tag),
        "le_drvgroup": str(le_drvgroup),
        "le_voltage_vrms": float(le_voltage_vrms),
        "runs": [run.to_dict() for run in runs],
    }
