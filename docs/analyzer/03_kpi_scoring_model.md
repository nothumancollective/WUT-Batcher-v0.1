# KPI Scoring & Ranking Model (Planning Scaffold)

**Last updated:** 2026-02-21

This file is intentionally a **planning scaffold**. The detailed KPI definitions live in the research:
- `01_kpi_research_raw.md` (canonical)
- `01_kpi_foundations.md` (index)

Purpose:
- Provide a stable place to document the eventual scoring model once KPI selection is finalized.

## Principles

- Separate:
  - **hard filters** (exclude invalid candidates)
  - **soft scores** (rank remaining candidates)
- Metrics must be:
  - stable enough to rank across batches (avoid extremely noise-sensitive metrics early)
  - aligned with the MT/HT horn development stage

## Intended structure

### A) Per-run metrics
- Computed from polars (MVP)
- Stored with algorithm versioning (future table, e.g., run_metrics)

### B) Per-batch summaries
- Distributions, percentiles, outliers
- Used for selection workflows

### C) Stage-based weighting
- Early stage: shape/control KPIs
- Mid stage: stability/smoothness KPIs
- Late stage: fine-tuning KPIs (phase-related etc., if available)

## To be filled once KPI set is confirmed
- KPI list (MVP, Phase 2)
- Exact band definitions used for aggregation
- Normalization strategy (robust vs mean/std)
- Penalty/score mapping rules

