# KPI Foundations for MT/HT Horn Analyzer

**Last updated:** 2026-02-21  
**Canonical research (verbatim):** `01_kpi_research_raw.md` (SHA256 `e26cb5d9f9ad`)

This document **does not replace** the research; it provides a **structured index + extraction scaffold**
so implementation can reference concepts deterministically while avoiding accidental omissions.

## How to use this doc

- If you need the full wording, refer to **01_kpi_research_raw.md**.
- If you are implementing: start from **“Implementation checklist”** below, then validate against the raw source.
- If anything in this doc conflicts with the raw research, the **raw research wins**.

---

## Structured index

> Note: headings below are a *navigation aid*. The detailed content lives in the raw research.

### A) Development process / stages (when KPIs matter)
- Identify which KPIs are appropriate at which stage of horn development.
- Goal: avoid optimizing late-stage metrics too early and enable fast iteration.

### B) KPI taxonomy (polar-first)
- KPI candidates derived from polar data (H/V/D):
  - Directivity / beamwidth behavior vs frequency
  - Smoothness / stability measures across angle and frequency
  - Symmetry across planes
  - Detection of collapse / sudden narrowing / pattern instability
- KPI outputs must support:
  - filtering (hard constraints)
  - ranking (soft scoring)
  - compare workflows (multi-run overlays)

### C) Computation requirements
- Inputs:
  - Complex polar matrix (freq × angle) per plane
  - Known angle bins and frequency bins (variable)
- Outputs:
  - per-run metrics
  - per-batch distributions / candidate selection

### D) UI implications from research
- Analyzer should support:
  - “find candidates” quickly
  - “compare” across runs
  - “diagnose” by linking KPI → plot view
  - stage-based KPI sets (early vs late)

### E) Beyond polars (future graph types)
- Research discusses when to add other VACS graph types (e.g., SPL, radiation impedance, etc.)
- This should be treated as “Phase 2+” expansion once polar-based loop is solid.

---

## Implementation checklist (derived from research needs)

Use this as an engineering checklist; validate each item against the raw research.

### 1) Define stages and KPI sets per stage
- [ ] Stage definitions for MT/HT horn iteration (early → late)
- [ ] For each stage:
  - [ ] primary objectives
  - [ ] KPIs to prioritize
  - [ ] KPIs to deprioritize (avoid premature optimization)

### 2) Define MVP KPI set (small, ranking-stable)
- [ ] Select a minimal set that is:
  - [ ] computable from polars alone
  - [ ] robust across batch sizes
  - [ ] meaningful for MT/HT horns
- [ ] Define for each KPI:
  - [ ] mathematical definition
  - [ ] computation from freq×angle
  - [ ] failure modes / sensitivity

### 3) Define Phase 2 KPI set (diagnostic depth)
- [ ] Add deeper metrics (plane symmetry, DI stability, phase-derived metrics if needed)
- [ ] Gate them behind “advanced” toggles and caching.

### 4) Define UI workflows that match iteration
- [ ] Shortlist candidates from a batch
- [ ] Compare selected runs
- [ ] Inspect failures (KPI flags link to plot context)
- [ ] Export candidate lists / reports for next iteration

### 5) Data requirements / caching plan
- [ ] Decide which KPIs are:
  - [ ] precomputed (stored in DB cache tables)
  - [ ] on-demand (computed for selected runs only)
- [ ] Ensure responsiveness with worker threads and bounded caches.

---

## Appendix: canonical research

The full research is included verbatim in:

- `01_kpi_research_raw.md` (SHA256 `e26cb5d9f9ad`)

---

## Phase 2A implementation baseline (MVP, now implemented)

### Data domain (MVP)

- Input source:
  - `polar_measurements` + `polar_points`
  - magnitude-only (`re`, `im` -> `|H|` in dB)
- No phase/group-delay KPI in MVP.

### Normalization policy

- Per frequency row and orientation:
  - reference = on-axis (`theta ~= 0 deg`, nearest available angle)
  - all angles are normalized to that reference in dB
- This is intentionally simple and robust for MVP.
- Future enhancement (not in MVP): power-normalized/iterative references.

### Implemented MVP KPIs

- `E_BW`:
  - beamwidth error vs target over selected band
  - beamwidth extracted from `-6 dB` contour around on-axis
- `B_PC`:
  - contiguous pass bandwidth where `|beamwidth - target| <= tol`
  - stored as octave span + pass-band edge frequencies
- `E_cov`:
  - RMS variation inside coverage region (`|theta| <= target/2`)
- `R_spill`:
  - outside-vs-inside energy ratio proxy (lower is better)
- Flags:
  - jump / collapse / wide transitions from beamwidth curve
  - used both as filter and score penalty

### Aggregate strategy

- Per-plane KPI compute first (`H`, `V`, optional `D`).
- Aggregate uses fixed plane weighting:
  - `H=0.45`, `V=0.45`, `D=0.10` (renormalized by present planes).

### Insufficient-coverage handling

- If angular coverage is too narrow for target region, KPI payload is marked `insufficient_coverage`.
- Such rows are scored as `0` in stage scoring and remain filterable in UI.

## Stage-curve definitions (Analyzer Stage Plot System)

The stage plot system adds frequency curves for Explorer/Compare visualization. These are computed from polar magnitude data only.

### Shared baseline

- Build `L(f,theta)` in dB from `polar_points`.
- Frequency axis is sorted ascending and displayed logarithmically.
- Reference policy remains nearest-to-`0 deg` normalization.
- Optional normalization-angle selector (`0 deg`/`10 deg`) is currently disabled in UI when unsupported by pipeline behavior.

### Stage 1 (Concept/Shaping)

- `BW(f)` from `-6 dB` contour around on-axis.
- `E_BW(f)` = `|BW(f) - BW_target|`.
- `E_cov(f)` = RMS variation inside target coverage window (`|theta| <= BW_target / 2`).
- `R_spill(f)` = outside-vs-inside energy ratio proxy.
- Heatmap overlays include:
  - `-6 dB` contour
  - target-window shading (`+-BW_target/2`).

### Stage 2 (Stabilization)

- `DI_proxy(f)` = local-window mean level minus all-angle mean level.
- `S_theta(f)` = RMS of angular gradient `dL/dtheta`.
  - default window: target coverage
  - optional advanced toggle uses full angles.
- `E_sym_shape(f)` = inter-plane consistency spread (beamwidth-based, with DI fallback).

### Stage 3 (Final/Resonance)

- `R_off(f)` = off-axis ripple spread using available off-axis angles (prefers `+-30`, `+-45`, `+-60`).
- `Impedance/Loading` and `Group Delay/Phase` plots are conditional:
  - shown only when corresponding artifacts are available
  - otherwise UI shows explicit “missing data” guidance.
