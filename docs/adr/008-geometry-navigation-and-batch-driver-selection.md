# ADR-008: Geometry navigation and batch driver selection

Status: accepted, 2026-08-02

## Context

Geometry and Driver are first-class domain objects, but the original foundation
exposed both through a modal reached from Project. It also resolved the Geometry
default Driver while saving a Batch and embedded that full snapshot in the
Batch. This made the normal workflow hard to discover and blurred the boundary
between a reusable Batch choice and an immutable Run record.

## Decision

The persistent lower navigation is `Project -> Geometry -> Batch -> Analyse`.
The Geometry page is the single management surface for Geometry CRUD, ATH
parameter context and the Geometry default Driver. The old Project action is a
compatibility shortcut that activates this page; it does not open another
manager implementation.

The Batch page owns only the selection policy:

- `geometry_default` (default): use the selected Geometry's current default;
- `explicit_override`: use one exact append-only Driver revision.

It shows the effective revision, completeness, LE readiness and revision hash,
and links to the canonical Driver Library. Driver creation, revisioning,
provenance, import/export and LE assets remain exclusively in that library.

At Run start the service resolves exactly one effective revision in this order:

1. explicit Batch override;
2. current Geometry default;
3. documented compatibility fallback: a preserved legacy Batch revision, then
   built-in `generic25` when available.

The Run receives a newly verified immutable `DriverSnapshot`. Run persistence
records the snapshot/hash and a `selection_source` token (`batch_override`,
`geometry_default`, `legacy_batch_revision`, or `legacy_generic25`). Historical
Run snapshots are never looked up again through mutable Geometry or Batch data.

## Storage and compatibility

Batch JSON gains additive `driver_selection_mode` and
`driver_override_revision_id` fields. Existing `driver_revision_id` and
`driver_snapshot` fields remain readable for legacy compatibility but are not a
second editable Driver store. A Batch lacking the new fields is interpreted as
`geometry_default`; its old revision participates only in fallback when the
Geometry has no default.

Project/global SQLite Batch rows gain nullable selection mode and override
columns. `run_driver_snapshots` gains nullable `selection_source`. Migrations
use idempotent `ALTER TABLE ADD COLUMN` checks; no paths or historical rows are
moved or rewritten.

## Invariants

- Geometry management has one service-backed UI surface.
- A Batch references at most one override revision and never owns Driver data.
- Changing a Geometry default can affect a future default-mode Run, never an
  already persisted Run snapshot.
- An archived/missing/incomplete effective revision is reported before native
  execution; no technical values are synthesized.
- SpeakerAssembly, DSP, crossover and CAD concerns remain out of scope.
