# Runner Status (2026-02-15)

## Doc Selection (2026-02-25)
- Runner execution/status source: `docs/RUNNER_STATUS.md` + `docs/RUNNER_AUDIT.md`.
- Analyzer/worker interaction source: `docs/analyzer/*` and the latest merge notes under `docs/release/*`.
- Storage root/source-of-truth source: `docs/release/project-library.md` + `docs/release/storage-audit.md`.
- Selection rationale: these files are the currently maintained docs referenced by the active runner, analyzer, and storage integration commits on `wut-batcher/rebuild`.
- Current debugging focus in this cycle: stage failure at `ath_abec_sync` (ATH succeeded, ABEC sync failed).

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

## Run Batch Immediate-Success Bug (2026-02-25)

Observed symptom:
- GUI marked batch run as complete/success immediately ("Run finished") even when pipeline failed before completion.

Root cause:
- `app/gui.py` `_on_batch_run_finished(...)` always set success UI state and "Run finished..." status text.
- It ignored `summary_payload["run_status"]` (`failed`, `noop`, etc.), so UI success semantics diverged from runtime truth.

Fixes applied:
- `app/gui.py`
  - `_on_batch_run_finished(...)` now maps `run_status` explicitly:
    - `succeeded/success` -> success UI + "Run finished..."
    - `noop/skipped/precondition_failed` -> no-op UI + "Nothing to run..."
    - everything else -> failed UI + "Run failed..."
  - `RunPage.set_noop_state(...)` added for explicit no-op terminal state.
  - `_BatchRunWorker.run()` now re-raises `KeyboardInterrupt`/`GeneratorExit` and only converts other `BaseException` to worker-failed signal.
- `app/runtime_orchestrator.py`
  - Run status now returns `noop` when no versions are planned (`nothing_to_run:no_planned_versions`) instead of reporting success.
  - Added run-level debug log (`<project_root>/runs/<run_id>/pipeline.stage_debug.jsonl`) with `run_start/run_end` records including resolved roots, DB path, and planned versions.
  - VACS stage `BaseException` boundary now also re-raises `GeneratorExit` (in addition to `KeyboardInterrupt`).

Library-root safety update:
- `app/cli.py`
  - `--library-root` for `run-sample`, `dataset-sync-global`, and `compat-verify` now uses an isolated temporary `SettingsStore`.
  - Command-scoped overrides no longer persist into user GUI settings (`~/.wut_batcher/config.json`).

## E2E GUI Run #1 (2026-02-25)

Environment:
- Existing user library root: `cleanup/runtime/vacs_systemexit_guard_real` (previously persisted by CLI override behavior).
- Stage debug enabled: `WUT_DEBUG_PIPELINE_STAGES=1`.

Result:
- Manual GUI worker path executed real stages and ended with failure at `ath_abec_sync`.
- UI correctly showed failure (not success):
  - status: `Run failed for B001`
  - mode: `Mode: failed`
  - progress label: `Run failed`
- Runtime summary showed true stage progression:
  - `ath: ok`
  - `ath_abec_sync: failed`
- Run-level debug log persisted at:
  - `<project_root>/runs/<run_id>/pipeline.stage_debug.jsonl`

Conclusion:
- The immediate-success false positive is fixed.
- Pipeline outcomes now map truthfully to GUI terminal state.

## E2E GUI Run #2 (isolated test library, 2026-02-25)

Setup:
- Temporary isolated settings file + isolated library root under `%TEMP%/wut_ui_e2e_debug_*`.
- Fake ATH/AKABAK/VACS toolchain from existing UI stress harness helpers.
- No writes to user settings store.

Observed stage transitions:
- Planned versions: `V005`, `V006`, `V007`, `V008`
- For each version: `ath: ok` then `ath_abec_sync: failed`
- Overall `run_status: failed`

Observed GUI terminal state:
- Status text: `Run failed for B001`
- Run page mode: `Mode: failed`
- Progress label: `Run failed`

Interpretation:
- In this environment/toolchain profile, pipeline preconditions fail at ABEC sync.
- Runner/UI now report truthful failure state (not false success), which is the required behavior for blocked preconditions.
