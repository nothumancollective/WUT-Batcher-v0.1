# Analyzer Plot UX Polish Smoketest (2026-02-24)

## Scope
- Explorer + Compare plot UX validation after axis/layout, target-overlay, transparent-canvas, compare-left-layout, info-icon, and metric-band-toggle fixes.
- Polar-only stages: `concept`, `stabilization`, `final`.

## Environment
- Branch: `feature/polar-analyzer-ui`
- Mode: Qt offscreen smoke (headless GUI lifecycle, real widgets/layout/render paths)
- Backend: existing `OrchestratorService` wiring with seeded compare payload for deterministic stage checks

## Executed flow
1. Create `AnalysePage` with real service/settings wiring.
2. Seed compare candidates and stage plot payload (`heatmap_overlays`, stage curves, summary KPIs).
3. Run resize probes at:
   - `1920x1080`
   - `1366x768`
   - `1100x700`
4. Switch stages (`concept -> stabilization -> final`) and render Explorer/Compare views.
5. Verify compare matrix mapping (`A..D`) and target-overlay alpha floors.
6. Validate axis layout geometry contract (`x-axis title` below `x tick labels`).
7. Validate help icons and metric-band default state.
8. Validate transparent outer-canvas behavior (corner alpha checks).

## Observed evidence
- Resize + compare-left contract:
  - `1920x1080`: left width `260`, horizontal scrollbar `False`
  - `1366x768`: left width `260`, horizontal scrollbar `False`
  - `1100x700`: left width `260`, horizontal scrollbar `False`
- Stage matrix (Compare):
  - `concept`: `A=heatmap`, `B=beamwidth`, `C=pareto`, `D=e_cov`
  - `stabilization`: `A=heatmap`, `B=di_proxy`, `C=s_theta`, `D=e_sym_shape`
  - `final`: `A=heatmap`, `B=r_off`, `C=e_sym_shape`, `D=s_theta`
- Target overlay visibility (all stages):
  - `target_shade_alpha=56`, `target_boundary_alpha=208`
- Axis layout overlap checks:
  - explorer `A` and `B`: `overlap_ok=True`
  - heatmap y-axis label remains `Angle (deg)`
- Help icon + metric band default:
  - help icons consistent with info icon asset
  - `show_metric_bands_default=False`
- Transparent outer-canvas checks:
  - heatmap corner alpha `0`
  - curve corner alpha `0`
  - pareto corner alpha `0`

## Acceptance criteria status
- A) Axis label/tick overlap/clipping: **PASS**
- B) Heatmap angle axis in degrees + cues: **PASS**
- C) Compare target overlay visibility: **PASS**
- D) No black-box slab look (transparent outer canvases): **PASS**
- E) Compare left table clipping/reachability: **PASS**
- F) Help icon is info (`i`) not gear: **PASS**
- G) Metric band does not obstruct and is togglable in Display Advanced: **PASS**
- H) Resize stability (`1920x1080`, `1366x768`, `1100x700`): **PASS**

## Guardrail check
- No Runner/VACS/export/import/schema/KPI-math changes in this smoke/fix series.
