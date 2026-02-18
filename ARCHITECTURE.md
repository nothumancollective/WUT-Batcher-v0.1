# WUT Batcher Architecture

Date: 2026-02-12
Branch: `wut-batcher/rebuild`

## Scope and Truth Sources
- Primary truth: user specification in this rebuild track.
- Secondary truth: current repository code.
- Tertiary truth: backup/recovery docs.

## Core Domain Model
- `Project`
  - immutable constraints snapshot after project creation
  - metadata: `project_id`, `project_name`, timestamps
- `Batch`
  - base variable params, sweep definitions, `sweep_mode` (`single|combined`)
  - sim/export settings (batch-constant)
- `Version`
  - deterministic resolved parameter snapshot
  - project-wide unique `version_id`
  - status, durations, artifact/log paths, ATH dimensions

## Storage Layout
```
<library>/
  global.sqlite
  <project_id>/
    project.json
    batches/<batch_id>/batch.json
    versions/<version_id>/
      cfg/input.cfg
      abec/Project.abec
      ath_work/
      exports/
      logs/
      version.json
    dataset/
      project.sqlite
      schema.json
    tables/
      project_versions.csv
    _logs/
```

## SQL-First Dataset Design
Primary tidy dataset storage is SQLite (not CSV/Parquet).

- Project DB: `<library>/<project_id>/dataset/project.sqlite`
- Global DB: `<library>/global.sqlite`
- Write strategy: project-first + global mirror write; global failures are queued in project DB (`replication_queue`) for retry.

### Required Tables (MVP)
- `projects`
  - `project_id`, `project_name`, `constraints_snapshot`, `created_at`, `updated_at`
- `batches`
  - `project_id`, `batch_id`, `batch_name`, `sweep_definitions`, `sweep_mode`, `sim_export_params`, `created_at`
- `versions`
  - `version_id`, `project_id`, `project_name`, `batch_id`, `batch_name`
  - `resolved_parameters_snapshot`, `version_config_hash`, `status`, `duration_seconds`
  - `ath_length_mm`, `ath_width_mm`, `ath_height_mm`
  - `tool_versions`, `created_at`, `finished_at`
- `runs`
  - `run_id`, `project_id`, `batch_id`, `started_at`, `finished_at`, `status`
  - `git_commit`, `app_version`, `settings_hash`, `error_summary`, `pinned`, `tag`
- `run_versions`
  - `run_id`, `version_id`, `project_id`, `batch_id`, `status`, `duration_seconds`, `created_at`, `finished_at`, `error_summary`
- `version_params`
  - `version_id`, `project_id`, `batch_id`, `param_name`, `value`, `unit`, `is_set`, `created_at`
  - `is_set=0` means parameter explicitly unset (must be omitted in CFG regeneration)
- `ath_dimensions`
  - `run_id`, `version_id`, `project_id`, `batch_id`, `length_mm`, `width_mm`, `height_mm`, `raw_line`, `source_file`, `created_at`
- `graphs`
  - `graph_id`, `project_id`, `batch_id`, `version_id`, `run_id`
  - `graph_type`, `graph_kind`, `variant`, `x_name`, `y_name`, `x_axis`, `y_axis`, `x_unit`, `y_unit`
  - `source_file`, `export_meta`, `meta_json`, `created_at`
- `graph_series`
  - `series_id`, `graph_id`, `series_kind`, `angle_deg`, `label`, `meta_json`, `created_at`
- `graph_points`
  - `series_id`, `point_index`, `x_value`, `y_value`, `y_imag`

Additional operational table:
- `replication_queue` for pending global-sync retries.

## Data Flow
1. UI (PySide6) collects input and calls service methods only (`OrchestratorService`).
2. Services call resolver + orchestrators:
   - `create_project()`
   - `create_batch()`
   - `resolve_versions()`
   - `run_batch()`
   - `export_version()`
3. Orchestrators call:
   - storage (`ProjectRepository`)
   - compatibility/resolve (`version_resolver`, `compat_engine`)
   - runners (`AthRunner`, `AkabakRunner`, `VacsRunner`)
   - SQL dataset sink (`SqlDatasetStore` via `TidyDatasetWriter`)
4. SQL writes happen to project DB and mirrored to global DB.
5. UI receives summaries/status only (no core logic in widgets).
6. Pending global mirror failures can be replayed via service/CLI sync (`sync_global_db` / `dataset sync-global`).

## Resolver and Validation
- Central resolver: `app/version_resolver.py`
  - deterministic expansion for `single` and `combined`
  - compatibility blocking (project/batch/version)
  - explicit `unset_parameters` list
- CFG rendering supports explicit omission:
  - `render_cfg_text(..., omit_keys=...)` removes unset keys from generated CFG.

## Runtime Pipeline
- Stage orchestration: `app/runtime_orchestrator.py`
  - plan/materialize versions
  - create run record (`runs`) and per-version run status (`run_versions`)
  - render CFG per version
  - optional deterministic `dry_run` mode (no external tool invocation)
  - ATH stage
  - AKABAK stage
  - VACS stage
  - VACS TXT parsing into SQL `graphs` + `graph_series` + `graph_points` (all tied to `run_id`)
  - status/duration updates in SQL
  - ATH dimension ingestion in SQL (`ath_dimensions` tied to `run_id`)

