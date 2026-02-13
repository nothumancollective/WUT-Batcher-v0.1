from __future__ import annotations

from contextlib import closing
import sqlite3
import tempfile
import unittest

from app.projectpage_ath_experiment import (
    _backfill_legacy_null_run_groups,
    _ensure_db_schema,
    classify_ath_output,
    generate_experiment_cases,
    parse_ath_output_metrics,
)


class ProjectPageAthExperimentTests(unittest.TestCase):
    def test_parse_ath_output_metrics_mm(self) -> None:
        stdout = (
            "Device width x height = 419.20 x 419.20 mm\n"
            "Device length = 130.00 mm\n"
            "-average mesh throat angle: 4.200 deg\n"
        )
        payload = parse_ath_output_metrics(stdout, "")
        self.assertAlmostEqual(float(payload["final_width_mm"]), 419.2, places=3)
        self.assertAlmostEqual(float(payload["final_height_mm"]), 419.2, places=3)
        self.assertAlmostEqual(float(payload["final_length_mm"]), 130.0, places=3)
        self.assertAlmostEqual(float(payload["avg_throat_angle_deg"]), 4.2, places=3)
        self.assertIsNotNone(payload["derived_volume_m3"])

    def test_parse_ath_output_metrics_meter_unit(self) -> None:
        stdout = "Final width x height = 0.45 x 0.30 m\nFinal length = 0.80 m\n"
        payload = parse_ath_output_metrics(stdout, "")
        self.assertAlmostEqual(float(payload["final_width_mm"]), 450.0, places=3)
        self.assertAlmostEqual(float(payload["final_height_mm"]), 300.0, places=3)
        self.assertAlmostEqual(float(payload["final_length_mm"]), 800.0, places=3)

    def test_classify_ath_output_known_fatal_pattern(self) -> None:
        stderr = "Fatal: The rollback feature is no longer supported. Use R-OSSE profile instead."
        result = classify_ath_output("", stderr, exit_code=2)
        self.assertEqual(result["ath_error_kind"], "rollback_not_supported")
        self.assertEqual(int(result["ath_warning_count"]), 0)

    def test_generator_avoids_rollback_keys(self) -> None:
        cases = generate_experiment_cases(
            cases=40,
            seed=1337,
            max_dim_mm=2000.0,
            hard_cap_mm=5000.0,
            prior_ranges={},
        )
        self.assertEqual(len(cases), 40)
        first = cases[0].case.field_values
        second = generate_experiment_cases(
            cases=40,
            seed=1337,
            max_dim_mm=2000.0,
            hard_cap_mm=5000.0,
            prior_ranges={},
        )[0].case.field_values
        self.assertEqual(first, second)
        for item in cases:
            keys = {str(key) for key, _ in item.case.field_values}
            self.assertFalse(any(key.startswith("Rollback") for key in keys))

    def test_db_schema_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = f"{tmp_dir}/exp.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                _ensure_db_schema(conn)
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertIn("experiment_runs", tables)
                self.assertIn("experiment_params", tables)
                self.assertIn("experiment_metrics", tables)
                self.assertIn("experiment_compare", tables)

    def test_backfill_legacy_null_run_groups_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = f"{tmp_dir}/exp.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                _ensure_db_schema(conn)
                rows = [
                    ("r1", None, "2026-01-01T00:00:00Z", 1337, 1, "ok"),
                    ("r2", None, "2026-01-01T00:00:01Z", 1337, 1, "ath_error"),
                    ("r3", None, "2026-01-01T00:00:02Z", 1337, 2, "ok"),
                    ("r4", None, "2026-01-01T00:00:03Z", 2026, 1, "ok"),
                    ("r5", None, "2026-01-01T00:00:04Z", 2026, 1, "ath_error"),
                ]
                conn.executemany(
                    """
                    INSERT INTO experiment_runs(
                        run_id, run_group_id, created_at, seed, case_index, status
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                conn.commit()

                first = _backfill_legacy_null_run_groups(conn)
                conn.commit()
                second = _backfill_legacy_null_run_groups(conn)
                conn.commit()

                self.assertGreaterEqual(int(first.get("changed_rows", 0)), 5)
                self.assertEqual(int(second.get("changed_rows", 0)), 0)
                null_remaining = conn.execute(
                    "SELECT COUNT(*) FROM experiment_runs WHERE run_group_id IS NULL"
                ).fetchone()
                self.assertEqual(int(null_remaining[0]), 0)

                duplicate_slots = conn.execute(
                    """
                    SELECT run_group_id, seed, case_index, COUNT(*)
                    FROM experiment_runs
                    GROUP BY run_group_id, seed, case_index
                    HAVING COUNT(*) > 1
                    """
                ).fetchall()
                self.assertEqual(len(duplicate_slots), 0)


if __name__ == "__main__":
    unittest.main()
