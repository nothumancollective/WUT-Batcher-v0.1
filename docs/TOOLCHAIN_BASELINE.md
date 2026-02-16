# Toolchain Baseline (test_cfg_baseline)

Date: 2026-02-16

## Command (current baseline)
`python -m app runner-test run --case test_cfg_baseline --repeats 3 --keep-exports false --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`

## Latest Stable Batch
- `test_run_id`: `3515ef82-c38c-4d97-89f7-124a7b1febef` -> `succeeded`
- `test_run_id`: `577b29f0-4abe-4af6-82ca-fbf95805e8d5` -> `succeeded`
- `test_run_id`: `e2ebbcf8-9b88-4313-ab2a-5423516ba2f4` -> `succeeded`

## What Changed In This Pass
- Added LE repair profile support in harness/CLI:
  - `baseline`
  - `driver_drvgroup`
  - `driver_drvgroup_def_driving`
  - `driver_drvgroup_def_driving_resistor` (doc-aligned LE network topology patch)
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
