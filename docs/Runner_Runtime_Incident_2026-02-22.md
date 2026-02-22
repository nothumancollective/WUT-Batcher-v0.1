# Runner Runtime Incident Report (2026-02-22)

## Scope

Manual run investigation for project `P021`, batch `B001`, run id
`55251260-e98f-40cb-bf78-92364b0cf068` in:

- `cleanup/runtime/postmerge_lib/P021`

Goal of this report:

1. Explain why the first processed version had no expected SPL result.
2. Explain why processing stopped from the next version onward.
3. Verify whether cleanup logic in the production runner path caused this.
4. Document where cleanup is implemented and where a settings switch must be connected.

This is a documentation-only analysis (no code changes in this commit).

## Evidence Reviewed

- `cleanup/runtime/postmerge_lib/P021/dataset/project.sqlite`
- `cleanup/runtime/postmerge_lib/P021/versions/V004/version.json`
- `cleanup/runtime/postmerge_lib/P021/versions/V005/version.json`
- `cleanup/runtime/postmerge_lib/P021/versions/V004/logs/ath.runner.log`
- `cleanup/runtime/postmerge_lib/P021/versions/V005/logs/ath.runner.log`
- `cleanup/runtime/postmerge_lib/P021/versions/V004/logs/vacs.export_pipeline.json`
- `cleanup/runtime/postmerge_lib/P021/versions/V004/logs/external_vacs_export_save_all/run_20260222_221742/summary.json`
- `cleanup/runtime/postmerge_lib/P021/batches/B001/batch.json`

## Timeline (UTC)

- `2026-02-22T22:13:55+00:00`: run started (`runs.status=running`), versions `V004..V006` inserted as `planned`.
- `2026-02-22T22:13:55+00:00`: `V004` ATH attempt 1 exit `0`.
- `2026-02-22T22:17:51+00:00`: `V004` finished as `success`.
- `2026-02-22T22:17:51+00:00`: `V005` ATH attempt 1 started.
- `2026-02-22T22:20:51+00:00` (derived from timeout+180s): `V005` ATH attempt 1 timeout.
- Manual abort happened before the pipeline could persist a final run/version state.

## Findings

### F1: "No SPL graph in first version" is a VACS export/mapping issue, not an ATH failure

The first processed version in this run is `V004` (not `V001`).

Observed behavior:

- `V004` completed with `status=success` in `version.json`.
- VACS external export summary reports:
  - `exported_ok_count=3`
  - `exported_failed_count=1`
  - failure reason: `export_configuration_invalid` for
    `Radiation Impedance - Radiation_Impedance #5`.
- Exported files came from `Mic Polar - BE_Spectrum #2/#3/#4`.
- Ingestion mapped these via `mapping_mode=any_graph` to `graph_kind=spl` (`external_01..03`).

Impact:

- No clean "main SPL + impedance + polar set" was produced.
- The run can still become `success` because this path accepted partial export success and no hard failure was raised.

### F2: "Runner did not start from second version" is an ATH-stage timeout + manual abort

Observed behavior for `V005`:

- `ath.runner.log`: `attempt=1 timeout after 180s`.
- `ath.stdout.log` and `ath.stderr.log`: timeout header only, no produced output body.
- `version.json` for `V005` still `status=planned` with no `ath_result` block.
- `runs` table remains `status=running`; `finished_at` is `NULL`.

Interpretation:

- Pipeline entered ATH stage for `V005`, but did not complete the ATH call.
- Manual interruption happened before post-stage state persistence (`ath_failed/failed`) and run finalization.

Corroborating artifact:

- `C:\Horns\P021_B001_V005_55251260` exists with only partial files
  (`ABEC_FreeStanding/bem_mesh.geo`, empty `solving.txt`), matching a mid-stage timeout/abort.

### F3: Cleanup routine is not the cause of the `V005` timeout in this run

For `V004` (successful version), cleanup clearly executed:

