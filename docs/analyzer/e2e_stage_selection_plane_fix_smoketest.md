# Analyzer E2E Smoke Test - Stage/Selection/Plane Fixes

Date: 2026-02-24  
Branch: `feature/polar-analyzer-ui`  
Mode: headless GUI smoke (`QT_QPA_PLATFORM=offscreen`) with real project data

## Scope

Validate end-to-end Analyzer user flow after fixes:

1. Explorer selection/version context across Concept/Stabilization/Final.
2. Stage-specific Version Information KPI labels/values.
3. `Refresh KPIs` action in all stages.
4. Compare manual add + auto-pick.
5. Compare H/V/D plane propagation from Display controls.
6. Missing-plane graceful behavior in Compare.

## Dataset and Context

- Project: `P021`
- Primary batch: `B011` (H/V/D data present)
- Missing-plane batch (for graceful handling check): `B005`

## Executed Flow and Results

## 1) Open project and seed Explorer

- Action: open project context `P021`, load `B011` rows.
- Result: `2` rows loaded; selected version `V038`.

## 2) Explorer stage switching + version info + refresh KPIs

For each stage, row selection remained valid and Version Information was populated:

- `concept`
  - rows: `2`
  - selected: `V038`
  - KPI rows: `Score`, `Pattern Ctrl`, `BW Error`, `Cov Error`, `Spill`, `Flags`
  - `Refresh KPIs`: compute thread completed, metadata refresh completed, no error.
- `stabilization`
  - rows: `2`
  - selected: `V038`
  - KPI rows: `Score`, `DI Proxy`, `Smoothness`, `Plane Consistency`, `Flags`
  - `Refresh KPIs`: compute thread completed, metadata refresh completed, no error.
- `final`
  - rows: `2`
  - selected: `V038`
  - KPI rows: `Score`, `Off-axis Ripple`, `Smoothness`, `Plane Consistency`, `Flags`
  - `Refresh KPIs`: compute thread completed, metadata refresh completed, no error.

## 3) Compare manual + auto-pick

- Manual add from selection:
  - shortlist slot `C1`: `B011/V038`.
- Auto-pick (top 2 within `B011`):
  - shortlist populated: `B011/V037`, `B011/V038`.

## 4) Compare plane propagation (Display H/V/D -> Compare)

Display plane button changes propagated to Compare plane state and completed compare plotting:

- `H`: active=`H`, compare=`H`, compare plot done.
- `V`: active=`V`, compare=`V`, compare plot done.
- `D`: active=`D`, compare=`D`, compare plot done.

## 5) Missing-plane graceful handling in Compare

- Compare set mixed with `B005/V014` (missing H) and `B011/V038` (has H).
- With compare plane `H`:
  - compare plot completed,
  - overlay status explicitly reported missing plane:
    - `Missing H: C1 B005/V014.`

## Conclusion

Acceptance criteria for stage selection, stage-aware Version Information KPIs, and compare plane propagation are satisfied in this smoke run.  
No Runner/export/project-batch compatibility code paths were modified by this fix series.
