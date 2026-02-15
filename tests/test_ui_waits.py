from __future__ import annotations

import time
import unittest

from app.ui_automation.waits import wait_until


class UiWaitsTests(unittest.TestCase):
    def test_wait_until_returns_when_predicate_matches(self) -> None:
        state = {"count": 0}

        def predicate():
            state["count"] += 1
            return (state["count"] >= 3, state["count"])

        value = wait_until(predicate=predicate, timeout_s=2.0, initial_interval_s=0.01, max_interval_s=0.05)
        self.assertEqual(value, 3)

    def test_wait_until_times_out(self) -> None:
        started = time.perf_counter()

        def predicate():
            return (False, None)

        with self.assertRaises(TimeoutError):
            wait_until(predicate=predicate, timeout_s=0.1, initial_interval_s=0.01, max_interval_s=0.02)
        self.assertGreaterEqual(time.perf_counter() - started, 0.08)


if __name__ == "__main__":
    unittest.main()
