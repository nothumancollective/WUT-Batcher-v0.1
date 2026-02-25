# Final Dimensions Data Gap (Verification Notes)

Date: 2026-02-25

Scope: Analyzer read-side verification only (no Runner/export ingest changes).

## Existing wiring

- Analyzer run listing already reads final dimensions from DB:
  - `app/services.py` selects `versions.ath_length_mm`, `versions.ath_width_mm`, `versions.ath_height_mm`.
  - It also has fallback mapping from `ath_results.length_mm/width_mm/height_mm` when available.
- Version Information UI already renders dimensions from payload:
  - `app/gui.py` -> `_update_version_information_panel(...)`
  - Display format: `L x W x H mm` when all three values exist.

## DB verification performed

- Scanned local repository `project.sqlite` files (`44` DB files found).
- Queried `versions` and `ath_results` for non-null dimension triples.
- Result:
  - `versions` rows with full `(ath_length_mm, ath_width_mm, ath_height_mm)`: `0`
  - `versions` rows with partial dimension data: `0`
  - `ath_results` rows with full `(length_mm, width_mm, height_mm)`: `0`

## Conclusion

- Final Dimensions are not currently present in available DB data, so Analyzer correctly shows `--`.
- No UI placeholder/fake values were added.

## Follow-up (out of current task scope)

- Populate `versions.ath_*` (or reliable `ath_results` fallback) during ATH ingest/export pipeline so Analyzer can display real final dimensions.
- This requires Runner/export-side ingestion work and is intentionally not done in this Analyzer UI task.
