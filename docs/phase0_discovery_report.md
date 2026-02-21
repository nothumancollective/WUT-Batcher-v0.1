# Phase 0 Discovery Report (Runner/Export/Import/DB)

## 1) Executive Summary (10 bullets)
- `project.sqlite` is the per-project DB and `global.sqlite` is the shared library DB (`app/sql_dataset_store.py:104-105`); both are initialized on writer startup (`app/sql_dataset_store.py:112-114`).
- Current graph persistence is `graphs`, `graph_series`, `graph_points` (`app/sql_dataset_store.py:237`, `app/sql_dataset_store.py:260`, `app/sql_dataset_store.py:271`).
- Runtime export root per version/run is deterministic: `<project_root>/versions/<version_id>/exports/<run_id>` (`app/runtime_orchestrator.py:113-114`).
- Runner export flow is `run_batch_pipeline` -> `run_vacs_export_specs` -> `_ingest_vacs_exports` (`app/runtime_orchestrator.py:1842-1878`).
- External VACS automation currently exports all graphs via `scripts/vacs_export_save_all.py`; raw filenames are `<script_run_id>_<index>_<safe_title>.txt` (`scripts/vacs_export_save_all.py:1252-1253`, `scripts/vacs_export_save_all.py:1668`).
- Fallback any-graph mapping re-copies files into canonical names `<version_id>_anygraph_<index>_<safe_title>.txt` (`app/vacs_export_pipeline.py:176`).
- Polar outputs are currently misclassified as `graph_kind='spl'` in DB in observed datasets because inference favors `Data_LevelType=SoundPressure` (`app/vacs_export_pipeline.py:57-89`, DB evidence below).
- Across scanned `Mic_Polar` files (`n=299`), observed raw shape is always `Data_Format=Complex`, `Param_Coord_x2` present, `Param_Coord_x3` present, no `Abscissa` block, and 39 numeric columns per data row.
- Current parser/import path stores only one complex pair per frequency row (first 3 numeric tokens), so polar matrices are lossy (`app/vacs_txt_parser.py:212-216`; confirmed by DB/file dimension mismatch).
- DB schema updates are startup-time ensure/migrate (no external migration files), and consolidation to `global.sqlite` is operation-based dual-write plus `replication_queue` retry (`app/sql_dataset_store.py:654`, `app/sql_dataset_store.py:761-777`, `app/sql_dataset_store.py:1356-1399`).

## 2) Export Pipeline (A)

### A1) Located export code paths (launch -> selection -> naming -> ingest)

| Stage | File/Function | Evidence-backed behavior |
|---|---|---|
| Export root resolution | `app/runtime_orchestrator.py:113` `_version_exports_dir` | Computes `<project_root>/versions/<version_id>/exports/<run_id>`. |
| Pipeline orchestration | `app/runtime_orchestrator.py:1842-1858` | Calls `run_vacs_export_specs(...)` when export specs exist. |
| Export execution | `app/vacs_export_pipeline.py:225` `run_vacs_export_specs` | Uses external UIA script path when `akabak_executable` is provided (`app/vacs_export_pipeline.py:253`). |
| External VACS control | `scripts/vacs_export_save_all.py` | Finds VACS windows, opens Data Export dialog via F7/WM_COMMAND=52, Save As, exports TXT. |
| Graph selection order | `scripts/vacs_export_save_all.py` (graph list sorted by title in loop) | In observed runs, first exported graphs are `Mic Polar - BE_Spectrum #2/#3/#4` then RadImp. |
| Raw naming | `scripts/vacs_export_save_all.py:1252-1253` | `<script_run_id>_<loop_idx:02d>_<safe_title>.txt`. |
| Canonical any-graph naming | `app/vacs_export_pipeline.py:176` | `<version_id>_anygraph_<index:02d>_<safe_title>.txt`. |
| Contract extraction for ingest | `app/runtime_orchestrator.py:1053` `_extract_export_contracts` | Uses `vacs_export_summary.exports[*].output_path` as expected files. |
| TXT ingest entrypoint | `app/runtime_orchestrator.py:1131` `_ingest_vacs_exports` | Parses TXT, builds rows, writes via `writer.write_measurements(rows)` (`app/runtime_orchestrator.py:1242`). |
| Graph persistence | `app/sql_dataset_store.py:1662` `write_measurements` | Upserts `graphs` + `graph_series` + `graph_points` via `_dual_write("upsert_graphs", ...)` (`app/sql_dataset_store.py:1750`). |

