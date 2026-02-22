# KPI Scoring & Ranking Model

**Last updated:** 2026-02-22

## Scope (MVP / Phase 2A)

- Ranking is based on cached per-run KPI scalars from polar magnitude data.
- Hard filters are applied before sorting (flags/warnings/thresholds).
- Soft score (`0..100`) is stage-weighted and deterministic.

## Cache + identity

- Storage table: `analyzer_run_kpis` (project and global DB via replication queue).
- A cache row is uniquely identified by:
  - project/batch/run/version
  - compute config (`band_low_hz`, `band_high_hz`, `target_h_deg`, `target_v_deg`, `tol_deg`)
  - `algo_version`
  - `source_hash` (derived from polar file hashes for the run/version)
- Recompute trigger:
  - missing cache row
  - `algo_version` changed
  - `source_hash` changed

## Default presets (MVP)

### Coverage target presets

- `90x40` (default)
- `60x60`
- `60x40`
- `90x60`
- `80x40`
- `75x50`
- `60x30`
- `50x50`
- `40x40`

### Tolerance preset

- Beamwidth tolerance default: `+/- 5 deg`

### Frequency-band presets

- `Full (auto)`
- `200-16k Hz` (default scoring band, starts at 200 Hz)
- `200-500 Hz`
- `500-1k Hz`
- `1-2k Hz`
- `2-4k Hz`
- `4-8k Hz`
- `8-16k Hz`
- `Custom...`

## Stage presets (weights + defaults)

### Concept

- Emphasis: pattern-control + beamwidth + flag sanity.
- Default visible columns: `score`, `B_PC`, `E_BW`, `flags`.
- Default filters:
  - `exclude_flagged = false`
  - `exclude_warnings = false`
- Weights:
  - `B_PC = 0.42`
  - `E_BW = 0.36`
  - `E_cov = 0.08`
  - `R_spill = 0.06`
  - `flags = 0.08`

### Shaping

- Emphasis: balanced control + uniformity + spill.
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

- Emphasis: smooth coverage + spill suppression + robustness flags.
- Default visible columns: `score`, `E_cov`, `R_spill`, `flags`, `B_PC`, `E_BW`.
- Default filters:
  - `exclude_flagged = true`
  - `exclude_warnings = true`
- Weights:
  - `B_PC = 0.18`
  - `E_BW = 0.18`
  - `E_cov = 0.30`
  - `R_spill = 0.22`
  - `flags = 0.12`

## Score normalization (MVP implementation)

- `B_PC` component (higher better):
  - normalized with soft cap around `3 octaves`
- `E_BW` component (lower better):
  - linear mapping, `0 deg -> 1.0`, `20 deg -> 0.0`
- `E_cov` component (lower better):
  - linear mapping, `0 dB -> 1.0`, `6 dB -> 0.0`
- `R_spill` component (lower better):
  - computed as outside/inside energy ratio
  - mapped in dB-like space (`-15 dB` good, `+5 dB` poor)
- `flags` component:
  - no flags -> full component score
  - flagged rows receive penalty based on flag count

Final score:

- Weighted sum of normalized components
- Clamped to `0..100`
- If `insufficient_coverage=true`, score is forced to `0`
