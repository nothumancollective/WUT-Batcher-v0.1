# Geometry and driver foundation baseline

Baseline commit: `725f58c9f45399aecd5df4fd40af082fa3ea9aa6`

## Existing ownership map

| Concern | Current authority | Compatibility constraint |
|---|---|---|
| Library root/index | `StorageManager`, `library.sqlite` | One portable library; no UI-private catalogue |
| Project manifests and paths | `ProjectRepository`, `project.json` | Existing project folder IDs and paths are stable |
| Batch/version manifests | `ProjectRepository`, `batch.json`, `version.json` | IDs are project-wide and existing artifacts refer to them |
| Dataset/results | `SqlDatasetStore` / `TidyDatasetWriter`, project SQLite | Add columns/tables; do not rewrite results |
| Planning | `materialize_batch_plan`, `version_resolver` | Immutable materialized plans are reused |
| Runtime | `run_batch_pipeline` | Validated ATH/AKABAK/VACS sequence remains unchanged |
| LE seed | harness registry `generic25` plus installed ATH asset | Promote through central library, retain exact bytes/hash |
| UI | `ProjectManagerWindow`, `MainWindow`, `ProjectPage`, `BatchPage` | Add geometry context without redesigning navigation |
| Analyzer | project/batch/version/run SQL identities | Geometry is an additive filter/context |

The canonical path layout currently keeps batches and versions directly below
the project. ADR-003 intentionally preserves it. Logical geometry ownership is
therefore the migration boundary, not a filesystem move.

## Read-only active-library inventory

The existing `library audit --scan-siblings` command was run read-only before
implementation. It reported eight canonical active projects, no structural
errors and 37 already-known duplicate immutable-plan warnings. Those historical
versions have distinct run/export ownership and are not cleanup candidates in
this work. Detached/sibling libraries were reported only. No user library file
was created, migrated, repaired or deleted.

Focused baseline tests covering project storage, manager/form/cards, batch UI,
compatibility and runtime orchestration: `137 passed, 8 skipped`.

