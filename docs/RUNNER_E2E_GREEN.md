# Runner E2E Green Status

Date: 2026-02-16

## Scope
- Non-visual UIA-only ATH -> AKABAK -> VACS harness flow
- Case: `test_cfg_baseline`
- Profile: `fast`
- LE repair: `driver_drvgroup_def_driving_resistor`

## Repro Command (stable path)
```powershell
python -m app runner-test run --case test_cfg_baseline --repeats 10 --keep-exports false --test-profile fast --le-repair-profile driver_drvgroup_def_driving_resistor --cfg-le-profile default --radimp-observation-profile default --driving-observation-profile default --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

## Latest 10/10 Success Run IDs
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

## Known Caveat
- Baseline green does not imply non-zero RadImp.
- In this environment the stable baseline still yields normalized/all-zero RadImp classification unless strict gate is enabled.
