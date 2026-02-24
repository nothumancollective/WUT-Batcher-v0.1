# Analyzer Stage/Selection/Plane Regression Audit (2026-02-24)

Date: 2026-02-24  
Branch: `feature/polar-analyzer-ui`  
Scope: Phase 0 root-cause audit only (no code changes)

## 1) Symptom Summary

Reported regressions after Analyzer stage refactor to Concept/Stabilization/Final:

1. Version selection and Version Information appear to work in Concept but break in Stabilization/Final.
2. Version Information KPI block is not stage-aware (labels/values stay Concept-oriented).
3. Compare plane changes from Display controls (H/V/D) do not propagate to Compare visuals.

## 2) Reproduction and Evidence

## 2.1 Stage switch empties selection context in Stabilization/Final

Runtime dataset probe (project-backed service):

- Project/Batch used for deterministic repro: `P021/B011`
- Service rows per stage via `analyzer_list_batch_review_runs(...)`:
  - Concept: 2 rows
  - Stabilization: 2 rows
  - Final: 2 rows
- After UI stage default filters are applied:
  - Concept filtered rows: 2
  - Stabilization filtered rows: 0
  - Final filtered rows: 0

Key observed reason codes on those rows: `INSUFFICIENT_ANGLE_COVERAGE` (warn severity).

Expected:
- Stage change should preserve selected version context and keep version info visible when rows exist.

Observed:
- Stage switch triggers filter defaults that remove all rows in Stabilization/Final, so selection clears and Version Information becomes empty.

## 2.2 Compare plane propagation failure from Display plane buttons

Widget-level repro:

- Open Analyze page, switch to Compare tab.
- Initial state: compare plane = `H`, active display plane = `H`.
- Toggle Display plane button to `V`.

Observed:
- `active_plane` changes to `V`.
- Compare plane remains `H`.
- Explorer refresh path is called, Compare refresh path is not called.

Expected:
- Compare should follow current global/display plane selection (or explicitly communicate decoupling).

## 2.3 KPI block is Concept-static

Source-level evidence:

- Version information KPI labels are statically created for Concept metrics only.
- Value update path writes only Concept aggregate fields (`kpi_b_pc_oct`, `kpi_e_bw`, `kpi_e_cov`, `kpi_r_spill`) plus score/flags.
- No stage-specific mapping is applied on stage change for label/value rows.

Expected:
- Stage change updates KPI rows (labels + values) according to stage mapping.

## 3) Confirmed Root Causes (with code references)

## 3.1 Stage defaults apply hard warning exclusion outside Concept

- `app/analyzer/presets.py`:
  - Stabilization filters: `exclude_warnings=True`
  - Final filters: `exclude_warnings=True`
- `app/gui.py:8644-8651` (`_apply_stage_defaults`) applies these defaults on every stage change.
- `app/gui.py:8675-8689` (`_filtered_rows`) drops rows when `exclude_warnings` and `_row_has_warning(...)`.
- `app/gui.py:8817-8827` (`_on_stage_changed`) reapplies defaults and refreshes runs, causing immediate row disappearance in warning-heavy batches.

Impact:
- Selection bar and version info appear broken in Stabilization/Final because the row set becomes empty.
- Compare manual add-selection path also becomes unusable for those stages (Auto Pick still works because it uses service-side candidate scan, not current table selection).

## 3.2 Version Information KPI model is stage-invariant

- `app/gui.py:5708-5716`: static KPI label set (Score/Pattern Ctrl/BW Error/Cov Error/Spill/Flags).
- `app/gui.py:8500-8505`: static value binding to Concept aggregate keys; no stage-specific remap.

Impact:
- Stage-dependent KPI semantics are not reflected in labels/values.

## 3.3 Display plane and Compare plane states are disconnected

- `app/gui.py:6798-6803` (`_on_plane_toggled`) updates `_active_plane` and schedules Explorer plot refresh only.
- Compare uses separate source of truth `compare_plane_combo` via `_compare_plane()` at `app/gui.py:7383-7385`.
- Compare fetch/render workers use `self._compare_plane()` (for example `app/gui.py:7433`), so Display plane changes do not affect Compare unless combo is changed separately.

Impact:
- Compare plots/tables can remain on stale plane after user changes Display plane.

## 4) Scope and Non-Scope

Affected:
- Analyzer Explorer/Compare stage transitions, selection persistence behavior, version info KPI presentation, compare plane propagation.

Not affected by this audit:
- Runner execution pipeline
- VACS export logic and enforcement
- Project/batch compatibility semantics
- Importer schema contracts

## 5) Surgical Fix Plan

1. Preserve selected version context across stage change:
   - Keep current selection identity stable.
   - Avoid destructive filter reset behavior that empties rows on stage switch.
   - Rebuild detail panel from preserved selection when row still exists.

2. Add stage-aware KPI mapping for Version Information:
   - Introduce deterministic `stage -> metric rows` mapping (labels + value keys).
   - Re-render KPI rows on stage change.
   - Show fallback placeholders (`--`) with compute hint if missing.

3. Propagate Display plane to Compare rendering path:
   - Sync Display plane changes into compare plane source of truth.
   - Trigger compare redraw/reload for plane-dependent visuals.
   - Surface per-candidate missing-plane status in Compare messaging (no silent failure).

4. Regression tests:
   - Stage switch preserves selected context and populated info.
   - Stage KPI row mapping changes as expected.
   - Compare plane propagation triggers refresh and updates plane source.

## 6) Validation Plan

1. Run focused Analyzer UI tests (`tests/test_gui_analyzer_page_ui.py`, `tests/test_gui_analyzer_compare_ui.py`) plus new regression cases.
2. Perform GUI smoke flow:
   - Explorer: select batch/version, switch Concept -> Stabilization -> Final, verify selection + info.
   - Compare: auto-pick and manual selection in all stages, change H/V/D and confirm compare visuals follow plane.
3. Confirm no regressions in existing Analyzer tests.
