"""UI-only compatibility adapter.

Builds button-level blocking and helper metadata from compatibility outputs
without mutating ATH rule logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ui.form_schema import FormSchema, build_project_form_schema


_NONE_TOKEN = "__none__"


def option_token(value: Any) -> str:
    if value is None:
        return _NONE_TOKEN
    return str(value)


def _is_controller_field_key(key: str, controller_keys: Set[str]) -> bool:
    return str(key).strip() in controller_keys


@dataclass(frozen=True)
class _Cause:
    key: str
    message: str
    hidden_keys: Tuple[str, ...]


class CompatUiAdapter:
    """Derives UI blocking state from compatibility snapshots via hypotheses."""

    def __init__(self, schema: Optional[FormSchema] = None) -> None:
        self.schema = schema or build_project_form_schema()
        self._field_by_key = self.schema.by_key()
        self._scope_by_key = {key: field.scope for key, field in self._field_by_key.items()}
        self.controller_options = self._collect_controller_options()
        self.controller_keys = set(self.controller_options.keys())

    def _collect_controller_options(self) -> Dict[str, List[Any]]:
        keys: Set[str] = {stack.controller_key for stack in list(self.schema.mode_stacks or [])}
        keys.add("Morph.TargetShape")
        result: Dict[str, List[Any]] = {}
        for key in sorted(keys):
            field = self._field_by_key.get(key)
            if field is None or field.widget_kind != "enum":
                continue
            options = [option.value for option in list(field.enum_options or ())]
            if options:
                result[key] = options
        return result

    def _pick_primary_cause(self, candidates: Sequence[str], *, last_changed_key: Optional[str]) -> str:
        values = [str(item) for item in list(candidates or []) if str(item).strip()]
        if not values:
            return ""
        controller_hits = sorted(item for item in values if _is_controller_field_key(item, self.controller_keys))
        if controller_hits:
            return controller_hits[0]
        if last_changed_key and str(last_changed_key).strip() in values:
            return str(last_changed_key).strip()
        return sorted(values)[0]

    @staticmethod
    def _helper_message(hidden_keys: Sequence[str]) -> str:
        labels = [str(item) for item in list(hidden_keys or []) if str(item).strip()]
        if not labels:
            return ""
        head = ", ".join(labels[:5])
        extra = len(labels) - min(len(labels), 5)
        suffix = f", +{extra}" if extra > 0 else ""
        return f"This parameter doesn't allow the configuration of: {head}{suffix}"

    @staticmethod
    def _extract_project_set_values(payload: Mapping[str, Any]) -> tuple[Dict[str, Any], Set[str]]:
        values: Dict[str, Any] = {}
        set_keys: Set[str] = set()
        for block_name in ("fixed_params", "limits"):
            block = payload.get(block_name)
            if not isinstance(block, Mapping):
                continue
            for key, value in block.items():
                key_s = str(key)
                values[key_s] = value
                set_keys.add(key_s)
        for raw in list(payload.get("param_states", []) or []):
            if not isinstance(raw, Mapping):
                continue
            key = str(raw.get("param_name", "")).strip()
            if not key:
                continue
            if bool(raw.get("is_set")):
                values[key] = raw.get("value")
                set_keys.add(key)
            else:
                values.pop(key, None)
                set_keys.discard(key)
        return values, set_keys

    def _apply_project_selection(self, payload: Mapping[str, Any], key: str, value: Any) -> Dict[str, Any]:
        updated = {
            "fixed_params": dict(payload.get("fixed_params", {}) or {}),
            "limits": dict(payload.get("limits", {}) or {}),
            "param_states": [dict(item) for item in list(payload.get("param_states", []) or []) if isinstance(item, Mapping)],
            "runner_mode": payload.get("runner_mode"),
        }
        scope = str(self._scope_by_key.get(str(key), "fixed_params"))
        if value is None:
            updated["fixed_params"].pop(str(key), None)
            updated["limits"].pop(str(key), None)
        else:
            target = updated["limits"] if scope == "limits" else updated["fixed_params"]
            target[str(key)] = value
        remaining_states = [row for row in updated["param_states"] if str(row.get("param_name", "")) != str(key)]
        remaining_states.append(
            {
                "param_name": str(key),
                "is_set": 0 if value is None else 1,
                "value": None if value is None else value,
            }
        )
        updated["param_states"] = remaining_states
        return updated

    def compute_project_ui_state(
        self,
        *,
        draft_payload: Mapping[str, Any],
        compat_state: Mapping[str, Any],
        evaluate_constraints: Callable[[Dict[str, Any]], Dict[str, Any]],
        last_changed_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        values, set_keys = self._extract_project_set_values(draft_payload)
        visible_now = {str(item) for item in list(compat_state.get("visible_keys", []) or []) if str(item).strip()}
        blocked_options: Dict[str, Dict[str, Dict[str, Any]]] = {}
        cause_map: Dict[str, str] = {}
        helper_text: Dict[str, str] = {}

        for controller_key, options in self.controller_options.items():
            current_set = controller_key in set_keys
            current_value = values.get(controller_key)
            for option_value in options:
                if current_set and option_value == current_value:
                    continue
                if (not current_set) and option_value is None:
                    continue
                hypothetical = self._apply_project_selection(draft_payload, controller_key, option_value)
                hypo_state = evaluate_constraints(hypothetical)
                hypo_visible = {str(item) for item in list(hypo_state.get("visible_keys", []) or []) if str(item).strip()}
                hidden_conflicts = sorted(
                    key
                    for key in set_keys
                    if key != controller_key and key in visible_now and key not in hypo_visible
                )
                if not hidden_conflicts:
                    continue
                cause_key = self._pick_primary_cause(hidden_conflicts, last_changed_key=last_changed_key)
                message = self._helper_message(hidden_conflicts)
                blocked_options.setdefault(controller_key, {})[option_token(option_value)] = {
                    "cause_key": cause_key,
                    "message": message,
                    "hidden_keys": hidden_conflicts,
                }
                cause_map[f"{controller_key}:{option_token(option_value)}"] = cause_key
                helper_text[f"{controller_key}:{option_token(option_value)}"] = message

        hidden_keys = sorted(set(self._field_by_key.keys()) - visible_now)
        return {
            "hidden_keys": hidden_keys,
            "blocked_keys": [],
            "blocked_options": blocked_options,
            "cause_map": cause_map,
            "helper_text_map": helper_text,
        }

    def compute_batch_ui_state(
        self,
        *,
        selected_params: Mapping[str, Any],
        sweeps: Mapping[str, Any],
        sweep_mode: str,
        compat_state: Mapping[str, Any],
        project_constraints: Optional[Mapping[str, Any]] = None,
        evaluate_batch: Callable[[Dict[str, Any], Dict[str, Any], str], Dict[str, Any]],
        last_changed_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        project_values, project_set_keys = self._extract_project_set_values(project_constraints or {})
        selected = {
            str(key): value
            for key, value in dict(selected_params or {}).items()
            if value is not None and str(key).strip()
        }
        set_keys = set(selected.keys()) | set(project_set_keys)
        visible_now = {str(item) for item in list(compat_state.get("visible_keys", []) or []) if str(item).strip()}
        blocked_options: Dict[str, Dict[str, Dict[str, Any]]] = {}
        cause_map: Dict[str, str] = {}
        helper_text: Dict[str, str] = {}

        for controller_key, options in self.controller_options.items():
            current_set = controller_key in selected
            if not current_set and controller_key in project_values:
                current_set = True
            current_value = selected.get(controller_key, project_values.get(controller_key))
            for option_value in options:
                if current_set and option_value == current_value:
                    continue
                if (not current_set) and option_value is None:
                    continue
                hypothetical = dict(selected)
                if option_value is None:
                    hypothetical.pop(controller_key, None)
                else:
                    hypothetical[controller_key] = option_value
                hypo_state = evaluate_batch(hypothetical, dict(sweeps or {}), str(sweep_mode or "single"))
                hypo_visible = {str(item) for item in list(hypo_state.get("visible_keys", []) or []) if str(item).strip()}
                hidden_conflicts = sorted(
                    key
                    for key in set_keys
                    if key != controller_key and key in visible_now and key not in hypo_visible
                )
                if not hidden_conflicts:
                    continue
                cause_key = self._pick_primary_cause(hidden_conflicts, last_changed_key=last_changed_key)
                message = self._helper_message(hidden_conflicts)
                blocked_options.setdefault(controller_key, {})[option_token(option_value)] = {
                    "cause_key": cause_key,
                    "message": message,
                    "hidden_keys": hidden_conflicts,
                }
                cause_map[f"{controller_key}:{option_token(option_value)}"] = cause_key
                helper_text[f"{controller_key}:{option_token(option_value)}"] = message

        hidden_keys = sorted(set(self._field_by_key.keys()) - visible_now)
        return {
            "hidden_keys": hidden_keys,
            "blocked_keys": [],
            "blocked_options": blocked_options,
            "cause_map": cause_map,
            "helper_text_map": helper_text,
        }
