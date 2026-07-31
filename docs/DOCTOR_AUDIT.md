# Doctor Audit

## Phase 0 Audit Findings (2026-03-01)

### Doctor Warning Catalog: Current Startup Payload

Normal GUI startup currently produces `overall_status=warn` with these warning checks in `logs/doctor_report.json`:

| Check | Message | Classification | Root Cause | Code |
| --- | --- | --- | --- | --- |
| `config_path` | `No config file path provided; defaults in use.` | False positive | GUI startup Doctor uses persisted `SettingsStore` (`~/.wut_batcher/config.json`), but `_run_doctor_for_splash()` calls `run_doctor_checks(..., config_path=None)` and makes the Doctor think no config source exists. | `app/gui.py:15591-15599`, `app/settings_store.py:19`, `app/settings_store.py:200` |
| `batch_results_root_exists` | `batch_results_root not configured in app_config.json.` | False positive for GUI startup | This is a legacy `app_config.json` field. The current GUI startup path does not source runtime settings from `app_config.json`, so missing legacy export-root config should not warn on a healthy GUI machine. | `app/doctor_service.py:429-444` |
| `ath_export_root_exists` | `ATH export root not configured in app_config.json.` | False positive for GUI startup | Same issue as `batch_results_root`: startup is reading GUI settings, not `app_config.json`, so the warning is not describing the live startup configuration. | `app/doctor_service.py:446-468` |
| `runner_dir` | `Runner directory missing: <repo>/Runner` | False positive / stale heuristic | The repo now uses the integrated Python runtime/orchestrator path. The Doctor still warns on a missing legacy `Runner/` folder even though current runtime code is present and used. | `app/doctor_service.py:182-197`, `app/doctor_service.py:480` |

Checks currently observed as valid on this machine:

- `Projects root_exists`: OK
- `Projects root_write`: OK
- `templates`: OK
- `ath_exe`: OK
- `akabak_exe`: OK
- `vacs_exe`: OK
- `zombies`: OK
- `doctor_report`: OK

### Startup Flicker Forensics: Initial Reproduction

Reproduction was captured with DEBUG-only instrumentation:

- env: `WUT_DEBUG_WINDOW_FLICKER=1`
- env: `WUT_DEBUG_WINDOW_FLICKER_EXIT_MS=3500`
- log: `%LOCALAPPDATA%\\WUTBatcher\\logs\\window_flicker_debug.jsonl`

Observed top-level startup windows:

- `QSplashScreen`
- `ProjectManagerWindow`

Observed flicker source from the trace:

- The splash itself is not the cause.
- During startup, `GuiController` eagerly constructs `MainWindow` before the splash is finished.
- `MainWindow` construction builds `DashboardPage`, `ProjectPage`, `BatchPage`, and `AnalysePage`.
- Several child widgets call `setVisible(False)` or `.hide()` before they are parented into layouts, so Windows briefly treats them as tiny standalone windows during startup.

Representative trace-backed offenders:

- `ui/helper_row.py:19` -> `self.setVisible(False)`
- `ui/helper_row.py:28` -> `self.icon_label.setVisible(False)`
- `ui/form_builder.py:357` -> `self._reset_btn.setVisible(False)`
- `ui/batch_parameter_form.py:1907` -> `row.sweep_popup.hide()`
- `app/gui.py:5335` -> `self._empty.setVisible(False)`
- `app/gui.py:7646-7662` -> hidden Batch/Analyzer controls created during `MainWindow` init
- `app/gui.py:8424`, `app/gui.py:8472`, `app/gui.py:8478`, `app/gui.py:8837` -> hidden Analyzer labels/badges created during `AnalysePage` init

Trace summary from the first capture:

- `61x` `HelperRow.hide_to_parent`
- `61x` `HelperRowIcon.hide_to_parent`
- `61x` `_SweepPopover.hide_to_parent`
- `12x` `AccordionHeaderResetButton.hide_to_parent`

Working hypothesis for the fix:

- Restore Doctor accuracy by making GUI startup checks use the authoritative GUI settings source and retiring the stale legacy `Runner/` warning.
- Stop startup flicker by preventing `MainWindow` construction from creating unparented hidden widgets during splash/startup, or by ensuring those widgets are parented before any visibility changes happen.

## Phase 1 Fixes Applied (2026-03-01)

### Doctor Warning Catalog: After Fix

Current GUI startup Doctor payload on this machine is now `overall_status=ok`.

