"""Loader for ATH geometry catalog/ruleset artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class AthKnowledgeBundle:
    catalog: Dict[str, Any]
    ruleset: Dict[str, Any]
    catalog_version: str
    ruleset_version: str


def _knowledge_root() -> Path:
    return Path(__file__).resolve().parent / "knowledge" / "ath"


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Knowledge file is not a JSON object: {path}")
    return payload


@lru_cache(maxsize=1)
def load_ath_knowledge() -> AthKnowledgeBundle:
    root = _knowledge_root()
    catalog_path = root / "catalog.v1.json"
    ruleset_path = root / "ruleset.v1.json"

    if not catalog_path.exists():
        raise FileNotFoundError(f"Missing ATH catalog: {catalog_path}")
    if not ruleset_path.exists():
        raise FileNotFoundError(f"Missing ATH ruleset: {ruleset_path}")

    catalog = _load_json(catalog_path)
    ruleset = _load_json(ruleset_path)
    return AthKnowledgeBundle(
        catalog=catalog,
        ruleset=ruleset,
        catalog_version=str(catalog.get("catalog_version", "unknown")),
        ruleset_version=str(ruleset.get("ruleset_version", "unknown")),
    )
