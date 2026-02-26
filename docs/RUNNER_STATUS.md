# Runner Status (2026-02-15)

## Core Semantics (Batch / Version / Run)

### Batch
- A `Batch` is a planning container under one project.
- It defines selected parameters, sweeps, and export configuration for a candidate execution set.
- A batch does not represent execution itself; it only defines what should be executed.

### Version
- A `Version` is one concrete design/parameter set materialized from batch planning.
- It has stable identity (`version_id`) and persists design/config state (e.g. cfg snapshots, version metadata).
- Multiple runs can execute the same version over time.

### Run
- A `Run` is one concrete execution process (`run_id`) for a batch planning snapshot.
- A run owns execution status timeline + run-version status rows and execution diagnostics.
- Runtime artifacts/logs must be attributable to a specific run id.

## Data Model Invariants

- `run_id` is globally unique for runtime execution identity.
- A run belongs to exactly one `(project_id, batch_id)` pair.
- `run_versions` bind each `(run_id, version_id)` execution row; a run can include multiple versions.
- Artifacts/logs emitted during execution must be resolvable via deterministic run context:
  - run-scoped: `<project_root>/runs/<run_id>/...`
  - version-scoped execution artifacts: `<project_root>/versions/<version_id>/...` with run-specific subpaths where applicable.
- Stage diagnostics must be written even for early failures, and must be discoverable from run identity without guessing.

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

## E2E GUI Run #3 (ath_abec_sync diagnostics capture, 2026-02-26)

Context:
- `WUT_DEBUG_PIPELINE_STAGES=1`
- Isolated GUI test root: `%TEMP%/wut_gui_ath_abec_sync_*`
- Result status: `Run failed for B001` with `run_status=failed`

Verbatim stage debug entry (`versions/V005/logs/pipeline.stage_debug.jsonl`):
```json
{"time":"2026-02-26T00:25:09+00:00","event":"stage_end","stage":"ath_abec_sync","version_id":"V005","ok":false,"error":"ath_abec_missing","summary_log":"...\\versions\\V005\\logs\\ath.abec_sync.json"}
```

Verbatim sync payload (`versions/V005/logs/ath.abec_sync.json`):
```json
{
  "ok": false,
  "target_abec": "...\\versions\\V005\\abec\\Project.abec",
  "search_roots": [
    "...\\runs\\ath_export\\..._V005_...",
    "...\\versions\\V005\\ath_work"
  ],
  "source_abec": "",
  "error": "generated_abec_missing"
}
```

Immediate implication:
- ATH completed successfully (`ath: ok`), but sync did not find any generated `.abec` in the current search roots for this version.

## Root cause: ath_abec_sync (2026-02-26)

Classification:
- Primary class: **A/B (artifact location mismatch in sync search roots)**.

Evidence:
- Expected target path:
  - `.../versions/V005/abec/Project.abec`
- Search roots used at failure time:
  - `.../runs/ath_export/<project>_B001_V005_<run8>`
  - `.../versions/V005/ath_work`
- Sync payload reported:
  - `"error": "generated_abec_missing"`
  - `"source_abec": ""`
- File-system check confirmed:
  - `versions/V005/abec/Project.abec` existed even while sync reported missing source.

Why this failed:
- `_sync_generated_abec(...)` only searched ATH export/work directories.
- In the reproduced run profile, ATH output ABEC directly into the version ABEC folder.
- Therefore sync could not locate the freshly generated artifact and marked stage failed.

Fix applied:
- `app/runtime_orchestrator.py`
  - Include `target_abec.parent` in sync search roots.
  - Add fresh-artifact guard (`min_mtime_ns`) to reject stale leftovers.
  - Add 5s mtime slop for Windows timestamp granularity.

Validation:
- `python -m pytest -q tests/test_runtime_orchestrator.py`
  - `23 passed`
- Added regression tests:
  - fresh target-dir ABEC is accepted
  - stale target-dir ABEC is rejected (`generated_abec_missing`)

## E2E evidence after fix (GUI, 2026-02-26)

Isolated GUI run (real user flow, stage debug enabled):
- Root: `%TEMP%/wut_gui_ath_abec_sync_fix2_*`
- Run status: `failed` (expected in this toolchain due a later guard), but `ath_abec_sync` no longer fails.

Run binding evidence (`runs/<run_id>/pipeline.stage_debug.jsonl`):
- `library_root`: `.../library`
- `project_root`: `.../library/projects/P0001__...`
- `run_root`: `.../library/projects/P0001__.../runs/3c953697-...`
- `project_db_path`: `.../library/projects/P0001__.../db/project.sqlite`

