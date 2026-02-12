# DEVLOG

## 2026-02-12
### Done
- Rebuild branch checked (`wut-batcher/rebuild` already active).
- Repository baseline analyzed:
  - Existing sweep planner, CFG renderer, compatibility engine, dataset importer inspected.
  - Current tests executed successfully (`13/13` passing).
- `ARCHITECTURE.md` created with Ist/Soll analysis and backlog.

### Next
- Introduce explicit domain-level `VersionSpec` and central resolver with `single|combined` semantics and `unset` handling.
- Add blocking compatibility validation during resolution.
- Start implementing target project storage layout and deterministic project-wide version IDs.

### Risks / Open Points
- Current snapshot references Runner automation in docs, but no `Runner/` directory exists in repo.
- Real ATH/AKABAK/VACS executable paths and invocation contracts are not yet validated in this workspace.

### Update 1
#### Done
- Added explicit execution-domain models:
  - `VersionSpec`, `ResolutionIssue`, `ResolveVersionsResult` in `app/models.py`.
- Implemented central resolver `app/version_resolver.py`:
  - deterministic version expansion (`single` and `combined`)
  - `unset_parameters` tracking for omitted ATH fields
  - project/batch/version compatibility blocking via `compat_engine`
  - deterministic project-wide version ID allocation with existing-ID carry-forward.
- Added machine-readable compatibility registry support in `app/compat_rules.py`.
- Implemented new target storage layer in `app/project_storage.py`:
  - `projects/<project_id>/...` structure
  - immutable project constraint enforcement
  - batch persistence and version materialization with placeholders/log paths.
- Implemented tidy dataset writer in `app/tidy_dataset.py`:
  - tidy CSV outputs for version parameters, measurements, ATH dimensions
  - schema output
  - optional parquet materialization when `pyarrow` is available
  - project table export (`tables/project_versions.csv`).
- Added high-level planner orchestration `app/batch_orchestrator.py`.
- Extended CLI with `plan materialize` command.
- Added tests:
  - `tests/test_version_resolver.py`
  - `tests/test_project_storage_and_tidy.py`
  - `tests/test_runners.py`
  - `tests/test_compat_rules.py`
- Full suite green: `21/21` tests passing.

#### Next
- Wire ATH runner into the new orchestration path as first concrete runtime step.
- Add ATH stdout dimension extraction into tidy writer flow.
- Add AKABAK/VACS runner staging hooks after ATH step.

#### Risks / Open Points
- Real ATH/AKABAK/VACS invocation flags are not validated yet in this repo snapshot.
- Runner wrappers are subprocess-safe but currently require explicit executable/path contracts from environment.

### Update 2
#### Done
- Added runtime stage orchestrator `app/runtime_orchestrator.py`.
  - Executes staged flow per version (`ATH -> AKABAK -> VACS`) with per-stage status persistence.
  - Renders CFG per version and parses ATH dimensions into tidy dataset rows.
- Extended CLI with `run pipeline` command for staged execution.
- Added runtime test `tests/test_runtime_orchestrator.py` (simulated ATH executable), suite now `22/22` green.

#### Next
- Bind real executable/automation contracts from the VM environment into `run pipeline` invocation.
- Integrate TXT export normalization from runtime stage into tidy measurement writer end-to-end.

#### Risks / Open Points
- AKABAK/VACS stages are currently subprocess wrappers and still need concrete UI-automation or CLI bridge contracts.
- Without real tool paths and flags, runtime behavior beyond ATH simulation remains environment-dependent.

### Update 3 (SQL + GUI Addendum)
#### Done
- Data storage switched to SQL-first architecture:
  - Added `app/sql_dataset_store.py` and made `app/tidy_dataset.py` a SQL-backed alias.
  - Implemented project DB + global DB dual-write with retry queue (`replication_queue`).
  - Implemented required MVP tables:
    - `projects`, `batches`, `versions`, `version_params`, `ath_dimensions`, `graphs`, `graph_points`.
  - Added explicit unset persistence (`version_params.is_set = 0`) and CFG reconstruction helpers.
- Orchestrator integration:
  - `app/batch_orchestrator.py` now registers project/batch/version data into SQL and writes table export from SQL.
  - `app/runtime_orchestrator.py` now updates version status/duration in SQL and writes ATH dimensions directly per version.
- Safe cleanup implementation:
  - Added `app/safe_cleanup.py` with guarded delete rules.
  - Runtime now attempts cleanup only for per-version `ath_work` folders under strict allowlist/deny-path checks.
- Export regeneration from SQL:
  - Added `app/services.py` with core methods:
    - `create_project`, `create_batch`, `resolve_versions`, `run_batch`, `export_version`.
  - Dashboard export path uses SQL parameter states and omits unset params from CFG via `omit_keys`.
- GUI skeleton (PySide6 orchestrator-only):
  - Added `app/gui.py` with splash -> doctor checks -> Project Manager flow.
  - Added main window with hidden stacked work areas (`DASHBOARD`, `PROJECT`, `BATCH`, `RUN`).
  - Added statusbar detail click behavior and About dialog trigger (`WUT BATCHER`).
  - Added Settings dialog backed by persistent config (`app/settings_store.py`).
  - Added CLI command `python -m app gui`.
- CFG renderer extension:
  - Added `omit_keys` support in `app/cfg_renderer.py` for exact unset omission.
- Tests added/updated:
  - `tests/test_sql_dataset_store.py`
  - `tests/test_safe_cleanup.py`
  - `tests/test_service_export.py`
  - Updated SQL expectations in existing storage/runtime tests.
- Full suite status: `28/28` passing.

#### Next
- Bind real VM ATH/AKABAK/VACS invocation details in runtime and GUI settings defaults.
- Integrate real VACS TXT parsing into `graphs` + `graph_points` write path during run.
- Replace STL CFG TODO hook with verified ATH STL export directive.

