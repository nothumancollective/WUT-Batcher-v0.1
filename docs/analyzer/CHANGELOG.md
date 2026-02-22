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

## 2026-02-21 (UI-1D.4)
- UI-1D.4: Consolidated Batch header into one compact row (`BATCH + Batch Name + Save + Run`) and removed redundant global TopBar page text for Batch mode.

## 2026-02-21 (UI-1D.5)
- UI-1D.5: Reworked Batch summary area into a responsive summary strip (Draft / Estimate / Validation) with reduced dead space and consistent card typography/padding.

## 2026-02-21 (UI-1D.6)
- UI-1D.6: Cleaned Exports footer copy/layout, switched to concise default-export labeling, and aligned `Simulate Enclosure` + `Advanced` actions with responsive wrapping.

## 2026-02-21 (Polish A6)
- Restored TopBar center title to `BATCH` for Batch mode to avoid an empty global header.
- Removed duplicate in-page `BATCH` text from the Batch header row; the row now starts with Batch Name and actions.

## 2026-02-21 (Polish A7.1)
- Added reusable header primitives for upcoming Batch upper-region rewrite:
  - `CommandHeaderWidget` (responsive command bar + status deck shell)
  - `FlowLayout` (wrap-safe chip row behavior).

## 2026-02-21 (Polish A7.2)
- Integrated `CommandHeaderWidget` into `BatchPage` and replaced the old Draft/Estimate/Validation card strip.
- Batch upper region now uses a compact two-row template:
  - command bar (`Batch Name`, `Save Batch`, `Run Batch`)
  - wrap-safe status deck (estimate chips + clickable issues chip with popover list).

## 2026-02-21 (Polish A8+A12)
- Fixed footer clipping around action buttons in Batch right-column panels:
  - Exports footer (`Simulate Enclosure`, `Advanced`)
  - Mesh group `Advanced` launcher button.
- Replaced brittle fixed-height usage with minimum-height + layout-padding constraints.

## 2026-02-21 (Polish A9)
- Added explicit shared form-grid spacing spec in `BatchParameterForm` and applied it to Basics rows for consistent label/editor alignment.
- Kept Basics as a regular parameter card (no mode-stack hierarchy changes, no field logic changes).

## 2026-02-21 (Polish A10)
- Removed R-OSSE single-object special-case rendering in Batch parameter form.
- R-OSSE now renders through property rows (`R-OSSE.*`) using the same row renderer as other throat-profile parameters.
- Sweep controls are now available on R-OSSE property rows, while selected-params payload still normalizes back to `R-OSSE` object shape.

## 2026-02-21 (Polish A11)
- Fixed GCurve Superformula alignment by inserting a conditional grid-gap cell between Common and Superformula rows on 3-column layouts.
- Added focused UI regression coverage for the Superformula gap cell in the GCurve responsive grid.

## 2026-02-21 (Regression fix: project open)
- Hardened Project Manager open flow by wiring tile double-click directly to the selected item payload and keeping Open button state in sync with selection.
- Refresh now restores or initializes a valid selection, reducing no-op open attempts.
- Added guarded error handling for failed project loads so open failures surface clearly instead of silently failing.

## 2026-02-21 (Regression fix: create + batch nav guard)
- Prevented duplicate project creation by enforcing single in-flight create execution and keeping `Create Project` disabled once project constraints are locked.
- Hardened project submit handler against re-entry while creation is active.
- Batch-mode navigation now requires an open project; when none is loaded it keeps the user in Project/Dashboard mode and shows a status prompt.

## 2026-02-21 (Regression tests: project open + batch navigation)
- Added focused UI regression tests covering:
  - single-shot project creation behavior on repeated create clicks
  - Project Manager open-project flow updating MainWindow state
  - Batch mode navigation via ModeBar and Dashboard `New Batch`
  - no-project Batch-mode guard behavior.

## 2026-02-21 (Runtime verification: uncaught trace logging)
- Added deterministic GUI runtime exception logging (`sys.excepthook` + Qt message handler) to:
  - `%LOCALAPPDATA%\\WUTBatcher\\logs\\ui_runtime_errors.log`
- Log entries now include timestamp, exception type/message, traceback, and current GUI context (`page`, `mode`, `project_id`).
- Added because real-run reproduction showed failures not captured by the prior unit/UI suite.

