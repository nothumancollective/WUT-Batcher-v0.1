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
- sweep coverage:
  - controller rows are sweep-capable: `Throat.Profile`, `GCurve.Type`, `Morph.TargetShape`
  - mesh rows are intentionally not sweep-capable for now (`Mesh.*`)
- default on first sweep activation:
  - if base is set and `start/end` empty, both initialize from base value
  - `steps` defaults to `3`
- `R-OSSE` object details render as a single-column details block and are shown only when `Throat.Profile == R-OSSE`

Compatibility gating:
- hidden when key is not in `visible_keys`
- hidden for project-fixed keys (`fixed_params`, `limits`, and set `param_states`)
- disabled when key is in `locked_keys`
- sweep button disabled when key is not in `sweepable_keys`
- enum sweep safety:
  - enum sweeps only emit payload when `start/end` match allowed enum values
  - invalid enum ranges stay in UI but are withheld from payload until corrected

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
  - opens a structured, frameless dialog (Project-Manager style `X` close) with scrolling
  - cards:
    - `SPL` card (`Activate`, format fixed to `txt`)
    - `Impedance` card (`Activate`, format fixed to `txt`)
    - up to 3 `Polar` cards (`Activate Polar`, `Polars Name`, map angle range, distance, offset, inclination, norm angle)
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

## STL Preview
Widgets / flow:
- `ui/batch_preview_placeholder.py` (panel + loader + message states)
- `ui/stl_preview_widget.py` (Qt3D renderer + STL parser fallback)
- `app/services.py::generate_preview_stl(...)` (single source of truth pipeline)
- `app/gui.py` (`_BatchPreviewWorker` in background thread + cancellation)
- model notes: `docs/PREVIEW_MINIMAL_COMPLETION_MODEL.md`

UI behavior:
- title is `Preview`
- preview is always enabled on the Batch page (no toggle)
- preview updates are triggered automatically after batch draft changes (debounced)
- loading state:
  - in-canvas indeterminate loader while cfg write + ATH run + STL copy + load
- failure state:
  - unobtrusive inline error text in preview panel (no modal)
- no footer controls in preview panel (canvas area maximized)

Render behavior:
- transparent background
- light gray/white glossy material
- basic orbit rotate + zoom
- STL loading supports binary and ASCII STL parsing
- if Qt3D is unavailable, a software fallback renderer is used (still interactive)

Hard paths:
- preview cfg directory: `C:\\Tools\\ATH`
- preview cfg file name: `preview_current.cfg`
- ATH export root: `C:\\Horns`

Cache:
- dedicated cache dir: `%LOCALAPPDATA%\\WUTBatcher\\preview_cache\\`
- file naming: `horn_preview_<timestamp>_<cfgHash>.stl`
- retention: keep last 10 preview STL files
- startup cleanup: remove stale files older than 7 days (cache dir only)

Project Manager thumbnail:
- first successful `Run` click on Batch page captures current preview canvas as:
  - `<project_dir>/_meta/project_preview.png`
- project tile rendering prefers this image over placeholder art
- preview thumbnail is write-once by default (existing file is preserved)

Debug artifacts:
- `%LOCALAPPDATA%\\WUTBatcher\\preview_cache\\logs\\preview_<run>.stdout.log`
- `%LOCALAPPDATA%\\WUTBatcher\\preview_cache\\logs\\preview_<run>.stderr.log`
- `%LOCALAPPDATA%\\WUTBatcher\\preview_cache\\logs\\preview_<run>.runner.log`

Preview robustness:
- preview generation uses resolver output when available
- resolver input for preview ignores unset (`None`) batch values, so transient hidden fields do not poison resolver prechecks
- if resolver returns no versions, preview falls back to seeded ATH parameters with iterative minimal completion:
  - adds only missing required fields from resolver issues (catalog/default based)
  - keeps user-entered values untouched
  - recomputes until stable (or max rounds)
- resolver issues `batch_param_not_visible` are parsed and hidden keys are ignored for preview generation (`ignored_hidden_keys` in preview result payload)
- internal UI selector `Throat.Profile = 2` (R-OSSE mode) is normalized before ATH run:
  - removed from final cfg
  - `R-OSSE` object is auto-completed with safe defaults when needed
- `Mesh.Enclosure` object completion:
  - if enclosure is set without `Plan` and without `Depth`, preview seed injects `Depth` for stable generation
  - list fields (`Spacing`, `FrontResolution`, `BackResolution`) are normalized to up to 4 values
  - plan mode is intentionally downgraded for preview STL generation when no in-CFG plan script block exists
  - preview payload reports this downgrade in `preview_notes`
- policy layer still reports missing enclosure requirements for explicit run decisions
- mesh interface list normalization is applied for preview generation:
  - `Mesh.InterfaceOffset` / `Mesh.InterfaceDraw` are normalized to list form
  - lengths are aligned to `Mesh.SubdomainSlices` when both are present
- runtime `MeshCmd` for preview uses a gmsh wrapper command to prevent ATH hangs on bare gmsh invocation.

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

Policy payload now also carries grouped missing requirements:
- `policy_missing_by_block` (`profile|mesh|gcurve|morph|enclosure`)

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

## Troubleshooting
- If the app crashes directly at startup with a theme token error like:
  - `KeyError: 'warning_text'`
- use the fixed theme mapping in `ui/theme.py` (`warning_text_muted`), then restart via:
  - `python -m app gui`

## Batch Action Policy
- Save: allowed when no `fatal` issues exist.
- Run button is interactable once batch name is set.
- Run execution still goes through validation and can be blocked by fatal issues.
- Incomplete/warning guidance remains visible in summary/fields.
- Save/Run buttons remain clickable (with name set) so validation blockers are communicated explicitly via status/dialog/tooltips.

## Warning Summary UX
- Top-right validation card shows sorted issue snippets (up to 3 lines) instead of a single generic counter.
- Hover tooltip on that card shows the extended sorted list.
- Field-level warning hover helpers are applied in batch form (base control + sweep button).

## Sweepability Fallback
- In baseline drafts some rulesets may return empty `sweepable_keys`.
- Batch UI now applies a deterministic fallback for visible numeric scalar keys (`float|int|expr`), excluding runner-locked and button-layout controls.
- This prevents false "all sweep toggles disabled" states while preserving compatibility gating.

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
- `ui/stl_preview_widget.py`
- `tests/test_batch_page_ui.py`
- `tests/test_gui_project_fixed_keys.py`
- `tests/test_compatibility_service_batch_sweep_validation.py`
- `tests/test_eta_estimator.py`

## Manual Preview Checklist
1. Open a project and go to Batch page.
2. Verify loader appears while preview is generated automatically.
4. Verify mesh appears and can be rotated (drag/orbit) and zoomed.
5. Verify background stays transparent and mesh is bright/neutral.
6. Change any visible batch parameter and verify preview regenerates automatically.
7. Trigger an ATH/config error and verify inline error text (no modal) appears.
8. Click `Run` once and verify Project Manager tile gets a preview thumbnail.
9. Check `%LOCALAPPDATA%\\WUTBatcher\\preview_cache\\` and verify:
   - unique file naming
   - only latest 10 STL files retained.

