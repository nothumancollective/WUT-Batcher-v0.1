from __future__ import annotations

import unittest

from app.akabak_driver import _new_process_ids


class AkabakDriverProcessIsolationTests(unittest.TestCase):
    def test_preexisting_akabak_pid_is_not_treated_as_new_worker(self) -> None:
        self.assertEqual(_new_process_ids([5048, 9940], {5048, 9940}), [])

    def test_only_process_started_after_baseline_is_a_worker_signal(self) -> None:
        self.assertEqual(_new_process_ids([5048, 9940, 12000], {5048, 9940}), [12000])


if __name__ == "__main__":
    unittest.main()
