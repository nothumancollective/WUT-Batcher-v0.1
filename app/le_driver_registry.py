"""Harness-side LE driver registry primitives (additive, non-production selector)."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LEDriverSpec:
    id: str
    driver_basename: str
    source_path: str
    default_voltage: float
    metadata: Dict[str, Any]

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "LEDriverSpec":
        return cls(
            id=str(payload.get("id") or "").strip(),
            driver_basename=str(payload.get("driver_basename") or "").strip(),
            source_path=str(payload.get("source_path") or "").strip(),
            default_voltage=float(payload.get("default_voltage", 1.0) or 1.0),
            metadata=dict(payload.get("metadata", {}) or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "driver_basename": self.driver_basename,
            "source_path": self.source_path,
            "default_voltage": float(self.default_voltage),
            "metadata": dict(self.metadata),
        }


def _registry_path(path: Optional[str | Path] = None) -> Path:
    if path is not None:
        return Path(str(path)).expanduser()
    return Path("app/knowledge/le/driver_registry.v1.json")


def load_le_driver_registry(path: Optional[str | Path] = None) -> List[LEDriverSpec]:
    registry_path = _registry_path(path)
    if not registry_path.exists():
        return []
    payload = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return []
    drivers = payload.get("drivers")
    if not isinstance(drivers, list):
        return []
    items: List[LEDriverSpec] = []
    for item in drivers:
        if not isinstance(item, dict):
            continue
        spec = LEDriverSpec.from_dict(item)
        if not spec.id or not spec.driver_basename:
            continue
        items.append(spec)
    return items

