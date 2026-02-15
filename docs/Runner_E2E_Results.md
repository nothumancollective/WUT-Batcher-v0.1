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
- latest `test_run_id`: `9bdda5f1-904e-4d71-acee-77eb96107aa5`
- failure reason: `pre_akabak_guard_missing_mesh_artifact` (`ath.msh`)

## AKABAK Import-Start-Apply Micro-Harness (Real VM)
Command:
- `python -m app runner-test import-start-apply-only --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --abec-path "runner_test_workspace\tmp\real_abec\ath\Project.abec" --repeats 5 --workspace-root "runner_test_workspace"`

Outcome:
- `ok=false`
- 5/5 consistent failure classification (`missing mesh modal before apply`)

Run IDs:
- `4aa8f411-0769-4939-b4ac-b789452d275a`
- `75c0323f-c1a8-44f5-b305-bf8114bcef76`
- `7821d89f-f445-4da1-9c97-33ffa505b49a`
- `63ec0d8e-3723-49a3-852e-f5b6b25fe4d3`
- `6f0568ce-139b-4ac7-ad15-bb1b0d69eef7`

Observation:
- `open_project` step is stable in all 5 runs.
- `import_start_apply` fails deterministically with AKABAK modal:
  - `Cannot find Mesh-File ...\ath\ath.msh`
- Failure diagnostics now persisted per run:
  - `runner_test_workspace/logs/<run_id>/akabak/import_failure_*.json`

Reference:
- Detailed failure analysis: `docs/Runner_E2E_Failure_Report.md`
