# AKABAK Open Dialog Hardening

Date: 2026-02-15
Scope: runner-test/open-dialog-only + runner-test/import-start-apply-only + AKABAK driver import path

## Goal
Make AKABAK ABEC open-file dialog closure deterministic without visual automation.

## Contract-First Window Model
- Main window: `akabak_main_window` (`TForm_Main`-style shell).
- Interpreter window: `akabak_interpreter_window` (`TForm_Interpreter`).
- Open-file dialog: `akabak_open_file_dialog` (`#32770`) with required controls:
  - filename edit (`automation_id=1148`)
  - open button (`automation_id=1`)

Contract file: `ui_contracts/akabak/solve_flow.contract.json`

## Deterministic SetPath + Confirm Ladder
Order is fixed and logged in attempts.

1. Tier A (UIA)
- Set filename via UIA edit control (`set_edit_text` / value pattern path).
- Confirm via UIA invoke/click on Open button.

2. Tier B (Win32 handle)
- `SetDlgItemTextW` / `WM_SETTEXT` equivalent on filename field.
- Confirm via `WM_COMMAND(IDOK)` and `BM_CLICK` where handle is available.

3. Tier C (LAST_RESORT scoped keys)
- Allowed only after keyboard focus is verified on filename edit control.
- Send scoped `type_keys(path)` + Enter.
- No blind typing, no coordinate clicking.

## Postcondition (Hard Gate)
Submission is considered successful only if both are true:
- Open-file dialog is absent.
- Project-loaded signal is present (interpreter `Start Importing` visible or equivalent loaded signal).

If postcondition fails, step fails fast.

## Failure Diagnostics
When all tiers fail, driver writes diagnostics into run log directory:
- `open_dialog_failure_<timestamp>.json`
- `open_dialog_failure_<timestamp>.txt`

Diagnostic JSON contains:
- dialog signature (class/control_type/automation_id/native handle)
- filename edit readback text
- per-tier attempt list (`set_method`, `invoke_method`, result/error)
- control dump path

Diagnostic TXT contains shallow control rows for dialog descendants.

Harness persistence:
- Adds diagnostics as artifact (`akabak_open_dialog_diagnostics`) to `runner_test.sqlite`.
- Adds matching `ui_observations` entry with dump path.
- Validation `open_dialog_close` stores diagnostics path on failure.

## Import Start/Apply Path (Primary Mesh Import Flow)
- Primary interpreter action sequence is now:
  1. `Start Importing`
  2. wait for `Apply` readiness
  3. `Apply`
- `Open ABEC project` inside interpreter is no longer used as the import success path.
- Postcondition for successful import:
  - interpreter closed, or
  - `Start Importing` is disabled after Apply.
- Known modal handling:
  - Missing mesh modal (`Error` / `Cannot find Mesh-File ...`) is detected deterministically, logged, and fails fast.

Failure diagnostics for import flow:
- `import_failure_<timestamp>.json`
- `import_failure_<timestamp>_main_window.txt`
- `import_failure_<timestamp>_interpreter_window.txt`

Harness persistence:
- Artifacts stored as `akabak_failure_diagnostics`.
- Validation: `import_start_apply_postcondition`.

## Repro Command
```bash
python -m app runner-test open-dialog-only --akabak-exe "<AKABAK>" --abec-path "<ABEC>" --repeats 5
```

Optional dry run:
```bash
python -m app runner-test open-dialog-only --akabak-exe "<AKABAK>" --abec-path "<ABEC>" --repeats 1 --dry-run
```

Import-only micro-harness:
```bash
python -m app runner-test import-start-apply-only --akabak-exe "<AKABAK>" --abec-path "<ABEC>" --repeats 5
```

## Current Real-VM Observation (latest pass)
- The strict postcondition currently fails in real runs:
  - dialog (`#32770`, title `Open File`) remains open after submit attempts.
- Evidence:
  - `runner_test_workspace/logs/15aaccb8-6120-49ed-8b71-74b65c90a3dd/akabak/open_dialog_failure_20260215_172445.json`
  - `runner_test_workspace/logs/1f623ea8-6aa7-4950-a42f-bc8f8861454f/akabak/open_dialog_failure_20260215_172314.json`
- What is confirmed:
  - file path write/readback works (`C:\Horns\test\ABEC_FreeStanding\Project.abec`)
  - open dialog control tree is captured (includes `Edit automation_id=1148`, `Button automation_id=1`)
  - close signal is not observed (`dialog_closed=false`)

Current blocker class:
- `akabak_open_dialog_not_closing_after_setpath`
