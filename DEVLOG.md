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

### Update 17 (PROJECT Form UX Finalization)
#### Done
- PROJECT page cleaned up for constraints-only workflow:
  - removed `Project Compatibility` panel from PROJECT view
  - removed `Back to Dashboard` and PROJECT-side `Show details` actions
  - PROJECT creation no longer blocks on compatibility `fatal` draft issues
- Form widgets upgraded to nullable, unset-safe controls:
  - new `NullableNumericInput` with empty-as-unset semantics and comma-decimal normalization
  - new nullable enum/bool/text controls with explicit clear behavior
  - per-field `Set` checkboxes removed across form fields
  - `Mesh.Enclosure` remains the only object toggle (`Enable Enclosure`)
- Layout and style polish:
  - unified compact numeric input widths
  - transparent label backgrounds (no dark text boxes)
  - improved segmented-mode selected state styling (checked/hover/pressed)
  - status bar adjusted as a single bottom line with left status and right brand label

#### Tests
- Updated/extended GUI contract tests:
  - `tests/test_project_form_ui.py`
  - covers nullable numeric mapping, ruleset-driven visibility switching, unset serialization, and PROJECT page button/panel cleanup

### Update 18 (PROJECT Layout/Selection Corrections)
#### Done
- PROJECT form layout switched to two columns (`Geometry | Mesh`) with separate scroll containers to reduce vertical scroll pressure.
- Geometry/Mesh card ordering fixed:
  - Geometry: `Basics -> Throat Profile -> Morph -> GCurve -> Rollback`
  - Mesh: `Core -> Enclosure`
- Removed `Source.*` and `OSSE` object block from PROJECT UI to avoid duplicated/conflicting parameter presentation.
- Selection controls refactored:
  - removed extra `x` clear buttons
  - segmented controls now clear on second click of the active option
- `Mesh.Enclosure` changed from checkbox to segmented `disabled/enabled`; detail fields hide and unset when disabled.
- `Rollback` changed to segmented `disabled/enabled`; `Rollback.Angle/Exp/StartAt` now use contextual disclosure and are unset when disabled.
- Input UX fixes:
  - ensured `optional` is placeholder only (not literal field text)
  - validated numeric entry remains editable
  - unified input widths with and without units using fixed total-width input rows.

#### Tests
- Expanded `tests/test_project_form_ui.py` with coverage for:
  - two-column layout presence
  - required geometry/mesh card order
  - source removal + single `R-OSSE` presence
  - segment second-click clear behavior
  - placeholder/editability regression guard
  - absence of `x` clear buttons in selection controls

### Update 19 (PROJECT Input Stability + Context UX Polish)
#### Done
- Fixed nullable numeric validator patterns so digits are accepted while placeholder text is visible.
  - `optional` remains placeholder-only; empty text now consistently maps to `unset`.
  - numeric parsing still normalizes locale decimal comma to dot on serialization.
- Added centralized hint helpers (`ui/hints.py`) and wired schema placeholders/tooltips through them.
  - numeric placeholders simplified to `optional`
  - list placeholders standardized to `e.g. 1,2,3`
  - expression placeholders use short examples (or fallback example) instead of long inline prose
- GCurve mode UX updated to three explicit options:
  - `no GCurve` -> `GCurve.Type` unset (explicit coverage mode)
  - `Superellipse` -> `GCurve.Type = 1`
  - `Superformula` -> `GCurve.Type = 2`
- Introduced reusable inset `ContextFrame` styling/component and applied it to conditional sections:
  - `R-OSSE` mode details
  - Morph details (shown only when `Morph.TargetShape != 0`)
  - Rollback details (shown only when rollback enabled)
  - GCurve common/mode details
  - Enclosure object details
- Converted bool control presentation to segmented optional controls (`off/on`) for PROJECT consistency.
  - includes `Morph.AllowShrinkage` (no checkbox look)
- Reduced control widths and grid spacing; disabled horizontal scrollbars on both PROJECT columns to prevent sideways scrolling.

#### Tests
- Extended `tests/test_project_form_ui.py` with:
  - horizontal scrollbar policy checks
  - GCurve three-option mode + unset payload check
  - Morph contextual frame disclosure + segmented bool control assertion
  - context-frame presence assertion
- Regression suite status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 20 (PROJECT Visual Polish + Layout Cleanup)
#### Done
- Removed nested dark overlay artifacts in PROJECT subblocks:
  - switched generic `QWidget` background styling to transparent
  - kept tone/border responsibility on explicit containers (`QGroupBox`, `ContextFrame`)
  - refined `ContextFrame` to a subtle inset style (no heavy dark fill)
- Reduced clipping risk and tightened layout spacing:
  - removed rigid grid minimum-width constraints
  - reduced sub-grid margins/spacing and slightly tightened control widths
  - kept horizontal scrollbars disabled in both PROJECT columns
- Throat mode sections polished:
  - ensured mode page headers resolve to `OS-SE` and `Circular Arc`
  - removed extra nested R-OSSE mode wrapper; R-OSSE now shows a single inset `Details` frame below selector
- Mesh/Core alignment cleanup:
  - custom core renderer with one aligned control column
  - selection controls (`Mesh.Quadrants`, `Mesh.RearShape`) and following inputs share the same left control anchor

#### Tests
- Extended `tests/test_project_form_ui.py`:
  - verifies throat page headers (`OS-SE`, `Circular Arc`) and absence of extra `R-OSSE` mode header frame
- Regression status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 21 (PROJECT Form Metrics + Unit/Placeholder Alignment)
#### Done
- Introduced centralized form layout metrics in `ui/form_metrics.py`:
  - shared label width, input width, label->input gap, column gap, row gap, and margins
  - reusable grid configurators for single-column control rows and two-column form rows
- Restored two-column subforms where regressions occurred:
  - `Mesh/Core` now uses selection rows on top + two-column form grid below
  - left control anchor stays aligned between selection rows and form rows
  - `GCurve Common` and mode-specific pages (including Superformula) render as two-column grids again
- Removed redundant Enclosure inner row label (`Mesh Enclosure`) by rendering object editor directly under `Enclosure` group title.
- Placeholder/text alignment normalization:
  - numeric and text inputs are explicitly left-aligned
  - `optional` now aligns consistently with all other placeholders
- Unit handling polish:
  - expression/list text inputs now support inline unit suffix labels (fixes missing unit on `Slot.Length`)
  - half-angle unit overrides applied where documentation confirms half-angle semantics:
    - `Throat.Angle`, `Throat.Ext.Angle`, `Coverage.Angle` -> `deg/2`
    - `R-OSSE.a0`, `R-OSSE.a` -> `deg/2`

