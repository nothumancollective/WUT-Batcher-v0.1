# KPI Foundations for MT/HT Horn Analyzer

Last updated: 2026-02-24
Canonical research (verbatim): `01_kpi_research_raw.md`

This document is a structured implementation companion to the raw research.
If anything conflicts, `01_kpi_research_raw.md` is authoritative.

## Structured index

### A) Development stages
- Stage-dependent KPI priorities support faster iteration.
- Active stage model in Analyzer:
  - `Concept`
  - `Stabilization`
  - `Final`

### B) KPI taxonomy (polar-first)
- Polar-derived KPI families:
  - beamwidth/directivity behavior vs frequency
  - coverage and spill behavior
  - angular smoothness
  - cross-plane consistency
  - off-axis ripple behavior

### C) Computation requirements
- Inputs:
  - complex polar matrix (`freq x angle`) per plane
  - known frequency and angle bins
- Outputs:
  - per-run KPI payload
  - compare-ready shortlist metrics

### D) UI implications
- Analyzer must support:
  - fast candidate filtering
  - deterministic shortlist ranking
  - KPI-to-plot diagnostics by stage

### E) Beyond polars (future)
- Additional graph types are future work.
- Current stage defaults are polar-only.

## Implementation checklist

### 1) Stage definitions and KPI sets
- [x] Define 3-stage model: Concept/Stabilization/Final.
- [x] Remove Shaping from active stage options.

### 2) MVP KPI set
- [x] `E_BW`, `B_PC`, `E_cov`, `R_spill`, `flags`
- [x] robust with one-sided and limited-angle exports

### 3) Stage-2/3 diagnostics
- [x] `DI_proxy`, `S_theta`, `E_sym_shape`
- [x] `R_off` for final-stage off-axis control
- [ ] additional non-polar metrics remain future work

### 4) UI workflows
- [x] shortlist candidates per batch
- [x] compare selected versions
- [x] surface reason codes with severity

### 5) Data and caching
- [x] cache KPI payloads in `analyzer_run_kpis`
- [x] keep heavy reads in worker flows

## Phase 2A baseline (implemented)

### Data domain
- Input: `polar_measurements` + `polar_points`
- KPI and stage curves use polar magnitude data.

### Normalization policy
- Per frequency row and orientation:
  - reference uses nearest available `0 deg` (or resolved norm-angle fallback path).

### Implemented KPI set
- `E_BW`: beamwidth error vs target
- `B_PC`: contiguous pass-band in octaves
- `E_cov`: in-window coverage RMS
- `R_spill`: outside/inside energy proxy
- `DI_proxy`: local-vs-wide level proxy
- `S_theta`: angular smoothness proxy
- `E_sym_shape`: inter-plane spread
- `R_off`: off-axis ripple spread
- Flags/reason codes: data adequacy and stability guardrails

### Aggregate strategy
- Per-plane KPI compute first (`H`, `V`, optional `D`).
- Aggregate uses default plane weighting (`H=0.45`, `V=0.45`, `D=0.10`, renormalized by present planes).

### Coverage handling
- Limited or insufficient angle coverage is explicitly marked and penalized.

## Stage-curve definitions (active)

### Concept
- `BW(f)` from `-6 dB` contour
- `E_BW(f)`
- `E_cov(f)`
- `R_spill(f)`

### Stabilization
- `DI_proxy(f)`
- `S_theta(f)`
- `E_sym_shape(f)`

### Final (polar-only)
- `R_off(f)`
- `S_theta(f)`
- `E_sym_shape(f)`
- No impedance/phase/GD stage slots.
