# VACS Export Enforcement

## Scope
- Phase 2 adds a pre-export enforcement guard for VACS `TForm_Export`.
- No DB schema/importer behavior is changed in this phase.
- Enforcement is non-visual only (Win32/UIA/message-based).

## Required Controls

Current enforced specification (`app/vacs_export_enforcer.py`):

| Purpose | Expected |
|---|---|
| `IncludeHeader` | `CHECKED` |
| `AbscissaDataBlocks` | `UNCHECKED` |
| `TryMatrixForm` | `UNCHECKED` |
| `SingleFile` | `UNCHECKED` |
| `ComplexFormat` | `UNCHECKED` |

Selector priority per control:
1. `AutomationId` (if known)
2. Win32 `ctrl_id`
3. class/name regex
4. stable checkbox index fallback

## Enforcement Logic
- Entry points:
  - `app/vacs_driver.py` in `VacsDriver.export_txt(...)`
  - `scripts/vacs_export_save_all.py` in both `run_once_safe(...)` and `run_once_fast(...)`
- For each required control:
  - read current state (`BM_GETCHECK`, UIA toggle fallback)
  - if already expected: no action
  - if mismatched:
    - if probe marked control `settable=true`: apply methods idempotently (`BM_SETCHECK`, `BM_CLICK`, UIA invoke/toggle) and verify
    - if probe marked `settable=false`: fail-fast immediately
- No blind toggling is performed in production enforcement.

## Probe Tool
- Tool: `tools/vacs_export_setter_probe.py`
- Outputs:
  - `docs/vacs_export_setter_probe_report.md`
  - `docs/vacs_export_setter_probe_report.json`
- Method sequence per control:
  - `BM_SETCHECK`
  - `BM_CLICK`
  - `UIA InvokePattern`
  - `UIA TogglePattern`
- Each method attempt re-reads state and restores original state.
- If no method changes state, control is marked `NON-SETTABLE`.

## Current Probe Summary
- Run timestamp: `2026-02-21T14:06:56.163690+00:00`
- Dialog discovery result: `dialog_not_found` in this environment
- Note: `dialog_not_found` is expected when the VACS export dialog is not reachable; rerun the probe in a live VACS session with `TForm_Export` open.
- Trigger attempts executed:
  - `WM_COMMAND(52)` on main window
  - `F7` on main window
- Because no `TForm_Export` was reachable, all required controls were classified as `NON-SETTABLE` for this probe run.

## Failure Handling
- Error type: `ExportConfigurationError`
- Message format:
  - `Export configuration invalid: [ControlPurpose] expected [X], found [Y]. Please enable this option in VACS preferences or export dialog.`
- Additional failure guards:
  - export dialog missing
  - control missing/unreadable
  - control disappearing during enforcement
  - timeout-bounded dialog discovery

## Re-run Probe (after VACS/version changes)
1. Open VACS to a state where `TForm_Export` can be opened for a graph.
2. Run:
   - `python tools/vacs_export_setter_probe.py --dialog-timeout-s 5`
3. Review and commit updated:
   - `docs/vacs_export_setter_probe_report.md`
   - `docs/vacs_export_setter_probe_report.json`
4. Re-run tests:
   - `python -m pytest -q tests/test_vacs_export_enforcer.py tests/test_vacs_driver_export_enforcement.py`
