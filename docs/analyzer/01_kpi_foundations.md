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

