# Runner E2E Failure Report

Date: 2026-02-15

## Latest Full E2E Run Context
- Command:
  - `python -m app runner-test run --case smoke_fast --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`
- `test_run_id`: `b0bdcff9-ae45-4915-84ac-48862af5a058`
- Result: `failed`

## Failing Step
- Stage: AKABAK import transition (`import_if_needed`)
- Error summary:
  - `AKABAK import modal detected: {'title': 'Error', 'class_name': '#32770', 'message': 'Cannot find Mesh-File at ...\\ath\\ath.msh', 'buttons': ['OK', 'Schliessen']}`
- Runner behavior:
  - Open-file dialog handling is now deterministic and succeeds.
  - Runner fails fast when import modal indicates missing mesh file.

## Evidence
- AKABAK driver log:
  - `runner_test_workspace/logs/b0bdcff9-ae45-4915-84ac-48862af5a058/akabak/akabak_driver.log.jsonl`
- UI observation dump:
  - `runner_test_workspace/logs/b0bdcff9-ae45-4915-84ac-48862af5a058/ui_discover/akabak_discover_tree_20260215_045444.json`
- `ui_discover` shows `TForm_Interpreter` with child modal `#32770` (`title`: `Error`) and `OK` button.

## Root Cause Classification
- Class: toolchain/data dependency, not visual/UI selector instability.
- The ABEC import references `ath.msh`, but that file is missing in the generated ATH output directory for this run.

## Status Of Previous Blocker
- Previous blocker (`ABEC open-file dialog did not close`) is resolved for micro-harness:
  - `runner-test open-dialog-only --repeats 5` succeeded on run_ids:
    - `b052b8fd-bdc7-410d-b860-dab479ae55ce`
    - `8780c294-1ccb-49ea-b1e2-65eb7ee294fb`
    - `875bcd90-2248-42d2-b5aa-9cb2c7685bc6`
    - `35afe2b6-ddf2-4b09-aadc-7a1645000058`
    - `accdf7e0-9960-406f-b9b7-bbf83fba9d57`

## Recommended Next Action
1. Ensure ATH stage produces/places referenced mesh file (`ath.msh`) in the ABEC-relative location before AKABAK import.
2. Re-run full E2E smoke immediately after mesh artifact issue is resolved.
