# BATCH UI

## Scope
The Batch page is form-driven and aligned with the PROJECT visual style.
It replaces JSON textareas with structured controls for variable parameters, sweeps, exports, preview placeholder, validation hints, and ETA.

## Implemented UI Blocks
- Summary strip (`ProjectSummaryPanel` style)
  - strict 3-card layout with equal widths (left/estimate/validation)
  - left: batch draft context + dynamic-hide explanation + version/export/mode meta
  - center: visible parameter count, active sweeps, defined variables, ETA
  - right: short validation teaser text (top issue)
- Main body (two columns)
  - left (~2/3): variable parameter form (`ui/batch_parameter_form.py`)
  - right (~1/3): preview card + export card
- Action bar (`ProjectActionBar` style)
  - severity pill
  - save/run gating
  - compact issue counters (`errors · warnings · incomplete`)

Note:
- `CompatibilityPanel` still exists (`app/gui.py`) but is currently not shown in Batch (`setVisible(False)`).
- Validation feedback is surfaced via summary/action bar and field-level visuals.

## Variable Parameters + Sweeps
Widget: `ui/batch_parameter_form.py`

Per variable field:
- base value editor
- segmented `Sweep` button (`QPushButton`, checkable)
- inline sweep inputs when active: `start`, `end`, `steps`

Behavior:
- only one accordion card can be expanded at a time
- labels use display names only (no `(<key>)` suffix)
- `Core` is displayed as `Mesh`
- button-layout fields (segmented/object/bool controllers) are not sweepable
- active sweep:
  - highlights the sweep button with active style
  - locks/dims the base editor (`baseLockedBySweep=true`)
  - shows inline sweep inputs
- default on first sweep activation:
  - if base is set and `start/end` empty, both initialize from base value
  - `steps` defaults to `3`
- `R-OSSE` object details render as a single-column details block and are shown only when `Throat.Profile == R-OSSE`

Compatibility gating:
- hidden when key is not in `visible_keys`
- hidden for project-fixed keys (`fixed_params`, `limits`, and set `param_states`)
- disabled when key is in `locked_keys`
- sweep button disabled when key is not in `sweepable_keys`

Payload API:
- `selected_params_payload() -> Dict[str, Any]`
- `sweeps_payload() -> Dict[str, {start,end,steps,spacing}]`
- `set_from_batch(batch)` for edit/clone hydration

## Export Settings
Widget: `ui/batch_export_panel.py`

- Top rows:
  - `Simulation Mode` (`Free Standing`, `Infinite Baffle`)
  - `Sweep Mode` (`single`, `combined`)
  - `Freq Start [Hz]`, `Freq End [Hz]`, `Points` (integer-only)
  - `Mesh Freq [Hz]` (optional integer-only)
- Presets:
  - segmented graph buttons: `SPL`, `Impedance`, `Polar`
  - no surrounding groupbox/title container
- Advanced:
  - compact `Advanced` button (no inline block)
  - opens a structured dialog with cards (no JSON/free-text editing)
  - cards:
    - `SPL` card (`Activate`, `Variant`, `Format`)
    - `Impedance` card (`Activate`, `Variant`, `Format`)
    - up to 3 `Polar` cards (`Activate Polar`, `Polars Name`, map angle range, distance, offset, inclination)
  - editing advanced cards deactivates touched presets
  - duplicate `Polars Name` values across active cards emit fatal issue `export_duplicate_polar_name`
- Global export settings:
  - `simulation_mode`
  - `sweep_mode`
  - frequency range (`freq_start_hz`, `freq_end_hz`, `num_points`)
  - optional `mesh_frequency`

Payload API:
- `sim_export_params_payload() -> Dict[str, Any]`
- compatible with `SimExportSettings.from_dict(...)`

## Preview Placeholder
Widget: `ui/batch_preview_placeholder.py`

- title: `Preview (.stl)`
- text: coming-soon placeholder
- small segmented button, right-bottom anchored:
  - first click label: `show preview`
  - subsequent label: `update preview`
- no renderer integration yet (future STL viewport hook)

## Validation and UI Risk Layer
Rule evaluation remains in `app/compatibility_service.py`.

UI adaptation is separate in `ui/compat_ui_adapter.py`:
- derives `compat_ui_state` from compatibility snapshots
- returns UI-only metadata such as:
  - `hidden_keys`
  - `blocked_options`
  - cause/helper mapping for blocked interactions

Field-level warning/error visuals are applied in Batch via:
- `MainWindow._on_batch_draft_changed(...)`
- `UiValidationEngine.evaluate(...)`
- `BatchPage.apply_ui_risks(...)` / `BatchParameterForm.apply_ui_risks(...)`

This adds warning/fatal/incomplete-aware field styling and keeps summary warning text in sync.

## Reconcile and Sanitization
Two protections are active for stale payload problems:

1. Hidden-field reconcile pass
- after applying compatibility, Batch payload is re-read
- if hidden rows removed stale values/sweeps, a guarded second validation pass runs
- avoids transient messages like:
  - `Batch parameter 'xy' is not visible for current project constraints`

2. Payload sanitization against current batch compatibility
- `MainWindow._sanitize_batch_payload_for_project_constraints(...)` prunes non-visible/non-sweepable/fixed keys
- sanitization uses the current batch compatibility snapshot (not only static project visibility)
- valid sweeps remain intact when currently visible+sweepable

## ETA Estimation
Service API: `OrchestratorService.estimate_batch_runtime(...)`

Data source:
- SQL history from successful `run_versions.duration_seconds`
- helper: `SqlDatasetStore.list_recent_success_durations(...)`

Estimator:
- `version_count_preview` from batch compatibility evaluation
- `median_seconds_per_version` from history
- `eta_seconds = median * version_count_preview`

UI:
- debounced recalculation on draft changes
- ETA shown in summary with tooltip (`median`, sample count)
- fallback: `ETA: unknown` if no usable history exists

## Sweep Validation Hardening
`CompatibilityService.evaluate_batch_definition(...)` no longer ignores invalid sweeps.

Behavior:
- invalid sweep entries produce `sweep_parse_failed` (`fatal`)
- `version_count_preview` is forced to `0`
- issue is surfaced in validation summary state

## Batch Action Policy
- Save: allowed when no `fatal` issues exist.
- Run: allowed only when no `fatal` and no `incomplete` issues exist.
- Incomplete issues remain visible as neutral guidance.

## Edit / Clone
Main window actions:
- `Edit Batch`: loads stored batch into the draft form
- `Clone Batch`: loads batch and sets draft name to `<name> Clone`

Both paths restore:
- selected/base values
- sweeps
- sweep mode
- export settings

## File Map
- `app/gui.py`
- `app/services.py`
- `app/compatibility_service.py`
- `app/sql_dataset_store.py`
- `app/ui_validation.py`
- `ui/compat_ui_adapter.py`
- `ui/batch_parameter_form.py`
- `ui/batch_export_panel.py`
- `ui/batch_preview_placeholder.py`
- `tests/test_batch_page_ui.py`
- `tests/test_gui_project_fixed_keys.py`
- `tests/test_compatibility_service_batch_sweep_validation.py`
- `tests/test_eta_estimator.py`

