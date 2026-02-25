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
