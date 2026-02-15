# RadImp Baseline Report (Evidence-Only)

Date: 2026-02-15

## Scope
- Case: `test_cfg_baseline`
- Latest full E2E run: `15aaccb8-6120-49ed-8b71-74b65c90a3dd`

## Result
- RadImp export is currently **blocked upstream**.
- AKABAK `open_project` fails before solve and before VACS export.
- Therefore no `radimp_diagnosis` validation row is produced for the full E2E baseline run yet.

## Evidence
- Open-dialog failure artifact:
  - `runner_test_workspace/logs/15aaccb8-6120-49ed-8b71-74b65c90a3dd/akabak/open_dialog_failure_20260215_172445.json`
- In repeated open-dialog-only runs, evidence is consistent:
  - full ABEC path is written/read back,
  - dialog remains open,
  - main window title remains `Akabak-Demo - (new)`.

## Current Diagnosis Class
- `blocked_by_akabak_open_dialog_not_closing`

## What Is Already Verified
- ATH stage and mesh artifact guard pass.
- Post-ATH LE repair assertions pass.
- Failure is localized to AKABAK open/import interaction, not ATH output generation.

## Next Verification Step
1. Make `open-dialog-only` pass with strict postcondition (`dialog_closed && loaded_signal`) for 5/5 runs.
2. Re-run full baseline E2E and only then evaluate RadImp zero/non-zero classes.
