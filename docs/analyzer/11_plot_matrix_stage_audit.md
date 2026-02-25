# Analyzer Plot Matrix Stage Audit (2026-02-24)

## Scope
- Audit only (no behavior changes in this document).
- Target: verify Explorer/Compare 2x2 matrix by stage (`concept`, `stabilization`, `final`) against the authoritative spec.
- Constraints respected: polar-only, no KPI math/schema/runner changes.

## Where stage-to-plot mapping is defined
- Explorer stage matrix is defined in `STAGE_EXPLORER_LAYOUTS`:
  - `app/gui.py:520-544`
- Compare currently uses a fixed 2x2 panel construction:
  - `app/gui.py:5653-5725`
- Stage switch updates:
  - Explorer panel kind/title via `_apply_stage_plot_layout`: `app/gui.py:6424-6475`
  - Compare overlay key only via `STAGE_COMPARE_OVERLAY_KEY`: `app/gui.py:546-550`, `app/gui.py:6456-6471`

## Plot backends and rendering modes (current)
- Heatmap renderer: `HeatmapCanvas` (`app/gui.py:624-940`)
  - log-frequency major/minor ticks: `app/gui.py:784-808`
  - angle grid/ticks (15 deg grid): `app/gui.py:822-836`, `_angle_ticks` in `app/gui.py:445-468`
  - target-window shading + `-6 dB` contour overlays: `app/gui.py:838-915`
  - raw/smoothed toggle: `Qt.FastTransformation` vs `Qt.SmoothTransformation`: `app/gui.py:773-775`
- Curve renderer: `MetricCurveCanvas` (`app/gui.py:943-1329`)
  - line, trend band, consistency strip, defect band styles: `app/gui.py:1222-1302`
  - defect risk zones/hotspots: `app/gui.py:1161-1192`, `app/gui.py:1270-1300`
- Pareto renderer: `ParetoScatterCanvas` (`app/gui.py:1332+`)

## Actual Explorer matrix (current)

### Concept
- A: Heatmap
- B: Pareto decision snapshot (`pareto_decision`)
- C: `E_cov` curve
- D: `R_spill` curve
- Evidence: `app/gui.py:520-531`, `app/gui.py:7440-7520`

### Stabilization
- A: Heatmap
- B: `DI_proxy` trend-band style
- C: `S_theta` consistency-strip style
- D: `E_sym_shape` consistency-strip style
- Evidence: `app/gui.py:532-537`, style mapping `app/gui.py:7386-7404`, render `app/gui.py:7500-7516`

### Final
- A: Heatmap
- B: `R_off` defect-band style
- C: `S_theta` consistency-strip style
- D: `E_sym_shape` consistency-strip style
- Evidence: `app/gui.py:538-543`, style mapping `app/gui.py:7405-7419`, render `app/gui.py:7500-7516`

Explorer status vs spec:
- Largely aligned with intended stage language.
- Concept differs slightly from requested ordering (spec says A2 `E_cov`, A3 `R_spill`, A4 Pareto; current has Pareto in B and `E_cov`/`R_spill` in C/D). Content is present, ordering differs.

## Actual Compare matrix (current)

Current fixed tiles for all stages:
- Compare A: Overlay curve panel (stage selects only curve key: beamwidth/di_proxy/r_off)
- Compare B: Candidate heatmap
- Compare C: Active candidate focus curve (same key as overlay)
- Compare D: Pareto scatter
- Evidence:
  - fixed grid construction: `app/gui.py:5660-5719`
  - focus curve render: `app/gui.py:7924-7960`
  - overlay render: `app/gui.py:7962-8047`
  - pareto render: `app/gui.py:8119-8158`

Stage dependency in Compare today:
- Only overlay/focus curve key changes with stage (`beamwidth`, `di_proxy`, `r_off`):
  - `app/gui.py:546-550`, `app/gui.py:6456-6471`
- Compare overlay/focus do not currently apply stage style profiles (`trend_band` / `defect_band`) and therefore still look line-like:
  - no `_curve_style_profile(...)` usage in `_render_compare_overlay`/`_render_compare_focus_curve`
  - `app/gui.py:7924-8047`

## Deviations vs authoritative spec

1. Compare stage matrix is not stage-specific enough.
- Spec requires per-stage 4-plot matrix where stabilization/final include dedicated smoothness and plane-consistency compare plots.
- Current Compare always has overlay + heatmap + active-focus + pareto.

2. Stabilization Compare is missing required dedicated plot tiles:
- Missing explicit `S_theta` compare tile and `E_sym_shape` compare tile.
- Current bottom-left is active-candidate focus of overlay key, not `S_theta`.

3. Final Compare is missing required dedicated plot tiles:
- Missing explicit `S_theta` compare tile and `E_sym_shape` compare tile.
- Current bottom-left is active-candidate focus of `r_off`, not `S_theta`.

4. Concept Compare C4 mismatch:
- Spec requires a coverage/spill comparison plot.
- Current C4 is Pareto and C3 is active focus curve; no dedicated coverage/spill compare tile.

5. Compare rendering style distinction is incomplete:
- Explorer has distinct stabilization/final styles.
- Compare overlay/focus currently render as line overlays with alpha/width emphasis only.

## Implementation plan (surgical)

1. Add explicit Compare stage matrix mapping (new `STAGE_COMPARE_LAYOUTS`) for 4 plot keys/kinds per stage.
- Concept: heatmap + target/decision compare + pareto + coverage/spill compare.
- Stabilization: heatmap + `di_proxy` trend compare + `s_theta` compare + `e_sym_shape` compare.
- Final: heatmap + `r_off` defect compare + `s_theta` compare + `e_sym_shape` compare.

2. Reuse existing compare panel stacks (`heatmap_canvas`, `curve_canvas`, `pareto_canvas`) and switch panel kinds per stage via `_set_stage_panel_kind`.
- No new plot engine.
- No KPI/data contract changes.

3. Introduce stage-aware compare render dispatcher.
- Replace single-purpose overlay/focus rendering with per-tile render by key.
- Keep active-slot semantics for heatmap candidate and optional visual emphasis in curve overlays.

4. Apply `_curve_style_profile(..., context='compare')` for compare curves so stabilization/final style language remains distinct in Compare.

5. Preserve worker-threaded data loading path and existing shortlist/plane propagation behavior.

## Risk notes
- Main risk is wiring regressions in Compare panel routing; mitigate with deterministic stage-matrix tests.
- No schema/service/pipeline risk expected because payload contract is unchanged.
