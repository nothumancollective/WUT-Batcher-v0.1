"""Runtime orchestration for staged ATH -> AKABAK -> VACS execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.batch_orchestrator import materialize_batch_plan
from app.ath_driver_assets import repair_post_ath_le_binding
from app.cfg_renderer import render_cfg_text
from app.constants import ATH_PREVIEW_EXPORT_ROOT
from app.export_specs import ExportSpec, parse_export_specs
from app.feature_flags import use_project_library_storage
from app.models import Batch, Project
from app.project_storage import resolve_project_paths, resolve_version_paths
from app.safe_cleanup import guarded_delete_file_in_workspace, guarded_delete_tree
from app.runners import AkabakRunner, AthRunner, RunnerResult, VacsRunner, parse_ath_dimensions
from app.tidy_dataset import TidyDatasetWriter
from app.polar_txt_parser import PolarTxtParseError, normalize_orientation_marker, parse_polar_legacy_complex_txt
from app.vacs_export_pipeline import run_vacs_export_specs
from app.vacs_txt_parser import parse_vacs_txt_file

try:
    from app.akabak_driver import AkabakDriver
except Exception:
    AkabakDriver = None  # type: ignore[assignment]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _debug_stage_logging_enabled() -> bool:
    value = str(os.environ.get("WUT_DEBUG_PIPELINE_STAGES", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _append_stage_debug_log(version_logs_dir: Path, *, event: str, payload: Dict[str, Any]) -> None:
    if not _debug_stage_logging_enabled():
        return
    path = version_logs_dir / "pipeline.stage_debug.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "time": _now_iso(),
        "event": str(event),
        **dict(payload),
    }
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        # Debug logging must never break runtime execution.
        return


def _append_run_debug_log(project_root: Path, run_id: str, *, event: str, payload: Dict[str, Any]) -> None:
    if not _debug_stage_logging_enabled():
        return
    path = Path(project_root) / "runs" / str(run_id) / "pipeline.stage_debug.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "time": _now_iso(),
        "event": str(event),
        **dict(payload),
    }
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        # Debug logging must never break runtime execution.
        return


def _describe_stage_exception(exc: BaseException) -> str:
    if isinstance(exc, SystemExit):
        code = getattr(exc, "code", None)
        if isinstance(code, BaseException):
            return f"SystemExit({type(code).__name__}: {code})"
        if code is None:
            return "SystemExit(None)"
        return f"SystemExit({code})"
    message = str(exc).strip()
    if message:
        return message
    return type(exc).__name__


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


@dataclass(frozen=True)
class StageExecution:
    version_id: str
    stage: str
    status: str
    exit_code: int
    timed_out: bool
    summary_log: str


@dataclass(frozen=True)
class RuntimeSummary:
    run_id: str
    run_status: str
    project_id: str
    batch_id: str
    project_root: str
    versions: List[str]
    stage_results: List[StageExecution]
    ath_dimension_rows: int
    cleanup_results: List[Dict[str, Any]]
    dry_run: bool = False


def _project_paths_from_root(project_root: Path):
    project_root_path = Path(project_root)
    return resolve_project_paths(project_root_path.parent, project_root_path.name, ensure=False)


def _version_json_path(project_root: Path, version_id: str) -> Path:
    return resolve_version_paths(_project_paths_from_root(project_root), version_id, ensure=False).version_json


def _version_cfg_path(project_root: Path, version_id: str) -> Path:
    return resolve_version_paths(_project_paths_from_root(project_root), version_id, ensure=False).cfg_file


def _runtime_cfg_basename(*, project_id: str, batch_id: str, version_id: str, run_id: str) -> str:
    token = "_".join([str(project_id), str(batch_id), str(version_id), str(run_id)[:8]])
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", token).strip("._")
    return cleaned or f"run_{version_id}"


def _version_runtime_cfg_path(project_root: Path, version_id: str, cfg_basename: str) -> Path:
    version_paths = resolve_version_paths(_project_paths_from_root(project_root), version_id, ensure=False)
    return version_paths.cfg_dir / f"{cfg_basename}.cfg"


def _planned_ath_export_dir(ath_export_root: Path | None, run_cfg_path: Path) -> Optional[Path]:
    if ath_export_root is None:
        return None
    return ath_export_root / run_cfg_path.stem


def _version_abec_path(project_root: Path, version_id: str) -> Path:
    return resolve_version_paths(_project_paths_from_root(project_root), version_id, ensure=False).abec_file


def _version_ath_work_path(project_root: Path, version_id: str) -> Path:
    return resolve_version_paths(_project_paths_from_root(project_root), version_id, ensure=False).ath_work_dir


def _version_logs_dir(project_root: Path, version_id: str) -> Path:
    return resolve_version_paths(_project_paths_from_root(project_root), version_id, ensure=False).logs_dir


def _version_exports_dir(project_root: Path, version_id: str, run_id: str) -> Path:
    version_paths = resolve_version_paths(_project_paths_from_root(project_root), version_id, ensure=False)
    return version_paths.exports_dir / run_id


def _load_template_text(template_cfg_path: Optional[str | Path]) -> str:
    if template_cfg_path is None:
        return "; autogenerated cfg template\n"
    return Path(template_cfg_path).read_text(encoding="utf-8")


def _resolve_template_cfg_path(
    template_cfg_path: Optional[str | Path],
    *,
    ath_executable: str | Path | None = None,
) -> Optional[Path]:
    if template_cfg_path is not None:
        path = Path(template_cfg_path).expanduser()
        return path.resolve() if path.exists() else path
    if not ath_executable:
        return None
    exe_path = Path(str(ath_executable)).expanduser()
    candidates = [
        exe_path.parent / "template_run.cfg",
        exe_path.parent / "test.cfg",
        exe_path.parent / "Tritonia.cfg",
        exe_path.parent / "testMan.cfg",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def _load_effective_template(
    template_cfg_path: Optional[str | Path],
    *,
    ath_executable: str | Path | None = None,
) -> Tuple[str, Optional[str]]:
    resolved = _resolve_template_cfg_path(template_cfg_path, ath_executable=ath_executable)
    if resolved is None:
        return "; autogenerated cfg template\n", None
    return resolved.read_text(encoding="utf-8"), str(resolved)


def _enforce_output_flag(cfg_text: str, *, key: str, value: int) -> str:
    pattern = re.compile(
        rf"(?im)^\s*{re.escape(str(key).strip())}\s*=\s*.+$",
        flags=re.MULTILINE,
    )
    replacement = f"{str(key).strip()} = {int(value)}"
    if pattern.search(cfg_text):
        return pattern.sub(replacement, cfg_text)
    text = cfg_text.rstrip()
    return f"{text}\n{replacement}\n"


def _enforce_cfg_assignment(cfg_text: str, *, key: str, value: Any) -> str:
    pattern = re.compile(
        rf"(?im)^\s*{re.escape(str(key).strip())}\s*=\s*.+$",
        flags=re.MULTILINE,
    )
    if isinstance(value, bool):
        value_text = "1" if value else "0"
    elif isinstance(value, float):
        value_text = f"{value:g}"
    else:
        value_text = str(value)
    replacement = f"{str(key).strip()} = {value_text}"
    if pattern.search(cfg_text):
        return pattern.sub(replacement, cfg_text)
    text = cfg_text.rstrip()
    return f"{text}\n{replacement}\n"


def _remove_named_cfg_blocks(cfg_text: str, *, headers: Sequence[str]) -> str:
    tokens = {str(item).strip().lower() for item in headers if str(item).strip()}
    if not tokens:
        return cfg_text
    lines = cfg_text.splitlines()
    out: List[str] = []
    idx = 0
    while idx < len(lines):
        raw = lines[idx]
        line = str(raw or "").strip()
        hit = next(
            (
                token
                for token in tokens
                if re.match(rf"^{re.escape(token)}\s*=\s*\{{\s*$", line, flags=re.IGNORECASE)
            ),
            None,
        )
        if not hit:
            out.append(raw)
            idx += 1
            continue
        idx += 1
        while idx < len(lines):
            if str(lines[idx] or "").strip() == "}":
                idx += 1
                break
            idx += 1
        while idx < len(lines) and not str(lines[idx] or "").strip():
            idx += 1
    return "\n".join(out) + ("\n" if cfg_text.endswith("\n") else "")


def _apply_sim_export_settings_to_cfg(
    cfg_text: str,
    *,
    sim_export_settings: Dict[str, Any],
    export_specs: Sequence[Any],
    runtime_parameters: Optional[Dict[str, Any]] = None,
) -> str:
    payload = dict(sim_export_settings or {})
    if not payload:
        return cfg_text

    text = cfg_text
    sim_mode = str(payload.get("simulation_mode", "free_standing") or "free_standing").strip().lower()
    sim_type = 1 if sim_mode == "infinite_baffle" else 2
    text = _enforce_cfg_assignment(text, key="ABEC.SimType", value=sim_type)

    f1 = payload.get("freq_start_hz")
    if f1 is not None:
        text = _enforce_cfg_assignment(text, key="ABEC.f1", value=float(f1))
    f2 = payload.get("freq_end_hz")
    if f2 is not None:
        text = _enforce_cfg_assignment(text, key="ABEC.f2", value=float(f2))
    points = payload.get("num_points")
    if points is not None:
        text = _enforce_cfg_assignment(text, key="ABEC.NumFrequencies", value=int(points))
    mesh_frequency = payload.get("mesh_frequency")
    if mesh_frequency is not None:
        text = _enforce_cfg_assignment(text, key="ABEC.MeshFrequency", value=float(mesh_frequency))

    polar_specs = [
        spec
        for spec in list(export_specs or [])
        if str(getattr(spec, "graph_kind", "") or "").strip().lower() == "polar"
    ]
    if not polar_specs:
        return text

    runtime_values = dict(runtime_parameters or {})

    def _to_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    length_mm = _to_float(runtime_values.get("Length"))

    headers: List[str] = []
    blocks: List[str] = []
    for idx, spec in enumerate(polar_specs, start=1):
        options = dict(getattr(spec, "options", {}) or {})
        polar_name = str(options.get("polar_name", "") or "").strip() or f"SPL_V_{idx}"
        header = f"ABEC.Polars:{polar_name}"
        headers.append(header)
        angle = list(options.get("map_angle_range", [0, 90, 19]) or [0, 90, 19])
        while len(angle) < 3:
            angle.append([0, 90, 19][len(angle)])
        angle_values = ",".join(str(int(float(item))) for item in angle[:3])
        distance = float(options.get("distance_m", 2.0) or 2.0)
        offset_from_length = _to_float(options.get("offset_from_length_mm"))
        if offset_from_length is not None and length_mm is not None:
            offset = int(round(length_mm + offset_from_length))
        else:
            offset = int(round(float(options.get("offset", 145) or 145)))
        inclination_raw = options.get("inclination")
        block_lines = [
            f"{header} = {{",
            f"  MapAngleRange = {angle_values}",
            f"  Distance = {distance:g}",
            f"  Offset = {offset}",
            "}",
        ]
        if inclination_raw is not None:
            inclination = int(round(float(inclination_raw)))
            block_lines.insert(4, f"  Inclination = {inclination}")
        blocks.append("\n".join(block_lines))

    text = _remove_named_cfg_blocks(text, headers=headers)
    stripped = text.rstrip()
    block_blob = "\n\n".join(blocks)
    if stripped:
        return f"{stripped}\n\n{block_blob}\n"
    return f"{block_blob}\n"


def _default_polar_export_specs() -> List[ExportSpec]:
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
            options={
                **base_options,
                "polar_name": "SPL_H",
                "offset": 145,
                "inclination": 0,
            },
            output_name_template="{version_id}_{graph_kind}_{export_id}.{format}",
        ),
        ExportSpec(
            id="default_polar_spl_v",
            tool="vacs",
            graph_kind="polar",
            variant="main",
            format="txt",
            options={
                **base_options,
                "polar_name": "SPL_V",
                "offset_from_length_mm": 40,
                "inclination": 90,
            },
            output_name_template="{version_id}_{graph_kind}_{export_id}.{format}",
        ),
        ExportSpec(
            id="default_polar_spl_d",
            tool="vacs",
            graph_kind="polar",
            variant="main",
            format="txt",
            options={
                **base_options,
                "polar_name": "SPL_D",
                "offset_from_length_mm": 40,
                "inclination": 45,
            },
            output_name_template="{version_id}_{graph_kind}_{export_id}.{format}",
        ),
    ]


def _plane_hint_from_polar_name(name: str) -> str:
    tokens = [token for token in re.split(r"[^a-z0-9]+", str(name or "").strip().lower()) if token]
    if any(token in {"h", "hor", "horizontal"} for token in tokens):
        return "H"
    if any(token in {"v", "ver", "vert", "vertical"} for token in tokens):
        return "V"
    if any(token in {"d", "diag", "diagonal"} for token in tokens):
        return "D"
    return ""


def _option_float(options: Dict[str, Any], key: str) -> Optional[float]:
    try:
        value = options.get(key)
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _legacy_safe_normalize_advanced_polar_specs(specs: Sequence[ExportSpec]) -> List[ExportSpec]:
    normalized: List[ExportSpec] = [spec for spec in list(specs or [])]
    by_id: Dict[str, int] = {}
    for idx, spec in enumerate(normalized):
        by_id[str(spec.id or "").strip().lower()] = idx

    h_idx = by_id.get("adv_polar_1")
    v_idx = by_id.get("adv_polar_2")
    d_idx = by_id.get("adv_polar_3")
    if h_idx is not None and v_idx is not None:
        h_spec = normalized[h_idx]
        v_spec = normalized[v_idx]
        if (
            str(h_spec.graph_kind or "").strip().lower() == "polar"
            and str(v_spec.graph_kind or "").strip().lower() == "polar"
        ):
            h_options = dict(h_spec.options or {})
            v_options = dict(v_spec.options or {})
            h_hint = _plane_hint_from_polar_name(str(h_options.get("polar_name", "") or ""))
            v_hint = _plane_hint_from_polar_name(str(v_options.get("polar_name", "") or ""))
            h_incl = _option_float(h_options, "inclination")
            v_incl = _option_float(v_options, "inclination")
            if (
                h_hint == "H"
                and v_hint == "V"
                and h_incl is not None
                and v_incl is not None
                and abs(h_incl - 90.0) <= 1e-6
                and abs(v_incl - 90.0) <= 1e-6
            ):
                h_options["inclination"] = 0
                normalized[h_idx] = ExportSpec(
                    id=h_spec.id,
                    tool=h_spec.tool,
                    graph_kind=h_spec.graph_kind,
                    variant=h_spec.variant,
                    format=h_spec.format,
                    options=h_options,
                    output_name_template=h_spec.output_name_template,
                )

    if d_idx is not None:
        d_spec = normalized[d_idx]
        if str(d_spec.graph_kind or "").strip().lower() == "polar":
            d_options = dict(d_spec.options or {})
            d_hint = _plane_hint_from_polar_name(str(d_options.get("polar_name", "") or ""))
            d_incl = _option_float(d_options, "inclination")
            if d_hint == "D" and d_incl is not None and abs(d_incl - 42.0) <= 1e-6:
                d_options["inclination"] = 45
                normalized[d_idx] = ExportSpec(
                    id=d_spec.id,
                    tool=d_spec.tool,
                    graph_kind=d_spec.graph_kind,
                    variant=d_spec.variant,
                    format=d_spec.format,
                    options=d_options,
                    output_name_template=d_spec.output_name_template,
                )
    return normalized


def _resolve_export_specs(sim_export_payload: Dict[str, Any]) -> List[ExportSpec]:
    specs = parse_export_specs(sim_export_payload)
    if specs:
        return _legacy_safe_normalize_advanced_polar_specs(specs)
    if bool(sim_export_payload.get("auto_default_polar_exports", False)):
        return _default_polar_export_specs()
    return []


def _best_mesh_cmd_for_runtime(ath_executable: str | Path | None) -> str:
    if not ath_executable:
        return ""
    candidate = Path(str(ath_executable)).expanduser().parent / "gmsh.exe"
    if candidate.exists() and candidate.is_file():
        return str(candidate.resolve())
    return ""


def _ensure_runtime_gmsh_wrapper(*, gmsh_exe: str) -> str:
    wrapper_root = Path(tempfile.gettempdir()) / "wut_batcher_mesh_wrapper"
    wrapper_root.mkdir(parents=True, exist_ok=True)
    wrapper_path = wrapper_root / "wut_runtime_gmsh_wrapper.cmd"
    gmsh_norm = str(gmsh_exe or "").strip().replace("\\", "/")
    wrapper_text = "\n".join(
        [
            "@echo off",
            "setlocal EnableDelayedExpansion",
            f"set \"GMSH_EXE={gmsh_norm}\"",
            "if not exist \"%GMSH_EXE%\" exit /b 1",
            "if exist \"mesh.geo\" (",
            "  \"%GMSH_EXE%\" -3 \"mesh.geo\" -format msh2 -o \"mesh.msh\" >nul 2>&1",
            "  exit /b %errorlevel%",
            ")",
            "for %%F in (*.geo) do (",
            "  \"%GMSH_EXE%\" -3 \"%%~fF\" -format msh2 -o \"%%~dpnF.msh\" >nul 2>&1",
            "  exit /b %errorlevel%",
            ")",
            "for /r %%F in (*.geo) do (",
            "  \"%GMSH_EXE%\" -3 \"%%~fF\" -format msh2 -o \"%%~dpnF.msh\" >nul 2>&1",
            "  exit /b %errorlevel%",
            ")",
            "exit /b 1",
            "",
        ]
    )
    try:
        existing = wrapper_path.read_text(encoding="ascii", errors="replace") if wrapper_path.exists() else ""
    except Exception:
        existing = ""
    if existing != wrapper_text:
        wrapper_path.write_text(wrapper_text, encoding="ascii")
    try:
        return str(wrapper_path.resolve())
    except Exception:
        return str(wrapper_path)


def _to_windows_short_path(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return raw
    if not any(char.isspace() for char in raw):
        return raw
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        size = ctypes.windll.kernel32.GetShortPathNameW(str(raw), buffer, len(buffer))
        if int(size) > 0:
            return str(buffer.value or raw)
    except Exception:
        return raw
    return raw


def _mesh_cmd_for_runtime(*, ath_work_dir: Path, mesh_cmd: str) -> str:
    raw = str(mesh_cmd or "").strip().strip('"').strip("'")
    if not raw:
        return raw
    if raw.lower().endswith("gmsh.exe"):
        wrapped = _ensure_runtime_gmsh_wrapper(gmsh_exe=raw)
        return _to_windows_short_path(wrapped)
    return _to_windows_short_path(raw)


def _write_runtime_ath_cfg(
    *,
    ath_work_dir: Path,
    ath_export_root: Path | None,
    ath_executable: str | Path | None,
) -> Dict[str, Any]:
    ath_work_dir.mkdir(parents=True, exist_ok=True)
    output_root = ath_export_root if ath_export_root is not None else (ath_work_dir / "ath_output")
    output_root.mkdir(parents=True, exist_ok=True)
    raw_mesh_cmd = _best_mesh_cmd_for_runtime(ath_executable)
    mesh_cmd = _mesh_cmd_for_runtime(ath_work_dir=ath_work_dir, mesh_cmd=raw_mesh_cmd)
    runtime_cfg_path = ath_work_dir / "ath.cfg"
    output_value = str(output_root).replace("\\", "/")
    runtime_cfg_path.write_text(
        (
            f'OutputRootDir = "{output_value}"\n'
            f'MeshCmd = "{mesh_cmd}"\n'
            'GnuplotPath = ""\n'
        ),
        encoding="utf-8",
    )
    return {
        "path": str(runtime_cfg_path),
        "output_root": str(output_root),
        "mesh_cmd": str(mesh_cmd),
        "mesh_cmd_raw": str(raw_mesh_cmd),
    }


def _select_generated_abec(search_roots: Sequence[Path]) -> Optional[Path]:
    candidates: List[Path] = []
    for root in search_roots:
        if not root.exists() or not root.is_dir():
            continue
        candidates.extend(path for path in root.rglob("*.abec") if path.is_file())
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    return candidates[0]


def _extract_abec_sidecar_relpaths(abec_path: Path) -> List[Path]:
    if not abec_path.exists() or not abec_path.is_file():
        return []
    try:
        text = abec_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    rows: List[Path] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = str(raw_line or "").strip()
        if not line or line.startswith(";"):
            continue
        if "=" not in line:
            continue
        _, rhs = line.split("=", 1)
        token = str(rhs or "").split(";", 1)[0].split("//", 1)[0].strip().strip('"').strip("'")
        if not token:
            continue
        if "," in token:
            token = token.split(",", 1)[0].strip()
        if not token:
            continue
        if re.match(r"^[A-Za-z]:[\\/]", token) or token.startswith("\\\\"):
            continue
        rel_path = Path(token)
        if not rel_path.name or not rel_path.suffix:
            continue
        key = str(rel_path).replace("/", "\\").strip().lower()
        if key and key not in seen:
            rows.append(rel_path)
            seen.add(key)

    try:
        for mesh in abec_path.parent.glob("*.msh"):
            rel_mesh = Path(mesh.name)
            key = str(rel_mesh).replace("/", "\\").strip().lower()
            if key and key not in seen:
                rows.append(rel_mesh)
                seen.add(key)
    except Exception:
        pass
    return rows


def _sync_generated_abec(
    *,
    target_abec: Path,
    search_roots: Sequence[Path],
    logs_dir: Path,
) -> Dict[str, Any]:
    source = _select_generated_abec(search_roots)
    payload: Dict[str, Any] = {
        "ok": False,
        "target_abec": str(target_abec),
        "search_roots": [str(root) for root in search_roots],
        "source_abec": str(source) if source is not None else "",
        "sidecar_referenced": [],
        "sidecar_copied": [],
        "sidecar_missing": [],
        "sidecar_copy_errors": [],
    }
    if source is None:
        payload["error"] = "generated_abec_missing"
        return payload
    try:
        target_abec.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target_abec.resolve():
            shutil.copy2(source, target_abec)
        sidecar_referenced = _extract_abec_sidecar_relpaths(source)
        sidecar_copied: List[str] = []
        sidecar_missing: List[str] = []
        sidecar_copy_errors: List[Dict[str, str]] = []
        for rel_path in sidecar_referenced:
            rel_token = str(rel_path)
            source_sidecar = source.parent / rel_path
            target_sidecar = target_abec.parent / rel_path
            if not source_sidecar.exists() or not source_sidecar.is_file():
                sidecar_missing.append(rel_token)
                continue
            try:
                target_sidecar.parent.mkdir(parents=True, exist_ok=True)
                if source_sidecar.resolve() != target_sidecar.resolve():
                    shutil.copy2(source_sidecar, target_sidecar)
                sidecar_copied.append(rel_token)
            except Exception as exc:
                sidecar_copy_errors.append(
                    {
                        "sidecar": rel_token,
                        "error": str(exc),
                    }
                )
        payload["sidecar_referenced"] = [str(row) for row in sidecar_referenced]
        payload["sidecar_copied"] = sidecar_copied
        payload["sidecar_missing"] = sidecar_missing
        payload["sidecar_copy_errors"] = sidecar_copy_errors
        if sidecar_missing:
            payload["error"] = "abec_sidecar_missing"
            return payload
        if sidecar_copy_errors:
            payload["error"] = "abec_sidecar_copy_failed"
            return payload
        payload["ok"] = True
        payload["bytes"] = int(target_abec.stat().st_size)
        payload["source_abec"] = str(source.resolve())
        payload["target_abec"] = str(target_abec.resolve())
        return payload
    except Exception as exc:
        payload["error"] = str(exc)
        payload["sync_log"] = str(logs_dir / "ath.abec_sync.json")
        return payload


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
    rows = _parse_abec_section_entries(abec_path, "observation")
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
        if "=" not in line:
            continue
        lhs, rhs = line.split("=", 1)
        lhs_token = str(lhs).strip().lower()
        if lhs_token != "scriptname_solving":
            continue
        if section not in {"project", "solving"}:
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
    solving_groups: List[str] = []
    observation_driving_groups: List[str] = []
    observation_radimp_pairs: List[List[str]] = []
    observation_radimp_groups: List[str] = []
    observation_has_radimp_section = False

    for path in solving_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in _extract_drvgroups_from_text(text):
            if token not in solving_groups:
                solving_groups.append(token)

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
    if not observation_has_radimp_section:
        violations.append("radimp_section_missing")
    if observation_has_radimp_section and not observation_radimp_pairs:
        violations.append("radimp_entries_missing")
    if expected:
        if expected not in solving_groups:
            violations.append("expected_drvgroup_missing_in_solving")
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
        "solving_drvgroups": solving_groups,
        "observation_driving_drvgroups": observation_driving_groups,
        "observation_radimp_pairs": observation_radimp_pairs,
        "observation_radimp_groups": observation_radimp_groups,
        "observation_has_radimp_section": observation_has_radimp_section,
    }


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


def _update_version_state(project_root: Path, version_id: str, updates: Dict[str, Any]) -> None:
    path = _version_json_path(project_root, version_id)
    payload = _read_json(path)
    payload.update(updates)
    _write_json(path, payload)


def _stage_from_result(version_id: str, stage: str, result: RunnerResult) -> StageExecution:
    return StageExecution(
        version_id=version_id,
        stage=stage,
        status="ok" if result.ok else "failed",
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        summary_log=result.summary_log,
    )


VACS_IMAGE_CANDIDATES: Tuple[str, ...] = ("vacsviewer_32.exe", "vacsviewer.exe")


def _list_process_ids_by_image(image_name: str) -> List[int]:
    target = str(image_name or "").strip().lower()
    if not target:
        return []
    try:
        cp = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {target}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []
    rows: List[int] = []
    for row in csv.reader(io.StringIO(str(cp.stdout or ""))):
        if not row or len(row) < 2:
            continue
        name = str(row[0] or "").strip().strip('"').lower()
        if name != target:
            continue
        try:
            rows.append(int(str(row[1] or "").strip().strip('"')))
        except Exception:
            continue
    return sorted(set(rows))


def _list_vacs_process_ids() -> List[int]:
    rows: List[int] = []
    for image in VACS_IMAGE_CANDIDATES:
        rows.extend(_list_process_ids_by_image(image))
    return sorted(set(rows))


def _terminate_process_ids(process_ids: Sequence[int]) -> Dict[str, Any]:
    requested = sorted({int(pid) for pid in process_ids if int(pid) > 0})
    terminated: List[int] = []
    failed: List[Dict[str, Any]] = []
    for pid in requested:
        try:
            cp = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            if int(cp.returncode) == 0:
                terminated.append(int(pid))
            else:
                failed.append(
                    {
                        "pid": int(pid),
                        "returncode": int(cp.returncode),
                        "stdout": str(cp.stdout or "")[:400],
                        "stderr": str(cp.stderr or "")[:400],
                    }
                )
        except Exception as exc:
            failed.append({"pid": int(pid), "error": str(exc)})
    return {"requested": requested, "terminated": terminated, "failed": failed}


def _run_akabak_ui_driver_stage(
    *,
    version_id: str,
    executable: str | Path,
    abec_project_path: Path,
    version_logs_dir: Path,
    require_vacs_graph_import: bool,
    akabak_solve_timeout_s: int = 600,
    preserve_vacs_for_export: bool = False,
) -> Tuple[StageExecution, Dict[str, Any], bool]:
    if AkabakDriver is None:
        raise RuntimeError("AkabakDriver unavailable (UI automation dependencies missing).")

    version_logs_dir.mkdir(parents=True, exist_ok=True)
    summary_log = version_logs_dir / "akabak.driver.summary.json"
    driver_log_dir = version_logs_dir / "akabak_driver"
    payload: Dict[str, Any] = {
        "mode": "uia_driver",
        "version_id": version_id,
        "abec_project_path": str(abec_project_path),
        "started_at": _now_iso(),
        "steps": {},
        "watchdog_events": [],
    }
    stage_ok = False
    timed_out = False
    error_text = ""
    driver = None
    vacs_before_stage = _list_vacs_process_ids()
    vacs_pre_cleanup = _terminate_process_ids(vacs_before_stage) if vacs_before_stage else {
        "requested": [],
        "terminated": [],
        "failed": [],
    }
    payload["vacs_cleanup"] = {
        "before_stage_pids": vacs_before_stage,
        "pre_stage": vacs_pre_cleanup,
    }
    try:
        driver = AkabakDriver(executable=str(executable), log_dir=driver_log_dir)
        opened = driver.open_project(abec_project_path)
        payload["steps"]["open_project"] = {"ok": bool(opened.ok), "status": str(opened.status)}

        imported = driver.import_if_needed()
        payload["steps"]["import_if_needed"] = {"ok": bool(imported.ok), "status": str(imported.status)}

        solve = driver.run_solve()
        payload["steps"]["run_solve"] = {"ok": bool(solve.ok), "status": str(solve.status)}

        timeout_s = max(1, int(akabak_solve_timeout_s))
        try:
            completed = driver.wait_for_completion(
                timeout_s=timeout_s,
                require_vacs_graph_import=bool(require_vacs_graph_import),
            )
        except TypeError:
            completed = driver.wait_for_completion(timeout_s=timeout_s)
        payload["steps"]["wait_for_completion"] = {"ok": bool(completed.ok), "status": str(completed.status)}
        stage_ok = True
    except TimeoutError as exc:
        timed_out = True
        error_text = str(exc)
    except Exception as exc:
        error_text = str(exc)
    finally:
        if driver is not None:
            try:
                closed = driver.close()
                payload["steps"]["close"] = {"ok": bool(closed.ok), "status": str(closed.status)}
            except Exception as exc:
                payload["steps"]["close"] = {"ok": False, "status": "failed", "error": str(exc)}
            payload["watchdog_events"] = list(getattr(driver, "watchdog_events", []) or [])
            payload["diagnostics"] = {
                "open_dialog": str(getattr(driver, "last_open_dialog_diagnostics_path", "") or ""),
                "import": str(getattr(driver, "last_import_diagnostics_path", "") or ""),
                "solve": str(getattr(driver, "last_solve_diagnostics_path", "") or ""),
            }
        vacs_after_stage = _list_vacs_process_ids()
        if preserve_vacs_for_export:
            vacs_post_cleanup = {
                "requested": [],
                "terminated": [],
                "failed": [],
                "skipped": True,
                "reason": "preserve_for_vacs_export",
            }
        else:
            vacs_post_cleanup = _terminate_process_ids(vacs_after_stage) if vacs_after_stage else {
                "requested": [],
                "terminated": [],
                "failed": [],
            }
        payload["vacs_cleanup"]["after_stage_pids"] = vacs_after_stage
        payload["vacs_cleanup"]["post_stage"] = vacs_post_cleanup
        payload["ok"] = bool(stage_ok)
        payload["timed_out"] = bool(timed_out)
        payload["finished_at"] = _now_iso()
        if error_text:
            payload["error"] = error_text
        _write_json(summary_log, payload)

    stage = StageExecution(
        version_id=version_id,
        stage="akabak",
        status="ok" if stage_ok else "failed",
        exit_code=0 if stage_ok else 1,
        timed_out=timed_out,
        summary_log=str(summary_log),
    )
    result_payload: Dict[str, Any] = {
        "mode": "uia_driver",
        "exit_code": 0 if stage_ok else 1,
        "timed_out": timed_out,
        "summary_log": str(summary_log),
    }
    if error_text:
        result_payload["error"] = error_text
    return stage, result_payload, stage_ok


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).lower()
    except Exception:
        return str(path).lower()


def _is_global_synced(result: Dict[str, Any] | None) -> bool:
    if not isinstance(result, dict):
        return True
    return bool(result.get("global_synced", True))


def _append_cleanup_skip(
    cleanup_results: List[Dict[str, Any]],
    *,
    version_id: str,
    run_cfg_path: Path,
    ath_export_dir: Optional[Path],
    reason: str,
) -> None:
    cleanup_results.append(
        {
            "version_id": version_id,
            "artifact": "cfg",
            "target": str(run_cfg_path),
            "deleted": False,
            "reason": reason,
        }
    )
    cleanup_results.append(
        {
            "version_id": version_id,
            "artifact": "ath_export_subdir",
            "target": str(ath_export_dir) if ath_export_dir is not None else "",
            "deleted": False,
            "reason": reason if ath_export_dir is not None else "ath_export_root_unset",
        }
    )


def _extract_export_contracts(
    *,
    exports_dir: Path,
    vacs_export_summary: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[Path]]:
    contracts: Dict[str, Dict[str, Any]] = {}
    expected_files: List[Path] = []
    if not isinstance(vacs_export_summary, dict):
        return contracts, expected_files
    rows = vacs_export_summary.get("exports")
    if not isinstance(rows, list):
        return contracts, expected_files

    for row in rows:
        if not isinstance(row, dict):
            continue
        output_path_raw = str(row.get("output_path", "") or "").strip()
        if not output_path_raw:
            continue
        output_path = Path(output_path_raw)
        if not output_path.is_absolute():
            output_path = exports_dir / output_path
        expected_files.append(output_path)
        spec = row.get("spec") if isinstance(row.get("spec"), dict) else {}
        entry = row.get("entry") if isinstance(row.get("entry"), dict) else {}
        contracts[_path_key(output_path)] = {
            "spec_id": str(spec.get("id", "") or ""),
            "graph_kind": str(spec.get("graph_kind", "") or str(entry.get("graph_kind", "") or "")).strip(),
            "variant": str(
                spec.get("variant")
                or entry.get("graph_variant")
                or entry.get("variant")
                or "default"
            ).strip()
            or "default",
            "spec": spec,
            "entry": entry,
            "plugin_id": row.get("plugin_id"),
            "details": row.get("details") if isinstance(row.get("details"), dict) else {},
        }
    return contracts, expected_files


def _graph_kind_mismatch(*, expected_kind: str, parsed_graph_type: str, parsed_export_meta: Dict[str, Any]) -> bool:
    expected = str(expected_kind or "").strip().lower()
    if not expected:
        return False

    metadata = parsed_export_meta.get("metadata")
    metadata_map = metadata if isinstance(metadata, dict) else {}
    hint = " ".join(
        [
            str(parsed_graph_type or ""),
            str(metadata_map.get("Data_LevelType", "") or ""),
            str(metadata_map.get("Data_Legend", "") or ""),
        ]
    ).lower()
    if not hint.strip():
        return False

    expected_tokens: Dict[str, Tuple[str, ...]] = {
        "spl": ("spl", "soundpressure", "spectrum"),
        "impedance": ("impedance", "radiation_impedance", "radiation impedance"),
        "imp": ("impedance", "radiation_impedance", "radiation impedance"),
        "polar": ("polar", "directivity"),
    }
    conflict_tokens: Dict[str, Tuple[str, ...]] = {
        "spl": ("impedance", "radiation_impedance", "radiation impedance"),
        "impedance": ("spl", "soundpressure", "spectrum"),
        "imp": ("spl", "soundpressure", "spectrum"),
    }
    positive = expected_tokens.get(expected, tuple())
    negative = conflict_tokens.get(expected, tuple())
    if any(token in hint for token in positive if token):
        return False
    return any(token in hint for token in negative if token)


def _parse_decimal(value: Any) -> Optional[float]:
    text = str(value or "").strip().replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _batch_export_specs(batch: Batch) -> List[Dict[str, Any]]:
    settings = getattr(batch, "sim_export_settings", None)
    if settings is None:
        return []
    if isinstance(settings, dict):
        payload = dict(settings)
    else:
        to_dict = getattr(settings, "to_dict", None)
        if not callable(to_dict):
            return []
        payload = dict(to_dict() or {})
    specs = payload.get("export_specs")
    if not isinstance(specs, list):
        return []
    return [item for item in specs if isinstance(item, dict)]


def _resolve_norm_angle_deg(
    *,
    batch: Batch,
    contract: Optional[Dict[str, Any]],
    metadata: Dict[str, Any],
) -> Tuple[Optional[float], Dict[str, Any]]:
    contract_row = contract if isinstance(contract, dict) else {}
    spec_payload = contract_row.get("spec") if isinstance(contract_row.get("spec"), dict) else {}
    spec_id = str(spec_payload.get("id", "") or contract_row.get("spec_id", "") or "").strip()
    options = spec_payload.get("options") if isinstance(spec_payload.get("options"), dict) else {}
    direct_value = _parse_decimal(options.get("norm_angle"))
    if direct_value is not None:
        return direct_value, {"source": "contract.spec.options.norm_angle", "spec_id": spec_id}

    batch_specs = _batch_export_specs(batch)
    if spec_id:
        for spec in batch_specs:
            if str(spec.get("id", "") or "").strip() != spec_id:
                continue
            spec_options = spec.get("options") if isinstance(spec.get("options"), dict) else {}
            from_batch = _parse_decimal(spec_options.get("norm_angle"))
            if from_batch is not None:
                return from_batch, {"source": "batch.export_specs.options.norm_angle", "spec_id": spec_id}

    polar_with_norm: List[Tuple[str, float]] = []
    for spec in batch_specs:
        graph_kind = str(spec.get("graph_kind", "") or "").strip().lower()
        if graph_kind != "polar":
            continue
        spec_options = spec.get("options") if isinstance(spec.get("options"), dict) else {}
        from_batch = _parse_decimal(spec_options.get("norm_angle"))
        if from_batch is None:
            continue
        polar_with_norm.append((str(spec.get("id", "") or "").strip(), from_batch))
    if len(polar_with_norm) == 1:
        spec_token, value = polar_with_norm[0]
        return value, {"source": "batch.single_polar_norm_angle", "spec_id": spec_token}

    for key, raw in metadata.items():
        key_token = str(key or "").strip().lower()
        if "norm" not in key_token or "angle" not in key_token:
            continue
        parsed = _parse_decimal(raw)
        if parsed is not None:
            return parsed, {"source": "header", "key": str(key)}

    return None, {"source": "none"}


def _is_polar_export_candidate(
    *,
    path: Path,
    metadata: Dict[str, Any],
    contract: Optional[Dict[str, Any]],
) -> Tuple[bool, Dict[str, Any]]:
    format_complex = str(metadata.get("Data_Format", "") or "").strip().lower() == "complex"
    has_angle_list = bool(str(metadata.get("Param_Coord_x2", "") or "").strip())
    has_orientation = bool(str(metadata.get("Param_Coord_x3", "") or "").strip())
    header_signal = format_complex and has_angle_list and has_orientation

    contract_kind = ""
    if isinstance(contract, dict):
        contract_kind = str(contract.get("graph_kind", "") or "").strip().lower()
    contract_signal = contract_kind == "polar"

    name_token = path.name.lower()
    filename_signal = ("mic_polar" in name_token) or ("mic polar" in name_token)

    return (
        bool(header_signal or contract_signal or filename_signal),
        {
            "header_signal": bool(header_signal),
            "contract_signal": bool(contract_signal),
            "filename_signal": bool(filename_signal),
            "contract_kind": contract_kind,
        },
    )


def _ingest_vacs_exports(
    *,
    writer: TidyDatasetWriter,
    project: Project,
    batch: Batch,
    run_id: str,
    version_id: str,
    exports_dir: Path,
    vacs_export_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    contracts, expected_contract_files = _extract_export_contracts(
        exports_dir=exports_dir,
        vacs_export_summary=vacs_export_summary,
    )
    missing_contract_files = [str(path) for path in expected_contract_files if not path.exists()]
    expected_contract_keys = {_path_key(path) for path in expected_contract_files}

    if expected_contract_files:
        export_files = sorted(path for path in expected_contract_files if path.exists() and path.is_file())
        ignored_files = sorted(
            str(path)
            for path in exports_dir.rglob("*.txt")
            if path.is_file() and _path_key(path) not in expected_contract_keys
        )
    else:
        export_files = sorted(path for path in exports_dir.rglob("*.txt") if path.is_file())
        ignored_files = []

    parse_errors: List[str] = []
    mapping_errors: List[str] = []
    rows: List[Dict[str, Any]] = []
    polar_measurements_written = 0
    polar_points_written = 0
    polar_duplicates_skipped = 0
    polar_warnings: List[str] = []
    write_results: List[Dict[str, Any]] = []
    mapped_file_count = 0

    for path in export_files:
        try:
            parsed = parse_vacs_txt_file(path)
        except ValueError as exc:
            parse_errors.append(f"{path}: {exc}")
            continue

        contract = contracts.get(_path_key(path))
        expected_kind = ""
        variant_from_contract = "default"
        if contract is not None:
            mapped_file_count += 1
            expected_kind = str(contract.get("graph_kind", "") or "").strip()
            variant_from_contract = str(contract.get("variant", "default") or "default")

        if expected_kind and _graph_kind_mismatch(
            expected_kind=expected_kind,
            parsed_graph_type=parsed.graph_type,
            parsed_export_meta=parsed.export_meta,
        ):
            mapping_errors.append(
                f"{path}: expected graph_kind '{expected_kind}', parsed hint '{parsed.graph_type}'"
            )
            continue

        metadata_raw = parsed.export_meta.get("metadata")
        metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
        is_polar_candidate, polar_detection = _is_polar_export_candidate(
            path=path,
            metadata=metadata,
            contract=contract,
        )

        polar_result = None
        if is_polar_candidate:
            try:
                polar_result = parse_polar_legacy_complex_txt(path)
            except PolarTxtParseError as exc:
                remediation = (
                    "Ensure VACS exports complex frequency-domain polar data "
                    "(Data_Format=Complex, Data_Domain=Frequency)."
                )
                reason = str(exc.reason)
                if str(exc.error_code) == "MISSING_HEADER":
                    missing_keys: List[str] = []
                    for key in ("Param_Coord_x2", "Param_Coord_x3"):
                        if not str(metadata.get(key, "") or "").strip():
                            missing_keys.append(key)
                    if missing_keys:
                        missing_text = ", ".join(missing_keys)
                        remediation = (
                            "Enable 'Export of Parameters' in VACS export settings; otherwise "
                            "Param_Coord_x2 / Param_Coord_x3 are missing from the TXT header."
                        )
                        reason = f"{exc.reason}; missing_header_keys={missing_text}"
                detail = f"; detail={exc.detail}" if getattr(exc, "detail", "") else ""
                parse_errors.append(
                    f"{path}: polar_parse_error[{exc.error_code}]: {reason}{detail}; remediation={remediation}"
                )
                raise PolarTxtParseError(
                    path=exc.path,
                    error_code=str(exc.error_code),
                    reason=f"{reason}; remediation={remediation}",
                    detail=str(exc.detail or ""),
                ) from exc

        graph_kind = expected_kind or parsed.graph_type
        file_rows: List[Dict[str, Any]] = []
        for series in parsed.series:
            variant = variant_from_contract
            metadata = parsed.export_meta.get("metadata")
            if isinstance(metadata, dict):
                metadata_variant = str(metadata.get("variant", metadata.get("Variant", "")) or "").strip()
                if not contract and metadata_variant:
                    variant = metadata_variant

            export_meta = dict(parsed.export_meta)
            if contract:
                export_meta["contract"] = {
                    "spec_id": contract.get("spec_id"),
                    "graph_kind": expected_kind,
                    "variant": variant_from_contract,
                    "plugin_id": contract.get("plugin_id"),
                    "spec": contract.get("spec", {}),
                    "entry": contract.get("entry", {}),
                    "details": contract.get("details", {}),
                }

            for point_index, point in enumerate(series.points):
                file_rows.append(
                    {
                        "project_id": project.project_id,
                        "batch_id": batch.batch_id,
                        "run_id": run_id,
                        "version_id": version_id,
                        "graph_type": parsed.graph_type,
                        "graph_kind": graph_kind,
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
                        "source_file": str(path),
                        "export_meta": export_meta,
                        "meta_json": export_meta,
                    }
                )
        rows.extend(file_rows)

        if polar_result is None:
            continue

        file_hash = _sha256_file(path)
        orientation_raw = polar_result.orientation_raw
        orientation = normalize_orientation_marker(orientation_raw)
        existing_polar_id = writer.find_polar_measurement_id(
            project_id=project.project_id,
            version_id=version_id,
            run_id=run_id,
            orientation=orientation,
            file_hash=file_hash,
        )
        if existing_polar_id:
            polar_duplicates_skipped += 1
            continue

        angles_deg = list(polar_result.angles_deg)
        diffs = [angles_deg[idx] - angles_deg[idx - 1] for idx in range(1, len(angles_deg))]
        angle_step_deg: Optional[float] = None
        if diffs:
            if max(diffs) - min(diffs) <= 1e-6:
                angle_step_deg = float(diffs[0])

        norm_angle_deg, norm_angle_policy = _resolve_norm_angle_deg(
            batch=batch,
            contract=contract,
            metadata=polar_result.metadata,
        )

        export_meta = dict(parsed.export_meta)
        export_meta["polar_import"] = {
            "file_hash": file_hash,
            "detection": polar_detection,
            "norm_angle_policy": norm_angle_policy,
            "orientation": {
                "normalized": orientation,
                "raw": orientation_raw,
            },
            "warnings": list(polar_result.warnings),
        }
        if contract:
            export_meta["contract"] = {
                "spec_id": contract.get("spec_id"),
                "graph_kind": expected_kind,
                "variant": variant_from_contract,
                "plugin_id": contract.get("plugin_id"),
                "spec": contract.get("spec", {}),
                "entry": contract.get("entry", {}),
                "details": contract.get("details", {}),
            }

        measurement_payload: Dict[str, Any] = {
            "project_id": project.project_id,
            "batch_id": batch.batch_id,
            "version_id": version_id,
            "run_id": run_id,
            "graph_id": None,
            "orientation": orientation,
            "orientation_raw": orientation_raw,
            "norm_angle_deg": norm_angle_deg,
            "data_level_type": str(polar_result.metadata.get("Data_LevelType", "") or ""),
            "data_base_unit": str(polar_result.metadata.get("Data_BaseUnit", "") or ""),
            "data_absc_unit": str(polar_result.metadata.get("Data_AbscUnit", "") or ""),
            "freq_min_hz": min(float(row.freq_hz) for row in polar_result.rows),
            "freq_max_hz": max(float(row.freq_hz) for row in polar_result.rows),
            "freq_count": len(polar_result.rows),
            "angle_min_deg": min(angles_deg),
            "angle_max_deg": max(angles_deg),
            "angle_step_deg": angle_step_deg,
            "angle_count": len(angles_deg),
            "angles_deg_json": json.dumps(angles_deg, ensure_ascii=False),
            "source_file": str(path),
            "file_hash": file_hash,
            "export_meta_json": json.dumps(export_meta, ensure_ascii=False, sort_keys=True),
            "created_at": _now_iso(),
        }

        polar_points: List[Dict[str, Any]] = []
        for freq_index, row_data in enumerate(polar_result.rows):
            for angle_index, angle_deg in enumerate(angles_deg):
                polar_points.append(
                    {
                        "freq_index": freq_index,
                        "angle_index": angle_index,
                        "freq_hz": float(row_data.freq_hz),
                        "angle_deg": float(angle_deg),
                        "re": float(row_data.re_values[angle_index]),
                        "im": float(row_data.im_values[angle_index]),
                    }
                )
        polar_write = writer.write_polar_measurement(
            measurement=measurement_payload,
            points=polar_points,
        )
        write_results.append(polar_write)
        polar_measurements_written += 1
        polar_points_written += int(polar_write.get("points_written", len(polar_points)))
        for warning in polar_result.warnings:
            polar_warnings.append(f"{path.name}: {warning}")

    write_result: Dict[str, Any] = {}
    if rows:
        write_result = writer.write_measurements(rows)
        write_results.append(write_result)

    if write_results:
        global_synced = all(bool(item.get("global_synced", True)) for item in write_results)
        queued_retries: List[int] = []
        for item in write_results:
            queued_retry = item.get("queued_retry")
            if queued_retry is not None:
                queued_retries.append(int(queued_retry))
            for queue_id in list(item.get("queued_retries", []) or []):
                queued_retries.append(int(queue_id))
        write_result = {
            "project_db_path": str(write_results[0].get("project_db_path", "")),
            "global_db_path": str(write_results[0].get("global_db_path", "")),
            "global_synced": global_synced,
            "queued_retry": queued_retries[-1] if queued_retries else None,
            "queued_retries": queued_retries,
            "legacy_rows_written": int(write_result.get("rows_written", 0) or 0),
            "polar_measurements_written": polar_measurements_written,
            "polar_points_written": polar_points_written,
        }

    return {
        "export_dir": str(exports_dir),
        "files_found": len(export_files),
        "contract_expected_files": len(expected_contract_files),
        "contract_mapped_files": mapped_file_count,
        "missing_contract_files": missing_contract_files,
        "ignored_unmapped_files": ignored_files,
        "rows_prepared": len(rows),
        "polar_measurements_written": polar_measurements_written,
        "polar_points_written": polar_points_written,
        "polar_duplicates_skipped": polar_duplicates_skipped,
        "polar_warnings": polar_warnings,
        "parse_errors": parse_errors,
        "mapping_errors": mapping_errors,
        "write_result": write_result,
    }


def run_batch_pipeline(
    project: Project,
    batch: Batch,
    *,
    projects_root: str | Path = "projects",
    library_root: str | Path | None = None,
    template_cfg_path: str | Path | None = None,
    ath_executable: str | Path | None = None,
    akabak_executable: str | Path | None = None,
    vacs_executable: str | Path | None = None,
    ath_base_args: Sequence[str] | None = None,
    akabak_base_args: Sequence[str] | None = None,
    vacs_base_args: Sequence[str] | None = None,
    akabak_solve_timeout_s: int = 600,
    continue_on_error: bool = True,
    dry_run: bool = False,
    run_id: Optional[str] = None,
    git_commit: Optional[str] = None,
    app_version: Optional[str] = "0.1-rebuild",
    settings_hash: Optional[str] = None,
    ath_export_root: str | Path | None = ATH_PREVIEW_EXPORT_ROOT,
) -> RuntimeSummary:
    effective_library_root: Path | None = None
    if library_root is not None:
        effective_library_root = Path(str(library_root)).expanduser().resolve()
    else:
        projects_root_path = Path(str(projects_root)).expanduser().resolve()
        if use_project_library_storage() and projects_root_path.name.lower() == "projects":
            effective_library_root = projects_root_path.parent
        else:
            effective_library_root = projects_root_path
    planning_summary = materialize_batch_plan(
        project=project,
        batch=batch,
        projects_root=projects_root,
        library_root=effective_library_root,
    )
    planned_version_ids = [str(version_id) for version_id in list(planning_summary.version_ids or [])]
    project_root = Path(planning_summary.project_root).expanduser().resolve()
    template_text, template_cfg_effective = _load_effective_template(
        template_cfg_path,
        ath_executable=ath_executable,
    )
    writer = TidyDatasetWriter(project_root, library_root=effective_library_root)
    effective_run_id = run_id or str(uuid.uuid4())
    ath_export_root_path: Optional[Path] = None
    if ath_export_root is not None:
        ath_export_root_path = Path(str(ath_export_root)).expanduser().resolve()

    bootstrap_sync_errors: List[str] = []
    create_run_result = writer.create_run(
        run_id=effective_run_id,
        project_id=project.project_id,
        batch_id=batch.batch_id,
        status="running",
        git_commit=git_commit,
        app_version=app_version,
        settings_hash=settings_hash,
    )
    if not _is_global_synced(create_run_result):
        bootstrap_sync_errors.append("create_run")
    write_run_versions_result = writer.write_run_versions(
        [
            {
                "run_id": effective_run_id,
                "version_id": version_id,
                "project_id": project.project_id,
                "batch_id": batch.batch_id,
                "status": "planned",
            }
            for version_id in planned_version_ids
        ]
    )
    if not _is_global_synced(write_run_versions_result):
        bootstrap_sync_errors.append("write_run_versions")

    sim_export_payload = batch.sim_export_settings.to_dict()
    export_specs = _resolve_export_specs(sim_export_payload)
    vacs_required = bool(export_specs)
    needs_abec_artifact = bool(akabak_executable) or vacs_required
    vacs_version = str(sim_export_payload.get("vacs_version", "default") or "default")
    vacs_base_args_list = list(vacs_base_args or [])
    akabak_ui_driver_enabled = (
        not dry_run
        and bool(akabak_executable)
        and not bool(list(akabak_base_args or []))
        and AkabakDriver is not None
    )

    ath_runner = None if dry_run or not ath_executable else AthRunner(ath_executable, base_args=ath_base_args)
    akabak_runner = (
        None
        if dry_run or not akabak_executable or akabak_ui_driver_enabled
        else AkabakRunner(akabak_executable, base_args=akabak_base_args)
    )
    vacs_runner = None if dry_run or not vacs_executable else VacsRunner(vacs_executable, base_args=vacs_base_args)

    stage_results: List[StageExecution] = []
    ath_dimension_rows = 0
    cleanup_results: List[Dict[str, Any]] = []
    if bootstrap_sync_errors:
        run_status = "failed"
        run_error_summary: Optional[str] = ", ".join(bootstrap_sync_errors)
    elif planned_version_ids:
        run_status = "succeeded"
        run_error_summary = None
    else:
        run_status = "noop"
        run_error_summary = "nothing_to_run:no_planned_versions"
    _append_run_debug_log(
        project_root,
        effective_run_id,
        event="run_start",
        payload={
            "run_id": effective_run_id,
            "project_id": project.project_id,
            "batch_id": batch.batch_id,
            "dry_run": bool(dry_run),
            "library_root": str(effective_library_root) if effective_library_root is not None else None,
            "project_root": str(project_root),
            "project_db_path": str(writer.project_db_path),
            "planned_versions": list(planned_version_ids),
            "planned_count": len(planned_version_ids),
        },
    )

    try:
        if not planned_version_ids and not bootstrap_sync_errors:
            _append_run_debug_log(
                project_root,
                effective_run_id,
                event="run_noop",
                payload={
                    "run_id": effective_run_id,
                    "reason": "no_planned_versions",
                },
            )
        for version_id in planned_version_ids:
            version_started = time.perf_counter()
            version_payload = _read_json(_version_json_path(project_root, version_id))
            version_params = dict(version_payload.get("parameters", {}) or {})
            runner_mode = str(batch.runner_mode or project.constraints.runner_mode)
            persist_sync_errors: List[str] = []
            version_logs_dir = _version_logs_dir(project_root, version_id)

            cfg_path = _version_cfg_path(project_root, version_id)
            cfg_basename = _runtime_cfg_basename(
                project_id=project.project_id,
                batch_id=batch.batch_id,
                version_id=version_id,
                run_id=effective_run_id,
            )
            run_cfg_path = _version_runtime_cfg_path(project_root, version_id, cfg_basename)
            ath_export_dir = _planned_ath_export_dir(ath_export_root_path, run_cfg_path)
            cfg_text = render_cfg_text(
                template_text=template_text,
                parameters=version_params,
                version_id=version_id,
                runner_mode=runner_mode,
            )
            cfg_text = _apply_sim_export_settings_to_cfg(
                cfg_text,
                sim_export_settings=sim_export_payload,
                export_specs=export_specs,
                runtime_parameters=version_params,
            )
            if needs_abec_artifact:
                cfg_text = _enforce_output_flag(cfg_text, key="Output.ABECProject", value=1)
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(cfg_text, encoding="utf-8")
            run_cfg_path.write_text(cfg_text, encoding="utf-8")
            _update_version_state(
                project_root,
                version_id,
                {
                    "run_id": effective_run_id,
                    "run_cfg_path": str(run_cfg_path),
                    "ath_export_dir": str(ath_export_dir) if ath_export_dir is not None else None,
                    "parameter_snapshot": version_params,
                    "constraints_snapshot": project.constraints.to_dict(),
                    "sweep_parameters_snapshot": dict(version_payload.get("sweep_parameters", {}) or {}),
                    "template_cfg_path_effective": template_cfg_effective,
                },
            )
            _append_stage_debug_log(
                version_logs_dir,
                event="version_runtime_prepared",
                payload={
                    "version_id": version_id,
                    "run_id": effective_run_id,
                    "project_id": project.project_id,
                    "batch_id": batch.batch_id,
                    "cfg_path": str(cfg_path),
                    "run_cfg_path": str(run_cfg_path),
                    "ath_export_dir": str(ath_export_dir) if ath_export_dir is not None else None,
                    "export_specs_count": len(export_specs),
                    "akabak_ui_driver_enabled": bool(akabak_ui_driver_enabled),
                },
            )

            def _track_sync(operation_name: str, result: Dict[str, Any] | None) -> None:
                if not _is_global_synced(result):
                    persist_sync_errors.append(operation_name)

            if dry_run:
                elapsed = time.perf_counter() - version_started
                stage_results.append(
                    StageExecution(
                        version_id=version_id,
                        stage="dry_run",
                        status="ok",
                        exit_code=0,
                        timed_out=False,
                        summary_log="dry_run",
                    )
                )
                _update_version_state(
                    project_root,
                    version_id,
                    {
                        "status": "dry_run_completed",
                        "dry_run": True,
                        "run_id": effective_run_id,
                        "finished_at": _now_iso(),
                        "duration_seconds": elapsed,
                    },
                )
                dry_status = writer.update_version_status(
                    version_id,
                    status="dry_run_completed",
                    run_id=effective_run_id,
                    duration_seconds=elapsed,
                    finished_at=_now_iso(),
                )
                _track_sync("update_version_status.dry_run_completed", dry_status)
                _append_cleanup_skip(
                    cleanup_results,
                    version_id=version_id,
                    run_cfg_path=run_cfg_path,
                    ath_export_dir=ath_export_dir,
                    reason="dry_run_no_delete",
                )
                continue

            ath_stage_ok = ath_runner is None
            akabak_stage_ok = not bool(akabak_executable)
            vacs_stage_ok = not vacs_required

            if ath_runner is not None:
                ath_work_dir = _version_ath_work_path(project_root, version_id)
                ath_work_dir.mkdir(parents=True, exist_ok=True)
                ath_work_cfg_path = ath_work_dir / run_cfg_path.name
                ath_work_cfg_path.write_text(cfg_text, encoding="utf-8")
                ath_runtime_cfg = _write_runtime_ath_cfg(
                    ath_work_dir=ath_work_dir,
                    ath_export_root=ath_export_root_path,
                    ath_executable=ath_executable,
                )
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_start",
                    payload={
                        "stage": "ath",
                        "version_id": version_id,
                        "workdir": str(ath_work_dir),
                        "cfg_path": str(ath_work_cfg_path),
                        "ath_runtime_cfg": ath_runtime_cfg,
                    },
                )
                ath_result = ath_runner.run_cfg(
                    ath_work_cfg_path,
                    version_logs_dir=version_logs_dir,
                    workdir=ath_work_dir,
                )
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_end",
                    payload={
                        "stage": "ath",
                        "version_id": version_id,
                        "ok": bool(ath_result.ok),
                        "exit_code": int(ath_result.exit_code),
                        "timed_out": bool(ath_result.timed_out),
                        "stdout_log": str(ath_result.stdout_log),
                        "stderr_log": str(ath_result.stderr_log),
                        "summary_log": str(ath_result.summary_log),
                    },
                )
                stage_results.append(_stage_from_result(version_id, "ath", ath_result))
                _update_version_state(
                    project_root,
                    version_id,
                    {
                        "status": "ath_ok" if ath_result.ok else "ath_failed",
                        "run_id": effective_run_id,
                        "ath_result": {
                            "exit_code": ath_result.exit_code,
                            "timed_out": ath_result.timed_out,
                            "stdout_log": ath_result.stdout_log,
                            "stderr_log": ath_result.stderr_log,
                            "summary_log": ath_result.summary_log,
                            "ath_work_cfg_path": str(ath_work_cfg_path),
                            "ath_runtime_cfg": ath_runtime_cfg,
                        },
                    },
                )
                ath_status = writer.update_version_status(
                    version_id,
                    status="ath_ok" if ath_result.ok else "ath_failed",
                    run_id=effective_run_id,
                )
                _track_sync("update_version_status.ath", ath_status)
                ath_stage_ok = ath_result.ok

                ath_stdout = Path(ath_result.stdout_log).read_text(encoding="utf-8")
                dims = parse_ath_dimensions(ath_stdout)
                # Persist final dimensions before downstream export/ingest stages.
                if None not in (dims.horn_length_mm, dims.horn_width_mm, dims.horn_height_mm):
                    raw_line = (
                        dims.raw_line
                        or (
                            f"Length={float(dims.horn_length_mm):.3f} "
                            f"Width={float(dims.horn_width_mm):.3f} "
                            f"Height={float(dims.horn_height_mm):.3f}"
                        )
                    )
                    dims_result = writer.write_ath_dimensions(
                        [
                            {
                                "project_id": project.project_id,
                                "batch_id": batch.batch_id,
                                "run_id": effective_run_id,
                                "version_id": version_id,
                                "horn_length_mm": dims.horn_length_mm,
                                "horn_width_mm": dims.horn_width_mm,
                                "horn_height_mm": dims.horn_height_mm,
                                "raw_line": raw_line,
                                "source_file": ath_result.stdout_log,
                            }
                        ]
                    )
                    _track_sync("write_ath_dimensions", dims_result)
                    ath_dimension_rows += 1

                ath_failure_reason = "ath_failed"
                if ath_result.ok and needs_abec_artifact:
                    abec_sync = _sync_generated_abec(
                        target_abec=_version_abec_path(project_root, version_id),
                        search_roots=tuple(
                            root
                            for root in (
                                ath_export_dir,
                                ath_work_dir,
                            )
                            if root is not None
                        ),
                        logs_dir=_version_logs_dir(project_root, version_id),
                    )
                    _update_version_state(project_root, version_id, {"ath_abec_sync": abec_sync})
                    if not bool(abec_sync.get("ok")):
                        ath_stage_ok = False
                        ath_failure_reason = "ath_abec_missing"
                        abec_sync_log = version_logs_dir / "ath.abec_sync.json"
                        _write_json(abec_sync_log, abec_sync)
                        _append_stage_debug_log(
                            version_logs_dir,
                            event="stage_end",
                            payload={
                                "stage": "ath_abec_sync",
                                "version_id": version_id,
                                "ok": False,
                                "error": "ath_abec_missing",
                                "summary_log": str(abec_sync_log),
                            },
                        )
                        stage_results.append(
                            StageExecution(
                                version_id=version_id,
                                stage="ath_abec_sync",
                                status="failed",
                                exit_code=1,
                                timed_out=False,
                                summary_log=str(abec_sync_log),
                            )
                        )

                if not ath_stage_ok and not continue_on_error:
                    elapsed = time.perf_counter() - version_started
                    failed_update = writer.update_version_status(
                        version_id,
                        status="failed",
                        run_id=effective_run_id,
                        duration_seconds=elapsed,
                        finished_at=_now_iso(),
                        error_summary=ath_failure_reason,
                    )
                    _track_sync("update_version_status.failed_ath", failed_update)
                    _append_cleanup_skip(
                        cleanup_results,
                        version_id=version_id,
                        run_cfg_path=run_cfg_path,
                        ath_export_dir=ath_export_dir,
                        reason="skipped_due_to_failure",
                    )
                    run_status = "failed"
                    continue

                if ath_stage_ok and (akabak_runner is not None or akabak_ui_driver_enabled or vacs_required):
                    _append_stage_debug_log(
                        version_logs_dir,
                        event="stage_start",
                        payload={
                            "stage": "post_ath_le_repair",
                            "version_id": version_id,
                            "abec_path": str(_version_abec_path(project_root, version_id)),
                        },
                    )
                    driver_sync = repair_post_ath_le_binding(
                        abec_path=_version_abec_path(project_root, version_id),
                        ath_executable=ath_executable,
                        diagnostics_dir=version_logs_dir,
                    )
                    _append_stage_debug_log(
                        version_logs_dir,
                        event="stage_end",
                        payload={
                            "stage": "post_ath_le_repair",
                            "version_id": version_id,
                            "ok": bool(driver_sync.ok),
                            "status": str(driver_sync.status),
                            "diagnostics_path": str(driver_sync.diagnostics_path or ""),
                        },
                    )
                    stage_results.append(
                        StageExecution(
                            version_id=version_id,
                            stage="post_ath_le_repair",
                            status="ok" if driver_sync.ok else "failed",
                            exit_code=0 if driver_sync.ok else 1,
                            timed_out=False,
                            summary_log=driver_sync.diagnostics_path or driver_sync.abec_path,
                        )
                    )
                    _update_version_state(
                        project_root,
                        version_id,
                        {
                            "le_driver_sync": driver_sync.to_dict(),
                        },
                    )
                    if not driver_sync.ok:
                        elapsed = time.perf_counter() - version_started
                        failed_update = writer.update_version_status(
                            version_id,
                            status="failed",
                            run_id=effective_run_id,
                            duration_seconds=elapsed,
                            finished_at=_now_iso(),
                            error_summary="post_ath_le_repair_failed",
                        )
                        _track_sync("update_version_status.failed_post_ath", failed_update)
                        _append_cleanup_skip(
                            cleanup_results,
                            version_id=version_id,
                            run_cfg_path=run_cfg_path,
                            ath_export_dir=ath_export_dir,
                            reason="skipped_due_to_failure",
                        )
                        run_status = "failed"
                        continue

                    if akabak_executable:
                        expected_drvgroup = str(
                            getattr(getattr(driver_sync, "driver_patch", None), "driver_drvgroup_value", "") or ""
                        ).strip() or None
                        le_contract = _assess_pre_akabak_le_driving_contract(
                            abec_path=_version_abec_path(project_root, version_id),
                            expected_drvgroup=expected_drvgroup,
                        )
                        le_contract_log = _version_logs_dir(project_root, version_id) / "pre_akabak_le_driving_contract.json"
                        _write_json(le_contract_log, le_contract)
                        stage_results.append(
                            StageExecution(
                                version_id=version_id,
                                stage="pre_akabak_le_driving_guard",
                                status="ok" if bool(le_contract.get("ok")) else "failed",
                                exit_code=0 if bool(le_contract.get("ok")) else 1,
                                timed_out=False,
                                summary_log=str(le_contract_log),
                            )
                        )
                        _update_version_state(
                            project_root,
                            version_id,
                            {
                                "pre_akabak_le_driving_contract": le_contract,
                            },
                        )
                        if not bool(le_contract.get("ok")):
                            elapsed = time.perf_counter() - version_started
                            failed_update = writer.update_version_status(
                                version_id,
                                status="failed",
                                run_id=effective_run_id,
                                duration_seconds=elapsed,
                                finished_at=_now_iso(),
                                error_summary="pre_akabak_le_driving_contract_failed",
                            )
                            _track_sync("update_version_status.failed_pre_akabak_le", failed_update)
                            _append_cleanup_skip(
                                cleanup_results,
                                version_id=version_id,
                                run_cfg_path=run_cfg_path,
                                ath_export_dir=ath_export_dir,
                                reason="skipped_due_to_failure",
                            )
                            run_status = "failed"
                            continue

                        mesh_guard = _parse_abec_mesh_requirements(_version_abec_path(project_root, version_id))
                        mesh_guard_ok = not bool(list(mesh_guard.get("missing_mesh_files", []) or []))
                        mesh_guard_log = _version_logs_dir(project_root, version_id) / "pre_akabak_mesh_artifacts.json"
                        _write_json(mesh_guard_log, mesh_guard)
                        stage_results.append(
                            StageExecution(
                                version_id=version_id,
                                stage="pre_akabak_mesh_guard",
                                status="ok" if mesh_guard_ok else "failed",
                                exit_code=0 if mesh_guard_ok else 1,
                                timed_out=False,
                                summary_log=str(mesh_guard_log),
                            )
                        )
                        _update_version_state(
                            project_root,
                            version_id,
                            {
                                "pre_akabak_mesh_guard": mesh_guard,
                            },
                        )
                        if not mesh_guard_ok:
                            elapsed = time.perf_counter() - version_started
                            failed_update = writer.update_version_status(
                                version_id,
                                status="failed",
                                run_id=effective_run_id,
                                duration_seconds=elapsed,
                                finished_at=_now_iso(),
                                error_summary="pre_akabak_mesh_artifact_missing",
                            )
                            _track_sync("update_version_status.failed_pre_akabak_mesh", failed_update)
                            _append_cleanup_skip(
                                cleanup_results,
                                version_id=version_id,
                                run_cfg_path=run_cfg_path,
                                ath_export_dir=ath_export_dir,
                                reason="skipped_due_to_failure",
                            )
                            run_status = "failed"
                            continue

            if ath_stage_ok and akabak_ui_driver_enabled and akabak_executable:
                preserve_vacs_for_export = bool(vacs_required and vacs_executable and export_specs)
                require_vacs_graph_import = bool(vacs_required)
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_start",
                    payload={
                        "stage": "akabak",
                        "version_id": version_id,
                        "mode": "uia_driver",
                        "abec_path": str(_version_abec_path(project_root, version_id)),
                        "preserve_vacs_for_export": bool(preserve_vacs_for_export),
                        "require_vacs_graph_import": bool(require_vacs_graph_import),
                        "timeout_s": int(akabak_solve_timeout_s),
                    },
                )
                akabak_stage, akabak_payload, akabak_stage_ok = _run_akabak_ui_driver_stage(
                    version_id=version_id,
                    executable=akabak_executable,
                    abec_project_path=_version_abec_path(project_root, version_id),
                    version_logs_dir=version_logs_dir,
                    require_vacs_graph_import=require_vacs_graph_import,
                    akabak_solve_timeout_s=akabak_solve_timeout_s,
                    preserve_vacs_for_export=preserve_vacs_for_export,
                )
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_end",
                    payload={
                        "stage": "akabak",
                        "version_id": version_id,
                        "mode": "uia_driver",
                        "ok": bool(akabak_stage_ok),
                        "status": str(akabak_stage.status),
                        "summary_log": str(akabak_stage.summary_log),
                        "exit_code": int(akabak_stage.exit_code),
                    },
                )
                stage_results.append(akabak_stage)
                _update_version_state(
                    project_root,
                    version_id,
                    {
                        "status": "akabak_ok" if akabak_stage_ok else "akabak_failed",
                        "run_id": effective_run_id,
                        "akabak_result": akabak_payload,
                    },
                )
                akabak_status = writer.update_version_status(
                    version_id,
                    status="akabak_ok" if akabak_stage_ok else "akabak_failed",
                    run_id=effective_run_id,
                )
                _track_sync("update_version_status.akabak", akabak_status)
                if not akabak_stage_ok and not continue_on_error:
                    elapsed = time.perf_counter() - version_started
                    failed_update = writer.update_version_status(
                        version_id,
                        status="failed",
                        run_id=effective_run_id,
                        duration_seconds=elapsed,
                        finished_at=_now_iso(),
                        error_summary="akabak_failed",
                    )
                    _track_sync("update_version_status.failed_akabak", failed_update)
                    _append_cleanup_skip(
                        cleanup_results,
                        version_id=version_id,
                        run_cfg_path=run_cfg_path,
                        ath_export_dir=ath_export_dir,
                        reason="skipped_due_to_failure",
                    )
                    run_status = "failed"
                    continue

            elif ath_stage_ok and akabak_runner is not None:
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_start",
                    payload={
                        "stage": "akabak",
                        "version_id": version_id,
                        "mode": "subprocess",
                        "abec_path": str(_version_abec_path(project_root, version_id)),
                        "timeout_s": max(1, int(akabak_solve_timeout_s)),
                    },
                )
                akabak_result = akabak_runner.run_project(
                    _version_abec_path(project_root, version_id),
                    version_logs_dir=version_logs_dir,
                    timeout_s=max(1, int(akabak_solve_timeout_s)),
                )
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_end",
                    payload={
                        "stage": "akabak",
                        "version_id": version_id,
                        "mode": "subprocess",
                        "ok": bool(akabak_result.ok),
                        "exit_code": int(akabak_result.exit_code),
                        "timed_out": bool(akabak_result.timed_out),
                        "summary_log": str(akabak_result.summary_log),
                    },
                )
                stage_results.append(_stage_from_result(version_id, "akabak", akabak_result))
                _update_version_state(
                    project_root,
                    version_id,
                    {
                        "status": "akabak_ok" if akabak_result.ok else "akabak_failed",
                        "run_id": effective_run_id,
                        "akabak_result": {
                            "exit_code": akabak_result.exit_code,
                            "timed_out": akabak_result.timed_out,
                            "summary_log": akabak_result.summary_log,
                        },
                    },
                )
                akabak_status = writer.update_version_status(
                    version_id,
                    status="akabak_ok" if akabak_result.ok else "akabak_failed",
                    run_id=effective_run_id,
                )
                _track_sync("update_version_status.akabak", akabak_status)
                akabak_stage_ok = akabak_result.ok
                if not akabak_result.ok and not continue_on_error:
                    elapsed = time.perf_counter() - version_started
                    failed_update = writer.update_version_status(
                        version_id,
                        status="failed",
                        run_id=effective_run_id,
                        duration_seconds=elapsed,
                        finished_at=_now_iso(),
                        error_summary="akabak_failed",
                    )
                    _track_sync("update_version_status.failed_akabak", failed_update)
                    _append_cleanup_skip(
                        cleanup_results,
                        version_id=version_id,
                        run_cfg_path=run_cfg_path,
                        ath_export_dir=ath_export_dir,
                        reason="skipped_due_to_failure",
                    )
                    run_status = "failed"
                    continue

            if ath_stage_ok and not akabak_stage_ok and vacs_required:
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_skipped",
                    payload={
                        "stage": "vacs",
                        "version_id": version_id,
                        "reason": "akabak_stage_failed",
                    },
                )

            elif ath_stage_ok and akabak_stage_ok and vacs_required and not vacs_executable:
                vacs_stage_ok = False
                summary_path = version_logs_dir / "vacs.export_pipeline.json"
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_start",
                    payload={
                        "stage": "vacs",
                        "version_id": version_id,
                        "mode": "export_specs",
                        "error": "vacs_executable_missing",
                    },
                )
                _write_json(
                    summary_path,
                    {
                        "error": "vacs_executable_missing",
                        "message": "VACS executable is required for configured export_specs.",
                        "remediation": "Configure vacs_exe in settings or remove export_specs for this batch.",
                    },
                )
                stage_results.append(
                    StageExecution(
                        version_id=version_id,
                        stage="vacs",
                        status="failed",
                        exit_code=1,
                        timed_out=False,
                        summary_log=str(summary_path),
                    )
                )
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_end",
                    payload={
                        "stage": "vacs",
                        "version_id": version_id,
                        "ok": False,
                        "error": "vacs_executable_missing",
                        "summary_log": str(summary_path),
                    },
                )
                _update_version_state(
                    project_root,
                    version_id,
                    {
                        "status": "vacs_failed",
                        "run_id": effective_run_id,
                        "vacs_result": {
                            "exit_code": 1,
                            "timed_out": False,
                            "summary_log": str(summary_path),
                            "error": "vacs_executable_missing",
                        },
                    },
                )
                vacs_status_result = writer.update_version_status(version_id, status="vacs_failed", run_id=effective_run_id)
                _track_sync("update_version_status.vacs_missing_exe", vacs_status_result)
                if not continue_on_error:
                    elapsed = time.perf_counter() - version_started
                    failed_update = writer.update_version_status(
                        version_id,
                        status="failed",
                        run_id=effective_run_id,
                        duration_seconds=elapsed,
                        finished_at=_now_iso(),
                        error_summary="vacs_executable_missing",
                    )
                    _track_sync("update_version_status.failed_vacs_missing_exe", failed_update)
                    _append_cleanup_skip(
                        cleanup_results,
                        version_id=version_id,
                        run_cfg_path=run_cfg_path,
                        ath_export_dir=ath_export_dir,
                        reason="skipped_due_to_failure",
                    )
                    run_status = "failed"
                    continue

            elif ath_stage_ok and akabak_stage_ok and vacs_executable and export_specs:
                exports_dir = _version_exports_dir(project_root, version_id, effective_run_id)
                exports_dir.mkdir(parents=True, exist_ok=True)
                vacs_summary_path = version_logs_dir / "vacs.export_pipeline.json"
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_start",
                    payload={
                        "stage": "vacs",
                        "version_id": version_id,
                        "mode": "export_specs",
                        "exports_dir": str(exports_dir),
                        "vacs_version": str(vacs_version),
                        "export_specs_count": len(export_specs),
                        "using_external_script": bool(akabak_ui_driver_enabled and akabak_executable),
                    },
                )
                try:
                    vacs_export_summary = run_vacs_export_specs(
                        executable=vacs_executable,
                        vacs_version=vacs_version,
                        project_id=project.project_id,
                        batch_id=batch.batch_id,
                        version_id=version_id,
                        abec_path=_version_abec_path(project_root, version_id),
                        export_specs=export_specs,
                        export_dir=exports_dir,
                        log_dir=_version_logs_dir(project_root, version_id),
                        akabak_executable=akabak_executable if akabak_ui_driver_enabled else None,
                        allow_graph_kind_fallback=True,
                    )
                    _write_json(vacs_summary_path, vacs_export_summary)
                    stage_results.append(
                        StageExecution(
                            version_id=version_id,
                            stage="vacs",
                            status="ok",
                            exit_code=0,
                            timed_out=False,
                            summary_log=str(vacs_summary_path),
                        )
                    )
                    vacs_ingest = _ingest_vacs_exports(
                        writer=writer,
                        project=project,
                        batch=batch,
                        run_id=effective_run_id,
                        version_id=version_id,
                        exports_dir=exports_dir,
                        vacs_export_summary=vacs_export_summary,
                    )
                    vacs_stage_ok = (
                        bool(vacs_export_summary.get("executed"))
                        and not bool(vacs_ingest.get("parse_errors"))
                        and not bool(vacs_ingest.get("mapping_errors"))
                        and not bool(vacs_ingest.get("missing_contract_files"))
                    )
                    if int(vacs_ingest.get("files_found", 0)) <= 0 or int(vacs_ingest.get("rows_prepared", 0)) <= 0:
                        vacs_stage_ok = False
                    _append_stage_debug_log(
                        version_logs_dir,
                        event="stage_end",
                        payload={
                            "stage": "vacs",
                            "version_id": version_id,
                            "mode": "export_specs",
                            "ok": bool(vacs_stage_ok),
                            "executed": bool(vacs_export_summary.get("executed")),
                            "export_count": int(vacs_export_summary.get("export_count", 0) or 0),
                            "files_found": int(vacs_ingest.get("files_found", 0) or 0),
                            "rows_prepared": int(vacs_ingest.get("rows_prepared", 0) or 0),
                            "parse_errors": int(len(list(vacs_ingest.get("parse_errors", []) or []))),
                            "mapping_errors": int(len(list(vacs_ingest.get("mapping_errors", []) or []))),
                            "missing_contract_files": int(
                                len(list(vacs_ingest.get("missing_contract_files", []) or []))
                            ),
                            "summary_log": str(vacs_summary_path),
                        },
                    )
                    vacs_status = "vacs_ok" if vacs_stage_ok else "vacs_failed"
                    _update_version_state(
                        project_root,
                        version_id,
                        {
                            "status": vacs_status,
                            "run_id": effective_run_id,
                            "vacs_result": {
                                "exit_code": 0,
                                "timed_out": False,
                                "summary_log": str(vacs_summary_path),
                            },
                            "vacs_export_ingest": vacs_ingest,
                            "vacs_export_pipeline": vacs_export_summary,
                        },
                    )
                    vacs_state_result = writer.update_version_status(version_id, status=vacs_status, run_id=effective_run_id)
                    _track_sync("update_version_status.vacs_export_specs", vacs_state_result)
                    write_result = vacs_ingest.get("write_result")
                    if int(vacs_ingest.get("rows_prepared", 0) or 0) > 0 and not _is_global_synced(
                        write_result if isinstance(write_result, dict) else None
                    ):
                        persist_sync_errors.append("write_measurements")
                except BaseException as exc:
                    if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
                        raise
                    vacs_stage_ok = False
                    error_text = _describe_stage_exception(exc)
                    _append_stage_debug_log(
                        version_logs_dir,
                        event="stage_end",
                        payload={
                            "stage": "vacs",
                            "version_id": version_id,
                            "mode": "export_specs",
                            "ok": False,
                            "error_type": type(exc).__name__,
                            "error": error_text,
                            "summary_log": str(vacs_summary_path),
                        },
                    )
                    _write_json(vacs_summary_path, {"error": error_text, "vacs_version": vacs_version})
                    stage_results.append(
                        StageExecution(
                            version_id=version_id,
                            stage="vacs",
                            status="failed",
                            exit_code=1,
                            timed_out=False,
                            summary_log=str(vacs_summary_path),
                        )
                    )
                    _update_version_state(
                        project_root,
                        version_id,
                        {
                            "status": "vacs_failed",
                            "run_id": effective_run_id,
                            "vacs_result": {
                                "exit_code": 1,
                                "timed_out": False,
                                "summary_log": str(vacs_summary_path),
                                "error": error_text,
                            },
                        },
                    )
                    vacs_failed_result = writer.update_version_status(
                        version_id,
                        status="vacs_failed",
                        run_id=effective_run_id,
                        error_summary=error_text,
                    )
                    _track_sync("update_version_status.vacs_failed", vacs_failed_result)
                    if not continue_on_error:
                        elapsed = time.perf_counter() - version_started
                        failed_update = writer.update_version_status(
                            version_id,
                            status="failed",
                            run_id=effective_run_id,
                            duration_seconds=elapsed,
                            finished_at=_now_iso(),
                            error_summary="vacs_export_failed",
                        )
                        _track_sync("update_version_status.failed_vacs_export", failed_update)
                        _append_cleanup_skip(
                            cleanup_results,
                            version_id=version_id,
                            run_cfg_path=run_cfg_path,
                            ath_export_dir=ath_export_dir,
                            reason="skipped_due_to_failure",
                        )
                        run_status = "failed"
                        continue

            elif ath_stage_ok and akabak_stage_ok and vacs_runner is not None and bool(vacs_base_args_list):
                exports_dir = _version_exports_dir(project_root, version_id, effective_run_id)
                exports_dir.mkdir(parents=True, exist_ok=True)
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_start",
                    payload={
                        "stage": "vacs",
                        "version_id": version_id,
                        "mode": "legacy_runner",
                        "exports_dir": str(exports_dir),
                        "base_args": list(vacs_base_args_list),
                    },
                )
                vacs_result = vacs_runner.run_export(
                    _version_abec_path(project_root, version_id),
                    version_logs_dir=version_logs_dir,
                    workdir=exports_dir,
                )
                stage_results.append(_stage_from_result(version_id, "vacs", vacs_result))
                vacs_stage_ok = vacs_result.ok
                vacs_ingest: Dict[str, Any] = {}
                if vacs_result.ok:
                    vacs_ingest = _ingest_vacs_exports(
                        writer=writer,
                        project=project,
                        batch=batch,
                        run_id=effective_run_id,
                        version_id=version_id,
                        exports_dir=exports_dir,
                    )
                    if (
                        int(vacs_ingest.get("files_found", 0)) <= 0
                        or int(vacs_ingest.get("rows_prepared", 0)) <= 0
                        or vacs_ingest.get("parse_errors")
                        or vacs_ingest.get("mapping_errors")
                    ):
                        vacs_stage_ok = False
                _append_stage_debug_log(
                    version_logs_dir,
                    event="stage_end",
                    payload={
                        "stage": "vacs",
                        "version_id": version_id,
                        "mode": "legacy_runner",
                        "ok": bool(vacs_stage_ok),
                        "runner_exit_code": int(vacs_result.exit_code),
                        "runner_timed_out": bool(vacs_result.timed_out),
                        "files_found": int(vacs_ingest.get("files_found", 0) or 0),
                        "rows_prepared": int(vacs_ingest.get("rows_prepared", 0) or 0),
                        "summary_log": str(vacs_result.summary_log),
                    },
                )
                vacs_status = "vacs_ok" if vacs_stage_ok else "vacs_failed"
                _update_version_state(
                    project_root,
                    version_id,
                    {
                        "status": vacs_status,
                        "run_id": effective_run_id,
                        "vacs_result": {
                            "exit_code": vacs_result.exit_code,
                            "timed_out": vacs_result.timed_out,
                            "summary_log": vacs_result.summary_log,
                        },
                        "vacs_export_ingest": vacs_ingest,
                    },
                )
                vacs_result_status = writer.update_version_status(version_id, status=vacs_status, run_id=effective_run_id)
                _track_sync("update_version_status.vacs_runner", vacs_result_status)
                if int(vacs_ingest.get("rows_prepared", 0) or 0) > 0:
                    write_result = vacs_ingest.get("write_result")
                    if not _is_global_synced(write_result if isinstance(write_result, dict) else None):
                        persist_sync_errors.append("write_measurements")

            elapsed = time.perf_counter() - version_started
            final_ok = ath_stage_ok and akabak_stage_ok and vacs_stage_ok and not persist_sync_errors
            final_status = "success" if final_ok else "failed"
            final_error = None if final_ok else ("global_sync_pending" if persist_sync_errors else "version_stage_failed")
            _update_version_state(
                project_root,
                version_id,
                {
                    "status": final_status,
                    "run_id": effective_run_id,
                    "finished_at": _now_iso(),
                    "duration_seconds": elapsed,
                    "persist_sync_errors": list(persist_sync_errors),
                },
            )
            final_result = writer.update_version_status(
                version_id,
                status=final_status,
                run_id=effective_run_id,
                duration_seconds=elapsed,
                finished_at=_now_iso(),
                error_summary=final_error,
            )
            if not _is_global_synced(final_result):
                persist_sync_errors.append("update_version_status.final")
                final_ok = False
                final_status = "failed"
                _update_version_state(
                    project_root,
                    version_id,
                    {
                        "status": "failed",
                        "persist_sync_errors": list(persist_sync_errors),
                    },
                )
                fallback_result = writer.update_version_status(
                    version_id,
                    status="failed",
                    run_id=effective_run_id,
                    duration_seconds=elapsed,
                    finished_at=_now_iso(),
                    error_summary="global_sync_pending",
                )
                _track_sync("update_version_status.fallback_failed", fallback_result)

            if final_ok:
                cfg_cleanup = guarded_delete_file_in_workspace(
                    run_cfg_path,
                    workspace_root=project_root,
                    expected_parent_name="cfg",
                    perform_delete=True,
                    deny_paths=(project_root, project_root.parent),
                )
                cleanup_results.append(
                    {
                        "version_id": version_id,
                        "artifact": "cfg",
                        "target": cfg_cleanup.target,
                        "deleted": cfg_cleanup.deleted,
                        "reason": cfg_cleanup.reason,
                    }
                )
                if ath_export_dir is not None and ath_export_root_path is not None:
                    export_cleanup = guarded_delete_tree(
                        ath_export_dir,
                        allowed_root=ath_export_root_path,
                        expected_dir_name=ath_export_dir.name,
                        perform_delete=True,
                        deny_paths=(ath_export_root_path, ath_export_root_path.parent),
                    )
                    cleanup_results.append(
                        {
                            "version_id": version_id,
                            "artifact": "ath_export_subdir",
                            "target": export_cleanup.target,
                            "deleted": export_cleanup.deleted,
                            "reason": export_cleanup.reason,
                        }
                    )
                else:
                    cleanup_results.append(
                        {
                            "version_id": version_id,
                            "artifact": "ath_export_subdir",
                            "target": str(ath_export_dir) if ath_export_dir is not None else "",
                            "deleted": False,
                            "reason": "ath_export_root_unset",
                        }
                    )
            else:
                reason = "persist_not_synced" if persist_sync_errors else "skipped_due_to_failure"
                _append_cleanup_skip(
                    cleanup_results,
                    version_id=version_id,
                    run_cfg_path=run_cfg_path,
                    ath_export_dir=ath_export_dir,
                    reason=reason,
                )
                run_status = "failed"
    except Exception as exc:
        run_status = "failed"
        run_error_summary = str(exc)
        raise
    finally:
        _append_run_debug_log(
            project_root,
            effective_run_id,
            event="run_end",
            payload={
                "run_id": effective_run_id,
                "status": str(run_status),
                "error_summary": run_error_summary,
                "stage_count": len(stage_results),
                "cleanup_count": len(cleanup_results),
            },
        )
        writer.update_run(
            effective_run_id,
            status=run_status,
            finished_at=_now_iso(),
            error_summary=run_error_summary,
        )

    return RuntimeSummary(
        run_id=effective_run_id,
        run_status=run_status,
        project_id=project.project_id,
        batch_id=batch.batch_id,
        project_root=str(project_root),
        versions=list(planned_version_ids),
        stage_results=stage_results,
        ath_dimension_rows=ath_dimension_rows,
        cleanup_results=cleanup_results,
        dry_run=dry_run,
    )
