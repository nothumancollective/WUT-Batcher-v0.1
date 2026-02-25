# Storage Audit (Phase 0 + Phase 1)

Date: 2026-02-25
Branch: `feature/project-library-storage`
Scope: full repo scan (`app/`, `docs/`, `tests/`, `cleanup/`, `tools/legacy/`)

## 1) Baseline Snapshot (no code changes)

### Environment assumptions observed
- OS/runtime: Windows + Python `3.12.2`
- Tools currently configured and detected executable:
  - `C:\Tools\ATH\ath.exe`
  - `C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe`
  - `C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe`
- User settings location used by current code: `%USERPROFILE%\.wut_batcher\config.json`

### Baseline run commands executed
- `python -m app run-sample --dry-run --library-root cleanup/runtime/baseline_prechange`
- `python -m app run-sample --real --library-root cleanup/runtime/baseline_prechange_real`

### Actual write targets observed
Dry-run (`cleanup/runtime/baseline_prechange`):
- Root DB: `cleanup/runtime/baseline_prechange/global.sqlite`
- Project root: `cleanup/runtime/baseline_prechange/P001/`
- Project DB: `cleanup/runtime/baseline_prechange/P001/dataset/project.sqlite`
- Version runtime cfg target: `cleanup/runtime/baseline_prechange/P001/versions/V002/cfg/P001_B001_V002_<run8>.cfg`
- ATH export target planned outside library: `C:\Horns\P001_B001_V002_<run8>`

Real run (`cleanup/runtime/baseline_prechange_real`):
- Same core layout as above (`global.sqlite` + `P001/...`)
- `cleanup_results` confirmed explicit deletion behavior:
  - runtime cfg file deleted in `.../versions/V002/cfg/`
  - ATH export subdir deleted at `C:\Horns\P001_B001_V002_<run8>`

### Current analyzer baseline
- Service query against baseline project returned no analyzer rows for this sample (`analyzer_list_polar_projects(source='project') -> []`), because sample run had no ingested polar exports.

## 2) Repo-wide archaeology findings

## 2.1 Active storage/path modules in runtime path
- `app/settings_store.py`
  - Owns persisted `library_root` and tool paths.
  - Default library root currently `~/Documents/WUT-Batches/Projects`.
- `app/gui.py`
  - Gear icon (global top bar) opens `SettingsDialog`.
  - `SettingsDialog` currently has plain `Library Folder` line edit; no folder picker.
- `app/services.py`
  - Creates `ProjectRepository(self.settings.library_root)`.
  - `create_project()` allocates numeric IDs (`P001`, `P002`, ...).
  - `run_batch()` calls `run_batch_pipeline(... projects_root=self.settings.library_root ...)`.
- `app/project_storage.py`
  - Current canonical project/batch/version directory structs for app flow.
- `app/runtime_orchestrator.py`
  - Additional ad-hoc path builders for version cfg/abec/log/export dirs.
  - Uses `C:\Horns` export root (`ATH_PREVIEW_EXPORT_ROOT`) for ATH output subtree.
- `app/sql_dataset_store.py` (aliased by `app/tidy_dataset.py`)
  - Creates per-project DB: `<project>/dataset/project.sqlite`
  - Creates library-scoped DB: `<library>/global.sqlite`
  - Mirrors writes project->global with replication queue fallback.

## 2.2 Parallel/legacy concepts found
- Legacy path resolver quarantine:
  - `app/path_resolver.py` -> shim to `tools/legacy/path_resolver.py`
  - Legacy layout pattern: `Project_<id>/Batch_<id>/Config|ATH Export|Resultate|Logs`
- Legacy storage migration quarantine:
  - `app/storage_migrations.py` -> shim to `tools/legacy/storage_migrations.py`
- Runner test workspace (separate testing subsystem):
  - `app/runner_test_workspace.py`, `app/runner_test_harness.py`, `app/runner_test_db.py`
  - Dedicated root `runner_test_workspace/` with its own DB (`runner_test.sqlite`)
