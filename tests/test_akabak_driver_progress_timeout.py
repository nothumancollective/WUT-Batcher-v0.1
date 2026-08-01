from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from app.akabak_driver import AkabakDriver, _solve_snapshot_made_progress


class AkabakDriverProgressTimeoutTests(unittest.TestCase):
    def test_completion_poll_uses_single_watchdog_pass(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.state = "running"
        driver.watchdog = Mock()
        driver.watchdog.handle_once.return_value = []
        driver.watchdog.run_watch.side_effect = AssertionError("bounded poll must not enter a timeout loop")
        driver.solve_context = {
            "baseline": {"akabak_pids": [100], "vacs_pids": []},
            "started": {"vacs_ui": {}},
        }
        driver.watchdog_events = []
        driver.solve_heartbeats = []
        driver.last_solve_diagnostics_path = None
        driver._connect = Mock()
        driver._log = Mock()
        driver._solve_signal_snapshot = Mock(
            return_value={
                "akabak_pids": [100],
                "vacs_pids": [],
                "progress_window_present": False,
                "vacs_ui": {},
            }
        )

        result = driver.wait_for_completion(timeout_s=1, require_vacs_graph_import=False)

        self.assertTrue(result.ok)
        driver.watchdog.handle_once.assert_called_once_with()
        driver.watchdog.run_watch.assert_not_called()

    def test_graphless_new_vacs_gets_one_bounded_f7_reimport(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.state = "running"
        driver.watchdog = None
        driver.solve_context = {
            "baseline": {"main_handle": 101, "akabak_pids": [100], "vacs_pids": []},
            "started": {"solve_command_enabled": False, "vacs_ui": {}},
        }
        driver.watchdog_events = []
        driver.solve_heartbeats = []
        driver.last_solve_diagnostics_path = None
        driver._connect = Mock()
        driver._log = Mock()
        driver._trigger_vacs_reimport_native = Mock(
            return_value={"trigger": "hwnd_postmessage_f7", "status": "sent", "main_handle": 101}
        )
        snapshots = iter(
            [
                {
                    "akabak_pids": [100],
                    "vacs_pids": [200],
                    "progress_window_present": False,
                    "vacs_ui": {"max_controls_count": 21, "max_graph_keyword_hits": 1},
                },
                {
                    "akabak_pids": [100],
                    "vacs_pids": [200],
                    "progress_window_present": False,
                    "vacs_ui": {"max_controls_count": 21, "max_graph_keyword_hits": 1},
                },
                {
                    "akabak_pids": [100],
                    "vacs_pids": [200],
                    "progress_window_present": False,
                    "vacs_ui": {"max_controls_count": 80, "max_graph_keyword_hits": 5},
                },
            ]
        )
        driver._solve_signal_snapshot = lambda: next(snapshots)

        with patch(
            "app.akabak_driver.time.perf_counter",
            side_effect=[0.0, 0.0, 0.0, 0.0, 0.0, 4.0, 4.0, 4.0, 4.0, 4.0],
        ), patch("app.akabak_driver.time.sleep"):
            result = driver.wait_for_completion(timeout_s=300, require_vacs_graph_import=True)

        self.assertTrue(result.ok)
        driver._trigger_vacs_reimport_native.assert_called_once_with(101)

    def test_completed_solve_starts_vacs_through_akabak_f7_handoff(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.state = "running"
        driver.watchdog = None
        driver.solve_context = {
            "baseline": {"main_handle": 101, "akabak_pids": [100], "vacs_pids": []},
            "started": {"solve_command_enabled": False, "vacs_ui": {}},
        }
        driver.watchdog_events = []
        driver.solve_heartbeats = []
        driver.last_solve_diagnostics_path = None
        driver._connect = Mock()
        driver._log = Mock()
        driver._start_vacs_for_handoff = Mock(
            return_value={
                "trigger": "hwnd_postmessage_f7",
                "status": "sent",
                "main_handle": 101,
                "method": "akabak_f7",
            }
        )
        driver._dismiss_vacs_startup_editors = Mock(return_value=[])
        driver._trigger_vacs_reimport_native = Mock()
        snapshots = iter(
            [
                {
                    "akabak_pids": [100],
                    "vacs_pids": [],
                    "progress_window_present": False,
                    "solve_command_enabled": True,
                    "vacs_ui": {},
                },
                {
                    "akabak_pids": [100],
                    "vacs_pids": [200],
                    "progress_window_present": False,
                    "vacs_ui": {"max_controls_count": 21, "max_graph_keyword_hits": 1},
                },
                {
                    "akabak_pids": [100],
                    "vacs_pids": [200],
                    "progress_window_present": False,
                    "vacs_ui": {"max_controls_count": 80, "max_graph_keyword_hits": 5},
                },
            ]
        )
        driver._solve_signal_snapshot = lambda: next(snapshots)

        with patch("app.akabak_driver.time.sleep"):
            result = driver.wait_for_completion(timeout_s=300, require_vacs_graph_import=True)

        self.assertTrue(result.ok)
        driver._start_vacs_for_handoff.assert_called_once_with(101)
        launch_log = next(
            call_row
            for call_row in driver._log.call_args_list
            if call_row.kwargs.get("event") == "vacs_handoff_launch"
        )
        self.assertEqual(launch_log.kwargs["payload"]["status"], "sent")
        driver._dismiss_vacs_startup_editors.assert_called_once_with([200])
        driver._trigger_vacs_reimport_native.assert_not_called()

    def test_delayed_solve_activation_defers_vacs_until_command_reenables(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.state = "running"
        driver.watchdog = None
        driver.solve_context = {
            "baseline": {"main_handle": 101, "akabak_pids": [100], "vacs_pids": []},
            "started": {
                "solve_command_enabled": True,
                "main_pid": 100,
                "akabak_cpu_times_s": {"100": 10.0},
                "vacs_ui": {},
            },
        }
        driver.watchdog_events = []
        driver.solve_heartbeats = []
        driver.last_solve_diagnostics_path = None
        driver._connect = Mock()
        driver._log = Mock()
        driver._start_vacs_for_handoff = Mock(
            return_value={
                "trigger": "hwnd_postmessage_f7",
                "status": "sent",
                "main_handle": 101,
                "method": "akabak_f7",
            }
        )
        driver._dismiss_vacs_startup_editors = Mock(return_value=[])
        driver._trigger_vacs_reimport_native = Mock()
        snapshots = iter(
            [
                {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.0},
                    "vacs_pids": [],
                    "progress_window_present": False,
                    "solve_command_enabled": True,
                    "vacs_ui": {},
                },
                {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.0},
                    "vacs_pids": [],
                    "progress_window_present": False,
                    "solve_command_enabled": False,
                    "vacs_ui": {},
                },
                {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.5},
                    "vacs_pids": [],
                    "progress_window_present": False,
                    "solve_command_enabled": True,
                    "vacs_ui": {},
                },
                {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.5},
                    "vacs_pids": [200],
                    "progress_window_present": False,
                    "solve_command_enabled": True,
                    "vacs_ui": {"max_controls_count": 80, "max_graph_keyword_hits": 5},
                },
            ]
        )
        driver._solve_signal_snapshot = lambda: next(snapshots)

        with patch("app.akabak_driver.time.sleep"):
            result = driver.wait_for_completion(timeout_s=300, require_vacs_graph_import=True)

        self.assertTrue(result.ok)
        driver._start_vacs_for_handoff.assert_called_once_with(101)
        driver._trigger_vacs_reimport_native.assert_not_called()

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
