# Analyzer Stage Visualization Refactor Audit (2026-02-24)

## Scope and constraints
- Goal: make `concept`, `stabilization`, and `final` visually distinct using existing polar data and existing KPI series.
- Out of scope: runner/export pipeline, importer/schema, KPI math/scoring, new data sources.
- Constraint: keep existing worker-threaded plot loading path.

## Current rendering architecture

### Data flow and threading
- Explorer plot loading uses `_AnalyzerPlotWorker` (Qt worker thread) and calls `service.analyzer_load_stage_plot_payload(...)`.
  - `app/gui.py:1923-2004`, `app/gui.py:7014-7073`
- Compare plot loading uses `_AnalyzerComparePlotWorker` (Qt worker thread), loading one stage payload per candidate.
  - `app/gui.py:2647-2732`, `app/gui.py:7525-7608`
- Stage payload assembly is in service + stage plot engine:
  - `app/services.py:2568-2697`
  - `app/analyzer/stage_plot_engine.py:324-402`

Conclusion: heavy DB reads/curve computation already happen off the UI thread and should remain unchanged.

### Plot backend and capabilities
- Backend is custom Qt painting (`QPainter`) in app code, not matplotlib/pyqtgraph:
  - `HeatmapCanvas` in `app/gui.py:619-906`
  - `MetricCurveCanvas` in `app/gui.py:909-1131`
  - `ParetoScatterCanvas` in `app/gui.py:1134+`
- Shared axis/margin helpers already exist:
  - `apply_analyzer_plot_margins`, `_log_tick_sets`, `_draw_analyzer_*_axis_label` in `app/gui.py:331-409`
- Heatmap already supports:
  - clamp/raw-bin smoothing switch (`Qt.SmoothTransformation` vs `Qt.FastTransformation`)
  - target-window shading
  - `-6 dB` contour overlays
  - angle/frequency grids and labels.
  - refs: `app/gui.py:745`, `app/gui.py:756-883`
- Curve canvas already supports multi-series, legend, log ticks, per-series `alpha` and `line_width`.
  - refs: `app/gui.py:957-1110`

Conclusion: stage-language changes can be implemented by extending `MetricCurveCanvas` style modes and by stage-aware render metadata, without changing payload schema or adding new plotting libraries.

## Current stage plot semantics (before refactor)
- Stage layouts and compare overlay key are configured by constants:
  - `STAGE_EXPLORER_LAYOUTS` + `STAGE_COMPARE_OVERLAY_KEY` in `app/gui.py:520-545`
- Current Explorer:
  - `concept`: `heatmap`, `e_bw`, `e_cov`, `r_spill`
  - `stabilization`: `heatmap`, `di_proxy`, `s_theta`, `e_sym_shape`
  - `final`: `heatmap`, `r_off`, `s_theta`, `e_sym_shape`
- Current Compare overlay is still line-series for all keys, with only label/title changes and active-candidate emphasis.
  - `app/gui.py:7667-7752`

Observed issue: stage-specific metric choices exist, but visual grammar is mostly identical (line overlays), so stabilization and final feel redundant.

## Existing data available for display-only styling
- Stage payload provides exactly what is needed:
  - heatmap overlays (`minus6_contour`, `target_half_window_deg`)
  - curves (`e_bw`, `e_cov`, `r_spill`, `di_proxy`, `s_theta`, `e_sym_shape`, `r_off`, `beamwidth`)
  - per-stage summary values.
  - `app/analyzer/stage_plot_engine.py:347-401`

No additional DB fields or KPI computations are required for the requested visual differentiation.

## Minimal-change implementation plan

### 1) Concept stage language (decision oriented)
- Keep `heatmap` in Explorer slot A with target shading + `-6 dB` contour (already available).
- Keep concept metric panels in slots B/C/D but remove redundant in-plot status text when not needed.
- Ensure heatmap and curve axis labels/ticks remain explicit (`Frequency (Hz, log)`, `Angle (deg)`).

### 2) Stabilization stage language (trend/consistency)
- Keep same metric keys (`di_proxy`, `s_theta`, `e_sym_shape`) but switch rendering mode away from plain thin-line:
  - use band/trend style for `di_proxy` (thicker line + soft fill/ribbon and threshold markers).
  - use strip/compact trend style for `s_theta` and `e_sym_shape`.
- Implement via new curve-style metadata in UI render path (no payload changes).

### 3) Final stage language (defect hunting)
- Keep `r_off` metric key but render as defect/risk style:
  - filled risk band with threshold zones and optional hotspot markers.
- Keep `s_theta` and `e_sym_shape` in compact stabilization-style language so `r_off` remains the visual focus.

### 4) Compare alignment
- Reuse same stage style mapping for Compare overlay and focus panels:
  - stabilization `di_proxy` overlay uses trend-band style
  - final `r_off` overlay uses defect/risk style
- Preserve active-candidate emphasis and plane propagation behavior.

### 5) Graph quality and readability
- Keep log tick set from `_log_tick_sets` and angle tick grids as canonical.
- Remove redundant in-plot text for titles already represented in panel headers.
- Keep raw-bin toggle behavior unchanged (`Show raw bins` off -> smoothed; on -> blocky).
- Tune plot margins minimally only if needed for 1366x768 clipping.

## Planned touch points (code-level)
- `app/gui.py`
  - `MetricCurveCanvas`: add optional rendering style modes (`line`, `trend_band`, `defect_band`, `strip`) and optional threshold/hotspot metadata.
  - `_render_plot_payload`: attach per-stage/per-metric style metadata when setting series.
  - `_render_compare_overlay` + `_render_compare_focus_curve`: apply stage style metadata to compare series.
  - `STAGE_EXPLORER_LAYOUTS` metadata copy/text updates for stage language clarity (display-only).
- Tests:
  - extend analyzer GUI tests to assert stage-specific rendering mode metadata differs by stage/key.
  - assert raw-bin toggle keeps heatmap mode behavior.
  - assert axis labels remain non-empty and log-frequency label remains configured.

## Risk assessment
- Low risk:
  - display-layer changes in custom canvases and UI render wiring.
  - no service payload contract changes required.
- Medium risk:
  - overloading `MetricCurveCanvas` complexity; mitigate by adding minimal optional style fields and preserving existing default line behavior.
- Regression watch:
  - compare overlay/active-slot emphasis
  - plane missing status handling
  - small-window label clipping.

## Execution order
1. Concept pass: heatmap-focused cleanup and title/status text reduction.
2. Stabilization pass: trend/consistency rendering styles.
3. Final pass: ripple defect rendering style.
4. Compare style parity pass.
5. Tests + smoke report.
