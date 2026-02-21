from __future__ import annotations

import unittest

from scripts.vacs_export_save_all import _apply_exit_status, build_exit_status


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


if __name__ == "__main__":
    unittest.main()

