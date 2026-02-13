"""Registry and resolution for VACS exporter plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.export_specs import ExportSpec
from app.vacs_exporters.base import VacsExporterPlugin
from app.vacs_exporters.builtin import builtin_plugins
from app.vacs_graph_catalog import GraphCatalogEntry


@dataclass
class VacsExporterRegistry:
    plugins: List[VacsExporterPlugin]

    @classmethod
    def with_builtin(cls) -> "VacsExporterRegistry":
        return cls(plugins=builtin_plugins())

    def resolve(self, spec: ExportSpec, entry: GraphCatalogEntry) -> VacsExporterPlugin | None:
        for plugin in self.plugins:
            if plugin.can_handle(spec, entry):
                return plugin
        return None
