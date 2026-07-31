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
| `TryMatrixForm` | `UNCHECKED` for `TForm_DatContour`; `CHECKED` for `TForm_DatGraph` |
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
  - derive the `TryMatrixForm` expectation from the selected graph class; live
    evidence from 2026-07-31 showed `UNCHECKED` for all three polar
    `TForm_DatContour` windows and `CHECKED` for the Radiation Impedance
    `TForm_DatGraph` window
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
- Successful live probe timestamp: `2026-02-21T14:25:54.800919+00:00`
- Target process: `VACSVIEWER_32.exe` PID `11740`
- Dialog discovery: `TForm_Export` found as a child window under `TForm_DatMain` (not only as desktop top-level).

| Purpose | Selector (resolved in live probe) | Settable | Working method |
|---|---|---|---|
| `IncludeHeader` | `automation_id=1050536`, fallback `name='Export of parameters'` | `NO` | none |
| `AbscissaDataBlocks` | `automation_id=2033636`, fallback `name='Abscissa separat'` | `NO` | none |
| `TryMatrixForm` | fallback `name='Try matrix form'`, `checkbox_index=0` | `NO` | none |
| `SingleFile` | fallback `name='Single file'`, `checkbox_index=7` | `NO` | none |
| `ComplexFormat` | `automation_id=788396`, fallback `name='Phase as radiant'` | `NO` | none |

- In this environment, `BM_SETCHECK`, `BM_CLICK`, UIA TogglePattern, and UIA InvokePattern did not change these states.
- Enforcer behavior remains verify-only for these controls and fails fast if a required state is wrong.

## Failure Handling
- Error type: `ExportConfigurationError`
- Message format:
  - `Export configuration invalid: [ControlPurpose] expected [X], found [Y]. Please set this option to the expected state in VACS preferences or the export dialog.`
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

## External Export Script Exit Codes
- Script: `scripts/vacs_export_save_all.py`
- The script always prints a compact final summary to `stderr` before exit:
  - `exported_ok_count` / `exported_failed_count`
  - `verification_ok_count` / `verification_failed_count`
  - top failure reasons (up to 3) with affected files/targets
  - `summary_file` and `trace_file` paths when available
- Exit code policy:
  - `0`: minimum required exports succeeded and no hard failure condition is present
  - `1`: hard failure (for example startup failures like `vacs_main_missing`, or missing required exports)
- Optional strictness knobs:
  - `--min-successful-exports`
  - `--required-graph-title-regex`
