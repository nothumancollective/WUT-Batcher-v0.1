# Final Dimensions Read-Side Notes

Date: 2026-02-25

Scope: Analyzer read-side verification only (no Runner/export ingest changes).

## Current wiring (Analyzer)

- Analyzer run listing already reads final dimensions from DB:
  - `app/services.py` selects `versions.ath_length_mm`, `versions.ath_width_mm`, `versions.ath_height_mm`.
  - It also reads `ath_dimensions.length_mm/width_mm/height_mm` and now falls back by `version_id` when a run-level key does not match.
- Version Information UI renders dimensions from the selected payload:
  - `app/gui.py` -> `_update_version_information_panel(...)`
  - Display format: `LxMxH  <L> x <M> x <H> mm` (one decimal each) when all three values exist.
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
- In the local verification datasets, dimensions are absent, so the dimensions line correctly remains hidden.
- No fake dimensions are generated in UI.
