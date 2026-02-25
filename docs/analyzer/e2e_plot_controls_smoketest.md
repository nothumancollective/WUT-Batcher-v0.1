# Analyzer Plot Controls Smoke Test (2026-02-24)

## Scope
- Validate the new Analyzer plot/control UX changes on real local project data.
- Focus: Auto Scale toggle, Metric Bands default/toggle, full-angle smoothness safety, Explorer Concept tile replacement, and black-slab background policy.

## Environment
- Branch: `feature/polar-analyzer-ui`
- Qt mode: offscreen smoke automation
- Settings path: `C:\Users\maximilianheinze\.wut_batcher\config.json`
- Library root from settings: `cleanup/runtime/postmerge_lib`
- Selected real project for smoke: `P001`
- Selected analyzer batch for smoke: `B005`

## Steps + Evidence
1. Open Analyzer with real project context (`P001`) and refresh metadata.
   - `OVERVIEW_READY=True`, `batch_count=2`
   - `RUNS_READY=True`, `run_rows=1`
2. Explorer Concept rendering check after first run selection.
   - `EXPLORER_PLOT_READY=True`
   - Concept slot D kind/key:
     - `EXPLORER_CONCEPT_SLOT_D_KIND=summary`
     - `EXPLORER_CONCEPT_SLOT_D_KEY=target_deviation_summary`
   - Summary rows rendered: `EXPLORER_TARGET_SUMMARY_ROWS=4`
3. Compare rendering check with shortlist.
   - `COMPARE_PLOT_READY=True`, `items=1`
4. Full-angle smoothness safety check in Compare Concept.
   - Force full-angle smoothness ON and re-render compare plot: `COMPARE_PLOT_READY_FULL_ANGLES=True`
   - Pareto remains stable (no crash); non-ready KPI state handled gracefully:
     - `COMPARE_PARETO_POINTS=0`
     - `COMPARE_PARETO_STATUS="Compute KPIs to populate."`
5. Metric band behavior.
   - Default ON verified: `METRIC_BANDS_DEFAULT=True`
   - Style profile follows toggle:
     - ON: `METRIC_BAND_PROFILE_ON=True`
     - OFF: `METRIC_BAND_PROFILE_OFF=False`
6. Auto Scale behavior.
   - Default OFF verified: `AUTO_SCALE_DEFAULT=False`
   - Stable cached range while OFF (same key, new values stay in prior range):
     - `(-0.12, 2.12)` -> `(-0.12, 2.12)`
   - Per-selection auto range after ON:
     - `(9.94, 11.06)`
7. Background policy / black-slab check.
   - Plot tile frame property active: `PLOT_TILE_PROPERTY=True`
   - Canvas corner alpha remains transparent: `CANVAS_CORNER_ALPHA=0 0`

## Acceptance Verdict
- A) Auto Scale control present and functional: PASS
- B) Metric Band default ON with working toggle: PASS
- C) Full-angles smoothness does not break Compare Concept Pareto rendering path: PASS
- D) Explorer Concept uses single-candidate Target Deviation Summary tile: PASS
- E) Plot tiles use panel-consistent surface policy without opaque black slab artifacts: PASS

## Notes
- Selected real batch (`B005`) had one Analyzer run row in this environment; compare overlays therefore used a single candidate during this smoke run.
- No Runner/VACS/export/import/schema/KPI-math changes were required for this UX/control implementation.
