# Scenario Results

## Status Table
| Scenario | Status | Duration (s) | Key Errors | Touched Modules Summary (from trace JSONL) |
|---|---|---:|---|---|
| `S01_cli_help` | OK | 2.394 | - | `app/cli.py (1)` |
| `S02_doctor` | OK | 2.905 | Doctor report contains failing checks (`overall_status=fail`) while command exits `0`. | `app/doctor_service.py (18), app/cli.py (3), app/models.py (2)` |
| `S03_run_sample_dry` | OK | 9.784 | - | `app/sql_dataset_store.py (36), app/compat_engine.py (26), app/runtime_orchestrator.py (18)` |
| `S04_run_sample_real` | UNSTABLE | 36.472 | Run payload reports failed version (`V002`) although command exits `0`. | `app/runtime_orchestrator.py (47), app/akabak_driver.py (47), app/sql_dataset_store.py (36)` |
| `S05_runner_test_dry` | OK | 6.211 | - | `app/runner_test_harness.py (38), app/compat_engine.py (23), app/runner_test_db.py (16)` |
| `S06_runner_test_real` | UNSTABLE | 6.931 | Scenario output reports `status=failed` / `ATH stage failed` with command exit `0`. | `app/runner_test_harness.py (41), app/compat_engine.py (23), app/runner_test_db.py (16)` |
| `S07_projectpage_ath_experiment_min` | UNSTABLE | 3600.035 | Timed out (`returncode=null`, `timed_out=true`) and gmsh needed manual kill. | `ui/form_builder.py (183), app/projectpage_ath_experiment.py (31), ui/form_schema.py (31)` |
| `S08_ath_experiments_admin` | OK | 99.052 | - | `ui/form_builder.py (104), app/projectpage_ath_experiment.py (35), ui/form_schema.py (24)` |
| `S09_compat_verify_quick` | UNSTABLE | 5.389 | Compat verify report includes `fail: 3` while command exits `0`. | `app/sql_dataset_store.py (19), app/compat_verification.py (13), app/compat_schema.py (10)` |
| `S10_ui_and_script_entrypoints` | OK | 45.378 | - | `app/ui_automation/session.py (24), app/settings_store.py (18), app/cli.py (8)` |
| `S07_projectpage_ath_experiment_min_retry` | UNSTABLE | 2218.529 | Retry payload reports `ath_error=1` and `compare_mismatch_exit0`. | `ui/form_builder.py (213), app/projectpage_ath_experiment.py (80), ui/form_schema.py (31)` |

## Evidence
- S01-S10 durations and exit/timed_out flags: `audit/data/scenario_runs_raw.json`.
- S07 timeout specifics:
  - `audit/data/scenario_runs_raw.json:348`
  - `audit/data/scenario_runs_raw.json:349`
  - `audit/data/scenario_runs_raw.json:350`
- gmsh hang/manual intervention:
  - `audit/DEVLOG.md:71`
  - `audit/DEVLOG.md:74`
  - `audit/DEVLOG.md:78`
  - `audit/DEVLOG.md:79`
- S07 retry runtime and argv:
  - `audit/run_traces/S07_projectpage_ath_experiment_min_retry/20260220T154155682140Z.summary.json`
- S07 profile artifacts:
  - `audit/profiles/S07_projectpage_ath_experiment_min.prof`
  - `audit/profiles/S07_projectpage_ath_experiment_min_retry.prof`
- S07 retry error payload:
  - `audit/runtime/scenario_logs/S07_projectpage_ath_experiment_min_retry_step01.stdout.txt:23`
  - `audit/runtime/scenario_logs/S07_projectpage_ath_experiment_min_retry_step01.stdout.txt:358`
  - `audit/runtime/scenario_logs/S07_projectpage_ath_experiment_min_retry_step01.stdout.txt:930`

## Notes
- `S07_projectpage_ath_experiment_min` is explicitly classified as `UNSTABLE` (not `FAILED`) because behavior alternates between timeout/hang and a later manual retry.
- Touched-module summaries are aggregated from `module` fields in `audit/run_traces/<scenario>/*.jsonl` (event type `py_function_first_call`).
