# Analyzer UI Architecture (Modern, Scalable, MT/HT Workflow)

**Last updated:** 2026-02-22

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

- Batch page top row is consolidated to `Batch Name + Save + Run` within one compact header strip.
- Global TopBar center text shows `BATCH` while Batch mode is active.

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

## Implementation status (Polish A7.1)

- Introduced reusable shared UI primitives for the next Batch header integration:
  - `CommandHeaderWidget`: two-row template (`Command Bar` + `Status Deck`) with deterministic wide/narrow switching.
  - `FlowLayout`: wrap-safe layout for status chips without fixed positioning.

## Implementation status (Polish A7.2)

- Batch upper region is now rendered through `CommandHeaderWidget`.
- Removed legacy `Batch Draft / Estimate / Validation` cards from Batch page content.
- `CommandHeaderWidget` behavior:
  - Row 1: responsive command bar (`Batch Name` + `Save Batch` + `Run Batch`) with deterministic wide/narrow switching.
  - Row 2: status deck with wrap-safe estimate chips and a clickable issues chip.
  - Issues chip opens an anchored popover listing current validation/warning messages.

## Implementation status (Polish A8+A12)

- Right-column action-footer clipping was reduced by replacing fixed-height button constraints with minimum-height layout-driven sizing.
- Exports footer and Mesh `Advanced` trigger now rely on bottom padding/margins plus non-fixed max heights for safer resize behavior.

## Implementation status (Polish A9)

- Basics card layout now uses the same shared row-grid spec family as the other geometry cards.
- Change scope stayed layout-only (label width/spacing/alignment); Basics field set and card hierarchy were preserved.

## Implementation status (Polish A10)

- R-OSSE throat-profile mode no longer uses a dedicated object-only editor path.
- R-OSSE properties are rendered as normal parameter rows (`R-OSSE.*`) in the same row/sweep system used by other throat-profile mode fields.
- Selected-parameter payload remains compatible by collapsing visible `R-OSSE.*` row values back into `R-OSSE` object form.

## Implementation status (Polish A11)

- GCurve responsive grid now supports conditional gap cells.
- Superformula mode uses a 3-column-only gap between `GCurve Rot` and first `GCurve.SF.*` cell, preventing direct adjacency/misalignment in wide layouts.

## Implementation status (Polish A13+A15+A18)

- Batch form rows now use one shared grid-spec family across cards (including Basics) to keep row spacing and label/control alignment consistent.
- GCurve rendering is split into two internal containers:
  - common parameters (`Dist`, `AspectRatio`, `Width`, `Rot`)
  - mode-driven parameters (`Mode`, `Superformula`, `Superellipse`)
- Circular Arc field ordering in Batch rendering is normalized so `TermAngle` is placed before `Radius` in the two-column row flow.

## Implementation status (Polish A19+A20)

- `Simulate Enclosure` now uses a dialog-local minimal form (enable/disable toggle + scrollable fields) bound to Batch variable parameter updates.
- `Mesh Advanced` now uses a dialog-local compatibility-filtered editor form bound to Batch variable parameter updates, avoiding runtime re-parent/clear cycles.
- Both dialogs are built once per open and update values through existing Batch field edit pathways; no card remounting/reparenting is used.

## Implementation status (Polish A21+A22+A24)

- Global TopBar title allocation now prioritizes center-title width (no symmetric stretch squeeze), reducing unnecessary truncation in normal window sizes.
- Command-header issue popover now enforces responsive width bounds plus a scrollable message area for long warning lists.

## Implementation status (Batch stabilization follow-up)

- Chip/titlebar text rendering now routes through a shared safe-text normalization helper to avoid mojibake/bytes rendering artifacts.
- Command-header warning chip text is now plain (`Warnings: N`) without trailing chevron glyph text.
- Sweep controls are explicitly marked with `role="sweep"` and excluded from warning-color selectors; warning borders remain on input controls only.
- Warning mapping now expands object-level `R-OSSE` issues to visible `R-OSSE.*` rows so input-level warning borders are consistently applied.
- Batch cards with internal subsections now render through subtle section frames (no extra headings) while keeping compact spacing.
- Responsive subgroup grids now repack based on explicit row visibility, preventing hidden-row hole artifacts in Circular Arc / Superformula layouts.
- GCurve subgroup stacking order is stabilized as `Mode` -> `Common` -> `Mode-specific` for predictable layout and spacing.
- Batch inline hint presentation now uses reusable `HelperRow` components (optional icon + wrapped text + subtle surface), replacing plain helper labels while preserving hint logic.
- Batch popup shells now reuse a shared frameless dialog template (`StyledDialogBase`) aligned with Export Advanced dialog visuals.
- Batch body column sizing now enforces explicit left/right bounds during resize so expanded left cards remain clipped to the left column and cannot bleed into the right Preview/Exports column.
- R-OSSE subsection visibility now follows rendered `R-OSSE.*` rows when only parent-key compatibility visibility (`R-OSSE`) is present.

