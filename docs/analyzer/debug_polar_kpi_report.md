# Analyzer Polar/KPI Debug Report (Phase 0)

Date: 2026-02-23
Branch: `feature/analyzer-pro-layout`
Scope: Analyzer-side diagnosis only (no Runner/export pipeline changes)

## 1) Reproduction target + IDs

- Active dataset inspected: `cleanup/runtime/postmerge_lib/P021/dataset/project.sqlite`
- Project: `P021`
- Batch with 3 versions: `B005` (`V012`, `V013`, `V014`)
- Run ID for that batch: `7dc2d26a-d4c9-456e-9ef7-c0a5652442f4`

Observed in Analyzer data path for `P021/B005`:
- `kpi_score = 0.0` for all 3 versions
- `kpi_flags_count = 4` for all 3 versions
- `planes = ['V', 'X3_45']`
- `norm_angle_deg = NULL`

Evidence (service output):

```text
{'version_id': 'V014', 'planes': ['V', 'X3_45'], 'kpi_score': 0.0, 'kpi_flags_count': 4, 'kpi_insufficient_coverage': True, 'norm_angle_deg': None}
{'version_id': 'V013', 'planes': ['V', 'X3_45'], 'kpi_score': 0.0, 'kpi_flags_count': 4, 'kpi_insufficient_coverage': True, 'norm_angle_deg': None}
{'version_id': 'V012', 'planes': ['V', 'X3_45'], 'kpi_score': 0.0, 'kpi_flags_count': 4, 'kpi_insufficient_coverage': True, 'norm_angle_deg': None}
```

## 2) DB inventory (polar_measurements / polar_points)

### 2.1 Orientation inventory by batch/version/run

```sql
SELECT project_id,batch_id,version_id,COALESCE(run_id,''),orientation,COUNT(*)
FROM polar_measurements
GROUP BY project_id,batch_id,version_id,COALESCE(run_id,''),orientation
ORDER BY batch_id,version_id,orientation;
```

Result highlights:
- All P021 batches use only `V` and `X3_45` orientations.
- For `B005` each version has 2 measurements (`V` + `X3_45`).
- No `H` rows in `B005`.

### 2.2 B005 sample rows from `polar_measurements` (6 rows)

Columns shown: `polar_id, version_id, orientation, orientation_raw, norm_angle_deg, freq_count, angle_count, source_file`

- `Pbcbf0a331ef72ea3, V012, V, 90.0, NULL, 12, 19, ...V012_anygraph_02...`
- `P32d825964c0e7e56, V012, X3_45, 45.0, NULL, 12, 19, ...V012_anygraph_01...`
- `P8de1f9658be40fc6, V013, V, 90.0, NULL, 12, 19, ...V013_anygraph_02...`
- `P7852b5d607e18d3d, V013, X3_45, 45.0, NULL, 12, 19, ...V013_anygraph_01...`
- `P3dacd81066788241, V014, V, 90.0, NULL, 12, 19, ...V014_anygraph_02...`
- `P958ca640a35aa61f, V014, X3_45, 45.0, NULL, 12, 19, ...V014_anygraph_01...`

### 2.3 `polar_points` integrity check

```sql
SELECT pm.polar_id, pm.version_id, pm.orientation,
       pm.freq_count, pm.angle_count,
       pm.freq_count*pm.angle_count AS expected_points,
       COUNT(pp.polar_id) AS actual_points
FROM polar_measurements pm
LEFT JOIN polar_points pp ON pp.polar_id = pm.polar_id
WHERE pm.project_id='P021' AND pm.batch_id='B005'
GROUP BY pm.polar_id, pm.version_id, pm.orientation;
```

Result: all 6 rows pass (`228 expected == 228 actual`).

### 2.4 `polar_points` sample (5 rows each)

For `V` polar (`Pbcbf0a331ef72ea3`):
- `(freq_hz=500.0, angle_deg=0.0, re=-0.01015678, im=0.05796891)`
- `(500.0, 5.0, -0.01005232, 0.05786716)`
- `(500.0, 10.0, -0.009745388, 0.05757075)`
- `(500.0, 15.0, -0.009240868, 0.05708731)`
- `(500.0, 20.0, -0.008546592, 0.05642907)`

For `X3_45` polar (`P32d825964c0e7e56`):
- `(500.0, -90.0, 0.01399469, 0.04025778)`
- `(500.0, -80.0, 0.009899535, 0.04238945)`
- `(500.0, -70.0, 0.005974746, 0.0447719)`
- `(500.0, -60.0, 0.002275511, 0.0473283)`
- `(500.0, -50.0, -0.001127319, 0.0499409)`

## 3) Real TXT header inspection (10 files)

Inspected files from `polar_measurements.source_file` in `P021` (`V004`, `V007`, `V010`, `V011`, `V012`; both polars each).

Common facts:
- `Data_Format=Complex`
- `Data_LevelType=SoundPressure`
- `Data_AbscUnit=Hz`, `Data_BaseUnit=Pa`
- `NormAngle` header key not present

Plane-specific facts:
- Diagonal-like files: `Param_Coord_x3=45`, `Param_Coord_x2=-90..90` (19 bins)
- Vertical-like files: `Param_Coord_x3=90`, `Param_Coord_x2=0..90` (19 bins)

