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

## 2026-02-22 (Analyzer UI: stage-based 2x2 Explorer + Compare grids)
- Explorer now renders a fixed stage-driven 2x2 panel matrix:
  - A: Polar map (heatmap + target shading + -6 dB contour)
  - B/C/D: stage-specific metric curves (concept/shaping, stabilization, final).
- Compare now renders a fixed 2x2 matrix:
  - A: stage-dependent overlay key curve
  - B: single-candidate heatmap with contour/shading
  - C: KPI breakdown panel
  - D: Pareto scatter with axis selectors.
- Stage selector now drives plot-tile mapping and compare defaults; Stage-3 missing artifacts are shown as explicit “missing data” messages in the relevant tiles.
- Added Display Advanced toggle for `use_full_angles_for_smoothness` (feeds stage-compute request config without touching runner/import flows).

## 2026-02-22 (Analyzer stage-plot tests: compute + UI)
- Added `tests/test_analyzer_stage_plot_engine.py` covering:
  - Stage-1 curve/overlay generation
  - stabilization curves (`di_proxy`, `s_theta`, `e_sym_shape`)
  - plane-consistency behavior.
- Updated analyzer GUI tests for stage payload wiring:
  - background plot worker tests now mock `analyzer_load_stage_plot_payload(...)`
  - stage-switch title mapping checks for Explorer 2x2
  - compare heatmap selector render path with stage overlay payload.

## 2026-02-22 (Analyzer docs: stage plot system alignment)
- Updated `02_ui_architecture.md` with the canonical stage-based 2x2 Explorer/Compare layout, worker dataflow, and artifact availability behavior.
- Updated `01_kpi_foundations.md` with implemented stage-curve definitions (`E_BW`, `E_cov`, `R_spill`, `DI_proxy`, `S_theta`, `E_sym_shape`, `R_off`) and Stage-3 conditional artifacts.
- Updated `03_kpi_scoring_model.md` with stage-to-plot mapping, compare overlay defaults, and Pareto axis defaults.

## 2026-02-22 (Analyzer surgical polish: plot readability + toolbar/tile cleanup)
- Introduced a shared Analyzer plot rendering policy (margins/ticks/grid) across heatmap and curve canvases to prevent clipped axis titles/tick labels at common window sizes.
- Frequency-axis major ticks now prioritize anchored log ticks (`200`, `500`, `1k`, `2k`, `5k`, `10k`, `16k`) within the active band, with subtle minor gridlines.
- Explorer curve panels no longer render `Selected` legend text in-plot; selection context remains in toolbar chips.
- Heatmap overlays refined:
  - target window shading (`±BW/2`) remains dynamic with target preset changes
  - integrated `-6 dB` contour contrast increased for better readability.
- Toolbar/tile polish:
  - top bar uses compact `Selection` + `Score` + `Flags` chips, `KPIs` and `Details`
  - removed redundant planes text from top bar (plane controls stay in Display tile)
  - `Refresh/Compute KPIs` action normalized to toolbar button sizing
  - Analysis tile exclude controls now have explicit checked-state affordance
  - Display tile normalization controls grouped into one compact row.

## 2026-02-22 (Analyzer UI polish: plot margins + anchored ticks)
- Added a shared `AnalyzerPlotStyle` + `apply_analyzer_plot_margins(...)` path used by Analyzer heatmap and metric curve canvases (Explorer + Compare).
- Increased left/bottom plot margins and moved y-axis labels into a dedicated rotated label band; axis titles now render without clipping/overlap against tick labels.
- Updated log-frequency tick policy so major ticks are anchored to `200/500/1k/2k/5k/10k/16k` within range, with consistent major/minor gridline rendering across heatmap and curves.
- Added a GUI regression test to assert non-empty plot axis labels and shared-style margin application on stage canvases.

## 2026-02-22 (Analyzer UI polish: target overlay + toolbar button sizing)
- Heatmap target-window rendering now computes visible boundaries from `target_half_window_deg` against the active angle range and draws subtle dashed boundary lines plus low-alpha shading.
- For `60x60`, the overlay now marks `+/-30 deg` when signed angles exist, or `0..30 deg` when only positive angles are present.
- Analyzer toolbar action controls were normalized to a single-height button row (`Versions`, `Refresh KPIs`, `KPIs`, `Details`) and `Refresh KPIs` now uses the same neutral analyzer-action styling (no white primary appearance).

## 2026-02-22 (Analyzer UI refresh: 3-block control bar + compact plot tiles)
- Reworked the Analyzer control row into three equal-width sub-blocks (`Analysis`, `KPIs`, `Display`) with reduced vertical footprint and compact label/control spacing.
- `Analysis` block now uses a strict 4-row layout:
  - header row
  - `Stage`
  - `Target` + `Min score`
  - `Exclude flagged` + `Exclude warnings`.
- Added a neutral placeholder `KPIs` middle block (slightly brighter background weighting) for follow-up KPI work.
- `Display` block now shows four compact framed slots; slot 1 contains `Band` + plane toggles (`H/V/D`), slots 2-4 are intentionally empty for staged rollout.
- Moved previously visible display options to `Display -> Advanced...`:
  - tolerance, custom band low/high, x-axis mode, normalization mode/angle, heatmap clamp/min, raw bins
  - `Use full angles for smoothness`
  - new `Show mirrored -6 dB contour` toggle (default off).
