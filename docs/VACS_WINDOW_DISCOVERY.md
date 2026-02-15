# VACS Window Discovery (Phase 1)

## Scope
Objective in this pass:
- identify reliable VACS child-window selection signals,
- classify context/modal windows,
- capture evidence for next export micro-harness iteration.

Non-visual constraints were kept:
- no pixel/OCR/screenshot-driven decisions,
- UIA/Win32 window/control signatures only.

## Test Rounds (max 3)

### Round 1
- State prep:
  - `runner_test_workspace/logs/interim_reimport/vacs_interim_reimport_20260215_214604.json` (`ok=true`)
- Observation:
  - Imported graph state reached (`controls_count` from `52` to `192`).
- Probe outcome:
  - first interactive probe path timed out (hang during deep interaction/export trigger path).
- Artifacts:
  - `runner_test_workspace/logs/vacs_probe/round1/ui_discover_after_probe/vacs_discover_20260215_215146.json`

### Round 2
- State prep:
  - `runner_test_workspace/logs/interim_reimport/vacs_interim_reimport_20260215_215451.json` (`ok=true`)
- Probe outcome:
  - second interactive probe path timed out again.
- Artifacts:
  - `runner_test_workspace/logs/vacs_probe/round2/ui_discover/vacs_discover_20260215_215545.json`

### Round 3 (stable discovery path)
- Stable snapshots collected without deep interactive traversal.
- Artifacts:
  - `runner_test_workspace/logs/vacs_probe/round3/ui_before/vacs_discover_tree_20260215_215831.json`
  - `runner_test_workspace/logs/vacs_probe/round3/ui_final/vacs_discover_tree_20260215_220355.json`
- Verified child windows present after import:
  - `TForm_DatContour` (3x: `Mic Polar - BE_Spectrum #2/#3/#4`)
  - `TForm_DatGraph` (1x: `Radiation Impedance - Radiation_Impedance #5`)
  - `TForm_Editor` (2x: `Editor - 1/-2`)

## Window Taxonomy (Observed)

### Main app container
- Main window:
  - `class_name=TForm_DatMain`
  - title example: `VacsViewer - (new)`
- Workspace container:
  - `class_name=MDIClient`
  - title example: `Arbeitsbereich`

### Child graph/editor windows (inside MDIClient)
- Graph (curve): `class_name=TForm_DatGraph`
- Graph (contour/polar): `class_name=TForm_DatContour`
- Editor: `class_name=TForm_Editor`
- Observed UIA automation ids in this session: `65280..65285` (session-specific, useful as secondary hint).

### Context/modal windows
- Confirm dialog (internal VACS):
  - `class_name=TForm_Confirm`
  - title: `Please confirm...`
  - child pane often contains `TRzDialogButtons`
- Save warning dialog:
  - `class_name=#32770`
  - title: `Warning`
  - text: `Save project?`
  - buttons:
    - `Yes` (`automation_id=CommandButton_6`)
    - `No` (`automation_id=CommandButton_7`)
    - `Cancel` (`automation_id=CommandButton_2`)

## Menus (Observed)
Top menu items on `TForm_DatMain`:
- `File`, `Edit`, `View`, `IO`, `Graph`, `Editor`, `Processing`, `Preferences`, `Window`, `Help`

Relevant export action:
- `IO -> Export data...` (menu id observed in win32 dump: `52`)

## What worked reliably
1. Detecting imported-state shift in VACS (`controls_count`/keyword growth) after AKABAK F7 handoff.
2. Enumerating child window classes and titles for graph-type discrimination.
3. Identifying modal classes and save-prompt controls with stable signatures.

## What remains unstable
1. Deep probe loops that combine child activation + immediate export-dialog interaction can hang in this VM/session.
2. For now, this is treated as an automation robustness issue in the probe path, not as a selector gap in the discovered signatures.

## Next hardening step (contract-first)
Build a dedicated `vacs-export-only` micro-harness with strict step contracts:
1. Precondition:
   - `TForm_DatMain` visible for target PID,
   - no blocking `TForm_Confirm` or `#32770` dialog.
2. Target selection:
   - enumerate `MDIClient` child windows,
   - choose by `class_name` + title regex + expected export spec mapping.
3. Action:
   - activate target child window,
   - invoke `IO -> Export data...` (menu-select with process-bound main window).
4. Postcondition:
   - export dialog signature found within timeout,
   - confirm controls available (`Save/Cancel` path),
   - exported file materializes in workspace.
5. Failure path:
   - dump UI tree snapshot and last active child signature,
   - classify as `modal_blocked`, `target_not_activated`, or `export_dialog_missing`.
