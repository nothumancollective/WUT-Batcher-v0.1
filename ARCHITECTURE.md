# WUT Batcher Architecture

Date: 2026-02-12
Branch: `wut-batcher/rebuild`

## Scope and Truth Sources
- Primary truth: user specification in this rebuild task.
- Secondary truth: current repository code.
- Tertiary truth: backup/recovery docs.

## Target Domain Model (Soll)
- `Project`: immutable constraints after project start, metadata, storage root.
- `Batch`: base values for variable params, optional sweeps, `sweep_mode` (`single|combined`), simulation/export settings.
- `Version`: fully resolved ATH parameter set + deterministic project-wide unique `version_id`, status, timestamps, artifact paths.

## Required Pipeline (Soll)
1. Build CFG from constraints + resolved variable params.
2. Execute ATH and generate ABEC.
3. Parse ATH terminal dimensions (length/width/height) into tidy dataset + project table.
4. Import ABEC in AKABAK and simulate.
5. Open results in VACS and export configured graphs to TXT.
6. Normalize TXT exports into tidy dataset + project table.
7. Close VACS and AKABAK.
8. Continue with next version.

## Current State (Ist)

### Implemented and Working
- `app/models.py`
  - Core data models plus new execution entities: `VersionSpec`, `ResolutionIssue`, `ResolveVersionsResult`.
- `app/version_resolver.py`
  - Central resolver for `Project.constraints + Batch -> VersionSpec[]`.
  - Exact `single` and `combined` sweep expansion.
  - Explicit `unset_parameters` handling for omitted ATH fields.
  - Blocking compatibility validation against `compat_engine` (project/batch/version).
  - Deterministic version ID allocation with carry-over from existing project versions.
- `app/compat_engine.py` + `app/knowledge/ath/*.json`
  - Rule-based visibility/sweepability/validity.
- `app/compat_rules.py`
  - Machine-readable compatibility export shape:
  - fields: `rule_id`, `description`, `scope`, `condition`, `action`, `severity`, `evidence`.
- `app/project_storage.py`
  - Target layout persistence:
  - `projects/<project_id>/project.json`
  - `projects/<project_id>/batches/<batch_id>/batch.json`
  - `projects/<project_id>/versions/<version_id>/...`
  - `projects/<project_id>/dataset/`, `tables/`, `_logs/`
  - immutable project constraint guard.
- `app/tidy_dataset.py`
  - Tidy CSV writer for:
  - version parameter resolution
  - measurement rows
  - ATH dimension rows
  - schema output + optional parquet output.
  - project-wide table export (`tables/project_versions.csv`).
- `app/batch_orchestrator.py`
  - High-level planning/materialization flow for milestone-ready placeholder pipeline.
- `app/runners.py`
  - `AthRunner`, `AkabakRunner`, `VacsRunner` subprocess wrappers.
  - stdout/stderr/summary logs, exit status, timeout, retry.
  - ATH dimension parser helper (`parse_ath_dimensions`).
- `app/runtime_orchestrator.py`
  - Staged runtime pipeline (`plan -> ATH -> AKABAK -> VACS`).
  - Per-version status updates and ATH dimension write-through into tidy dataset.
- `app/cli.py`
  - New command: `plan materialize` for project+batch resolution and folder materialization.
  - New command: `run pipeline` for staged runtime execution.
- Tests
  - Existing: `tests/test_m2_compat_engine.py`, `tests/test_m5_planner_renderer.py`
  - New: `tests/test_version_resolver.py`, `tests/test_project_storage_and_tidy.py`, `tests/test_compat_rules.py`, `tests/test_runners.py`

### Partially Implemented vs Target
- Runtime orchestration exists as staged subprocess pipeline, but external tool contracts are still generic:
  - ATH stage supports execution + dimension parsing when executable contract is provided.
  - AKABAK and VACS stages are wired as subprocess stages, but UI-specific automation contracts are not yet bound in this snapshot.
- Legacy modules (`app/path_resolver.py`, `app/dataset_pipeline.py`) still use prior storage/import conventions and coexist with new rebuild modules.

### Missing in Current Repo Snapshot
- No `Runner/` directory in this snapshot despite references in older docs; wrappers therefore target generic subprocess contracts only.
- No live UI automation adapter in app layer yet (only isolated runner wrappers).

## Gap List / Backlog (Updated)
1. Bind concrete ATH/AKABAK/VACS CLI/UI invocation contracts from real environment into runtime orchestrator.
2. Add robust per-version state transitions across stage boundaries including recovery/resume semantics.
3. Implement VACS TXT export parsing ingestion in the new tidy writer path (currently legacy importer handles this separately).
4. Add project-table update hooks for imported measurements (currently focus is version metadata + ATH dimensions).
5. Optionally unify or migrate legacy dataset/path modules to the new layout.

## Milestone Definition (next)
- Create project with immutable constraints persisted.
- Create batch with base values, sweeps, sweep mode, sim/export settings.
- Resolve deterministic `VersionSpec` list with project-wide IDs.
- Materialize per-version folders with placeholders and logs.
- Write tidy dataset with at least version metadata + resolved parameters (without real simulation).

Status against milestone: achieved in current rebuild implementation.
