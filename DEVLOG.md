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
