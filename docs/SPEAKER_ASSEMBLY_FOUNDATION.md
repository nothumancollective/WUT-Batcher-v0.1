# SpeakerAssembly foundation

SpeakerAssembly is a project-local, additive arrangement layer for reusable
Geometry objects. It records placement intent without changing the validated
single-Geometry ATH -> AKABAK -> VACS pipeline.

## User workflow

1. Open a project and select **Geometry** in the bottom navigation.
2. Select **Speaker Assemblies**.
3. Create an Assembly, then add one or more existing project Geometries.
4. For each instance choose **Normal** or **Coaxial**, enter a name and set its
   translation in metres and rotation in degrees.
5. Use **Move Up** / **Move Down** to define deterministic order. Assemblies can
   be renamed and soft-archived; instances can be edited or removed.

The UI remains usable in a small, resizable window: the manager and instance
form are scrollable and all critical actions remain reachable by keyboard.

## Data and coordinate contract

Each instance stores a stable ID, its live `geometry_id`, a complete immutable
Geometry snapshot and the SHA-256 of the canonical snapshot. Editing the live
Geometry later does not rewrite existing Assembly instances. A pure transform,
name or arrangement edit also preserves the original snapshot; explicitly
selecting another Geometry captures a new one.

The frame is right-handed: +X right, +Y up and +Z forward along the nominal
acoustic axis. Translation is stored in SI metres. Rotation is stored in
degrees, normalized to `[-180, 180)`, and interpreted as active right-hand,
fixed-axis X then Y then Z rotation (`Rz * Ry * Rx` for column vectors).

Canonical manifests live at
`<project>/assemblies/<assembly_id>/assembly.json`. Project SQLite schema 2.11
adds `speaker_assemblies` and `speaker_assembly_instances`; existing paths and
records do not move. Opening an old project idempotently creates empty additive
tables and does not invent an Assembly.

## Current boundary

This foundation does not run coupled acoustics and does not assign Drivers,
DSP/crossovers or CAD semantics to an Assembly. It neither changes the Runner
nor the Batch Driver resolution contract. Future execution must deliberately
resolve Driver snapshots and solver semantics instead of treating placement
metadata as an executable multi-source model.

Architecture and invariants are specified in
`docs/adr/009-speaker-assembly-foundation.md`. The visible acceptance record is
`docs/validation/SPEAKER_ASSEMBLY_UI_SMOKE_2026-08-03.md`.