## 2026-02-21 (Runtime fix: CommandHeader widget lifecycle)
- Real-run trace showed repeated crashes:
  - `RuntimeError: Internal C++ object (PySide6.QtWidgets.QPushButton) already deleted`
  - stack rooted in `CommandHeaderWidget._rebuild_status_chips()` and `MainWindow.show_batch()/load_project()`.
- Fixed command-header lifecycle:
  - status-chip rebuild now preserves `issues_chip` instead of deleting it via flow clear
  - command-bar remount now detaches persistent widgets before layout clearing
  - narrow actions row is persistent (no transient container that could orphan/delete Save/Run buttons).
- Verified in real runtime session:
  - existing project open works (Open button + double-click)
  - newly created project opens
  - Batch tab and Dashboard `New Batch` both reach Batch page
  - no unhandled exceptions in `ui_runtime_errors.log` (only non-fatal Qt geometry warnings).

## 2026-02-21 (Polish A16+A17+A23)
- Header reset visibility logic fixed: reset icon now shows only when a block is collapsed and has overrides.
- Sweep warning tint override removed; sweep buttons keep primary sweep styling while warnings apply only to inputs.

## 2026-02-22 (Batch UI stabilization regression fix)
- Corrected chip/titlebar text rendering by normalizing chip values through a shared `safe_text()` helper and replacing corrupted glyph output with safe display tokens.
- Restored GCurve subgroup ordering so mode selector controls render above the common parameter grid, with mode-specific controls below.
- Replaced unstable dialog widget-moving flows for `Simulate Enclosure` and `Mesh Advanced` with stable dialog-local editors bound directly to Batch variable parameter updates.
- Extended warning styling to input widgets (`QLineEdit`/spinbox family) while explicitly pinning sweep buttons to sweep styling so warnings never recolor sweep controls.
- Added issue-chip click affordance (cursor + chevron cue) and widened top-bar title minimum width to reduce title ellipsis.
- Verified via targeted UI suite and runtime Batch smoke script (dialogs open/edit/close/reopen without blanking/crash).
- Warning border selectors now explicitly cover `QSpinBox`/`QDoubleSpinBox`/`QAbstractSpinBox` (including internal line edits) without border-width changes.

## 2026-02-21 (Polish A13+A15+A18)
- Unified Batch form-grid spec across cards, including Basics, to keep label/control spacing consistent without extra vertical gaps.
- Refactored GCurve card rendering into two structural containers:
  - `common_frame`: `Dist`, `AspectRatio`, `Width`, `Rot`
  - `mode_frame`: `Mode` + mode-specific parameters (`Superformula` / `Superellipse`)
- Added subtle container separation in GCurve without textual subheadings and removed the old gap-cell workaround.
- Enforced Circular Arc ordering so `CircArc.TermAngle` renders before `CircArc.Radius`, aligning both fields in the same two-column row flow.

## 2026-02-21 (Polish A14)
- Compatibility sweep-key resolution now includes `R-OSSE` when that mode is visible, re-enabling sweep controls for `R-OSSE.*` rows.
- Added regression coverage to ensure `R-OSSE.R` / `R-OSSE.r0` sweeps become active in R-OSSE mode and serialize into sweep payload.
- Added UI coverage that group-header reset controls start hidden when no overrides are present.

## 2026-02-21 (Polish A19+A20)
- `open_enclosure_dialog()` now temporarily restores Enclosure group visibility/expanded state in the dialog, then restores hidden/collapsed state after close.
- `open_mesh_advanced_dialog()` now temporarily restores compatibility-visible advanced rows in the dialog (instead of empty modal content) and restores detached hidden state on close.
- Added dialog population regression tests for both Enclosure and Mesh Advanced modal paths.

## 2026-02-21 (Polish A21+A22+A24)
- TopBar center-title layout was rebalanced (removed symmetric stretch squeeze) so mode titles do not truncate under normal window widths.
- Issues popover now applies responsive content width bounds and keeps a scrollable body for large warning lists to prevent clipping.
- Added reusable `HelperRow` primitive and integrated it into Batch field hints (optional icon + wrapped text + subtle background) without changing Batch action button sizes.