- Hidden the standalone metadata status row (`Version list updated` line no longer rendered in page flow).
- Plot tile presentation polish:
  - reduced stage-plot title size (analyzer-only)
  - reduced Explorer/Compare tile gaps by >=50% and tightened tile inner padding
  - added y-tick overlap guard for metric curves to prevent top-label collisions.
- Heatmap `-6 dB` contour rendering now respects the new mirrored toggle; mirrored branch is disabled by default and can be enabled from Advanced.

## 2026-02-23 (Analyzer debug evidence report: polar visibility + KPI zero)
- Added `docs/analyzer/debug_polar_kpi_report.md` with hard evidence from live `P021/B005` data:
  - DB inventory + grouped orientation counts (`V` + `X3_45`)
  - `polar_points` integrity checks (`actual == freq_count * angle_count`)
  - representative TXT-header extraction (`Param_Coord_x2`, `Param_Coord_x3`, missing NormAngle key, freq ranges)
  - KPI row inspection showing stored rows with `score=0.0` and `insufficient_coverage=true`
  - root-cause list with confidence and file/line fix targets.

## 2026-02-23 (Analyzer plane normalization: `X3_45` alias + fallback handling)
- Added analyzer orientation helpers in `app/analyzer/orientation.py`:
  - canonicalization of orientation tokens (`X3_45`/`X3_42` -> `D`, `X3_90` -> `V`, `X3_0` -> `H`)
  - query alias expansion for plot loading.
- Updated Analyzer run aggregation and KPI ingestion to use canonical orientation tokens (`app/services.py`).
- Updated plot loading query to match canonical plane selections against alias tokens in DB (`app/analyzer/plot_service.py`), so selecting `D` can load rows stored as `X3_45`.
- Updated UI available-plane resolution to keep unknown fallback tokens instead of silently dropping them (`app/gui.py`).
- Added regression tests:
  - `tests/test_analyzer_kpi_service.py::test_orientation_alias_x3_45_is_exposed_as_d_and_loads_plot_data`
  - `tests/test_gui_analyzer_page_ui.py::test_unknown_plane_token_is_kept_as_fallback_plane`.

## 2026-02-23 (Analyzer norm-angle resolution + details fallback clarity)
- Added analyzer-side effective norm-angle resolution in `app/services.py`:
  - prefer stored `polar_measurements.norm_angle_deg`
  - fallback to unambiguous `batches.sim_export_params.export_specs[].options.norm_angle`
  - final fallback to nearest available polar angle to `0 deg`.
- Analyzer run payloads now include:
  - `norm_angle_deg` (effective value)
  - `norm_angle_source`
  - `norm_angle_note`.
- Plot normalization now prefers stored norm-angle when available (otherwise nearest-to-zero) via `normalize_relative_to_reference(...)` in `app/analyzer/plot_service.py`.
- Fixed `Run Details` dialog zero-value rendering bug (`0.0` no longer collapses to `--`) and added explicit norm-angle source/note fields (`app/gui.py`).
- Added regression tests:
  - `tests/test_analyzer_kpi_service.py::test_norm_angle_falls_back_to_batch_export_settings_when_db_missing`
  - `tests/test_analyzer_plot_service.py::test_normalize_prefers_provided_norm_angle_when_present`
  - `tests/test_gui_analyzer_page_ui.py::test_run_details_dialog_shows_zero_norm_angle_value`.

## 2026-02-23 (Analyzer KPI robustness: band intersection, one-sided coverage, reason codes)
- Updated KPI engine (`app/analyzer/kpi_engine.py`) to:
  - keep strict requested-band intersection (`EMPTY_BAND_INTERSECTION` on empty overlap)
  - support one-sided angle sets with limited-coverage beamwidth estimation
  - emit explicit reason codes and missing-plane diagnostics
  - treat unscorable payloads as `score=None` instead of forced `0.0`.
- Updated analyzer service wiring (`app/services.py`):
  - cache reads now expose `kpi_reason_codes` (with compatibility backfill for older cache rows)
  - cache writes persist nullable score when payload is unscorable.
- Updated Analyzer UI surfaces (`app/gui.py`):
  - run table/details now show `missing` when KPI rows are absent (`MISSING_KPI_ROWS`)
  - details panels now display joined KPI reason codes.
- Updated docs rules in `docs/analyzer/02_ui_architecture.md` for:
  - norm-angle reference fallback behavior
  - strict band-intersection and unscorable-score semantics.
- Added regression tests:
  - `tests/test_analyzer_kpi_engine.py::test_one_sided_angles_are_scored_with_limited_coverage_reason`
  - `tests/test_analyzer_kpi_engine.py::test_empty_band_intersection_marks_payload_unscorable`
  - `tests/test_analyzer_kpi_service.py::test_batch_review_rows_mark_missing_kpi_rows_with_reason_code`
  - `tests/test_gui_analyzer_page_ui.py::test_missing_kpi_rows_show_missing_flag_text`.
