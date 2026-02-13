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

### Milestone
- Milestone: GUI runnable + VACS ingest + dry-run contracts

### Update 7 (Sub-Milestone: Sample E2E Command + Success Status)
#### Done
- Added CLI command: `python -m app run-sample`
  - creates or reuses project/batch and runs a minimal one-version pipeline
  - mode control: `--real` or `--dry-run` (auto-fallback to dry-run if tools are not fully executable)
  - uses settings tool paths (`ath_exe`, `akabak_exe`, `vacs_exe`) as source of truth
  - validates post-run contracts directly against project SQL + runtime summary:
    - `versions.status`
    - `ath_dimensions`
    - `graphs` + `graph_points`
    - guarded cleanup result
    - core artifact paths
  - returns deterministic JSON report and non-zero exit code when checks fail.
- Runtime final success state normalized:
  - final version status is now `success` (instead of `completed`) when all stages pass.
- Added tests:
  - `tests/test_cli_run_sample.py` (dry-run success + real-mode-missing-tools failure path).

#### Validation
- `python -m unittest tests.test_cli_run_sample tests.test_runtime_orchestrator -v` -> passing.
- `python -m app run-sample --library-root .tmp_sample_lib` -> dry-run contract report returned `ok: true`.

### Update 8 (Sub-Milestone: Export Regeneration + UI Wiring)
#### Done
- Export path hardened in `OrchestratorService.export_version()`:
  - CFG regeneration still uses SQL parameter states with explicit unset omission.
  - ABEC export now requires ATH regeneration run and expects generated `.abec` artifact from export workspace.
  - Missing ATH executable for STL/ABEC now fails fast with clear error.
- STL export hook isolated for future patching:
  - single constant `ATH_STL_EXPORT_DIRECTIVE` controls final STL directive injection.
  - until known, deterministic TODO hook remains idempotent.
- Added service API for export UI:
  - `list_versions(project_id, batch_id=None)` reads version rows from project SQL.
- Dashboard UI integration:
  - replaced inline export fields with modal `ExportDialog` (batch/version + STL/ABEC).
  - export errors are surfaced in status bar detail instead of crashing flow.
- Run view and status UX:
  - run page now displays active mode (`real` or `dry-run`).
  - startup doctor status now shows concise failure/warn message with click-through details in status bar.

#### Validation
- `python -m unittest tests.test_service_export tests.test_cli_run_sample -v` -> passing.
- GUI smoke including new export dialog/theme/titlebar path passed.
- Full test suite remains green (`45/45`).

#### Real-Tools Check
- Executed `python -m app run-sample --real`.
- Result: tools unavailable in current settings (`ath_exe`, `akabak_exe`, `vacs_exe` not configured), real run skipped with deterministic error payload.

### Update 9 (Real-Tools Attempt with Provided Paths)
#### Done
- Validated tool executables from provided folders:
  - `C:\Tools\ATH\ath.exe`
  - `C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe`
  - `C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe`
- Stored those paths in user settings and executed:
  - `python -m app run-sample --real --library-root <repo>\\real_tools_library`

#### Result
- Real run reached ATH stage and failed before AKABAK/VACS:
  - stage result: `ath failed`
  - ATH stderr: `ath.cfg: No such file or directory`
- Manual verification in ATH workdir showed ATH then starts but hits mesh invocation issue:
  - `error: gmsh call status = 1`
  - shell parse indicates space-path handling issue for mesh command (`C:\Program ...`)

#### Open Blocker
- Current ATH integration contract is incomplete for this environment:
  - runner must prepare ATH runtime control file expectations (`ath.cfg`) per workdir
  - runner/config must normalize mesh command invocation (gmsh path with spaces) to non-interactive reliable execution
- Until this is implemented, deterministic dry-run remains the reliable validation path in this VM snapshot.

### Update 10 (Compatibility Rules Hardening v1.1)
#### Done
- Fixed semantic inconsistency in guiding-curve rule:
  - `validity_guidingcurve_requires_dist_and_width` now uses fatal requirements (`require(GCurve.Dist)`, `require(GCurve.Width)`) instead of warn action.
- Added in-memory schema migration and normalization:
  - new module `app/compat_schema.py`
  - migrates `ath-geometry-constraints.v1` -> `ath-geometry-constraints.v1.1`
  - adds per-rule fields: `kind`, `applies_to`, `evidence`, optional `verification_plan`
  - enriches runner restrictions with `kind/applies_to/evidence`
  - seeds `semantic_facts` evidence records.
- Added evidence policy wiring:
  - doc-backed evidence for `Length` mandatory and `Source.Contours` override where references exist in knowledge bundle
  - hypotheses with confidence <= 0.5 + verification plans for unbacked facts/rules.
- Added ignored semantics support:
  - new action `note_ignored(key, because)`
  - Source override rule now emits ignored notes for `Source.Shape/Radius/Curv`.
- Reworked DSL evaluation for determinism/security:
  - replaced runtime `eval(...)` execution with restricted AST interpreter
  - explicit unset (`param_states` with `is_set=0`) treated as not defined.
