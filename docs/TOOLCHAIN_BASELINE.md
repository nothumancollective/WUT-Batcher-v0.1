# Toolchain Baseline (test_cfg_baseline)

Date: 2026-02-16

## Command (current baseline)
`python -m app runner-test run --case test_cfg_baseline --repeats 3 --keep-exports false --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --radimp-observation-profile default --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`

## Latest Stable Batch
- `test_run_id`: `f09efdc4-60fc-4fcc-be4d-e1ee5b7e6b12` -> `succeeded`
- `test_run_id`: `c917fcf1-927c-4bb8-aca6-ff0cafa25de0` -> `succeeded`
- `test_run_id`: `67f9f99b-2961-42f6-8646-fca2f793ec6f` -> `succeeded`

## What Changed In This Pass
- Added LE repair profile support in harness/CLI:
  - `baseline`
  - `driver_drvgroup`
  - `driver_drvgroup_def_driving`
  - `driver_drvgroup_def_driving_resistor` (doc-aligned LE network topology patch)
- Added observation experiment profile support in harness/CLI:
  - `default`
  - `force_absolute`
  - `drop_radimptype`
- Added persistent ATH/AKABAK diagnostics snapshots:
  - `ath_input_snapshot` (`Project.abec`, `solving.txt`, `observation.txt`, effective LE script)
  - `abec_tree_snapshot` after AKABAK solve
- Improved process safety:
  - PID tracking now includes VACS PIDs already alive before export (spawned by AKABAK/F4)
  - preflight waits briefly for transient unmanaged tool processes to disappear instead of failing immediately

## Stage Outcomes (latest successful run)
- `preflight`: `ok`
- `resolve_case`: `ok`
- `generate_cfg`: `ok`
- `ath`: `ok`
- `post_ath_le_repair`: `ok`
- `pre_akabak_guard`: `ok`
- `akabak`: `ok`
- `vacs_export`: `ok`
- `ingest`: `ok`
- `safe_clean`: `ok`

## RadImp Status
- `export_quality:impedance`: `ok` with message `all-zero accepted for normalized radimp baseline`
- `radimp_diagnosis`: `ok` with classification `radimp_normalized_zero_baseline`
- No muted-sources watchdog events in successful runs.