#### Tests
- Expanded `tests/test_project_form_ui.py` coverage for:
  - Mesh/Core two-column structure and control-anchor alignment
  - removal of redundant Enclosure label
  - Slot.Length unit visibility (`mm`)
  - half-angle unit overrides
  - placeholder left alignment
  - two-column rendering for GCurve Common/Superformula
- Regression status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 22 (PROJECT Layout Corrections Follow-up)
#### Done
- Geometry/Mesh top sections switched from collapsible toggles to static section headers.
- `Projekt erstellen` action moved to the lower-right side of PROJECT page.
- Input width/spacing pass:
  - reduced input width further and unified widths across fields with and without unit suffix
  - reserved a fixed suffix slot in text/numeric inputs so visual input width is consistent
  - tightened global label->input gap to match Mesh/Core horizontal rhythm
- Mesh/Core adjusted:
  - kept selection rows on top
  - balanced two-column form body by splitting remaining fields across left/right columns
- GCurve mode UX:
  - hidden empty `Common` frame when `GCurve.Type` is unset (`no GCurve`)
  - mode page stack switched to auto-sizing widget to avoid oversized blank vertical space for smaller pages
- Unit display parity:
  - `deg/2` now visibly renders in input suffix for half-angle fields
  - Slot expression units remain shown via suffix slot (`Slot.Length -> mm`)

#### Tests
- Expanded `tests/test_project_form_ui.py` for:
  - non-collapsible Geometry/Mesh headers
  - right-aligned create button in PROJECT page
  - uniform input widths (with/without unit)
  - hidden GCurve `Common` frame in `no GCurve` mode
  - balanced Mesh/Core two-column labels
  - explicit `deg/2` suffix visibility checks
- Regression status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 23 (PROJECT Fine Tuning: Anchoring, Header Cleanup, Unit Clipping)
#### Done
- Responsive layout behavior adjusted:
  - inner form column gaps remain fixed while window growth now increases outer spacing (column-to-column spacing and section content margins).
  - group blocks are width-capped and left/top anchored to avoid internal horizontal drift.
- Mesh/Core refinement:
  - right-column trailing blank row removed by rebalancing left/right field assignment.
- Dynamic height/anchoring improvements:
  - mode stacks (`Throat Profile`, `GCurve`) use auto-sizing pages and top-anchored container layouts.
  - page switching now updates stack/group geometry immediately.
  - `Throat.Profile` now has an explicit unset page (no OS-SE page shown when profile is cleared).
- Header visual cleanup:
  - context headings switched to `ContextTitle` (bold, transparent background).
  - group-box title styling forced transparent and bold to remove remaining dark header artifacts.
- Unit suffix clipping fix:
  - increased reserved unit suffix width so `deg/2` renders fully without clipping.

#### Tests
- `tests/test_project_form_ui.py` extended and updated for:
  - `Throat.Profile` unset hides OS-SE page content
  - `deg/2` suffix visibility assertions
  - Mesh/Core balanced two-column counts
  - non-collapsible section headers and create-button alignment regression guards remain green
- Regression status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 24 (PROJECT Follow-up Corrections)
#### Done
- Header styling scope corrected:
  - block titles (`QGroupBox::title`) remain bold
  - inner/context titles switched back to non-bold style (`ContextTitle`) to avoid emphasizing under-block labels
- Mesh/Core column count normalized:
  - moved `Mesh.InterfaceOffset` to `Enclosure` group mapping
  - Core body now renders `6/6` label rows consistently
- Mode block sizing refined:
  - mode stacks now apply fixed current-page height on switch for deterministic vertical shrink/grow
  - keeps Throat/GCurve block height synced to active subblock state
- Width behavior tightened:
  - block group width fixed to a shared form width hint
  - prevents inner-column spacing drift while window grows (extra room is absorbed by outer margins/gaps)

#### Tests
- `tests.test_project_form_ui`: passing
- compatibility/storage/runtime targeted suites: passing

### Update 25 (PROJECT Alignment + Coverage Move + Fullscreen Open)
#### Done
- Main workflow window now opens in fullscreen when creating/opening a project from Project Manager.
- PROJECT header alignment pass:
  - increased left margin for page title area
  - project-name input moved into a two-column top grid and fixed to geometry block width
  - create button placed in mirrored right-column container so it aligns to mesh block right edge while keeping bottom row position
- Geometry/Mesh section headers now inherit the same horizontal inset as their block stacks, keeping headings left-aligned with block edges.
- `Coverage.Angle` moved out of `no GCurve` mode page into `Basics`:
  - `no GCurve` subblock removed (empty page)
  - `Coverage.Angle` shown only when `GCurve.Type` is unset
  - `Coverage.Angle` hidden/unset when a guiding-curve mode is selected
- Mode layout behavior refined:
  - fixed-width group boxes to keep horizontal width constant across mode changes
  - vertical size still follows active subblock/page height

#### Tests
- Extended `tests/test_project_form_ui.py` with:
  - coverage-angle visibility behavior in basics vs gcurve mode
  - absence of `no GCurve` context heading block
  - updated project-button alignment assertion for new grid layout
- Regression status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 26 (PROJECT Window Controls + Placeholder 0 + Scrollbar Polish)
#### Done
- Replaced PROJECT main-window open mode from true fullscreen to native maximized window mode:
  - keeps standard Windows titlebar controls (minimize / maximize / close) available
  - applied consistently for both "open existing project" and "new project"
- Unified PROJECT form placeholders for editable text-based controls to `0`:
  - numeric, expression, list and text inputs now all show `0` when unset/empty
  - placeholder remains visual-only; unset semantics stay unchanged (`is_set=0`, value `NULL`)
- Added dedicated PROJECT column scroll-area styling (`Geometry` and `Mesh`) for cleaner dark UI:
  - transparent track, slimmer handle, rounded thumb, no arrow buttons
  - keeps horizontal scrolling disabled as before

#### Tests
- `python -m unittest tests.test_project_form_ui -v` (all passing)

### Update 27 (PROJECT Segments: Forced No/Disabled Fallbacks)
#### Done
- Added field-specific segmented-control fallback behavior for PROJECT mode selectors:
  - `Morph.TargetShape`: defaults to `no morph` and cannot end in unselected state.
  - `GCurve.Type`: defaults to `no GCurve` and cannot end in unselected state.
  - `Rollback`: defaults to `disabled` and cannot end in unselected state.
  - `Mesh.Enclosure` toggle: defaults to `disabled` and cannot end in unselected state.
- Re-click behavior updated for these controls:
  - when a non-default option is clicked again, selection now returns automatically to the fallback (`no...` / `disabled`).
  - clicking the fallback itself no longer clears to empty for these controls.
