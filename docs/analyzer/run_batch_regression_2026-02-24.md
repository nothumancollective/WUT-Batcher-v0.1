# Run Batch Regression (2026-02-24)

## 1) Symptom and Repro

Date observed: **2026-02-24**.

Observed symptom in GUI:
- User configures a Batch and clicks `Run Batch`.
- Run page immediately transitions to failed state (`Run failed`).
- No run executes.

Deterministic repro used:
1. Launch app (`python -m app gui`) or execute the existing GUI E2E flow in `tests/test_ui_e2e_stress_runs.py`.
2. Create project with valid constraints.
3. Open Batch page.
4. Set `Length` and `Coverage.Angle` with small sweeps (`steps=2`).
5. Click `Run Batch`.

Observed result:
- Status becomes `Run failed for B001` almost immediately.

Expected result:
- Batch run starts, progresses through runtime stages, and completes with `Run finished for <batch_id>`.

## 2) Root Cause Analysis

First fatal exception captured from `MainWindow.last_status_detail`:

```text
Traceback (most recent call last):
  File "...\\app\\gui.py", line 1665, in run
    summary = self._service.run_batch(...)
  File "...\\app\\services.py", line 3419, in run_batch
    return run_batch_pipeline(...)
TypeError: run_batch_pipeline() got an unexpected keyword argument 'akabak_solve_timeout_s'
```

Failing contract:
- Caller: `OrchestratorService.run_batch` in `app/services.py` now passes `akabak_solve_timeout_s`.
- Callee: `run_batch_pipeline` in `app/runtime_orchestrator.py` does **not** accept this parameter.

Crash location:
- UI worker path `_BatchRunWorker.run()` catches the exception and emits `failed`, which drives the immediate `Run failed` state.

Regression evidence:
- `git log -L` / `git blame` shows `akabak_solve_timeout_s` was added in `app/services.py` by commit `1fcd76b` (`feat(analyzer): add saved analyses storage and autopick service`) on 2026-02-22.
- `run_batch_pipeline` signature was not updated in the same change.

Related test evidence:
- `tests.test_service_export.ServiceExportTests.test_run_batch_auto_uses_dry_run_when_tools_missing` fails with the same `TypeError`.

## 3) Scope

Affected:
- Any GUI or service invocation path calling `OrchestratorService.run_batch`.
- Immediate failure before runtime orchestration starts.

Not affected:
- Batch creation, project creation, analyzer read paths.
- Runtime orchestration internals once entered (pipeline stages are not reached in this regression case).
- VACS export semantics (not reached due to early failure).

## 4) Fix Plan (Surgical)

1. Restore interface compatibility at the service->pipeline boundary by accepting the timeout argument in `run_batch_pipeline` with safe default behavior.
2. Wire the timeout value only through the existing AKABAK execution paths (subprocess and UI-driver wait) without changing stage flow/order/semantics.
3. Add a focused regression test that exercises real `service.run_batch(..., dry_run=True)` invocation path to catch signature mismatches.

Constraints:
- No redesign of runner orchestration.
- No compatibility logic changes.
- No analyzer behavior changes.
- No VACS export behavior changes.

## 5) Validation Plan

1. Re-run targeted failing tests:
   - `tests.test_service_export.ServiceExportTests.test_run_batch_auto_uses_dry_run_when_tools_missing`
   - `tests.test_ui_e2e_stress_runs.UiE2EStressRunsTests.test_three_full_ui_runs_are_stable`
2. Re-run minimal GUI repro flow and confirm status changes from immediate failure to successful completion.
3. Perform full lightweight GUI E2E:
   - create/select project
   - configure small batch (max 2 values per sweep)
   - run batch
   - verify completion state, DB run rows, and expected version artifacts.
