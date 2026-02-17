from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

from app.contextual_range_analysis import run_contextual_range_analysis


def _seed_db(path: Path) -> None:
    with closing(sqlite3.connect(str(path))) as conn:
        conn.executescript(
            """
            CREATE TABLE experiment_runs(
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                seed INTEGER NOT NULL,
                case_index INTEGER NOT NULL,
                status TEXT NOT NULL,
                ath_exit_code INTEGER,
                ath_error_kind TEXT,
                ath_error_message TEXT,
                ath_warning_count INTEGER NOT NULL DEFAULT 0,
                cfg_path TEXT,
                horns_export_dir TEXT,
                stdout_path TEXT,
                stderr_path TEXT,
                notes TEXT,
                run_group_id TEXT
            );
            CREATE TABLE experiment_compare(
                run_id TEXT PRIMARY KEY,
                config_ok INTEGER NOT NULL DEFAULT 0,
                no_ghosts INTEGER NOT NULL DEFAULT 0,
                missing_keys_required_json TEXT,
                missing_keys_optional_json TEXT,
                extra_keys_defaulted_json TEXT,
                extra_keys_ghost_json TEXT,
                mismatch_json TEXT
            );
            CREATE TABLE experiment_params(
                run_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value_text TEXT,
                value_num REAL,
                is_set INTEGER NOT NULL,
                PRIMARY KEY(run_id, key)
            );
            CREATE TABLE experiment_metrics(
                run_id TEXT PRIMARY KEY,
                final_width_mm REAL,
                final_height_mm REAL,
                final_length_mm REAL,
                avg_throat_angle_deg REAL,
                derived_volume_m3 REAL,
                flags_json TEXT
            );
            """
        )
        rows = [
            ("r1", "g1", 1, 120.0),
            ("r2", "g1", 1, 150.0),
            ("r3", "g1", 3, 200.0),
            ("r4", "g2", 3, 260.0),
        ]
        for run_id, run_group, throat_profile, length in rows:
            conn.execute(
                """
                INSERT INTO experiment_runs(run_id, created_at, seed, case_index, status, run_group_id)
                VALUES(?, '2026-02-17T00:00:00+00:00', 1, 1, 'ok', ?)
                """,
                (run_id, run_group),
            )
            conn.execute(
                """
                INSERT INTO experiment_compare(run_id, config_ok, no_ghosts, missing_keys_required_json, missing_keys_optional_json, extra_keys_defaulted_json, extra_keys_ghost_json, mismatch_json)
                VALUES(?, 1, 1, '[]', '[]', '[]', '[]', '[]')
                """,
                (run_id,),
            )
            conn.execute(
                "INSERT INTO experiment_params(run_id, key, value_text, value_num, is_set) VALUES(?, 'Throat.Profile', ?, ?, 1)",
                (run_id, str(throat_profile), float(throat_profile)),
            )
            conn.execute(
                "INSERT INTO experiment_params(run_id, key, value_text, value_num, is_set) VALUES(?, 'Length', ?, ?, 1)",
                (run_id, str(length), float(length)),
            )
        conn.commit()


class ContextualRangeAnalysisTests(unittest.TestCase):
    def test_contextual_ranges_can_be_built_from_minimal_db(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ctx_ranges_") as tmp:
            root = Path(tmp)
            db_path = root / "ath_experiments.sqlite"
            _seed_db(db_path)
            summary = run_contextual_range_analysis(
                reports_root=root,
                run_group="g1",
                min_count=1,
                output_json_name="ctx.json",
                output_md_name="ctx.md",
            )
            self.assertTrue(bool(summary.get("ok")))
            payload = json.loads((root / "ctx.json").read_text(encoding="utf-8"))
            global_length = dict(payload.get("global_per_key", {}).get("Length", {}) or {})
            self.assertEqual(int(global_length.get("count", 0)), 3)
            contexts = dict(payload.get("contextual_per_key", {}).get("Length", {}) or {})
            self.assertTrue(any("profile=osse" in token for token in contexts.keys()))
            self.assertTrue(any("profile=circarc" in token for token in contexts.keys()))


if __name__ == "__main__":
    unittest.main()