- Docs contain mixed historical models:
  - Current active examples: `cleanup/runtime/postmerge_lib/...`
  - Legacy documented resolver model in `docs/path_resolver.md`

## 2.3 Entry-point trace (what current app actually uses)
CLI/GUI entry path confirms active stack:
- `python -m app` -> `app.__main__` -> `app.cli.main`
- `python -m app gui` -> `app.gui.launch_gui()` -> `OrchestratorService`
- Project create/save/run path:
  - GUI `MainWindow._create_project()` -> `OrchestratorService.create_project()`
  - `create_batch()` -> `materialize_batch_plan()` -> `ProjectRepository` + `TidyDatasetWriter`
  - `run_batch()` -> `run_batch_pipeline()`
- No runtime callsites found for `app.path_resolver` or `app.storage_migrations`.

## 2.4 Dead/unreferenced candidates (with proof)
- `app/path_resolver.py`
  - only docs references; no active imports in `app/*` runtime path.
  - `rg -n "from app\.path_resolver|import app\.path_resolver" app tests` -> no callsites.
- `app/storage_migrations.py`
  - only self file + docs references.
  - `rg -n "storage_migrations|from app\.storage_migrations" app tests` -> no callsites.

These are currently quarantine shims, effectively non-shipping for the main app runtime.

## 2.5 Duplications and ambiguities

### A) Multiple sources of truth for path layout
- `project_storage.py` defines project logs directory as `_logs`.
- `sql_dataset_store.py cleanup_unpinned_runs()` writes cleanup audit logs under `project_root/logs` (without underscore).
- Runtime helpers in `runtime_orchestrator.py` manually rebuild `versions/<version_id>/...` paths already representable via `project_storage.resolve_version_paths()`.

### B) Mixed naming of "library" DB
- Code uses `<library>/global.sqlite`.
- Mission target calls for one library-scoped DB/index (`library.sqlite` preferred naming).
- Analyzer/service logic has direct hardcoded references to `global.sqlite` in several methods.

### C) ID semantics mismatch with mission
- Current project identity is counter-only (`P001`, `P002`, ...), derived from folder scan.
- No `library_uid`, no `project_uid`, no counter state persisted as library metadata.
- Counter behavior depends on discovered folders, not explicit library metadata state.

### D) Non-library outputs in current runtime
- ATH runtime export root is hardcoded to `C:\Horns` in normal run path.
- Cleanup deletes subfolders from this external root, proving run artifacts are currently split across library root + external path.

### E) Settings persistence location not OS-typical for Windows
- Current default settings path `%USERPROFILE%\.wut_batcher\config.json`.
- Requirement asks for app settings in standard OS app-data location.

## 3) Current cleanup workflow summary

Two distinct cleanup flows currently coexist:

1. Runtime post-success cleanup (`app/runtime_orchestrator.py` + `app/safe_cleanup.py`)
- Deletes generated runtime cfg file per version (`.../versions/<V>/cfg/<run_cfg>.cfg`).
- Deletes ATH export subdir under configured ATH export root (currently `C:\Horns\<run_cfg_stem>`).
- Strong guardrails (absolute path checks, allowlist roots, deny paths, expected names).

2. User-invoked data cleanup (`runs cleanup-testdata` -> `OrchestratorService.cleanup_test_data()` -> `SqlDatasetStore.cleanup_unpinned_runs()`)
- Deletes unpinned run records and optionally export files within project root.
- Writes cleanup audit JSON under project log folder.

## 4) Consolidation decision input from audit

Existing code already has a viable storage abstraction that should be extended instead of replaced:
- Reuse/extend `ProjectRepository` (folder/manifest layout) + `SqlDatasetStore` (library + project DB).
- Introduce a single authoritative storage manager on top of these for all path generation.
- Keep legacy cleanup workflow callable behind compatibility flag until new project-library path redirection passes E2E.

