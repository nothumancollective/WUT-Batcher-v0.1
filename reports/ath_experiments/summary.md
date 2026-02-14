# ATH Project Page Experiment Summary

- Cases requested: 200
- Seed: 2402
- OK: 175
- ATH errors: 17
- Pipeline errors: 0
- Skipped: 8

## Top ATH Error Patterns
- hard_cap_exceeded: 14 (examples: ath_exp_2402_0003_3f0a9ec4b7, ath_exp_2402_0004_731be0c163, ath_exp_2402_0005_5f4372a8e1, ath_exp_2402_0015_22d549612b, ath_exp_2402_0022_ec45d6ccb7)
- diameter_over_100m: 3 (examples: ath_exp_2402_0118_fc2ad32bed, ath_exp_2402_0159_ed71bb7816, ath_exp_2402_0165_d5ea6cdd4f)

## Dimension Threshold Hits
- max_dim_warn_hits: 59
- hard_cap_hits: 14

## Mode Error Rates
- gcurve:
  - no_gcurve: total=71, ath_error_rate=0.028, non_ok_rate=0.085
  - superellipse: total=73, ath_error_rate=0.068, non_ok_rate=0.096
  - superformula: total=56, ath_error_rate=0.179, non_ok_rate=0.214
- throat_profile:
  - Circular Arc: total=70, ath_error_rate=0.000, non_ok_rate=0.014
  - OS-SE: total=68, ath_error_rate=0.235, non_ok_rate=0.279
  - R-OSSE: total=62, ath_error_rate=0.016, non_ok_rate=0.081
- morph:
  - morph_off: total=87, ath_error_rate=0.069, non_ok_rate=0.069
  - morph_on: total=113, ath_error_rate=0.097, non_ok_rate=0.168
- enclosure:
  - enclosure_off: total=185, ath_error_rate=0.076, non_ok_rate=0.114
  - enclosure_on: total=15, ath_error_rate=0.200, non_ok_rate=0.267

## Dimension Distribution
- final_length_mm: p50=546.62, p90=899.018, p99=1582.446400000001, min=56.43, max=2556.29
- final_width_mm: p50=1176.24, p90=3698.6420000000026, p99=13567.903200000044, min=0.0, max=58247.97
- final_height_mm: p50=1089.07, p90=3928.7120000000004, p99=18892.778800000036, min=0.0, max=110982.23

## Error Classes (Mode View)
- hard_cap_exceeded: count=14
  - gcurve: no_gcurve=2, superellipse=5, superformula=7
  - throat_profile: OS-SE=13, R-OSSE=1
  - morph: morph_off=5, morph_on=9
  - enclosure: enclosure_off=11, enclosure_on=3
- diameter_over_100m: count=3
  - gcurve: superformula=3
  - throat_profile: OS-SE=3
  - morph: morph_off=1, morph_on=2
  - enclosure: enclosure_off=3

## Anti-Spurious Guidance
- Interpret correlations as risk indicators, not direct causality.
- Prioritize stable effects across modes/seeds and threshold behaviors.
- Validate top candidates with controlled counterfactual mini-runs.
