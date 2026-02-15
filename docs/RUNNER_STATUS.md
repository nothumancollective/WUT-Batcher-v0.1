# Runner Status (2026-02-15)

## Scope Reviewed
- `docs/RUNNER_AUDIT.md`
- `docs/RUNNER_TEST_HARNESS.md`
- `docs/UI_AUTOMATION_CONTRACTS.md`
- `docs/Runner_E2E_Failure_Report.md`
- `docs/Runner_E2E_Results.md`
- `app/akabak_driver.py`
- `app/vacs_driver.py`
- `app/ui_automation/*`

## Current State
- Runner test harness is isolated under `runner_test_workspace/` and persists telemetry to `runner_test_workspace/db/runner_test.sqlite`.
- Safe cleanup is allowlist-based and limited to workspace paths (`cfg`, `ath_out`, optional `exports`).
- UI automation is UIA/Win32 contract-driven; no pixel/OCR/coordinate decisions.
- `open-dialog-only` micro-harness is stable with absolute path write + readback + close/load postcondition.
- Full E2E now fails early at `pre_akabak_guard` when referenced mesh artifacts are missing, instead of failing late in AKABAK.

## AKABAK/VACS Contracts
- AKABAK open-file dialog contract is active (`#32770`, filename edit `1148`, open button `1`).
- AKABAK interpreter flow now tracks `Start Importing -> Apply` as the primary import path.
- VACS export remains contract-driven with deterministic export-spec mapping and TXT ingestion validations.

## Known Blocker
- ATH output still references mesh files that are not present at import time (`ath.msh`), which blocks successful AKABAK import and therefore full E2E completion.
- Failure is reproducible and classified in DB/docs with run-level diagnostics.

## Added In This Iteration
- New micro-harness: `runner-test import-start-apply-only` for AKABAK interpreter import flow.
- Import diagnostics dump on failure (`import_failure_*.json/.txt`) persisted into `artifacts` + `ui_observations`.
- AKABAK contract updated with explicit `import_start_apply` action and missing-mesh modal classification.
