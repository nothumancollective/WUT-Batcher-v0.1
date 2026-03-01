# Final Dimensions Read-Side Notes

Date: 2026-02-25

Scope: Analyzer read-side verification only (no Runner/export ingest changes).

## Current wiring (Analyzer)

- Analyzer run listing already reads final dimensions from DB:
  - `app/services.py` selects `versions.ath_length_mm`, `versions.ath_width_mm`, `versions.ath_height_mm`.
  - It reads `ath_dimensions.length_mm/width_mm/height_mm` (strict project+batch scope) and now also falls back by `(run_id, version_id)` when legacy rows carry stale scope keys.
  - If present, Analyzer also accepts `experiment_metrics.final_length_mm/final_width_mm/final_height_mm` by `run_id` as a final read-side fallback.
- Version Information UI renders dimensions from the selected payload:
  - `app/gui.py` -> `_update_version_information_panel(...)`
  - Display format: `L×M×H  <L> × <M> × <H> mm` (one decimal each) when all three values exist.
  - UI accepts `ath_*` keys plus fallback keys (`final_*`, `length/width/height`) and parses numeric strings like `123,4 mm`.
  - If any dimension is missing, UI renders `—` (placeholder) and tooltip `Not available`.

## DB verification performed

- Scanned local repository `project.sqlite` files (`44` DB files found).
- Queried `versions` and `ath_dimensions` for non-null dimension triples.
- Result:
  - `versions` rows with full `(ath_length_mm, ath_width_mm, ath_height_mm)`: `0`
  - `versions` rows with partial dimension data: `0`
  - `ath_dimensions` rows with full `(length_mm, width_mm, height_mm)`: `0`

## Conclusion

- Analyzer now displays final dimensions immediately when those DB fields are present in payload.
- In the local verification datasets used in that audit, dimensions were absent, so no populated dimensions value was shown.
- No fake dimensions are generated in UI.

## 2026-02-25 write-side correction (runner + DB)

### Root cause on write path

- ATH dimension persistence in runtime was gated by `dims.raw_line`.
- The parser accepted only a single-line pattern containing `Length + Width + Height` together.
- If ATH printed dimensions across multiple lines, persistence could be skipped even when numeric values existed.
- In mixed ATH stdout logs, non-final parameter echoes (for example `Length = ...`, `GCurve.Width = ...`) could be parsed before final dimensions and produce incorrect values.

### Fixed behavior

- `parse_ath_dimensions` now accepts split-line dimension output and reconstructs a raw trace text.
- The parser now prefers dimension-summary context lines (`Final ...` / `... dimension ...`) over generic parameter echoes and ignores dotted parameter-path keys (for example `GCurve.Width`).
- Runtime writes dimensions when all three numeric values are present.
- This write is executed as the first export-data persistence step after ATH stage completion, before downstream export ingestion.

### DB fields written (project + library DB)

- Table `ath_dimensions`:
  - `length_mm`
  - `width_mm`
  - `height_mm`
- Table `versions`:
  - `ath_length_mm`
  - `ath_width_mm`
  - `ath_height_mm`
- Scope guard for version update was tightened to include project and batch keys.

### Version Information UI mapping (current)

- Row label: `Dim (LxWxH)`
- Row placement: left info column, directly above `Throat / GCurve / Morph / Driver / Enclosure`.
- Row value format: `{L:.1f} × {W:.1f} × {H:.1f} mm`
- Missing dimensions: `—` with tooltip `Not available`.

## 2026-02-27 audit update (no code changes)

Scope:
- Re-audited end-to-end final-dimensions path with live project artifacts.

Observed path status:
1. ATH source lines are present in runtime logs
   - `Device width x height = <W> x <H> mm`
   - `Device length = <L> mm`
2. Runtime parser misses height on this line shape
   - `app/runners.py::parse_ath_dimensions` returns `(length, width, None)` for audited logs.
3. Runtime write is therefore skipped
   - `app/runtime_orchestrator.py` persists only when all three values are non-null.
4. Analyzer read/UI remain correct
   - Read side (`app/services.py`) and Version Information rendering (`app/gui.py`) already display dimensions when DB fields are populated.
   - Current blank display is caused by missing persisted triples, not UI formatting/binding errors.

## 2026-02-27 fix update

Root cause confirmed:
- Extraction layer bug in `app/runners.py::parse_ath_dimensions`.
- ATH geometry output line `Device width x height = <W> x <H> mm` was parsed as width-only by the generic token regex, leaving height unset.
- Runtime write in `app/runtime_orchestrator.py` requires complete `(length, width, height)`, so persistence was skipped.

Fix implemented:
- Parser now explicitly supports ATH pair signatures:
  - `Device width x height = <W> x <H> mm`
  - `Device length = <L> mm`
- Runtime extracts from the ATH `stdout` log tail after ATH completion.
- Extra extraction/write diagnostics are emitted only when `WUT_DEBUG_PIPELINE_STAGES=1`.

Persistence/read/UI contract after fix:
- Write targets unchanged (project DB + library DB mirror):
  - `ath_dimensions.length_mm/width_mm/height_mm`
  - `versions.ath_length_mm/ath_width_mm/ath_height_mm`
- Analyzer retrieval unchanged (`app/services.py`): reads `ath_*` values as primary source.
- Version Information formatting unchanged (`app/gui.py`):
  - label: `Dim (LxWxH)`
  - value: `{L:.1f} × {W:.1f} × {H:.1f} mm`
  - missing: `—`

Live validation:
- Real batch run (`B010`, run `9f33fb6a-7e8d-46eb-8e0f-0197d998fe0b`) wrote ATH dimensions for two versions (`ath_dimension_rows=2`).
- `V048` persisted with full triplet in both DBs and is returned by analyzer read API with non-null `ath_*` dimensions.
- Offscreen Analyzer page binding shows: `140.0 × 271.0 × 271.0 mm` for the retrieved run payload.

## 2026-03-01 runtime-minimization update

Reason:
- Follow-up runner forensics showed no reproducible stage-time regression from dimension parsing itself, but the initial fix had added avoidable hot-path work (`stdout`/`stderr` full-file readback plus unconditional extra debug events).

Write-side behavior now:
- Dimension extraction reads only the ATH `stdout` log tail (`64 KiB` cap) after ATH completes.
- No run-tree scans are used.
- If dimensions are incomplete, the run continues normally; an explicit debug record is written only when `WUT_DEBUG_PIPELINE_STAGES=1`.

Validation:
- Current real CLI run `9bfbca7e-7891-449f-ab36-a13a062380e7` (`B012`) succeeded with `ath_dimension_rows=2`.
- Current real GUI/offscreen worker run `b1ad0971-7084-44fa-822b-0243b6a9cdec` (`B013`) succeeded with `ath_dimension_rows=2`.
- Analyzer Version Information still renders the dimension row from persisted DB values.
