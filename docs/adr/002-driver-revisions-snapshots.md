# ADR-002: Driver identity, revisions and snapshots

Status: accepted, 2026-08-01

## Decision

`DriverDefinition` owns stable identity (`driver_id`, manufacturer, model,
variant, kind and origin). `DriverRevision` is append-only and owns technical
values, provenance, explicit units, completeness state and an optional LE
network asset. Editing creates a new revision. Missing values remain null and
are never replaced by invented defaults.

A simulation stores a canonical immutable `DriverSnapshot` containing the
definition identity, exact revision payload, schema version, revision hash and
the effective LE-network bytes/hash. Runs never depend on a mutable library
lookup after planning.

`generic25` is seeded as built-in/read-only. Its installed LE file is copied
into library-owned content-addressed storage when available; the copy and
source are hashed. No T/S-to-LE conversion is inferred.

## Supported kinds and provenance

Kinds are `compression_driver`, `cone_driver`, `generic_test` and
`future_unknown`. Origin is `built_in`, `user`, or `imported`. Provenance stores
source name/URL, document/file hashes, licence/use note and trust state. JSON
import/export is versioned and returns structured validation findings.

## Invariants

- Published revisions and snapshots are immutable.
- Built-in definitions/revisions cannot be edited or archived by CRUD calls.
- Every numeric parameter declares its SI unit (or an explicit source unit plus
  normalized SI value).
- Unknown fields survive import/export in an extensions object.
