"""Recipe loading and schema validation for UI automation interactions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


REQUIRED_RECIPE_FIELDS = (
    "recipe_id",
    "version",
    "tool",
    "graph_type",
    "preconditions",
    "actions",
    "required_settings",
    "expected_output",
    "recovery_actions",
)

REQUIRED_ACTION_FIELDS = ("op", "selector")


class RecipeValidationError(ValueError):
    pass


def _ensure_selector(value: Any, *, field_name: str) -> None:
    if not isinstance(value, dict):
        raise RecipeValidationError(f"{field_name} must be an object.")
    selector_keys = {"automation_id", "control_type", "class_name_regex", "title_regex", "title", "path"}
    if not any(key in value for key in selector_keys):
        raise RecipeValidationError(
            f"{field_name} must provide at least one selector key "
            f"({', '.join(sorted(selector_keys))})."
        )


def validate_recipe(recipe: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    for field in REQUIRED_RECIPE_FIELDS:
        if field not in recipe:
            raise RecipeValidationError(f"Missing recipe field: {field}")

    actions = recipe.get("actions")
    if not isinstance(actions, list) or not actions:
        raise RecipeValidationError("actions must be a non-empty list.")
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise RecipeValidationError(f"actions[{index}] must be an object.")
        for action_field in REQUIRED_ACTION_FIELDS:
            if action_field not in action:
                raise RecipeValidationError(f"actions[{index}] missing field: {action_field}")
        _ensure_selector(action.get("selector"), field_name=f"actions[{index}].selector")

    preconditions = recipe.get("preconditions")
    if not isinstance(preconditions, dict):
        raise RecipeValidationError("preconditions must be an object.")
    window_signature = preconditions.get("window_signature")
    if not isinstance(window_signature, str) or not window_signature.strip():
        raise RecipeValidationError("preconditions.window_signature is required.")

    required_settings = recipe.get("required_settings")
    if not isinstance(required_settings, list):
        raise RecipeValidationError("required_settings must be a list.")
    for index, setting in enumerate(required_settings):
        if not isinstance(setting, dict):
            raise RecipeValidationError(f"required_settings[{index}] must be an object.")
        if "key" not in setting:
            raise RecipeValidationError(f"required_settings[{index}].key is required.")
        if "selector" in setting:
            _ensure_selector(setting["selector"], field_name=f"required_settings[{index}].selector")
        else:
            warnings.append(f"required_settings[{index}] has no selector.")

    expected_output = recipe.get("expected_output")
    if not isinstance(expected_output, dict):
        raise RecipeValidationError("expected_output must be an object.")
    if "file_pattern" not in expected_output:
        raise RecipeValidationError("expected_output.file_pattern is required.")

    recovery_actions = recipe.get("recovery_actions")
    if not isinstance(recovery_actions, list):
        raise RecipeValidationError("recovery_actions must be a list.")
    for index, action in enumerate(recovery_actions):
        if not isinstance(action, dict):
            raise RecipeValidationError(f"recovery_actions[{index}] must be an object.")
        if "when" not in action or "actions" not in action:
            raise RecipeValidationError(f"recovery_actions[{index}] requires 'when' and 'actions'.")

    return warnings


def _load_recipe(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecipeValidationError(f"Invalid JSON in recipe {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RecipeValidationError(f"Recipe payload must be an object: {path}")
    return payload


def load_recipes(directory: str | Path) -> List[Dict[str, Any]]:
    root = Path(directory)
    if not root.exists():
        return []
    recipes: List[Dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        recipe = _load_recipe(path)
        warnings = validate_recipe(recipe)
        recipe["_path"] = str(path)
        recipe["_warnings"] = warnings
        recipes.append(recipe)
    return recipes


def load_vacs_export_recipes() -> List[Dict[str, Any]]:
    return load_recipes(Path("ui_recipes") / "vacs")


def recipe_index_by_id(recipes: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for recipe in recipes:
        recipe_id = str(recipe.get("recipe_id", "")).strip()
        if not recipe_id:
            continue
        index[recipe_id] = recipe
    return index


def validate_recipe_directory(directory: str | Path) -> Tuple[int, int]:
    recipes = load_recipes(directory)
    warning_count = sum(len(list(recipe.get("_warnings", []) or [])) for recipe in recipes)
    return len(recipes), warning_count
