# 00 Inventory

## Snapshot
- Audit timestamp source: `audit/data/import_graph.json`.
- Repository counts: `py=135`, `md=123`, `json=144`, `sqlite=58`.
- Python layers (from `audit/data/import_graph.json`): `app=64`, `ui=13`, `scripts=3`, `tests=55`.
- Import graph summary (from `audit/data/import_graph.json`): `135` modules, `252` internal import edges.

## Production Entry Points
- Module launcher: `app/__main__.py:3` imports CLI `main`, and `app/__main__.py:6` executes it via `SystemExit`.
- CLI root parser: `app/cli.py:868` (`build_parser`) with root subparsers at `app/cli.py:872`.
- GUI command wiring: `app/cli.py:313` (`cmd_gui`) and `app/cli.py:948` (`p_gui.set_defaults(func=cmd_gui)`).
- Runtime sample command wiring: `app/cli.py:175` (`cmd_run_sample`) and `app/cli.py:959`.
- Runner test command wiring: `app/cli.py:618` (`cmd_runner_test_run`) and `app/cli.py:1043`.
- ATH experiment command wiring: `app/cli.py:380` (`cmd_projectpage_ath_experiment`).
- CLI dispatch: `app/cli.py:1834` (`main(argv=None)`).
- GUI direct entry function: `app/gui.py:3759` (`def main()`).
- Theme preview direct entry function: `ui/theme_preview.py:115` (`def main()`).
- Script entrypoints (standalone): `scripts/vacs_export_save_all.py:2297`, `scripts/vacs_export_dialog_rounds.py:589`, `scripts/vacs_interim_reimport.py:921`.

## CLI Surface Summary
- Parser inventory was generated into `audit/data/entrypoints.json` from AST in `app/cli.py`.
- High-impact command groups present in parser graph: `doctor`, `dataset`, `run`, `run-sample`, `runner-test`, `projectpage-ath-experiment`, `ath-experiments`, `ui`, `vacs`, `runs`.
- Evidence artifact: `audit/data/entrypoints.json`.

## Import Graph Summary
- Highest in-degree modules (shared dependencies): `app.models` (23), `app.constants` (17), `app.ath_knowledge` (11), `app.settings_store` (10), `app.export_specs` (9).
- Highest out-degree modules (orchestrators): `app.cli` (20), `app.runner_test_harness` (17), `app.services` (13), `app.projectpage_ath_test` (10).
- Runtime orchestration path anchor: `app/services.py:1848` -> `app/services.py:1861` -> `app/runtime_orchestrator.py:1258`.
- Evidence artifact: `audit/data/import_graph.json`.

## DB Map (Code + Runtime Files)
- Core project/global SQL schema source: `app/sql_dataset_store.py:139` through `app/sql_dataset_store.py:336`.
- Runner-test SQL schema source: `app/runner_test_db.py:75` through `app/runner_test_db.py:218`.
- ATH experiment SQL schema source: `app/projectpage_ath_experiment.py:1137` through `app/projectpage_ath_experiment.py:1186`.
- Dataset pipeline SQLite schema source: `app/dataset_pipeline.py:299` through `app/dataset_pipeline.py:332`.
- On-disk SQLite inventory discovered: `58` files (see `audit/data/db_inventory.json`).
- Dominant runtime DB families found on disk:
- `project/global` DBs with tables including `projects`, `batches`, `versions`, `runs`, `run_versions`, `graphs`, `graph_series`, `graph_points`, `replication_queue`, `federation_*`.
- `runner_test_workspace/db/runner_test.sqlite` with harness tables `test_runs`, `test_cases`, `test_run_steps`, `ui_observations`, `artifacts`, `validations`.
- `reports/ath_experiments/ath_experiments.sqlite` with `experiment_runs`, `experiment_params`, `experiment_metrics`, `experiment_compare`.
- Many `oracle_cache.sqlite` files under `reports/minimal_completion*` containing `oracle_cache`.

## Stale Doc Mismatches (Static)
- `docs/ChatGPT_Context.md:13` and `docs/ChatGPT_Context.md:45` reference `Runner/`, but `Runner` path does not exist in this repo root.
- `docs/ChatGPT_Context.md:32` references `run_full_batch_v5.py`, but file is absent.
- `docs/ChatGPT_Context.md:33` references `start_gui.ps1`, but file is absent.
- Presence check evidence command result recorded in DEVLOG:
- `Runner` -> `False`
- `run_full_batch_v5.py` -> `False`
- `start_gui.ps1` -> `False`

## Repro Commands (Phase A)
- `python` AST/SQLite inventory generator that writes:
- `audit/data/import_graph.json`
- `audit/data/entrypoints.json`
- `audit/data/db_inventory.json`
- `rg -n '__main__|def main\(' app/__main__.py app/cli.py app/gui.py scripts/vacs_export_save_all.py scripts/vacs_export_dialog_rounds.py scripts/vacs_interim_reimport.py ui/theme_preview.py`
- `rg -n 'CREATE TABLE IF NOT EXISTS|sqlite3.connect\(|project.sqlite|ath_experiments.sqlite|runner_test.sqlite' app/sql_dataset_store.py app/runner_test_db.py app/projectpage_ath_experiment.py app/dataset_pipeline.py app/cli.py`
- `rg -n 'Runner/|run_full_batch_v5.py|start_gui\.ps1' docs/ChatGPT_Context.md`