### A2) How Runner currently decides “polar” (and what is reliable)

Observed decision signals ordered by reliability (current code + DB/file evidence):

1. Header metadata pattern (most reliable for actual polar content):
- Signal: `Param_Coord_x2` present, `Param_Coord_x3` present, `Data_Format=Complex` (often with `Param_Coord_Type=Spherical`).
- Evidence: `299/299` scanned `Mic_Polar` files carry `Param_Coord_x2`, `Param_Coord_x3`, `Data_Format=Complex`.
- Reliability: High for content-type detection; independent of DB `graph_kind`.

2. Source title/path contains `Mic Polar` / `Mic_Polar`:
- Signal from exported source title and filename.
- Evidence: present in most raw + canonical any-graph filenames; child window titles in UIA rounds are stable (`Mic Polar - BE_Spectrum #2/#3/#4`).
- Reliability: Medium-high, but not complete (counterexample below).

3. Variant pattern in any-graph fallback (`external_01/02/03`):
- Signal from `export_meta.contract.variant` and DB `variant`.
- Evidence: across DBs with Mic Polar rows, `external_01 -> x3=42`, `external_02 -> x3=0`, `external_03 -> x3=90` (13 each).
- Reliability: Medium; depends on fallback mode and preserved contract metadata.

4. `graph_kind` / `graph_type` fields (currently unreliable for polar):
- Signal: `_infer_graph_kind_for_any_mapping` scoring (`app/vacs_export_pipeline.py:57-110`).
- Evidence: all observed Mic Polar DB rows are stored as `graph_kind='spl'` (39 total across project DBs), because inference favors `SoundPressure`.
- Reliability: Low for polar detection.

5. UI list item titles only (weakest):
- Signal: UI child window name text.
- Reliability: Lowest (locale/title drift risk).

DB row examples proving current misclassification:
- `V077_anygraph_01_Mic_Polar_-_BE_Spectrum_2.txt` -> `graph_kind='spl'`, `inferred_graph_kind='spl'`, but header has `Param_Coord_x2` + `Param_Coord_x3=42`.
- `V001_spl.txt` (no `Mic_Polar` in name) still has `Param_Coord_x2` + `Param_Coord_x3=42`.

#### Recommended PRIMARY polar detection rule (evidence-backed)
- `PRIMARY`: classify as polar if parsed metadata contains all of:
  - `Param_Coord_x2` (non-empty angle list)
  - `Param_Coord_x3` (orientation marker)
  - `Data_Format=Complex`
- Reason: survives naming/misclassification drift and matched all observed polar-like content.

#### Recommended fallback rule
- `FALLBACK`: if metadata is incomplete, use `source_file`/`source_title` contains `Mic_Polar` or `Mic Polar`; secondary fallback to any-graph `variant` mapping (`external_01/02/03`) only when header missing.
- Important: filename suffix `BE_Spectrum_2/3/4` is not fully reliable by itself (observed anomalies in raw exports).

### A3) Required export options and UIA automation evidence

Data Export dialog signature:
- Window class/title: `TForm_Export` / `Data Export` (`scripts/vacs_export_save_all.py:371-381`, `scripts/vacs_export_dialog_rounds.py:129-140`).

Live state probe evidence (UIA + Win32, 2026-02-21):
- `runner_test_workspace/logs/vacs_export_state_probe/run_20260221_130626/summary.json`
- Targeted graphs: `Mic Polar - BE_Spectrum #2/#3/#4`
- `BM_GETCHECK` states were identical for all three polar dialogs.

#### UIA Selector Table

