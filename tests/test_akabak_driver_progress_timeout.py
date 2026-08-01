from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from app.akabak_driver import AkabakDriver, _solve_snapshot_made_progress, _vacs_reimport_retry_due_s


class AkabakDriverProgressTimeoutTests(unittest.TestCase):
    def test_vacs_reimport_schedule_is_bounded_and_waits_for_readiness(self) -> None:
        self.assertIsNone(_vacs_reimport_retry_due_s(attempt_count=0, graphless_s=2.99))
        self.assertEqual(_vacs_reimport_retry_due_s(attempt_count=0, graphless_s=3.0), 3.0)
        self.assertIsNone(_vacs_reimport_retry_due_s(attempt_count=1, graphless_s=14.99))
        self.assertEqual(_vacs_reimport_retry_due_s(attempt_count=1, graphless_s=15.0), 15.0)
        self.assertEqual(_vacs_reimport_retry_due_s(attempt_count=2, graphless_s=45.0), 45.0)
        self.assertEqual(_vacs_reimport_retry_due_s(attempt_count=3, graphless_s=90.0), 90.0)
        self.assertEqual(_vacs_reimport_retry_due_s(attempt_count=4, graphless_s=180.0), 180.0)
        self.assertEqual(_vacs_reimport_retry_due_s(attempt_count=5, graphless_s=300.0), 300.0)
        self.assertIsNone(_vacs_reimport_retry_due_s(attempt_count=6, graphless_s=600.0))

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

    def test_graphless_vacs_retries_f7_after_delayed_com_dialogs(self) -> None:
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
            return_value={"trigger": "hwnd_postmessage_f7", "status": "sent", "main_handle": 101}
        )
        driver._trigger_vacs_reimport_native = Mock(
            return_value={"trigger": "hwnd_postmessage_f7", "status": "sent", "main_handle": 101}
        )
        driver._dismiss_vacs_startup_editors = Mock(return_value=[])
        clock = [0.0]
        rows = iter(
            [
                (0.0, {"vacs_pids": [], "solve_command_enabled": True, "vacs_ui": {}}),
                (0.0, {"vacs_pids": [200], "solve_command_enabled": True, "vacs_ui": {}}),
                (4.0, {"vacs_pids": [200], "solve_command_enabled": True, "vacs_ui": {}}),
                (16.0, {"vacs_pids": [200], "solve_command_enabled": True, "vacs_ui": {}}),
                (30.0, {"vacs_pids": [200], "solve_command_enabled": False, "vacs_ui": {}}),
                (46.0, {"vacs_pids": [200], "solve_command_enabled": True, "vacs_ui": {}}),
                (
                    46.0,
                    {
                        "vacs_pids": [200],
                        "solve_command_enabled": True,
                        "vacs_ui": {"max_controls_count": 80, "max_graph_keyword_hits": 5},
                    },
                ),
            ]
        )

        def _next_snapshot() -> dict:
            at_s, row = next(rows)
            clock[0] = at_s
            return {
                "main_pid": 100,
                "akabak_pids": [100],
                "progress_window_present": False,
                **row,
            }

        driver._solve_signal_snapshot = _next_snapshot

        with patch("app.akabak_driver.SOLVE_COMMAND_REENABLE_STABLE_S", 0.0), patch(
            "app.akabak_driver.time.perf_counter", side_effect=lambda: clock[0]
        ), patch("app.akabak_driver.time.sleep"):
            result = driver.wait_for_completion(timeout_s=300, require_vacs_graph_import=True)

        self.assertTrue(result.ok)
        self.assertEqual(driver._trigger_vacs_reimport_native.call_count, 3)
        driver._trigger_vacs_reimport_native.assert_called_with(101)
        reimport_logs = [
            call_row.kwargs["payload"]
            for call_row in driver._log.call_args_list
            if call_row.kwargs.get("event") == "vacs_reimport_triggered"
        ]
        self.assertEqual([row["attempt_count"] for row in reimport_logs], [1, 2, 3])

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

        with patch("app.akabak_driver.SOLVE_COMMAND_REENABLE_STABLE_S", 0.0), patch(
            "app.akabak_driver.time.sleep"
        ):
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

    def test_missing_vacs_process_retries_bounded_f7_handoff(self) -> None:
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
            side_effect=[
                {
                    "trigger": "hwnd_postmessage_f7",
                    "status": status,
                    "main_handle": 101,
                    "method": "akabak_f7",
                }
                for status in ("rejected", "sent", "sent", "sent")
            ]
        )
        driver._dismiss_vacs_startup_editors = Mock(return_value=[])
        driver._trigger_vacs_reimport_native = Mock()
        clock = [0.0]
        rows = iter(
            [
                (0.0, {"vacs_pids": [], "vacs_ui": {}}),
                (2.0, {"vacs_pids": [], "vacs_ui": {}}),
                (4.0, {"vacs_pids": [], "vacs_ui": {}}),
                (16.0, {"vacs_pids": [], "vacs_ui": {}}),
                (46.0, {"vacs_pids": [], "vacs_ui": {}}),
                (
                    47.0,
                    {
                        "vacs_pids": [200],
                        "vacs_ui": {"max_controls_count": 80, "max_graph_keyword_hits": 5},
                    },
                ),
            ]
        )

        def _next_snapshot() -> dict:
            at_s, row = next(rows)
            clock[0] = at_s
            return {
                "main_pid": 100,
                "akabak_pids": [100],
                "progress_window_present": False,
                "solve_command_enabled": True,
                **row,
            }

        driver._solve_signal_snapshot = _next_snapshot

        with patch("app.akabak_driver.SOLVE_COMMAND_REENABLE_STABLE_S", 0.0), patch(
            "app.akabak_driver.time.perf_counter", side_effect=lambda: clock[0]
        ), patch("app.akabak_driver.time.sleep"):
            result = driver.wait_for_completion(timeout_s=300, require_vacs_graph_import=True)

        self.assertTrue(result.ok)
        self.assertEqual(driver._start_vacs_for_handoff.call_count, 4)
        rejected_logs = [
            call_row.kwargs["payload"]
            for call_row in driver._log.call_args_list
            if call_row.kwargs.get("event") == "vacs_handoff_rejected"
        ]
        self.assertEqual([row["attempt_count"] for row in rejected_logs], [1])
        launch_logs = [
            call_row.kwargs["payload"]
            for call_row in driver._log.call_args_list
            if call_row.kwargs.get("event") in {"vacs_handoff_launch", "vacs_handoff_retry"}
        ]
        self.assertEqual([row["attempt_count"] for row in launch_logs], [2, 3, 4])
        driver._trigger_vacs_reimport_native.assert_not_called()

    def test_unknown_menu_state_after_busy_signal_does_not_complete_early(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.state = "running"
        driver.watchdog = None
        driver.solve_context = {
            "baseline": {"main_handle": 101, "akabak_pids": [100], "vacs_pids": []},
            "started": {
                "solve_command_enabled": False,
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
        snapshot_count = [0]

        def _launch_only_after_authoritative_reenable(main_handle: int) -> dict:
            self.assertEqual(main_handle, 202)
            self.assertGreaterEqual(snapshot_count[0], 4)
            return {
                "trigger": "hwnd_postmessage_f7",
                "status": "sent",
                "main_handle": main_handle,
                "method": "akabak_f7",
            }

        driver._start_vacs_for_handoff = Mock(side_effect=_launch_only_after_authoritative_reenable)
        driver._dismiss_vacs_startup_editors = Mock(return_value=[])
        driver._trigger_vacs_reimport_native = Mock()
        clock = [0.0]
        rows = iter(
            [
                (0.0, None, [], {}),
                (1.0, False, [], {}),
                (2.0, True, [], {}),
                (6.0, True, [], {}),
                (7.0, True, [200], {"max_controls_count": 80, "max_graph_keyword_hits": 5}),
            ]
        )

        def _next_snapshot() -> dict:
            at_s, menu_state, vacs_pids, vacs_ui = next(rows)
            clock[0] = at_s
            snapshot_count[0] += 1
            return {
                "main_pid": 100,
                "akabak_pids": [100],
                "akabak_cpu_times_s": {"100": 10.0},
                "vacs_pids": vacs_pids,
                "progress_window_present": False,
                "solve_command_enabled": menu_state,
                "solve_main_handle": 202,
                "vacs_ui": vacs_ui,
            }

        driver._solve_signal_snapshot = _next_snapshot

        with patch("app.akabak_driver.time.perf_counter", side_effect=lambda: clock[0]), patch(
            "app.akabak_driver.time.sleep"
        ):
            result = driver.wait_for_completion(timeout_s=300, require_vacs_graph_import=True)

        self.assertTrue(result.ok)
        driver._start_vacs_for_handoff.assert_called_once_with(202)

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
        snapshot_count = [0]

        def _launch_after_quiescence(_main_handle: int) -> dict:
            self.assertGreaterEqual(snapshot_count[0], 6)
            return {
                "trigger": "hwnd_postmessage_f7",
                "status": "sent",
                "main_handle": 101,
                "method": "akabak_f7",
            }

        driver._start_vacs_for_handoff = Mock(side_effect=_launch_after_quiescence)
        driver._dismiss_vacs_startup_editors = Mock(return_value=[])
        driver._trigger_vacs_reimport_native = Mock()
        clock = [0.0]
        snapshots = iter(
            [
                (0.0, {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.0},
                    "vacs_pids": [],
                    "progress_window_present": False,
                    "solve_command_enabled": True,
                    "vacs_ui": {},
                }),
                (1.0, {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.0},
                    "vacs_pids": [],
                    "progress_window_present": False,
                    "solve_command_enabled": False,
                    "vacs_ui": {},
                }),
                (2.0, {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.5},
                    "vacs_pids": [],
                    "progress_window_present": False,
                    "solve_command_enabled": True,
                    "vacs_ui": {},
                }),
                (3.0, {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.7},
                    "vacs_pids": [],
                    "progress_window_present": False,
                    "solve_command_enabled": True,
                    "vacs_ui": {},
                }),
                (4.0, {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.7},
                    "vacs_pids": [],
                    "progress_window_present": False,
                    "solve_command_enabled": True,
                    "vacs_ui": {},
                }),
                (6.0, {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.7},
                    "vacs_pids": [],
                    "progress_window_present": False,
                    "solve_command_enabled": True,
                    "vacs_ui": {},
                }),
                (6.0, {
                    "main_pid": 100,
                    "akabak_pids": [100],
                    "akabak_cpu_times_s": {"100": 10.7},
                    "vacs_pids": [200],
                    "progress_window_present": False,
                    "solve_command_enabled": True,
                    "vacs_ui": {"max_controls_count": 80, "max_graph_keyword_hits": 5},
                }),
            ]
        )

        def _next_snapshot() -> dict:
            at_s, row = next(snapshots)
            clock[0] = at_s
            snapshot_count[0] += 1
            return row

        driver._solve_signal_snapshot = _next_snapshot

        with patch("app.akabak_driver.time.perf_counter", side_effect=lambda: clock[0]), patch(
            "app.akabak_driver.time.sleep"
        ):
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

    def test_long_solve_gets_fresh_bounded_vacs_handoff_budget(self) -> None:
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
        clock = [0.0]
        snapshots = iter(
            [
                (
                    19.0,
                    {
                        "akabak_pids": [100],
                        "vacs_pids": [],
                        "progress_window_present": False,
                        "solve_command_enabled": True,
                        "vacs_ui": {},
                    },
                ),
                (
                    21.0,
                    {
                        "akabak_pids": [100],
                        "vacs_pids": [200],
                        "progress_window_present": False,
                        "solve_command_enabled": True,
                        "vacs_ui": {"max_controls_count": 21, "max_graph_keyword_hits": 1},
                    },
                ),
                (
                    25.0,
                    {
                        "akabak_pids": [100],
                        "vacs_pids": [200],
                        "progress_window_present": False,
                        "solve_command_enabled": True,
                        "vacs_ui": {"max_controls_count": 80, "max_graph_keyword_hits": 5},
                    },
                ),
            ]
        )

        def _next_snapshot() -> dict:
            at_s, row = next(snapshots)
            clock[0] = at_s
            return row

        driver._solve_signal_snapshot = _next_snapshot

        with patch("app.akabak_driver.SOLVE_COMMAND_REENABLE_STABLE_S", 0.0), patch(
            "app.akabak_driver.time.perf_counter", side_effect=lambda: clock[0]
        ), patch("app.akabak_driver.time.sleep"):
            result = driver.wait_for_completion(timeout_s=10, require_vacs_graph_import=True)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        driver._start_vacs_for_handoff.assert_called_once_with(101)
        self.assertTrue(
            any(
                call_row.kwargs.get("event") == "post_solve_vacs_budget_started"
                for call_row in driver._log.call_args_list
            )
        )

    def test_post_solve_vacs_reimport_budget_remains_bounded(self) -> None:
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
        driver._trigger_vacs_reimport_native = Mock(
            return_value={"trigger": "hwnd_postmessage_f7", "status": "sent", "main_handle": 101}
        )
        clock = [0.0]
        graphless = {
            "akabak_pids": [100],
            "vacs_pids": [200],
            "progress_window_present": False,
            "solve_command_enabled": True,
            "vacs_ui": {"max_controls_count": 21, "max_graph_keyword_hits": 1},
        }
        rows = iter(
            [
                (0.0, {**graphless, "vacs_pids": [], "vacs_ui": {}}),
                (0.0, graphless),
                (4.0, graphless),
                (16.0, graphless),
                (46.0, graphless),
                (91.0, graphless),
                (181.0, graphless),
                (301.0, graphless),
                (331.0, graphless),
            ]
        )

        def _next_snapshot() -> dict:
            at_s, row = next(rows)
            clock[0] = at_s
            return dict(row)

        driver._solve_signal_snapshot = _next_snapshot

        with patch("app.akabak_driver.SOLVE_COMMAND_REENABLE_STABLE_S", 0.0), patch(
            "app.akabak_driver.time.perf_counter", side_effect=lambda: clock[0]
        ), patch("app.akabak_driver.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "remained graphless"):
                driver.wait_for_completion(timeout_s=10, require_vacs_graph_import=True)

        self.assertEqual(driver._trigger_vacs_reimport_native.call_count, 6)


if __name__ == "__main__":
    unittest.main()
