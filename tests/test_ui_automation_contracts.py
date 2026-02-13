from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.ui_automation.inspector import inspect_tool_ui
from app.ui_automation.recipes import load_vacs_export_recipes, validate_recipe_directory
from app.ui_contracts.window_signatures import WINDOW_SIGNATURES


class UiAutomationContractsTests(unittest.TestCase):
    def test_vacs_recipe_directory_is_valid(self) -> None:
        count, warnings = validate_recipe_directory(Path("ui_recipes") / "vacs")
        self.assertGreaterEqual(count, 1)
        self.assertGreaterEqual(warnings, 0)

    def test_vacs_recipes_define_required_contract_fields(self) -> None:
        recipes = load_vacs_export_recipes()
        self.assertGreaterEqual(len(recipes), 1)
        for recipe in recipes:
            self.assertIn("recipe_id", recipe)
            self.assertIn("actions", recipe)
            self.assertIn("expected_output", recipe)
            self.assertIsInstance(recipe.get("actions"), list)
            self.assertIsInstance(recipe.get("required_settings"), list)

    def test_window_signatures_not_title_only(self) -> None:
        self.assertGreaterEqual(len(WINDOW_SIGNATURES), 1)
        for signature in WINDOW_SIGNATURES.values():
            self.assertTrue(signature.process_names)
            self.assertTrue(signature.class_name_regex or signature.control_type)

    def test_inspector_dry_run_writes_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = inspect_tool_ui(
                tool_name="akabak",
                executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                output_root=tmp_dir,
                dry_run=True,
            )
            self.assertTrue(payload["dry_run"])
            summary_path = Path(payload["summary_path"])
            self.assertTrue(summary_path.exists())


if __name__ == "__main__":
    unittest.main()
