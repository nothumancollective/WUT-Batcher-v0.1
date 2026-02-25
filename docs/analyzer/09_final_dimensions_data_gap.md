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
  - If any dimension is missing, the dimensions line is hidden (no placeholder text).

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

### Fixed behavior

- `parse_ath_dimensions` now accepts split-line dimension output and reconstructs a raw trace text.
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
- Row value format: `{L:.1f} × {W:.1f} × {H:.1f} mm`
- Missing dimensions: `—` with tooltip `Not available`.
