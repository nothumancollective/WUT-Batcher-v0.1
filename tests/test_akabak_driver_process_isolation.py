from __future__ import annotations

import unittest

from app.akabak_driver import (
    AkabakDriver,
    _is_noninteractive_tool_window,
    _new_process_ids,
    _solve_heartbeat_payload,
    _title_matches_regex,
)


class AkabakDriverProcessIsolationTests(unittest.TestCase):
    def test_preexisting_akabak_pid_is_not_treated_as_new_worker(self) -> None:
        self.assertEqual(_new_process_ids([5048, 9940], {5048, 9940}), [])

    def test_only_process_started_after_baseline_is_a_worker_signal(self) -> None:
        self.assertEqual(_new_process_ids([5048, 9940, 12000], {5048, 9940}), [12000])

    def test_interpreter_title_match_ignores_windows_accelerator_marker(self) -> None:
        self.assertTrue(_title_matches_regex(r"start\s+importing", "Start &Importing"))

    def test_only_titleless_delphi_infrastructure_window_is_noninteractive(self) -> None:
        self.assertTrue(_is_noninteractive_tool_window({"title": "", "class_name": "TApplication"}))
        self.assertFalse(_is_noninteractive_tool_window({"title": "Save As", "class_name": "#32770"}))
        self.assertFalse(_is_noninteractive_tool_window({"title": "Helper", "class_name": "TApplication"}))

    def test_cleanup_ownership_excludes_preexisting_tool_processes(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.initial_akabak_pids = {5048}
        driver.initial_vacs_pids = {6000}
        driver.owned_akabak_pids = set()
        driver.owned_vacs_pids = set()
        driver._list_akabak_process_ids = lambda: [5048, 9940]
        driver._list_vacs_process_ids = lambda: [6000, 12000]

        owned = driver._refresh_owned_tool_process_ids()

        self.assertEqual(owned, {"akabak": [9940], "vacs": [12000]})
        self.assertNotIn(5048, driver.owned_akabak_pids)
        self.assertNotIn(6000, driver.owned_vacs_pids)

    def test_solve_heartbeat_keeps_compact_progress_signals(self) -> None:
        payload = _solve_heartbeat_payload(
            {
                "status": "waiting_vacs_graph_import",
                "main_pid": 7160,
                "akabak_pids": [7160],
                "new_akabak_pids": [],
                "akabak_cpu_times_s": {"7160": 470.1},
                "vacs_pids": [9308],
                "new_vacs_pids": [9308],
                "progress_window_present": False,
                "vacs_ui": {"max_controls_count": 42, "max_graph_keyword_hits": 3, "windows": {"large": "omitted"}},
            },
            elapsed_s=31.23456,
        )

        self.assertEqual(payload["elapsed_s"], 31.235)
        self.assertEqual(payload["status"], "waiting_vacs_graph_import")
        self.assertEqual(payload["akabak_pids"], [7160])
        self.assertEqual(payload["akabak_cpu_times_s"], {"7160": 470.1})
        self.assertEqual(payload["vacs_pids"], [9308])
        self.assertEqual(payload["vacs_max_controls_count"], 42)
        self.assertEqual(payload["vacs_max_graph_keyword_hits"], 3)
        self.assertNotIn("windows", payload)


if __name__ == "__main__":
    unittest.main()
