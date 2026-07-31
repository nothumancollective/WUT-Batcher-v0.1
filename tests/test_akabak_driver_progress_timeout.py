from __future__ import annotations

import unittest
from unittest.mock import patch

from app.akabak_driver import AkabakDriver, _solve_snapshot_made_progress


class AkabakDriverProgressTimeoutTests(unittest.TestCase):
    def test_worker_cpu_growth_counts_as_progress(self) -> None:
        previous = {
            "new_akabak_pids": [200],
            "worker_cpu_times_s": {"200": 10.0},
        }
        current = {
            "new_akabak_pids": [200],
            "worker_cpu_times_s": {"200": 10.2},
        }
        self.assertTrue(_solve_snapshot_made_progress(previous, current))

    def test_idle_worker_presence_does_not_count_as_progress(self) -> None:
        previous = {
            "new_akabak_pids": [200],
            "worker_cpu_times_s": {"200": 10.0},
        }
        current = {
            "new_akabak_pids": [200],
            "worker_cpu_times_s": {"200": 10.0},
        }
        self.assertFalse(_solve_snapshot_made_progress(previous, current))

    def test_main_process_cpu_growth_counts_as_progress(self) -> None:
        previous = {
            "main_pid": 100,
            "new_akabak_pids": [],
            "akabak_cpu_times_s": {"100": 470.1},
        }
        current = {
            "main_pid": 100,
            "new_akabak_pids": [],
            "akabak_cpu_times_s": {"100": 471.0},
        }
        self.assertTrue(_solve_snapshot_made_progress(previous, current))

    def test_new_worker_and_vacs_graph_growth_count_as_progress(self) -> None:
        self.assertTrue(
            _solve_snapshot_made_progress(
                {"new_akabak_pids": []},
                {"new_akabak_pids": [200]},
            )
        )

    def test_active_solver_gets_grace_window_and_can_complete(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.state = "running"
        driver.watchdog = None
        driver.solve_context = {
            "baseline": {"akabak_pids": [100], "vacs_pids": []},
            "started": {
                "new_akabak_pids": [200],
                "worker_cpu_times_s": {"200": 0.0},
                "vacs_ui": {},
            },
        }
        driver.watchdog_events = []
        driver.solve_heartbeats = []
        driver.last_solve_diagnostics_path = None
        driver._connect = lambda: None
        events: list[str] = []
        driver._log = lambda **payload: events.append(str(payload.get("event", "")))
        snapshots = iter(
            [
                {
                    "akabak_pids": [100, 200],
                    "vacs_pids": [],
                    "worker_cpu_times_s": {"200": 0.5},
                    "progress_window_present": False,
                    "vacs_ui": {},
                },
                {
                    "akabak_pids": [100, 200],
                    "vacs_pids": [],
                    "worker_cpu_times_s": {"200": 1.0},
                    "progress_window_present": False,
                    "vacs_ui": {},
                },
                {
                    "akabak_pids": [100],
                    "vacs_pids": [],
                    "worker_cpu_times_s": {},
                    "progress_window_present": False,
                    "vacs_ui": {},
                },
            ]
        )
        driver._solve_signal_snapshot = lambda: next(snapshots)

        with (
            patch(
                "app.akabak_driver.time.perf_counter",
                side_effect=[0.0, 0.0, 0.2, 0.2, 1.1, 1.1, 1.2, 1.2],
            ),
            patch("app.akabak_driver.time.sleep"),
        ):
            result = driver.wait_for_completion(timeout_s=1, require_vacs_graph_import=False)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertIn("active_solve_grace_window", events)
        self.assertTrue(
            _solve_snapshot_made_progress(
                {"new_akabak_pids": [], "vacs_ui": {"max_controls_count": 20}},
                {"new_akabak_pids": [], "vacs_ui": {"max_controls_count": 80}},
            )
        )


if __name__ == "__main__":
    unittest.main()
