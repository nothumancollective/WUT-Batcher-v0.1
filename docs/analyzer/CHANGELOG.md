# Analyzer Docs — Changelog

## 2026-02-21
- Created initial persistent Analyzer documentation set:
  - Context overview
  - KPI research (raw + indexed foundations)
  - UI architecture decisions
  - KPI scoring scaffold
  - Future geometry layer planning
- Restored repo-grounded Analyzer UI plan artifacts (md+json) for traceability.

## 2026-02-21 (Roadmap update)
- Added `docs/analyzer/ROADMAP.md` with phased plan A-G (Navigation Skeleton -> Geometry Layer) and acceptance criteria.
- Introduced explicit CI fixture constraint: Analyzer CI test batches are capped at max 5 runs.
- Documented real-world large-batch handling strategy: incremental compute + caching (not heavy full-batch tests).
- Officially planned cross-batch comparison via `Candidate Pool` (pin/shortlist across batches, lightweight selection behavior).

## 2026-02-21 (UI-1A)
- UI-1A: Introduced global top bar and bottom mode bar skeleton.
- Added an `Analyse` placeholder page wired into main stacked navigation.
- Kept Batch page internals unchanged; no KPI or database logic added.

## 2026-02-21 (UI-1B)
- UI-1B: Migrated Batch actions (Save/Run) into page header and removed legacy bottom bar.

## 2026-02-21 (UI-1C)
- UI-1C: Implemented Analyzer MVP layout (split view) with read-only polar run discovery.

## 2026-02-21 (UI-1D.1)
- UI-1D.1: Added Qt resource icon pipeline (QRC + compiled resource module) and updated global TopBar buttons to Home + Settings SVG icons.

## 2026-02-21 (UI-1D.2)
- UI-1D.2: Fixed QComboBox/QSpinBox arrow rendering using QRC SVG chevrons and updated theme subcontrols to keep arrow regions visible on Windows HiDPI.

## 2026-02-21 (UI-1D.3)
- UI-1D.3: Reworked bottom ModeBar into a compact segmented switch with checkable toolbuttons and fixed clipping at the status-bar boundary.
