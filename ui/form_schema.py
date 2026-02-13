"""Metadata-driven schema for project parameter forms."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.ath_knowledge import AthKnowledgeBundle, load_ath_knowledge
from ui.hints import placeholder_for, property_placeholder_for, property_tooltip_for, tooltip_for


_COND_EQ_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*==\s*(-?\d+)\s*$")
_SHOW_ACTION_RE = re.compile(r"^show\(([^)]+)\)$")
_UNIT_OVERRIDES: Dict[str, str] = {
    "Throat.Angle": "deg/2",
    "Throat.Ext.Angle": "deg/2",
    "Coverage.Angle": "deg/2",
    "R-OSSE.a0": "deg/2",
    "R-OSSE.a": "deg/2",
}


@dataclass(frozen=True)
class EnumSpec:
    label: str
    value: Any


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    widget_kind: str
    ath_type: str = ""
    default: Any = None
    decimals: int = 2
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    unit: Optional[str] = None
    tooltip: str = ""
    placeholder: str = ""
    group_path: Tuple[str, ...] = ("Geometry", "Basics")
    order: int = 0
    ui_mode_tags: Tuple[str, ...] = ()
    advanced: bool = False
    scope: str = "fixed_params"
    enum_options: Tuple[EnumSpec, ...] = ()
    object_properties: Tuple["FieldSpec", ...] = ()
    object_parent_key: Optional[str] = None


@dataclass(frozen=True)
class ModePageSpec:
    value: Optional[int]
    label: str
    field_keys: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ModeStackSpec:
    controller_key: str
    label: str
    pages: Tuple[ModePageSpec, ...]


@dataclass(frozen=True)
class FormSchema:
    fields: Tuple[FieldSpec, ...]
    mode_stacks: Tuple[ModeStackSpec, ...] = ()

    def by_key(self) -> Dict[str, FieldSpec]:
        return {field.key: field for field in self.fields}

    def keys(self) -> List[str]:
        return [field.key for field in self.fields]


def _clean_unit(raw: Any) -> Optional[str]:
    value = str(raw or "").strip()
    if not value:
        return None
    return value


def _unit_for_key(key: str, raw: Any) -> Optional[str]:
    override = _UNIT_OVERRIDES.get(key)
    if override:
        return override
    return _clean_unit(raw)


def _title_from_key(key: str) -> str:
    parts = [part for part in re.split(r"[._-]+", key) if part]
    if not parts:
        return key
    return " ".join(parts).strip()


def _field_label(param: Mapping[str, Any], fallback_key: str) -> str:
    label = str(param.get("label", "")).strip()
    if label:
        return label
    return _title_from_key(fallback_key)


def _numeric_limits(param: Mapping[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    domain = param.get("domain")
    if not isinstance(domain, dict):
        return (None, None)
    min_value = domain.get("min")
    max_value = domain.get("max")
    try:
        minimum = float(min_value) if min_value is not None else None
    except (TypeError, ValueError):
        minimum = None
    try:
        maximum = float(max_value) if max_value is not None else None
    except (TypeError, ValueError):
        maximum = None
    return (minimum, maximum)


def _enum_options(param: Mapping[str, Any]) -> Tuple[EnumSpec, ...]:
    domain = param.get("domain")
    if not isinstance(domain, dict):
        return ()
    values = domain.get("enum")
    if not isinstance(values, list):
        return ()
    meaning = domain.get("meaning")
    meaning_map = meaning if isinstance(meaning, dict) else {}
    options: List[EnumSpec] = []
    for raw in values:
        label = str(meaning_map.get(str(raw), _title_from_key(str(raw)))).strip()
        options.append(EnumSpec(label=label, value=raw))
    return tuple(options)


def _scope_for_key(key: str) -> str:
    if key.startswith("Mesh."):
        return "limits"
    return "fixed_params"


def _group_path_for_key(key: str, catalog_group: str) -> Tuple[str, ...]:
    if key.startswith("Mesh."):
        if key.startswith("Mesh.Enclosure") or key == "Mesh.InterfaceOffset":
            return ("Mesh", "Enclosure")
        return ("Mesh", "Core")
    if key.startswith("Morph."):
        return ("Geometry", "Morph")
    if key.startswith("Rollback"):
        return ("Geometry", "Rollback")
    if key.startswith("GCurve.") or key == "Coverage.Angle":
        return ("Geometry", "GCurve")
    if key.startswith("CircArc.") or key.startswith("Term.") or key.startswith("OS.k") or key.startswith("R-OSSE"):
        return ("Geometry", "Throat Profile")
    return ("Geometry", "Basics")


def _widget_kind_for_type(raw_type: str) -> str:
    mapping = {
        "float": "float",
        "int": "int",
        "bool": "bool",
        "enum": "enum",
        "expr": "ex",
        "string": "text",
        "list<float>": "list",
        "list<int>": "list",
        "object": "object",
    }
    return mapping.get(str(raw_type), "text")


def _is_advanced(key: str, widget_kind: str) -> bool:
    if widget_kind in {"list", "object"}:
        return True
    tokens = ("Subdomain", "Interface", "ZMap", ".SF.")
    return any(token in key for token in tokens)


def _catalog_index(bundle: AthKnowledgeBundle) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for item in bundle.catalog.get("parameters", []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        if key:
            result[key] = item
    return result


def _rule_visibility_map(bundle: AthKnowledgeBundle) -> Dict[str, Dict[int, set[str]]]:
    by_controller: Dict[str, Dict[int, set[str]]] = {}
    rules = bundle.ruleset.get("rules", [])
    if not isinstance(rules, list):
        return by_controller

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if str(rule.get("scope", "")).strip() != "visibility":
            continue
        when = str(rule.get("when", "")).strip()
        cond = _COND_EQ_RE.match(when)
        if not cond:
            continue
        controller_key = cond.group(1)
        try:
            controller_value = int(cond.group(2))
        except ValueError:
            continue

        actions = list(rule.get("then", []) or [])
        for raw_action in actions:
            action = str(raw_action).strip()
            show_match = _SHOW_ACTION_RE.match(action)
            if not show_match:
                continue
            target = str(show_match.group(1)).strip()
            by_controller.setdefault(controller_key, {}).setdefault(controller_value, set()).add(target)
    return by_controller


def _mode_stacks(
    catalog_by_key: Mapping[str, Mapping[str, Any]],
    visibility_map: Mapping[str, Mapping[int, set[str]]],
) -> Tuple[ModeStackSpec, ...]:
    stacks: List[ModeStackSpec] = []
    controller_keys = ("Throat.Profile", "GCurve.Type")
    gcurve_common = {"GCurve.Dist", "GCurve.Width", "GCurve.AspectRatio", "GCurve.Rot"}

    for controller_key in controller_keys:
        param = catalog_by_key.get(controller_key)
        if not param:
            continue
        enum_opts = _enum_options(param)
        if controller_key == "Throat.Profile":
            enum_opts = _append_rosse_option(enum_opts)
        if controller_key == "GCurve.Type":
            enum_opts = _gcurve_options(enum_opts)
        enum_labels = {int(option.value): option.label for option in enum_opts if isinstance(option.value, int)}
        controller_modes = visibility_map.get(controller_key, {})
        pages: List[ModePageSpec] = []

        if controller_key == "GCurve.Type":
            pages.append(ModePageSpec(value=None, label="no GCurve", field_keys=("Coverage.Angle",)))

        for value in sorted(controller_modes):
            label = enum_labels.get(value, str(value))
            page_targets = set(controller_modes.get(value, set()))
            if controller_key == "GCurve.Type":
                page_targets.update(gcurve_common)
            page_keys = tuple(sorted(page_targets))
            pages.append(ModePageSpec(value=value, label=label, field_keys=page_keys))

        if controller_key == "Throat.Profile":
            pages.insert(0, ModePageSpec(value=None, label="", field_keys=()))
            # TODO(max): Verify final CFG mapping strategy for R-OSSE mode against ATH export output.
            pages.insert(2, ModePageSpec(value=2, label="R-OSSE", field_keys=("R-OSSE",)))

        if len(pages) >= 2:
            label = "GCurve" if controller_key == "GCurve.Type" else _title_from_key(controller_key)
            stacks.append(ModeStackSpec(controller_key=controller_key, label=label, pages=tuple(pages)))

    return tuple(stacks)


def _append_rosse_option(options: Tuple[EnumSpec, ...]) -> Tuple[EnumSpec, ...]:
    label_override = {
        1: "OS-SE",
        2: "R-OSSE",
        3: "Circular Arc",
    }
    merged = []
    values = set()
    for option in options:
        value = option.value
        values.add(value)
        label = label_override.get(value, option.label)
        merged.append(EnumSpec(label=label, value=value))
    if 2 not in values:
        merged.append(EnumSpec(label="R-OSSE", value=2))
    merged.sort(key=lambda option: int(option.value) if isinstance(option.value, int) else 10_000)
    return tuple(merged)


def _gcurve_options(options: Tuple[EnumSpec, ...]) -> Tuple[EnumSpec, ...]:
    label_override = {
        1: "Superellipse",
        2: "Superformula",
    }
    merged: List[EnumSpec] = [EnumSpec(label="no GCurve", value=None)]
    for option in options:
        merged.append(EnumSpec(label=label_override.get(option.value, option.label), value=option.value))
    return tuple(merged)


def _ui_mode_tags_for_key(
    key: str,
    visibility_map: Mapping[str, Mapping[int, set[str]]],
) -> Tuple[str, ...]:
    tags: List[str] = []
    for controller_key, mode_map in visibility_map.items():
        for value, affected in mode_map.items():
            if key in affected:
                tags.append(f"{controller_key}={value}")
    if key == "R-OSSE":
        tags.append("Throat.Profile=2")
    if key == "Coverage.Angle":
        tags.append("GCurve.Type=<unset>")
    return tuple(sorted(set(tags)))


def _property_specs(
    parent_key: str,
    param: Mapping[str, Any],
    group_path: Sequence[str],
    order_seed: int,
) -> Tuple[FieldSpec, ...]:
    domain = param.get("domain")
    if not isinstance(domain, dict):
        return ()
    properties = domain.get("properties")
    if not isinstance(properties, dict):
        return ()

    specs: List[FieldSpec] = []
    for index, (property_name, property_schema_raw) in enumerate(properties.items()):
        if not isinstance(property_schema_raw, dict):
            continue
        property_key = f"{parent_key}.{property_name}"
        widget_kind = _widget_kind_for_type(str(property_schema_raw.get("type", "text")))
        minimum, maximum = _numeric_limits(property_schema_raw)
        label = _field_label(property_schema_raw, property_name)
        tooltip = property_tooltip_for(property_schema_raw)
        options = _enum_options(property_schema_raw)
        specs.append(
            FieldSpec(
                key=property_key,
                label=label,
                widget_kind=widget_kind,
                ath_type=str(property_schema_raw.get("type", "")),
                decimals=2,
                minimum=minimum,
                maximum=maximum,
                unit=_unit_for_key(property_key, property_schema_raw.get("unit")),
                tooltip=tooltip,
                placeholder=property_placeholder_for(widget_kind=widget_kind, property_schema=property_schema_raw),
                group_path=tuple(group_path),
                order=order_seed + index,
                scope=_scope_for_key(parent_key),
                enum_options=options,
                object_parent_key=parent_key,
            )
        )
    return tuple(specs)


def build_project_form_schema(bundle: AthKnowledgeBundle | None = None) -> FormSchema:
    bundle = bundle or load_ath_knowledge()
    catalog_by_key = _catalog_index(bundle)
    visibility_map = _rule_visibility_map(bundle)

    fields: List[FieldSpec] = []
    for index, param in enumerate(bundle.catalog.get("parameters", [])):
        if not isinstance(param, dict):
            continue
        key = str(param.get("key", "")).strip()
        if not key:
            continue
        if key.startswith("Source."):
            continue
        if key == "OSSE":
            # PROJECT UX keeps explicit OS-SE mode through Throat.Profile + Term/OS keys.
            continue

        widget_kind = _widget_kind_for_type(str(param.get("type", "")))
        minimum, maximum = _numeric_limits(param)
        group_path = _group_path_for_key(key, str(param.get("group", "")))
        enum_options = _enum_options(param)
        if key == "Throat.Profile":
            enum_options = _append_rosse_option(enum_options)
        if key == "GCurve.Type":
            enum_options = _gcurve_options(enum_options)

        field = FieldSpec(
            key=key,
            label=_field_label(param, key),
            widget_kind=widget_kind,
            ath_type=str(param.get("type", "")),
            default=param.get("default"),
            decimals=2,
            minimum=minimum,
            maximum=maximum,
            unit=_unit_for_key(key, param.get("unit")),
            tooltip=tooltip_for(param),
            placeholder=placeholder_for(widget_kind=widget_kind, param=param),
            group_path=group_path,
            order=index,
            ui_mode_tags=_ui_mode_tags_for_key(key, visibility_map),
            advanced=_is_advanced(key, widget_kind),
            scope=_scope_for_key(key),
            enum_options=enum_options,
            object_properties=_property_specs(key, param, group_path, order_seed=index * 100),
        )
        fields.append(field)

    return FormSchema(fields=tuple(fields), mode_stacks=_mode_stacks(catalog_by_key, visibility_map))


def schema_field_keys(schema: FormSchema) -> List[str]:
    return schema.keys()


def iter_mode_keys(schema: FormSchema) -> Iterable[str]:
    for stack in schema.mode_stacks:
        yield stack.controller_key
        for page in stack.pages:
            for key in page.field_keys:
                yield key
