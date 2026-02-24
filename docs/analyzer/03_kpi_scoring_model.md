# KPI Scoring and Ranking Model

Last updated: 2026-02-24

## Scope

- Ranking is based on cached per-run KPI scalars from polar magnitude data.
- Hard filters are applied before sorting (flags and warning filters).
- Soft score (`0..100`) is stage-weighted and deterministic.

## Cache and identity

- Storage table: `analyzer_run_kpis`.
- A cache row is identified by:
  - `project_id`, `batch_id`, `run_id`, `version_id`
  - compute config (`band_low_hz`, `band_high_hz`, `target_h_deg`, `target_v_deg`, `tol_deg`)
  - `algo_version`
  - `source_hash`

## Stage presets (3-stage model)

### Concept

- Focus: pattern control and broad beam shaping quality.
- Default visible columns: `score`, `B_PC`, `E_BW`, `E_cov`, `R_spill`, `flags`.
- Default filters:
  - `exclude_flagged = false`
  - `exclude_warnings = false`
- Weights:
  - `B_PC = 0.30`
  - `E_BW = 0.30`
  - `E_cov = 0.18`
  - `R_spill = 0.14`
  - `flags = 0.08`

### Stabilization

- Focus: directivity stability, smoothness, and inter-plane consistency.
- Default visible columns: `score`, `DI_proxy`, `S_theta`, `E_sym_shape`, `flags`.
- Default filters:
  - `exclude_flagged = true`
  - `exclude_warnings = true`
- Weights:
  - `DI_proxy = 0.34`
  - `S_theta = 0.30`
  - `E_sym_shape = 0.24`
  - `flags = 0.12`

### Final

- Focus: off-axis ripple finishing quality plus smoothness/consistency guardrails.
- Default visible columns: `score`, `R_off`, `S_theta`, `E_sym_shape`, `flags`.
- Default filters:
  - `exclude_flagged = true`
  - `exclude_warnings = true`
- Weights:
  - `R_off = 0.38`
  - `S_theta = 0.28`
  - `E_sym_shape = 0.22`
  - `flags = 0.12`

## Version Information KPI rows (stage-aware UI mapping)

- The Analyzer Version Information KPI block is stage-mapped in the UI:
  - `concept`: `Score`, `Pattern Ctrl`, `BW Error`, `Cov Error`, `Spill`, `Flags`
  - `stabilization`: `Score`, `DI Proxy`, `Smoothness`, `Plane Consistency`, `Flags`
  - `final`: `Score`, `Off-axis Ripple`, `Smoothness`, `Plane Consistency`, `Flags`
- Stage-specific UI values are sourced from cached KPI aggregate fields.
- Missing values render as `--` with a `Compute KPIs` hint (no empty KPI block).

## Score normalization

- Higher-better metrics:
  - `B_PC`: normalized with soft cap around `3 octaves`.
  - `DI_proxy`: normalized with soft cap around `6 dB`.
- Lower-better metrics:
  - `E_BW`: `0 deg -> 1.0`, `20 deg -> 0.0`.
  - `E_cov`: `0 dB -> 1.0`, `6 dB -> 0.0`.
  - `R_spill`: mapped via ratio in dB-like space.
  - `S_theta`: lower angular-gradient RMS is better.
  - `E_sym_shape`: lower inter-plane spread is better.
  - `R_off`: lower off-axis ripple spread is better.
- Flags component:
  - no flags -> full score
  - flagged rows receive penalty by flag count
- Coverage guardrail:
  - `insufficient_coverage` applies an additional penalty multiplier.

## Stage plot mapping (Explorer/Compare defaults)

### Explorer 2x2 by stage

- `concept`:
  - A `Polar Map`
  - B `E_BW(f)`
  - C `E_cov(f)`
  - D `R_spill(f)`
- `stabilization`:
  - A `Polar Map`
  - B `DI_proxy(f)`
  - C `S_theta(f)`
  - D `E_sym_shape(f)`
- `final`:
  - A `Polar Map`
  - B `R_off(f)`
  - C `S_theta(f)`
  - D `E_sym_shape(f)`

### Compare overlay default per stage

- `concept`: `beamwidth`
- `stabilization`: `di_proxy`
- `final`: `r_off`

### Pareto defaults per stage

- `concept`: `E_BW` vs `R_spill`
- `stabilization`: `DI_proxy` vs `S_theta`
- `final`: `R_off` vs `S_theta`

## Polar-only policy

- Final-stage defaults are polar-only.
- No impedance, phase, or group-delay stage slots are part of stage defaults.
