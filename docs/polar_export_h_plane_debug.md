# Polar H-Plane Export Debug Report (B006)

Date: 2026-02-23
Branch: `fix/polars-h-plane-export` (from `wut-batcher/rebuild`)

## Scope and Method
- Goal: find exactly where H is lost in the pipeline `Batch UI -> sim_export_settings -> cfg -> VACS TXT -> DB`.
- No code changes were made in this phase.
- Evidence source: existing real run artifacts for `P021/B006` (run id `61235f44-0704-486c-83e5-1e3a39ba79f8`) plus live repository code.

## 1) Batch Export Settings Persistence Evidence

### 1.1 Persisted batch config (`batch.json`)
Path: `cleanup/runtime/postmerge_lib/P021/batches/B006/batch.json`

Observed `sim_export_settings.export_specs` (trimmed):

```json
{
  "id": "adv_polar_1",
  "graph_kind": "polar",
  "options": {
    "polar_name": "Polars H",
    "inclination": 90,
    "map_angle_range": [-90, 90, 19],
    "distance_m": 2.0,
    "offset": 145,
    "norm_angle": 0
  }
}
{
  "id": "adv_polar_2",
  "graph_kind": "polar",
  "options": {"polar_name": "Polars V", "inclination": 90, ...}
}
{
  "id": "adv_polar_3",
  "graph_kind": "polar",
  "options": {"polar_name": "Polars D", "inclination": 45, ...}
}
```

### 1.2 Same payload persisted in DB `batches.sim_export_params`
Query:

```sql
SELECT project_id,batch_id,batch_name,sim_export_params
FROM batches
WHERE project_id='P021' AND batch_id='B006';
```

Result confirms `adv_polar_1` is `Polars H` with `inclination=90`.

## 2) cfg/Contract Generation Evidence

### 2.1 Generated cfg for B006/V022
Path: `cleanup/runtime/postmerge_lib/P021/versions/V022/cfg/P021_B006_V022_61235f44.cfg`

Excerpt:

```cfg
ABEC.Polars:Polars H = {
  MapAngleRange = -90,90,19
  Distance = 2
  Offset = 145
  Inclination = 90
}

ABEC.Polars:Polars V = {
  ...
  Inclination = 90
}

ABEC.Polars:Polars D = {
  ...
  Inclination = 45
}
```

Conclusion: config->cfg did not drop H; it carried the persisted (wrong) H inclination value.

### 2.2 Export pipeline summary evidence
Path: `cleanup/runtime/postmerge_lib/P021/versions/V022/logs/vacs.export_pipeline.json`

Observed:
- `mapping_mode: "any_graph"`
- 3 exported polar files mapped as `external_any_01..03`
- `requested_spec_ids` contains `adv_polar_1`, `adv_polar_2`, `adv_polar_3`

This confirms export pipeline executed three requested polar specs, but fallback naming is any-graph (`...anygraph_01/02/03...`), not plane-tagged.

## 3) Exported TXT Header Evidence

Sample files:
- `cleanup/runtime/postmerge_lib/P021/versions/V015/exports/61235f44-0704-486c-83e5-1e3a39ba79f8/V015_anygraph_01_Mic_Polar_-_BE_Spectrum_2.txt`
- `cleanup/runtime/postmerge_lib/P021/versions/V015/exports/61235f44-0704-486c-83e5-1e3a39ba79f8/V015_anygraph_02_Mic_Polar_-_BE_Spectrum_3.txt`
- `cleanup/runtime/postmerge_lib/P021/versions/V015/exports/61235f44-0704-486c-83e5-1e3a39ba79f8/V015_anygraph_03_Mic_Polar_-_BE_Spectrum_4.txt`
- `cleanup/runtime/postmerge_lib/P021/versions/V021/exports/61235f44-0704-486c-83e5-1e3a39ba79f8/V021_anygraph_01_Mic_Polar_-_BE_Spectrum_2.txt`
- `cleanup/runtime/postmerge_lib/P021/versions/V021/exports/61235f44-0704-486c-83e5-1e3a39ba79f8/V021_anygraph_02_Mic_Polar_-_BE_Spectrum_3.txt`
- `cleanup/runtime/postmerge_lib/P021/versions/V021/exports/61235f44-0704-486c-83e5-1e3a39ba79f8/V021_anygraph_03_Mic_Polar_-_BE_Spectrum_4.txt`
- `cleanup/runtime/postmerge_lib/P021/versions/V022/exports/61235f44-0704-486c-83e5-1e3a39ba79f8/V022_anygraph_01_Mic_Polar_-_BE_Spectrum_2.txt`
- `cleanup/runtime/postmerge_lib/P021/versions/V022/exports/61235f44-0704-486c-83e5-1e3a39ba79f8/V022_anygraph_02_Mic_Polar_-_BE_Spectrum_3.txt`
- `cleanup/runtime/postmerge_lib/P021/versions/V022/exports/61235f44-0704-486c-83e5-1e3a39ba79f8/V022_anygraph_03_Mic_Polar_-_BE_Spectrum_4.txt`