Stage progression excerpt (first version):
- `ath: ok`
- `post_ath_le_repair: ok`
- next failure moved to `pre_akabak_le_driving_guard` (upstream precondition), proving `ath_abec_sync` passed.

Analyzer interaction safety check:
- Post-run analyzer project query executed without DB-lock exceptions (`analyzer_list_polar_projects(source='project')` returned cleanly).

## Phase 0 Audit Findings (Path Convention, 2026-02-26)

Doc selection (authoritative for this change set):
- `docs/RUNNER_STATUS.md` (this file): latest runner execution map + current failure timeline.
- `docs/release/project-library.md`: active storage root policy and library/project DB boundaries.
- `docs/LE_DRIVING_AUDIT.md`: current LE/AKABAK contract expectations and known pre-AKABAK checks.
- `docs/runner/path-convention.md`: single path/artifact convention and per-stage mapping table.
- Selection rationale: these docs are currently aligned with active `wut-batcher/rebuild` runtime behavior and referenced by current runner fixes.

Code-path archaeology summary (hotspots):
- Runner path assembly and stage handoff:
  - `app/runtime_orchestrator.py`
  - hotspots: `_planned_ath_export_dir`, `_version_*` helpers, `_sync_generated_abec`, `_version_exports_dir`, inline stage `workdir` wiring.
- Project/storage structural source:
  - `app/project_storage.py`
  - `resolve_project_paths`, `resolve_version_paths`, `ProjectPaths`, `VersionPaths`.
- Service-level orchestration root decisions:
  - `app/services.py::OrchestratorService.run_batch`
  - picks `ath_export_root` and passes root/tool settings into `run_batch_pipeline`.
- External VACS exporter boundary:
  - `app/vacs_export_pipeline.py`
  - uses script execution rooted at app repo (`scripts/vacs_export_save_all.py`) with stage-provided export/log paths.

Path-mixing and ambiguity hotspots identified:
- Mixed artifact loci between version-owned dirs and run-owned dirs:
  - version paths (`versions/<V>/ath_work`, `versions/<V>/abec`, `versions/<V>/exports/<run_id>`) coexist with run-level ATH export root (`runs/ath_export/<cfg_stem>`).
- Reader/writer mismatch risks:
  - prior `ath_abec_sync` searched limited roots and missed `versions/<V>/abec`.
  - several stages still use ad-hoc path composition instead of a single run layout object.
- Search/discovery patterns still present:
  - ABEC selection and TXT ingestion rely on directory scans (`rglob`) in stage-specific roots; currently deterministic but not yet centralized by one formal run-layout helper.
- Legacy naming coexistence:
  - `db/` vs `dataset/`, `logs/` vs `_logs/` compatibility branches remain in `project_storage`.

Consolidation decision:
- **Extend existing convention (preferred)**:
  - keep `StorageManager` + `project_storage` as storage authorities.
  - add one runner `PathContext/RunLayout` helper for stage-level artifact paths.
  - migrate stage code to consume that helper (no parallel resolver module, no new storage system).

## Phase 2 Implementation (PathContext wiring, 2026-02-26)

Implemented:
- New helper module: `app/run_path_context.py`
  - `RunPathContext.build(...)` (run-scoped roots and tool paths)
  - `RunPathContext.version(...)` (version-scoped canonical artifact paths)
- Runtime integration: `app/runtime_orchestrator.py`
  - `run_batch_pipeline(...)` now builds one `RunPathContext` per run and uses it for:
    - cfg input/runtime cfg paths
    - ATH workdir path
    - ABEC canonical path
    - version logs path
    - run export path
    - bounded ABEC sync roots (`ath_export_dir`, `ath_work_dir`, `abec_dir`)
  - run-level debug logging now writes via `run_paths.run_debug_log_path()`.
  - removed legacy ad-hoc `_version_*` path helper usage from the run loop.

Expected impact:
- deterministic writer/reader parity per stage
- no implicit fallback to repo-relative or cleanup roots during GUI runs
- clearer diagnostics when expected artifacts are missing.

## E2E GUI Run #4 (Path Convention Validation, 2026-02-26)

Scope:
- Offscreen GUI worker flow (`MainWindow._start_batch_run_worker`) with isolated temp settings and isolated temp library root.
- `WUT_DEBUG_PIPELINE_STAGES=1` enabled.
- No writes to user settings store; settings file was scoped to `%TEMP%/wut_pathctx_gui_e2e2_*/settings.json`.

Execution notes:
- Fake ATH/AKABAK/VACS executables used to keep runtime short.
- Toolchain-dependent guard points were patched in test harness only (no product code change):
  - `repair_post_ath_le_binding` -> success stub
  - LE-driving guard -> `ok: true`
  - mesh guard -> no missing mesh
  - `run_vacs_export_specs` -> deterministic TXT export stub

