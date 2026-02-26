# Batch Lineage Graph

Date: 2026-02-26  
Status: Phase 0 archaeology completed, implementation approach selected

## Phase 0 Repository Archaeology

## Scope and constraints
- Goal: project-page lineage graph with root `Constraints`, batch nodes, and provenance edges.
- Hard constraints:
  - Native Qt only (`QGraphicsView`/`QGraphicsScene`), no web engine.
  - Deterministic lineage from DB (not folder scans).
  - Keep existing storage authorities (`StorageManager` + `project_storage` + `sql_dataset_store`) and existing main flows intact.

## Docs audit (authoritative sources)

## Project page/dashboard UI authority
- [docs/PROJECT_UI.md](../PROJECT_UI.md)
  - Dashboard target and wiring baseline: `DashboardPage` is the "Project page" target (`Dashboard Redesign Preflight`, `Dashboard Layout Refresh`, `Dashboard Constraints Grid Refresh`).
  - Existing constraints summary grid behavior and dashboard action contracts are documented there.

## Analyzer iterate behavior authority
- [docs/analyzer/CHANGELOG.md](../analyzer/CHANGELOG.md)
  - `2026-02-25 (Iterate tab scaffold + centered analysis tab group)`
  - `2026-02-25 (Iterate action wired to child-batch creation)`
  - Confirms iterate path currently creates a child batch from pinned version `version_params`, then opens Batch mode.

## Storage and DB authority
- [docs/release/project-library.md](../release/project-library.md)
  - Canonical library/project DB placement and storage path policy.
- [docs/RUNNER_STATUS.md](../RUNNER_STATUS.md)
  - Batch/Version/Run semantics and explicit path/DB references.
  - Reinforces preserving semantics and storage boundaries.

## Code audit (entry points and reusable infrastructure)

## Project page + constraints area
- `app/gui.py`
  - `ConstraintSummaryGrid` at line 4966.
  - `DashboardPage` at line 5268.
  - `MainWindow.refresh_dashboard` at line 13861.
  - Current dashboard actions wiring:
    - `request_new_batch` -> `show_batch` (line 13364)
    - `request_edit_batch` -> `_edit_batch` (line 13365)
    - `request_clone_batch` -> `_clone_batch` (line 13366)

## Batch creation/provenance write paths
- Manual save path:
  - `MainWindow._save_batch` line 13963 -> `OrchestratorService.create_batch(...)` line 3621 (`app/services.py`).
- Iterate path:
  - `MainWindow._iterate_from_analyzer_version` line 14179 (`app/gui.py`).
  - Reads pinned version params via `OrchestratorService.analyzer_list_version_param_rows` line 2638 (`app/services.py`).
  - Creates child via existing `_save_batch`.
- Clone path:
  - `MainWindow._clone_batch` line 14252 (`app/gui.py`) prepares clone draft, then normal save flow.

## Pinned-version source (analyzer iterate tab)
- `AnalysePage` iterate table is populated from rows where `version_pinned` is true (`app/gui.py`, `_update_iterate_table` around lines 10338+).
- Pin state is persisted via analyzer UI prefs (`version_pins_v1`) and applied into run rows before iterate filtering.

## Drawer/overlay pattern to reuse
- `app/gui.py`
  - `_DrawerScrim` line 346.
  - Analyzer compare drawer overlay + animation pattern around lines 7082-7186 and 10638-10706.
- `ui/theme.py`
  - Existing drawer surface/scrim tokens:
    - `AnalyzerCompareDrawer*` selectors around lines 808-833.

## DB schema and migration system
- `app/sql_dataset_store.py`
  - Current schema version constant: line 19 (`SCHEMA_VERSION = "2.7"`).
  - `batches` table DDL in `_init_db` around line 209.
  - Additive migration entrypoint: `_migrate_schema(...)` line 851.
  - Batch upsert op: `_op_upsert_batch(...)` line 1176.
  - Batch payload writers: `register_batch(...)` line 2058 and `write_plan_bundle(...)` line 2113.
