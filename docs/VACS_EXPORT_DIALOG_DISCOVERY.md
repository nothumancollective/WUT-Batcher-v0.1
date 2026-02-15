# VACS Export Dialog Discovery (5 Rounds)

## Scope
Goal of this iteration:
- open `Data Export` deterministically from selected VACS child windows,
- log interaction options in `Data Export`,
- identify save control and common pitfalls for fallback handling.

Execution artifact root:
- `runner_test_workspace/logs/vacs_export_rounds/run_20260215_232004/`

## Round Result Summary
- rounds executed: 5
- successful rounds (`ok`): 5/5
- `Data Export` observed: 5/5
- save control detected by win32 signature: 5/5 (after deep dump analysis)

Primary summary file:
- `runner_test_workspace/logs/vacs_export_rounds/run_20260215_232004/summary.json`

## Deterministic Selection/Trigger Findings
Per round flow that worked:
1. prepare imported-graph state using interim handoff (`AKABAK -> F7 -> VACS`)
2. select target child window (`TForm_DatGraph` or `TForm_DatContour`)
3. trigger export with ladder:
   - child `{F7}`
   - main `{F7}`
   - main `WM_COMMAND` id `52` (`IO->Export data`)

Observed caveat:
- `menu_select("IO->Export data...")` was repeatedly disabled (`MenuItemNotEnabled`) even though export dialog still appeared via keyboard/command triggers.

## Data Export Window Signature
Observed stable dialog signature:
- title: `Data Export`
- class: `TForm_Export`
- control type: `Window`
- visible/enabled: `true/true` in all successful captures

## Data Export Controls (Important)
UIA exposes mostly custom panes (`TRz*`) instead of classic `Button` controls.
Key controls from deep dump:
- `TRzBitBtn` text `Save...` (win32 text `&Save...`)  -> **save action control**
- `TRzBitBtn` text `Copy`
- `TRzBitBtn` text `View...`
- `TRzBitBtn` text `Close`
- several `TRzCheckBox` options (e.g. `Single file`, `Export of graph view`, `Phase as radiant`, etc.)
- format `TRzComboBox` groups

Representative evidence (round 5 payload):
- `runner_test_workspace/logs/vacs_export_rounds/run_20260215_232004/r5_properties_probe.json`

## Save Button Identification
Confirmed save control (win32):
- class: `TRzBitBtn`
- text: `&Save...`
- example ctrl_id: `855506` (round-specific handle/id can vary)

Important implementation note:
- UIA `control_type=Button` filtering alone misses this control.
- Save detection must include custom class path (`TRzBitBtn`, pane-based controls).

## Pitfalls / Non-Export Windows
### 1) Graph Range dialog
Reproduced with both methods:
- menu: `Graph -> Range...`
- double-click on `TForm_DatGraph` child window (diagnostic check)

Observed signature:
- title: `Graph range`
- class: `TForm_CurvesRange`

### 2) Large view / maximize-like behavior
- `Window -> Maximize` was disabled in tested state.
- double-click on `TForm_DatContour` produced no extra modal/dialog window in this session.
- treat as possible in-place child-state change (not a separate top-level dialog).

### 3) Close behavior fragility
- after export probing, VACS close often timed out in graceful path.
- fallback force-kill (`taskkill`) was required in the diagnostic script.

## Robust Workflow Implications
For production-grade VACS export driver:
1. select child window by class/title contract (`TForm_DatGraph` / `TForm_DatContour`)
2. trigger export via key/command ladder (not menu-only)
3. require `Data Export` signature (`title + class`) as hard postcondition
4. find save via custom control contract (`TRzBitBtn` text `Save...`), not generic `Button`
5. detect and close pitfall dialogs (`TForm_CurvesRange`, `TForm_Confirm`, `#32770`) before retry

## Files Added/Updated in this iteration
- `scripts/vacs_export_dialog_rounds.py`
- this report: `docs/VACS_EXPORT_DIALOG_DISCOVERY.md`
