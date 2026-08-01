# Legacy Runner Behavior Reference (Read-Only Evidence)

Date: 2026-02-15
Source Scope: `R:\Batch-Software Lokal Backup\Runner` (+ `R:\Batch-Software Lokal Backup\run_full_batch_v5.py`)
Purpose: semantic behavior extraction for contract-driven UIA hardening; no code reuse.

## Scope And Restrictions
- This document summarizes observed behavior only.
- Legacy implementation contains prohibited mechanisms (pixel/image, coord clicks, tab-count macros).
- Those mechanisms are not accepted for production runner logic and are listed only as evidence of what legacy tried.

## High-Level Semantic Sequence
1. ATH stage creates ABEC project output and queue metadata.
2. AKABAK stage starts, dismisses startup popup (`Example Files`), opens/imports ABEC project, triggers solve.
3. Solve completion is required before export handoff.
4. VACS stage receives data (`F7` handoff from AKABAK), discovers graph/child windows, exports TXT files.
5. Export validation checks file existence/content and fails run when outputs are missing/invalid.
6. Cleanup closes AKABAK/VACS and historically killed leftover processes on
   retries. That name-wide fallback is evidence only and is prohibited in the
   current runtime.

## AKABAK Semantic Flow (Observed)
1. Ensure AKABAK main window exists.
2. Handle startup modal:
- Dialog: `Example Files` (`TForm_ExampleFiles` in newer observations).
- Semantic action: dismiss popup before import flow.
3. Open/import ABEC project:
- Legacy trigger options observed: `Ctrl+O` and explicit import command path.
- Open-file dialog appears (`Open File` / `Oeffnen`, class often `#32770`).
- Path is entered into filename field and confirmed.
4. Import interpreter window appears:
- Title pattern: `Importing Scripts or ABEC Projects`.
- Required semantic controls:
  - `Open ABEC Project`
  - `Start Importing`
5. Solve:
- Triggered from AKABAK main shell (`F5` in legacy).
- Postcondition: solve finished signal before export handoff.

## VACS Semantic Flow (Observed)
1. Bring VACS main window to front (`VacsViewer`).
2. Handoff from AKABAK to VACS (`F7` in legacy flow).
3. Optional confirm modal may appear and must be handled deterministically.
4. Discover graph/plot child windows.
5. For each selected graph/export intent:
- Open export dialog (`Data Export` / `Daten Export`, often `TForm_Export`).
- Trigger save flow.
- Handle save/file dialog (`#32770` or `TForm_Edit` variants).
- Write TXT output and confirm overwrite dialogs if present.
6. Build deterministic mapping of exported files to graph semantics.

## Dialogs/Windows Seen In Legacy Evidence
- AKABAK main: `Akabak` / class `TForm_Main`.
- AKABAK startup modal: `Example Files` / class `TForm_ExampleFiles`.
- AKABAK open dialog: `Open File` / `Oeffnen` / class `#32770`.
- AKABAK interpreter: `Importing Scripts or ABEC Projects` / class `TForm_Interpreter`.
- Generic confirm: title patterns including `Confirm` / `Warning`.
- VACS main: `VacsViewer`.
- VACS export form: `TForm_Export`, title containing `Data Export`/`Daten Export`.
- VACS save dialogs: `#32770`, `TForm_Edit`.
- Context popup menus in some flows: `#32768`.

## Success Signals Extracted
- AKABAK open/import:
- Open-file dialog disappears after confirmation.
- Interpreter closes or transitions after start-import action.
- AKABAK solve:
- Legacy used visual status-bar matching (`ready`/`processing`) as solver completion signal.
- For hardened runner, equivalent must be non-visual (window/state/result signals).
- VACS export:
- Expected TXT files exist with non-trivial size.
- Content contains numeric rows and plausible headers/axes.

## Known Failure Situations In Legacy Material
- Open-file dialog not closing after path entry/confirm.
- Missing/late export dialog after VACS export trigger.
- Save dialog not appearing; legacy attempted tab-count search fallback.
- Overwrite/confirm dialogs blocking progress.
- Child plot windows not discovered within timeout.
- Export files missing, too small, or lacking numeric content.

## How Legacy Handled Failures (Evidence Only)
- Retries with global delays.
- Process kill fallback (`akabak.exe`, `vacsviewer_32.exe`) between attempts.
- Multiple fallback branches for export/save dialogs.
- Significant use of prohibited mechanisms:
- `pyautogui`, image template matching, coordinate clicks.
- fixed tab-count macros.

Current policy is stricter: only exact run-owned PIDs, validated with
executable path, parent relationship and start time, may be terminated.
Unknown/manual tool instances block the next test; they are never cleaned by
global image name.

## Implications For Current UIA Contracts
- AKABAK open/import must treat dialog-close + project-loaded as hard postconditions.
- Interpreter and open-file dialog must be first-class contract entities.
- VACS export requires deterministic modal handling and file-dialog control targeting.
- Any unknown modal must fail with actionable UI observation dump.
