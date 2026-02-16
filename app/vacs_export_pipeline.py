"""Execution pipeline for semantic ExportSpecs via VACS exporter plugins."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable, List

from app.export_specs import ExportSpec
from app.vacs_driver import VacsDriver
from app.vacs_exporters.registry import VacsExporterRegistry
from app.vacs_graph_catalog import build_catalog_index, load_graph_catalog, resolve_catalog_entry


class VacsExportPipelineError(RuntimeError):
    pass


def _graph_kind_tokens(kind: str) -> List[str]:
    key = str(kind or "").strip().lower()
    aliases = {
        "spl": ["spl", "spectrum", "polar"],
        "impedance": ["impedance", "radiation"],
        "imp": ["impedance", "radiation"],
        "polar": ["polar", "directivity"],
    }
    return aliases.get(key, [key] if key else [])


def _matches_graph_kind(*, graph_kind: str, title: str, path: str) -> bool:
    haystack = f"{title} {path}".lower()
    tokens = _graph_kind_tokens(graph_kind)
    if not tokens:
        return False
    return any(token in haystack for token in tokens)


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
    cmd = [
        sys.executable,
        str(script_path),
        "--mode",
        "fast",
        "--assume-vacs-ready",
        "--akabak-exe",
        str(akabak_executable),
        "--vacs-exe",
        str(executable),
        "--export-dir",
        str(export_dir),
        "--output-dir",
        str(output_dir),
        "--max-runtime-s",
        "240",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    stdout = str(proc.stdout or "").strip()
    stderr = str(proc.stderr or "").strip()
    if proc.returncode != 0:
        raise VacsExportPipelineError(
            f"external vacs export failed (rc={proc.returncode}): {stderr or stdout or 'no output'}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise VacsExportPipelineError(f"external vacs export returned invalid json: {exc}") from exc
    if not bool(payload.get("ok")):
        raise VacsExportPipelineError(f"external vacs export reported failure: {payload}")
    return payload


def _render_output_path(
    *,
    export_dir: Path,
    project_id: str,
    batch_id: str,
    version_id: str,
    spec: ExportSpec,
) -> Path:
    name = spec.render_output_name(project_id=project_id, batch_id=batch_id, version_id=version_id)
    return export_dir / name


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
        used_indices = set()
        exports: List[Dict[str, Any]] = []
        for spec in specs:
            output_path = _render_output_path(
                export_dir=export_root,
                project_id=project_id,
                batch_id=batch_id,
                version_id=version_id,
                spec=spec,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            match_index = None
            for index, row in enumerate(exported_files):
                if index in used_indices:
                    continue
                title = str((row.get("graph", {}) or {}).get("title", "") or "")
                source_path = str(row.get("path", "") or "")
                if _matches_graph_kind(graph_kind=spec.graph_kind, title=title, path=source_path):
                    match_index = index
                    break
            if match_index is None:
                raise VacsExportPipelineError(
                    f"external vacs export could not map graph_kind='{spec.graph_kind}' for spec '{spec.id}'"
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
