# Preflight Audit: Project Library Merge + Version Info Enhancements

Date: 2026-02-25
Branch: feature/polar-analyzer-ui (pre-merge)

## Scope

- Merge readiness from `feature/project-library-storage` into `feature/polar-analyzer-ui`
- Project page Export bar cleanup control status
- Final dimensions persistence path and Analyzer display path
- Version score rendering mode in Version Information

## Repo/Docs archaeology findings

- `feature/polar-analyzer-ui` is an ancestor of `feature/project-library-storage`:
  - merge-base = `6c430b6` (current `feature/polar-analyzer-ui` HEAD)
  - merge strategy can be clean (fast-forward or no-ff merge commit).
- Existing Analyzer docs already discuss dimensions read-side behavior:
  - `docs/analyzer/09_final_dimensions_data_gap.md`
  - `docs/analyzer/03_kpi_scoring_model.md`
- In this pre-merge branch state, release-level storage docs are not present yet (`docs/release/*` missing); they exist on `feature/project-library-storage` and will arrive with merge.

## Current code baseline (pre-merge)

### Export bar cleanup button

- Project page Dashboard export bar currently contains:
  - `Open Export Dialog`
  - `Runs verwalten...`
  - `Testdaten aufraeumen...`
- Source: `app/gui.py` (`DashboardPage` export grid).

### Final dimensions persistence path

- ATH dimensions are parsed in runner:
  - `app/runners.py::parse_ath_dimensions`
- Runtime writes ATH dimensions through tidy writer:
  - `app/runtime_orchestrator.py` -> `writer.write_ath_dimensions(...)`
- DB write path updates both `ath_dimensions` rows and `versions.ath_*` columns:
  - `app/sql_dataset_store.py::_op_upsert_ath_dimensions`

### Analyzer Version Information mapping

- Version Information panel reads dimensions from payload keys:
  - primary: `ath_length_mm`, `ath_width_mm`, `ath_height_mm`
  - fallback: `final_*` and raw `length/width/height`
- Display format is deterministic with one decimal and `mm` when all 3 exist.
- Source: `app/gui.py::_update_version_information_panel`
- Incomplete triplets are hidden (no fallback placeholder row in this branch state).

### Score display mode (pre-merge)

- Score in Version Information is currently rendered as plain metric text in KPI rows, not as a dedicated colored chip.
- Source:
  - `VERSION_INFO_STAGE_METRICS` includes `score`
  - `_sync_version_metric_rows()` fills text labels.

## Risk and change boundaries for next phases

- Keep runner/analyzer/batch logic unchanged except:
  - ensure final dimensions write ordering and dual-DB persistence are explicit and deterministic
  - expose dimensions and score chip in Version Information UI only
- Keep single storage authority after merge:
  - use merged project-library `StorageManager` path system; do not reintroduce legacy resolver flows.