Header facts:
- All files: `Data_Format=Complex`, `Data_Domain=Frequency`
- All files: `Param_Coord_x2` has 19 angles (`-90..90`)
- Per version, observed `Param_Coord_x3` values are always: `45`, `90`, `90`
- Per version, files #3 and #4 are byte-identical (same SHA256), indicating duplicate 90deg export.

Example (V022):

| file | x3 | sha256 (short) |
|---|---:|---|
| `V022_anygraph_01..._2.txt` | 45 | `9817b9a9b37e9839` |
| `V022_anygraph_02..._3.txt` | 90 | `8a1388cc585d089b` |
| `V022_anygraph_03..._4.txt` | 90 | `8a1388cc585d089b` |

No `Param_Coord_x3=0` file was found for B006.

## 4) DB Ingestion Evidence

DB: `cleanup/runtime/postmerge_lib/P021/dataset/project.sqlite`

### 4.1 Inventory query

```sql
SELECT project_id,batch_id,version_id,coalesce(run_id,'') run_id,orientation,COUNT(*) n
FROM polar_measurements
WHERE project_id='P021' AND batch_id='B006'
GROUP BY project_id,batch_id,version_id,coalesce(run_id,''),orientation
ORDER BY version_id,run_id,orientation;
```

Result pattern for all B006 versions (`V015..V022`):
- `orientation='V'`, count 1
- `orientation='X3_45'`, count 1
- no `H`

### 4.2 Integrity query

```sql
SELECT m.version_id,coalesce(m.run_id,'') run_id,m.polar_id,m.orientation,
       m.freq_count,m.angle_count,m.freq_count*m.angle_count expected,
       COUNT(p.polar_id) actual
FROM polar_measurements m
LEFT JOIN polar_points p ON p.polar_id=m.polar_id
WHERE m.project_id='P021' AND m.batch_id='B006'
GROUP BY m.version_id,coalesce(m.run_id,''),m.polar_id,m.orientation,m.freq_count,m.angle_count
ORDER BY m.version_id,run_id,m.orientation,m.polar_id;
```

Result: all rows satisfy `actual == expected` (e.g. `12*19=228`).

Conclusion: importer is ingesting what exists in TXT; H is absent in source data, not dropped during point ingestion.

## 5) Orientation Mapping Code Check

`app/polar_txt_parser.py` maps:
- `0 -> H`
- `90 -> V`
- `42 -> D`
- all other values -> `X3_<value>`

So if `Param_Coord_x3=0` existed, importer would produce `H`. B006 has no `0` in TXT headers.

## 6) Root Cause(s) and Confidence

1. **Primary root cause (very high confidence): wrong inclination persisted for H in Batch export settings.**
- `Polars H` is saved as `inclination=90` in B006 settings.
- cfg emits H with `Inclination=90`.
- exports then produce `x3=90` twice (V and H effectively same plane).

2. **Secondary issue (high confidence): default inclination constants are inconsistent with desired defaults.**
- UI/model defaults currently bias polar card inclination to `90`.
- Built-in default D spec still uses `42` in several places.

3. **Reliability issue (medium confidence): any-graph fallback naming drops explicit plane identity in filenames.**
- Exports are named `...anygraph_01/02/03...` and not `_H/_V/_D`.
- Plane identity still recoverable from headers, but filename-level identity is not deterministic by plane.

## 7) Exact Point Where H Is Lost

H is first lost at **persisted batch export settings** (`sim_export_settings.export_specs`): the H spec is already configured with `inclination=90` instead of `0`.

Downstream stages (cfg generation, export, ingestion) preserve this value; they do not reconstruct H.

## 8) Minimal Fix Plan (next phase)

1. **Set single-source defaults for polar inclinations (H=0, V=90, D=45)** and apply consistently in:
- `ui/batch_export_panel.py` (advanced card defaults, default spec generation, load fallback)
- `app/runtime_orchestrator.py` default polar specs
- `app/runner_test_harness.py` default polar specs (test harness parity)

2. **Preserve persisted values safely**:
- On loading existing batches, only apply defaults when value is missing/invalid.
- Do not overwrite user-provided inclinations.

3. **Keep plane identity stable through exports**:
- Ensure exported polar outputs can carry deterministic plane tags (`H/V/D`) in copied output filenames when orientation is known from header.
- Keep backward compatibility for unknown orientations.

4. **Orientation normalization compatibility**:
- Add/retain D aliases for both `42` and `45` on analyzer/import side without collapsing unknowns.

5. **Tests**:
- batch export settings persistence for default inclinations
- cfg generation includes correct inclinations for H/V/D
- orientation mapping test for `0->H`, `90->V`, `42/45->D` behavior as applicable
- filename collision/plane-tag uniqueness test where relevant
