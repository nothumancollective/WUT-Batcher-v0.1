"""Versioned VACS graph catalog mapping semantic specs to UI contracts/recipes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.export_specs import ExportSpec


@dataclass(frozen=True)
class GraphCatalogEntry:
    graph_kind: str
    variant: Optional[str]
    format: str
    recipe_id: str
    selectors: Dict[str, Any]
    export_dialog_signature: str
    supported_formats: List[str]
    options: Dict[str, Any]

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "GraphCatalogEntry":
        return cls(
            graph_kind=str(payload.get("graph_kind", "")).strip().lower(),
            variant=(str(payload.get("variant")).strip().lower() if payload.get("variant") else None),
            format=str(payload.get("format", "txt")).strip().lower(),
            recipe_id=str(payload.get("recipe_id", "")).strip(),
            selectors=dict(payload.get("selectors", {}) or {}),
            export_dialog_signature=str(payload.get("export_dialog_signature", "")).strip(),
            supported_formats=[str(item).strip().lower() for item in list(payload.get("supported_formats", []) or [])],
            options=dict(payload.get("options", {}) or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_kind": self.graph_kind,
            "variant": self.variant,
            "format": self.format,
            "recipe_id": self.recipe_id,
            "selectors": dict(self.selectors),
            "export_dialog_signature": self.export_dialog_signature,
            "supported_formats": list(self.supported_formats),
            "options": dict(self.options),
        }


def _catalog_path(*, catalog_root: str | Path, vacs_version: str) -> Path:
    root = Path(catalog_root)
    return root / str(vacs_version) / "graph_catalog.json"


def _fallback_catalog_path(*, catalog_root: str | Path) -> Path:
    return Path(catalog_root) / "default" / "graph_catalog.json"


def _load_catalog_payload(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Catalog payload must be object: {path}")
    return payload


def load_graph_catalog(*, vacs_version: str, catalog_root: str | Path = "ui_maps/vacs") -> Dict[str, Any]:
    path = _catalog_path(catalog_root=catalog_root, vacs_version=vacs_version)
    if not path.exists():
        fallback = _fallback_catalog_path(catalog_root=catalog_root)
        if not fallback.exists():
            raise FileNotFoundError(
                f"Graph catalog not found for VACS version '{vacs_version}'. "
                f"Expected {path} or fallback {fallback}."
            )
        path = fallback
    payload = _load_catalog_payload(path)
    payload["_path"] = str(path)
    return payload


def _entry_key(graph_kind: str, variant: Optional[str], format_name: str) -> Tuple[str, str, str]:
    return (
        str(graph_kind).strip().lower(),
        str(variant or "").strip().lower(),
        str(format_name).strip().lower(),
    )


def build_catalog_index(payload: Dict[str, Any]) -> Dict[Tuple[str, str, str], GraphCatalogEntry]:
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        return {}
    index: Dict[Tuple[str, str, str], GraphCatalogEntry] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        entry = GraphCatalogEntry.from_dict(item)
        if not entry.graph_kind or not entry.recipe_id:
            continue
        index[_entry_key(entry.graph_kind, entry.variant, entry.format)] = entry
    return index


def resolve_catalog_entry(index: Dict[Tuple[str, str, str], GraphCatalogEntry], spec: ExportSpec) -> Optional[GraphCatalogEntry]:
    exact = _entry_key(spec.graph_kind, spec.variant, spec.format)
    if exact in index:
        return index[exact]
    variantless = _entry_key(spec.graph_kind, None, spec.format)
    return index.get(variantless)


def discover_graph_catalog(
    *,
    vacs_version: str,
    output_root: str | Path = "ui_maps/vacs",
    recipes: Iterable[Dict[str, Any]] = (),
    inspect_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for recipe in recipes:
        if not isinstance(recipe, dict):
            continue
        graph_kind = str(recipe.get("graph_type", "")).strip().lower()
        recipe_id = str(recipe.get("recipe_id", "")).strip()
        if not graph_kind or not recipe_id:
            continue
        row = {
            "graph_kind": graph_kind,
            "variant": None,
            "format": "txt",
            "recipe_id": recipe_id,
            "selectors": {
                "window_signature": recipe.get("preconditions", {}).get("window_signature", "vacs_main_window"),
                "graph_open": recipe.get("preconditions", {}).get("graph_open", graph_kind),
            },
            "export_dialog_signature": "vacs_export_dialog",
            "supported_formats": ["txt"],
            "options": {"status": "TODO_verify_on_target_build"},
        }
        rows.append(row)

    payload = {
        "schema_version": "1.0",
        "vacs_version": vacs_version,
        "generated_by": "vacs discover-graphs",
        "inspect_summary": inspect_summary or {},
        "entries": rows,
    }
    path = _catalog_path(catalog_root=output_root, vacs_version=vacs_version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"catalog_path": str(path), "entry_count": len(rows), "payload": payload}