- Updated compatibility export:
  - `app/compat_rules.py` now exports schema 1.1 fields and semantic facts.

#### Tests
- Added:
  - `tests/test_compat_schema.py`
  - extended `tests/test_m2_compat_engine.py`
  - extended `tests/test_compat_rules.py`
- Full suite remains green: `50/50`.

#### Docs
- Added `docs/COMPATIBILITY_SCHEMA.md`.
- Replaced corrupted `docs/Rules.md` with updated rule/evidence/DSL guidance.

### Update 11 (Compatibility Verification + Evidence Completion)
#### Done
- Evidence hardening completed from ATH official docs:
  - semantic facts for `Output.STL`/`Output.ABECProject`, auto subdirectory behavior, and omitted `Source.*` defaults now carry `ath_doc` evidence with `{doc, section, page, quote_hint}` refs.
  - normalization now preserves doc-backed fallback evidence instead of downgrading missing rule evidence to hypothesis.
- Added deterministic compatibility verification harness:
  - new module `app/compat_verification.py` builds minimal CFG cases, executes ATH, checks artifacts/exit behavior, writes JSON report.
  - SQL persistence added via new table `compat_verification_results` in both project/global DB dual-write flow.
  - CLI command added: `python -m app compat verify`.
- DSL engine adversarial hardening:
  - fixed bool semantics so explicit `UNSET` is false in evaluator truthiness.
  - added dedicated adversarial tests in `tests/test_compat_engine_dsl.py` for precedence, negation, dotted/missing keys, escaped warn strings, numeric edge cases, and eval denylist checks.
- Added evidence report:
  - `docs/COMPATIBILITY_EVIDENCE_REPORT.md` generated from normalized schema with rule/fact evidence status and hypothesis coverage.

#### Validation
- Full suite green: `59/59` tests passing.
- Harness tests green with ATH stub and SQL persistence.

#### Open Points
- Most behavior rules are still hypothesis-backed and require either direct ATH doc citation per rule or dedicated executable verification cases to promote confidence.

### Update 12 (Compatibility in Product Reality)
#### Done
- Added central `CompatibilityService` (`app/compatibility_service.py`) to keep UI orchestrator-only:
  - rules-driven `visible_keys`, `locked_keys`, `sweepable_keys`
  - enriched issues with `rule_id`, `severity`, `evidence_type`, inferred `field_key`
  - batch draft evaluation via resolver preview (strict=False)
- UI integration in `app/gui.py`:
  - PROJECT and BATCH pages now render a rules-driven Compatibility panel (visible/locked/sweepable + top issues)
  - locked fields shown as disabled list with tooltip `Locked by runner mode`
  - Save/Run now show a Validation Summary (Top 5 + details) using engine/service issues only
  - fatal issues block save/create; no duplicate validation logic in UI
- CFG emitter/runtime contract hardened:
  - `OrchestratorService.create_batch()` now strips runner-locked keys from user-selected params/sweeps before planning
  - renderer contract unchanged but covered with stronger tests
  - fixed missing `json` import in `cfg_renderer` for list/dict formatting
- Compat regression workflow expanded:
  - `compat verify` now supports modes:
    - `--mode quick` (6 deterministic fast cases)
    - `--mode full` (all defined cases)
  - `--hypothesis-only` to skip doc-backed facts
  - results continue to persist in SQL table `compat_verification_results`

#### Validation
- Full suite green: `63/63`.
- GUI module import smoke passed (`gui_import_ok`).

#### Verify Usage
- Quick run:
  - `python -m app compat verify --mode quick`
- Full run:
  - `python -m app compat verify --mode full`
- Hypothesis-only quick run:
  - `python -m app compat verify --mode quick --hypothesis-only`
- SQL result location:
  - project DB: `<library>/<project_id>/dataset/project.sqlite` table `compat_verification_results`
  - mirrored global DB: `<library>/global.sqlite` table `compat_verification_results`

### Update 13 (UI Automation Contracts: AKABAK + VACS, No Pixel Scanning)
#### Done
- Added UIA contract foundation (no image/pixel matching):
  - `app/ui_contracts/window_signatures.py` with robust signatures (process/class/control/automation_id based, title regex not sole selector)
  - `app/ui_automation/session.py` with `pywinauto` primary backend and `uiautomation` fallback
  - `app/ui_automation/watchdog.py` for modal dialog monitoring, whitelist handling, unknown-dialog debug capture, strict timeouts
- Added deterministic drivers with state-machine style APIs and structured logs:
  - `app/akabak_driver.py`
  - `app/vacs_driver.py`
  - idempotent method contracts and pre/postcondition checks
- Added versioned VACS export recipes:
  - `ui_recipes/vacs/export_spl.txt.json`
  - `ui_recipes/vacs/export_impedance.txt.json`
  - recipe schema validation in `app/ui_automation/recipes.py`
- Added UI inspection CLI commands:
  - `python -m app ui inspect-akabak`
  - `python -m app ui inspect-vacs`
  - outputs written to `ui_maps/` (summary + tree dump artifacts)
