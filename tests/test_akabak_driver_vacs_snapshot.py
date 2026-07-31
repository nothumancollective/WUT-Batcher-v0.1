from __future__ import annotations

import unittest

from app.akabak_driver import AkabakDriver


class AkabakDriverVacsSnapshotTests(unittest.TestCase):
    def test_polling_snapshot_uses_native_metrics_without_uia_tree(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver._list_vacs_process_ids = lambda: [101, 202]
        native_calls: list[int] = []

        def native_metrics(process_id: int):
            native_calls.append(process_id)
            return [
                {
                    "title": "VacsViewer",
                    "class_name": "TForm_DatMain",
                    "controls_count": 22 if process_id == 101 else 151,
                    "graph_keyword_hits": 1 if process_id == 101 else 9,
                }
            ]

        driver._native_vacs_window_metrics = native_metrics
        driver._process_top_level_windows = lambda **_: self.fail("UIA polling must not run")

        snapshot = driver._vacs_ui_snapshot()

        self.assertEqual(native_calls, [101, 202])
        self.assertEqual(snapshot["pids"], [101, 202])
        self.assertEqual(snapshot["max_controls_count"], 151)
        self.assertEqual(snapshot["max_graph_keyword_hits"], 9)
        self.assertEqual(snapshot["snapshot_backend"], "win32_hwnd")


if __name__ == "__main__":
    unittest.main()