- Kept existing clear-to-unset behavior for unrelated segmented controls (e.g. `Throat.Profile`) unchanged.

#### Tests
- `python -m unittest tests.test_project_form_ui -v` (30 tests passing)

### Update 28 (PROJECT Page ATH Pipeline Test Harness)
#### Done
- Added isolated real-run harness for PROJECT-page constraints:
  - new module `app/projectpage_ath_test.py`
  - uses PROJECT form schema + `ParameterForm` + `CompatibilityService` to build the same constraints draft structure as UI
  - resolves one version via existing resolver path (`resolve_versions`) and renders CFG via existing renderer (`render_cfg_text`)
  - writes CFGs to `C:\Tools\ATH\ProjectPageATHTestN.cfg`
  - runs ATH real via `AthRunner`, writes runtime `ath.cfg`, detects newest export folder in `C:\Horns`
  - parses generated CFG and exported `config`/`config.txt`, compares against expected UI-set values (+ allowed mandatory globals), reports missing/extra/mismatch keys
  - writes per-run JSON reports and suite summary to `reports/projectpage_ath_test/`
- Added CLI entrypoint:
  - `python -m app projectpage-ath-test`
  - options: `--ath-exe`, `--template-cfg`, `--cfg-dir`, `--export-root`, `--reports-root`, `--count`
- Added parser/compare unit tests:
  - `tests/test_projectpage_ath_test.py`

#### Tests
- `python -m py_compile app/projectpage_ath_test.py app/cli.py tests/test_projectpage_ath_test.py`
- `python -m unittest tests.test_projectpage_ath_test -v`

### Update 29 (Rollback Off + Mesh Mapping + R-OSSE Normalization)
#### Done
- Rollback disabled for current ATH mode:
  - PROJECT form schema omits `Rollback*` fields.
  - PROJECT page shows explicit notice: `Rollback is not supported in this ATH version. Use R-OSSE profile instead.`
  - ruleset replaced rollback visibility toggle logic with:
    - permanent rollback hide rule
    - fatal validity rule when rollback is explicitly enabled.
- Resolver now carries PROJECT mesh `limits` into resolved version parameters, so `Mesh.*` set on PROJECT can be rendered into CFG.
- CFG renderer now emits object parameters as ATH blocks, including deterministic `R-OSSE = { ... }` serialization order.
- ATH config parser and comparison normalization improved:
  - supports empty object assignment patterns (`R-OSSE =` followed by member lines),
  - compares with optional-missing prefixes (currently `Mesh.*` in exported config),
  - separates `extra_keys_defaulted` from `extra_keys_ghost` in reports.
- ATH harness suite adjusted to 6 rollback-free autonomous cases with conservative geometry.

#### Tests
- `python -m unittest tests.test_project_form_ui tests.test_m2_compat_engine -v`
- `python -m unittest tests.test_version_resolver -v`
- `python -m unittest tests.test_m5_planner_renderer tests.test_projectpage_ath_test -v`

### Update 30 (PROJECT ATH Experiment Harness v1)
#### Done
- Added large-scale experiment harness:
  - `app/projectpage_ath_experiment.py`
  - CLI command: `python -m app projectpage-ath-experiment`
  - deterministic seeded generation with safe/exploratory mix (`70/30` target).
- Harness uses the existing PROJECT UI data path only:
  - `ParameterForm -> CompatibilityService -> resolve_versions -> render_cfg_text -> ATH`.
- Added persistent experiment dataset:
  - SQLite at `reports/ath_experiments/ath_experiments.sqlite`
  - tables: `experiment_runs`, `experiment_params`, `experiment_metrics`, `experiment_compare`
  - indexes on status/error/keys/numeric dimensions.
- Added ATH stdout/stderr parsing and classification:
  - parses final width/height/length and average mesh throat angle
  - normalizes units (`m` -> `mm`)
  - classifies known error patterns and warning counts
  - applies dimension thresholds (`max-dim` warn, `hard-cap` fail).
- Added report outputs:
  - per-run JSON: `reports/ath_experiments/cases/run_XXXX/report.json`
  - copied raw logs: `reports/ath_experiments/logs/run_XXXX_stdout.txt|stderr.txt`
  - aggregate outputs:
    - `reports/ath_experiments/summary.json`
    - `reports/ath_experiments/summary.md`
    - `reports/ath_experiments/range_suggestions.v1.json`
- Added compatibility experiment documentation and machine-readable draft rule skeleton:
  - `docs/COMPATIBILITY_EXPERIMENT_NOTES.md`
  - `app/knowledge/ath/experimental_rules.v1.json`

#### Tests
- `python -m py_compile app/projectpage_ath_experiment.py app/cli.py`
- `python -m unittest tests.test_projectpage_ath_experiment tests.test_projectpage_ath_test -v`

### Update 31 (PROJECT UI Risk States + Hover Helper Refinement)
#### Done
- Unified PROJECT field-risk pipeline integrated in UI:
  - source merge from normative compatibility issues + experiment hints (`range_suggestions`, `compat_rule_candidates`)
  - deterministic per-field merge policy: `fatal > warn > ok > neutral`.
- Added debounced live-validation update path for PROJECT draft changes.
- Added persistent `fieldState` styling hooks:
  - input-level outlines for `ok` (green), `warn` (amber), `fatal` (red), `neutral`.
  - existing green "conform" state preserved.
- Reworked helper behavior to avoid layout jumps:
  - removed inline per-field helper lines that changed row height
  - kept compact field badges (`!` / `x`) next to inputs
  - introduced hover helper popup with severity styling and placement by column side.
- Helper text normalization:
  - clean English output (no "Experiment..." prefix)
  - display-only decimal formatting to 2 places in helper popup.
- Numeric input normalization:
  - decimal comma is normalized to decimal dot in numeric editors (`123,45 -> 123.45`)
  - matches ATH/CFG decimal notation expectations.

#### Notes
- Compatibility semantics/rules were not changed in this pass.
- Only UI presentation and interaction around existing issue outputs were changed.

#### Tests
- `python -m unittest tests.test_ui_validation_ranges tests.test_ui_validation_candidates -v`
- `python -m unittest tests.test_project_form_ui -v`

### Update 32 (PROJECT Accordion Redesign: Header Row, Chips, Section Status)
#### Done
- Replaced minimal accordion header with full row-item header component:
  - title + summary chips (collapsed state) + status badge + chevron
  - full-row click target + keyboard toggle (`Enter` / `Space`) support.
- Kept per-column exclusive expand behavior:
  - opening one section collapses others in the same column
  - values remain preserved while sections collapse.
