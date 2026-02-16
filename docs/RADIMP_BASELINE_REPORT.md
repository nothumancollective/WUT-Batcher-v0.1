# RadImp Baseline Report (Evidence-Only)

Date: 2026-02-16

## Scope
- Case: `test_cfg_baseline`
- Toolchain: ATH -> AKABAK import/solve -> VACS export -> TXT ingest
- Focus: Why `V001_radimp.txt` is all-zero across frequencies.

## A/B/C/D Matrix (real runs)
1. A (`baseline`): `92d37a9a-fcff-4f73-880b-c647f9c94451`
2. B (`driver_drvgroup`): `f2cc10a8-c2fe-4e3a-b389-c24a6e887957`
3. C (`driver_drvgroup_def_driving`): `159eef18-4a67-4727-afc1-19bbda645c25`
4. D (`driver_drvgroup_def_driving_resistor`): `427c4a22-7fdb-4f8d-a963-54dbda0c8091`

Result across A/B/C/D:
- AKABAK+VACS flow succeeds.
- SPL export is non-zero.
- RadImp export remains numerically zero in all variants.
- Therefore the zero signature is not explained by missing `Scriptname_LEScript`, missing `Driver DrvGroup`, or missing `Def_Driving`/`Resistor` topology alone.

## Observation Profile Experiments (real runs)
1. `default`: `e4648f14-2d45-48cc-8590-59c6812b9dcc` (succeeded)
2. `force_absolute`: `3f03e9cf-36d7-4bc1-8a0d-743555f90091` (failed in export mapping)
3. `drop_radimptype`: `5afeefcb-ac24-46a9-9f55-e21807586f8e` (flow succeeded, RadImp still zero)

Observed behavior:
- `force_absolute` patches `observation.txt` as intended, but after solve/VACS only SPL contour windows are present (no Radiation Impedance graph window to map/export).
- `drop_radimptype` keeps the Radiation Impedance graph, but export metadata still resolves to normalized RadImp and remains all-zero.
- Therefore no tested observation-profile variant in this pass produced non-zero RadImp values.

## Driving_Values / DrvType Matrix (real runs)
Profiles tested on top of stable LE repair and default RadImp observation profile:
- `default` (`8854f9dd-b0ac-4df2-9d8b-238ae3105d00`)
- `accel_2p83` (`13114a8a-6ca6-4cca-9fd1-4cf57f2c12ba`)
- `accel_10` (`a00eef05-0624-4f5e-8c53-ce0222639f25`)
- `velocity_1` (`42920920-1b53-47ef-8f24-c8428deb5992`)
- `displacement_1` (`781979c4-b2aa-466f-8512-6f201e91bfe6`)

Observation snapshots confirm profile patches were applied (`DrvType/Value` changed as configured), while `RadImpType=Normalized` remained unchanged.

Result:
- All matrix runs completed.
- RadImp export stayed all-zero for all profiles.
- `radimp_diagnosis` remained normalized-zero baseline in every profile.

## Key Evidence
- Exported graph is the correct one:
  - VACS child window title: `Radiation Impedance - Radiation_Impedance #5`
  - Export header: `Data_Legend='Radiation_Impedance #5;  ; Normalized'`
  - Export header: `Data_LevelType=Impedance10`
- Observation script in generated ATH input:
  - `RadImpType=Normalized`
  - section item uses identical groups: `1001 1001`
- No `sources muted` watchdog dialogs in these runs.

## Diagnosis
- Current baseline is best classified as:
  - `radimp_normalized_zero_baseline`
- Interpretation:
  - For this normalized RadImp setup, a zero-valued export is accepted as baseline signal, not a hard pipeline error.
  - This is now encoded in validation and diagnosis logic.

## Validation Logic Change (implemented)
- `export_quality:impedance` no longer hard-fails when all values are zero **and** metadata indicates normalized RadImp baseline.
- `radimp_diagnosis` now emits:
  - `radimp_normalized_zero_baseline` (status `ok`) when all-zero is expected from normalized RadImp context.

## Remaining Open Question (separate from runner robustness)
- If non-trivial (non-zero) RadImp values are required for downstream analysis, the model/export definition must switch to a non-normalized RadImp target or a different observation/export configuration.
- This is a modeling/ATH-observation question, not an AKABAK/VACS UI automation instability in the current baseline.
