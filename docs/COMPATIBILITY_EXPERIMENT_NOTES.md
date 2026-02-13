# Compatibility Experiment Notes

This document captures how `projectpage-ath-experiment` findings should feed the compatibility layer.

## Scope

- Data source: `reports/ath_experiments/ath_experiments.sqlite`
- Reports:
  - `reports/ath_experiments/summary.json`
  - `reports/ath_experiments/summary.md`
  - `reports/ath_experiments/range_suggestions.v1.json`
- Pipeline requirement: all runs are generated through the same PROJECT-page path used by UI
  (`ParameterForm -> CompatibilityService -> resolve_versions -> render_cfg_text -> ATH`).

## Rule Policy

- Do not auto-promote ranges to fatal constraints unless the ATH fatal is reproducible and stable.
- Prefer experiment-backed warnings:
  - `warn_large_dimensions`: observed final width/height/length above configured soft threshold.
  - `warn_throat_angle_outlier`: observed average throat angle outside success-heavy interval.
- Keep evidence metadata explicit:
  - `evidence.type = "experiment"`
  - include sample `run_id`s
  - include counts and observed value spans

## Operational Notes

- Cleanup mode may delete generated CFG/export folders, but never removes the experiment DB/reports.
- Use `range_suggestions.v1.json` as an initial candidate set, then validate manually before any UI rule hardening.
