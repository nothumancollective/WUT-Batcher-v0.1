# ADR-003: Additive storage and migration

Status: accepted, 2026-08-01

## Decision

Geometry and driver storage are additive to the existing central storage
authorities. Project databases gain geometry, assignment and run-snapshot
tables/columns. `library.sqlite` gains the central driver catalogue. No second
UI-owned database or parallel library is introduced.

Existing physical paths remain unchanged:

```
<project>/batches/<batch_id>
<project>/versions/<version_id>
<project>/runs/...
<project>/exports/...
```

Geometry scope is recorded in manifests and SQLite. New geometry metadata is
stored under `<project>/geometries/<geometry_id>/geometry.json`; this directory
does not own or relocate historical batches/versions. Driver LE assets use
`<library>/drivers/assets/sha256/<hash>` and are referenced by hash.

## Migration

Migration is schema-versioned, transactional for SQLite, idempotent and safe to
resume. Every existing project receives exactly one deterministic legacy
geometry ID derived from its immutable project identity. Existing batches,
versions and runs are assigned to it without changing their IDs or paths.

The migration API supports dry-run and emits a report containing proposed
changes, warnings, database backup location/hash and before/after schema state.
Backups are created before write mode. Tests operate only on copied fixtures;
the active user library is not bulk-migrated in this development round.

Foreign keys are enabled for new normalized tables. Historical denormalized
tables retain additive nullable geometry columns to avoid destructive table
rebuilds. Archive state is a timestamp/flag, never physical deletion.
