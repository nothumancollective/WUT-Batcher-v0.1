# Analyzer Compare Left-Panel KPI Table Audit (2026-02-24)

Date: 2026-02-24  
Branch: `feature/polar-analyzer-ui`  
Scope: Phase 0 audit only (no functional changes in this commit)

## Goal

Restructure Compare so KPI comparison lives in the left panel and remove the in-grid `Selected Candidate KPIs` block, while preserving existing compare behavior (add/auto-pick/save/load/plots).

## Current Compare Structure (confirmed)

## Layout wiring

- Compare root is built in `AnalysePage`:
  - Left panel in `app/gui.py` around `compare_left` (`~5318+`)
  - Right panel in `app/gui.py` around `compare_right` (`~5421+`)
- Current left panel contains:
  - actions frame (`Add selected`, `Auto-pick...`, `Save Analysis...`, `Saved+Load`, `Cancel`)
  - shortlist table `compare_slots_table` (5x5): `Slot`, `Selection`, `Score`, `Flags`, `Remove`
- Current right panel contains:
  - top row controls (`Overlay plane`, `Heatmap candidate`)
  - 2x2 grid where bottom-left is currently `compare_kpi_panel` (`Selected Candidate KPIs`)
  - bottom-right is Pareto panel

## Problematic element to remove from grid

- `compare_kpi_panel` + `compare_kpi_matrix` is created at `app/gui.py` (`~5380..5416`)
- It is inserted into compare grid bottom-left at:
  - `app/gui.py` (`self.compare_grid_layout.addWidget(self.compare_kpi_panel, 1, 0, 1, 1)`)

This is the main space consumer currently shrinking plot area.

## State/model and bindings currently in use

- Candidate source of truth:
  - `self._compare_candidates` (`List[Dict]`) populated by:
    - `_set_compare_candidates(...)`
    - `_on_compare_add_selected(...)`
    - `_on_autopick_finished(...)`
    - saved-analysis load path
- Active candidate:
  - `self._selected_compare_slot_index`
  - updated by `_on_compare_slot_selection_changed(...)`
- Table/render update hub:
  - `_update_compare_slots(...)`
  - fills shortlist rows, remove buttons, heatmap selector options
- In-grid KPI matrix update:
  - `_update_compare_kpi_panel(...)`
  - uses fixed KPI rows and per-candidate columns C1..C5
- Stage influence:
  - stage changes call `_apply_stage_plot_layout(...)` and data refresh paths
  - compare overlay metric key is stage-dependent (`self._compare_overlay_curve_key`)
  - shortlist KPI columns are currently not stage-dependent
- Heatmap selector:
  - currently follows `self._selected_compare_slot_index` when options are rebuilt in `_update_compare_slots(...)`

## Confirmed constraints for surgical replacement

- Must not alter KPI computation/scoring logic (`app/services.py` + analyzer engines remain untouched).
- Must not alter DB schema/import/export/runner.
- Must remain UI-thread safe (compare data loads stay worker-threaded as currently implemented).

## Replacement Plan

1. Remove in-grid KPI panel
- Delete insertion of `compare_kpi_panel` from 2x2 grid.
- Keep right grid as plot-only 2x2: overlay, heatmap, pareto + one additional plot tile placeholder/metric tile already present in stage model (no KPI table block).

2. Redesign left panel around one combined compare table
- Keep existing actions row semantics unchanged.
- Replace current shortlist table schema with a combined slot+KPI table:
  - fixed 5 rows (`C1..C5`)
  - columns: slot chip, selection, score, flags, stage KPI columns, remove
- Ensure compact widths and right-aligned numeric columns.

3. Add display-only Stage -> KPI column mapping for compare left table
- Concept: Pattern Ctrl (oct), BW Err (deg), Cov Err (dB), Spill Ratio
- Stabilization: DI Trend (dB), Smoothness, Plane Consistency (+ Spill optional)
- Final: Off-axis Ripple (dB), Smoothness, Plane Consistency (+ Cov Err optional)
- Missing KPI values render `--` + tooltip `Compute KPIs to populate`.

4. Active candidate wiring
- Keep slot row click as active-candidate source.
- Ensure active row drives:
  - heatmap selector default/current
  - overlay emphasis (selected candidate visually emphasized, colors unchanged)

5. Tests and docs
- Add focused compare-left-panel regression tests for:
  - fixed 5 slots
  - stage column remap
  - row click -> active candidate + heatmap selector sync
  - remove-row stability
- Update analyzer docs/changelog to reflect new compare responsibilities.
