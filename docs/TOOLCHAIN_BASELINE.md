# Toolchain Baseline (test_cfg_baseline)

Date: 2026-02-16

## Command (current baseline)
`python -m app runner-test run --case test_cfg_baseline --repeats 3 --keep-exports false --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --radimp-observation-profile default --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`

## Command (strict non-zero gate)
`python -m app runner-test run --case test_cfg_baseline --repeats 1 --keep-exports true --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --cfg-le-profile default --radimp-observation-profile default --driving-observation-profile default --strict-nonzero-radimp --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`

## Latest Stable Batch
- `test_run_id`: `f09efdc4-60fc-4fcc-be4d-e1ee5b7e6b12` -> `succeeded`
- `test_run_id`: `c917fcf1-927c-4bb8-aca6-ff0cafa25de0` -> `succeeded`
- `test_run_id`: `67f9f99b-2961-42f6-8646-fca2f793ec6f` -> `succeeded`

## Latest Stable Batch (10/10, 2026-02-16)
- `5fa745e8-8885-4ec2-a421-68b6966081de`
- `8b04fab7-5161-4388-8c34-b1e6c7b69809`
- `3756bd6d-7669-4cdd-aa93-b27ae0b518c5`
- `a2f9667d-d852-432e-9a43-c1afeb5d5f31`
- `5c07e3de-3e20-4d4c-bb27-4b75518bce29`
- `0a96afd2-bcd2-4e65-a45e-2ea4b9690acf`
- `783ffd0d-2df6-4332-bd97-3877b2ad0b68`
- `5a915552-d2c4-4b1b-be95-6c6e5ea1ccfa`
- `f2304c75-44c0-43db-ae61-5e16df7c50f3`
- `8be59014-353d-4ca6-926f-aca7f17f136b`

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
- Strict non-zero gate result (latest): `failed` on `test_run_id=4747aaa6-f41a-4566-9912-74edd5391535`
  - `strict_nonzero_radimp`: `failed`
  - `radimp_diagnosis.classification`: `radimp_normalized_zero_baseline`

## Driving Matrix
- Matrix command available:
  - `python -m app runner-test radimp-driving-matrix --case test_cfg_baseline ...`
- Latest matrix batch (5 profiles) completed:
  - `default`: `8854f9dd-b0ac-4df2-9d8b-238ae3105d00`
  - `accel_2p83`: `13114a8a-6ca6-4cca-9fd1-4cf57f2c12ba`
  - `accel_10`: `a00eef05-0624-4f5e-8c53-ce0222639f25`
  - `velocity_1`: `42920920-1b53-47ef-8f24-c8428deb5992`
  - `displacement_1`: `781979c4-b2aa-466f-8512-6f201e91bfe6`