- Added section-level status aggregation from existing field issues:
  - counts per section (`ok/warn/fatal`)
  - fatal dominance for section badge (`x n`), warn badge (`! n`)
  - summary chips clipped to max 3 with `+N` overflow indicator.
- Styling refinement for calmer hierarchy:
  - section severity emphasis moved primarily to header accent/badge
  - expanded section frame uses subtle warn/fatal tone (no loud full-block warning style).
- Vertical rhythm/spacing pass:
  - more top space between project-name row and column headers
  - larger, more intentional header rows to reduce "thin/unfinished" appearance.

#### Tests
- Extended `tests/test_project_form_ui.py` with:
  - accordion collapse behavior + value persistence assertions
  - section-level warning/fatal badge dominance assertions
  - collapsed-chip overflow (`+N`) assertions
- Regression status:
  - `tests.test_project_form_ui`: passing
  - `tests.test_ui_validation_ranges`: passing
  - `tests.test_ui_validation_candidates`: passing

### Update 33 (PROJECT Action Bar + Summary Panel + Tooltip Accent Styling)
#### Done
- Added a sticky PROJECT action bar above the global `QStatusBar`:
  - left: status pill (`Ready to create`, `Warnings: n`, `Fix errors: n`, `Checking constraints...`, `Creating project...`, `Constraints locked for this project`)
  - optional hint text and `View issues` action when warnings/errors exist
  - right: primary CTA moved to `Create Project`.
- Clarified status responsibilities:
  - action bar now owns user-facing draft state on Project Page
  - bottom `QStatusBar` remains for technical/transient messages.
- Added compact summary/info panel under project name:
  - explains constraint locking after creation
  - shows `Errors: n • Warnings: n`
  - shows mode chips (Throat/Morph/GCurve/Enclosure) for quick context.
- Improved collapsed-state density:
  - reduced geometry/mesh column gap
  - aligned project-name row with the left column grid for cleaner rhythm.
- Updated helper popup styling to reduce visual noise:
  - removed heavy warning border look
  - neutral popup border + severity accent strip.

#### Tests
- `python -m unittest tests.test_project_form_ui -v`
- `python -m unittest tests.test_ui_validation_ranges tests.test_ui_validation_candidates -v`

### Update 34 (PROJECT Responsive UX + Deterministic Issues Navigation)
#### Done
- Added responsive baseline for PROJECT columns:
  - switched form columns to `QSplitter` with per-column internal scrolling
  - kept bottom action area visible while columns resize
  - set main window minimum size (`1120x760`) to avoid unusable cramped states.
- Improved PROJECT top layout alignment and rhythm:
  - aligned `Project Name` row with left content column
  - adjusted top spacing so title/name/summary card read as a structured header area.
- Reduced visual density issues in section content:
  - mesh/core grid spacing increased (especially label-input rhythm in right-side fields)
  - field labels switched to single-line with tooltip fallback to avoid wrapped labels pushing rows unpredictably.
- Introduced deterministic UI issue model (presentation-only, no compat semantic changes):
  - new `app/project_issue_model.py` classifies issues into `error`, `warn`, `incomplete`
  - fatal "required missing" on unset fields now shown as `incomplete` (neutral) instead of immediate red error state
  - stable ordering: errors -> warnings -> incomplete.
- Reworked `View issues` behavior:
  - added on-page `ProjectIssuesPanel` listing all issues grouped by severity
  - clicking an issue opens the correct accordion section, scrolls to the field, focuses it, and applies a short subtle flash.
- Refined action bar behavior (not a second status bar):
  - compact issue counts (`errors · warnings · incomplete`)
  - concise state copy for ready/incomplete/warn/error/creating/locked/validating
  - create button disabled for `error` or `incomplete` with explicit tooltip reason.
- Accordion section state chips/badges now communicate progress:
  - `unset`, `ok`, `warn`, `fatal`, `incomplete` states represented via subtle tokenized badge/chip styling.

#### Manual QA Checklist
- Fullscreen:
  - two-column layout remains stable, action bar visible above OS status bar
  - section badges/chips update with field changes.
- Restore-down window:
  - no global page collapse; column scrolling stays inside Geometry/Mesh columns
  - bottom action bar remains visible and usable.
- Issues navigation:
  - `View issues` shows full grouped list (no random single issue)
  - clicking list item expands target accordion and focuses target field.
- Create CTA:
  - disabled for errors and incomplete required fields
  - enabled when only warnings are present.

#### Tests
- `python -m unittest tests.test_project_issue_model tests.test_project_form_ui tests.test_ui_validation_ranges tests.test_ui_validation_candidates -v`
- `python -m py_compile app/gui.py ui/form_builder.py ui/theme.py app/project_issue_model.py`

### Update 35 (PROJECT Layout Cleanup: No Splitter Handle + In-Card Issues Popover)
#### Done
- Removed draggable middle column splitter behavior on Project Page:
  - replaced splitter-based column container with fixed-gap two-column `QHBoxLayout`
  - both Geometry and Mesh columns are now `QSizePolicy.Expanding`
  - fixed inter-column spacing keeps the center gap stable (no giant middle void).
- Moved "View issues" into the top summary card (right side of card header):
  - clicking opens an anchored popup issues viewer (`Qt.Popup`) instead of adding a new page area
  - popup lists all issues grouped and ordered by severity (Errors, Warnings, Incomplete)
  - selecting an issue expands the right accordion section, scrolls to the field, and focuses it.
- Corrected fresh-start mode defaults:
  - `Throat.Profile` now starts unset (no implicit OS-SE preselection).
- Added smooth accordion expand/collapse animation:
  - body height animation (`OutCubic`, ~180ms)
  - subtle opacity fade for smoother perceived transitions.
- Reduced expanded-section density without redesign:
  - tighter inner margins/row spacing in section bodies
  - non-wrapping labels with tooltip fallback to avoid multi-line label drift
  - mesh core horizontal spacing tuned to avoid label/input crowding in right column.
- Updated minimum baseline for no-scroll target:
  - main window minimum size now `1280x800` for Project Page usability baseline.

#### Manual QA Checklist
- Fullscreen:
  - no draggable handle between Geometry and Mesh columns
  - top summary card keeps "View issues" button inline; opening issues does not change page height
  - accordion transitions are smooth (no hard snap).
- Restore-down:
  - columns remain readable with fixed middle gap
  - action bar remains visible and usable.
- Issue navigation:
  - popup shows deterministic grouped list (no random single issue)
  - clicking issue opens section and focuses target field.
- Defaults:
  - fresh project starts with `Throat Profile = unset` (no OS-SE preselected).

