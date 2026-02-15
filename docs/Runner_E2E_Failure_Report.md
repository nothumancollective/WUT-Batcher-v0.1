# Runner E2E Failure Report

Date: 2026-02-15

## Latest Full E2E Run Context
- Command:
  - `python -m app runner-test run --case smoke_fast --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`
- `test_run_id`: `9bdda5f1-904e-4d71-acee-77eb96107aa5`
- Result: `failed`

## Failing Step
- Stage: `pre_akabak_guard` (between ATH and AKABAK)
- Error summary:
  - `pre_akabak_guard_missing_mesh_artifact: ...\\ath\\ath.msh`
- Runner behavior:
  - Open-file dialog handling remains deterministic and stable.
  - Runner now fails earlier (before AKABAK start) when ABEC references missing mesh artifacts.

## Evidence
- Guard step details persisted in `runner_test.sqlite`:
  - validation: `pre_akabak_mesh_artifacts=failed`
  - step: `pre_akabak_guard=failed`
- ATH outputs for the run show ABEC references to `ath.msh`, but file absent in run output directory.

## Import Micro-Harness Evidence (AKABAK-only)
- Command:
  - `python -m app runner-test import-start-apply-only --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --abec-path "runner_test_workspace\\tmp\\real_abec\\ath\\Project.abec" --repeats 5 --workspace-root "runner_test_workspace"`
- Run IDs:
  - `4aa8f411-0769-4939-b4ac-b789452d275a`
  - `75c0323f-c1a8-44f5-b305-bf8114bcef76`
  - `7821d89f-f445-4da1-9c97-33ffa505b49a`
  - `63ec0d8e-3723-49a3-852e-f5b6b25fe4d3`
  - `6f0568ce-139b-4ac7-ad15-bb1b0d69eef7`
- Consistent result:
  - `open_project` succeeded in all runs.
  - `import_start_apply` failed deterministically with modal:
    - `Cannot find Mesh-File at ...\\ath\\ath.msh`
- Diagnostics persisted per run:
  - `runner_test_workspace/logs/<run_id>/akabak/import_failure_*.json`

## Root Cause Classification
- Class: toolchain/data dependency, not visual/UI selector instability.
- The ABEC import references `ath.msh`, but that file is missing in both:
  - full E2E ATH output for the run
  - micro-harness ABEC fixture path used for import-only testing

## Status Of Previous Blocker
- Previous blocker (`ABEC open-file dialog did not close`) is resolved for micro-harness:
  - `runner-test open-dialog-only --repeats 5` succeeded on run_ids:
    - `b052b8fd-bdc7-410d-b860-dab479ae55ce`
    - `8780c294-1ccb-49ea-b1e2-65eb7ee294fb`
    - `875bcd90-2248-42d2-b5aa-9cb2c7685bc6`
    - `35afe2b6-ddf2-4b09-aadc-7a1645000058`
    - `accdf7e0-9960-406f-b9b7-bbf83fba9d57`

## Recommended Next Action
1. Fix ATH/Gmsh mesh generation path so referenced `ath.msh` exists before AKABAK import.
2. Re-run `import-start-apply-only --repeats 5` and require 5/5 green.
3. Re-run full E2E smoke immediately after mesh artifact issue is resolved.