This section captured the initial Phase 0/1 baseline; later implementation phases appended validation results below.

## 5) E2E Results (Phase 7 validation pass)

Date: 2026-02-25 (feature branch `feature/project-library-storage`, flag `USE_PROJECT_LIBRARY_STORAGE=1`)

### Scenario results
- Default first-run settings root:
  - Fresh settings store resolved to `C:\\Users\\maximilianheinze\\Desktop\\WUT Project Library`.
  - Desktop default rule: PASS.
- Library root #1 (`Desktop/WUT Project Library E2E Codex 1`):
  - Project create: `P0001__<uuid>` with `display_number=P0001` and non-empty `project_uid`.
  - Library metadata/index: `library.json` + `library.sqlite` present.
  - No separate `global.sqlite` created in project-library mode (single library index DB invariant).
  - Project DB path: `<project>/db/project.sqlite` present.
  - Dry-run pipeline writes/cleanup targets remained inside project root (ATH export target under `<project>/runs/ath_export/...`).
- Library root switch to #2 (`Desktop/WUT Project Library E2E Codex 2`):
  - First project in new root created as `P0001__<uuid>` (counter reset): PASS.
  - `project_uid` uniqueness across roots: PASS.
- Reopen old root #1:
  - Previously created project remained discoverable via `list_projects()`: PASS.

### Real-run note
- `run-sample --real` on new project root hit `ath_abec_sync` stage failure in this environment.
- Despite failure, artifact paths still stayed within project library tree (no `C:\\Horns` target in this run path).

### Analyzer smoke
- Analyzer project listing call against E2E roots executed without path-resolution errors.
- No polar datasets were ingested in these sample runs, so analyzer result rows were empty (`0`).

### Fixes applied during E2E hardening
- Fixed `library.sqlite` handle leak in `StorageManager` by explicitly closing sqlite connections.
- Corrected plan/runtime writer wiring so library DB writes use the library root (not `<library>/projects`).
- Added feature-flagged project DB directory switch to `db/project.sqlite` with legacy fallback support.
- Redirected ATH export root to project-local path when project-library storage flag is enabled.

## 6) Bug: Library root change - root cause & affected modules

Date: 2026-02-25

### Reproduction and forensics
- Event handler: `SettingsDialog._save()` in `app/gui.py`.
- Baseline happy path:
  - Selecting a new empty directory and saving succeeded in local repro.
- Failure path (deterministic repro):
  - Set library root input to an invalid target (existing file path), then save.
  - Exception observed:
    - `FileExistsError [WinError 183]` from `StorageManager.ensure_library_root()` (`Path.mkdir()` on file target).
  - Stack trace path:
    - `SettingsDialog._save() -> OrchestratorService.save_settings() -> _bootstrap_library_root() -> StorageManager.ensure_library_root()`.

### Root cause
- Non-atomic settings write in `OrchestratorService.save_settings()`:
  - `settings_store.save(settings)` executes before library-root bootstrap/validation.
  - On bootstrap failure, persisted settings already point to broken root.
- Missing failure guard in `SettingsDialog._save()`:
  - Exceptions from `service.save_settings()` are not handled in dialog flow.
  - Result: crash path with no actionable user feedback.
- Path normalization/validation is deferred too late:
  - Dialog sends raw text directly to settings object without preflight bootstrap transaction.

### Affected modules
- `app/gui.py` (`SettingsDialog._save`, root chooser/open actions)
- `app/services.py` (`OrchestratorService.save_settings`, `_bootstrap_library_root`)
- `app/storage_manager.py` (`ensure_library_root` bootstrap path)
- `app/settings_store.py` (persisted root source of truth)

### Duplicate/parallel path systems check
- `app/path_resolver.py` and `app/storage_migrations.py` are quarantine shims only.
- No runtime callsites use them in current Preferences or runtime path.
- Fix should stay in active stack above; no new storage subsystem needed.