#### Risks / Open Points
- Exact ATH STL export directive is still unknown; export currently inserts explicit TODO block in CFG.
- AKABAK/VACS runtime stages are subprocess-capable but still depend on concrete environment contracts for production runs.

### Update 4 (UI Theme Addendum)
#### Done
- Added centralized theme token system:
  - `ui/theme_tokens.py` as source of truth for near-black palette, spacing, radii, typography.
- Added robust Qt theming layer:
  - `ui/theme.py` with `build_palette()`, `build_stylesheet()`, `apply_theme()`.
  - Global style uses `Fusion` + dark `QPalette` + targeted QSS.
- Implemented Windows dark titlebar handling:
  - Qt-way env setup before app start (`QT_QPA_PLATFORM=windows:darkmode=1`).
  - Win32 fallback via `DwmSetWindowAttribute` (attribute 20 then 19).
  - Function: `apply_windows_dark_titlebar(window)`; non-Windows no-op.
- Added theme preview window:
  - `ui/theme_preview.py`
  - launch via CLI: `python -m app theme preview`.
- Integrated new theme stack into GUI:
  - `app/gui.py` now uses `apply_theme()` and titlebar dark-mode application for splash, project manager, and main window.
  - Removed direct styling dependency on legacy-only theme implementation.
- Added backward-compat wrapper:
  - `app/gui_theme.py` now proxies new theme API.

#### Validation
- CLI routes:
  - `python -m app --help` includes `theme`
  - `python -m app theme --help` includes `preview`
- Test suite remains green: `28/28`.

#### Risks / Open Points
- Final visual polish (exact spacing/rhythm, panel density) still requires iterative tuning against real screen captures.
- Win32 titlebar behavior can vary by OS build; fallback path is implemented, but should be visually verified on target VM build.

### Update 5 (Continue Pass)
#### Done
- Priority A: SQL dual-write hardened with atomic plan-bundle operation.
  - Added `upsert_plan_bundle` operation in `app/sql_dataset_store.py`.
  - Added `write_plan_bundle(project,batch,versions)` to commit project+batch+versions in one transaction per DB target.
  - `app/batch_orchestrator.py` now uses bundle-write instead of three separate writes.
  - Added global retry sync service API `OrchestratorService.sync_global_db()`.
  - Added CLI command `dataset sync-global` for replaying pending mirror writes.
- Priority B: UI skeleton polish.
  - Applied dark titlebar handling to Settings/About dialogs on show.
  - Project Manager now opens maximized for fullscreen-like workflow.
- Priority C: run-loop cleanup guard hardening.
  - Added `expected_dir_name` guard to `guarded_delete_tree()`.
  - Runtime cleanup now enforces target dir name `ath_work`.

#### Tests / Validation
- Unit tests expanded and green: `31/31`.
  - Added/extended tests for bundle-write, sync summary, and cleanup dir-name guard.
- Smoke test (service/DB without GUI):
  - created sample project + batch
  - verified `project.sqlite`, `global.sqlite`, batch/version artifacts
  - global sync replay ran clean (`processed=0`, `failed=0`).
- GUI smoke note:
  - not executable in current env because `PySide6` is missing (`ModuleNotFoundError`).

#### Open Point
- ATH STL export flag still unknown; TODO hook remains intentionally in code until verified.

### Update 6 (Next Pass: GUI Runtime + VACS SQL + Dry-Run Contracts)
#### Done
- Environment/runtime baseline completed.
  - Verified Python runtime source on VM (`Python312-arm64`, no repo venv, no conda).
  - Added dependency manifest: `requirements.txt` with `PySide6`.
  - Added setup guide: `SETUP.md` (venv, install, app run, tests).
  - GUI smoke validated:
    - `python -c "import PySide6; print(PySide6.__version__)"`
    - GUI controller/theme/titlebar probe completed without crash.
- VACS TXT export integration into SQL implemented.
  - Added parser: `app/vacs_txt_parser.py`.
  - Runtime now executes VACS in version-local exports dir and ingests TXT exports into:
    - `graphs`
    - `graph_points`
  - Parse failures/no export files after successful VACS process now mark version `vacs_failed` to prevent false-success runs.
  - Added fixtures and parser tests:
    - `tests/fixtures/vacs/result_v001spl.txt`
    - `tests/fixtures/vacs/result_v001imp.txt`
    - `tests/test_vacs_txt_parser.py`
  - Added runtime integration test for VACS->SQL write path.
- End-to-end contract hardening (without tool dependency) implemented.
  - Added deterministic runtime `dry_run` mode (`run_batch_pipeline(..., dry_run=True)`).
  - Service `run_batch()` now auto-falls back to dry-run when ATH/AKABAK/VACS executables are not all available.
  - Dry-run still executes resolver/materialization, CFG generation, SQL status writes, and cleanup guard evaluation.
  - Cleanup guard extended with `perform_delete=False` for safe dry-run evaluation.
- Doctor checks upgraded for executable validation.
  - `run_doctor_checks(..., tool_paths=...)` supports explicit settings-driven executable paths.
  - Executable check now enforces existence + file + executable.
  - Splash doctor now runs against configured settings paths.
  - Added doctor unit tests.

#### Validation
- Focused tests:
  - parser/runtime/cleanup/service/doctor: `15/15` passing.
- Full suite:
  - `39/39` passing.
- Deterministic dry-run contract smoke:
  - resolver -> cfg -> sql -> cleanup-guard path executed
  - result reported `dry_run=true` and cleanup reason `dry_run_no_delete`.

#### Open Point
- ATH STL export directive remains unknown; TODO hook intentionally retained in `app/services.py`.
