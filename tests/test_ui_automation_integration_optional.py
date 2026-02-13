from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from app.ui_automation.inspector import inspect_tool_ui


@unittest.skipUnless(os.environ.get("WUT_UIA_INTEGRATION") == "1", "Optional UIA integration tests are disabled.")
class UiAutomationIntegrationOptionalTests(unittest.TestCase):
    def test_inspect_akabak_real_process(self) -> None:
        exe = os.environ.get("WUT_AKABAK_EXE")
        self.assertTrue(exe, "Set WUT_AKABAK_EXE for integration tests.")
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = inspect_tool_ui(
                tool_name="akabak",
                executable=exe,
                output_root=tmp_dir,
                dry_run=False,
            )
            self.assertNotIn("error", payload)
            self.assertGreaterEqual(int(payload.get("window_count", 0)), 1)

    def test_inspect_vacs_real_process(self) -> None:
        exe = os.environ.get("WUT_VACS_EXE")
        self.assertTrue(exe, "Set WUT_VACS_EXE for integration tests.")
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = inspect_tool_ui(
                tool_name="vacs",
                executable=exe,
                output_root=tmp_dir,
                dry_run=False,
            )
            self.assertNotIn("error", payload)
            self.assertGreaterEqual(int(payload.get("window_count", 0)), 1)


if __name__ == "__main__":
    unittest.main()