| Control purpose | UIA selector | Expected state | Verification method | Fallback selector |
|---|---|---|---|---|
| Open Data Export dialog | `Window[class_name='TForm_Export', title='Data Export']` | visible+enabled | UIA signature check (`class_name/title`) | Win32 top-level dialog class `TForm_Export` |
| Keep header params (angle/orientation keys) | Under Data Export: `TRzCheckBox` title `Export of parameters` | checked (`1`) | Win32 `BM_GETCHECK` on checkbox handle | Win32 child `class='TRzCheckBox'` text `Export of parameters` |
| Abscissa/Data block toggle | Under Data Export: `TRzCheckBox` title `Abscissa separat` | unchecked (`0`) in observed polar exports | Win32 `BM_GETCHECK` | Win32 child `TRzCheckBox` text `Abscissa separat` |
| Matrix form toggle | (UIA often does not expose this checkbox in contour case) | unchecked (`0`) in observed polar exports | Win32 `BM_GETCHECK` on `Try matrix form` | Win32 child `TRzCheckBox` text `Try matrix form` |
| Single file toggle | (UIA often does not expose this checkbox in contour case) | unchecked (`0`) in observed polar exports | Win32 `BM_GETCHECK` on `Single file` | Win32 child `TRzCheckBox` text `Single file` |
| Complex/phase formatting behavior | `TRzCheckBox` title `Phase as radiant` | unchecked (`0`) in observed polar exports | Win32 `BM_GETCHECK` | Win32 child `TRzCheckBox` text `Phase as radiant` |
| Save action | `TRzBitBtn` title/text contains `Save...` | actionable | existing save ladder (`win32 click`/`BM_CLICK`) | Win32 child `TRzBitBtn` text `&Save...` |

Observed checkbox states for polar dialogs (`#2/#3/#4`):
- Checked: `Export of parameters`.
- Unchecked: `Abscissa separat`, `Try matrix form`, `Single file`, `Phase as radiant`, `Preserve continuous phase`, `Points within process window only`, `Scaling parameters extra`, `Amplitude as rms-values`, `Export of graph view`.

Important automation finding:
- Checkbox `AutomationId` values are not stable across runs/dialog instances.
- In contour dialog probes, attempts to toggle checkboxes via Win32 `BM_CLICK` and UIA `type_keys(' ')` did not change state (controls behaved read-only in tested path). Enforce-by-verification (assert state, fail fast on mismatch) is currently more reliable than enforce-by-toggle.

### A4) Export location + naming contract

#### Strict path spec
- Export directory per version/run:  
  `<project_root>/versions/<version_id>/exports/<run_id>/`

Observed filename patterns inside that folder:
1. Raw external export script output:
- `<script_run_id>_<index:02d>_<safe_title>.txt`
- Example: `20260221_130626_01_Mic_Polar_-_BE_Spectrum_2.txt`

2. Canonical any-graph re-mapped output (used by ingest contract):
- `<version_id>_anygraph_<index:02d>_<safe_title>.txt`
- Example: `V077_anygraph_01_Mic_Polar_-_BE_Spectrum_2.txt`

3. Non-anygraph/spec-rendered output (template-driven):
- `ExportSpec.output_name_template` (default often `{version_id}_{graph_kind}.{format}`)
- Example observed in older dataset: `V001_spl.txt`.

#### Mapping rule: `file_path -> {project_id, batch_id, version_id, run_id, orientation}`
1. Parse path segments:
- `project_id` = directory before `versions`.
- `version_id` = segment right after `versions`.
- `run_id` = segment right after `exports`.
2. Resolve `batch_id` deterministically from DB:
- Primary: `versions.version_id -> batch_id`.
- Consistency check: `runs.run_id -> batch_id` should match.
3. Resolve `orientation`:
- Primary: header `Param_Coord_x3` (numeric).
- Fallback 1: `export_meta.metadata.Param_Coord_x3` if already parsed.
- Fallback 2: any-graph `variant` mapping (`external_01->42`, `external_02->0`, `external_03->90`) when header missing.
- Do **not** rely solely on filename suffix `BE_Spectrum_2/3/4`.

