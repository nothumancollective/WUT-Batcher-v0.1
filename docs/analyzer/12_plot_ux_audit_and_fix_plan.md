# Analyzer Plot UX Audit + Fix Plan (2026-02-24)

## Scope
- Audit-only document for the current Explorer/Compare plot UX implementation.
- No KPI math, schema, importer, runner, or export pipeline behavior changes in this phase.
- This document maps each requested issue to concrete code locations and a minimal fix approach.

## Current rendering pipeline (status quo)
- Plot backend is custom Qt painting, not pyqtgraph:
  - Heatmap: `HeatmapCanvas` in `app/gui.py:645-962`
  - Metric overlays/curves: `MetricCurveCanvas` in `app/gui.py:964-1351`
  - Pareto scatter: `ParetoScatterCanvas` in `app/gui.py:1353-1664`
- Stage/tile mapping sources:
  - Explorer matrix: `STAGE_EXPLORER_LAYOUTS` in `app/gui.py:520-544`
  - Compare matrix: `STAGE_COMPARE_LAYOUTS` in `app/gui.py:552-571`
  - Stage switch apply: `_apply_stage_plot_layout` in `app/gui.py:6452-6542`
- Compare grid and controls are built in `app/gui.py:5583-5776`.
- Plot margin/tick helpers currently exist but are static:
  - `AnalyzerPlotStyle` + `apply_analyzer_plot_margins` in `app/gui.py:304-338`
  - log ticks in `app/gui.py:345-370`
  - angle ticks in `app/gui.py:445-468`

## Issue map -> evidence -> minimal fix plan

1) Axis label clipping / tick crowding / fonts+padding inconsistency
- Evidence:
  - Static margins and fixed tick label boxes in `app/gui.py:304-338`, `app/gui.py:821-829`, `app/gui.py:848-856`, `app/gui.py:1167-1180`, `app/gui.py:1572-1580`.
  - Fixed tiny plot title font in theme (`9px`) in `ui/theme.py:87-90`.
- Fix plan:
  - Introduce one central plot theme application path used by heatmap, curve, and pareto painters.
  - Move margin/font/tick density to dynamic sizing based on active font/plot geometry class (small/medium/large).
  - Keep existing data payloads and rendering backends; only adjust display metrics.

2) Excessive/uneven title sizing and duplicate visual emphasis
- Evidence:
  - Header title style is globally tiny (`ui/theme.py:87-90`) while axis/tick text is separately fixed in painter paths.
- Fix plan:
  - Normalize title/axis/tick/legend scale ratios via shared theme constants and apply consistently in all 3 canvas classes.

3) Overlong legend/series labels (must be only `V###`)
- Evidence:
  - Compare series labels currently include slot + batch/version and `[PIN]`: `app/gui.py:8110-8114`.
  - Missing-plane/status text also embeds `C# B#/V#`: `app/gui.py:8102`, `app/gui.py:8158`.
- Fix plan:
  - Add a single formatter `format_series_label(version_id) -> V###` and route all series labels through it.
  - Keep full identity only in tooltip/status/details, not in plotted labels.

4) Line thickness/legibility rules not matching requested constraints
- Evidence:
  - Compare selected line width can exceed 2 (up to 2.6+): `app/gui.py:8105-8108`.
  - Style profiles define >2 widths (3.0/3.2 etc.): `app/gui.py:7458-7477`.
- Fix plan:
  - Clamp normal width to 1, active width to 2, non-active alpha in 0.55-0.70 window.
  - Preserve style-mode semantics (trend/defect/strip) but within requested width envelope.

5) Compare bottom-right stage rule mismatch (hard requirement)
- Evidence:
  - Final compare `D` is currently `e_sym_shape`, not `s_theta`: `app/gui.py:565-570`.
- Fix plan:
  - Update stage mapping so:
    - Stabilization `D` = `e_sym_shape`
    - Final `D` = `s_theta`
  - Keep 4 plot tiles always active.

6) Compare tile sometimes shows selection hint despite candidates
- Evidence:
  - Curve render early-exits on empty `_compare_plot_items` and shows selection hint: `app/gui.py:8069-8071`.
  - Heatmap render requires selector/index and can show selection prompt: `app/gui.py:8172-8175`.
- Fix plan:
  - Use candidate count as primary guard for “Select candidates”.
  - If candidates exist but KPI/series missing, render axes + “Compute KPIs” overlay instead of empty/select prompt.

7) Compare left panel overlap / unused space
- Evidence:
  - Left side is wrapped in a `QScrollArea` with only a minimum width, no upper bound policy: `app/gui.py:5645-5652`.
  - Splitter hard sizes/stretch only (`app/gui.py:5773-5775`) and right min width (`app/gui.py:5771`) can force cramped behavior.
