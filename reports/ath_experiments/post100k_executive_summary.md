# Post-100k Executive Summary

- Generated: 2026-02-14T15:30:20.672043+00:00

## 1) Outcome and Trend
- legacy_5k: total=5000 ok=4408 ath_error=586 pipeline_error=0 skipped=6 (ok_rate=0.882, ath_error_rate=0.117).
- pp10k_multi_seed: total=10000 ok=8857 ath_error=1119 pipeline_error=0 skipped=24 (ok_rate=0.886, ath_error_rate=0.112).
- pp100k_multi_seed: total=100000 ok=78903 ath_error=18289 pipeline_error=0 skipped=2808 (ok_rate=0.789, ath_error_rate=0.183).

## 2) Dominant Error Patterns (100k)
- hard_cap_exceeded: 8677
- unknown: 8050
- diameter_over_100m: 1539
- ath_nonzero_exit: 20
- numeric_overflow: 3
- `unknown` in this run is mostly compare/config mismatch with ATH exit code 0, not ATH runtime crash.

### Context per Error Class
- hard_cap_exceeded: OS-SE + Superformula + no morph + enclosure_off (1756); OS-SE + Superformula + rectangle + enclosure_off (1514); OS-SE + Superellipse + rectangle + enclosure_off (912)
- diameter_over_100m: OS-SE + Superformula + no morph + enclosure_off (591); OS-SE + Superformula + rectangle + enclosure_off (486); OS-SE + Superformula + circle + enclosure_off (337)
- unknown: Circular Arc + Superformula + rectangle + enclosure_off (425); R-OSSE + Superformula + no morph + enclosure_off (411); R-OSSE + Superformula + rectangle + enclosure_off (397)

## 3) Metrics and Thresholds
- final_width_mm: p50=1203.74 p90=4102.69 p99=57958.80 max=2807184607525.91
- final_height_mm: p50=1219.43 p90=4292.26 p99=63151.26 max=3119553468808.71
- final_length_mm: p50=542.61 p90=979.78 p99=2523.40 max=105785024.13
- avg_throat_angle_deg: p50=10.65 p90=22.09 p99=48.63 max=72.93
- final_width_mm: >1000mm=55020 (0.575), >2000mm=27172 (0.284), >5000mm=7242 (0.076).
- final_height_mm: >1000mm=55359 (0.579), >2000mm=28048 (0.293), >5000mm=7812 (0.082).
- final_length_mm: >1000mm=8301 (0.087), >2000mm=1888 (0.020), >5000mm=65 (0.001).

### Threshold-based Risk Signals (not causal claims)
- GCurve=Superformula + Throat=OS-SE: matched=10447 hard_cap_rate=0.424 (uplift +0.337), diameter_over_100m_rate=0.147 (uplift +0.131).
- Coverage.Angle>70 with OS-SE: matched=490 hard_cap_rate=0.724 (uplift +0.638), diameter_over_100m_rate=0.012 (uplift -0.003).
- Length>1000 mm: matched=2719 hard_cap_rate=0.139 (uplift +0.053), diameter_over_100m_rate=0.016 (uplift +0.000).
- GCurve.Width>900 mm: matched=3258 hard_cap_rate=0.186 (uplift +0.099), diameter_over_100m_rate=0.029 (uplift +0.014).
- observed max dimension > 2000 mm: matched=30350 hard_cap_rate=0.286 (uplift +0.199), diameter_over_100m_rate=0.000 (uplift -0.015).

## 4) New and Surprising Coverage
- Keys with 0% pre-100k and >0 in 100k: 18
- Mesh.MouthResolution: 100000 set in pp100k
- Mesh.RearResolution: 100000 set in pp100k
- Mesh.ThroatResolution: 100000 set in pp100k
- Mesh.WallThickness: 100000 set in pp100k
- Throat.Ext.Angle: 12120 set in pp100k
- Throat.Ext.Length: 12120 set in pp100k
- Slot.Length: 9065 set in pp100k
- Mesh.Enclosure: 6893 set in pp100k
- Mesh.RearShape: 6893 set in pp100k
- Morph.AllowShrinkage: 3000 set in pp100k
- Morph.FixedPart: 3000 set in pp100k
- Morph.Rate: 3000 set in pp100k
- Enclosure_on combinations covered: 27 (total samples=6893).
- OS-SE + Superformula + rectangle + enclosure_on: n=368 ok_rate=0.318 ath_error_rate=0.620
- OS-SE + Superellipse + no morph + enclosure_on: n=367 ok_rate=0.864 ath_error_rate=0.136
- R-OSSE + Superellipse + rectangle + enclosure_on: n=358 ok_rate=0.768 ath_error_rate=0.204
- OS-SE + No GCurve + rectangle + enclosure_on: n=355 ok_rate=0.673 ath_error_rate=0.276
- Circular Arc + No GCurve + rectangle + enclosure_on: n=354 ok_rate=0.879 ath_error_rate=0.076
- OS-SE + Superellipse + rectangle + enclosure_on: n=354 ok_rate=0.661 ath_error_rate=0.291
