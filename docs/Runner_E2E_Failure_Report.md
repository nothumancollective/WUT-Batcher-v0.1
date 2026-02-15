# Runner E2E Failure Report

Date: 2026-02-15

## Run Context
- Command:
  - `python -m app runner-test run --case smoke_fast --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`
- `test_run_id`: `6bcfdb6e-916d-4762-8791-725c1d81c887`
- Result: `failed`

## Failing Step
- Step: `akabak` (fails in `open_project`)
- Error summary:
  - `Failed to open project in AKABAK: RuntimeError('ABEC open-file dialog did not close after non-visual confirmation attempts.')`
- Stage telemetry from `akabak_driver.log.jsonl` confirms deterministic flow up to the blocking point:
  - startup modal `TForm_ExampleFiles` closed
  - import command `WM_COMMAND 113` sent
  - interpreter button `Open ABEC Project` triggered
  - filename path written into open dialog (`SetDlgItemTextW` readback correct)
  - then timeout waiting for open dialog close

## UI Observations (last 2-3)
- Observation 1:
  - `test_run_id`: `6bcfdb6e-916d-4762-8791-725c1d81c887`
  - `window_signature_json`: `{"pid":11568,"window_count":1,"windows":[{"class_name":"TForm_Main","control_type":"Window","title":"Akabak-Demo - (new)","handle":3212132}]}`
  - `control_dump_path`: `runner_test_workspace/logs/6bcfdb6e-916d-4762-8791-725c1d81c887/ui_discover/akabak_discover_tree_20260215_034947.json`
  - `notes`: `akabak_stage_exception`
- Observation 2:
  - `test_run_id`: `5f28a0e7-8727-447c-b886-bc52a3c47a8b`
  - `window_signature_json`: `{"pid":5480,"window_count":1,"windows":[{"class_name":"TForm_Main","control_type":"Window","title":"Akabak-Demo - (new)","handle":3409246}]}`
  - `control_dump_path`: `runner_test_workspace/logs/5f28a0e7-8727-447c-b886-bc52a3c47a8b/ui_discover/akabak_discover_tree_20260215_025505.json`
  - `notes`: `akabak_stage_exception`

## Control Dump Evidence
- In `runner_test_workspace/logs/6bcfdb6e-916d-4762-8791-725c1d81c887/ui_discover/akabak_discover_tree_20260215_034947.json`:
  - `#32770` open dialog is present (`title`: `Öffnen`)
  - `TForm_Interpreter` is present
  - `Open ABEC Project` control exists in interpreter tree
- This matches the failure mode: open dialog remains active and blocks progress.

## Process Safety Observation
- This run tracks the AKABAK PID as harness-owned and executes cleanup in `safe_clean`.
- `test_run_steps.safe_clean.details_json.process_cleanup` records that the PID was alive during cleanup and was targeted for teardown.

## Modal Dialog Assessment
- Detected and handled:
  - `TForm_ExampleFiles` startup window (closed via handle-based `WM_CLOSE`)
- Detected but not fully handled:
  - ABEC open-file dialog (`#32770` / `Öffnen`) did not close via non-visual confirmation attempts (`InvokePattern`/keyboard/`WM_COMMAND` path)
- Unknown modal dialogs:
  - none in this run

## Recommended Contract Changes
1. Extend AKABAK contract with explicit interpreter subflow:
   - `akabak_interpreter_window` (`TForm_Interpreter`)
   - required controls: `Open ABEC Project`, `Start Importing`
2. Treat `akabak_open_file_dialog` as hard gate:
   - if still present after submit attempts -> fail immediately with dump path and dialog metadata
3. Add explicit dialog-action strategy in contract metadata:
   - allowed actions order (invoke, keyboard activation, message-based command)
   - expected close signal (`dialog disappeared within timeout`)

## Current Status
- ATH stage is fixed and stable.
- AKABAK now reaches the correct interpreter/open-dialog state deterministically.
- Remaining blocker is a non-visual confirmation path for the ABEC open-file dialog on this VM/build.