- `cleanup/runtime/postmerge_lib/P021/versions/V004/cfg/P021_B001_V004_55251260.cfg` is deleted.
- `C:\Horns\P021_B001_V004_55251260` is deleted.

For `V005` (interrupted version), cleanup did not execute:

- `cleanup/runtime/postmerge_lib/P021/versions/V005/cfg/P021_B001_V005_55251260.cfg` still exists.
- `C:\Horns\P021_B001_V005_55251260` still exists.

Conclusion:

- In this incident, cleanup ran only after successful `V004` and targeted only version-local/generated artifacts.
- There is no overlap between cleaned `V004` targets and `V005` runtime targets.
- Therefore cleanup is unlikely to be the reason why `V005` stalled.

## Cleanup Routine Map (Production Runner Path)

### Runtime execution and cleanup trigger

- `app/runtime_orchestrator.py:1560`: `run_batch_pipeline(...)`.
- `app/runtime_orchestrator.py:2364`: cleanup is executed only when `final_ok` is true.
- `app/runtime_orchestrator.py:2365`: delete per-version runtime cfg (`cfg/<run_cfg>.cfg`) via guarded delete.
- `app/runtime_orchestrator.py:2382`: delete ATH export subdir (`<ath_export_root>/<run_cfg_stem>`) via guarded delete.
- `app/runtime_orchestrator.py:2408`: on failure/persist issues, cleanup is skipped and recorded as skip reason.
- `app/runtime_orchestrator.py:1030`: `_append_cleanup_skip(...)` writes skip entries into `cleanup_results`.

### Guardrails

- `app/safe_cleanup.py:33`: `guarded_delete_tree(...)`.
- `app/safe_cleanup.py:143`: `guarded_delete_file_in_workspace(...)`.
- Guard checks include root-boundary checks, deny lists, and expected path shape constraints.

### What is currently NOT cleaned in production runner

- `ath_work` is created per version (`app/runtime_orchestrator.py:1745`) and is currently not deleted in the final cleanup branch.
- This means ATH helper/config artifacts remain under `versions/<Vxxx>/ath_work` after successful runs.

## Gap to Requested Feature (Settings Switch for Cleanup)

Requested target behavior:

- Cleanup routine should be user-switchable in Settings.
- Cleanup should cover ATH scripts/work artifacts and ATH export folder per version.

Current state:

- No dedicated cleanup toggle in settings model:
  - `app/settings_store.py:45` (`UserSettings`) has no cleanup field.
- No GUI control in settings dialog:
  - `app/gui.py:3005` to `app/gui.py:3012` only shows tool paths + automation + timeout.
- No CLI switch for `run pipeline`:
  - `app/cli.py:198` to `app/cli.py:213`.
- `OrchestratorService.run_batch(...)` always calls runner with default cleanup behavior:
  - `app/services.py:2868` to `app/services.py:2903`.

Note:

- Existing `--cleanup-files` flags in `app/cli.py:1539` apply to
  `projectpage-ath-experiment` tooling, not to the production batch runner flow.

## Recommended Implementation Direction (for next code pass)

1. Add settings flag `runtime_cleanup_enabled` (default `true`).
2. Add optional second flag `runtime_cleanup_delete_ath_work` (default `false` or `true`, product decision).
3. Thread flags through:
   - `UserSettings` serialization/deserialization,
   - GUI Settings dialog,
   - `OrchestratorService.run_batch(...)`,
   - `run_batch_pipeline(...)` cleanup branch.
4. Keep `safe_cleanup` guard APIs for all deletions; do not add direct `rmtree/unlink` calls.
5. Persist explicit cleanup decision in `cleanup_results` for each version (`enabled/disabled` reason codes).

## Bottom Line

- Incident root causes are:
  - VACS export/mapping quality issue in `V004` (partial/incorrect graph set interpreted as success).
  - ATH timeout + manual interruption in `V005` before state finalization.
- Cleanup did execute for `V004`, but evidence does not support cleanup as cause of `V005` stall.
- A settings-driven cleanup toggle for the production runner path is currently missing and should be added in a dedicated code change.