## 2026-02-22 (Batch UI final stabilization pass)
- Batch card layout stabilization:
  - added consistent subsection frames across Batch cards (`Basics`, `Throat Profile`, `GCurve`, `Morph`, `Mesh`) without introducing extra headings or inflated vertical spacing
  - fixed responsive reflow so hidden rows no longer reserve diagonal/empty grid slots (notably Circular Arc / Superformula cases)
  - kept GCurve ordering as `Mode -> Common -> Mode-specific`.
- Header + warning polish:
  - removed the extra trailing `v` from the command-header warnings chip (`Warnings: N` only)
  - removed cheap text chevrons from card headers and kept clear click affordance via clickable/hoverable header cursor behavior.
- Warning propagation hardening:
  - object-key issues (e.g. `R-OSSE`) now fan out to visible `R-OSSE.*` rows so warn styling consistently reaches the actual input controls
  - added segment-button warn styling while preserving sweep-button immunity from warning tint.
- Popup stability + consistency:
  - introduced shared frameless popup template (`StyledDialogBase`) and applied it to Batch popups and Export Advanced dialog shell
  - migrated Mesh Advanced / Simulate Enclosure popup editors to schema-driven `ScalarFieldEditor` controls (matching project-side control types while writing Batch variables)
  - verified no blanking/crash on toggle/edit flows.

## 2026-02-22 (Batch layout + R-OSSE visibility follow-up)
- Fixed R-OSSE subgroup visibility regression: subsection frame visibility now tracks rendered `R-OSSE.*` property rows (not just the parent `R-OSSE` object key), so the block appears reliably when mode 2 is active.
- Stabilized Batch card resize behavior by reducing aggressive multi-column expansion at large widths (keeps Basics/GCurve/Throat behavior consistent under fullscreen-like widths).
- Hardened Batch split-column bounds: left panel is now explicitly width-bounded against the computed right-panel width to prevent left-card rendering from intruding into the right Preview/Exports column.

## 2026-02-22 (Analyzer Phase 2A: cache schema + presets baseline)
- Added additive KPI cache storage table `analyzer_run_kpis` to SQL dataset schema (project + global), including cache identity indexes and score-oriented lookup indexes.
- Added `_dual_write` replication operation `upsert_analyzer_run_kpis` and store-level upsert/list APIs for Analyzer KPI rows.
- Added canonical Analyzer preset definitions (`coverage`, `band`, `tolerance`, `stage`) in `app/analyzer/presets.py`, including a default scoring band starting at `200 Hz`.

## 2026-02-22 (Analyzer Phase 2A: KPI engine + service caching)
- Added magnitude-only KPI compute engine (`app/analyzer/kpi_engine.py`) implementing MVP metrics: `B_PC`, `E_BW`, `E_cov`, `R_spill`, and Jump/Collapse/Wide flags.
- Added service-layer Analyzer APIs for:
  - presets exposure
  - cached KPI reads by compute config
  - batch-level KPI compute with cache-skip/recompute rules (`algo_version` + `source_hash`)
  - run metadata merge with cached KPI scalars/stage score for Batch Review table consumption.
- Added synthetic unit tests for KPI engine behavior and service caching/recompute flow (`tests/test_analyzer_kpi_engine.py`, `tests/test_analyzer_kpi_service.py`).

## 2026-02-22 (Analyzer Phase 2A: Batch Review UI wiring)
- Extended Analyzer page UI with KPI controls for stage/target/tolerance/band presets, plus filter controls and a `Compute KPIs` action.
- Added background KPI compute worker with progress/cancel wiring; compute runs only for project source and refreshes cached KPI scalars on completion.
- Updated run table to show sortable KPI columns (`score`, `B_PC`, `E_BW`, `E_cov`, `R_spill`, `flags`) and stage-based default column visibility/filter presets.
- Added focused GUI regression coverage for Analyzer KPI controls and filter behavior.

