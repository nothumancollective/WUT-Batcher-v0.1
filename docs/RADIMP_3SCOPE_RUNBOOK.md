# RadImp 3-Scope Runbook

Date: 2026-02-16

## Single E2E with explicit diagnostics profiles

```powershell
python -m app runner-test run --case test_cfg_baseline --repeats 1 --keep-exports true --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --cfg-le-profile le_voltage_2p83 --radimp-observation-profile default --driving-observation-profile accel_2p83 --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

## Strict non-zero gate

```powershell
python -m app runner-test run --case test_cfg_baseline --repeats 1 --keep-exports true --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --cfg-le-profile default --radimp-observation-profile default --driving-observation-profile default --strict-nonzero-radimp --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

## Force-absolute stability check (expected deterministic failure with evidence)

```powershell
python -m app runner-test run --case test_cfg_baseline --repeats 3 --keep-exports true --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --radimp-observation-profile force_absolute --driving-observation-profile default --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

## Full 3-scope matrix with repeats

```powershell
python -m app runner-test radimp-3scope-matrix --case test_cfg_baseline --cfg-profiles "default,le_voltage_2p83,le_voltage_10" --radimp-profiles "default,force_absolute" --driving-profiles "default,accel_2p83" --repeats-per-combo 2 --keep-exports false --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

## Randomized matrix order (bias guard)

```powershell
python -m app runner-test radimp-3scope-matrix --case test_cfg_baseline --cfg-profiles "default,le_voltage_2p83,le_voltage_10" --radimp-profiles "default,drop_radimptype" --driving-profiles "default,accel_2p83,velocity_1" --repeats-per-combo 1 --keep-exports false --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --strict-nonzero-radimp --matrix-seed 20260216 --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

## Bias safeguards checklist
- Randomized combination order with fixed seed (`--matrix-seed`) for reproducibility.
- Strict non-zero gate separates “pipeline works” from “target signal achieved”.
- Manual UI interaction during run must be marked as interrupted/aborted (do not aggregate with matrix evidence).
- Keep SPL export in every run as positive control (non-trivial result path).

## Expected status pattern (current VM)

- `radimp_observation_profile=default`: stable success.
- `radimp_observation_profile=force_absolute`: stable deterministic failure with `available_graphs` evidence showing `Data_LevelType=SoundPressure` only.