| Check | Before | After | Fix Status | Code |
| --- | --- | --- | --- | --- |
| `config_path` | Warned that no config path was provided. | Reports `Loaded config from C:\\Users\\maximilianheinze\\.wut_batcher\\config.json`. | Fixed false positive. | `app/gui.py:15621-15633`, `app/doctor_service.py:394-417` |
| `batch_results_root_exists` | Warned about missing legacy `app_config.json` field. | Not included in GUI startup Doctor payload. | Fixed false positive for GUI startup by skipping non-authoritative legacy export-root checks in this context only. | `app/gui.py:15621-15633`, `app/doctor_service.py:439-455` |
| `ath_export_root_exists` | Warned about missing legacy `app_config.json` field. | Not included in GUI startup Doctor payload. | Fixed false positive for GUI startup by skipping non-authoritative legacy export-root checks in this context only. | `app/gui.py:15621-15633`, `app/doctor_service.py:457-481` |
| `runner_dir` | Warned when `Runner/` was absent. | Reports OK when integrated runtime exists at `app/runtime_orchestrator.py`. | Fixed stale heuristic. | `app/doctor_service.py:182-208` |

Notes:

- The GUI splash Doctor uses the persisted GUI settings file as its source of truth and skips legacy export-root checks that are not authoritative in this startup path.
- The former CLI difference described here was removed in Phase 2 below.

### Startup Flicker Forensics: After Fix

Fix applied:

- `GuiController` no longer constructs `MainWindow` during splash/startup.
- `MainWindow` is created lazily on first actual need (`open project` / `new project` / explicit `controller.main_window` access).
- Startup Doctor status is stored in the controller and applied to `MainWindow` when the window is created later, so the status/detail behavior is preserved.

Why this is safe:

- `ProjectManagerWindow` remains the startup landing window.
- No runner/analyzer/project logic changed; only the timing of `MainWindow` construction moved out of splash/startup.
- Existing UI tests that access `controller.main_window` still work because the public property now materializes the window on demand.

Post-fix trace with the same DEBUG instrumentation:

- env: `WUT_DEBUG_WINDOW_FLICKER=1`
- env: `WUT_DEBUG_WINDOW_FLICKER_EXIT_MS=3500`
- log: `%LOCALAPPDATA%\\WUTBatcher\\logs\\window_flicker_debug.jsonl`

Observed startup windows after fix:

- `show` / `hide`: `QSplashScreen`
- `show` / `hide`: `ProjectManagerWindow`
- No other top-level or temporarily top-level widgets were recorded during startup (`non_startup_windows = 0`).

## Validation Notes

Targeted automated checks run after the fix:

- `python -m pytest tests/test_doctor_service.py tests/test_gui_project_open_and_batch_nav_ui.py -q`
  - result: `8 passed`
- `python -m pytest tests/test_gui_analyzer_page_ui.py::AnalyzerPageUiTests::test_analyse_modebar_opens_analyzer_page tests/test_project_manager_ui.py -q`
  - result: `4 passed`

Manual / live diagnostics:

- Startup Doctor payload via `_run_doctor_for_splash(service)` on this machine now reports `overall_status=ok`.
- Instrumented live startup trace now records exactly `QSplashScreen` and `ProjectManagerWindow`, with no tiny transient windows during splash/startup.

Broader smoke note:

- The existing fake-toolchain stress test `tests/test_ui_e2e_stress_runs.py::UiE2EStressRunsTests::test_three_full_ui_runs_are_stable` still fails in the batch-run path with `Run failed for B001`.
- That failure reproduces both with lazy `MainWindow` startup and with an explicitly eager-created `MainWindow`, so it is not attributable to this Doctor/startup fix scope.

## Phase 2: One authoritative settings source (2026-07-31)

The CLI and GUI now call `run_settings_doctor_checks()` and therefore inspect
the same `SettingsStore` data used by the runtime. The legacy `AppConfig` path
is used only when a caller explicitly supplies global `--config`.

Behavioral contracts:

- Default settings: `%USERPROFILE%\.wut_batcher\config.json`.
- Default report: `%USERPROFILE%\.wut_batcher\logs\doctor_report.json`.
- Legacy runner and export-root checks are not emitted for modern settings.
- `--kill-zombies` remains explicit; a normal Doctor run never terminates a
  process.
- The writeability check creates and removes a small sentinel file. It does not
  alter projects, manifests or databases.

Final live check on the validation VM:

```powershell
python -m app doctor --report-path tmp\doctor_final_20260731.json
```

Result: `overall_status=ok`. Config, active Project Library, templates,
integrated runtime, ATH, AKABAK, VACS, process state and report output all
reported `ok`. No known simulation-tool processes were left running.

Regression coverage includes the settings wrapper, CLI default/legacy routing,
report destination and GUI use of the modern wrapper.
