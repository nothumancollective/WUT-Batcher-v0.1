"""Built-in VACS exporter plugins for currently supported graphs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.export_specs import ExportSpec
from app.vacs_exporters.base import VacsExporterPlugin
from app.vacs_graph_catalog import GraphCatalogEntry


@dataclass
class _RecipeTxtExporter(VacsExporterPlugin):
    plugin_id: str
    supported_kinds: List[str]

    def can_handle(self, spec: ExportSpec, entry: GraphCatalogEntry) -> bool:
        if spec.format != "txt":
            return False
        if str(entry.format).lower() != "txt":
            return False
        return str(spec.graph_kind).lower() in {value.lower() for value in self.supported_kinds}

    def open_graph(self, driver: Any, spec: ExportSpec, entry: GraphCatalogEntry) -> None:
        graph_target = str(entry.selectors.get("graph_open") or spec.graph_kind)
        driver.open_graph(graph_target)

    def export(self, driver: Any, spec: ExportSpec, entry: GraphCatalogEntry, output_path: Path) -> Dict[str, Any]:
        profile: Dict[str, Any] = {
            "recipe_id": entry.recipe_id,
            "graph_type": spec.graph_kind,
            "output_file": str(output_path),
        }
        profile.update(dict(spec.options))
        result = driver.export_txt(profile)
        return {"driver_result": result.details, "output_file": str(output_path)}

    def validate_output(self, output_path: Path, entry: GraphCatalogEntry) -> None:
        pattern = str(entry.options.get("file_pattern") or "")
        if output_path.exists():
            return
        if pattern:
            matches = [item for item in output_path.parent.glob("*") if item.is_file()]
            if matches:
                return
        raise FileNotFoundError(f"Expected TXT export output does not exist: {output_path}")


def builtin_plugins() -> List[VacsExporterPlugin]:
    return [
        _RecipeTxtExporter(plugin_id="vacs_txt_spl", supported_kinds=["spl"]),
        _RecipeTxtExporter(plugin_id="vacs_txt_impedance", supported_kinds=["impedance", "imp"]),
    ]
