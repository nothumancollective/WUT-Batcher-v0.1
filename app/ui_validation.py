"""Project-page field risk evaluation (normative + experiment hints)."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from app.ath_knowledge import load_ath_knowledge


_VERSIONED_RE = re.compile(r"^(?P<base>[A-Za-z0-9_.-]+)\.v(?P<v1>\d+)(?:\.(?P<v2>\d+))?\.json$")
_KEY_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_.]*)\b")
_DIM_PROXY_KEYS = ("Length", "Morph.TargetWidth", "Morph.TargetHeight")
_UNSET = object()


@dataclass(frozen=True)
class FieldIssue:
    key: str
    severity: str
    message: str
    source: str
    evidence_ref: str = ""
    suggestion: str = ""
    rule_id: str = ""
    confidence: Optional[float] = None


@dataclass(frozen=True)
class _RangeHint:
    safe_min: Optional[float]
    safe_max: Optional[float]
    rec_p05: Optional[float]
    rec_p95: Optional[float]
    notes: str


@dataclass(frozen=True)
class _CandidateRule:
    rule_id: str
    severity: str
    condition: str
    message: str
    evidence_ref: str
    suggestion: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    raw = value.strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _is_constant_numeric_expr(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if re.search(r"\bp\b", text, flags=re.IGNORECASE):
        return False
    return _to_float(text) is not None


def _fmt_num(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if abs(value - int(value)) <= 1e-9:
        return str(int(value))
    return f"{value:.4g}"


def _extract_draft_values(draft_payload: Mapping[str, Any]) -> Tuple[Dict[str, Any], Set[str]]:
    values: Dict[str, Any] = {}
    set_keys: Set[str] = set()
    for block_key in ("fixed_params", "limits"):
        block = draft_payload.get(block_key)
        if not isinstance(block, Mapping):
            continue
        for key, value in block.items():
            key_s = str(key)
            values[key_s] = value
            set_keys.add(key_s)

    states = draft_payload.get("param_states")
    if isinstance(states, list):
        for row in states:
            if not isinstance(row, Mapping):
                continue
            key = str(row.get("param_name", "")).strip()
            if not key:
                continue
            is_set = bool(row.get("is_set"))
            if is_set:
                values[key] = row.get("value")
                set_keys.add(key)
            else:
                values.pop(key, None)
                set_keys.discard(key)
    return values, set_keys


def _latest_versioned_file(base_dir: Path, basename: str) -> Optional[Path]:
    prefix = f"{basename}.v"
    candidates: List[Tuple[Tuple[int, int], Path]] = []
    for file_path in base_dir.glob(f"{basename}.v*.json"):
        match = _VERSIONED_RE.match(file_path.name)
        if not match:
            continue
        if match.group("base") != basename:
            continue
        major = int(match.group("v1") or 0)
        minor = int(match.group("v2") or 0)
        candidates.append(((major, minor), file_path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _load_json(path: Optional[Path]) -> Any:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_candidate_message(raw: Mapping[str, Any]) -> str:
    message_en = str(raw.get("suggested_message_en", "")).strip()
    message_de = str(raw.get("suggested_message_de", "")).strip()
    rationale = str(raw.get("rationale", "")).strip()
    return message_en or message_de or rationale or "Potential risk detected."


def _path_from_attribute(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        root = _path_from_attribute(node.value)
        if not root:
            return None
        return f"{root}.{node.attr}"
    return None


def _collect_condition_tokens(condition: str) -> Set[str]:
    keys: Set[str] = set()
    try:
        tree = ast.parse(_normalize_condition(condition), mode="eval")
    except SyntaxError:
        return keys
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            token = str(node.value).strip()
            if _KEY_TOKEN_RE.match(token):
                keys.add(token)
        elif isinstance(node, ast.Attribute):
            path = _path_from_attribute(node)
            if path:
                keys.add(path)
        elif isinstance(node, ast.Name):
            if _KEY_TOKEN_RE.match(node.id):
                keys.add(node.id)
    return keys


def _boolify(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_boolify(item) for item in value)
    if value is _UNSET or value is None:
        return False
    return bool(value)


def _normalize_condition(condition: str) -> str:
    normalized = str(condition or "")
    normalized = re.sub(r"\band\s*\(", "and_(", normalized)
    normalized = re.sub(r"\bor\s*\(", "or_(", normalized)
    normalized = re.sub(r"\bnot\s*\(", "not_(", normalized)
    return normalized


def _resolve_token_value(value: Any, *, values: Mapping[str, Any], set_keys: Set[str]) -> Any:
    if isinstance(value, str):
        token = value.strip()
        if token in values and token in set_keys:
            return values[token]
    return value


def _compare_values(op: str, left: Any, right: Any) -> Any:
    if isinstance(left, (list, tuple)):
        return [_compare_values(op, item, right) for item in list(left)]
    if isinstance(right, (list, tuple)):
        return [_compare_values(op, left, item) for item in list(right)]

    left_num = _to_float(left)
    right_num = _to_float(right)
    if left_num is not None and right_num is not None:
        if op == "eq":
            return left_num == right_num
        if op == "ne":
            return left_num != right_num
        if op == "gt":
            return left_num > right_num
        if op == "gte":
            return left_num >= right_num
        if op == "lt":
            return left_num < right_num
        if op == "lte":
            return left_num <= right_num
    if op == "eq":
        return str(left) == str(right)
    if op == "ne":
        return str(left) != str(right)
    return False


def _eval_condition(condition: str, *, values: Mapping[str, Any], set_keys: Set[str]) -> bool:
    try:
        tree = ast.parse(_normalize_condition(condition), mode="eval")
    except SyntaxError:
        return False

    input_numeric = [float(val) for key, val in values.items() if key in set_keys for val in [_to_float(values.get(key))] if val is not None]
    observed_max = max(input_numeric) if input_numeric else None
    env: Dict[str, Any] = {
        "input_numeric": input_numeric,
        "observed.max_dimension_mm": observed_max,
    }

    def eval_node(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            if node.id in values:
                return values[node.id]
            return _UNSET
        if isinstance(node, ast.Attribute):
            path = _path_from_attribute(node)
            if path and path in env:
                return env[path]
            if path and path in values:
                return values[path]
            return _UNSET
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                return False
            fn = node.func.id
            args = [eval_node(arg) for arg in node.args]
            if fn in {"and", "and_"}:
                return all(_boolify(arg) for arg in args)
            if fn in {"or", "or_"}:
                return any(_boolify(arg) for arg in args)
            if fn in {"not", "not_"}:
                return not _boolify(args[0]) if args else False
            if fn in {"eq", "ne", "gt", "gte", "lt", "lte"}:
                if len(args) != 2:
                    return False
                left = _resolve_token_value(args[0], values=values, set_keys=set_keys)
                right = _resolve_token_value(args[1], values=values, set_keys=set_keys)
                return _compare_values(fn, left, right)
            if fn == "isDefined":
                if len(args) != 1:
                    return False
                arg = args[0]
                if isinstance(arg, str) and arg in set_keys:
                    return True
                if arg is _UNSET or arg is None:
                    return False
                return True
            if fn == "any":
                if not args:
                    return False
                return any(_boolify(item) for item in (args[0] if isinstance(args[0], (list, tuple)) else args))
            return False
        return False

    try:
        return _boolify(eval_node(tree.body))
    except Exception:
        return False


class UiValidationEngine:
    """Unified field issue pipeline for Project page."""

    def __init__(
        self,
        *,
        reports_root: Optional[Path] = None,
    ) -> None:
        root = reports_root or (_repo_root() / "reports" / "ath_experiments")
        self.reports_root = Path(root)
        self.range_path = _latest_versioned_file(self.reports_root, "range_suggestions") or (self.reports_root / "range_suggestions.v1.3.json")
        self.candidates_path = _latest_versioned_file(self.reports_root, "compat_rule_candidates") or (
            self.reports_root / "compat_rule_candidates.v2.json"
        )
        self._ranges: Dict[str, _RangeHint] = {}
        self._candidates: List[_CandidateRule] = []
        self._unit_by_key: Dict[str, str] = {}
        self.enabled = False
        self._load_units()
        self.reload()

    def _load_units(self) -> None:
        try:
            bundle = load_ath_knowledge()
            params = list(bundle.catalog.get("parameters", []) or [])
        except Exception:
            params = []
        units: Dict[str, str] = {}
        for row in params:
            if not isinstance(row, Mapping):
                continue
            key = str(row.get("key", "")).strip()
            if not key:
                continue
            unit = str(row.get("unit", "")).strip().lower()
            if unit:
                units[key] = unit
        self._unit_by_key = units

    def _is_hard_cap_key_supported(self, key: str) -> bool:
        unit = str(self._unit_by_key.get(str(key), "")).strip().lower()
        return "mm" in unit

    def reload(self) -> None:
        self._ranges = self._load_ranges(self.range_path)
        self._candidates = self._load_candidates(self.candidates_path)
        self.enabled = bool(self._ranges or self._candidates)

    def _load_ranges(self, path: Path) -> Dict[str, _RangeHint]:
        payload = _load_json(path)
        if not isinstance(payload, Mapping):
            return {}
        per_key = payload.get("per_key")
        if not isinstance(per_key, Mapping):
            return {}
        out: Dict[str, _RangeHint] = {}
        for key, raw in per_key.items():
            if not isinstance(raw, Mapping):
                continue
            out[str(key)] = _RangeHint(
                safe_min=_to_float(raw.get("safe_min")),
                safe_max=_to_float(raw.get("safe_max")),
                rec_p05=_to_float(raw.get("rec_p05")),
                rec_p95=_to_float(raw.get("rec_p95")),
                notes=str(raw.get("notes", "")),
            )
        return out

    def _load_candidates(self, path: Path) -> List[_CandidateRule]:
        payload = _load_json(path)
        if not isinstance(payload, Mapping):
            return []
        rows = payload.get("candidates")
        if not isinstance(rows, list):
            return []
        out: List[_CandidateRule] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            severity = str(raw.get("severity", raw.get("kind", ""))).strip().lower()
            if severity not in {"warn", "fatal"}:
                continue
            condition = str(raw.get("condition", raw.get("when", ""))).strip()
            if not condition:
                continue
            evidence_ref = ""
            evidence = raw.get("evidence")
            if isinstance(evidence, Mapping):
                if "matched_total" in evidence:
                    evidence_ref = f"matched_total={evidence.get('matched_total')}"
                elif "ath_pattern" in evidence:
                    evidence_ref = str(evidence.get("ath_pattern", ""))
            out.append(
                _CandidateRule(
                    rule_id=str(raw.get("id", "experiment_candidate")),
                    severity=severity,
                    condition=condition,
                    message=_normalize_candidate_message(raw),
                    evidence_ref=evidence_ref,
                    suggestion=str(raw.get("verification_plan", "")).strip(),
                )
            )
        return out

    @staticmethod
    def _is_visibility_noise_issue(raw: Mapping[str, Any]) -> bool:
        rule_id = str(raw.get("rule_id", "")).strip().lower()
        message = str(raw.get("message", "")).strip().lower()
        if rule_id in {"batch_param_not_visible", "project_param_not_visible"}:
            return True
        if "not visible for current project constraints" in message:
            return True
        return False

    def evaluate_normative_issues(
        self,
        validation_state: Mapping[str, Any],
        *,
        visible_keys: Optional[Iterable[str]] = None,
    ) -> List[FieldIssue]:
        issues: List[FieldIssue] = []
        visible = {str(item) for item in list(visible_keys or []) if str(item).strip()}
        for raw in list(validation_state.get("issues", []) or []):
            if not isinstance(raw, Mapping):
                continue
            if self._is_visibility_noise_issue(raw):
                continue
            key = str(raw.get("field_key", "")).strip()
            if not key:
                continue
            if visible and key not in visible:
                continue
            issues.append(
                FieldIssue(
                    key=key,
                    severity=str(raw.get("severity", "info")).lower(),
                    message=str(raw.get("message", "")).strip(),
                    source="normative",
                    evidence_ref=str(raw.get("evidence_type", "ruleset")),
                    suggestion="",
                    rule_id=str(raw.get("rule_id", "compat_rule")),
                )
            )
        return issues

    def evaluate_experiment_issues(
        self,
        draft_payload: Mapping[str, Any],
        *,
        visible_keys: Optional[Iterable[str]] = None,
    ) -> List[FieldIssue]:
        if not self.enabled:
            return []
        values, set_keys = _extract_draft_values(draft_payload)
        if not set_keys:
            return []
        visible = set(str(item) for item in (visible_keys or set_keys))
        if not visible:
            visible = set(set_keys)

        # Range-based hints.
        issues: List[FieldIssue] = []
        for key in sorted(set_keys):
            if key not in visible:
                continue
            hint = self._ranges.get(key)
            if hint is None:
                continue
            value = values.get(key)
            if not _is_constant_numeric_expr(value):
                continue
            number = _to_float(value)
            if number is None:
                continue

            outside_safe = bool((hint.safe_min is not None and number < hint.safe_min) or (hint.safe_max is not None and number > hint.safe_max))
            outside_rec = bool((hint.rec_p05 is not None and number < hint.rec_p05) or (hint.rec_p95 is not None and number > hint.rec_p95))

            if outside_safe:
                issues.append(
                    FieldIssue(
                        key=key,
                        severity="warn",
                        source="experiment",
                        rule_id="exp_range_safe",
                        message=(
                            f"{key} is outside the safe range "
                            f"[{_fmt_num(hint.safe_min)}, {_fmt_num(hint.safe_max)}]."
                        ),
                        evidence_ref=hint.notes,
                        suggestion=f"Recommended range: [{_fmt_num(hint.rec_p05)}, {_fmt_num(hint.rec_p95)}].",
                    )
                )
                continue
            if outside_rec:
                issues.append(
                    FieldIssue(
                        key=key,
                        severity="warn",
                        source="experiment",
                        rule_id="exp_range_recommended",
                        message=(
                            f"{key} is outside the recommended range "
                            f"[{_fmt_num(hint.rec_p05)}, {_fmt_num(hint.rec_p95)}]."
                        ),
                        evidence_ref=hint.notes,
                        suggestion=f"Safe range: [{_fmt_num(hint.safe_min)}, {_fmt_num(hint.safe_max)}].",
                    )
                )
                continue

            issues.append(
                FieldIssue(
                    key=key,
                    severity="ok",
                    source="experiment",
                    rule_id="exp_range_ok",
                    message="",
                    evidence_ref=hint.notes,
                    suggestion="",
                )
            )

        # Candidate mode/threshold hints.
        for candidate in self._candidates:
            if not _eval_condition(candidate.condition, values=values, set_keys=set_keys):
                continue
            token_keys = _collect_condition_tokens(candidate.condition)
            affected = sorted(
                key
                for key in token_keys
                if key in set_keys and key in visible and key != "observed.max_dimension_mm" and key != "input_numeric"
            )
            if "observed.max_dimension_mm" in token_keys:
                for proxy in _DIM_PROXY_KEYS:
                    if proxy in set_keys and proxy in visible:
                        affected.append(proxy)
            if "input_numeric" in token_keys or not affected:
                for key in sorted(set_keys):
                    if key not in visible:
                        continue
                    value_num = _to_float(values.get(key))
                    if value_num is None:
                        continue
                    if "hard_cap" in candidate.rule_id and self._is_hard_cap_key_supported(key) and value_num > 5000.0:
                        affected.append(key)
            for key in sorted(set(affected)):
                issues.append(
                    FieldIssue(
                        key=key,
                        severity=candidate.severity,
                        message=candidate.message,
                        source="experiment",
                        evidence_ref=candidate.evidence_ref,
                        suggestion=candidate.suggestion,
                        rule_id=candidate.rule_id,
                    )
                )

        dedup: Dict[Tuple[str, str, str, str], FieldIssue] = {}
        for issue in issues:
            dedup[(issue.key, issue.severity, issue.rule_id, issue.message)] = issue
        return list(dedup.values())

    def evaluate(
        self,
        *,
        draft_payload: Mapping[str, Any],
        validation_state: Mapping[str, Any],
        visible_keys: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        issues = []
        issues.extend(self.evaluate_normative_issues(validation_state, visible_keys=visible_keys))
        issues.extend(self.evaluate_experiment_issues(draft_payload, visible_keys=visible_keys))
        return [asdict(item) for item in issues]
