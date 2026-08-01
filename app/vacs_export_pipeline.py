"""Execution pipeline for semantic ExportSpecs via VACS exporter plugins."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, Iterable, List

from app.export_specs import ExportSpec
from app.polar_txt_parser import normalize_orientation_marker
from app.vacs_driver import VacsDriver
from app.vacs_exporters.registry import VacsExporterRegistry
from app.vacs_graph_catalog import build_catalog_index, load_graph_catalog, resolve_catalog_entry


class VacsExportPipelineError(RuntimeError):
    pass


LEGACY_VACS_PATH_BUDGET = 240
LEGACY_WINDOWS_FILE_PATH_BUDGET = 259


def _bounded_export_filename(
    export_root: Path,
    desired_name: str,
    *,
    fallback_stem: str,
    path_budget: int = LEGACY_VACS_PATH_BUDGET,
) -> str:
    """Keep an export path below the budget of the component that will consume it."""

    desired = str(desired_name or "").strip() or "export.txt"
    budget = max(1, int(path_budget))
    if len(str(export_root / desired)) <= budget:
        return desired
    suffix = Path(desired).suffix or ".txt"
    digest = hashlib.sha256(desired.encode("utf-8", errors="replace")).hexdigest()[:8]
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(fallback_stem or "export")).strip("._") or "export"
    compact = f"{safe_stem}_{digest}{suffix}"
    if len(str(export_root / compact)) > budget:
        compact = f"x_{digest}{suffix}"
    if len(str(export_root / compact)) > budget:
        raise VacsExportPipelineError(
            f"VACS export directory is too long for the active path budget ({budget}): {export_root}"
        )
    return compact


def _graph_kind_tokens(kind: str) -> List[str]:
    key = str(kind or "").strip().lower()
    aliases = {
        "spl": ["spl", "spectrum", "polar"],
        "impedance": ["impedance", "radiation"],
        "imp": ["impedance", "radiation"],
        "polar": ["polar", "directivity"],
    }
    return aliases.get(key, [key] if key else [])


def _read_vacs_export_metadata(path: Path) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return metadata
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except Exception:
        return metadata
    for line in lines[:80]:
        stripped = str(line).strip()
        if not stripped or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key_norm = str(key).strip()
        if not key_norm:
            continue
        value_norm = str(value).strip().strip('"').strip("'")
        metadata[key_norm] = value_norm
        if key_norm == "Data":
            break
    return metadata


def _graph_kind_match_score(
    *,
    graph_kind: str,
    title: str,
    path: str,
    metadata: Dict[str, str] | None = None,
) -> int:
    key = str(graph_kind or "").strip().lower()
    if not key:
        return 0
    haystack = f"{title} {path}".lower()
    tokens = _graph_kind_tokens(graph_kind)
    score = 0
    for token in tokens:
        if token and token in haystack:
            score = max(score, 4)
    meta = {str(k).lower(): str(v).lower() for k, v in dict(metadata or {}).items()}
    level_type = str(meta.get("data_leveltype", "") or "")
    legend = str(meta.get("data_legend", "") or "")
    if key in {"impedance", "imp"}:
        if "impedance" in level_type or "radiation_impedance" in legend or "radiation impedance" in legend:
            score = max(score, 8)
        elif "soundpressure" in level_type:
            score = max(score, 0)
    elif key == "spl":
        if "soundpressure" in level_type:
            score = max(score, 8)
        elif "spl" in legend or "spectrum" in legend:
            score = max(score, 6)
    elif key == "polar":
        if "polar" in title.lower() or "polar" in legend:
            score = max(score, 6)
    return score


def _infer_graph_kind_for_any_mapping(
    *,
    title: str,
    path: str,
    metadata: Dict[str, str] | None = None,
) -> str:
    best_kind = ""
    best_score = 0
    for kind in ("impedance", "spl", "polar"):
        score = _graph_kind_match_score(
            graph_kind=kind,
            title=title,
            path=path,
            metadata=metadata,
        )
        if score > best_score:
            best_score = score
            best_kind = kind
    return best_kind


def _graph_kind_family(kind: str) -> str:
    token = str(kind or "").strip().lower()
    if token in {"spl", "polar", "directivity"}:
        return "sound_pressure"
    if token in {"imp", "impedance", "radiation_impedance"}:
        return "impedance"
    return token or "unknown"


def _missing_requested_graph_coverage(
    *,
    requested_specs: Iterable[ExportSpec],
    exports: Iterable[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    requested_counts: Dict[str, int] = {}
    exported_counts: Dict[str, int] = {}
    for spec in list(requested_specs or []):
        family = _graph_kind_family(spec.graph_kind)
        requested_counts[family] = int(requested_counts.get(family, 0)) + 1
    for row in list(exports or []):
        spec_payload = dict(row.get("spec", {}) or {})
        family = _graph_kind_family(str(spec_payload.get("graph_kind", "") or ""))
        exported_counts[family] = int(exported_counts.get(family, 0)) + 1
    missing: Dict[str, Dict[str, int]] = {}
    for family, required in requested_counts.items():
        available = int(exported_counts.get(family, 0))
        if available < int(required):
            missing[family] = {"required": int(required), "available": available}
    return missing


def _orientation_token_from_metadata(metadata: Dict[str, str] | None) -> str:
    raw = str((metadata or {}).get("Param_Coord_x3", "") or "").strip().strip("'").strip('"')
    if not raw:
        return ""
    try:
        numeric = float(raw)
    except Exception:
        return ""
    token = normalize_orientation_marker(numeric)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(token)).strip("._")


def _run_external_vacs_export_save_all(
    *,
    executable: str | Path,
    akabak_executable: str | Path,
    export_dir: Path,
    log_dir: Path,
) -> Dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "vacs_export_save_all.py"
    if not script_path.exists() or not script_path.is_file():
        raise VacsExportPipelineError(f"Missing script: {script_path}")
    output_dir = log_dir / "external_vacs_export_save_all"
    output_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wut_vacs_export_") as staging_dir_raw:
        staging_dir = Path(staging_dir_raw)
        cmd = [
            sys.executable,
            str(script_path),
            "--mode",
            "auto",
            "--assume-vacs-ready",
            "--akabak-exe",
            str(akabak_executable),
            "--vacs-exe",
            str(executable),
            "--export-dir",
            str(staging_dir),
            "--output-dir",
            str(output_dir),
            "--max-runtime-s",
            "240",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        stdout = str(proc.stdout or "").strip()
        stderr = str(proc.stderr or "").strip()
        payload: Dict[str, Any] | None = None
        parse_error: str = ""
        if stdout:
            try:
                loaded = json.loads(stdout)
                if isinstance(loaded, dict):
                    payload = loaded
                else:
                    parse_error = "external vacs export returned non-object json payload"
            except json.JSONDecodeError as exc:
                parse_error = str(exc)
        if proc.returncode != 0:
            failure_parts: List[str] = []
            if isinstance(payload, dict):
                payload_error = str(payload.get("error", "") or "").strip()
                if payload_error:
                    failure_parts.append(payload_error)
                summary_file = str(payload.get("summary_file", "") or "").strip()
                trace_file = str(payload.get("trace_file", "") or "").strip()
                if summary_file:
                    failure_parts.append(f"summary_file={summary_file}")
                if trace_file:
                    failure_parts.append(f"trace_file={trace_file}")
            elif parse_error:
                failure_parts.append(f"invalid_json={parse_error}")
            reason = " | ".join(failure_parts) or stderr or stdout or "no output"
            raise VacsExportPipelineError(
                f"external vacs export failed (rc={proc.returncode}): {reason}"
            )
        if payload is None:
            raise VacsExportPipelineError(
                f"external vacs export returned invalid json: {parse_error or 'missing output payload'}"
            )
        if not bool(payload.get("ok")):
            raise VacsExportPipelineError(f"external vacs export reported failure: {payload}")

        relocated: List[Dict[str, Any]] = []
        for index, row_raw in enumerate(list(payload.get("exported_files", []) or []), start=1):
            row = dict(row_raw or {})
            source = Path(str(row.get("path", "") or ""))
            if not source.exists() or not source.is_file():
                raise VacsExportPipelineError(f"external VACS staging file is missing: {source}")
            suffix = source.suffix or ".txt"
            target_name = _bounded_export_filename(
                export_dir,
                f"external_raw_{index:02d}{suffix}",
                fallback_stem=f"raw_{index:02d}",
                path_budget=LEGACY_WINDOWS_FILE_PATH_BUDGET,
            )
            target = export_dir / target_name
            shutil.copy2(source, target)
            row["staged_path"] = str(source)
            row["path"] = str(target)
            relocated.append(row)
        payload["exported_files"] = relocated
        payload["staging"] = {
            "used": True,
            "relocated_count": len(relocated),
            "dialog_path_budget": LEGACY_VACS_PATH_BUDGET,
            "final_path_budget": LEGACY_WINDOWS_FILE_PATH_BUDGET,
        }
        return payload


def _build_external_any_graph_exports(
    *,
    exported_files: Iterable[Dict[str, Any]],
    export_root: Path,
    version_id: str,
    requested_specs: Iterable[ExportSpec],
) -> List[Dict[str, Any]]:
    exports: List[Dict[str, Any]] = []
    requested_ids = [str(spec.id or "").strip() for spec in list(requested_specs or []) if str(spec.id or "").strip()]
    for index, row in enumerate(list(exported_files or []), start=1):
        source = Path(str(row.get("path", "") or "")).resolve()
        if not source.exists() or not source.is_file():
            continue
        title = str((row.get("graph", {}) or {}).get("title", "") or "").strip() or source.stem
        safe_title = re.sub(r"[^A-Za-z0-9_.-]+", "_", title).strip("._")
        if not safe_title:
            safe_title = f"graph_{index:02d}"
        metadata = _read_vacs_export_metadata(source)
        orientation_token = _orientation_token_from_metadata(metadata)
        suffix = f"_{orientation_token}" if orientation_token else ""
        desired_name = f"{version_id}_anygraph_{index:02d}_{safe_title}{suffix}.txt"
        output_path = export_root / _bounded_export_filename(
            export_root,
            desired_name,
            fallback_stem=f"{version_id}_anygraph_{index:02d}",
            path_budget=LEGACY_WINDOWS_FILE_PATH_BUDGET,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        inferred_kind = _infer_graph_kind_for_any_mapping(
            title=title,
            path=str(source),
            metadata=metadata,
        )
        inferred_variant = f"external_{index:02d}"
        exports.append(
            {
                "spec": {
                    "id": f"external_any_{index:02d}",
                    "tool": "vacs",
                    "graph_kind": inferred_kind,
                    "variant": inferred_variant,
                    "format": "txt",
                },
                "entry": {"graph_kind": inferred_kind, "graph_variant": inferred_variant, "format": "txt"},
                "plugin_id": "external_vacs_export_save_all",
                "output_path": str(output_path),
                "details": {
                    "source_file": str(source),
                    "source_title": title,
                    "source_data_level_type": str(metadata.get("Data_LevelType", "") or ""),
                    "source_data_legend": str(metadata.get("Data_Legend", "") or ""),
                    "inferred_graph_kind": inferred_kind,
                    "source_orientation_token": orientation_token,
                    "mapping_mode": "any_graph",
                    "requested_spec_ids": requested_ids,
                    "bytes": int(source.stat().st_size),
                },
            }
        )
    return exports


def _render_output_path(
    *,
    export_dir: Path,
    project_id: str,
    batch_id: str,
    version_id: str,
    spec: ExportSpec,
    path_budget: int = LEGACY_VACS_PATH_BUDGET,
) -> Path:
    name = spec.render_output_name(project_id=project_id, batch_id=batch_id, version_id=version_id)
    bounded_name = _bounded_export_filename(
        export_dir,
        name,
        fallback_stem=f"{version_id}_{spec.id or spec.graph_kind or 'export'}",
        path_budget=path_budget,
    )
    return export_dir / bounded_name


def run_vacs_export_specs(
    *,
    executable: str | Path,
    vacs_version: str,
    project_id: str,
    batch_id: str,
    version_id: str,
    abec_path: str | Path,
    export_specs: Iterable[ExportSpec],
    export_dir: str | Path,
    log_dir: str | Path,
    catalog_root: str | Path = "ui_maps/vacs",
    akabak_executable: str | Path | None = None,
    allow_graph_kind_fallback: bool = False,
) -> Dict[str, Any]:
    specs = [spec for spec in list(export_specs) if str(spec.tool).lower() == "vacs"]
    if not specs:
        return {"executed": False, "reason": "no_vacs_export_specs", "exports": []}

    payload = load_graph_catalog(vacs_version=vacs_version, catalog_root=catalog_root)
    index = build_catalog_index(payload)
    registry = VacsExporterRegistry.with_builtin()
    export_root = Path(export_dir)
    export_root.mkdir(parents=True, exist_ok=True)
    log_root = Path(log_dir)
    log_root.mkdir(parents=True, exist_ok=True)

    if akabak_executable:
        external = _run_external_vacs_export_save_all(
            executable=executable,
            akabak_executable=akabak_executable,
            export_dir=export_root,
            log_dir=log_root,
        )
        exported_files = list(external.get("exported_files", []) or [])
        if allow_graph_kind_fallback:
            exports = _build_external_any_graph_exports(
                exported_files=exported_files,
                export_root=export_root,
                version_id=version_id,
                requested_specs=specs,
            )
            if not exports:
                raise VacsExportPipelineError("external vacs export produced no usable graph files")
            missing_coverage = _missing_requested_graph_coverage(
                requested_specs=specs,
                exports=exports,
            )
            if missing_coverage:
                raise VacsExportPipelineError(
                    "external vacs export did not cover all requested graph families: "
                    f"{json.dumps(missing_coverage, sort_keys=True)}"
                )
            return {
                "executed": True,
                "catalog_path": None,
                "driver": {
                    "process_id": None,
                    "backend": "external_script",
                    "started_process": False,
                    "external_run_id": external.get("run_id"),
                    "external_mode": str(external.get("mode", "") or ""),
                    "external_fallback_used": bool(external.get("fallback_used", False)),
                    "external_fallback_reason": str(external.get("fallback_reason", "") or ""),
                },
                "export_count": len(exports),
                "exports": exports,
                "external_export_summary_file": external.get("summary_file"),
                "mapping_mode": "any_graph",
            }
        used_indices = set()
        exports: List[Dict[str, Any]] = []
        metadata_cache: Dict[int, Dict[str, str]] = {}
        signatures: List[Dict[str, Any]] = []
        for index, row in enumerate(exported_files):
            source = Path(str(row.get("path", "") or "")).resolve()
            metadata = _read_vacs_export_metadata(source)
            metadata_cache[index] = metadata
            signatures.append(
                {
                    "index": int(index),
                    "title": str((row.get("graph", {}) or {}).get("title", "") or ""),
                    "path": str(source),
                    "data_level_type": str(metadata.get("Data_LevelType", "") or ""),
                    "data_legend": str(metadata.get("Data_Legend", "") or ""),
                }
            )
        for spec in specs:
            output_path = _render_output_path(
                export_dir=export_root,
                project_id=project_id,
                batch_id=batch_id,
                version_id=version_id,
                spec=spec,
                path_budget=LEGACY_WINDOWS_FILE_PATH_BUDGET,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            match_index = None
            best_score = -1
            for index, row in enumerate(exported_files):
                if index in used_indices:
                    continue
                title = str((row.get("graph", {}) or {}).get("title", "") or "")
                source_path = str(row.get("path", "") or "")
                score = _graph_kind_match_score(
                    graph_kind=spec.graph_kind,
                    title=title,
                    path=source_path,
                    metadata=metadata_cache.get(index),
                )
                if score > best_score:
                    best_score = score
                    match_index = index
            if match_index is None or best_score <= 0:
                available = [
                    {
                        **row,
                        "suggested_score": _graph_kind_match_score(
                            graph_kind=spec.graph_kind,
                            title=str(row.get("title", "") or ""),
                            path=str(row.get("path", "") or ""),
                            metadata={
                                "Data_LevelType": str(row.get("data_level_type", "") or ""),
                                "Data_Legend": str(row.get("data_legend", "") or ""),
                            },
                        ),
                    }
                    for row in signatures
                ]
                raise VacsExportPipelineError(
                    "external vacs export could not map "
                    f"graph_kind='{spec.graph_kind}' for spec '{spec.id}'. "
                    f"available_graphs={json.dumps(available, ensure_ascii=False)}"
                )
            used_indices.add(match_index)
            row = exported_files[match_index]
            source = Path(str(row.get("path", "") or "")).resolve()
            if not source.exists() or not source.is_file():
                raise VacsExportPipelineError(f"external vacs export missing source file: {source}")
            shutil.copy2(source, output_path)
            exports.append(
                {
                    "spec": spec.to_dict(),
                    "entry": {"graph_kind": spec.graph_kind, "graph_variant": spec.variant, "format": spec.format},
                    "plugin_id": "external_vacs_export_save_all",
                    "output_path": str(output_path),
                    "details": {
                        "source_file": str(source),
                        "source_title": str((row.get("graph", {}) or {}).get("title", "") or ""),
                        "source_data_level_type": str(
                            metadata_cache.get(match_index, {}).get("Data_LevelType", "") or ""
                        ),
                        "source_data_legend": str(
                            metadata_cache.get(match_index, {}).get("Data_Legend", "") or ""
                        ),
                        "mapping_score": int(best_score),
                        "bytes": int(Path(source).stat().st_size),
                    },
                }
            )
        return {
            "executed": True,
            "catalog_path": None,
            "driver": {
                "process_id": None,
                "backend": "external_script",
                "started_process": False,
                "external_run_id": external.get("run_id"),
                "external_mode": str(external.get("mode", "") or ""),
                "external_fallback_used": bool(external.get("fallback_used", False)),
                "external_fallback_reason": str(external.get("fallback_reason", "") or ""),
            },
            "export_count": len(exports),
            "exports": exports,
            "external_export_summary_file": external.get("summary_file"),
        }

    driver = VacsDriver(
        executable=executable,
        log_dir=log_root,
    )
    exports: List[Dict[str, Any]] = []
    driver_meta: Dict[str, Any] = {}
    try:
        driver.open_results(abec_path)
        session = getattr(driver, "session", None)
        driver_meta = {
            "process_id": getattr(session, "process_id", None),
            "backend": getattr(session, "backend", None),
            "started_process": bool(getattr(session, "started_process", False)),
        }
        for spec in specs:
            entry = resolve_catalog_entry(index, spec)
            if entry is None:
                raise VacsExportPipelineError(
                    "Unmapped VACS ExportSpec: "
                    f"{spec.id} ({spec.graph_kind}/{spec.variant or 'default'}/{spec.format}). "
                    "Remediation: run `python -m app vacs discover-graphs --vacs-version <version>` "
                    "and update ui_maps/vacs/<version>/graph_catalog.json."
                )
            plugin = registry.resolve(spec, entry)
            if plugin is None:
                raise VacsExportPipelineError(
                    "No VACS exporter plugin can handle spec "
                    f"{spec.id} ({spec.graph_kind}/{spec.format}). "
                    "Remediation: add mapping/plugin in app/vacs_exporters."
                )
            output_path = _render_output_path(
                export_dir=export_root,
                project_id=project_id,
                batch_id=batch_id,
                version_id=version_id,
                spec=spec,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            plugin.open_graph(driver, spec, entry)
            details = plugin.export(driver, spec, entry, output_path)
            plugin.validate_output(output_path, entry)
            exports.append(
                {
                    "spec": spec.to_dict(),
                    "entry": entry.to_dict(),
                    "plugin_id": getattr(plugin, "plugin_id", plugin.__class__.__name__),
                    "output_path": str(output_path),
                    "details": details,
                }
            )
    finally:
        driver.close()

    return {
        "executed": True,
        "catalog_path": payload.get("_path"),
        "driver": driver_meta,
        "export_count": len(exports),
        "exports": exports,
    }