Canonical example:
- `C:\...\P001\versions\V077\exports\8c86fced-...\V077_anygraph_01_Mic_Polar_-_BE_Spectrum_2.txt`
- maps to `{project_id:P001, batch_id:B010_FASTCHECK, version_id:V077, run_id:8c86fced-..., orientation:42}`.

## 3) TXT Format Classes (B1)

Sampling summary:
- `299` `*Mic_Polar*.txt` files scanned across many runs/versions; representative set of 20 files collected from distinct export run folders.

### Format Matrix

| Format | Detection rule | Frequency extraction | Angle extraction | Data shape | Known pitfalls |
|---|---|---|---|---|---|
| Legacy complex matrix (observed) | `Data_Format=Complex`, `Data`/`Data_End`, no `Abscissa` block, numeric row width `39` | First numeric token per data row | `Param_Coord_x2` CSV list | `freq_rows x (1 + 2*angle_count)`; observed `angle_count=19`, row widths always `39` | Parser currently reads only first 3 numeric tokens per row (lossy for matrices). |
| Abscissa/Data blocks | Presence of explicit `Abscissa` section + data matrix section | UNKNOWN (not observed) | UNKNOWN (not observed) | UNKNOWN | Not observed in workspace corpus (`0` files). |

Observed header keys in current Mic Polar corpus:
- Always present: `Data_Format`, `Data_Domain`, `Data_LevelType`, `Data_BaseUnit`, `Param_Coord_x2`, `Param_Coord_x3`, `Param_Coord_Type`, `Param_Coord_AngularFormat`.

Observed dimensions and variability:
- Angle bins (`Param_Coord_x2`): one observed pattern only: `0..90` step `5` (19 bins).
- Orientation (`Param_Coord_x3`): observed values `42`, `0`, `90`.
- Frequency row counts: observed `{5, 6, 10, 16}`.
- Data row width: always `39` (1 frequency + 38 real/imag values).

### Norm Angle Resolution Policy (B2)

Evidence:
- UI stores per-polar `norm_angle` in advanced payload (`ui/batch_export_panel.py:87`, `ui/batch_export_panel.py:615`).
- `version.json` / `batches.sim_export_params` contain `norm_angle` in some datasets (observed values currently all `0`).
- Runtime CFG writer `_apply_sim_export_settings_to_cfg` does not currently apply `norm_angle` into generated cfg blocks (`app/runtime_orchestrator.py:220+`; no `norm_angle` assignment).
- Scanned Mic Polar TXT headers contain no `norm_angle` key (`n=299`).

Definitive import policy (for implementation):
1. If TXT header includes explicit norm-angle key in future, use that file-local value.
2. Else if export contract for that file contains a mapped spec option `norm_angle`, use it.
3. Else read from version/batch export settings (`sim_export_params.export_specs[*].options.norm_angle`) for the producing version.
4. If multiple candidate specs map to one file and candidate `norm_angle` values differ, set `norm_angle_deg=UNKNOWN` and emit conflict flag.
5. If no source provides it, persist `NULL` and record `norm_angle_source='missing'`.

Current observed result under this policy:
- resolvable values are `0` in available datasets, but per-file spec mapping in any-graph fallback is ambiguous when specs diverge (see Unknowns).

## 4) Import Pipeline (B2)

### Current Import Pipeline

```text
TXT file(s)
  -> app.runtime_orchestrator._ingest_vacs_exports
      -> app.vacs_txt_parser.parse_vacs_txt_file
      -> flat measurement rows (project/batch/version/run/graph/series/point)
      -> writer.write_measurements(rows)
          -> SqlDatasetStore._dual_write("upsert_graphs", payload)
              -> _op_upsert_graphs
                  -> graphs
                  -> graph_series
                  -> graph_points
```

Entrypoint references:
- `_ingest_vacs_exports`: `app/runtime_orchestrator.py:1131`
- Parser call: `app/runtime_orchestrator.py:1166`
- Write call: `app/runtime_orchestrator.py:1242`
- Parser numeric extraction: `app/vacs_txt_parser.py:212-216`

