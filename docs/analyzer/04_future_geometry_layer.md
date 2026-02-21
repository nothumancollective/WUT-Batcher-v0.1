# Future Geometry Layer (Planning)

**Last updated:** 2026-02-21

This document captures the intended **future** feature: multiple geometries per project and a Merge workflow.
It is not part of the current implementation scope, but the UI architecture should not block it.

## Goal

Within a single project, users can create and manage multiple geometries (“horn candidates”).
Each geometry has:
- its own constraints/settings
- its own batches
- its own analyzer results

This enables:
- multi-way systems
- coax systems
- derived/merged geometries

## UX model

- Project Manager remains the Project Manager (unchanged).
- Mode bar remains (Project | Batch | Analyse), later adds **Merge**.
- Geometry selection happens on the **Project** page, similar to selecting a timeline in DaVinci’s Edit page.
- Batch/Analyse/Merge operate on the currently selected geometry.

## Merge mode (future)

- User selects one or more existing geometries (or a selected “version” from within a batch).
- Merge produces a new “Merged Geometry”.
- Merged Geometry becomes a first-class geometry:
  - can be batched
  - can be analyzed

## Architectural implication (for later)

- Data model must become geometry-scoped.
- UI must show the active geometry context clearly.
- Import/export paths must preserve geometry identity.

