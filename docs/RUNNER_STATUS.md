# Runner Status (2026-02-15)

## Scope Reviewed
- `docs/RUNNER_AUDIT.md`
- `docs/RUNNER_TEST_HARNESS.md`
- `docs/UI_AUTOMATION_CONTRACTS.md`
- `docs/Runner_E2E_Failure_Report.md`
- `docs/Runner_E2E_Results.md`
- `app/akabak_driver.py`
- `app/vacs_driver.py`
- `app/ui_automation/*`

## Current State
- Runner test harness is isolated under `runner_test_workspace/` and persists telemetry to `runner_test_workspace/db/runner_test.sqlite`.
- Safe cleanup is allowlist-based and limited to workspace paths (`cfg`, `ath_out`, optional `exports`).
- UI automation is UIA/Win32 contract-driven; no pixel/OCR/coordinate decisions.
- `open-dialog-only` micro-harness is stable with absolute path write + readback + close/load postcondition.
- Full E2E now fails early at `pre_akabak_guard` when referenced mesh artifacts are missing, instead of failing late in AKABAK.

## AKABAK/VACS Contracts
- AKABAK open-file dialog contract is active (`#32770`, filename edit `1148`, open button `1`).
- AKABAK interpreter flow now tracks `Start Importing -> Apply` as the primary import path.
- VACS export remains contract-driven with deterministic export-spec mapping and TXT ingestion validations.

## Known Blocker
- ATH output still references mesh files that are not present at import time (`ath.msh`), which blocks successful AKABAK import and therefore full E2E completion.
- Failure is reproducible and classified in DB/docs with run-level diagnostics.

## Added In This Iteration
- New micro-harness: `runner-test import-start-apply-only` for AKABAK interpreter import flow.
- Import diagnostics dump on failure (`import_failure_*.json/.txt`) persisted into `artifacts` + `ui_observations`.
- AKABAK contract updated with explicit `import_start_apply` action and missing-mesh modal classification.

## Pipeline Map (2026-02-25)

### Authoritative docs by subsystem (latest used source)

- Runner orchestration + stage sequence:
  - `docs/RUNNER_STATUS.md` (this file) and `docs/RUNNER_AUDIT.md`.
  - Why authoritative: both documents are cross-referenced by current runner docs and were updated in the latest runner stabilization series.
- Runner test harness + stage contracts:
  - `docs/RUNNER_TEST_HARNESS.md`.
  - Why authoritative: contains current CLI and DB contract for staged execution and workspace layout used by active tests.
- AKABAK import/solve behavior:
  - `docs/AKABAK_IMPORT_SOLVE.md`.
  - Why authoritative: describes current non-visual UIA contract and completion signals used by `app/akabak_driver.py`.
- LE repair / generic25 precondition:
  - `docs/AKABAK_GENERIC25_LE_NETWORK.md`.
  - Why authoritative: documents the currently enforced LE script restore path used in runtime (`repair_post_ath_le_binding`).
- VACS export guard + external script exit semantics:
  - `docs/vacs_export_enforcement.md`.
  - Why authoritative: maintained enforcement spec tied to `app/vacs_export_enforcer.py`, `app/vacs_driver.py`, and `scripts/vacs_export_save_all.py`.
- Library/storage location and DB boundaries:
  - `docs/release/project-library.md` and `docs/release/storage-audit.md`.
  - Why authoritative: current branch-level storage design + verified E2E behavior for project/library DB routing.
- Final dimensions write/read path:
  - `docs/analyzer/09_final_dimensions_data_gap.md`.
  - Why authoritative: latest end-to-end note for ATH parse -> DB write -> analyzer read mapping.

### Stage map (runtime path)

Primary call chain (GUI):
- `app/gui.py` `_BatchRunWorker.run()`
- `app/services.py` `OrchestratorService.run_batch()`
- `app/runtime_orchestrator.py` `run_batch_pipeline(...)`

Stage sequence in `run_batch_pipeline`:

1. Constraints/Batch resolution and version plan
   - Module: `app/batch_orchestrator.py` via `materialize_batch_plan(...)`
   - Inputs: project constraints, batch selected/sweep params
   - Outputs: planned version IDs and per-version manifests
2. ATH runtime CFG generation
   - Module: `app/runtime_orchestrator.py` (`render_cfg_text`, `_apply_sim_export_settings_to_cfg`)
   - Inputs: template cfg + version params
   - Outputs: version cfg + runtime cfg under version `cfg/`
3. ATH execution
   - Module: `app/runners.py` `AthRunner.run_cfg(...)`
   - Inputs: runtime cfg
   - Outputs: ATH stdout/stderr logs, generated ABEC artifacts
4. Final dimensions extraction/persist (first export-data persistence step)
   - Modules: `app/runners.py` `parse_ath_dimensions`, `app/tidy_dataset.py` writer
   - Inputs: ATH stdout
   - Outputs: `ath_dimensions` + `versions.ath_*` in project DB and library DB mirror
5. ABEC sync + LE repair + pre-AKABAK guards
   - Module: `app/runtime_orchestrator.py` (`_sync_generated_abec`, `repair_post_ath_le_binding`, contract checks)
   - Inputs: ATH output dir + ABEC files
   - Outputs: project ABEC path + guard diagnostics logs
