# Geometry and driver foundation

This release adds an explicit simulation context while preserving all existing
ATH, AKABAK, VACS, project, result and export paths:

`Project -> Geometry -> Batch -> Version -> Run`

Each new run is bound to one `geometry_id` and one immutable driver snapshot.
The snapshot contains the selected definition/revision, canonical hashes and
the exact LE-network bytes staged into the run workspace. Later edits to the
driver library therefore cannot change an old run.

## User workflow

1. Open a project and choose **Manage Geometries & Drivers**.
2. Create, rename, duplicate, archive or open a geometry. The deterministic
   Legacy Geometry keeps pre-migration content readable and cannot be archived.
3. Open **Driver Library** to search/filter drivers, create compression or cone
   drivers, add revisions, duplicate/archive user drivers, or import/export
   versioned JSON. `generic25` is shown as built-in/read-only.
4. Select a default driver revision for the geometry, or explicitly retain
   **No default driver**. Missing optional values remain visible and are never
   synthesized.
5. Create and run batches inside the selected geometry. The Batch page shows
   the geometry, revision and abbreviated revision hash before simulation.

Old service callers remain supported: batches without an explicit geometry are
assigned to the deterministic Legacy Geometry, and a resolvable installed
`generic25` is snapshotted for the existing coupling. These adapters are a
compatibility boundary, not a second library.

## Storage and schema

- `library.sqlite`: central `driver_definitions` and append-only
  `driver_revisions` tables.
- `<library>/drivers/assets/sha256/<hash>`: content-addressed LE assets.
- `<project>/geometries/<geometry_id>/geometry.json`: geometry metadata.
- project SQLite schema `2.9`: additive `geometry_id` columns, `geometries`, and
  `run_driver_snapshots`.
- existing `batches/`, `versions/`, `runs/` and `exports/` paths are unchanged.

IDs are opaque and stable. Archive operations are soft deletes. Driver revision
JSON uses schema `wut.driver-library`, version `1`; unknown extension data is
retained under `extensions`. Numeric parameters use objects with explicit
`value` and supported `unit` tokens. Import returns structured errors and never
invents missing values or converts T/S parameters into an LE network.

## Safe legacy migration

The command is dry-run by default and accepts an exact project directory, not a
library root:

```powershell
python -m app library migrate-geometries `
  --project-root "C:\path\to\library\projects\P0001__example" `
  --report-path "C:\safe\reports\P0001-geometry-preview.json"
```

Apply mode requires a backup destination:

```powershell
python -m app library migrate-geometries `
  --project-root "C:\path\to\library\projects\P0001__example" `
  --apply --backup-root "C:\safe\backups\P0001-before-geometry" `
  --report-path "C:\safe\reports\P0001-geometry-apply.json"
```

Migration is additive, idempotent and repairs partial assignments. Test a copy
first, retain the JSON report and backup, and never apply it to an entire
library through path enumeration. The active WUT Project Library was inventoried
read-only during development and was not bulk-migrated.

## Compatibility findings

Every new rule has a stable `rule_id`, rationale and evidence type:

| Rule | Severity boundary |
|---|---|
| `geometry_driver_kind_compatibility` | warning for an unusual known pairing |
| `driver_le_network_required` | fatal only when current AKABAK coupling lacks an LE network |
| `driver_data_incomplete` | warning; missing optional fields remain missing |
| `driver_snapshot_integrity` | fatal for a hash mismatch |

The established ATH compatibility hypotheses were not reclassified. Geometry
roles and driver kinds are extensible, and no acoustic-validity claim is made
from a role/kind pairing alone.

## Operational limits

- No coupled speaker, enclosure, DSP/crossover or multi-source simulation.
- No CAD interior recognition, remeshing or CAD export.
- No automatic download/scraping of driver data and no T/S-to-LE synthesis.
- Analyzer storage remains backward-compatible and project-addressable; the
  selected Geometry filters the project dashboard and batch creation context.
- A true first-Windows-session VACS startup remains a separate external
  validation condition and is not changed by this feature.