Frequency facts:
- `V004`: `freq_count=16`, `freq_min=500`, `freq_max=10000`
- `V007/V010/V011/V012`: `freq_count=12`, `freq_min=500`, `freq_max=10000`

No header carried `NormAngle` in inspected files.

## 4) Exported file count vs ingested count

For `V012` export folder there are 3 polar files:
- `..._01_Mic_Polar_-_BE_Spectrum_2.txt` (x3=45)
- `..._02_Mic_Polar_-_BE_Spectrum_3.txt` (x3=90)
- `..._03_Mic_Polar_-_BE_Spectrum_4.txt` (x3=90)

SHA256 hashes show `_02` and `_03` are byte-identical, so importer dedupe keeps one.

Implication:
- 3 exports were produced, but only 2 unique measurements are ingested for each version.

## 5) KPI table evidence

`analyzer_run_kpis` rows exist for `B005` (9 rows across stage/band presets).

For `stage_mode='shaping'`:
- `V012 score=0.0`
- `V013 score=0.0`
- `V014 score=0.0`

Flags payload example:

```json
{
  "collapse_hz": {"V": [10000.0]},
  "insufficient_coverage": true,
  "jump_hz": {"V": [862.0271]},
  "wide_hz": {"V": [500.0, 656.5162]}
}
```

`kpi_json.planes` contains only `V` (the `X3_45` plane is dropped by compute filter).

## 6) UI behavior reproduction evidence

Using the real `AnalysePage` class with payload from `P021/B005`:

```text
table_planes_cell V/X3_45
selected planes payload ['V', 'X3_45']
available planes ['V']
H enabled False
V enabled True
D enabled False
```

Cause: `_available_planes` keeps only `{H,V,D}` and drops unknown tokens.

## 7) Root causes (with confidence)

1. Unknown orientation filtering in Analyzer UI and KPI compute (High)
- DB stores `X3_45`; analyzer compute/UI paths accept only `{H,V,D}`.
- Evidence:
  - UI filter: `app/gui.py:6164-6169`
  - KPI compute filter: `app/services.py:2685-2688`
- Outcome:
  - Plane selector enables only `V`.
  - `X3_45` plane excluded from KPI math.

2. Score forced to zero when `insufficient_coverage` is true (High)
- Evidence: `compute_stage_score` early return `0.0` on insufficient coverage (`app/analyzer/kpi_engine.py:378+`).
- Outcome: all rows with this flag become `0.0` even when partial usable data exists.

3. One-sided angle handling marks coverage insufficient too aggressively (High)
- V plane in this batch is `0..90` only; current KPI logic assumes symmetric coverage check around 0.
- Evidence: `compute_plane_kpis` coverage check (`app/analyzer/kpi_engine.py`, `min_angle > -coverage_half or max_angle < coverage_half`).
- Outcome: `insufficient_coverage=true`, then score forced to 0.

4. NormAngle null + UI detail rendering bug for zero (High)
- `polar_measurements.norm_angle_deg` is NULL in this dataset.
- TXT headers have no NormAngle key; version config contains `norm_angle=0` in all 3 polar specs.
- Details dialog uses `str(data.get("norm_angle_deg") or "--")`, which also hides valid `0.0`.
- Evidence: `app/gui.py:2085`.

5. 3 exports != 3 unique polars in this batch (High)
- `_02` and `_03` files are identical hashes (`x3=90` both).
- Outcome: dedupe keeps one, leaving 2 unique polars.

## 8) Minimal fix plan (targeted, analyzer-side)

1. Plane normalization/alias + fallback
- Add analyzer-side orientation canonicalization that maps known aliases (`X3_45` -> `D`; keep other unknowns as fallback tokens).
- Apply in:
  - run list plane parsing (`app/services.py`)
  - KPI compute ingestion (`app/services.py`)
  - UI available-plane logic (`app/gui.py`) so unknown labels are not silently dropped.

2. NormAngle effective value + fallback reason
- Compute an effective norm angle in Analyzer read path:
  - use stored `norm_angle_deg` if present
  - else infer from export metadata when unambiguous
  - else use nearest angle to `0°`
- Fix details dialog zero rendering bug (`app/gui.py:2085`).
- Extend payload with source/reason for details UI.

3. KPI robustness
- In KPI engine (`app/analyzer/kpi_engine.py`):
  - use strict band intersection (no silent full-band fallback)
  - support one-sided angle sets via limited/half-coverage beamwidth handling
  - emit explicit reason codes:
    - `INSUFFICIENT_ANGLE_COVERAGE`
    - `EMPTY_BAND_INTERSECTION`
    - `MISSING_PLANE`
- Avoid treating every insufficient case as forced `0.0`; return `None` score when unscorable.

4. UI presentation for missing/unscorable KPIs
- Keep `--` when KPI rows are missing/unscorable.
- Add reason code display in details and use explicit `MISSING_KPI_ROWS` marker.

5. Tests/docs
- Add synthetic tests for:
  - `H/V/D` + alias/unknown plane handling
  - one-sided angles (`0..90`)
  - empty band intersection
  - norm-angle missing fallback messaging
- Update `docs/analyzer/CHANGELOG.md` per commit and `docs/analyzer/02_ui_architecture.md` for norm/band rules.

## 9) Constraints check

- No Runner / VACS automation / export-enforcement changes required for these fixes.
- No schema change required for MVP fixes.
- Analyzer remains polar-only for KPI compute.
