"""Base interfaces for VACS exporter plugins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Protocol

from app.export_specs import ExportSpec
from app.vacs_graph_catalog import GraphCatalogEntry


@dataclass(frozen=True)
class ExportContext:
    project_id: str
    batch_id: str
    version_id: str
    output_dir: Path
    log_dir: Path
    vacs_version: str


class VacsExporterPlugin(Protocol):
    plugin_id: str

    def can_handle(self, spec: ExportSpec, entry: GraphCatalogEntry) -> bool:
        ...

    def open_graph(self, driver: Any, spec: ExportSpec, entry: GraphCatalogEntry) -> None:
        ...

    def export(self, driver: Any, spec: ExportSpec, entry: GraphCatalogEntry, output_path: Path) -> Dict[str, Any]:
        ...

    def validate_output(self, output_path: Path, entry: GraphCatalogEntry) -> None:
        ...
