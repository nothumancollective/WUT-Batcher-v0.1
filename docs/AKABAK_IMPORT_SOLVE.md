# AKABAK Import -> Solve Contract (Non-Visual UIA)

## Scope
This note documents the hardened AKABAK subsection only:
1. open project
2. `Start Importing -> Apply`
3. close import/interpreter window so only AKABAK main window remains
4. trigger solve (`F4`)
5. detect completion via state/process signals
6. close AKABAK/VACS

No visual automation is used.

## Root-Cause Analysis of Waiting Behavior
- Wait after file name submit:
  - Expected wait for deterministic postcondition (`dialog closed` + `project loaded signal`).
  - Not an arbitrary sleep.
- Wait before file name input:
  - Open-dialog detection now uses fast handle/control-id checks (`GetDlgItem(1148)`), reducing pre-input idle scanning.
- Wait after `Apply`:
  - Settle timeout reduced to a short bounded window (~1.5-3.0s) before moving to close/confirm path.
- Wait after `Apply`:
  - Previously too long due missing report-text signal path.
  - Timeout was reduced to 12s for this check; close flow now continues deterministically.

## Implemented Contracts
- Import close contract:
  - After close action and confirmation handling, assert `main_only_open`.
  - Postcondition: exactly one visible AKABAK top-level window (main window), no interpreter window.
- Solve start contract:
  - `run_solve` no longer accepts a blind `running` state.
  - Required start signal:
    - progress window appears, or
    - AKABAK worker process appears, or
    - VACS process appears.
  - Trigger ladder:
    - Tier A: focused UIA `type_keys("{F4}")`
    - Tier B: handle-scoped `PostMessage(F4)` fallback
- Solve completion contract:
  - Completion requires:
    - no AKABAK progress/worker signal AND
    - VACS graph-import signal present (not just VACS process start).
  - Graph-import signal is based on VACS UI enrichment:
    - control-tree size growth / graph-keyword controls after solve start.
  - Timeout persists solve diagnostics with window/process snapshot.

## Real Run Evidence
- Artifact summary:
  - `runner_test_workspace/logs/manual_import_solve/import_solve_contract_summary_v4.json`
- Result:
  - `ok=true` (2/2 attempts succeeded)
  - Import close postcondition:
    - `ensure_main_only_after_import.status=main_only_open`
  - Solve start:
    - Tier A (`type_keys`) produced no start signal
    - Tier B (`hwnd_postmessage_f4`) produced `start_signal=vacs_process_started`
  - Solve completion:
    - `status=completed_vacs_graphs_imported`
    - `graphs_imported_signal=true`
    - observed VACS UI enrichment: `controls_count` rose to ~151, `graph_keyword_hits` to ~9
- Warning dialogs after `F4`:
  - none observed in this run (`watchdog_events=[]`)
  - unknown modal class would be persisted via solve diagnostics dump on failure.

## Files touched
- `app/akabak_driver.py`
