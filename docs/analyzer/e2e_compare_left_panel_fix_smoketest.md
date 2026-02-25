# Compare Left-Panel Fix Smoke Test (2026-02-24)

## Scope
- Validate Compare workflow after left-panel KPI/table redesign.
- Confirm stage-dependent KPI columns, active-candidate wiring, and remove/save/load flows.
- Confirm responsive layout geometry at 1920x1080 and 1366x768 in offscreen GUI runtime.

## Environment
- Branch: `feature/polar-analyzer-ui`
- Runtime: PySide6 offscreen (`QT_QPA_PLATFORM=offscreen`)
- Service: temporary project library via `OrchestratorService`

## Steps Executed
1. Create temporary project and open `AnalysePage`.
2. Load synthetic run payload with mixed planes (`H/V`, `H/V/D`, `V/D`) and KPI values.
3. Switch to Compare tab.
4. Add candidate via `Add selected`.
5. Expand shortlist (`_set_compare_candidates`) and apply `Auto-pick` payload.
6. Switch stage across `concept -> stabilization -> final`.
7. Toggle display plane buttons (`H`, `V`, `D` when enabled).
8. Select slot row `C2` and verify active-candidate/heatmap sync.
9. Remove a candidate and verify shortlist remains stable.
10. Save and reload compare analysis entry.

## Results
- Workflow completed without exceptions.
- Active-candidate and heatmap selector stayed synchronized (`active_idx=1`, `heatmap_idx=1`).
- Final-stage Compare table headers reflected stage mapping:
  - `Off-axis Ripple (dB)`, `Smoothness`, `Plane Consistency`
- Compare shortlist retained fixed 5-row structure after add/remove/save/load cycle.

## Responsive Layout Probe
Measured widget widths after showing Compare tab in offscreen mode:

- `1920x1080`:
  - left panel viewport: `415 px`
  - right compare grid: `1437 px`
  - compare table viewport: `470 px`
- `1366x768`:
  - left panel viewport: `316 px`
  - right compare grid: `1095 px`
  - compare table viewport: `470 px`

Interpretation:
- Left panel remains readable and scroll-capable.
- Right plot grid gets the majority of horizontal space.
- No overlap/clipping exceptions occurred during resize and redraw.