## 7) E2E Results - library root switch fix

Date: 2026-02-25

Validation executed via real `SettingsDialog` and `OrchestratorService` wiring (Qt offscreen), feature flag `USE_PROJECT_LIBRARY_STORAGE=1`.

### Steps and outcomes
1. Default root when settings are unset:
   - Loaded default: `C:\\Users\\maximilianheinze\\Desktop\\WUT Project Library`
   - Expected Desktop default: `C:\\Users\\maximilianheinze\\Desktop\\WUT Project Library`
   - Result: PASS
2. Switch root in Preferences to new empty Desktop folder:
   - Target: `Desktop\\WUT Project Library 2 QA <timestamp>`
   - Save succeeded and service root updated.
3. Create project in new root:
   - First project ID: `P0001__<uid>`
   - Verified `projects/P0001__<uid>/project.json` exists.
   - Verified root-level `library.sqlite` exists.
4. Switch root to another new empty Desktop folder:
   - Target: `Desktop\\WUT Project Library 3 QA <timestamp>`
   - First project ID in new root: `P0001__<uid>`
   - `project_uid` compared to previous root: unique (no collision).
5. Switch back to previous root:
   - Save succeeded.
   - Previously created project in root #2 remained listed/accessible.

### Safety regression checks
- Invalid root save path (existing file path) no longer corrupts settings:
  - Save returns `saved=false` with user-facing error.
  - Previous `library_root` in memory and on disk remains unchanged.
- Startup resilience with previously broken settings:
  - If configured `library_root` fails bootstrap, service attempts default Desktop library root fallback.
  - On successful fallback, settings are rewritten to the recovered default root and app remains usable.
- Library metadata repair paths:
  - Missing `library.json` + existing `library.sqlite`: JSON regenerated.
  - Missing `library.sqlite` + existing `library.json`: sqlite initialized with metadata hints.

## 8) Root switch while project open & new project crash (Phase 0 repro)

Date: 2026-02-25

### Repro: root switch while project open
- Opened project in `MainWindow` and then opened `SettingsDialog`.
- Observed behavior:
  - `library_root_locked=True` was passed from `MainWindow._open_settings()`.
  - `ProjectLibraryRootChooseButton` was disabled when `current_project` was set.
- Event path:
  - `MainWindow._open_settings()` -> `SettingsDialog(..., library_root_locked=True)`.

### Repro: new project crash path
- Forced a storage/repo-root failure condition (`ProjectRepository` pointed at a file path).
- Triggered project creation through UI path (`MainWindow._create_project`).
- Observed unhandled exception (UI crash path):
  - `NotADirectoryError [WinError 267]` from `project_storage.ProjectRepository.list_projects()`.
- Stack path:
  - `MainWindow._create_project()` -> `OrchestratorService.create_project()` ->
    `ProjectRepository.list_projects()` -> `Path.iterdir()` -> `os.listdir()`.

### Phase 0 instrumentation added (DEBUG-only)
- Added debug logs around:
  - settings open entry (`MainWindow._open_settings`)
  - project create start/failure (`MainWindow._create_project`)
  - project close transition for new-project flow (`GuiController._new_project`)

## 9) Audit update for UX/root-switch change (Phase 1)

Date: 2026-02-25

### Audit scope
- Queried `app/`, `tests/`, `docs/` for:
  - `library_root`, `cleanup`, `workspace`, `project_dir`, `output_dir`
  - `path_resolver`, `storage_migrations`, `StorageManager`
  - `library_root_locked`, `SettingsDialog`, `OrchestratorService`, `create_project`, `new_project`

### Findings relevant to this change
- Authoritative storage root/metadata module:
  - `app/storage_manager.py` (normalization, bootstrap, metadata, sqlite init, atomic root switch API).
- Authoritative app settings persistence:
  - `app/settings_store.py` (`UserSettings.library_root` single key; no duplicate library-root key found).
