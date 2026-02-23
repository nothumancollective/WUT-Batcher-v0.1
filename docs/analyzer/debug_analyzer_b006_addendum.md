# Analyzer B006 Addendum (Phase 0 Evidence)

Date: 2026-02-23  
Branch: `fix/analyzer-kpi-planes-ux`  
Scope: Analyzer-only evidence collection before fixes

## 1) Dataset + Selection

- Project DB: `cleanup/runtime/postmerge_lib/P021/dataset/project.sqlite`
- Affected batch: `B006` (`project_id=P021`)
- Screenshot-consistent Analyzer config (reproduced via service/UI harness):
  - `stage=concept`
  - `target=60x60`
  - `band=800..10000`
  - `tol=2`
- Under this config, `V022` score reproduces as `9.38` (matches user screenshot).

## 2) Reproduction Summary (Headless UI Harness)

I reproduced the key symptoms using `AnalysePage` in offscreen mode with live DB-backed rows:

1. H plane unavailable while V/D available:
   - selected row planes: `['V', 'D']`
   - `H` button disabled with tooltip:
     - `H not available in imported polar data for this Batch/Version (MISSING_PLANE).`

2. Compare shortlist score loss (`--`) while top summary keeps numeric score:
   - initial:
     - slot C1 score: `9.38`
     - top summary: `Score: 9.38`
   - after run payload refresh:
     - slot C1 score: `--`
     - top summary still: `Score: 9.38`

3. Auto-pick:
   - no crash reproduced
   - returns 5 candidates and slot score renders (`9.38`) on completion

4. Pareto panel rectangle artifact reproduced:
   - center pixel sampled from rendered Pareto pixmap:
     - `RGBA=(192,132,252,255)` (same as C5 point color)
   - corner pixel remains panel background:
     - `RGBA=(17,18,23,255)`
   - This is consistent with the full plot rect being filled by the last point color.

## 3) DB Evidence (SQL + Output)

### 3.1 Batch existence

```sql
SELECT project_id,batch_id,created_at
FROM batches
WHERE batch_id='B006'
ORDER BY project_id;
```

Output:

| project_id | batch_id | created_at |
|---|---|---|
| P021 | B006 | 2026-02-23T14:39:52+00:00 |

### 3.2 Plane inventory (by version/run/orientation)

```sql
SELECT project_id,batch_id,version_id,COALESCE(run_id,'') AS run_id,orientation,COUNT(*) AS measurement_rows
FROM polar_measurements
WHERE batch_id='B006'
GROUP BY project_id,batch_id,version_id,COALESCE(run_id,''),orientation
ORDER BY version_id,run_id,orientation;
```

Observed:

- 16 rows total (8 versions x 2 orientations)
- Orientations are only:
  - `V`
  - `X3_45`

Distinct check:

```sql
SELECT DISTINCT orientation
FROM polar_measurements
WHERE batch_id='B006'
ORDER BY orientation;
```

Output:

| orientation |
|---|
| V |
| X3_45 |

No `H`, no `X3_0`.

### 3.3 Polar points integrity

```sql
SELECT pm.version_id,COALESCE(pm.run_id,'') AS run_id,pm.orientation,pm.polar_id,
       pm.freq_count,pm.angle_count,
       (pm.freq_count*pm.angle_count) AS expected_points,
       COUNT(pp.polar_id) AS actual_points
FROM polar_measurements pm
LEFT JOIN polar_points pp ON pp.polar_id=pm.polar_id
WHERE pm.batch_id='B006'
GROUP BY pm.version_id,COALESCE(pm.run_id,''),pm.orientation,pm.polar_id,pm.freq_count,pm.angle_count
ORDER BY pm.version_id,run_id,pm.orientation;
```

Output summary:

- 16/16 polar IDs satisfy `actual_points = expected_points`
- For all rows: `freq_count=12`, `angle_count=19`, `expected=228`, `actual=228`

### 3.4 KPI inventory

```sql
SELECT COUNT(*) AS n
FROM analyzer_run_kpis
WHERE batch_id='B006';
```

Output:

| n |
|---|
| 16 |

Latest rows for screenshot-like band/target show persisted scores exist:

```sql
SELECT project_id,batch_id,COALESCE(run_id,'') AS run_id,version_id,stage_mode,
       band_low_hz,band_high_hz,target_h_deg,target_v_deg,tol_deg,
       score,algo_version,source_hash,computed_at
FROM analyzer_run_kpis
WHERE batch_id='B006'
ORDER BY computed_at DESC
LIMIT 16;
```

Relevant latest block:

