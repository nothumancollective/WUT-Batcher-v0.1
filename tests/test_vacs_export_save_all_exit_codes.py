from __future__ import annotations

import unittest
from argparse import Namespace
from unittest.mock import patch

from scripts.vacs_export_save_all import _apply_exit_status, build_exit_status, run_once


class VacsExportSaveAllExitCodeTests(unittest.TestCase):
    def test_partial_success_without_required_pattern_is_not_hard_failure(self) -> None:
        payload = {
            "per_graph": [
                {
                    "loop": 1,
                    "target": {"title": "Mic Polar - BE_Spectrum #2"},
                    "file_postcondition": {"ok": True, "path": "run_01.txt"},
                },
                {
                    "loop": 2,
                    "target": {"title": "Mic Polar - BE_Spectrum #3"},
                    "file_postcondition": {"ok": True, "path": "run_02.txt"},
                },
                {
                    "loop": 3,
                    "target": {"title": "Mic Polar - BE_Spectrum #4"},
                    "file_postcondition": {"ok": True, "path": "run_03.txt"},
                },
                {
                    "loop": 4,
                    "target": {"title": "Radiation Impedance - Radiation_Impedance #5"},
                    "error": "export_configuration_invalid",
                },
            ],
            "exported_files": [{"path": "run_01.txt"}, {"path": "run_02.txt"}, {"path": "run_03.txt"}],
        }
        status = build_exit_status(payload, min_successful_exports=1, required_graph_title_regex="")
        self.assertFalse(bool(status.get("hard_failure")))
        self.assertEqual(int(status.get("exported_ok_count", -1)), 3)
        self.assertEqual(int(status.get("exported_failed_count", -1)), 1)
        self.assertEqual(int(status.get("verification_ok_count", -1)), 3)
        self.assertEqual(int(status.get("verification_failed_count", -1)), 1)
        top = list(status.get("top_failure_reasons", []) or [])
        self.assertTrue(top)
        self.assertEqual(str(top[0].get("reason", "")), "export_configuration_invalid")

    def test_required_graph_failure_is_hard_failure(self) -> None:
        payload = {
            "per_graph": [
                {
                    "loop": 1,
                    "target": {"title": "Mic Polar - BE_Spectrum #2"},
                    "error": "export_configuration_invalid",
                }
            ],
            "exported_files": [],
        }
        status = build_exit_status(
            payload,
            min_successful_exports=1,
            required_graph_title_regex=r"mic\s*polar",
        )
        self.assertTrue(bool(status.get("hard_failure")))
        hard = list(status.get("hard_failure_reasons", []) or [])
        self.assertIn("required_graph_failed", hard)

    def test_top_level_startup_error_stays_hard_failure(self) -> None:
        payload = {"error": "vacs_main_missing", "per_graph": [], "exported_files": []}
        _apply_exit_status(payload, min_successful_exports=1, required_graph_title_regex="")
        self.assertFalse(bool(payload.get("ok", True)))
        summary = dict(payload.get("final_summary") or {})
        self.assertTrue(bool(summary.get("hard_failure")))
        hard = list(summary.get("hard_failure_reasons", []) or [])
        self.assertIn("fatal:vacs_main_missing", hard)

    def test_auto_mode_preserves_actionable_graph_export_failure(self) -> None:
        fast = {
            "ok": False,
            "error": "required_graph_export_failed",
            "per_graph": [{"loop": 1, "error": "export_file_missing_or_empty"}],
            "summary_file": "fast-summary.json",
        }
        with (
            patch("scripts.vacs_export_save_all.run_once_fast", return_value=fast),
            patch("scripts.vacs_export_save_all.run_once_safe") as safe,
        ):
            result = run_once(Namespace(mode="auto"))

        safe.assert_not_called()
        self.assertIs(result, fast)
        self.assertFalse(bool(result.get("fallback_used")))
        self.assertEqual(result.get("fallback_skipped_reason"), "fast_path_reached_graph_export")
        self.assertEqual(result["per_graph"][0]["error"], "export_file_missing_or_empty")

    def test_auto_mode_still_falls_back_for_readiness_failure(self) -> None:
        fast = {"ok": False, "error": "vacs_not_ready_after_f4", "summary_file": "fast-summary.json"}
        safe_result = {"ok": True, "summary_file": "safe-summary.json", "run_id": "safe-run"}
        with (
            patch("scripts.vacs_export_save_all.run_once_fast", return_value=fast),
            patch("scripts.vacs_export_save_all.run_once_safe", return_value=safe_result) as safe,
        ):
            result = run_once(Namespace(mode="auto"))

        safe.assert_called_once()
        self.assertIs(result, safe_result)
        self.assertTrue(bool(result.get("fallback_used")))
        self.assertEqual(result.get("fallback_reason"), "fast_mode_failed")


if __name__ == "__main__":
    unittest.main()

