"""CFG rendering with runner compatibility enforcement."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from app.ath_knowledge import AthKnowledgeBundle, load_ath_knowledge
from app.compare_policy import canonicalize_cfg_value
from app.constants import DEFAULT_RUNNER_MODE, MANDATORY_SOURCE_BLOCK


_ASSIGN_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=")


def _catalog_keys(bundle: AthKnowledgeBundle) -> List[str]:
    keys: List[str] = []
    for item in bundle.catalog.get("parameters", []):
        if isinstance(item, dict):
            key = item.get("key")
            if isinstance(key, str):
                keys.append(key)
    return keys


def _runner_locked_keys(bundle: AthKnowledgeBundle, runner_mode: str) -> set[str]:
    restrictions = bundle.ruleset.get("runner_restrictions", {})
    if not isinstance(restrictions, dict):
        return set()
    if restrictions.get("runner_mode") != runner_mode:
        return set()
    raw = restrictions.get("locked_or_hidden_keys", [])
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw}


def _format_value(value: Any, *, keep_float_trailing_zero: bool = False) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return f"{value:.1f}" if keep_float_trailing_zero else str(int(value))
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_format_value(item, keep_float_trailing_zero=keep_float_trailing_zero) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _format_geometry_line(key: str, value: Any) -> str:
    return f"{key:<17}= {_format_value(value)}"


def _ordered_object_items(key: str, value: Dict[str, Any]) -> List[Tuple[str, Any]]:
    if key == "R-OSSE":
        preferred = ["R", "r0", "a0", "a", "k", "r", "m", "b", "q"]
        ranked: List[Tuple[str, Any]] = []
        seen: set[str] = set()
        for name in preferred:
            if name in value:
                ranked.append((name, value[name]))
                seen.add(name)
        for name in value.keys():
            if str(name) not in seen:
                ranked.append((str(name), value[name]))
        return ranked
    return [(str(name), sub_value) for name, sub_value in value.items()]


def _format_geometry_lines(key: str, value: Any) -> List[str]:
    if isinstance(value, dict):
        lines = [f"{key} = {{"]
        for sub_key, sub_value in _ordered_object_items(key, value):
            lines.append(f"{sub_key} = {_format_value(sub_value)}")
        lines.append("}")
        return lines
    return [_format_geometry_line(key, value)]


def _format_mandatory_line(key: str, value: Any) -> str:
    if key == "ABEC.AkabakMode":
        return f"{key:<19}= {_format_value(value)}"
    return f"{key:<12}= {_format_value(value, keep_float_trailing_zero=True)}"


def build_cfg_updates(
    parameters: Dict[str, Any],
    runner_mode: str = DEFAULT_RUNNER_MODE,
    bundle: AthKnowledgeBundle | None = None,
) -> Dict[str, Any]:
    bundle = bundle or load_ath_knowledge()
    allowed_keys = set(_catalog_keys(bundle))
    locked = _runner_locked_keys(bundle, runner_mode)
    mandatory_keys = {key for key, _ in MANDATORY_SOURCE_BLOCK}

    raw_params = dict(parameters or {})
    # Canonicalize UI convenience superformula list to stable subkeys before rendering.
    sf_value = raw_params.get("GCurve.SF")
    if isinstance(sf_value, list) and len(sf_value) >= 6 and all(
        sf_key not in raw_params for sf_key in ("GCurve.SF.a", "GCurve.SF.b", "GCurve.SF.m1", "GCurve.SF.m2", "GCurve.SF.n1", "GCurve.SF.n2", "GCurve.SF.n3")
    ):
        try:
            a = float(sf_value[0])
            b = float(sf_value[1])
            m = float(sf_value[2])
            n1 = float(sf_value[3])
            n2 = float(sf_value[4])
            n3 = float(sf_value[5])
        except Exception:
            pass
        else:
            raw_params["GCurve.SF.a"] = a
            raw_params["GCurve.SF.b"] = b
            raw_params["GCurve.SF.m1"] = m
            raw_params["GCurve.SF.m2"] = m
            raw_params["GCurve.SF.n1"] = n1
            raw_params["GCurve.SF.n2"] = n2
            raw_params["GCurve.SF.n3"] = n3
            raw_params.pop("GCurve.SF", None)

    updates: Dict[str, Any] = {}
    for key, value in raw_params.items():
        if key in mandatory_keys:
            continue
        if key in locked:
            continue
        if key in allowed_keys:
            updates[key] = canonicalize_cfg_value(key, value)
    return updates


def render_cfg_text(
    template_text: str,
    parameters: Dict[str, Any],
    version_id: str,
    runner_mode: str = DEFAULT_RUNNER_MODE,
    omit_keys: Iterable[str] = (),
    bundle: AthKnowledgeBundle | None = None,
) -> str:
    bundle = bundle or load_ath_knowledge()
    updates = build_cfg_updates(parameters=parameters, runner_mode=runner_mode, bundle=bundle)
    locked = _runner_locked_keys(bundle, runner_mode)
    mandatory_keys = {key for key, _ in MANDATORY_SOURCE_BLOCK}
    suppressed = locked | mandatory_keys | {str(key) for key in omit_keys}

    # ATH interprets a UTF-8 BOM as visible cp1252 characters in the first key
    # (``ï»¿Output...``). Strip it before matching or rendering assignments.
    lines = str(template_text).lstrip("\ufeff").splitlines()
    rendered: List[str] = []
    consumed_updates: set[str] = set()

    for raw_line in lines:
        match = _ASSIGN_RE.match(raw_line)
        if not match:
            rendered.append(raw_line)
            continue

        key = match.group(1).strip()
        if key in suppressed:
            continue
        if key in updates:
            rendered.extend(_format_geometry_lines(key, updates[key]))
            consumed_updates.add(key)
            continue
        rendered.append(raw_line)

    remaining_keys = sorted((set(updates.keys()) - consumed_updates))
    if remaining_keys:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.append("; --- appended geometry updates ---")
        for key in remaining_keys:
            rendered.extend(_format_geometry_lines(key, updates[key]))

    if rendered and rendered[-1].strip():
        rendered.append("")
    rendered.append("; ----- AKABAK import compatibility -----")
    for key, value in MANDATORY_SOURCE_BLOCK[:1]:
        rendered.append(_format_mandatory_line(key, value))
    rendered.append('; ----- Drive without needing AKABAK "Fixed Driving" -----')
    for key, value in MANDATORY_SOURCE_BLOCK[1:]:
        rendered.append(_format_mandatory_line(key, value))

    return "\n".join(rendered) + "\n"


def render_cfg_file(
    template_path: Path,
    output_path: Path,
    parameters: Dict[str, Any],
    version_id: str,
    runner_mode: str = DEFAULT_RUNNER_MODE,
    omit_keys: Iterable[str] = (),
    bundle: AthKnowledgeBundle | None = None,
) -> str:
    template_text = template_path.read_text(encoding="utf-8-sig")
    cfg_text = render_cfg_text(
        template_text=template_text,
        parameters=parameters,
        version_id=version_id,
        runner_mode=runner_mode,
        omit_keys=omit_keys,
        bundle=bundle,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(cfg_text, encoding="utf-8")
    return cfg_text