- Active settings-to-runtime wiring:
  - `app/services.py` (`OrchestratorService.save_settings`, `_bootstrap_library_root*`, repo rebind).
- Active Preferences UI wiring:
  - `app/gui.py` (`SettingsDialog`, `MainWindow._open_settings`).

### Parallel/legacy path systems
- `app/path_resolver.py` and `app/storage_migrations.py` remain quarantine shims to `tools/legacy/*`.
- No active runtime imports/calls found for these shims in app/test execution paths.
- Consolidation decision: keep these deprecated shims quarantined; do not introduce new path system.

### Cleanup-only flows still present
- `sql_dataset_store.cleanup_unpinned_runs` and runtime guarded cleanup remain active for explicit cleanup behavior.
- These flows are not authoritative for project-library root switching and should stay separate.

### Root-switch UX blocker and crash surface
- Root switching was UI-locked by `library_root_locked` in `SettingsDialog`.
- New-project crash surface exists at `MainWindow._create_project` because service/storage exceptions were not handled in UI layer.

## 10) Implementation outcomes for this request

Date: 2026-02-25

### Open-project root switching behavior (updated)
- `SettingsDialog` no longer disables `Choose...` when a project is open.
- If library root changes while a project is open:
  - Confirmation modal shown:
    - Title: `Switch Project Library?`
    - Message: `Current project will be closed. Continue?`
    - Buttons: `Close Project & Switch`, `Cancel`
  - On confirm, app closes current project via existing new-project transition flow.
  - Atomic library-root switch runs only after close succeeds.
  - On any failure: user-facing error, root stays unchanged, app remains stable.

### Preferences accessibility
- Added `Settings...` button in `ProjectManagerWindow` (landing/no-project window), opening the same `SettingsDialog`.
- Global top-bar gear remains available in `MainWindow`.

### New-project crash hardening
- `OrchestratorService.create_project()` now bootstraps/rebinds library root before allocation/writes.
- `MainWindow._create_project()` now guards and reports failures (modal + status) instead of propagating uncaught exceptions.
- Repro crash call path from section 8 is now mitigated.

### Storage default policy
- `USE_PROJECT_LIBRARY_STORAGE` now defaults to ON.
- Explicit emergency fallback remains available:
  - set `USE_PROJECT_LIBRARY_STORAGE=0` to force legacy layout behavior.

### E2E smoke (Qt offscreen) for this change
1. Unset settings -> default root resolved to Desktop `WUT Project Library`: PASS
2. Created project -> `P0001__<uid>`: PASS
3. Opened settings while project open, switched root, confirmed close/switch:
   - project context closed
   - root switched successfully
4. Created project in new root -> first project `P0001__<uid>`: PASS
5. Landing window has active `Settings...` entry point: PASS

## 11) Folder dialog crash repro + signals (Phase 0)

Date: 2026-02-25

### Repro targets
- `SettingsDialog._choose_library_root()` (opened from MainWindow settings gear)
- Same dialog path when opened from ProjectManager `Settings...` entry

### Classification signals gathered
- Reported behavior in user environment: hard process crash when clicking `Choose...`.
- Local offscreen probe of native `QFileDialog.getExistingDirectory(...)`:
  - No Python traceback produced.
  - Call did not return in headless probe (timed out), consistent with native dialog handoff behavior but not sufficient to confirm crash locally.
- Windows Application log query during session found no fresh `Application Error` / `Windows Error Reporting` entry tied to this probe run.

### Diagnostics added (DEBUG-guarded)
- `faulthandler.enable(all_threads=True)` via `_enable_fault_diagnostics()` when DEBUG logger is enabled (or `WUT_ENABLE_FAULTHANDLER=1`).
- Added pre/post log markers around native folder dialog open:
  - `about to open native folder dialog`
  - `folder dialog returned`
- Added settings-open entry logs for both call paths:
  - MainWindow settings gear
  - ProjectManager settings entry