#### Tests
- `python -m unittest tests.test_project_issue_model tests.test_project_form_ui tests.test_ui_validation_ranges tests.test_ui_validation_candidates -v`
- `python -m py_compile app/gui.py ui/form_builder.py ui/form_metrics.py ui/theme.py app/project_issue_model.py`

### Update 36 (PROJECT Dense Top Area + Embedded In-Card Issues + Compact Superformula Grid)
#### Done
- Freed top vertical space:
  - removed redundant top-panel `Errors/Warnings/Incomplete` line (counts remain in sticky bottom bar only)
  - removed standalone `Project Name` caption row label; input now uses placeholder + tooltip.
- Reworked top chips into a strict single-line strip:
  - chips do not wrap
  - overflow collapsed as `+N`.
- Replaced issues overlay behavior with embedded in-card issues viewer:
  - top info card now has internal left/right structure
  - right side hosts toggleable embedded issues panel with internal scrolling
  - toggle animation uses `QPropertyAnimation` (`OutCubic`, ~190ms) on width/opacity
  - card height remains fixed while issues view opens/closes.
- Reduced Geometry/Mesh middle gap:
  - constant non-stretch spacing reduced to a compact range.
- Reduced left-column expanded height pressure:
  - introduced responsive compact grid for `GCurve -> Superformula` fields
  - uses 3 columns when width allows, falls back to 2 columns on narrow width.

#### Tests
- `python -m unittest tests.test_project_form_ui tests.test_project_issue_model tests.test_ui_validation_ranges tests.test_ui_validation_candidates -v`
- `python -m py_compile app/gui.py ui/form_builder.py ui/theme.py ui/form_metrics.py tests/test_project_form_ui.py`

### Update 37 (Pre-Change Verification Checklist for Compact Project Page Pass)
#### Current State Check (before implementation)
- Requirement 1 (Issues subsection inside top InfoBar, header-toggle only): **Not implemented**
  - Current state: top InfoBar uses a separate `View issues` / `Hide issues` button and an embedded panel area, but no subsection-style header row with chevron toggle semantics.
- Requirement 2 (3-column input layout for all LEFT subsections): **Partially implemented**
  - Current state: only `GCurve -> Superformula` uses a compact grid; other Geometry subsection bodies still render as 2-column grids.
- Requirement 3 (main columns exactly 2/3 left and 1/3 right, no stretchy middle gap): **Not implemented**
  - Current state: columns use stretch weights `6:5` with a reduced fixed spacing, not the required `2:1` split.
- Requirement 4 (shorter InfoBar + chips one-line + no extra status line): **Partially implemented**
  - Current state: redundant top counts line already removed and chips use single-line overflow (`+N`), but InfoBar still keeps two description lines and remains taller than required.

### Update 38 (PROJECT Compact Pass: InfoBar Issues Subsection + 3-Column Geometry + 2:1 Main Split)
#### What was wrong
- Issues in the top panel were still controlled by a separate button instead of a real subsection-style header toggle.
- Geometry subsections still used mostly 2-column field layouts, causing extra vertical growth.
- Main Geometry/Mesh content split was not the requested fixed test ratio (`2/3` vs `1/3`).
- InfoBar still consumed too much height due to two description lines.

#### What changed
- `app/gui.py`
  - Replaced top-right button-driven issues area with an in-card, right-anchored issues subsection:
    - header row (`Issues` + `E/W/I` counts + chevron)
    - click header to expand/collapse (no standalone hide button)
    - scrollable grouped issue list in subsection body
    - row click still focuses the exact field and opens the right accordion section.
  - Reduced summary InfoBar height and content density:
    - fixed height reduced to a compact size
    - one description line retained
    - chips stay single-row with existing overflow behavior.
- `ui/form_builder.py`
  - Main column split changed to `2:1` (Geometry : Mesh).
  - Geometry subsection bodies switched to dense `ResponsiveCompactGrid` usage broadly:
    - 3 columns in normal/wide mode
    - fallback to 2 columns for compact widths
    - reduced intra-section spacing for lower vertical footprint.
- `ui/theme.py`
  - Added styling for new InfoBar issues subsection/header/body objects.
  - Kept existing green/yellow/red semantics unchanged.
- `tests/test_project_form_ui.py`
  - Updated assertions for embedded subsection behavior.
  - Added checks for Geometry 3-column rendering and InfoBar subsection toggle behavior.

#### Manual test checklist
- Fullscreen:
  - open PROJECT page
  - verify InfoBar is compact and chips remain one line (`+N` on overflow)
  - open one Geometry + one Mesh section; page should avoid vertical scrollbar in normal use.
- Windowed/restore-down:
  - verify Geometry and Mesh keep `2:1` width relationship with moderate fixed center gap
  - toggle Issues via InfoBar subsection header (right side), not by overlay/popover.
- Issue navigation:
  - trigger multiple severities
  - open Issues subsection, click a row, verify focus jumps to the target field and correct accordion opens.

### Update 39 (InfoBar Issues Anchoring + Mesh Core Label Contract)
#### What was wrong
- Top InfoBar issues area could clip rows when warnings were present and the toggle looked too heavy.
- Issues width did not reliably expand left up to the Mesh column boundary on resize.
- In `Mesh -> Core`, right-column labels/inputs were not following the same spacing contract as left column, causing cramped label rendering (e.g. `Mesh InterfaceResolution`).

#### What changed
- `app/gui.py`
  - Reworked the issues toggle into a compact `QToolButton`-style header (`Issues` / `Issues (N)`), replacing the oversized framed look.
  - Kept issues embedded inside the InfoBar (no overlay), with left-expanding body animation (`maximumWidth`, `InOutCubic`).
  - Added deterministic width calculation against Mesh column boundary:
    - computes target expanded width from right issues anchor to Mesh column left edge on resize.
  - Increased internal panel resilience:
    - scroll area keeps rows visible (no clipping)
    - issue rows use elided text with full tooltip.
- `ui/form_builder.py`
  - Added `ElidedFixedLabel` for non-wrapping, elided labels with tooltips.
  - Updated `Mesh -> Core` grid to a strict two-column row contract for both sides:
    - fixed label width
    - fixed label-to-input gap
    - matched spacing left/right so labels no longer wrap under inputs.
- `ui/theme.py`
  - Styled compact issues toggle (`QToolButton`) and adjusted embedded issues panel text emphasis for readability.

#### Verification
- `python -m py_compile app/gui.py ui/form_builder.py ui/theme.py`
- `python -m unittest tests.test_project_form_ui -v`

## 2026-02-15 - Runner Harness hardening pass (Phase 1+2 and Phase 3 kickoff)

