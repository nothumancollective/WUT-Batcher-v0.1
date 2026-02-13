# UI Automation Contracts

## Policy
- Automation uses Windows UI Automation selectors only.
- Primary backend: `pywinauto` with `backend="uia"`.
- Optional fallback: `uiautomation` module when specific controls are inaccessible.
- Pixel/template/image matching is forbidden.
- Screenshots are allowed only as debug artifacts for unknown modal dialogs.

## Discovery Commands
- `python -m app ui inspect-akabak`
- `python -m app ui inspect-vacs`

Inspector outputs are written to `ui_maps/`:
- `<tool>_inspect_<timestamp>.json` summary
- `<tool>_uia_tree_<timestamp>.txt` (`PrintControlIdentifiers` output when available)
- `<tool>_uia_tree_<timestamp>.json` structured tree snapshot

Use `--dry-run` to validate command wiring without launching tools.

## Contracts
- Window signatures live in `app/ui_contracts/window_signatures.py`.
- Signatures must combine process/class/control selectors; title regex alone is not allowed.
- Export recipes live in `ui_recipes/vacs/*.json`.
- Recipes are versioned and validated by `app/ui_automation/recipes.py`.

## Driver State Machines
- `app/akabak_driver.py`:
  - `open_project()`
  - `import_if_needed()`
  - `run_solve()`
  - `wait_for_completion()`
  - `close()`
- `app/vacs_driver.py`:
  - `open_results()`
  - `open_graph()`
  - `export_txt()`
  - `close()`

Each method enforces:
- preconditions
- deterministic action sequence
- postcondition checks
- structured JSONL step logs

## Watchdog / Recovery
- `app/ui_automation/watchdog.py` monitors modal dialogs.
- Whitelisted dialogs are auto-handled via rule actions.
- Unknown dialogs trigger:
  - signature debug dump
  - optional screenshot
  - safe abort

## Updating After Tool Upgrades
1. Run inspector commands for AKABAK and VACS.
2. Compare new `ui_maps/*` outputs against existing signatures.
3. Update `window_signatures.py` selectors if automation IDs/classes changed.
4. Update or version-bump affected recipe JSON in `ui_recipes/vacs/`.
5. Run contract tests:
   - `python -m unittest tests.test_ui_automation_contracts -v`
6. If tools are installed, run optional integration tests:
   - `WUT_UIA_INTEGRATION=1 WUT_AKABAK_EXE=... WUT_VACS_EXE=... python -m unittest tests.test_ui_automation_integration_optional -v`
