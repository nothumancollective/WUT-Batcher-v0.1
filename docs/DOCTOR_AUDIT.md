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
