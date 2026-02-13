# ATH Project Page Experiment Summary

- Cases requested: 0
- Seed: 2026
- OK: 13748
- ATH errors: 1790
- Pipeline errors: 0
- Skipped: 52

## Top ATH Error Patterns
- hard_cap_exceeded: 1513 (examples: ath_exp_1337_0005_ed3639ff54, ath_exp_1337_0015_8ad44576ef, ath_exp_1337_0005_5576d3f3a8, ath_exp_1337_0015_6cd37bcea5, ath_exp_1337_0005_23fff8b3a5)
- diameter_over_100m: 262 (examples: ath_exp_1337_0025_bd94261911, ath_exp_1337_0049_3076cdc7d0, ath_exp_1337_0082_3e0ba2303f, ath_exp_1337_0094_b8bab71b6e, ath_exp_1337_0188_700b0dd5f8)
- ath_nonzero_exit: 11 (examples: ath_exp_2026_0628_d9b91e3099, ath_exp_2026_2311_93cda55d91, ath_exp_2026_2321_b547ad7e19, ath_exp_2026_3652_bbacc0427f, ath_exp_2026_4910_703b9065df)
- numeric_overflow: 4 (examples: ath_exp_2026_2913_9757248023, ath_exp_2026_4056_a6c06def2b, ath_exp_2027_0150_bde64f72ab, ath_exp_2029_1252_940a2e6e84)

## Dimension Threshold Hits
- max_dim_warn_hits: 3839
- hard_cap_hits: 1513

## Mode Error Rates
- gcurve:
  - no_gcurve: total=5456, ath_error_rate=0.106, non_ok_rate=0.109
  - superellipse: total=5554, ath_error_rate=0.071, non_ok_rate=0.075
  - superformula: total=4580, ath_error_rate=0.178, non_ok_rate=0.182
- throat_profile:
  - Circular Arc: total=5315, ath_error_rate=0.000, non_ok_rate=0.005
  - OS-SE: total=5169, ath_error_rate=0.320, non_ok_rate=0.324
  - R-OSSE: total=5106, ath_error_rate=0.027, non_ok_rate=0.028
- morph:
  - morph_off: total=6946, ath_error_rate=0.093, non_ok_rate=0.097
  - morph_on: total=8644, ath_error_rate=0.132, non_ok_rate=0.135
- enclosure:
  - enclosure_off: total=15590, ath_error_rate=0.115, non_ok_rate=0.118

## Dimension Distribution
- final_length_mm: p50=673.28, p90=1110.88, p99=3959.9539999999943, min=0.0, max=8745.72
- final_width_mm: p50=786.1, p90=4400.98, p99=58956.31999999994, min=0.0, max=108915876.27
- final_height_mm: p50=784.48, p90=4448.12, p99=60760.3559999998, min=0.0, max=96469064.67

## Error Classes (Mode View)
- hard_cap_exceeded: count=1513
  - gcurve: no_gcurve=561, superellipse=387, superformula=565
  - throat_profile: OS-SE=1392, R-OSSE=121
  - morph: morph_off=532, morph_on=981
  - enclosure: enclosure_off=1513
- diameter_over_100m: count=262
  - gcurve: no_gcurve=12, superellipse=4, superformula=246
  - throat_profile: OS-SE=262
  - morph: morph_off=117, morph_on=145
  - enclosure: enclosure_off=262
- ath_nonzero_exit: count=11
  - gcurve: no_gcurve=4, superellipse=4, superformula=3
  - throat_profile: R-OSSE=11
  - morph: morph_on=11
  - enclosure: enclosure_off=11
- numeric_overflow: count=4
  - gcurve: no_gcurve=1, superellipse=2, superformula=1
  - throat_profile: R-OSSE=4
  - morph: morph_on=4
  - enclosure: enclosure_off=4

## Anti-Spurious Guidance
- Interpret correlations as risk indicators, not direct causality.
- Prioritize stable effects across modes/seeds and threshold behaviors.
- Validate top candidates with controlled counterfactual mini-runs.
