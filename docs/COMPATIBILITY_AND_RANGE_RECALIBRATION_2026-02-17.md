# Compatibility And Range Recalibration (2026-02-17)

## Scope
This note answers:
1. What changed in compatibility behavior after the recent preview/UI work?
2. What is now the role of `ath_experiments.sqlite`?
3. Can safe-range extraction be improved with the new findings and ATH guide constraints?

## 1) What Changed In Compatibility Logic

### Rule engine (ATH compatibility) status
- **No ATH rule semantics were changed** in this step.
- `app/compatibility_service.py` remains the normative rule-evaluation layer.

### What changed around it
- Preview/run orchestration now uses explicit two-tier completion (`ath_minimal` vs `policy_minimal`) in `app/services.py`.
- `policy_missing_by_block` was added to keep requirement logic explicit by block:
  - `profile`, `mesh`, `gcurve`, `morph`, `enclosure`
- Batch default-apply flow can now merge nested defaults for:
  - `R-OSSE.*`
  - `Mesh.Enclosure.*`

### Preview runtime stability fixes
- Preview `MeshCmd` now uses a gmsh wrapper command (instead of bare `gmsh.exe`) to prevent 90s ATH timeouts.
- CFG list serialization for object fields now uses ATH-native CSV lists (not JSON arrays).

## 2) Role Of `ath_experiments.sqlite` After New Findings

Database path:
- `reports/ath_experiments/ath_experiments.sqlite`

Current size/status snapshot:
- ~116k runs, ~93k successful (`status='ok'`), ~6.6M parameter rows.

Interpretation:
- The DB remains the empirical evidence base for:
  - candidate rule discovery,
  - warning heuristics,
  - statistical ranges.
- The recent minimal-completion and preview findings do **not** invalidate the DB.
- But global ranges from mixed contexts are statistically broad and less interpretable for UI guidance.

## 3) Safe Range Recalibration: Better Method

## Problem with global ranges
Existing `range_suggestions.v1.3.json` is global per key across heterogeneous contexts.
This mixes structurally different geometries (OS-SE, CircularArc, R-OSSE, with/without GCurve/Morph/Enclosure).

## Implemented improvement
A new contextual range analysis was added:
- Module: `app/contextual_range_analysis.py`
- CLI:
  - `python -m app ath-experiments contextual-ranges ...`

It stratifies numeric values by:
- profile mode (`osse|circarc|rosse`)
- gcurve mode (`none|se|sf`)
- morph mode (`off|shape1|shape2`)
- enclosure mode (`off|on`)

Range metrics per key and context:
- `safe_min/safe_max`: p01/p99
- `rec_p05/rec_p95`: p05/p95
- `count`

Generated artifacts:
- `reports/ath_experiments/range_suggestions.contextual.v1.json`
- `reports/ath_experiments/range_suggestions.contextual.v1.md`

## UI integration
`UiValidationEngine` now auto-loads contextual ranges when available:
- file: `reports/ath_experiments/range_suggestions.contextual.v1.json`
- behavior:
  - context-specific range preferred
  - fallback to global range if no matching context bucket exists

This directly improves warning precision without changing ATH core rules.

## 4) ATH Guide Alignment Used For Recalibration

Local references used:
- `C:\Users\maximilianheinze\Desktop\Ath-4.8.2-UserGuide-2.pdf`
- `C:\Users\maximilianheinze\Desktop\R-OSSE Waveguide rev7-2.pdf`

Key guide anchors applied:
- Mandatory/default semantics (guide chapter 4, p.17-19).
- Profile/GCurve/Morph item definitions and defaults (p.18-19).
- Enclosure semantics:
  - pre-defined enclosure: `Depth` mandatory in that mode (p.55)
  - plan mode uses `Plan` flow (p.57-58)

These guide constraints were used to keep policy-minimal requirements explicit while preserving preview robustness.

## 5) Practical Outcome
- Compatibility engine truth remains stable.
- Preview pipeline is now more robust and deterministic.
- Safe-range warnings can be context-aware instead of globally over-broad.
- `ath_experiments` becomes more valuable after stratification, not less.

