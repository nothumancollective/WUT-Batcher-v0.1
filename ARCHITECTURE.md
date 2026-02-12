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
  - Core JSON-backed data models: `AppConfig`, `ProjectConstraints`, `Project`, `Batch`, `DatasetManifest`.
  - Sweep definitions represented by `SweepSpec` + `ParamSelection`.
- `app/batch_planner.py`
  - Deterministic sweep expansion with `single` and `combined` modes.
  - Job count calculation.
- `app/compat_engine.py` + `app/knowledge/ath/*.json`
  - Rule-based parameter visibility, sweepability, validity report.
  - Runner-mode restrictions for fixed source block.
- `app/cfg_renderer.py`
  - CFG rendering with mandatory AKABAK-compatible source block enforcement.
- `app/dataset_pipeline.py`
  - Imports `Result_*.txt` into SQLite (`versions`, `measurements`, `measurement_meta`) with manifest-based incremental updates.
- Tests
  - `tests/test_m2_compat_engine.py`
  - `tests/test_m5_planner_renderer.py`

### Present but Incomplete vs Target
- `app/path_resolver.py`
  - Uses legacy path style (`Project_<id>/batches/Batch_<id>/...`), not target unified `projects/<project_id>/.../versions/<version_id>/...` layout.
- `app/cli.py`
  - Only `doctor`, `batch job-count`, `dataset build/update` are active.
  - No complete project/batch/version lifecycle orchestration in current repo snapshot.

### Missing in Current Repo Snapshot
- No integrated orchestrator that executes full ATH -> AKABAK -> VACS per `Version`.
- No current `Runner/` directory in this snapshot, despite references in docs.
- No first-class `VersionSpec` resolver output with explicit `unset` semantics.
- No project-wide version ID allocator/registry in storage layer.
- No tidy file-based dataset writer (CSV/Parquet) for normalized rows as primary output format.
- No project table writer in target format.
- No machine-readable compatibility registry with explicit fields
  (`rule_id`, `description`, `scope`, `condition`, `action`, `severity`, `evidence`).

## Gap List / Backlog
1. Add explicit domain entities for resolved versions and batch definitions in execution context.
2. Implement central resolver:
   - Input: `Project.constraints` + `Batch`.
   - Output: deterministic `VersionSpec[]`.
   - Exact `single` and `combined` behavior.
   - Preserve "empty field => omitted parameter" as explicit `unset` markers.
3. Add blocking validation layer:
   - Project constraints validity.
   - Batch parameter visibility/sweepability compatibility against constraints.
   - Version-level fatal validity blocking.
4. Implement target project storage layout:
   - `projects/<project_id>/project.json`
   - `projects/<project_id>/batches/<batch_id>/batch.json`
   - `projects/<project_id>/versions/<version_id>/...`
   - `projects/<project_id>/dataset/...`
   - `projects/<project_id>/tables/...`
   - `projects/<project_id>/_logs/...`
5. Implement deterministic project-wide version ID allocation.
6. Implement tidy dataset writer:
   - normalized curve rows
   - ATH dimension features
   - schema file
   - CSV + optional Parquet.
7. Implement minimal project table export.
8. Add runner wrappers (`AthRunner`, `AkabakRunner`, `VacsRunner`) with logging, status, timeout, retries.
9. Add smoke tests from resolver to file outputs.

## Milestone Definition (next)
- Create project with immutable constraints persisted.
- Create batch with base values, sweeps, sweep mode, sim/export settings.
- Resolve deterministic `VersionSpec` list with project-wide IDs.
- Materialize per-version folders with placeholders and logs.
- Write tidy dataset with at least version metadata + resolved parameters (without real simulation).
