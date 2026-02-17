"""Centralized UI hint generation for metadata-driven form fields."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping


def _source_refs(param: Mapping[str, Any]) -> str:
    refs: List[str] = []
    for source in list(param.get("sources", []) or []):
        if not isinstance(source, dict):
            continue
        section = str(source.get("section", "")).strip()
        quote_hint = str(source.get("quote-hint", "")).strip()
        if section:
            refs.append(section)
        if quote_hint:
            refs.append(quote_hint)
            break
    return refs[0] if refs else ""


def tooltip_for(param: Mapping[str, Any]) -> str:
    description = str(param.get("description", "")).strip()
    source_ref = _source_refs(param)
    if description and source_ref:
        return f"{description}\n\n{source_ref}"
    if source_ref:
        return source_ref
    return description


def placeholder_for(*, widget_kind: str, param: Mapping[str, Any]) -> str:
    kind = str(widget_kind)
    if kind == "list":
        return "v1, v2, v3, v4"
    if kind in {"float", "int", "ex", "text"}:
        return "0"
    return ""


def property_tooltip_for(property_schema: Mapping[str, Any]) -> str:
    meaning = property_schema.get("meaning")
    if isinstance(meaning, list):
        return ", ".join(str(item) for item in meaning if str(item).strip())
    if meaning is not None:
        return str(meaning).strip()
    return str(property_schema.get("note", "")).strip()


def property_placeholder_for(*, widget_kind: str, property_schema: Mapping[str, Any]) -> str:
    if str(widget_kind) == "list":
        length_raw = property_schema.get("length")
        meaning = property_schema.get("meaning")
        if isinstance(length_raw, int) and int(length_raw) == 4:
            if isinstance(meaning, list) and len(meaning) == 4:
                labels = ",".join(str(item) for item in meaning)
                return f"v1, v2, v3, v4 ({labels})"
            return "v1, v2, v3, v4"
        return "v1, v2, v3"
    return placeholder_for(widget_kind=widget_kind, param=property_schema)
