# Polar DB Schema

This document describes the additive polar storage introduced for full complex polar matrices (`freq x angle`) in parallel with legacy `graphs/graph_series/graph_points`.

## Tables

### `polar_measurements`

One row per imported polar export file (or deduplicated file identity).

Columns:
- `polar_id TEXT PRIMARY KEY`
- `project_id TEXT NOT NULL`
- `batch_id TEXT NOT NULL`
- `version_id TEXT NOT NULL`
- `run_id TEXT`
- `graph_id TEXT`
- `orientation TEXT NOT NULL`
- `orientation_raw REAL`
- `norm_angle_deg REAL`
- `data_level_type TEXT`
- `data_base_unit TEXT`
- `data_absc_unit TEXT`
- `freq_min_hz REAL`
- `freq_max_hz REAL`
- `freq_count INTEGER NOT NULL`
- `angle_min_deg REAL`
- `angle_max_deg REAL`
- `angle_step_deg REAL`
- `angle_count INTEGER NOT NULL`
- `angles_deg_json TEXT NOT NULL`
- `source_file TEXT NOT NULL`
- `file_hash TEXT NOT NULL`
- `export_meta_json TEXT`
- `created_at TEXT NOT NULL`

Indices:
- `idx_polar_meas_version (version_id)`
- `idx_polar_meas_run (run_id)`
- `idx_polar_meas_batch (project_id, batch_id)`
- `idx_polar_meas_orientation (orientation)`
- `uq_polar_meas_identity (project_id, version_id, coalesce(run_id, ''), orientation, file_hash)`

### `polar_points`

One row per matrix cell.

Columns:
- `polar_id TEXT NOT NULL`
- `freq_index INTEGER NOT NULL`
- `angle_index INTEGER NOT NULL`
- `freq_hz REAL NOT NULL`
- `angle_deg REAL NOT NULL`
- `re REAL NOT NULL`
- `im REAL NOT NULL`

Keys:
- `PRIMARY KEY (polar_id, freq_index, angle_index)`
- `FOREIGN KEY (polar_id) REFERENCES polar_measurements(polar_id) ON DELETE CASCADE`

Indices:
- `idx_polar_points_polar_freq (polar_id, freq_hz)`
- `idx_polar_points_polar_angle_freq (polar_id, angle_index, freq_hz)`
- `idx_polar_points_polar_angle (polar_id, angle_deg)`

## Orientation Mapping

Raw orientation marker comes from `Param_Coord_x3` when present.

Normalization:
- `0 -> "H"`
- `90 -> "V"`
- `42 -> "D"` (legacy diagonal exports)
- `45 -> "D"` (current diagonal default inclination)
- Any other numeric value -> `"X3_<value>"`
- Missing marker -> `"X3_UNKNOWN"`

Both values are stored:
- normalized string in `orientation`
- raw numeric in `orientation_raw`

## Export Recommendations For Analyzer

For reliable H/V/D plane availability in Analyzer, configure three polar exports with explicit inclinations:

- H: `Inclination = 0`
- V: `Inclination = 90`
- D: `Inclination = 45`

Recommended angle coverage is symmetric (for example `MapAngleRange = -90,90,19`) to avoid one-sided interpretation artifacts.

## Norm-Angle Policy

Importer resolves `norm_angle_deg` deterministically:
1. Use `norm_angle` from the mapped export contract/spec (`vacs_export_summary.exports[*].spec.options.norm_angle`) when available.
2. Else use `batch.sim_export_settings.export_specs[*].options.norm_angle` for the relevant spec id (or an unambiguous single polar spec).
3. Else use a header key containing both `norm` and `angle` if present.
4. Else store `NULL`.

Resolution source is recorded in `export_meta_json` under `polar_import.norm_angle_policy`.

## Deduplication Policy

Importer computes `sha256` for each source file and stores it in `file_hash`.

Before insert, it checks existing identity:
- `(project_id, version_id, run_id, orientation, file_hash)`

If found, import is skipped for that polar file. This prevents duplicates across retries/replays.

## Validation and Failure Behavior

Supported polar TXT shapes:
- Format A (`legacy_with_frequency`)
  - Required headers include `Param_Coord_x2`, `Param_Coord_x3`
  - Data block rows are `frequency + (2 * angle_count)` numeric values (Re/Im pairs)
- Format B (`abscissa_data`)
  - Required headers include `StartString_Absc`/`EndString_Absc`, `StartString_Data`/`EndString_Data`,
    `Param_Coord_x2`, `Param_Coord_x3`
  - Abscissa block contains one frequency per row
  - Data block rows contain only `(2 * angle_count)` numeric values (Re/Im pairs), mapped by row index

Deterministic format detection:
1. If `StartString_Absc` and `EndString_Absc` are present, parse as Format B.
2. Otherwise parse as Format A.
3. In both cases enforce:
   - `Data_Format=Complex`
   - `Data_Domain` contains `Frequency`

Validation rules:
- `angle_count >= 1`
- `freq_count >= 1`
- Format A row width must equal `1 + 2*angle_count`
- Format B data-row width must equal `2*angle_count`
- Format B row counts must match: `len(Abscissa rows) == len(Data rows)`
- Frequency decreases are flagged as warnings (stored in import metadata)
- `NaN`/`Inf` values are rejected with row-level parse errors

Fail-fast behavior:
- Missing required headers (`Param_Coord_x2`, `Param_Coord_x3`, `Data_Format`, `Data_Domain`) or unsupported layout
  raise structured `PolarTxtParseError` with:
  - `error_code` (for example `MISSING_HEADER`, `BAD_DIMENSIONS`, `UNSUPPORTED_FORMAT`, `INVALID_NUMERIC`)
  - `file_path`
  - detailed expected vs. actual values when applicable
- Importer surfaces actionable remediation text, for example:
  - Enable `Export of parameters`
  - Ensure VACS export uses `Data_Format=Complex` and frequency domain output
- Must-have export setting: VACS export must have `Export of Parameters` enabled so `Param_Coord_x2` and
  `Param_Coord_x3` are present in the TXT header.
- No partial `polar_*` writes are performed for the failed file.

## Replication Integration

Global consolidation uses operation-based dual-write + retry queue.

New operations:
- `upsert_polar_measurement`
- `insert_polar_points_chunk`

Ordering:
- Measurement op is written before points ops.

Idempotence:
- Points use `INSERT OR IGNORE` with PK `(polar_id, freq_index, angle_index)`.
