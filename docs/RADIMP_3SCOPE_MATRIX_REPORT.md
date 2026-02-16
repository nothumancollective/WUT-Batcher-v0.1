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

## Repeats Validation (2026-02-16, post-mapping hardening)
### Command C (2x2x2, repeats-per-combo=2)
```powershell
python -m app runner-test radimp-3scope-matrix \
  --case test_cfg_baseline \
  --cfg-profiles "default,le_voltage_2p83" \
  --radimp-profiles "default,force_absolute" \
  --driving-profiles "default,accel_2p83" \
  --repeats-per-combo 2 \
  --keep-exports false \
  --test-profile fast \
  --le-repair-profile driver_drvgroup_def_driving_resistor \
  --ath-exe "C:\Tools\ATH\ath.exe" \
  --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" \
  --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

### Pattern
- All `radimp_observation_profile=default` combinations: stable success (2/2 each).
- All `radimp_observation_profile=force_absolute` combinations: stable deterministic failure (2/2 each), now with explicit evidence payload:
  - `available_graphs=[{title,data_level_type,data_legend,suggested_score}, ...]`
  - all discovered exports are `Data_LevelType=SoundPressure`, `suggested_score=0` for expected `impedance`.

Representative run IDs:
- default/default/default: `3c95f214-9b68-41d5-ab95-21daa2dcac4f`, `fc0c1822-c357-4532-9d09-33dca2d99b30`
- default/default/accel_2p83: `5f5a74e0-0310-41b5-9d24-96344f610035`, `999a1e3e-0cfd-46b7-99df-180a3e4a5ae0`
- default/force_absolute/default: `1ab7e3f3-1222-4029-b62f-7cf4c328823f`, `45b69aae-0543-4a96-85ab-10d0dff79a91`
- default/force_absolute/accel_2p83: `92a62b22-ea6f-496f-9899-7f0df200310f`, `60ac21f5-b6b6-4185-8bcb-947eeef1acb0`
- le_voltage_2p83/default/default: `62753b29-ecaf-4dcd-9dd3-f942543dc5bb`, `0fd05d92-d430-45da-8075-0461b61cc611`
- le_voltage_2p83/default/accel_2p83: `ad681acf-076b-4cae-a579-bb784d39f264`, `593392df-693e-4ded-9dd7-fd97346a87cd`
- le_voltage_2p83/force_absolute/default: `02587b45-26a6-43cb-995b-9f3f3e4ca980`, `6c596419-1626-4ee3-8294-71ffc395ed4b`
- le_voltage_2p83/force_absolute/accel_2p83: `1a4b0e5f-81e5-414a-b4ed-380f576aebe5`, `840fa8e8-eab1-4bfd-905a-e2f21d831d72`

### Command D (cfg profile extension, repeats-per-combo=2)
```powershell
python -m app runner-test radimp-3scope-matrix \
  --case test_cfg_baseline \
  --cfg-profiles "le_voltage_10" \
  --radimp-profiles "default,force_absolute" \
  --driving-profiles "default" \
  --repeats-per-combo 2 \
  --keep-exports false \
  --test-profile fast \
  --le-repair-profile driver_drvgroup_def_driving_resistor \
  --ath-exe "C:\Tools\ATH\ath.exe" \
  --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" \
  --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

### Pattern
- `le_voltage_10 + default`: stable success (2/2).
- `le_voltage_10 + force_absolute`: stable deterministic failure (2/2) with identical `SoundPressure`-only evidence.

Run IDs:
- le_voltage_10/default/default: `56cb7f3b-ae35-4c5a-aef4-f18c7fa62687`, `9c9ef072-47c8-4319-989a-284f29dc2292`
- le_voltage_10/force_absolute/default: `feb18fc9-703c-4cbf-a026-ac51834ef678`, `dbec610d-e2f7-44ac-ae01-e83f837913ad`
