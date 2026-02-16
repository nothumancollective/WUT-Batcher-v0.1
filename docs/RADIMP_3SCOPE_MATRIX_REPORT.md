# RadImp 3-Scope Matrix Report

Date: 2026-02-16

## Goal
Test RadImp behavior across three independent scopes in the harness:
1. CFG-level LE voltage profile (`cfg_le_profile`)
2. Observation RadImp profile (`radimp_observation_profile`)
3. Observation Driving profile (`driving_observation_profile`)

## Command A (2x2x2)
```powershell
python -m app runner-test radimp-3scope-matrix \
  --case test_cfg_baseline \
  --cfg-profiles "default,le_voltage_2p83" \
  --radimp-profiles "default,force_absolute" \
  --driving-profiles "default,accel_2p83" \
  --repeats-per-combo 1 \
  --keep-exports true \
  --test-profile fast \
  --le-repair-profile driver_drvgroup_def_driving_resistor \
  --ath-exe "C:\Tools\ATH\ath.exe" \
  --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" \
  --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

### Run IDs
- default/default/default: `f85e86fb-2a01-43e9-bf9a-030c9c61338b` (`succeeded`)
- default/default/accel_2p83: `cc13dcbf-3f8e-4dab-9275-f0acd48bebd9` (`succeeded`)
- default/force_absolute/default: `c9655c3f-d139-4ab1-a867-de381e86e3c7` (`failed`)
- default/force_absolute/accel_2p83: `856d30a7-589b-4bad-94dd-4db45bc76a8b` (`failed`)
- le_voltage_2p83/default/default: `7cbb5d72-0b66-4f59-b8f0-4edf81e87079` (`succeeded`)
- le_voltage_2p83/default/accel_2p83: `f5910812-dc58-4162-a626-ac70444fdf69` (`succeeded`)
- le_voltage_2p83/force_absolute/default: `00532955-bd4d-43c6-9945-274fc8b75a4d` (`failed`)
- le_voltage_2p83/force_absolute/accel_2p83: `eea7720c-b2ab-48d6-8548-1dfa0710ce80` (`failed`)

### Result Pattern
- All `force_absolute` combinations failed at VACS graph mapping:
  - `external vacs export could not map graph_kind='impedance' for spec 'radimp_main'`
- All `default` RadImp profile combinations succeeded.
- In successful runs, `radimp_diagnosis` remained:
  - `radimp export is normalized and zero-valued baseline (accepted)`

## Command B (add cfg_le_profile=le_voltage_10)
```powershell
python -m app runner-test radimp-3scope-matrix \
  --case test_cfg_baseline \
  --cfg-profiles "le_voltage_10" \
  --radimp-profiles "default" \
  --driving-profiles "default,accel_2p83" \
  --repeats-per-combo 1 \
  --keep-exports true \
  --test-profile fast \
  --le-repair-profile driver_drvgroup_def_driving_resistor \
  --ath-exe "C:\Tools\ATH\ath.exe" \
  --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" \
  --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

### Run IDs
- le_voltage_10/default/default: `84e0215c-bd4a-4c6e-b814-e5804c6ce6b2` (`succeeded`)
- le_voltage_10/default/accel_2p83: `5b8e391d-96de-40f0-bc17-8674fc96f11d` (`succeeded`)

### Validation Evidence
- `cfg_le_profile_applied` persisted expected cfg patch states:
  - `le_voltage_2p83` -> `detected_le_voltage_after=2.83`
  - `le_voltage_10` -> `detected_le_voltage_after=10.0`
- Despite cfg + driving variation, successful runs still produced normalized/all-zero RadImp baseline.

## Conclusion
- The harness can now execute and persist a three-scope diagnostic matrix.
- CFG LE voltage variation is active and verified in artifacts.
- Current blocker for non-zero RadImp is not solved by cfg voltage/driving variation alone in this setup.
- `force_absolute` observation path remains a separate mapping issue (VACS graph type availability/selection).