Commits:
- `55a338c` docs: add runner status audit and capability matrix
- `c18f63b` runner-test: add isolated workspace layout and strict cleanup guards
- `cbafcb5` runner-test: add persistent runner_test.sqlite schema and store
- `a2e2266` runner-test: add harness skeleton and CLI run entry
- `f89601f` runner-test: implement full E2E harness with fast profile and hard validations

Highlights:
- Added isolated `runner_test_workspace` with strict guarded cleanup (absolute path + workspace boundary checks).
- Added dedicated `runner_test.sqlite` with test-run telemetry (`test_runs`, `test_run_steps`, `ui_observations`, `artifacts`, `validations`) plus project-compatible run/graph tables.
- Added `runner-test run` CLI command and sample case model wiring.
- Upgraded harness from dry skeleton to full ATH -> AKABAK(UIA) -> VACS(UIA) -> ingest -> validate -> safe clean pipeline.
- Added `runner_test_profile=fast` overrides for low-resolution/quick test execution and persisted effective overrides in DB records.
- Added hard export/data validation checks (size, point thresholds, monotonic x, finite values, zero-series, graph-kind mismatch).
- Added central state-based `wait_until` backoff utility and replaced key fixed sleeps in AKABAK/VACS flows.
- Removed screenshot capture from runner watchdog flow; diagnostics remain UIA/control-dump based.
- Added UI contract stubs under `ui_contracts/akabak` and `ui_contracts/vacs`.

Validation executed:
- `python -m py_compile app/runner_test_harness.py app/runner_test_profiles.py app/ui_automation/waits.py`
- `python -m unittest tests.test_runner_test_workspace tests.test_runner_test_db tests.test_runner_test_profiles tests.test_runner_test_harness tests.test_cli_runner_test tests.test_ui_waits tests.test_vacs_export_pipeline tests.test_runtime_orchestrator tests.test_cli_run_sample tests.test_cli_runs_tools tests.test_ui_automation_contracts -v`

## 2026-02-15 - Runner real VM pass (contract-first AKABAK stabilization)

### Update 40 (Real E2E run + deterministic AKABAK open/import hardening)
#### Why
- Real VM E2E failed in AKABAK project-open stage with incomplete diagnostics.
- AKABAK had a startup blocker window (`TForm_ExampleFiles`) and a modal interpreter/open-file chain that needed strict non-visual contracts.

#### What changed
- `app/akabak_driver.py`
  - Switched AKABAK session startup to `prefer_start=True` to avoid attaching stale external processes.
  - Added deterministic startup modal handling:
    - detect `TForm_ExampleFiles` child window
    - close via handle-based `WM_CLOSE`
    - wait for disappearance (no blind sleeps).
  - Replaced fragile `Ctrl+O` open attempt with command-driven ABEC import flow:
    - send `WM_COMMAND` (`Import ABEC project`, id `113`)
    - wait for interpreter (`TForm_Interpreter`)
    - trigger `Open ABEC Project` control using non-visual keyboard message path
    - wait for open-file dialog (`#32770`) and set filename (`SetDlgItemTextW` id `1148`)
    - hard-fail if open dialog does not close after non-visual confirmation attempts.
  - `import_if_needed()` now handles interpreter state:
    - detects `Start Importing`
    - triggers via non-visual key message and waits for interpreter closure.
  - Error messages now include actionable detail (`repr`) instead of empty exceptions.
- `app/ui_contracts/window_signatures.py`
  - Added AKABAK signatures:
    - `akabak_interpreter_window` (`TForm_Interpreter`)
    - `akabak_open_file_dialog` (`#32770`, `Edit(1148)`, `Button(1)`)
  - Updated main/successor class regexes to real VM classes (`TForm_Main`, `TForm_DatMain`, broader progress/export dialog classes).
- `ui_contracts/akabak/solve_flow.contract.json`
  - Added interpreter + open-file required window contracts.
  - Added startup modal rule for `TForm_ExampleFiles`.
- `app/ui_automation/session.py`
  - Added `prefer_start` option for deterministic session ownership.
- `app/vacs_driver.py`
  - Enabled `prefer_start=True` for isolation parity with AKABAK.

#### Validation
- Unit tests:
  - `python -m unittest tests.test_runner_test_harness tests.test_cli_runner_test tests.test_ui_automation_contracts -v`
- Syntax checks:
  - `python -m py_compile app/akabak_driver.py app/ui_automation/session.py app/ui_contracts/window_signatures.py app/vacs_driver.py app/cli.py app/runner_test_harness.py app/ui_automation/discover.py app/ui_automation/watchdog.py`
- Real VM E2E:
  - `python -m app runner-test run --case smoke_fast --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`
  - `test_run_id`: `6bcfdb6e-916d-4762-8791-725c1d81c887`
  - Result: `failed` at AKABAK open-project with explicit non-visual dialog-close blocker:
    - `ABEC open-file dialog did not close after non-visual confirmation attempts.`

#### Additional hardening in same pass
- `app/runner_test_harness.py`
  - Register AKABAK started PID immediately after open/connect (not only after solve completion), so failing open/import runs are still process-tracked.
  - `safe_clean` now executes explicit started-PID teardown attempts and logs `process_cleanup` telemetry per PID.
- `app/ui_automation/session.py`
  - `close()` now force-terminates only harness-started pywinauto processes when graceful closure is insufficient.

#### Artifacts
- Failure report updated:
  - `docs/Runner_E2E_Failure_Report.md`
- UI dump evidence:
  - `runner_test_workspace/logs/6bcfdb6e-916d-4762-8791-725c1d81c887/ui_discover/akabak_discover_tree_20260215_034947.json`

## 2026-02-15 - Runner hardening pass (legacy evidence + open-dialog micro-harness)

### Update 41 (Legacy evidence extraction)
#### What changed
- Added semantic legacy behavior extraction (read-only source analysis):
  - `docs/LEGACY_RUNNER_BEHAVIOR.md`
  - `docs/legacy_runner_actions.json`
- Captured AKABAK/VACS semantic sequences, modal/dialog inventory, success signals, and known failure classes.
- Explicitly documented prohibited legacy mechanisms (visual automation, tab-count macros) as non-adopted evidence only.

#### Validation
- JSON validity check:
  - `python -m json.tool docs/legacy_runner_actions.json`

### Update 42 (Open-dialog-only harness + CLI)
#### What changed
- Added micro-harness mode for AKABAK open dialog only:
  - `app/runner_test_harness.py`: `run_runner_test_open_dialog_only(...)`
  - `app/cli.py`: `runner-test open-dialog-only` command
- Added persistent DB telemetry for micro-harness runs:
  - `test_runs`, `test_run_steps`, `ui_observations`, `artifacts`, `validations`
