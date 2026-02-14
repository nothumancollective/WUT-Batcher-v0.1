"""Key-specific compare/canonicalization policy for ATH cfg<->config roundtrips."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


_NUMERIC_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?$")

_SF_ALIAS_KEYS = (
    "GCurve.SF.a",
    "GCurve.SF.b",
    "GCurve.SF.m1",
    "GCurve.SF.m2",
    "GCurve.SF.n1",
    "GCurve.SF.n2",
    "GCurve.SF.n3",
)


@dataclass(frozen=True)
class CompareSemantics:
    key: str
    value_type: str
    order_significant: bool = True
    duplicates_allowed: bool = True
    epsilon: float = 1e-6
    allow_empty_equivalences: bool = False
    optional_missing_in_ath_config: bool = False
    aliases_to_subkeys: bool = False


_POLICY: Dict[str, CompareSemantics] = {
    "Morph.AllowShrinkage": CompareSemantics(
        key="Morph.AllowShrinkage",
        value_type="bool",
        allow_empty_equivalences=True,
    ),
    "Mesh.SubdomainSlices": CompareSemantics(
        key="Mesh.SubdomainSlices",
        value_type="list_int",
        allow_empty_equivalences=True,
        optional_missing_in_ath_config=True,
    ),
    "Mesh.InterfaceDraw": CompareSemantics(
        key="Mesh.InterfaceDraw",
        value_type="list_float",
        allow_empty_equivalences=True,
        optional_missing_in_ath_config=True,
    ),
    "Mesh.ZMapPoints": CompareSemantics(
        key="Mesh.ZMapPoints",
        value_type="list_float",
        allow_empty_equivalences=True,
        optional_missing_in_ath_config=True,
    ),
    "GCurve.SF": CompareSemantics(
        key="GCurve.SF",
        value_type="list_float",
        allow_empty_equivalences=True,
        optional_missing_in_ath_config=True,
        aliases_to_subkeys=True,
    ),
}


def compare_semantics(key: str) -> Optional[CompareSemantics]:
    return _POLICY.get(str(key))


def _parse_numeric(value: Any) -> Optional[float]:
    text = str(value).strip()
    if not text or not _NUMERIC_RE.match(text):
        return None
    try:
        return float(text.replace(",", "."))
    except Exception:
        return None


def _parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "1.0", "true", "yes", "on"}:
        return True
    if text in {"0", "0.0", "false", "no", "off"}:
        return False
    return None


def _parse_list(value: Any, *, prefer_int: bool) -> Optional[List[Any]]:
    if isinstance(value, list):
        raw = list(value)
    else:
        text = str(value).strip()
        if not text:
            return []
        if text.startswith("{") and text.endswith("}"):
            text = text[1:-1].strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1].strip()
        if not text:
            return []
        if "," in text:
            raw = [item.strip() for item in text.split(",") if item.strip()]
        else:
            raw = [item.strip() for item in re.split(r"\s+", text) if item.strip()]

    parsed: List[Any] = []
    for item in raw:
        number = _parse_numeric(item)
        if number is None:
            parsed.append(str(item).strip())
            continue
        if prefer_int and abs(number - round(number)) <= 1e-9:
            parsed.append(int(round(number)))
        else:
            parsed.append(float(number))
    return parsed


def _sf_alias_from_map(values: Mapping[str, Any]) -> Optional[List[float]]:
    present = {key: values.get(key) for key in _SF_ALIAS_KEYS if key in values}
    if not present:
        return None
    required = ("GCurve.SF.a", "GCurve.SF.b", "GCurve.SF.n1", "GCurve.SF.n2", "GCurve.SF.n3")
    if not all(item in present for item in required):
        return None
    a = _parse_numeric(present["GCurve.SF.a"])
    b = _parse_numeric(present["GCurve.SF.b"])
    n1 = _parse_numeric(present["GCurve.SF.n1"])
    n2 = _parse_numeric(present["GCurve.SF.n2"])
    n3 = _parse_numeric(present["GCurve.SF.n3"])
    m1 = _parse_numeric(present.get("GCurve.SF.m1"))
    m2 = _parse_numeric(present.get("GCurve.SF.m2"))
    if None in {a, b, n1, n2, n3}:
        return None
    m = m1 if m1 is not None else m2
    if m is None:
        return None
    if m1 is not None and m2 is not None and abs(m1 - m2) > 1e-6:
        return None
    return [float(a), float(b), float(m), float(n1), float(n2), float(n3)]


def canonicalize_cfg_value(key: str, value: Any) -> Any:
    semantics = compare_semantics(key)
    if semantics is None:
        return value
    if semantics.value_type == "bool":
        parsed = _parse_bool(value)
        if parsed is None:
            return value
        return 1 if parsed else 0
    if semantics.value_type == "list_int":
        parsed = _parse_list(value, prefer_int=True)
        return parsed if parsed is not None else value
    if semantics.value_type == "list_float":
        parsed = _parse_list(value, prefer_int=False)
        return parsed if parsed is not None else value
    return value


def canonicalize_config_value(key: str, value: Any, *, observed_map: Optional[Mapping[str, Any]] = None) -> Any:
    semantics = compare_semantics(key)
    if semantics is None:
        return value
    if semantics.value_type == "bool":
        parsed = _parse_bool(value)
        if parsed is None:
            return value
        return parsed
    if semantics.value_type in {"list_int", "list_float"}:
        if semantics.aliases_to_subkeys and observed_map is not None:
            alias = _sf_alias_from_map(observed_map)
            if alias is not None:
                return alias
        parsed = _parse_list(value, prefer_int=semantics.value_type == "list_int")
        return parsed if parsed is not None else value
    return value


def is_optional_missing_for_target(key: str, *, target: str) -> bool:
    semantics = compare_semantics(key)
    if semantics is None:
        return False
    return target == "ath_config" and bool(semantics.optional_missing_in_ath_config)


def has_alias_match(key: str, *, observed_map: Mapping[str, Any]) -> bool:
    semantics = compare_semantics(key)
    if semantics is None or not semantics.aliases_to_subkeys:
        return False
    return _sf_alias_from_map(observed_map) is not None


def policy_values_equal(
    key: str,
    expected: Any,
    actual: Any,
    *,
    target: str,
    observed_map: Mapping[str, Any],
) -> Optional[bool]:
    semantics = compare_semantics(key)
    if semantics is None:
        return None

    lhs = canonicalize_cfg_value(key, expected)
    rhs = canonicalize_config_value(key, actual, observed_map=observed_map)

    if semantics.value_type == "bool":
        lhs_bool = _parse_bool(lhs)
        rhs_bool = _parse_bool(rhs)
        if lhs_bool is None or rhs_bool is None:
            if semantics.allow_empty_equivalences and target == "ath_config" and str(rhs).strip() == "":
                return True
            return None
        return bool(lhs_bool) == bool(rhs_bool)

    if semantics.value_type in {"list_int", "list_float"}:
        lhs_list = _parse_list(lhs, prefer_int=semantics.value_type == "list_int")
        rhs_list = _parse_list(rhs, prefer_int=semantics.value_type == "list_int")
        if rhs_list is None:
            if semantics.allow_empty_equivalences and target == "ath_config" and str(actual).strip() == "":
                return True
            return None
        lhs_list = lhs_list or []
        rhs_list = rhs_list or []
        if len(lhs_list) != len(rhs_list):
            if semantics.allow_empty_equivalences and target == "ath_config" and len(rhs_list) == 0:
                return True
            return False
        for left, right in zip(lhs_list, rhs_list):
            lnum = _parse_numeric(left)
            rnum = _parse_numeric(right)
            if lnum is not None and rnum is not None:
                if abs(float(lnum) - float(rnum)) > float(semantics.epsilon):
                    return False
                continue
            if str(left).strip() != str(right).strip():
                return False
        return True
    return None


def policy_tracked_keys() -> List[str]:
    return sorted(_POLICY.keys())


def policy_summary() -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for key, item in _POLICY.items():
        summary[key] = {
            "type": item.value_type,
            "order_significant": item.order_significant,
            "duplicates_allowed": item.duplicates_allowed,
            "epsilon": item.epsilon,
            "allow_empty_equivalences": item.allow_empty_equivalences,
            "optional_missing_in_ath_config": item.optional_missing_in_ath_config,
            "aliases_to_subkeys": item.aliases_to_subkeys,
        }
    return summary


def alias_allowed_keys_for_expected(expected_keys: Iterable[str]) -> List[str]:
    raw = {str(item) for item in expected_keys}
    allowed: List[str] = []
    if "GCurve.SF" in raw:
        allowed.extend(list(_SF_ALIAS_KEYS))
    return sorted(set(allowed))