- Migration pattern already in use:
  - additive `ALTER TABLE` helpers (`_ensure_versions_columns`, `_ensure_graphs_columns`, etc.) called from `_migrate_schema`.

## Reuse vs extend decision

Decision: reuse existing stack and extend minimally.

- Reuse:
  - `MainWindow`/`DashboardPage` architecture in `app/gui.py`.
  - Existing drawer overlay pattern (`_DrawerScrim`, `QPropertyAnimation`, overlay geometry logic) from Analyzer compare drawer.
  - Existing dual-write project/global DB path through `SqlDatasetStore` and `TidyDatasetWriter`.
- Extend:
  - Batch provenance in project/global `batches` table (Option A style) with additive columns:
    - `parent_batch_id TEXT NULL`
    - `created_via TEXT NOT NULL DEFAULT 'manual'`
    - `created_from_version_id TEXT NULL`
  - Propagate provenance through existing creation entry points (manual/iterate/clone) without changing run semantics.
  - Add a native Qt graph pane (`QGraphicsView`/`QGraphicsScene`) on dashboard workspace right side.
  - Add deterministic in-process layout algorithm (stable ordering by lineage depth + creation order / batch id).

## Non-goals confirmed for this task
- No runner/analyzer data-pipeline redesign.
- No folder scanning for lineage.
- No web engine.
- No alternative storage path outside `project_storage`/`SqlDatasetStore`.

## Phase 1 schema update

Implemented schema direction: Option A (columns on `batches`).

- File: `app/sql_dataset_store.py`
  - `SCHEMA_VERSION` advanced from `2.7` to `2.8`.
  - Base `batches` table DDL now includes:
    - `parent_batch_id`
    - `created_via`
    - `created_from_version_id`
  - Additive migration helper `_ensure_batches_columns(...)` is called in `_migrate_schema(...)` to backfill legacy DBs safely.
  - `upsert_batch` now writes/updates lineage columns.
  - `register_batch` and `write_plan_bundle` now forward lineage payload from `Batch.extra`.
  - New read helper `list_batches_with_lineage(...)` returns deterministic lineage rows from DB.

Rationale:
- Keeps lineage deterministic and local to canonical project/global DB writes.
- Fits existing additive migration pattern (`ALTER TABLE` in `_migrate_schema` helpers).
- Avoids introducing a second lineage storage path.

## Phase 2 provenance write wiring

Creation-point lineage writes are now mapped as follows:

- Manual new/save batch:
  - `created_via='manual'`
  - `parent_batch_id=NULL`
  - `created_from_version_id=NULL`
- Iterate from pinned version:
  - `created_via='iterate'`
  - `parent_batch_id=<source batch id>`
  - `created_from_version_id=<selected version id>`
- Clone:
  - `created_via='clone'`
  - `parent_batch_id=<source batch id>`
  - `created_from_version_id=NULL`

Implementation notes:
- `app/services.py::create_batch(...)` now accepts provenance inputs and stores them in `Batch.extra` for downstream DB writes.
- `app/gui.py::MainWindow` now tracks draft lineage context and forwards provenance through `_save_batch(...)` for manual/clone/run-save paths.
- Analyzer iterate path forwards explicit iterate provenance at child creation call site.
- Behavior is unchanged for run orchestration: no auto-run added by iterate, and run/version semantics are unchanged.

## Implementation plan alignment
- Phase 1: DB provenance columns + migration helper + docs.
- Phase 2: provenance writes at manual/iterate/clone creation points + tests.
- Phase 3: dashboard constraints bar fixed-height + top drawer behavior; 50/50 workspace split with graph pane placeholder.
- Phase 4: lineage graph model/layout/render/interactions.
- Phase 5: validation (DB tests + GUI smoke).
