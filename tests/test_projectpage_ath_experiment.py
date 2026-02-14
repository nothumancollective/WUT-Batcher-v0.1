from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.projectpage_ath_experiment import (
    _append_cleanup_log,
    _backfill_legacy_null_run_groups,
    _ensure_db_schema,
    _scaled_quota,
    classify_ath_output,
    generate_experiment_cases,
    parse_ath_output_metrics,
)


class ProjectPageAthExperimentTests(unittest.TestCase):
    @staticmethod
    def _field_map(case_fields):
        return {str(key): value for key, value in list(case_fields)}

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

    def test_generator_sampler_v2_quota_smoke(self) -> None:
        total_cases = 10_000
        cases = generate_experiment_cases(
            cases=total_cases,
            seed=2100,
            max_dim_mm=2000.0,
            hard_cap_mm=5000.0,
            prior_ranges={},
        )
        self.assertEqual(len(cases), total_cases)

        enclosure_count = 0
        sf_list_count = 0
        slot_length_count = 0
        throat_extension_count = 0
        subdomain_bundle_count = 0
        zmap_count = 0
        allow_shrinkage_count = 0
        morph_curve_count = 0
        rot_count = 0

        for item in cases:
            values = self._field_map(item.case.field_values)
            if "Mesh.Enclosure" in values:
                enclosure_count += 1
                self.assertIn("Mesh.Enclosure.Spacing", values)
                self.assertIn("Mesh.Enclosure.Depth", values)
                self.assertIn("Mesh.Enclosure.EdgeRadius", values)
                self.assertIn("Mesh.Enclosure.EdgeType", values)
                self.assertIn("Mesh.Enclosure.FrontResolution", values)
                self.assertIn("Mesh.Enclosure.BackResolution", values)

            sf_value = values.get("GCurve.SF")
            if isinstance(sf_value, list):
                sf_list_count += 1
                self.assertEqual(len(sf_value), 6)
                for num in sf_value:
                    self.assertIsInstance(num, float)

            if "Slot.Length" in values:
                slot_length_count += 1

            has_ext_angle = "Throat.Ext.Angle" in values
            has_ext_len = "Throat.Ext.Length" in values
            self.assertEqual(has_ext_angle, has_ext_len)
            if has_ext_angle and has_ext_len:
                throat_extension_count += 1
                self.assertGreater(float(values["Throat.Ext.Angle"]), 0.0)
                self.assertGreater(float(values["Throat.Ext.Length"]), 0.0)

            has_sub = "Mesh.SubdomainSlices" in values
            has_off = "Mesh.InterfaceOffset" in values
            has_draw = "Mesh.InterfaceDraw" in values
            if has_sub:
                subdomain_bundle_count += 1
                self.assertTrue(has_off)
                self.assertTrue(has_draw)
                self.assertEqual(len(values["Mesh.SubdomainSlices"]), len(values["Mesh.InterfaceOffset"]))
                self.assertEqual(len(values["Mesh.SubdomainSlices"]), len(values["Mesh.InterfaceDraw"]))
            else:
                self.assertFalse(has_off)
                self.assertFalse(has_draw)

            if "Mesh.ZMapPoints" in values:
                zmap_count += 1
            if "Morph.AllowShrinkage" in values:
                allow_shrinkage_count += 1
            if "Morph.FixedPart" in values and "Morph.Rate" in values:
                morph_curve_count += 1
            if "Rot" in values:
                rot_count += 1

            self.assertEqual(int(values["Mesh.AngularSegments"]) % 4, 0)

        self.assertGreaterEqual(enclosure_count, _scaled_quota(total_cases, 5_000))
        self.assertGreaterEqual(sf_list_count, _scaled_quota(total_cases, 1_500))
        self.assertGreaterEqual(slot_length_count, _scaled_quota(total_cases, 2_000))
        self.assertGreaterEqual(throat_extension_count, _scaled_quota(total_cases, 2_000))
        self.assertGreaterEqual(subdomain_bundle_count, _scaled_quota(total_cases, 2_500))
        self.assertGreaterEqual(zmap_count, _scaled_quota(total_cases, 2_500))
        self.assertGreaterEqual(allow_shrinkage_count, _scaled_quota(total_cases, 3_000))
        self.assertGreaterEqual(morph_curve_count, _scaled_quota(total_cases, 3_000))
        self.assertGreaterEqual(rot_count, _scaled_quota(total_cases, 2_000))

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

    def test_append_cleanup_log_writes_group_specific_end_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = {"phase": "end", "kind": "cases", "deleted_count": 2}
            _append_cleanup_log(
                reports_root=root,
                phase="end",
                payload=payload,
                run_group_id="pp100k_2100",
            )
            self.assertTrue((root / "cleanup_end.log").exists())
            self.assertTrue((root / "cleanup_end_pp100k_2100.log").exists())


if __name__ == "__main__":
    unittest.main()
