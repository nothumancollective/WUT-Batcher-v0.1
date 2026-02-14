# Post-100k Gap Plan

- Generated: 2026-02-14T15:30:20.672043+00:00
- Method: focus on under-covered keys/modes and validate with controlled counterfactual mini-runs.

## Top 20 Gaps
| gap_type | item | current_count | current_ratio | target_next_run | strategy |
|---|---|---:|---:|---:|---|
| key | `Mesh.InterfaceOffset` | 0 | 0.0000 | 4000 | add valid generator path for InterfaceOffset coupled with SubdomainSlices + InterfaceDraw |
| key | `GCurve.SF` | 1500 | 0.0150 | 5000 | direct key quota with mode-aware validity guards |
| key | `Rot` | 2000 | 0.0200 | 5000 | direct key quota with mode-aware validity guards |
| key | `Mesh.InterfaceDraw` | 2500 | 0.0250 | 5500 | direct key quota with mode-aware validity guards |
| key | `Mesh.InterfaceResolution` | 2500 | 0.0250 | 5500 | direct key quota with mode-aware validity guards |
| key | `Mesh.SubdomainSlices` | 2500 | 0.0250 | 5500 | direct key quota with mode-aware validity guards |
| key | `Mesh.ZMapPoints` | 2500 | 0.0250 | 5500 | direct key quota with mode-aware validity guards |
| key | `Morph.AllowShrinkage` | 3000 | 0.0300 | 6000 | direct key quota with mode-aware validity guards |
| key | `Morph.FixedPart` | 3000 | 0.0300 | 6000 | direct key quota with mode-aware validity guards |
| key | `Morph.Rate` | 3000 | 0.0300 | 6000 | direct key quota with mode-aware validity guards |
| key | `Mesh.Enclosure` | 6893 | 0.0689 | 9893 | direct key quota with mode-aware validity guards |
| key | `Mesh.RearShape` | 6893 | 0.0689 | 9893 | direct key quota with mode-aware validity guards |
| mode_combo | `Circular Arc + Superformula + circle + enclosure_on` | 49 | 0.0005 | 300 | stratified bucket oversampling |
| mode_combo | `OS-SE + No GCurve + circle + enclosure_on` | 58 | 0.0006 | 308 | stratified bucket oversampling |
| mode_combo | `Circular Arc + No GCurve + circle + enclosure_on` | 61 | 0.0006 | 311 | stratified bucket oversampling |
| mode_combo | `R-OSSE + No GCurve + circle + enclosure_on` | 63 | 0.0006 | 313 | stratified bucket oversampling |
| mode_combo | `Circular Arc + Superellipse + circle + enclosure_on` | 66 | 0.0007 | 316 | stratified bucket oversampling |
| mode_combo | `OS-SE + Superellipse + circle + enclosure_on` | 68 | 0.0007 | 318 | stratified bucket oversampling |
| mode_combo | `OS-SE + Superformula + circle + enclosure_on` | 68 | 0.0007 | 318 | stratified bucket oversampling |
| mode_combo | `R-OSSE + Superformula + circle + enclosure_on` | 75 | 0.0008 | 325 | stratified bucket oversampling |

## Controlled Counterfactual Mini-Runs
1. `cf_superformula_width` (400): fix OS-SE + superformula; vary only `GCurve.Width` (50mm steps).
2. `cf_superformula_dist` (400): fix OS-SE + superformula; vary only `GCurve.Dist` (fraction+mm bands).
3. `cf_coverage_osse` (300): fix OS-SE baseline; vary only `Coverage.Angle` 20..90.
4. `cf_length_threshold` (300): fixed mode; vary only `Length` 200..1500.
5. `cf_enclosure_circle_sparse` (500): target rare enclosure_on + circle combos, vary one parameter at a time.

## Schema / Ingest Limits
- `Mesh.Enclosure` and `R-OSSE` are stored as object-level keys in `experiment_params`; subkeys are not persisted separately.
- Proposal: flatten subkeys (e.g. `Mesh.Enclosure.Depth`) at ingest while keeping parent object snapshot for traceability.
