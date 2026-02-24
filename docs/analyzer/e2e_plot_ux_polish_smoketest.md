# Analyzer Plot UX Polish Smoketest (2026-02-24)

## Scope
- Explorer + Compare plot UX validation after plot-theme unification and compare-matrix fixes.
- Polar-only stages (`concept`, `stabilization`, `final`) with shared plane controls.

## Environment
- Branch: `feature/polar-analyzer-ui`
- Qt mode: `offscreen` (headless GUI smoke run in CI-like shell)
- Backend: existing Analyzer service + in-memory temporary workspace

## Executed flow
1. Instantiate `AnalysePage` with real `OrchestratorService` wiring.
2. Resize window to `1920x1080`, then `1366x768`.
3. Seed compare candidates (`C1..C3`) and compare plot payload (heatmap + stage curves).
4. Switch stages in order: `concept -> stabilization -> final`.
5. Render compare visuals per stage and inspect slot mapping (`A..D`) and labels.
6. Toggle plane from display controls and verify compare plane propagation path.

## Observed results
- Grid integrity:
  - Explorer: always 4 stage panels.
  - Compare: always 4 stage panels.
- Stage matrix (Compare):
  - `concept`: `A=heatmap`, `B=beamwidth`, `C=pareto`, `D=e_cov`
  - `stabilization`: `A=heatmap`, `B=di_proxy`, `C=s_theta`, `D=e_sym_shape`
  - `final`: `A=heatmap`, `B=r_off`, `C=e_sym_shape`, `D=s_theta`
- Hard bottom-right rule satisfied:
  - stabilization `D -> e_sym_shape`
  - final `D -> s_theta`
- Legend/series labels:
  - Compare overlay candidate labels are version-only (`V001`, `V002`, `V003`).
- Target-window visibility:
  - Heatmap overlays retained `target_half_window_deg=30.0` in all tested stages.
- Resize/readability:
  - No panel count collapse or plot-tile disappearance at `1920x1080` and `1366x768`.
- Plane propagation:
  - Display-plane toggles trigger compare redraw path and update active compare plane state.

## Notes
- Validation used headless Qt rendering; no pipeline, DB schema, importer, KPI math, runner, or VACS export logic changes were involved.