## Implementation status (Analyzer Phase 2A: Batch Review KPI MVP)

- Analyzer `Batch Review` now includes KPI-focused control surface:
  - stage selector: `Concept | Shaping | Stabilization`
  - target preset selector (`H x V`)
  - tolerance control (`+/- deg`)
  - frequency-band preset selector (including `Full (auto)` and `Custom`)
  - filters (`Exclude flagged`, `Exclude warnings`, `Min score`)
  - `Compute KPIs` / `Refresh KPIs` action
- Run table now renders cached KPI columns per run/version:
  - `Score`, `B_PC`, `E_BW`, `E_cov`, `R_spill`, `Flags`
  - stage presets toggle default visible KPI columns and filter defaults
- Compute path is background-threaded with progress + cancel:
  - compute runs only against project source DB
  - writes KPI cache rows to project DB and replicates to global DB via existing replication queue model
  - UI refresh re-queries cached scalar rows only (no matrix preload in table view)
- Metadata/list view remains lightweight:
  - table refresh uses metadata + cached scalar joins
  - `polar_points` are loaded only inside the explicit compute worker.

## Implementation status (Analyzer Phase 2B: Polar visualization MVP)

- Analyzer right pane now uses an explicit `Context Bar` + sub-tabs:
  - `Explorer`: Polar Heatmap + Beamwidth(-6 dB) curve
  - `Compare`: scalar KPI compare skeleton (up to 5 selected runs) + Phase 2C note
- Context Bar controls are compact and editable in place:
  - Stage, Target preset, Band preset (`Full`/`Custom` included), Tolerance
  - Heatmap clamp toggle + clamp minimum dB control
  - Plane toggle (`H` / `V` / `D`, `D` shown only when available)
- Plot data flow is on-demand per selected run/version/plane:
  - metadata table stays scalar-only
  - selecting a run starts a debounced background plot worker
  - switching selection/plane cancels the previous worker request
  - no `polar_points` matrix preload for the run table
- Plot pipeline:
  - deterministic angle/frequency ordering
  - relative normalization against nearest angle to `0 deg`
  - beamwidth curve uses fixed `-6 dB` criterion on log-frequency axis
  - deterministic heatmap downsample cap for display (`<= 512` freq bins)
- Caching (POLAR-only, in-memory LRU) is now configurable via Settings:
  - `Low`: keep 1 run, size limit `0 MB` (most-recent only)
  - `Balanced`: keep 5 runs, soft limit `< 250 MB`
  - `High`: keep 15 runs, soft limit `< 750 MB`
  - `Extreme`: keep 30 runs, soft limit `< 1500 MB`
  - `Custom`: user-defined soft limit (`<= 10 GB`) and keep-last count
- Cache keys include selection/config identity:
  - project_id, batch_id, run_id, version_id, plane, normalization policy, band range.

## Implementation status (Analyzer Phase 2C: Saved Analyses data model + auto-pick service)

- Added project-local persistence for compare sessions (POLAR artifact type):
  - `analyzer_analyses` stores analysis metadata + context config JSON (`stage`, `target`, `band`, `tolerance`, clamp, strategy/filter settings).
  - `analyzer_analysis_candidates` stores ordered candidate identities (`batch_id`, `run_id`, `version_id`) with max 5 slots.
- Persistence is currently project-db only by design (no global replication in 2C).
- Added Analyzer service APIs for:
  - save/load/list saved analyses
  - deterministic project-local auto-pick strategies from cached KPI scalars:
    - `A`: top N by score
    - `B`: top N by selected KPI
    - `C`: filter + score tie-break.
