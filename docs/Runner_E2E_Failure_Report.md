# Runner E2E Failure Report

Date: 2026-02-15

## Latest Full E2E Run
- Command:
  - `python -m app runner-test run --case test_cfg_baseline --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`
- `test_run_id`: `15aaccb8-6120-49ed-8b71-74b65c90a3dd`
- Result: `failed`

## Failing Step
- Stage: `AKABAK open_project`
- Error:
  - `ABEC open-file dialog did not close with loaded-project signal`
- Diagnostics:
  - `runner_test_workspace/logs/15aaccb8-6120-49ed-8b71-74b65c90a3dd/akabak/open_dialog_failure_20260215_172445.json`

## Evidence Snapshot
- File dialog is detected as standard `#32770` (`Open File`).
- Full absolute ABEC path is written/read back successfully:
  - `C:\Horns\test\ABEC_FreeStanding\Project.abec`
- Confirmation actions (UIA/Win32/scoped key) do not close the dialog deterministically.
- Main window remains:
  - `Akabak-Demo - (new)`

## What Is Green In The Same Run
- `ath`: `ok`
- `post_ath_le_repair`: `ok`
- `pre_akabak_guard`: `ok`
  - mesh file present (`input.msh`)

## Micro-Harness Evidence
- `open-dialog-only` (strict postcondition) is currently red.
- `import-start-apply-only` is also red because project open is not reliable first.
- Typical failure artifact:
  - `runner_test_workspace/logs/<run_id>/akabak/open_dialog_failure_*.json`

## Root Cause Class (current)
- `akabak_open_dialog_not_closing_after_setpath`

## Next Action
1. Stabilize open-dialog close contract first (5/5 open-dialog-only green).
2. Re-run baseline E2E (`repeats=1`, then `repeats=3`).
3. Continue with RadImp analysis only after VACS export stage is reachable.
