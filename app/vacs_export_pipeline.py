"""Execution pipeline for semantic ExportSpecs via VACS exporter plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.export_specs import ExportSpec
from app.vacs_driver import VacsDriver
from app.vacs_exporters.registry import VacsExporterRegistry
from app.vacs_graph_catalog import build_catalog_index, load_graph_catalog, resolve_catalog_entry


class VacsExportPipelineError(RuntimeError):
    pass


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