### Confirmed current limitation
- For matrix rows, parser uses only `numbers[0]` (x), `numbers[1]` (y), `numbers[2]` (y_imag) and ignores remaining columns.
- Concrete evidence:
  - File: `...V077_anygraph_01_Mic_Polar_-_BE_Spectrum_2.txt`
  - File shape: `6` data rows, `39` columns, `19` angle bins -> expected `6*19=114` complex cells.
  - Stored DB for that graph: `series_count=1`, `point_count=6`.

### Recommended insertion point for new `polar_*` importer
- Best hook: inside `_ingest_vacs_exports`, immediately after parse and before flattening point rows.
- Branch logic:
1. Detect polar content using metadata-based PRIMARY rule.
2. For polar content: parse full matrix into `polar_*` payloads.
3. Keep existing legacy graph write path unchanged for non-polar content.
4. For backward compatibility, optionally keep writing current legacy graph rows for polar too (feature flag), until downstream consumers migrate.

## 5) Migrations (C) — Playbook

### D1) Migration mechanism
- There are no external/versioned migration files.
- Schema is ensured on startup in `SqlDatasetStore._init_db()` and patched in `_migrate_schema()` (`app/sql_dataset_store.py:357`, `app/sql_dataset_store.py:654`).
- Both `project.sqlite` and `global.sqlite` run the same init/migrate path (`app/sql_dataset_store.py:112-114`).

### Migration Playbook (exact entrypoints)
1. Add new `polar_*` tables and indexes in `SqlDatasetStore._init_db` and `_migrate_schema`.
2. If backfill is required, add a dedicated `_migrate_<table>_schema` helper and call it from `_migrate_schema`.
3. Update schema descriptor table list (`persist_schema_descriptor`) if needed.
4. Run migrations in dev:
- `python -m app run-sample --dry-run`
- or instantiate writer directly for a project root (one-liner script).
5. Run migrations in runner E2E path:
- `python -m app run pipeline --project-json <...> --batch-json <...> --dry-run`
6. Verify with SQL:
- `SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'polar_%';`
- run for both project DB and global DB.

## 6) Replication to `global.sqlite` — Checklist

### D2) Current replication/consolidation behavior
- Write path is operation-based dual-write, not table-whitelist-based:
  - Project DB apply -> Global DB apply (`_dual_write`) (`app/sql_dataset_store.py:761-770`)
  - On global failure, queue operation JSON in `replication_queue` (`app/sql_dataset_store.py:713-721`, `app/sql_dataset_store.py:771-777`)
  - Replay via `retry_pending_global_writes` (`app/sql_dataset_store.py:1356-1399`)
- Operation dispatch is explicit in `_apply_operation` (`app/sql_dataset_store.py:723-759`).

### Replication Integration Checklist for `polar_*`
- Add `CREATE TABLE IF NOT EXISTS polar_*` to `_init_db` so both DBs have schema.
- Add migration guards/index creation for `polar_*` in `_migrate_schema`.
- Add new operation name(s) in `_apply_operation` (e.g., `upsert_polar_graphs`).
- Implement corresponding `_op_*` handlers for inserts/updates/deletes in both DBs.
- Route writer entrypoint through `_dual_write(...)` so project/global stay in sync.
- Extend cleanup/delete logic (`_op_delete_runs`, `cleanup_unpinned_runs` counts) if `polar_*` rows are keyed by run/graph/version.
- Extend any federation/export payload item-count accounting if `polar_*` data is included in exports.
- Validate retry path with:
  - forced global write failure -> queue row exists,
  - `python -m app dataset sync-global --max-items-per-project N` -> queued rows become `synced`.

## 7) Risks + Unknowns

### Top 10 Risks (with detection + mitigation)

