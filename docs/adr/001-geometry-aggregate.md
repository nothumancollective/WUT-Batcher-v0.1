# ADR-001: Geometry aggregate and lineage

Status: accepted, 2026-08-01

## Decision

The domain hierarchy is `Project -> Geometry -> Batch -> Version`. A geometry
has a stable opaque `geometry_id` scoped to its project, a user-facing name and
description, an extensible role (`hf_horn`, `mid_horn`, `waveguide`, or an
unknown future token), an ATH template/parameter base, timestamps, archive
state, schema version, and an optional default driver revision.

`Batch.geometry_id` and `Version.geometry_id` are required for newly created
objects. Existing objects without that field resolve through the project's one
deterministic legacy geometry. Batch and version IDs remain project-wide unique
in this release; changing their namespace would break paths and external links.

Geometry duplication creates a new identity and copies editable geometry
settings, but not batch/version/run history. Archiving is a soft state; archived
geometries remain readable and analyzable.

## Rationale

This makes geometry the explicit simulation context without moving existing
folders or changing validated artifact locations. It permits later geometry-
scoped physical paths through a separate migration while preserving every
existing ID, export and analyzer reference.

## Invariants

- A batch and all its versions resolve to exactly one geometry.
- A version cannot silently change geometry after materialization.
- No DSP, enclosure, speaker-assembly or CAD assumptions belong to Geometry.
- The selected geometry is visible whenever batch or analyzer data is shown.