- Added documentation:
  - `docs/UI_AUTOMATION_CONTRACTS.md` (update workflow for `ui_maps` + recipes, strict no-pixel policy)

#### Tests
- Added contract tests:
  - `tests/test_ui_automation_contracts.py` (recipes/signatures/inspector dry-run)
- Added optional integration tests (env gated):
  - `tests/test_ui_automation_integration_optional.py` (`WUT_UIA_INTEGRATION=1`)
- Full suite status after changes: `69/69` passing, `2` optional integration tests skipped by default.

### Update 14 (SQL Graph Schema Upgrade for Polar/Series Data)
#### Done
- Upgraded SQL dataset schema to `2.2` with series-aware model:
  - added `graph_series(series_id, graph_id, series_kind, angle_deg, label, meta_json, created_at)`
  - upgraded `graph_points` to `series_id` foreign key + optional `y_imag`
  - extended `graphs` with semantic columns (`graph_kind`, `x_axis`, `y_axis`, `meta_json`) while keeping legacy fields for compatibility
- Added in-place migration logic for legacy DBs:
  - detects old `graph_points(graph_id, ...)`
  - creates default per-graph series rows
  - migrates points losslessly to new schema
- Added performance indices:
  - `idx_graph_points_series_x (series_id, x_value)`
  - `idx_graph_series_graph_angle (graph_id, angle_deg)`
  - `idx_graphs_version_kind (version_id, graph_kind)`
- Updated CLI row counting to join `graph_points -> graph_series -> graphs` for version-scoped checks.

#### Tests
- Added migration regression test:
  - `tests/test_sql_dataset_store.py::test_migrates_legacy_graph_points_schema_to_series_model`
- Extended storage smoke assertions with `graph_series` row counts.

### Update 15 (VACS Polar/Complex TXT Ingestion)
#### Done
- Extended `app/vacs_txt_parser.py` from flat point parsing to series-aware parsing:
  - new model: `VacsGraph -> VacsSeries[] -> VacsSeriesPoint[]`
  - supports per-series markers (e.g. `Series=Angle:30`)
  - extracts `angle_deg` for polar slices
  - parses optional third numeric column into `y_imag` for complex-valued exports
- Updated runtime ingestion (`app/runtime_orchestrator.py`) to write:
  - graph metadata to `graphs`
  - per-angle/per-curve rows to `graph_series`
  - point data with optional imaginary part to `graph_points`
  - includes `meta_json/export_meta` persistence for reproducible provenance.

#### Tests
- Added fixtures:
  - `tests/fixtures/vacs/result_v001polar.txt` (3 angles x 5 freqs)
  - `tests/fixtures/vacs/result_v001polar_complex.txt` (complex samples)
- Added parser coverage:
  - `tests/test_vacs_txt_parser.py` polar + complex parsing assertions
- Added run-loop integration coverage:
  - `tests/test_runtime_orchestrator.py::test_pipeline_ingests_polar_series_into_sql`

### Update 16 (Run Governance + Cleanup Test Data)
#### Done
- Added run-tracking foundation in SQL schema (`2.3`):
  - `runs` lifecycle table with pin/tag and metadata (`git_commit`, `app_version`, `settings_hash`, `error_summary`)
  - `run_versions` table for per-version status per run
  - `versions.version_config_hash` (SHA-256 over canonical effective params with unset semantics)
  - `graphs.run_id` + uniqueness constraints for anti-duplicate behavior inside a run
  - `graph_series` uniqueness constraints (graph/angle/label)
- Runtime now creates a `run_id` per execution and writes lifecycle updates (`running` -> `succeeded|failed`).
- Output rows are tied to runs:
  - `graphs` include `run_id`
  - `ath_dimensions` migrated to `(run_id, version_id)` identity
- Added helper queries/services:
  - latest succeeded run per version (`latest_successful_run_per_version`)
  - run listing (`list_runs`)
  - default service version listing now prefers latest succeeded run data.

#### Cleanup / Pinning
- CLI added:
  - `runs pin <run_id> [--project-id] [--tag]`
  - `runs unpin <run_id> [--project-id]`
  - `runs cleanup-testdata [--project-id] [--delete-exports] [--dry-run]`
- Cleanup deletes only unpinned runs and dependent rows, optionally deletes run-linked export files (inside project root only), and writes audit logs:
  - `<project>/logs/cleanup_<timestamp>.json`

#### GUI
- Dashboard additions:
  - `Runs verwalten...` dialog (pin/unpin)
  - `Testdaten aufraeumen...` dialog (preview, delete-exports toggle, `DELETE` confirmation)
- Pin button tooltip:
  - `Markiert einen Run als Ergebnis, das behalten werden soll.`

#### Tests
- Added:
  - `tests/test_runs_governance.py`
  - `tests/test_cli_runs_tools.py`
- Extended:
  - `tests/test_runtime_orchestrator.py`
  - `tests/test_sql_dataset_store.py`
- Full suite green: `83/83` passing, `2` optional integration tests skipped.
