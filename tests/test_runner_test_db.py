from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.runner_test_db import RunnerTestDb


class RunnerTestDbTests(unittest.TestCase):
    def test_init_creates_required_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = RunnerTestDb(Path(tmp_dir) / "runner_test.sqlite")
            self.assertEqual(db.count_rows("test_runs"), 0)
            self.assertEqual(db.count_rows("test_cases"), 0)
            self.assertEqual(db.count_rows("runs"), 0)
            self.assertEqual(db.count_rows("versions"), 0)
            self.assertEqual(db.count_rows("graphs"), 0)
            self.assertEqual(db.count_rows("graph_series"), 0)
            self.assertEqual(db.count_rows("graph_points"), 0)

    def test_persists_test_run_and_step_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = RunnerTestDb(Path(tmp_dir) / "runner_test.sqlite")
            db.upsert_test_case(
                case_id="smoke_fast",
                name="Smoke Fast",
                description="Minimal smoke case",
                constraints_json={"fixed_params": {"Length": 120}},
            )
            db.create_test_run(
                test_run_id="run-1",
                status="running",
                machine_info={"os": "windows"},
            )
            db.add_test_run_step(
                test_run_id="run-1",
                step_name="preflight",
                status="ok",
                details={"tool_check": "ok"},
            )
            db.add_validation(
                test_run_id="run-1",
                validation_name="export_non_empty",
                status="ok",
                metrics={"bytes": 1234},
            )
            db.finish_test_run(test_run_id="run-1", status="succeeded")

            self.assertEqual(db.count_rows("test_cases"), 1)
            self.assertEqual(db.count_rows("test_runs"), 1)
            self.assertEqual(db.count_rows("test_run_steps"), 1)
            self.assertEqual(db.count_rows("validations"), 1)
            rows = db.list_test_runs()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["test_run_id"], "run-1")
            self.assertEqual(rows[0]["status"], "succeeded")

    def test_write_measurements_persists_graph_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = RunnerTestDb(Path(tmp_dir) / "runner_test.sqlite")
            rows = [
                {
                    "project_id": "PTEST",
                    "batch_id": "BTEST",
                    "run_id": "run-1",
                    "version_id": "V001",
                    "graph_type": "SPL",
                    "graph_kind": "spl",
                    "variant": "default",
                    "x_name": "Frequency",
                    "y_name": "SPL",
                    "x_axis": "Frequency",
                    "y_axis": "SPL",
                    "x_unit": "Hz",
                    "y_unit": "dB",
                    "series_kind": "curve",
                    "series_label": "default",
                    "x_value": 100.0,
                    "y_value": 90.5,
                    "point_index": 0,
                    "source_file": "C:/tmp/Result_V001SPL.txt",
                    "export_meta": {"point_count": 2},
                    "meta_json": {"point_count": 2},
                },
                {
                    "project_id": "PTEST",
                    "batch_id": "BTEST",
                    "run_id": "run-1",
                    "version_id": "V001",
                    "graph_type": "SPL",
                    "graph_kind": "spl",
                    "variant": "default",
                    "x_name": "Frequency",
                    "y_name": "SPL",
                    "x_axis": "Frequency",
                    "y_axis": "SPL",
                    "x_unit": "Hz",
                    "y_unit": "dB",
                    "series_kind": "curve",
                    "series_label": "default",
                    "x_value": 200.0,
                    "y_value": 91.0,
                    "point_index": 1,
                    "source_file": "C:/tmp/Result_V001SPL.txt",
                    "export_meta": {"point_count": 2},
                    "meta_json": {"point_count": 2},
                },
            ]
            result = db.write_measurements(rows)
            self.assertEqual(result["graphs_written"], 1)
            self.assertEqual(result["series_written"], 1)
            self.assertEqual(result["points_written"], 2)
            self.assertEqual(db.count_rows("graphs"), 1)
            self.assertEqual(db.count_rows("graph_series"), 1)
            self.assertEqual(db.count_rows("graph_points"), 2)


if __name__ == "__main__":
    unittest.main()