- Added tests:
  - `tests/test_runner_test_harness.py`
  - `tests/test_cli_runner_test.py`

#### Validation
- `python -m unittest tests.test_runner_test_harness tests.test_cli_runner_test`

### Update 43 (AKABAK open-dialog contract/handler hardening)
#### What changed
- Updated AKABAK open-file contract and selector requirements:
  - `ui_contracts/akabak/solve_flow.contract.json`
  - `app/ui_contracts/window_signatures.py`
- Implemented deterministic tier ladder in AKABAK open-file submit:
  - Tier A UIA value/invoke
  - Tier B Win32 message path
  - Tier C scoped keys with focus verification
- Added hard postcondition:
  - dialog closed AND project-loaded signal present

#### Validation
- `python -m py_compile app/akabak_driver.py app/ui_contracts/window_signatures.py`
- `python -m unittest tests.test_runner_test_harness tests.test_cli_runner_test tests.test_ui_automation_contracts`

### Update 44 (Failure diagnostics + persistence)
#### What changed
- Added open-dialog failure diagnostics dump files (`json` + `txt`) in AKABAK log dir.
- Persisted diagnostics into `runner_test.sqlite` as artifacts + UI observations.
- Added docs:
  - `docs/AKABAK_OPEN_DIALOG.md`

#### Validation
- `python -m py_compile app/akabak_driver.py app/runner_test_harness.py`
- `python -m unittest tests.test_runner_test_harness tests.test_cli_runner_test tests.test_ui_automation_contracts`

### Update 45 (Real VM stabilization results)
#### What changed
- Stabilized AKABAK open-dialog trigger path by adding main-menu deterministic open fallback (`File->Open project...`) before interpreter fallback.
- Added fail-fast import modal detection in `import_if_needed` with modal detail capture and deterministic primary-button invoke.
- Updated run result docs:
  - `docs/Runner_E2E_Results.md`
  - `docs/Runner_E2E_Failure_Report.md`

#### Real VM runs
- Open-dialog micro-harness, repeats=5:
  - command: `python -m app runner-test open-dialog-only --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --abec-path "runner_test_workspace\\tmp\\real_abec\\ath\\Project.abec" --repeats 5 --workspace-root "runner_test_workspace"`
  - run_ids: `b052b8fd-bdc7-410d-b860-dab479ae55ce`, `8780c294-1ccb-49ea-b1e2-65eb7ee294fb`, `875bcd90-2248-42d2-b5aa-9cb2c7685bc6`, `35afe2b6-ddf2-4b09-aadc-7a1645000058`, `accdf7e0-9960-406f-b9b7-bbf83fba9d57`
  - result: 5/5 succeeded
- Full E2E smoke, repeats=1:
  - command: `python -m app runner-test run --case smoke_fast --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`
  - run_id: `b0bdcff9-ae45-4915-84ac-48862af5a058`
  - result: failed fast with import modal `Cannot find Mesh-File ...\ath\ath.msh`

### Update 46 (Import Start/Apply micro-harness + deterministic postcondition)
#### What changed
- AKABAK import flow hardened to contract-first primary path:
  - `Start Importing` -> wait Apply ready -> `Apply`
  - hard postcondition: `interpreter_closed` OR `start_button_disabled`
  - deterministic modal classification and fail-fast on missing mesh modal
- Added import failure diagnostics dump in AKABAK driver:
  - `import_failure_<timestamp>.json`
  - `import_failure_<timestamp>_main_window.txt`
  - `import_failure_<timestamp>_interpreter_window.txt`
- Added new micro-harness + CLI:
  - `runner-test import-start-apply-only`
  - DB persistence for steps/validations/artifacts/ui observations
- Extended full E2E AKABAK exception persistence to include both open-dialog and import diagnostics.
- Updated docs/contracts:
  - `ui_contracts/akabak/solve_flow.contract.json`
  - `docs/AKABAK_OPEN_DIALOG.md`
  - `docs/RUNNER_TEST_HARNESS.md`
  - `docs/RUNNER_STATUS.md`
  - `docs/Runner_E2E_Results.md`
  - `docs/Runner_E2E_Failure_Report.md`

#### Validation
- Static/tests:
  - `python -m py_compile app\\akabak_driver.py app\\runner_test_harness.py app\\cli.py tests\\test_runner_test_harness.py tests\\test_cli_runner_test.py`
  - `python -m unittest tests.test_runner_test_harness tests.test_cli_runner_test`
- Real VM run (`import-start-apply-only`, repeats=5):
  - command: `python -m app runner-test import-start-apply-only --abec-path "runner_test_workspace\\tmp\\real_abec\\ath\\Project.abec" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --repeats 5 --workspace-root "runner_test_workspace"`
  - run_ids:
    - `4aa8f411-0769-4939-b4ac-b789452d275a`
    - `75c0323f-c1a8-44f5-b305-bf8114bcef76`
    - `7821d89f-f445-4da1-9c97-33ffa505b49a`
    - `63ec0d8e-3723-49a3-852e-f5b6b25fe4d3`
    - `6f0568ce-139b-4ac7-ad15-bb1b0d69eef7`
  - result: 0/5 success, but deterministic classification in all 5 runs (`Cannot find Mesh-File ...\\ath\\ath.msh`)
- Real VM full E2E smoke (latest guard check):
  - command: `python -m app runner-test run --case smoke_fast --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`
  - run_id: `9bdda5f1-904e-4d71-acee-77eb96107aa5`
  - result: failed fast at `pre_akabak_guard_missing_mesh_artifact`

### Update 47 (LE driving audit + post-ATH repair contract)
#### What changed
- Added focused audit note:
  - `docs/LE_DRIVING_AUDIT.md`
- Implemented centralized post-ATH LE repair helper:
  - `app/ath_driver_assets.py`
  - copy `generic25.txt` into ABEC folder (hash-aware)
  - patch `Project.abec` idempotently to `Scriptname_LEScript=generic25.txt`
  - fail-fast assertions and optional diagnostics snapshots
- Wired repair into:
  - `app/runner_test_harness.py`
  - `app/runtime_orchestrator.py`
  - `app/services.py`

#### Validation
- `python -m py_compile app\\ath_driver_assets.py app\\runner_test_harness.py app\\runtime_orchestrator.py app\\services.py app\\cli.py app\\akabak_driver.py`
- `python -m unittest tests.test_m5_planner_renderer -q`

### Update 48 (LE repair/import micro-harness + CLI)
#### What changed
- Added new micro-harness:
  - `runner-test le-repair-import-only`
  - optional ATH run (`--ath-cfg-path`) or reuse existing ABEC (`--abec-path` / `--reuse-export-dir`)
  - persists LE repair artifacts + assertions + AKABAK import telemetry