Observed result:
- GUI status: `Run finished for B001`
- runtime payload: `run_status=succeeded`
- run root used:
  - `.../library/projects/P0001__98e2e136-d09d-4765-bdc6-7ca130522988/runs/0305ce7d-9d9a-4076-80d4-d0fdc50b49cb`

Run log evidence (`runs/<run_id>/pipeline.stage_debug.jsonl`):
- `run_start` captured explicit bindings:
  - `app_root`
  - `library_root`
  - `project_root`
  - `run_root`
  - `project_db_path`
- `run_end` captured:
  - `status=succeeded`
  - `stage_count=6`

Version stage progression excerpt (`versions/V002/logs/pipeline.stage_debug.jsonl`):
- `ath: ok`
- `post_ath_le_repair: ok`
- `akabak (subprocess): ok`
- `vacs (export_specs): ok`

Conclusion:
- Stage paths were resolved from one deterministic run/version context.
- No path-mismatch failure was observed in this run.

## Root cause: `pipeline.stage_debug.jsonl` not findable (2026-02-26)

Observed user symptom:
- after a run, users could not find `pipeline.stage_debug.jsonl` reliably.

Proven cause:
- runtime debug logging was gated by `WUT_DEBUG_PIPELINE_STAGES=1`, so no debug JSONL was written in normal runs.
- run records did not persist `run_root` / `run_debug_log_path`, so users had to infer filesystem paths manually.
- UI run screen did not expose run identity/path shortcuts.

Repro evidence:
- `python -m app run-sample --dry-run --library-root cleanup/runtime/tmp_findability_probe`
- run completed, but both paths were missing:
  - `<project_root>/runs/<run_id>/pipeline.stage_debug.jsonl`
  - `<project_root>/versions/<version_id>/logs/pipeline.stage_debug.jsonl`

## Findability fixes applied (2026-02-26)

Code changes:
- `app/runtime_orchestrator.py`
  - run/version debug JSONL writing is now unconditional (not env-flag gated).
  - runtime summary now includes:
    - `run_root`
    - `run_debug_log_path`
  - `create_run(...)` now persists run path metadata.
- `app/sql_dataset_store.py`
  - `runs` schema extended with:
    - `run_root TEXT`
    - `run_debug_log_path TEXT`
  - `upsert_run`, `list_runs`, and migration path updated accordingly.
- `app/gui.py` (`RunPage`)
  - added run findability fields:
    - `Run ID`
    - `Run Folder`
    - `Stage Debug`
  - added `Open Run Folder` button.

## How to locate run logs (current behavior)

1. Start a run from GUI.
2. On RUN screen read:
   - `Run ID: <run_id>`
   - `Run Folder: <abs_path>`
   - `Stage Debug: <abs_path>/pipeline.stage_debug.jsonl`
3. Click `Open Run Folder` to open `<project_root>/runs/<run_id>/`.
4. For per-version stage traces, open:
   - `<project_root>/versions/<version_id>/logs/pipeline.stage_debug.jsonl`

## E2E GUI Run #5 (Findability validation, 2026-02-26)

Setup:
- Offscreen GUI worker flow with isolated temp settings + isolated temp library root.
- `WUT_DEBUG_PIPELINE_STAGES` intentionally unset.
- Fake toolchain + guarded stage stubs (no product logic change) for deterministic completion.

Result:
- `run_status=succeeded`
- run record created with persisted path metadata.
- artifacts confirmed present:
  - `run_root` exists
  - run-level `pipeline.stage_debug.jsonl` exists
  - version-level `pipeline.stage_debug.jsonl` exists

Run record evidence (`runs` table row):
- `run_root`: `.../library/projects/P0001__.../runs/<run_id>`
- `run_debug_log_path`: `.../library/projects/P0001__.../runs/<run_id>/pipeline.stage_debug.jsonl`

Run log excerpt:
- first event: `run_start` with explicit root bindings
- last event: `run_end` with terminal run status

## Run `812d5bff-c5dd-461a-a730-99de10d8d4b6` Forensics (2026-02-26)

Source run metadata (user report + on-disk verification):
- `run_id`: `812d5bff-c5dd-461a-a730-99de10d8d4b6`
- `project_id`: `P0003__057c91ad-28e8-4682-9de7-63ccb58c9ad2`
- `batch_id`: `B003`
- `planned_versions`: `V011`, `V012`
- `library_root`: `C:\Users\maximilianheinze\Desktop\WUT Project Library`
- `project_root`: `C:\Users\maximilianheinze\Desktop\WUT Project Library\projects\P0003__057c91ad-28e8-4682-9de7-63ccb58c9ad2`
- `run_root`: `...\runs\812d5bff-c5dd-461a-a730-99de10d8d4b6`