## 2026-02-22 (Analyzer Phase 2B: Explorer plots + cache settings)
- Added Analyzer polar plot data pipeline (`AnalyzerPlotService`) and in-memory LRU cache manager (`AnalyzerPlotCache`) with soft-limit eviction.
- Extended Settings dialog with `Analyzer -> Cache` modes (`Low`, `Balanced`, `High`, `Extreme`, `Custom`) and persisted mode/limit/keep-last settings.
- Extended Analyzer `Batch Review` right pane with:
  - Context Bar (Stage/Target/Band/Tolerance + clamp controls + plane toggle)
  - `Explorer` sub-tab (heatmap + beamwidth rendering)
  - `Compare` sub-tab skeleton (up to 5 selected runs, cached KPI scalar table, Phase 2C note)
- Plot loading now runs in a dedicated background worker with debounce + cancel, and loads `polar_points` only for the selected run/version/plane.

## 2026-02-22 (Analyzer Phase 2B: plot/cache regression tests)
- Added unit coverage for Analyzer plot cache policy/eviction and plot math helpers:
  - nearest-0deg normalization
  - beamwidth(-6 dB) curve extraction.
- Extended GUI Analyzer tests to cover Explorer behavior:
  - run selection triggers background plot load and renders canvases
  - fast run switching remains stable while plot workers are canceled/replaced.

## 2026-02-22 (Analyzer Phase 2B: settings layout follow-up)
- Increased default Settings dialog size to keep the new Analyzer cache controls visible without clipping at open.

## 2026-02-22 (Analyzer Phase 2C: saved analyses schema + service APIs)
- Added additive project-db tables for persisted Analyzer Compare sessions:
  - `analyzer_analyses`
  - `analyzer_analysis_candidates`
- Added service/store APIs for saved analyses lifecycle:
  - save/update analysis config + candidates (max 5)
  - list analyses
  - load analysis (config + ordered candidates)
- Added project-local auto-pick service (`A/B/C` strategies) that ranks from cached KPI scalars only (no `polar_points` preload for table operations).

## 2026-02-22 (Analyzer Phase 2C: Compare tab workflow + heatmap/overlay styling)
- Replaced Compare placeholder with a real candidate workflow:
  - compare slots (max 5) with remove actions
  - `Add selected`, `Auto-pick...`, `Save Analysis...`, `Load` actions
  - saved-analysis selector (project source only)
- Added worker-driven Compare plotting pipeline:
  - beamwidth overlay (distinct stable colors per candidate order)
  - single-candidate heatmap switcher for compare mode
  - cancel support for compare/autopick background operations
- Added shared VACS-like POLAR heatmap LUT module and applied it consistently to Explorer + Compare heatmaps.
- Added focused UI+style test coverage for compare workflow and LUT sanity.

## 2026-02-22 (Analyzer UI layout overhaul: plot-first Batch Review workspace)
- Reworked Analyzer Batch Review layout to prioritize plot readability:
  - compact Analyzer toolbar with project/batch/source/filters and run summary chips
  - run details moved to a read-only `Details...` dialog (summary/files/raw tabs)
  - legacy always-visible details panel removed from main workspace
- Replaced permanent left run column with compact run selection:
  - toolbar run selector for primary selection
  - collapsible `Runs` drawer containing the full run table
- Explorer now uses a scalable plot-tile architecture:
  - two splitter tiles with per-tile graph type selectors (`Heatmap`, `Beamwidth`, `SPL` scaffold)
  - focus/unfocus action per tile for temporary single-tile expansion
- No KPI compute/scoring logic was changed; updates are UI/layout and presentation wiring only.

## 2026-02-22 (Analyzer UI overhaul test coverage)
- Extended Analyzer GUI smoke coverage to lock the new workflow:
  - toolbar run selector presence
  - run selection -> summary chip updates
  - `Details...` dialog open path
  - Explorer/Compare tab switching stability
- Existing Analyzer compare and project/batch navigation regression suites remain green after the layout overhaul.

## 2026-02-22 (Analyzer pro-layout refactor + settings relocation)
- Analyzer page IA restructured for readability and scaling:
  - compact project-local toolbar (`Batch`, `Version`, refresh/compute, context chips, details dialog)
  - two control tiles (`Analysis` + `Display`) replacing overcrowded mixed rows
  - explicit segmented mode navigation (`Explorer` / `Compare`) with hidden tab bar clutter.
