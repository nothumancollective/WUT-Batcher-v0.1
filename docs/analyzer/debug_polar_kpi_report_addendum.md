# Analyzer Polar/KPI Debug Addendum (Phase 0)

Date: 2026-02-23  
Branch: `feature/analyzer-pro-layout`  
Scope: evidence-only addendum before further fixes

## 1) Target and reproduction scope

- Dataset: `cleanup/runtime/postmerge_lib/P021/dataset/project.sqlite`
- Project: `P021`
- Batch: `B005`
- Versions: `V012`, `V013`, `V014`
- Run: `7dc2d26a-d4c9-456e-9ef7-c0a5652442f4`

## 2) UI reproduction snapshot

Using the current `AnalysePage` against `P021/B005` payload:

```text
run_table planes cell row0: V/D
available planes from selected row: ['V', 'D']
H enabled: False
V enabled: True
D enabled: True
row reason codes: ['INSUFFICIENT_ANGLE_COVERAGE', 'MISSING_PLANE']
row score: 17.1
```

Confirmed:
- H plane is not available in the Analyzer plane toggle for this batch.
- Flags are present on each row with the same two reason codes.

## 3) DB evidence (polar_measurements / polar_points)

### 3.1 Orientation inventory (project P021)

```sql
SELECT project_id,batch_id,version_id,COALESCE(run_id,''),orientation,COUNT(*)
FROM polar_measurements
WHERE project_id='P021'
GROUP BY project_id,batch_id,version_id,COALESCE(run_id,''),orientation
ORDER BY batch_id,version_id,orientation;
```

Observed orientations (all batches in P021):
- `V`
- `X3_45`

No `H`-type token observed.

### 3.2 Orientation totals and raw values

```sql
SELECT orientation,COUNT(*),MIN(orientation_raw),MAX(orientation_raw)
FROM polar_measurements
WHERE project_id='P021'
GROUP BY orientation
ORDER BY orientation;
```

Result:
- `('V', 7, 90.0, 90.0)`
- `('X3_45', 7, 45.0, 45.0)`

Alias probe for H-style codes:
- `H`: `0`
- `X3_0`: `0`
- `X3_0.0`: `0`
- `X3_00`: `0`

### 3.3 B005 rows

`polar_measurements` for `B005` contains exactly two orientations per version:
- `V` (`orientation_raw=90`)
- `X3_45` (`orientation_raw=45`)

No `H` row exists in DB for `B005`.

### 3.4 Integrity check

```sql
SELECT pm.polar_id,pm.version_id,pm.orientation,
       pm.freq_count,pm.angle_count,
       pm.freq_count*pm.angle_count AS expected_points,
       COUNT(pp.polar_id) AS actual_points
FROM polar_measurements pm
LEFT JOIN polar_points pp ON pp.polar_id=pm.polar_id
WHERE pm.project_id='P021' AND pm.batch_id='B005'
GROUP BY pm.polar_id,pm.version_id,pm.orientation,pm.freq_count,pm.angle_count;
```

All rows pass (`actual_points == expected_points`, each `228 == 12*19`).

## 4) Real TXT header evidence (affected run)

Inspected files under:
- `cleanup/runtime/postmerge_lib/P021/versions/V012/exports/7dc2d26a-d4c9-456e-9ef7-c0a5652442f4`
- `cleanup/runtime/postmerge_lib/P021/versions/V013/exports/7dc2d26a-d4c9-456e-9ef7-c0a5652442f4`
- `cleanup/runtime/postmerge_lib/P021/versions/V014/exports/7dc2d26a-d4c9-456e-9ef7-c0a5652442f4`

Per version there are 3 exported polar files (`..._2`, `..._3`, `..._4`).

Header facts:
- `_2` files: `Param_Coord_x3=45`
- `_3` files: `Param_Coord_x3=90`
- `_4` files: `Param_Coord_x3=90`
- No file with `Param_Coord_x3=0` was found.

SHA256 facts:
- For each version, `_3` and `_4` are byte-identical (same hash), so they represent duplicate content.

Implication:
- Exported planes for this run are effectively `45` and `90` only.
- A distinct `0` plane (H) is not present in these exported files.

## 5) Compare Auto-pick crash investigation

### 5.1 Runtime log check

Checked:
- `C:\Users\maximilianheinze\AppData\Local\WUTBatcher\logs\ui_runtime_errors.log`

Result:
- No Auto-pick-specific traceback found.
- Only unrelated Batch-page sweep validation tracebacks were present.

### 5.2 In-app path reproduction (headless)

Executed:
- Service-level `analyzer_autopick_candidates(...)` for `P021/B005`: succeeds.
- UI slot path `_on_autopick_finished(...)`: no exception.

Observed payload contract mismatch:
- Service candidate rows use key `score`.
- UI `_candidate_from_row(...)` reads `kpi_score`.

Resulting candidate after Auto-pick in UI:

```text
{
  'batch_id': 'B005',
  'version_id': 'V012',
  'score': None,
  'kpi_flags_count': None,
  'planes': [],
  ...
}
```

This does not always crash immediately, but it degrades compare state (missing score/planes metadata) and is a high-risk defect in the Auto-pick path.

### 5.3 Stack trace status

- No deterministic Auto-pick crash stack trace was reproducible from current `P021/B005` in this headless run.
- No Auto-pick stack trace was present in runtime logs.
- The strongest concrete defect found in this path is the payload key mismatch (`score` vs `kpi_score`) and missing propagated fields (`planes`, reason metadata).

## 6) Flags evidence (current batch)

For `P021/B005` (`stage=shaping`, `band=200..16000`, `target=90x40`, `tol=5`):

Reason-code counts:
- `INSUFFICIENT_ANGLE_COVERAGE`: 3
- `MISSING_PLANE`: 3

Per-version rows:
- `V012`: score `17.15`, flags `4`, reasons `INSUFFICIENT_ANGLE_COVERAGE`, `MISSING_PLANE`
- `V013`: score `17.10`, flags `4`, reasons `INSUFFICIENT_ANGLE_COVERAGE`, `MISSING_PLANE`
- `V014`: score `17.10`, flags `4`, reasons `INSUFFICIENT_ANGLE_COVERAGE`, `MISSING_PLANE`

## 7) Hypotheses (confidence)

1. **H plane missing in this affected run due source data, not analyzer filtering** (Very high)
- DB has no `H`/`X3_0` rows.
- Exported TXT headers in affected run show only x3=`45` and x3=`90` (with duplicated `90` file).

2. **Auto-pick instability comes from candidate payload contract mismatch** (High)
- Service emits `score`; UI reads `kpi_score`.
- UI loses score/flags/planes metadata in autopicked candidates, which can destabilize compare interactions.

3. **Current flag volume is mostly structural for this dataset** (High)
- `MISSING_PLANE` is legitimate (H absent).
- `INSUFFICIENT_ANGLE_COVERAGE` is expected due one-sided vertical angle set and limited plane set.

4. **Scoping still needs explicit hardening tests for non-mixing guarantees** (Medium)
- Current evidence for `P021/B005` does not show cross-batch mixing in DB inventory.
- Dedicated tests are still needed to lock strict project+batch+version+run(+plane) separation in analyzer list/autopick paths.