6. AKABAK simulation/import stage
   - Module: `app/runtime_orchestrator.py` (`_run_akabak_ui_driver_stage`) and `app/akabak_driver.py`
   - Inputs: ABEC file, AKABAK executable, timeout
   - Outputs: stage summary JSON + optional preserved VACS process state
7. VACS export stage
   - Module: `app/vacs_export_pipeline.py` `run_vacs_export_specs(...)`
   - External script path when AKABAK UI driver path is active: `scripts/vacs_export_save_all.py` via subprocess
   - Inputs: export specs, ABEC context, VACS executable, export/log directories
   - Outputs: exported txt files + `vacs.export_pipeline.json`
8. DB ingestion for VACS exports
   - Module: `app/runtime_orchestrator.py` `_ingest_vacs_exports(...)`
   - Parser modules: `app/vacs_txt_parser.py`, `app/polar_txt_parser.py`
   - Outputs: graph/series/points rows in project DB + mirrored library DB writes

### IDs and persistence source-of-truth used in this pipeline

- `project_id`: project identity in project manifest + DB tables (`projects`, `versions`, `runs`)
- `batch_id`: batch identity in batch manifest + run/version DB rows
- `version_id`: per planned variation identity, links all stage artifacts and DB rows
- `run_id`: execution identity for one batch execution pass, names export folders and run rows

DBs in active project-library storage mode:
- Project DB: `<project_root>/db/project.sqlite`
- Library DB/index: `<library_root>/library.sqlite`

## VACS SystemExit Forensics (2026-02-25)

Observed symptom in manual runs:
- run abort around VACS export with script tail pointing to:
  - `scripts/vacs_export_save_all.py` -> `raise SystemExit(main())`

Reproduced call-chain and failure boundary:
- GUI batch run path:
  - `app/gui.py` `_BatchRunWorker.run()`
  - `app/services.py` `OrchestratorService.run_batch()`
  - `app/runtime_orchestrator.py` `run_batch_pipeline(...)`
  - `app/vacs_export_pipeline.py` `run_vacs_export_specs(...)`
  - external process call to `scripts/vacs_export_save_all.py`

Stage-level diagnostics added (DEBUG-gated):
- New env flag: `WUT_DEBUG_PIPELINE_STAGES=1`
- Per-version JSONL log:
  - `<project>/versions/<version_id>/logs/pipeline.stage_debug.jsonl`
- Captured before/after records for ATH, AKABAK, and VACS stages, including paths, mode, exit/timed-out state, and short error details.

Root-cause hypothesis before fix:
- The runner currently catches `Exception` for VACS export stage errors, but not `SystemExit` (`BaseException` path).
- A `SystemExit` raised inside a VACS stage call boundary can bypass normal stage-fail conversion and escape the pipeline thread.
- Existing runtime logs also show non-crash VACS hard failures (`rc=1`) with root reason `vacs_not_ready_after_f4`; these should remain stage failures with clear diagnostics, never process termination.

## VACS Robustness Fixes Applied (2026-02-25)

Confirmed root causes:
- `SystemExit` was not caught in VACS stage boundary:
  - `app/runtime_orchestrator.py` used `except (VacsExportPipelineError, Exception)` and therefore did not intercept `SystemExit`.
- GUI batch worker catch was also `Exception`-only:
  - `app/gui.py` `_BatchRunWorker.run()` could let `SystemExit` escape the worker thread.
- VACS stage execution was not gated by AKABAK stage success:
  - when AKABAK timed out/failed, VACS export could still start and predictably fail with `vacs_not_ready_after_f4`.

Implemented fixes:
- Stage boundary hardening:
  - `app/runtime_orchestrator.py`
  - VACS export stage now catches `BaseException` (re-raises only `KeyboardInterrupt`), normalizes `SystemExit(...)` into deterministic stage failure text, persists failure to version state + run status, and keeps process alive.
- GUI worker hardening:
  - `app/gui.py`
  - `_BatchRunWorker.run()` now catches `BaseException` and emits a controlled failure payload instead of thread/process termination.
- VACS gating on AKABAK success:
  - `app/runtime_orchestrator.py`
  - VACS stage now only executes when `akabak_stage_ok` is true; otherwise it is explicitly skipped (debug log reason: `akabak_stage_failed`).
- External VACS error surfacing:
  - `app/vacs_export_pipeline.py`
  - non-zero external script exits now parse structured stdout JSON when available and surface concise reasons (`error`, `summary_file`, `trace_file`) instead of opaque blobs.

Validation executed:
- `python -m pytest -q tests/test_runtime_orchestrator.py tests/test_vacs_export_pipeline.py`
  - result: `30 passed`
- Added regression coverage:
  - runtime captures `SystemExit(1)` from VACS boundary as stage failure (no crash).
  - runtime skips VACS stage when AKABAK stage failed (no futile export attempt).
  - external runner non-zero exit returns structured error details.
- CLI real-smoke:
  - `python -m app run-sample --real --library-root cleanup/runtime/vacs_systemexit_guard_real`
  - run failed earlier at `ath_abec_sync` in this environment, but app stayed stable and returned structured failure summary (no crash/SystemExit termination).
