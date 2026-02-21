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
