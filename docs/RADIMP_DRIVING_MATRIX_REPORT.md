# RadImp Driving Matrix Report

Date: 2026-02-16

## Goal
Evaluate whether `Driving_Values` changes in `observation.txt` (DrvType/Value) produce non-trivial RadImp exports for the stable baseline case.

## Command
`python -m app runner-test radimp-driving-matrix --case test_cfg_baseline --profiles "default,accel_2p83,accel_10,velocity_1,displacement_1" --repeats-per-profile 1 --keep-exports true --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --radimp-observation-profile default --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`

## Matrix Runs
1. `default` -> `8854f9dd-b0ac-4df2-9d8b-238ae3105d00`
2. `accel_2p83` -> `13114a8a-6ca6-4cca-9fd1-4cf57f2c12ba`
3. `accel_10` -> `a00eef05-0624-4f5e-8c53-ce0222639f25`
4. `velocity_1` -> `42920920-1b53-47ef-8f24-c8428deb5992`
5. `displacement_1` -> `781979c4-b2aa-466f-8512-6f201e91bfe6`

All five runs completed with `status=succeeded`.

## Evidence (Snapshot Verification)
Patched `observation.txt` values were applied as intended:
- `default`: `DrvType=Acceleration; Value=1.0`
- `accel_2p83`: `DrvType=Acceleration; Value=2.83`
- `accel_10`: `DrvType=Acceleration; Value=10.0`
- `velocity_1`: `DrvType=Velocity; Value=1.0`
- `displacement_1`: `DrvType=Displacement; Value=1.0`

`RadImpType` remained `Normalized` for all matrix profiles.

## Outcome
Across all driving profiles:
- VACS impedance export remained all-zero.
- `radimp_diagnosis` remained `ok` with normalized-zero baseline classification.

## Conclusion
For this baseline model and normalized RadImp observation setup, changing only `Driving_Values` (`DrvType`/`Value`) does not move RadImp away from the normalized zero baseline.

This narrows the remaining work to observation/model semantics beyond `Driving_Values` tuning (not runner UI automation robustness).
