# PROJECT UI (Form-Based Constraints)

## Scope
- Replaces raw JSON textareas on the PROJECT page with a metadata-driven PySide6 form UI.
- Sources of truth:
  - `app/knowledge/ath/catalog.v1.json`
  - `app/knowledge/ath/ruleset.v1.json`
  - `app/compat_engine.py` / `app.compatibility_service.CompatibilityService`

## Implementation
- Schema: `ui/form_schema.py`
  - Builds `FieldSpec` definitions from ATH catalog metadata.
  - Derives visibility-mode relations from ruleset visibility rules.
  - Extends `Throat.Profile` UI options to `OS-SE / R-OSSE / Circular Arc`.
- Builder: `ui/form_builder.py`
  - Maps field types to Qt widgets:
    - `float/int -> NullableNumericInput` (empty allowed, locale `,` normalized to `.`)
    - `enum -> segmented buttons (<=4) or combo`
    - `bool -> optional segmented off/on` (second click clears to `unset`)
    - `ex -> nullable line edit` (short example placeholder + tooltip semantics)
    - `list -> nullable line edit` (`e.g. 1,2,3`)
    - `object -> nested property subform` (segmented toggle for `Mesh.Enclosure`)
  - Adds reusable inset `ContextFrame` blocks for conditional detail sections (`R-OSSE`, `Morph`, `GCurve`, `Rollback`, `Enclosure`).
  - `Throat.Profile` mode pages now render with clean headers (`OS-SE`, `Circular Arc`); `R-OSSE` avoids an extra nested mode-frame and shows only one inset details frame.
  - Uses centralized placeholder/tooltip hints from `ui/hints.py` to keep field hints short and consistent.
  - Uses two side-by-side columns (`Geometry | Mesh`) with dedicated scroll areas.
  - Horizontal scrollbars are disabled in both PROJECT columns.
  - Mesh Core uses a single aligned control column (selection rows and numeric/text rows share the same left control anchor).
  - Geometry order: `Basics -> Throat Profile -> Morph -> GCurve -> Rollback`.
  - Mesh order: `Core -> Enclosure`.
  - Supports unset semantics without per-field `Set` toggles and serializes to `param_states`.
- Integration: `app/gui.py`
  - PROJECT page now emits draft payload from form (`fixed_params`, `limits`, `param_states`).
  - Compatibility actions drive progressive disclosure (show/hide).
  - Project creation is blocked only on `fatal`; `warn`/`incomplete` remain creatable.

## Storage
- `ProjectConstraints` now persists `param_states` (`app/models.py`).
- `create_project` and compatibility preview flow preserve and evaluate `param_states`.

## Notes
- Theme polish:
  - generic inner `QWidget` backgrounds are transparent to avoid dark overlay artifacts in nested forms.
  - `ContextFrame` uses a subtle inset tone + border (no heavy full-block fill).
- PROJECT page no longer renders a dedicated compatibility panel and no longer includes `Back to Dashboard` / `Show details` actions.
- PROJECT summary right card now uses a compact validation teaser (`summary_issue_hint`) aligned to the Batch summary style.
- Source fields (`Source.*`) and `OSSE` object block are intentionally hidden from PROJECT UI to avoid duplication/conflicts.
- `Throat.Profile = 2 (R-OSSE)` is treated as UI mode selector; it is kept in `param_states` for UI/rules evaluation and omitted from rendered fixed CFG key map.
- `GCurve.Type` uses explicit UI modes: `no GCurve` (`unset`), `Superellipse` (`1`), `Superformula` (`2`).
- TODO verification hook:
  - Confirm final production mapping strategy for R-OSSE mode against ATH export behavior (UI mode value vs. pure object-block mapping).

## Batch UI Companion

The Batch page is now implemented as a companion to the PROJECT form design.

- Detailed spec and implementation map: `docs/BATCH_UI.md`
- Reused style primitives:
  - `ProjectSummaryPanel`
  - `ProjectActionBar`
  - severity pill semantics (`ok|warn|fatal`)
- Batch-specific UX:
  - per-parameter base value + sweep toggle (start/end/steps)
  - export presets + structured advanced graph cards (no free-text table editing)
  - preview placeholder panel with `show preview`/`update preview` button hook
  - SQL-history based ETA estimate in summary

## Compatibility UX Policy
- Strict separation:
  - rule truth from `CompatibilityService`
  - UI interaction blocking from `ui/compat_ui_adapter.py`
- Blocked segmented options are rendered in disabled/dark style and emit `blocked_interaction` on click.
- Clicking a blocked option flashes the primary cause field (controller keys prioritized).
- Project creation policy:
  - `fatal` blocks create
  - `incomplete` does not block create
- Batch policy differs:
  - save allowed on `incomplete`
  - run blocked on `incomplete` and `fatal`
  - hidden-value reconcile + payload sanitize pass prevents transient `batch_param_not_visible` conflicts

## Dashboard Redesign Preflight (2026-02-25)
- Merge prerequisite for the redesign task was checked first:
  - current branch: `wut-batcher/rebuild`
  - merge command: `git merge --no-ff origin/wut-batcher/rebuild`
  - result: already up to date (no content merge delta)
- Audit findings for "Project page" target:
  - target view is `DashboardPage` in `app/gui.py` (project-open dashboard), not `ProjectPage`.
  - current top-left `DASHBOARD` title and bottom action/export bars live in `DashboardPage`.
  - existing action wiring that must remain unchanged:
    - `new_batch_btn -> request_new_batch`
    - `edit_batch_btn -> request_edit_batch`
    - `clone_batch_btn -> request_clone_batch`
    - `export_btn -> request_open_export_dialog`
    - `manage_runs_btn -> request_manage_runs`
    - `cleanup_testdata_btn -> request_cleanup_testdata`
    - `settings_btn -> request_settings`
- Style-system reuse baseline:
  - `ProjectSummaryPanel`, `SummaryTitle`, `SummaryMeta`, `SummaryText`, `SummaryChip`, `BatchPrimaryButton`, `BatchSecondaryButton`, `BatchGhostButton` already exist in `ui/theme.py` and will be reused.
- Baseline smoke before redesign edits:
  - app startup (offscreen) and main window creation succeeds on this branch baseline.

## Dashboard Layout Refresh (Phase 1)
- `DashboardPage` was updated to the new top-row shell without changing service behavior:
  - removed the large `DASHBOARD` headline.
  - added a single top row under global chrome:
    - left: `Project Constraints` panel (`2/3` layout weight)
    - right: `Actions` panel (`1/3` layout weight)
- Actions are now grouped in two internal columns:
  - `Batch`: `New`, `Edit`, `Clone`, `Manage`
  - `Export`: `Export`
- Action wiring stayed unchanged:
  - `New -> request_new_batch`
  - `Edit -> request_edit_batch`
  - `Clone -> request_clone_batch`
  - `Manage -> request_manage_runs`
  - `Export -> request_open_export_dialog`
- Legacy bottom action/export bars were removed, and the batches list now expands into freed vertical space.
- Cleanup action is kept as a hidden compatibility control (`request_cleanup_testdata`) and is no longer shown in the default Project dashboard UI.
