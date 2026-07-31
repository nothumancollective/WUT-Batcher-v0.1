# Project Library Design

Date: 2026-02-25
Status: implemented baseline (feature-flag default ON)

## 1) Goal

Introduce a portable, user-configurable Project Library root that contains only user project data plus one library-scoped index DB, while keeping application/runtime/tool installations outside the library.

## 2) Canonical library layout

```text
<LibraryRoot>/
  library.json
  library.sqlite
  projects/
    P0001__<project_uid>/
      project.json
      db/
        project.sqlite
      batches/
      versions/
      runs/
      exports/
      logs/
```

Notes:
- `library.sqlite` is the authoritative library index and counter state store.
- `library.json` is lightweight metadata for quick inspection/portability diagnostics.
- `projects/` is mandatory as the project container directory.

## 3) Identity model

### Library identity
- `library_uid`: UUIDv4, generated once per library root.
- Stored in `library.sqlite` metadata table and mirrored in `library.json`.

### Project identity
- `display_number`: user-facing counter per library root (`P0001`, `P0002`, ...).
- `project_uid`: UUIDv4 (globally unique, migration-safe).
- Folder name: `<display_number>__<project_uid>`.

Choice rationale:
- ULID dependency is not present in current runtime dependencies.
- UUIDv4 is available in stdlib and satisfies global uniqueness requirements.

## 4) Counter behavior

- Counter state is library-scoped (`project_counter_next`) in `library.sqlite`.
- New library root initializes `project_counter_next = 1`.
- Switching to a different/new root uses that root's independent counter state.
- Resetting display counter by changing root does not risk collisions because `project_uid` remains globally unique.

## 5) Library content boundary

### Allowed inside library
- Project folders and project-owned data artifacts only:
  - manifests, project DB, run outputs, exports, logs, generated cfg snapshots.
- Library metadata/index:
  - `library.sqlite`, optional `library.json` mirror.

### Not allowed inside library
- App code, bundled runtime dependencies, virtualenv, binaries/tool installations.
- Machine-specific application settings (tool executable paths, UI prefs not tied to project data).
- Temporary process-level caches unrelated to project artifacts.

## 6) Portability model

- Copying `<LibraryRoot>` to another machine preserves all project data and library index.
- App-level settings remain machine-local and can point to moved/copied library root.
- Tool paths are resolved from local app settings on each machine.

## 7) Coexistence and migration plan

1. Introduce StorageManager/LibraryManager as central path + metadata authority.
2. Feature flag `USE_PROJECT_LIBRARY_STORAGE` controls storage mode.
3. When flag ON:
   - resolve paths only through StorageManager,
   - write library DB as `library.sqlite`,
   - create projects under `projects/P0001__<uid>/...`.
4. Keep legacy cleanup/data-governance workflows callable during transition.
5. Provide non-destructive coexistence:
   - no automatic destructive migration,
   - legacy roots remain openable.
6. Runtime default:
   - Project Library storage is ON by default.
   - Emergency legacy fallback is explicit: set `USE_PROJECT_LIBRARY_STORAGE=0`.

## 8) Invariants

- Every project manifest must include: `library_uid`, `project_uid`, `display_number`, `schema_version`, `created_at`.
- Every project DB path must be inside project folder (`db/project.sqlite`).
- Every runtime/export/log path for project runs must resolve inside that project folder (except explicit external tool execution paths).
- Path generation must be centralized in one authoritative storage module.

## 9) Library Root Selection Rules (GUI vs tests/CLI)

- GUI/default app settings:
  - Library root is read from user settings store (`~/.wut_batcher/config.json`).
  - Default when unset is Desktop `WUT Project Library` (fallback: `~/WUT Project Library`).
- Command/test overrides:
  - CLI options that accept `--library-root` (`run-sample`, `dataset-sync-global`, `compat-verify`) now use isolated temporary settings stores.
  - These command-scoped overrides must not persist to user GUI settings.
- Safety rule:
  - The app must not silently rewrite a user’s configured library root just because a test/sample command used an alternate root.

## 10) Read-only operational audit (2026-07-31)

Run the structural audit without opening, initializing or migrating a library:

```powershell
python -m app library audit --scan-siblings
```

Use `--library-root <path>` to inspect a non-active root and `--report-path
<path>` to store JSON outside the library. The command never repairs or deletes
data. It reports:

- canonical root markers and project folder/manifest identity;
- preferred versus legacy project database placement;
- batch, version, normal-run and auxiliary-run directory counts;
- duplicate immutable version plans and their run/export ownership;
- sibling folders that look like libraries;
- detached `library.sqlite` candidates whose authority is unknown.

### Validation-machine findings

The active root `Desktop\WUT Project Library` is canonical and contains seven
projects. There is one root index (`library.sqlite`), no `global.sqlite`, and no
project contains both preferred and legacy databases. `PRAGMA quick_check` was
run against copies of all eight databases (one library plus seven project DBs)
and returned `ok` for each copy.

The audit reports 37 historical duplicate-plan groups: 28 in P0003 and three
each in P0005, P0006 and P0007. They were retained because individual versions
can own different run/export history. Current batch materialization reuses an
equivalent stored version, preventing new duplicate cohorts without rewriting
history.

Several February QA/E2E library roots, a detached `Desktop\projects` container
and a detached `Desktop\library.sqlite` also exist. They are inactive and were
only reported. Their deletion or migration requires an explicit, separately
reviewed user decision.
