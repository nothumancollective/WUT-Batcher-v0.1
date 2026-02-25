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
