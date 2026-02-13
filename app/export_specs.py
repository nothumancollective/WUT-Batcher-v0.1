"""Semantic export specification model (tool-agnostic, UI-step free)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class ExportSpec:
    id: str
    tool: str
    graph_kind: str
    variant: Optional[str] = None
    format: str = "txt"
    options: Dict[str, Any] = field(default_factory=dict)
    output_name_template: str = "{version_id}_{graph_kind}.{format}"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ExportSpec":
        return cls(
            id=str(payload.get("id", "")).strip(),
            tool=str(payload.get("tool", "vacs")).strip().lower(),
            graph_kind=str(payload.get("graph_kind", "")).strip(),
            variant=(str(payload.get("variant")).strip() if payload.get("variant") is not None else None),
            format=str(payload.get("format", "txt")).strip().lower(),
            options=dict(payload.get("options", {}) or {}),
            output_name_template=str(
                payload.get("output_name_template", "{version_id}_{graph_kind}.{format}")
            ).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "graph_kind": self.graph_kind,
            "variant": self.variant,
            "format": self.format,
            "options": dict(self.options),
            "output_name_template": self.output_name_template,
        }

    def render_output_name(self, *, version_id: str, batch_id: str, project_id: str) -> str:
        values = {
            "project_id": project_id,
            "batch_id": batch_id,
            "version_id": version_id,
            "graph_kind": self.graph_kind,
            "variant": self.variant or "default",
            "format": self.format,
            "export_id": self.id,
        }
        template = self.output_name_template or "{version_id}_{graph_kind}.{format}"
        try:
            return template.format(**values)
        except Exception:
            return f"{version_id}_{self.id or self.graph_kind}.{self.format}"


def _from_legacy_exports(payload: Dict[str, Any]) -> List[ExportSpec]:
    exports = payload.get("exports")
    if not isinstance(exports, dict):
        return []
    rows: List[ExportSpec] = []
    for key, value in exports.items():
        if not isinstance(value, dict):
            continue
        if not bool(value.get("enabled", False)):
            continue
        rows.append(
            ExportSpec(
                id=f"legacy_{key}",
                tool="vacs",
                graph_kind=str(key),
                format="txt",
                options=dict(value.get("params", {}) or {}),
                output_name_template="{version_id}_{graph_kind}.{format}",
            )
        )
    return rows


def parse_export_specs(payload: Dict[str, Any]) -> List[ExportSpec]:
    specs_raw = payload.get("export_specs")
    specs: List[ExportSpec] = []
    if isinstance(specs_raw, list):
        for item in specs_raw:
            if not isinstance(item, dict):
                continue
            spec = ExportSpec.from_dict(item)
            if not spec.id or not spec.graph_kind:
                continue
            specs.append(spec)
    if specs:
        return specs
    return _from_legacy_exports(payload)


def dump_export_specs(specs: Iterable[ExportSpec]) -> List[Dict[str, Any]]:
    return [spec.to_dict() for spec in specs]
