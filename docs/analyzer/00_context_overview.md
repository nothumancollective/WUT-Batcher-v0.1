# WUT Batcher — Analyzer Documentation Context

**Last updated:** 2026-02-21

This folder contains the **persistent design context** for the *Analyzer* feature (MT/HT horn focus).
It is intended to be attached to Codex tasks so implementation stays aligned with requirements.

> Raw research is canonical; do not edit; add structured notes in foundations doc.

## Product focus

- Domain: **midrange and high-frequency horns / waveguides (MT/HT)**.
- Workflow: batch-based parametric exploration → simulation → export → ingestion → analysis → iteration.
- Data source: **VACS exports** (currently: polar data; later: additional graph types).

## Current implementation state (foundation)

Implemented in the repo (already working end-to-end):

- **VACS export enforcement** is *verify-only + fail-fast* (checkboxes are not settable in this VACS environment).
- **Polar TXT ingestion** supports:
  - Complex format
  - Format A: frequency included per Data row
  - Format B: Abscissa block + Data matrix
- Storage:
  - per-project `project.sqlite` and consolidated `global.sqlite`
  - `polar_measurements` + `polar_points` store full matrices (H/V/D)

## UI direction (high-level decisions)

- Keep **Project Manager** as a persistent “launcher” window.
- Use a **bottom mode bar** (DaVinci-like) for the main app:
  - Project | Batch | Analyse (later: Merge)
- Global always-visible actions:
  - 🏠 Project Manager
  - ⚙ Settings / Preferences
- Page-local actions remain inside the relevant page (e.g., Save/Run within Batch).

> Detailed UI/navigation requirements and responsiveness rules are in: **02_ui_architecture.md**.

## KPI research source of truth

The KPI research document is included **verbatim** (for auditability) and also structured into an implementation-friendly index.

- Structured: **01_kpi_foundations.md**
- Verbatim source: **01_kpi_research_raw.md** (checksum `e26cb5d9f9ad`)

## Change process (important)

When requirements change:
1. Update the relevant doc(s) in this folder.
2. Append a short entry to **CHANGELOG.md** describing what changed and why.
3. When implementing, reference the doc section(s) you are implementing.