- Fix plan:
  - Apply explicit left panel width contract (min/max/default), proper size policies, remove oversized spacer behavior.
  - Keep splitter architecture; do not alter compare workflow logic.

8) Redundant compare controls (Overlay plane / Heatmap candidate)
- Evidence:
  - Redundant top-row controls exist in compare view: `app/gui.py:5659-5673`.
  - They are separately wired: `app/gui.py:6322-6323`.
- Fix plan:
  - Remove or hide both controls in Compare chrome.
  - Keep plane propagation driven by global display plane only.
  - Heatmap candidate follows active shortlist slot.

9) Stray text under plots
- Evidence:
  - Persistent compare hint label under grid: `app/gui.py:5766-5769`.
- Fix plan:
  - Remove static under-plot hint text.
  - Move context/help text into tile help tooltips.

10) Pareto scatter inconsistencies (theme mismatch/label overlap potential)
- Evidence:
  - Pareto uses fixed pixel text placements and marker labels inside canvas: `app/gui.py:1453-1468`, `app/gui.py:1619-1641`.
  - No shared dynamic tick-density profile with heatmap/curves.
- Fix plan:
  - Apply shared theme sizing and density selection.
  - Keep current scatter semantics; improve readability/spacing and consistent axis treatment.

11) Black background box perception
- Evidence:
  - Plot canvases explicitly fill dark solid backgrounds (`#111217`): `app/gui.py:744`, `app/gui.py:1007`, `app/gui.py:1393`.
  - Compare containers themselves are already transparent by theme (`QFrame#ProjectIssuesPanel`): `ui/theme.py:989-993`.
- Fix plan:
  - Keep plot backgrounds but remove heavy surrounding container look by making compare wrappers/padding subtler and avoiding extra “hint strip” blocks.
  - Verify no additional non-plot dark slabs remain.

12) Target window visibility not guaranteed enough across all stages
- Evidence:
  - Target overlay alpha is stage-dimmed outside concept (`app/gui.py:7435-7449`), can become visually weak.
  - Overlay draw path exists (`app/gui.py:859-882`, compare path uses same overlay payload in `app/gui.py:8182-8204`).
- Fix plan:
  - Make target boundaries/fill always visible and consistent across stages.
  - Add target badge in tile header; keep plot interior free of redundant text.

13) Color palette for non-heatmap plots not explicit by KPI type
- Evidence:
  - Most series colors are slot-driven via `compare_overlay_color(index)` in compare and explorer (`app/gui.py:8116`, `app/gui.py:7579`).
- Fix plan:
  - Introduce minimal KPI palette mapping for single-metric tiles and threshold bands.
  - Preserve slot colors for compare overlays as requested.

14) Help icon style mismatch
- Evidence:
  - Plot help buttons are plain text `"?"`: `app/gui.py:6390-6393`.
  - No dedicated style entry for `BatchSecondaryToolButton` in theme.
- Fix plan:
  - Replace text glyph with same icon family used by top bar icons; add lightweight hover style.
  - Keep tooltip behavior; no persistent inline help text.

## Root causes summary
- UX rules are currently distributed across three separate custom painters with mostly fixed pixel constants.
- Compare view still carries legacy controls/text and label contracts that conflict with the new plot-first design.
- Stage matrix is centralized now, but one hard mapping rule (final compare bottom-right metric) is currently out-of-spec.

## Ordered surgical implementation plan
1. Add central plot theme hooks (fonts/margins/tick density) and route all three canvas renderers through them.
2. Enforce `V###` series labels and updated line width/alpha contract.
3. Correct compare stage matrix bottom-right behavior and missing-data placeholder behavior.
4. Tighten compare splitter width policy and remove redundant compare-top controls and under-plot hint text.
5. Strengthen always-on target overlay visibility and header badge.
6. Update help icon style and add focused UI regression coverage + E2E smoke report.

## Status update (2026-02-24)
- `FIXED/VERIFIED` issue cluster 1 (axis/label/layout):
  - Dynamic `QFontMetrics` margins and axis/tick spacing are now shared across Heatmap/Curve/Pareto via `apply_plot_theme(...)`.
  - Layout geometry contract added via `compute_plot_layout_geometry(...)` and covered by regression tests.
  - Heatmap angle ticks now render with explicit `deg` labels and improved non-overlapping spacing.
  - Pareto now uses the shared axis-label path (rotated y-label + dynamic bottom spacing), removing prior orientation/clipping drift.
