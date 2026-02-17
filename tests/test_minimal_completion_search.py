from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.minimal_completion_search import (
    ScenarioSpec,
    _adaptive_complete_candidate,
    _card_registry,
    _catalog_map,
    _classify_run_status,
    run_minimal_completion_search,
)
from app.settings_store import UserSettings
from ui.form_schema import build_project_form_schema


def _init_experiment_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE experiment_runs(
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                seed INTEGER NOT NULL,
                case_index INTEGER NOT NULL,
                status TEXT NOT NULL,
                run_group_id TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE experiment_params(
                run_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value_text TEXT,
                value_num REAL,
                is_set INTEGER NOT NULL,
                PRIMARY KEY(run_id, key)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO experiment_runs(run_id, created_at, seed, case_index, status, run_group_id)
            VALUES ('run_ok_1', '2026-02-17T00:00:00+00:00', 1, 1, 'ok', 'G_TEST')
            """
        )
        rows = [
            ("run_ok_1", "Throat.Profile", "1", 1.0, 1),
            ("run_ok_1", "Throat.Diameter", "25.4", 25.4, 1),
            ("run_ok_1", "Throat.Angle", "7", 7.0, 1),
            ("run_ok_1", "Coverage.Angle", "45", 45.0, 1),
            ("run_ok_1", "Term.s", "0.5", 0.5, 1),
            ("run_ok_1", "Term.n", "4.0", 4.0, 1),
            ("run_ok_1", "Term.q", "0.996", 0.996, 1),
        ]
        conn.executemany(
            "INSERT INTO experiment_params(run_id, key, value_text, value_num, is_set) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


class MinimalCompletionSearchTests(unittest.TestCase):
    def test_classify_run_status(self) -> None:
        self.assertEqual(_classify_run_status(ath_exit_code=0, stl_path="C:/Horns/x/test.stl"), "stl")
        self.assertEqual(_classify_run_status(ath_exit_code=0, stl_path=None), "noStl")
        self.assertEqual(_classify_run_status(ath_exit_code=2, stl_path=None), "athFail")

    def test_db_observed_search_returns_seed_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_mincomp_test_") as tmp:
            root = Path(tmp)
            reports_root = root / "reports"
            reports_root.mkdir(parents=True, exist_ok=True)
            db_path = reports_root / "ath_experiments.sqlite"
            _init_experiment_db(db_path)
            output_root = root / "out"

            summary = run_minimal_completion_search(
                settings=UserSettings(),
                reports_root=reports_root,
                output_root=output_root,
                verify_with_ath=False,
                scenario_filter="s1_profile1_basic",
                seed_run_limit=20,
                max_seed_candidates=3,
            )

            self.assertEqual(int(summary.get("scenario_count", -1)), 1)
            results = list(summary.get("results", []) or [])
            self.assertEqual(len(results), 1)
            row = dict(results[0])
            self.assertEqual(str(row.get("status")), "observed_only")
            self.assertEqual(str(row.get("source")), "ath_experiments")
            self.assertEqual(str(row.get("run_id")), "run_ok_1")
            params = dict(row.get("params", {}) or {})
            self.assertEqual(int(params.get("Throat.Profile", -1)), 1)
            self.assertTrue(Path(str(summary.get("report_json"))).exists())
            self.assertTrue(Path(str(summary.get("report_md"))).exists())

    def test_adaptive_completion_adds_required_gcurve_keys(self) -> None:
        schema = build_project_form_schema()
        _, key_to_card = _card_registry(schema)
        catalog = _catalog_map()
        scenario = ScenarioSpec(
            scenario_id="test_gcurve",
            description="",
            included_cards=("profile", "basics", "mesh", "gcurve"),
            selectors={"Throat.Profile": 1, "GCurve.Type": 1},
            require_defined=(),
            require_undefined=("Morph.TargetShape", "Mesh.Enclosure"),
        )
        params = {
            "Throat.Profile": 1,
            "Throat.Diameter": 25.4,
            "Throat.Angle": 7.0,
            "Coverage.Angle": 45.0,
            "Term.s": 0.5,
            "Term.n": 4.0,
            "Term.q": 0.996,
            "Mesh.AngularSegments": 64,
            "Mesh.LengthSegments": 20,
            "Mesh.ThroatResolution": 4.0,
            "Mesh.InterfaceResolution": 8.0,
            "GCurve.Type": 1,
        }
        completed, meta = _adaptive_complete_candidate(
            params=params,
            scenario=scenario,
            key_to_card=key_to_card,
            catalog_by_key=catalog,
        )
        self.assertIn("GCurve.Dist", completed)
        self.assertIn("GCurve.Width", completed)
        self.assertIn("GCurve.Dist", list(meta.get("added_keys", []) or []))
        self.assertIn("GCurve.Width", list(meta.get("added_keys", []) or []))


if __name__ == "__main__":
    unittest.main()