VACS TXT ingestion details:
- parser module: `app/vacs_txt_parser.py`
- supports key/value metadata + explicit `Data`/`Data_End` sections
- supports delimiter-based exports (`;`, tab, `|`) and locale decimals (`90,5`)
- supports series markers (`Series=...`) and derives `angle_deg` for polar-style exports
- supports optional complex point format (`x y y_imag`) with deterministic numeric parsing
- writes graph metadata (`graphs`), per-series metadata (`graph_series`) and tidy points (`graph_points`)
- if VACS stage succeeds but no TXT files are found or parse errors occur, version is marked `vacs_failed`

## Cleanup Policy (Per-Version Runtime Artifacts)
Implemented in `app/safe_cleanup.py`, invoked from runtime pipeline after successful integration.

Rules:
- delete target must be an absolute resolved directory
- delete target must be inside allowlisted root (`<project>/versions`)
- target cannot equal allowlist root
- target cannot be root-like/protected path
- target cannot match deny-list entries (project root/library root/versions root)
- if any guard fails: deletion is refused and reason is recorded

Scope of deletion:
- version-local runtime CFG file:
  - `<project>/versions/<version_id>/cfg/<runtime_cfg>.cfg`
- version-local ATH export subfolder:
  - `<ath_export_root>/<runtime_cfg_stem>`
- never global ATH folders, library root, or broad parent directories
- dry-run support:
  - guarded cleanup APIs run with `perform_delete=False`
  - runtime dry-run uses this mode to validate cleanup policy deterministically

## Export Regeneration Logic (Dashboard Export)
Implemented in `OrchestratorService.export_version()`.

Inputs:
- `project_id`, `batch_id`, `version_id`, `export_stl`, `export_abec`

Reconstruction:
- load parameter states from SQL (`version_params`)
- build `set_params` (`is_set=1`) and `unset_params` (`is_set=0`)
- regenerate CFG from template:
  - write only `is_set=1` values
  - force omission for `is_set=0` via `omit_keys`
- ABEC export contract:
  - requires ATH executable and regeneration run
  - expects generated `.abec` artifact in export workspace
  - canonical export target remains `<project>/exports/<batch_id>/<version_id>/Project.abec`

Output path:
- `<project>/exports/<batch_id>/<version_id>/...`

STL note (open point):
- exact ATH STL directive is not yet verified in this repo snapshot
- hook is isolated behind `ATH_STL_EXPORT_DIRECTIVE` in `app/services.py`
- when constant is unset, implementation appends explicit TODO hook block to CFG for deterministic behavior
- TODO tracked in DEVLOG; once directive is verified, replace placeholder with real ATH option

## GUI Architecture (PySide6)
- Entry: `app/gui.py` (`python -m app gui`)
- Dark modern style via:
  - `ui/theme_tokens.py` (design-token source of truth: colors/spacing/radii/typography)
  - `ui/theme.py` (Fusion style + dark palette + targeted QSS + Windows titlebar dark mode)
  - `ui/theme_preview.py` (`python -m app theme preview`)
- Startup flow:
  1. splash screen
  2. doctor checks in background phase
  3. open Project Manager window
- Windows/areas:
  - Project Manager (separate window)
  - Main Window with hidden stacked pages:
    - `DASHBOARD`
    - `PROJECT`
    - `BATCH`
    - `RUN`
  - Settings dialog (small)
  - About dialog (small)
- Status bar:
  - clickable status text -> detail popup
  - right clickable `WUT BATCHER` -> About dialog

## Theme and Windows Titlebar Strategy
- Global Qt style is set to `Fusion`.
- Theming layers:
  1. QPalette built from tokens (`build_palette`)
  2. focused QSS for controls where palette is not enough (`build_stylesheet`)
- Typography:
  - preferred app font: `Condor`
  - fallback chain: `Segoe UI`, `Arial`
- Windows dark titlebar:
  - Qt-way: set `QT_QPA_PLATFORM=windows:darkmode=1` before `QApplication`
  - Win32 fallback: `DwmSetWindowAttribute(DWMWA_USE_IMMERSIVE_DARK_MODE)` with robust attribute fallback (20 then 19)
  - no-op on non-Windows platforms

## Doctor and Contract Validation
- doctor checks are centralized in `app/doctor_service.py`
- startup splash (`app/gui.py`) passes configured tool paths from user settings
- executable checks require:
  - path exists
  - path is a file
  - path is executable
- write access checks include library/projects root write-test
- contract run behavior:
  - if ATH/AKABAK/VACS paths are not all executable, service run falls back to deterministic `dry_run`
  - dry-run still executes resolver, CFG generation, SQL writes, and cleanup guard evaluation
  - CLI smoke command `run-sample` performs post-run contract checks against SQL/runtime artifacts

## Open Points
1. Bind real ATH/AKABAK/VACS invocation contracts from VM (flags, startup semantics).
2. Replace STL TODO directive with verified ATH export option.
3. Expand dashboard batch editing policy (lock/clone behavior for successful batches).