### A) run_root contents
- Present in run root:
  - `pipeline.stage_debug.jsonl`
- Missing in run root for this run:
  - no per-stage entries, only `run_start` + `run_end`
  - no run-level `logs/` stage summary files

`run_root/pipeline.stage_debug.jsonl` contained only:
- `run_start` (with bindings and planned versions)
- `run_end` (`status=failed`, `error_summary=null`, `stage_count=4`)

### B) per-version stage logs
- Present and populated:
  - `versions/V011/logs/pipeline.stage_debug.jsonl`
  - `versions/V012/logs/pipeline.stage_debug.jsonl`
- Both versions showed:
  - `ath: ok`
  - `ath_abec_sync: failed`
- Stage-specific details existed in:
  - `versions/V011/logs/ath.abec_sync.json`
  - `versions/V012/logs/ath.abec_sync.json`

### C) project.sqlite run records
- `runs` row for this `run_id`:
  - `status='failed'`
  - `error_summary=NULL`
  - `run_root` and `run_debug_log_path` populated
- `run_versions` rows:
  - both `V011` and `V012` marked `failed`
  - `error_summary='version_stage_failed'` (generic, no stage name)

### D) forensic conclusion
- Failure reason did exist, but only in version-local stage logs / `ath.abec_sync.json`.
- Run-level debug file was not sufficient for diagnosis (no stage entries, null summary).
- Concrete first failing stage and reason:
  - stage: `ath_abec_sync`
  - reason: `abec_sidecar_missing` (missing sidecar `*.msh` referenced by generated ABEC).

## Diagnostics hardening + ath_abec_sync unblock (2026-02-26)

### Why failed runs had `error_summary=null`
- `run_batch_pipeline(...)` only wrote stage records to version-local logs and in-memory `stage_results`.
- `run_end` used `run_error_summary` that was not populated from stage failures, so failed runs could end with `error_summary=null`.
- Result: users had to inspect per-version logs manually and could not identify the failing stage from the run record alone.

### Runtime fixes applied
- `app/runtime_orchestrator.py`
  - Added run-level stage logging for every executed stage:
    - `event=stage_start` on stage entry
    - `event=stage_end` on stage completion/failure
    - always written to `<run_root>/pipeline.stage_debug.jsonl` (not env-gated).
  - Consolidated stage result recording through `_record_stage_result(...)` so run-level debug rows and `stage_results` stay in sync.
  - Failed run summary is now always non-null:
    - derives from first failing stage: `<stage>:<reason>` (for example `vacs:vacs_executable_missing`).
    - `run_end` now includes `failing_stage`, `failing_version_id`, and `failing_summary_log`.
  - Added synthetic failure capture when an exception escapes after stage start:
    - writes a synthetic failed `stage_end` row and summary log under `<run_root>/logs/`.
- `app/runtime_orchestrator.py` (`_sync_generated_abec`)
  - Added narrow mesh-reference recovery:
    - if generated ABEC references a missing `*.msh` but `bem_mesh.msh` exists in the same export, mesh references in `[MeshFiles]` are repaired to `bem_mesh.msh`.
    - prevents false-negative `ath_abec_sync` failures in the known ATH output pattern.

### Validation evidence
- Automated:
  - `python -m pytest -q tests/test_runtime_orchestrator.py` -> `25 passed`
  - `python -m pytest -q tests/test_gui_run_status_semantics.py tests/test_vacs_export_pipeline.py tests/test_cli_run_sample.py` -> `16 passed`
- Real toolchain run (using configured executables from settings):
  - run_id: `c583877d-206a-42b9-ac75-0a087ad101df`
  - status: `succeeded`
  - stage progression (both versions): `ath -> ath_abec_sync -> post_ath_le_repair -> pre_akabak_le_driving_guard -> pre_akabak_mesh_guard -> akabak -> vacs`
  - run log: `<project_root>/runs/c583877d-.../pipeline.stage_debug.jsonl` contains stage_start/stage_end entries and terminal `run_end`.
- Forced precondition failure check (missing VACS executable):
  - run_id: `3c645e27-cc79-4562-8118-bd49e351f049`
  - status: `failed`
  - `run_end.error_summary`: `vacs:vacs_executable_missing`
  - `run_end.failing_stage`: `vacs`
  - DB row (`runs`): `status='failed'`, `error_summary='vacs:vacs_executable_missing'`, `run_root` + `run_debug_log_path` populated.
