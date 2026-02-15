# Runner E2E Results

Date: 2026-02-15

## AKABAK Open-Dialog Micro-Harness (Real VM)
Command:
- `python -m app runner-test open-dialog-only --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --abec-path "runner_test_workspace\\tmp\\real_abec\\ath\\Project.abec" --repeats 5 --workspace-root "runner_test_workspace"`

Outcome:
- `ok=true`
- 5/5 succeeded

Run IDs:
- `b052b8fd-bdc7-410d-b860-dab479ae55ce`
- `8780c294-1ccb-49ea-b1e2-65eb7ee294fb`
- `875bcd90-2248-42d2-b5aa-9cb2c7685bc6`
- `35afe2b6-ddf2-4b09-aadc-7a1645000058`
- `accdf7e0-9960-406f-b9b7-bbf83fba9d57`

Step timing snapshot (from `test_run_steps`):
- `open_dialog_only`: ~4-5s per run
- `preflight`: <1s
- `safe_clean`: <1s

Validation status:
- `open_dialog_close`: `ok` in all 5 runs

## Full E2E Smoke (Real VM)
Command:
- `python -m app runner-test run --case smoke_fast --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`

Outcome:
- `ok=false`
- `test_run_id`: `b0bdcff9-ae45-4915-84ac-48862af5a058`
- failure reason: AKABAK import modal reports missing mesh file (`ath.msh`)

Reference:
- Detailed failure analysis: `docs/Runner_E2E_Failure_Report.md`