- UI terminology now prioritizes `Batch/Version` identity in list/shortlist surfaces; internal `run_id` is kept in details/raw views.
- Compare UI redesigned to fixed `C1..C5` shortlist slots with persistent candidate colors and compact overlay/heatmap + KPI compare surfaces.
- Plot readability improved:
  - heatmap smoothing default with raw-bin toggle
  - log/linear x-axis mode selector
  - visible frequency ticks/grid labels for Explorer and Compare beamwidth plots.
- Gear Settings now includes an `Analyzer` tab with `Data source` selection (`Project`/`Global`); per-page source dropdown removed from Analyzer toolbar.

## 2026-02-22 (Analyzer pro-layout regression tests)
- Updated Analyzer UI tests to assert `Batch/Version`-first display (instead of exposing run UUIDs in primary table/summary surfaces).
- Added shortlist interaction coverage for Compare (`add/remove` updates visible slot rows without crashes).
- Added Gear Settings Analyzer-tab tests to lock data-source relocation (`Analyzer` tab + source save roundtrip).
- Stabilized Explorer background-plot smoke assertion to wait for async completion signal before checking ready-state text.

## 2026-02-22 (Analyzer pro-layout polish: toolbar/tiles/plots/compare)
- Toolbar cleanup:
  - replaced workspace-level `Versions` panel behavior with an anchored searchable version picker popup (keyboard-friendly: arrows/Enter/Esc)
  - kept exactly one KPI compute action button in the visible toolbar
  - reduced inline KPI text noise to compact summary chips + dedicated KPI popover (`KPIs` button) with friendly labels.
- Control-tile refinement:
  - converted `Exclude flagged` / `Exclude warnings` into explicit checkable toggle buttons
  - moved `Band` + `Tol` into `Display` tile with tooltip clarifying shared plot/KPI impact
  - set clamp default to `-20 dB` in UI defaults and heatmap canvas behavior
  - added a disabled `Norm angle` selector (`0 deg` / `10 deg`) with explanatory tooltip because post-hoc angle normalization switching is not currently supported by the plot pipeline.
- Plot readability/padding pass (Explorer + Compare):
  - heatmap now renders angle ticks/labels, log-frequency major+minor ticks, and subtle horizontal/vertical grid cues
  - beamwidth and beamwidth-overlay plots now render consistent axis labels, log/linear tick handling, and improved margins to avoid clipped tick text
  - removed redundant in-plot title/status text where page/tile titles already provide context
  - enforced consistent heatmap orientation by mapping larger angles upward in the rendered view.
- Compare panel cleanup:
  - narrowed left shortlist column defaults
  - replaced bottom KPI row emphasis with a compact `Selected Candidate KPIs` panel under shortlist
  - kept overlay-heatmap candidate selector with explicit tooltip describing single-heatmap + overlay behavior.
- Added/updated targeted UI tests covering:
  - single compute button presence
  - versions picker popup selection path
  - analyzer toggle controls + clamp default
  - compare shortlist KPI panel behavior
  - heatmap orientation sanity rendering.

## 2026-02-22 (Analyzer pro-layout polish: regression test lock)
- Extended Analyzer GUI regression coverage to lock the final polish pass:
  - toolbar compactness contract (`1` compute button, popup-based version selection path)
  - control defaults (`-20 dB` clamp) and toggle affordances
  - compare shortlist KPI panel and overlay-heatmap selector guidance
  - heatmap orientation sanity rendering (positive angles map upward in plot view).

## 2026-02-22 (Analyzer stage-plot discovery + artifact/service scaffolding)
- Discovery baseline confirmed in repo:
  - Analyzer UI shell and workers already present in `app/gui.py`
  - KPI cache table `analyzer_run_kpis` and saved-analysis tables already exist in dataset schema
  - polar source tables (`polar_measurements`, `polar_points`) are available in freshly initialized project/global DBs.
- Added canonical Analyzer artifact registry scaffold in `app/analyzer/artifacts.py`:
  - `POLAR` (available)
  - `SPL_FR`, `IMPEDANCE`, `PHASE_GD` (availability probes only; no ingestion changes).
- Added stage-curve compute module `app/analyzer/stage_plot_engine.py` and integrated service API:
  - `analyzer_load_stage_plot_payload(...)` now returns stage-specific curves + artifact availability metadata
  - no runner/export/import pipeline changes.
