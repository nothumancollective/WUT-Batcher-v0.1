# Analyzer UI Architecture (Modern, Scalable, MT/HT Workflow)

**Last updated:** 2026-02-21

This document captures the **UI/navigation decisions** and **implementation constraints** for the Analyzer UI.
It is written to be actionable for Codex implementation while minimizing risk to existing Batch UI polish.

## Non-negotiables (from product requirements)

- Keep **Project Manager** as a persistent launcher window (separate window).
- Main app uses a **bottom mode bar** (DaVinci-like modes):
  - Project | Batch | Analyse
  - (Future: Merge)
- Global always-visible icon actions:
  - 🏠 Project Manager
  - ⚙ Settings / Preferences
- Page-local actions remain on their pages (e.g., Save/Run within Batch).
- Future expansion: **Geometry layer**:
  - Geometry selection will happen on Project page (like Timeline selection in DaVinci’s Edit).
  - Modes always operate on the currently selected Geometry (future).

## Navigation model

### Global vs page-local actions
- **Global actions:** apply regardless of current mode/page (Project Manager, Settings).
- **Page-local actions:** apply only in the current mode/page (Save/Run Batch, Analysis compare/export).

### Proposed frame layout (Qt)
- QMainWindow
  - Top context bar (global icons, title; later: project/geometry context)
  - Central content: existing QStackedWidget pages
  - Bottom mode bar (Project/Batch/Analyse)

## Design language constraints (match current style)

- Do not “invent” a new style system.
- Reuse existing components/classes and existing QSS (if present).
- No large visual refactors of Batch page cards.
- Icon buttons must follow existing hover/pressed/disabled states.

## Responsiveness rules (prevent glitches on resize)

**Hard rules:**
- Use Qt layouts only (QVBoxLayout/QHBoxLayout/QGridLayout/QSplitter).
- No absolute positioning (`move()`, fixed geometries).
- Avoid fixed widths/heights except for small toolbars/bars.
- Correct size policies:
  - bars: fixed height, expanding width
  - plots/tables: expanding both directions
- Define sensible minimum window size and minimum widths for critical panels.
- Use eliding/word wrap for labels where needed; avoid text overlap.
- Use ScrollArea for long forms rather than squeezing controls.

## Batch page: minimal-invasive changes

Goal: remove the current bottom bar controls without damaging the polished Batch layout.

- Remove: “Back to Dashboard”
- Move global actions out of the page:
  - Project Manager becomes 🏠 in the global top bar
  - Settings becomes ⚙ in the global top bar
- Keep page-local actions:
  - Save Batch
  - Run Batch
- Integrate Save/Run minimally:
  - Prefer placing them in a stable header area of the Batch page
  - Or within the existing “Exports” panel (only if it preserves layout integrity)
- Do not rearrange the parameter cards and their internal spacing/validation UI.

## Analyse page: initial structure

For UI-1 implementation (structure first):
- Add Analyse page to the main stacked widget
- Layout uses QSplitter:
  - Left: run/batch selection + KPI filters + shortlist (table)
  - Right: plots (heatmap/beamwidth overlay placeholders)
- Do not implement KPI math yet unless explicitly scoped.

## Analyzer subviews (planned before implementation)

The Analyzer page is planned with two explicit subviews:

1. `Batch Review`
- Focus: one batch at a time.
- Purpose:
  - inspect runs within a selected batch
  - apply filter/sort/rank controls
  - open per-run visual diagnostics
- Performance rule:
  - selection and sort/filter interactions must stay lightweight
  - expensive KPI work must run incrementally in background workers

2. `Candidate Pool`
- Focus: cross-batch comparison.
- Purpose:
  - pin/shortlist runs across multiple batches
  - compare pinned runs side-by-side in Analyzer
- Core behavior:
  - pinning is metadata/selection management first
  - selecting pinned runs must **not** trigger heavy full recompute
  - use cached metrics/results where available; defer expensive compute on-demand only

## Future: geometry layer implications (preview only)

- Geometry selector appears on Project page (timeline-like list).
- New mode “Merge” appears in bottom bar later.
- Mode pages always operate on currently selected geometry.
- This implies future DB changes (e.g., geometry_id) — not in scope now.

## Implementation status (UI-1A)

- Implemented in app shell:
  - persistent global top bar (`home` + page title + `settings`)
  - persistent bottom mode bar (`Project | Batch | Analyse`) with exclusive mode switching
  - empty `Analyse` placeholder page in the main stacked widget
- Scope intentionally preserved:
  - no KPI logic
  - no database/query changes
  - no structural changes to Batch page internal cards/forms
- Deferred to later phases:
  - migration/removal of legacy Batch-local navigation controls
  - Analyzer subview layout (`Batch Review` / `Candidate Pool`) and KPI panels

## Implementation status (UI-1B)

- Batch page legacy bottom action bar was removed (`Project Manager`, `Back to Dashboard`, `Save Batch`, `Run Batch`).
- `Save Batch` and `Run Batch` now live in the Batch page header row (top-right), preserving existing card/parameter layout.
- Existing save/run code paths are unchanged; only button placement and wiring surface changed.

## Implementation status (UI-1C)

- Analyzer page now uses a horizontal split layout:
  - left: selector panel (`Project`, `Batch`) plus sortable multi-select run table
  - right: selected-run metadata panel plus plot placeholder tabs
- Data loading uses read-only metadata queries only (`polar_measurements`), with all DB reads executed in background worker threads.
- Current scope is discovery-only:
  - no KPI computation
  - no `polar_points` matrix loading yet
  - plot containers are placeholders prepared for future plotting integration.

## Implementation status (UI-1D.3)

- Bottom ModeBar is now a compact segmented switch (`QToolButton`-based, checkable/exclusive) with reduced height and subdued contrast.
- Layout was adjusted to keep ModeBar visually separated from `QStatusBar`, preventing clipping at small heights.

## Implementation status (UI-1D.4)

- Batch page top row is consolidated to `BATCH + Batch Name + Save + Run` within one compact header strip.
- Global TopBar center text is intentionally blank while Batch page is active to avoid duplicated “Batch” titles.

## Implementation status (UI-1D.5)

- Batch summary section now behaves as a responsive strip:
  - wide: three side-by-side cards (Draft / Estimate / Validation)
  - medium: Draft + Estimate top row, Validation full-width below
  - narrow: stacked cards
- Fixed heights and spacer-heavy card interiors were removed to reduce empty space while preserving all summary information.

## Implementation status (UI-1D.6)

- Exports panel footer now presents concise default-export text (`Default exports: Polars (H/V/D)`) with details in tooltip.
- Footer actions are normalized into one right-aligned action group:
  - primary: `Simulate Enclosure`
  - secondary: `Advanced`
- Footer layout switches between wide and compact rows on narrow widths to avoid awkward wrapping/clipping.
