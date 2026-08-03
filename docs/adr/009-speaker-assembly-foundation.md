# ADR-009: Additive SpeakerAssembly foundation

Status: accepted, 2026-08-03

## Context and boundary

Projects already own reusable Geometry objects, Geometry-scoped Batches and a
central revisioned Driver Library. A SpeakerAssembly must arrange several
Geometry instances without changing those authorities or implying coupled
simulation support.

This decision implements identity, immutable Geometry snapshots, transforms,
storage, CRUD and UI only. It does not alter ATH, AKABAK, VACS, Batch Driver
resolution, DSP, crossover, CAD or analyzer semantics.

## Aggregate

`Project -> SpeakerAssembly -> GeometryInstance` is an additive project-local
aggregate. A SpeakerAssembly has a stable opaque `assembly_id`, project ID,
name, description, timestamps, schema version and nullable `archived_at`.
Archiving is a soft state; archived assemblies remain readable.

Each active instance has:

- stable opaque `instance_id` scoped to the Assembly;
- user-facing name and description;
- arrangement `normal` or `coaxial`;
- deterministic zero-based `order_index`;
- reference to an existing project Geometry by `geometry_id`;
- the complete canonical Geometry JSON captured when the instance is added or
  explicitly pointed at another Geometry;
- SHA-256 of that canonical snapshot;
- translation `(x, y, z)` in metres and rotation `(x, y, z)` in degrees.

The snapshot is the immutable semantic reference. Renaming or editing the live
Geometry later does not change an existing Assembly instance. Selecting a
different Geometry creates a new captured snapshot for that instance. Assembly
data never copies Driver definitions or LE assets; future execution must resolve
and snapshot Driver revisions through the existing ADR-008 contract.

## Coordinate and rotation convention

The Assembly frame is right-handed: `+X` is right, `+Y` is up and `+Z` is the
nominal forward/acoustic-axis direction. A Geometry's local frame uses the same
axes with its throat/origin at `(0, 0, 0)` and local `+Z` forward.

Translations are finite SI metre values. Rotations are finite degrees and are
normalized to `[-180, 180)`. They are active, right-hand, fixed-axis rotations
applied in X, then Y, then Z order; for column vectors the composed matrix is
`Rz * Ry * Rx`. The representation may have Euler-angle ambiguity but remains
deterministic. No solver interpretation is implemented in this milestone.

## Storage and migration

The canonical manifest is
`<project>/assemblies/<assembly_id>/assembly.json`. No existing folders move.
Project SQLite gains additive `speaker_assemblies` and
`speaker_assembly_instances` tables with project/assembly indexes and foreign
keys. The instance table stores the Geometry snapshot JSON and hash as evidence,
not as a second editable Geometry store.

Schema creation is transactional and idempotent. Existing projects receive no
synthetic Assembly and require no manifest rewrite. Opening their dataset merely
ensures the new empty tables. Partial states are repairable by replaying the
manifest through the repository's upsert transaction.

## CRUD and governance

- Create, read/list, update and soft-archive Assemblies through the central
  orchestration service.
- Add, edit, reorder and remove instances through the same service.
- Reordering always compacts active order indexes to `0..n-1`.
- IDs, project ownership, creation timestamps, schema version and stored
  snapshot hashes are immutable through ordinary update operations.
- Unknown extension fields are retained for forward compatibility.
- A missing, archived or foreign Geometry is rejected when adding/repointing an
  instance; existing snapshots remain readable if the source is archived later.

## UI

The canonical Geometry page exposes one **Speaker Assemblies** entry point.
The manager is service-backed and owns no separate persistence. It supports
Assembly CRUD and ordered instance editing in a scrollable/resizable layout.
Keyboard focus follows ordinary Qt controls; critical actions remain visible in
small windows.

## Non-goals

No coupled acoustics, multi-source solver input, Driver assignment, DSP,
crossover, CAD import/export, download or external data integration is implied
or implemented.
