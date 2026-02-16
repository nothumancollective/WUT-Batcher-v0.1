# BATCH UI

## Scope
The Batch page is now form-driven and aligned with the PROJECT page visual language.
It replaces JSON textareas with structured controls for variable parameters, sweeps, export settings, preview placeholder, and ETA.

## Implemented UI Blocks
- Summary panel (`ProjectSummaryPanel` style)
  - strict 3-way card layout (left/estimate/validation with equal width)
  - center card: visible variable parameter count + active sweep count + defined variable count
  - left card: version preview/export spec summary + dynamic-hide explanation
  - right card: short validation teaser text from top issue
  - ETA line with tooltip
- Main body (two columns)
  - left: variable parameter form (`ui/batch_parameter_form.py`) at ~2/3 width
  - right: STL preview placeholder (`ui/batch_preview_placeholder.py`) + export panel (`ui/batch_export_panel.py`) at ~1/3 width
- Compatibility panel (details + rule messages)
- Action bar (`ProjectActionBar` style) with save/run gating and severity pill

## Variable Parameters + Sweeps
Widget: `ui/batch_parameter_form.py`

Per variable field:
- base value input (`Optional[float]`)
- sweep toggle (`QPushButton`, segmented style)
- inline sweep details when enabled:
  - start (float)
  - end (float)
  - steps (int)
  - spacing placeholder (`linear`, disabled control for v1)

Behavior:
- active sweep locks and dims base value editor
- labels show only display label text (no `(<key>)` suffix)
- `Core` group is rendered as `Mesh`
- `R-OSSE` object details render as single-column rows and only when `Throat.Profile == R-OSSE`

Default behavior on sweep enable:
- if base value is set and start/end are empty: start=end=base
- steps defaults to `3`

Compatibility gating:
- hide keys not in `visible_keys`
- disable keys in `locked_keys`
- disable sweep toggle if key not in `sweepable_keys`
- hide project-fixed keys (`fixed_params` + `limits`) from batch editing

Payload API:
- `selected_params_payload() -> Dict[str, Optional[float]]`
- `sweeps_payload() -> Dict[str, {start,end,steps,spacing}]`
- `set_from_batch(batch)` for edit/clone draft loading

## Export Settings
Widget: `ui/batch_export_panel.py`

- Presets:
  - segmented preset buttons: `SPL`, `Impedance`, `Polar` (`Polar` currently disabled/coming soon)
- Advanced:
  - structured graph cards by graph kind (no free-text table editing)
  - graph-level variant/format controls
  - per-graph guide dialog with repo-verified static export defaults
- Global export settings:
  - `sweep_mode` (`single|combined`) moved into export panel
  - `mesh_frequency` optional numeric field persisted in `sim_export_settings`

Payload API:
- `sim_export_params_payload() -> Dict[str, Any]`
- output is compatible with `SimExportSettings.from_dict(...)`

## Preview Placeholder
Widget: `ui/batch_preview_placeholder.py`

- card title: `Preview (.stl)`
- message: `Coming soon`
- disabled controls (`Open`, `Refresh`) as integration hook for future viewer (VTK planned)

## ETA Estimation
Service API: `OrchestratorService.estimate_batch_runtime(...)`

Data source:
- SQL history from `run_versions.duration_seconds`
- helper: `SqlDatasetStore.list_recent_success_durations(...)`
- filter:
  - `runs.status = 'succeeded'`
  - `run_versions.status = 'success'`
  - non-null durations only

Estimator:
- `version_count_preview` from compatibility batch evaluation
- `median_seconds_per_version` from history
- `eta_seconds = median * version_count_preview`
- additional basis stats: sample count, p25, p75

UI integration:
- debounced draft validation (`MainWindow`)
- ETA shown in Batch summary with tooltip (sample count + median)
- fallback: `ETA: unknown` when no history exists

## Validation Hardening
`CompatibilityService.evaluate_batch_definition(...)` no longer silently ignores invalid sweep payloads.

Behavior:
- invalid sweep entries produce issue `sweep_parse_failed` (severity `fatal`)
- version preview is forced to `0` in that case
- issue is shown in compatibility details and summary state

## Rule/UI Separation
Compatibility rules remain in `app/compatibility_service.py` unchanged in meaning.

UI blocking is derived separately in `ui/compat_ui_adapter.py`:
- input: compatibility snapshot (`visible_keys`, `locked_keys`, `sweepable_keys`, `issues`)
- output: `compat_ui_state` with:
  - `hidden_keys`
  - `blocked_options` (segment option-level blocking metadata)
  - `cause_map` and helper text for blocked interactions

The adapter runs hypothetical checks through existing service calls only and does not mutate ATH rules.

### Reconcile Pass (`batch_param_not_visible` fix)
- `MainWindow._on_batch_draft_changed(...)` applies compatibility, then immediately re-reads batch payload.
- if hidden keys caused stale values/sweeps to be removed, a guarded second validation pass runs.
- this removes transient resolver errors like:
  - `Batch parameter 'xy' is not visible for current project constraints`

### Batch Action Policy
- Save: allowed when no `fatal` issues exist.
- Run: blocked when `fatal` or `incomplete` issues exist.
- Incomplete issues (missing required values) remain visible as neutral/incomplete guidance.

## Edit / Clone
Main window actions are now wired:
- `Edit Batch`: loads stored batch into Batch draft UI
- `Clone Batch`: loads batch and sets cloned name (`<name> Clone`)

Both paths populate:
- base values
- sweeps
- sweep mode
- export settings

## File Map
- `app/gui.py`
- `app/services.py`
- `app/compatibility_service.py`
- `app/sql_dataset_store.py`
- `ui/batch_parameter_form.py`
- `ui/batch_export_panel.py`
- `ui/batch_preview_placeholder.py`
- `tests/test_batch_page_ui.py`
- `tests/test_compatibility_service_batch_sweep_validation.py`
- `tests/test_eta_estimator.py`
