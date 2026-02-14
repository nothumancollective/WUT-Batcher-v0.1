from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.projectpage_ath_experiment import (
    _append_cleanup_log,
    _backfill_legacy_null_run_groups,
    _backfill_param_subkeys,
    _backfill_unknown_split,
    _classify_compare_payload,
    _ensure_db_schema,
    _param_rows_from_payload,
    _refine_error_pattern,
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

    def test_classify_ath_output_nonzero_unknown_is_runtime_unknown(self) -> None:
        result = classify_ath_output("", "fatal unknown situation", exit_code=5)
        self.assertEqual(result["ath_error_kind"], "ath_runtime_unknown")

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
                run_columns = {
                    str(row[1]) for row in conn.execute("PRAGMA table_info(experiment_runs)").fetchall()
                }
                self.assertIn("error_pattern_refined", run_columns)

    def test_param_rows_flatten_object_subkeys(self) -> None:
        payload = {
            "param_states": [
                {
                    "param_name": "Mesh.Enclosure",
                    "is_set": 1,
                    "value": {
                        "Depth": 120.5,
                        "Spacing": [10.0, 20.0, 30.0, 40.0],
                        "Plan": "my_plan",
                    },
                },
                {
                    "param_name": "R-OSSE",
                    "is_set": 1,
                    "value": {"a0": 14.0, "k": 0.85},
                },
            ]
        }
        rows = _param_rows_from_payload(payload=payload, fallback_fields=[])
        by_key = {row[0]: row for row in rows}
        self.assertIn("Mesh.Enclosure", by_key)
        self.assertIn("Mesh.Enclosure.Depth", by_key)
        self.assertIn("Mesh.Enclosure.Spacing", by_key)
        self.assertIn("Mesh.Enclosure.Spacing.0", by_key)
        self.assertIn("Mesh.Enclosure.Spacing.3", by_key)
        self.assertIn("R-OSSE.a0", by_key)
        self.assertIn("R-OSSE.k", by_key)

    def test_backfill_param_subkeys_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = f"{tmp_dir}/exp.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                _ensure_db_schema(conn)
                conn.execute(
                    """
                    INSERT INTO experiment_runs(
                        run_id, run_group_id, created_at, seed, case_index, status
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("run1", "pp100k_2100", "2026-02-14T00:00:00Z", 2100, 1, "ok"),
                )
                conn.executemany(
                    """
                    INSERT INTO experiment_params(run_id, key, value_text, value_num, is_set)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run1",
                            "Mesh.Enclosure",
                            str({"Depth": 123.4, "Spacing": [1.0, 2.0, 3.0, 4.0], "EdgeType": "round"}),
                            None,
                            1,
                        ),
                        ("run1", "R-OSSE", str({"a0": 12.0, "k": 0.75}), None, 1),
                    ],
                )
                conn.commit()

                first = _backfill_param_subkeys(conn, run_groups=["pp100k_2100"])
                second = _backfill_param_subkeys(conn, run_groups=["pp100k_2100"])
                self.assertGreater(int(first.get("rows_added", 0)), 0)
                self.assertEqual(int(second.get("rows_added", 0)), 0)
                keys = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT key FROM experiment_params WHERE run_id='run1'"
                    ).fetchall()
                }
                self.assertIn("Mesh.Enclosure.Depth", keys)
                self.assertIn("Mesh.Enclosure.Spacing.0", keys)
                self.assertIn("R-OSSE.a0", keys)

    def test_refine_error_pattern_compare_mismatch_exit0(self) -> None:
        refined = _refine_error_pattern(
            status="ath_error",
            ath_error_kind=None,
            ath_exit_code=0,
            config_ok=False,
            no_ghosts=True,
        )
        self.assertEqual(refined, "compare_mismatch_exit0")

    def test_refine_error_pattern_runtime_unknown(self) -> None:
        refined = _refine_error_pattern(
            status="ath_error",
            ath_error_kind=None,
            ath_exit_code=2,
            config_ok=True,
            no_ghosts=True,
        )
        self.assertEqual(refined, "ath_runtime_unknown")

    def test_classify_compare_payload_maps_legacy_mismatch_kind(self) -> None:
        classification = _classify_compare_payload(
            missing_required=[],
            missing_optional=[],
            extra_defaulted=[],
            extra_ghost=[],
            mismatches=[
                {
                    "key": "Mesh.SubdomainSlices",
                    "expected": [4, 8, 16],
                    "actual": "",
                    "mismatch_kind": "structure_mismatch_object",
                }
            ],
        )
        self.assertEqual(classification.get("compare_class_primary"), "cmp_structure_mismatch_object")
        self.assertIn("cmp_structure_mismatch_object", list(classification.get("compare_classes", [])))

    def test_backfill_unknown_split_sets_refined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = f"{tmp_dir}/exp.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                _ensure_db_schema(conn)
                conn.execute(
                    """
                    INSERT INTO experiment_runs(
                        run_id, run_group_id, created_at, seed, case_index, status, ath_exit_code, ath_error_kind
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("r_cmp", "pp100k_2100", "2026-02-14T00:00:00Z", 2100, 1, "ath_error", 0, None),
                )
                conn.execute(
                    """
                    INSERT INTO experiment_runs(
                        run_id, run_group_id, created_at, seed, case_index, status, ath_exit_code, ath_error_kind
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("r_rt", "pp100k_2100", "2026-02-14T00:00:01Z", 2100, 2, "ath_error", 3, None),
                )
                conn.execute(
                    """
                    INSERT INTO experiment_compare(
                        run_id, config_ok, no_ghosts, missing_keys_required_json, missing_keys_optional_json,
                        extra_keys_defaulted_json, extra_keys_ghost_json, mismatch_json
                    ) VALUES (?, ?, ?, '[]', '[]', '[]', '[]', '[]')
                    """,
                    ("r_cmp", 0, 1),
                )
                conn.execute(
                    """
                    INSERT INTO experiment_compare(
                        run_id, config_ok, no_ghosts, missing_keys_required_json, missing_keys_optional_json,
                        extra_keys_defaulted_json, extra_keys_ghost_json, mismatch_json
                    ) VALUES (?, ?, ?, '[]', '[]', '[]', '[]', '[]')
                    """,
                    ("r_rt", 1, 1),
                )
                conn.commit()

                summary = _backfill_unknown_split(conn, run_groups=["pp100k_2100"])
                self.assertGreaterEqual(int(summary.get("rows_updated", 0)), 2)
                rows = {
                    str(row[0]): str(row[1] or "")
                    for row in conn.execute(
                        "SELECT run_id, error_pattern_refined FROM experiment_runs ORDER BY run_id"
                    ).fetchall()
                }
                self.assertEqual(rows["r_cmp"], "compare_mismatch_exit0")
                self.assertEqual(rows["r_rt"], "ath_runtime_unknown")

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