- `algo_version=analyzer-mvp-2a-v3`
- `stage_mode=shaping`
- `band=800..10000`, `target=60/60`, `tol=2`
- version scores present (`V022=21.46`, `V021=21.31`, ...)

## 4) Source File Header Evidence

From DB `source_file` paths and direct file inspection (`V015..V022`):

- Each version has 3 exported polar files:
  - `_2`, `_3`, `_4`
- Header values:
  - `_2`: `Param_Coord_x3=45`
  - `_3`: `Param_Coord_x3=90`
  - `_4`: `Param_Coord_x3=90`
- `Param_Coord_x2` includes symmetric angles `-90..90` (19 values)
- `_3` and `_4` are byte-identical (same SHA256), so no distinct H plane source file is present.

Example (V022):

- `V022_anygraph_01_Mic_Polar_-_BE_Spectrum_2.txt` -> `Param_Coord_x3=45`
- `V022_anygraph_02_Mic_Polar_-_BE_Spectrum_3.txt` -> `Param_Coord_x3=90`
- `V022_anygraph_03_Mic_Polar_-_BE_Spectrum_4.txt` -> `Param_Coord_x3=90` (duplicate of `_02`)

## 5) Root Cause Evidence

## 5.1 H plane missing (B006)

Evidence:

- DB has only `V` + `X3_45` for B006.
- Export headers show only x3 `45/90/90` and duplicate `90` file.

Conclusion:

- H is not silently hidden by Analyzer for this dataset; H is absent in imported B006 polar source content.

## 5.2 Shortlist score shows `--` while top summary shows numeric

Code evidence:

- Compare slot score uses `candidate["score"]`:
  - `app/gui.py:6821`
- During run payload refresh, compare candidates are replaced with raw run rows:
  - `app/gui.py:7756-7761`
- Raw run rows carry `kpi_score`, not `score`.

Repro output (B006 rows):

- before refresh: slot score `9.38`
- after refresh: slot score `--`
- top summary remains `Score: 9.38`

Conclusion:

- Score key mismatch introduced during `_apply_runs_payload` merge path.

## 5.3 Pareto “filled rectangle” artifact

Code evidence:

- In `ParetoScatterCanvas`:
  - sets brush to point color: `app/gui.py:1178`
  - draws points
  - then draws plot rectangle without resetting brush: `app/gui.py:1184`

Qt behavior:

- `drawRect(...)` uses current brush -> plot area gets filled by the last candidate color.

Conclusion:

- This is a rendering-state bug in Pareto canvas, not KPI mapping.

## 5.4 Beamwidth value sanity (large deg values)

Definition in code:

- -6 dB beamwidth crossing around reference angle:
  - `app/analyzer/kpi_engine.py:37-92`
  - `app/analyzer/plot_service.py:113-146`
- `E_BW` is mean absolute deviation from target in degrees:
  - `app/analyzer/kpi_engine.py:297-299`

For `B006/V022` (`band=800..10000`, `target=60`):

- Plane curves start near ~134 deg at low frequencies and narrow to ~34-38 deg at 10 kHz.
- Mean absolute deviation from target naturally lands around `24.22 deg`.

Conclusion:

- Large values are explainable by current dataset directivity shape; not immediately a unit bug.
- Still worth adding explicit saturation/target annotation clarity in UI.

## 6) Hypotheses (confidence)

1. H missing in B006 because exported polar set is `45/90/90` (no `0`) (Very high)
2. Shortlist score `--` is due refresh-time key mismatch (`score` vs `kpi_score`) (Very high)
3. Pareto rectangle is caused by brush not reset before plot-rect draw (Very high)
4. Beamwidth magnitude appears high but is algorithmically consistent with data (High)
5. Auto-pick crash was not reproducible in this repo state (Medium; no crash trace found for Auto-pick path)

## 7) Minimal Fix Plan

1. Plane availability:
   - Keep current explicit H-disabled messaging when missing.
   - If B006 has no H in source/DB, do not alias unknown codes to H.

2. Shortlist score:
   - Normalize refreshed compare candidates through `_candidate_from_row(...)` in `_apply_runs_payload` so `kpi_score -> score` mapping is preserved.
   - Keep identity strict: `project_id + batch_id + run_id + version_id`.

3. Pareto:
   - Reset brush to `Qt.NoBrush` before drawing plot frame rectangle.
   - Keep true scatter semantics (one point per candidate).

4. Compare KPI panel UX:
   - Replace single-candidate form block with compact C1..C5 KPI matrix to avoid clipping and improve readability.

5. Beamwidth clarity:
   - Add target line/annotation + saturation indicator in beamwidth plots.
   - Add tests for known synthetic beamwidth and saturation edge.