| Risk | Detection | Mitigation |
|---|---|---|
| 1. UIA `AutomationId` instability for dialog controls | Compare control IDs across runs/dialogs; IDs change frequently | Select by dialog signature + control class + control text; treat `AutomationId` as opportunistic only |
| 2. Polar dialog checkboxes appear non-toggleable in current automation path | A/B probes: `BM_CLICK` and UIA key toggle do not change `BM_GETCHECK` | Implement verify-and-fail-fast guard; if mismatch, abort export and surface actionable error |
| 3. Any-graph inference mislabels polar as `spl` | DB audit: Mic Polar rows persisted as `graph_kind='spl'` | Decouple polar detection from `graph_kind`; use metadata-based polar detection |
| 4. Filename-only orientation inference can be wrong | Audit raw files: `BE_Spectrum_2` not always `x3=42` | Read orientation from header `Param_Coord_x3`; use filename/variant only as fallback |
| 5. Parser lossy matrix handling | Compare file matrix width vs persisted points | New polar matrix parser path + dedicated `polar_*` schema |
| 6. Unknown future TXT shape (`Abscissa` format unobserved) | Regression tests with fixture corpus including synthetic Abscissa files | Add explicit format detection and parser branching with hard validation |
| 7. Variable frequency grids across runs | Validate row counts/frequency vectors per file before merge | Store per-file grid metadata; normalize only with explicit policy |
| 8. Partial plane export (missing #2/#3/#4) | Per-run completeness check on expected orientations | Mark run incomplete, do not silently aggregate partial sets |
| 9. Norm-angle ambiguity in any-graph mode | If multiple candidate specs differ and file-spec mapping is not explicit | Persist `UNKNOWN` + conflict flag; require deterministic mapping upgrade before strict use |
| 10. Replication gaps for new tables | Integration tests with forced global failure and replay | Add operation handlers + cleanup + replay tests before rollout |

### Unknowns (strict)
- `UNKNOWN`: deterministic, idempotent setter method for polar Data Export checkboxes in current contour-dialog automation path (read state is proven; write success not proven).
- `UNKNOWN`: whether VACS Preferences sub-dialog contains additional stable controls for forcing alternate TXT shapes in this environment.
- `UNKNOWN`: deterministic mapping from any-graph exported file to specific requested polar spec when multiple requested specs exist (current contract has `requested_spec_ids` list but not per-file spec binding).
- `UNKNOWN`: real-world Abscissa/Data-block polar TXT examples in this workspace (none observed).
- `UNKNOWN`: conflict behavior when future batches use differing per-spec `norm_angle` values (current observed values are all `0`).

## 8) Implementation Readiness Checklist (✅/❌)

### REQUIRED INFO FOUND
- ✅ DB identity and roles (`project.sqlite` vs `global.sqlite`) confirmed.
- ✅ Current graph storage tables confirmed (`graphs`, `graph_series`, `graph_points`).
- ✅ Export code path and ingest code path fully identified.
- ✅ Export directory and filename contracts identified (raw + canonical any-graph).
- ✅ Polar content markers in TXT headers identified and quantified.
- ✅ Current parser/import loss point identified with concrete dimension mismatch evidence.
- ✅ Migration mechanism and runtime entrypoints identified.
- ✅ Replication mechanism and required integration touchpoints identified.
- ✅ UIA selector inventory for Data Export dialog controls captured, including live checkbox states for polar dialogs.

### MISSING / BLOCKED
- ❌ Proven write-capable, idempotent automation method to enforce checkbox states in polar contour export dialog.
  - Next action: build a dedicated control-setter probe using additional Win32/UIA patterns (e.g., message sequences specific to `TRzCheckBox`) and fail-safe verification.
- ❌ Real sample files for Abscissa/Data-block format.
  - Next action: generate/export with manually changed VACS settings in controlled session, then add fixtures to parser tests.
- ❌ Deterministic per-file mapping from any-graph output to original requested polar spec (for per-spec norm-angle resolution when values diverge).
  - Next action: extend export contract generation to include `resolved_spec_id` per exported file before ingest.
- ❌ Verified conflict behavior for non-zero/divergent `norm_angle` across multiple polar specs.
  - Next action: create controlled batch with distinct `norm_angle` values and run end-to-end capture.