- Added CLI integration:
  - `app/cli.py`
- Added docs:
  - `docs/LE_REPAIR_IMPORT_HARNESS.md`
- Added tests:
  - `tests/test_ath_driver_assets.py`
  - extended `tests/test_runner_test_harness.py`
  - extended `tests/test_cli_runner_test.py`

#### Validation
- `python -m py_compile app\\ath_driver_assets.py app\\runner_test_harness.py app\\cli.py`
- `python -m unittest tests.test_ath_driver_assets tests.test_runner_test_harness tests.test_cli_runner_test -q`

### Update 49 (RadImp diagnosis classification + AKABAK watchdog capture)
#### What changed
- Added AKABAK watchdog event capture for deterministic diagnosis:
  - `app/akabak_driver.py` (`watchdog_events`)
- Added E2E RadImp diagnosis stage in harness:
  - validation row `radimp_diagnosis`
  - classes:
    - `sources_muted_dialog_seen`
    - `solve_succeeded_radimp_all_zero`
    - `observation_misconfigured_or_wrong_export`
    - `radimp_nonzero_or_not_flagged`
    - `radimp_not_requested`
- Increased import wait ceilings from 30s to 60s in `import_if_needed` to reduce late-dialog timeouts without fixed sleeps.

#### Real VM run
- command:
  - `python -m app runner-test le-repair-import-only --repeats 5 --abec-path "C:\\Horns\\test\\ABEC_FreeStanding\\Project.abec" --akabak-exe "C:\\Program Files (x86)\\RDTeam\\AKABAK\\AKABAK.exe" --ath-exe "C:\\Tools\\ATH\\ATH.exe"`
- result:
  - LE repair assertions passed
  - failures were in AKABAK import postcondition path (intermittent apply-timeout / no explicit LE text in UI tree)
  - run_ids:
    - `0bfde103-6a72-49f7-922b-20ec65c19396`
    - `a16e4051-bbb4-4cfa-8f57-b10c5827bf19`
    - `0a496085-c365-4120-8930-253fcbd778cd`
    - `4a92e571-222c-4188-b669-57ae4beda83b`
    - `33a7dc2c-2018-42bf-bfec-844230fd2f88`

### Update 50 (Recovery: manual interrupt classified as aborted)
#### What changed
- Manual-interrupt recovery applied for run:
  - `f5688841-63bb-40dd-85e0-d2b78d97ba2e`
- Updated Runner_Test DB state:
  - `test_runs.status = aborted`
  - `test_runs.notes += manual_interrupt_user_error`
  - added `test_run_steps.step_name = manual_recovery_mark`
- Added recovery documentation:
  - `docs/RUNNER_RECOVERY_NOTE.md`

#### Validation
- Verified run status is `aborted` in `runner_test_workspace/db/runner_test.sqlite`.
- Verified process ledger is empty at recovery time (`runner_test_workspace/logs/process_ledger.json`).
- Verified no non-ledger AKABAK process was force-terminated by recovery logic.

### Update 51 (Baseline case + ATH runtime cfg + AKABAK open-dialog diagnostics hardening)
#### What changed
- Added baseline runner-test case:
  - `runner_test_cases/test_cfg_baseline.json`
  - uses `C:\Tools\ATH\test.cfg` + `ath_export_root` hint `C:\Horns`
- Hardened harness preflight telemetry:
  - executable probes (exists/executable/size/mtime)
  - export-root probe (exists/writable)
  - persisted into `test_runs.tool_versions`
- Hardened ATH stage in harness:
  - writes local `input.cfg` and local runtime `ath.cfg` per run
  - persists `ath_runtime_cfg` artifact
  - creates output root folder deterministically so ATH mesh generation works
- Added mesh-missing classification in pre-AKABAK guard:
  - `mesher_missing_meshcmd`
  - `mesher_executable_missing`
  - `mesher_execution_failed`
  - `ath_output_mesh_artifact_missing`
- Tightened AKABAK open/import diagnostics:
  - interpreter button states + report text readback in import failure dumps
  - open-dialog attempts now log postcondition snapshot (`dialog_closed`, titles, signal, methods)
  - open dialog control dump now captures real `#32770` tree with controls

#### Real VM runs in this pass
- Full baseline run (latest): `15aaccb8-6120-49ed-8b71-74b65c90a3dd`
  - ATH + LE repair + mesh guard are green
  - blocked at AKABAK open dialog close postcondition
- Open-dialog micro runs (strict contract) still red:
  - `6adf03a6-8a20-439d-9958-d854d9872c9e`
  - `1f623ea8-6aa7-4950-a42f-bc8f8861454f`
- Import-start-apply micro run still red:
  - `ea0d03e1-6e1e-4536-b4cb-ceef63c08328`

#### Validation
- `python -m unittest tests.test_ath_driver_assets tests.test_runner_test_harness tests.test_cli_runner_test`
- repeated targeted real VM runs via:
  - `runner-test run --case test_cfg_baseline ...`
  - `runner-test open-dialog-only ...`
  - `runner-test import-start-apply-only ...`

### Update 52 (VACS child-window discovery, 3-round probe)
#### Done
- Executed 3-round VACS discovery pass focused on child windows and context dialogs.
- Captured stable UI signatures and menu taxonomy from real imported-graph state.
- Added documentation:
  - `docs/VACS_WINDOW_DISCOVERY.md`
- Key observed classes/signatures:
  - main: `TForm_DatMain`
  - workspace: `MDIClient` (`Arbeitsbereich`)
  - child graph windows: `TForm_DatGraph`, `TForm_DatContour`
  - editor windows: `TForm_Editor`
  - context/modals: `TForm_Confirm`, `#32770` (`Warning`, Save project prompt with `Yes/No/Cancel`)

#### Real VM evidence
- Reimport runs used for starting state:
  - `runner_test_workspace/logs/interim_reimport/vacs_interim_reimport_20260215_214604.json`
  - `runner_test_workspace/logs/interim_reimport/vacs_interim_reimport_20260215_215451.json`
- UI-discover artifacts:
  - `runner_test_workspace/logs/vacs_probe/round1/...`
  - `runner_test_workspace/logs/vacs_probe/round2/...`
  - `runner_test_workspace/logs/vacs_probe/round3/ui_final/vacs_discover_tree_20260215_220355.json`

#### Known instability
- Deep interactive probe paths (child activation + immediate export-dialog interaction) timed out in rounds 1/2.
- This is logged as a probe robustness issue; next pass should isolate it in a dedicated `vacs-export-only` micro-harness with strict per-step timeout contracts.
