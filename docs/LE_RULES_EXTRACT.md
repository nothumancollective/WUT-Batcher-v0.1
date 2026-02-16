# LE Rules Extract (ATH + AKABAK)

Date: 2026-02-16

## Local Sources
- `C:\Users\maximilianheinze\Documents\Downloads\AKABAK.pdf`
- `C:\Users\maximilianheinze\Desktop\Ath-4.8.2-UserGuide-2.pdf`

## Online Source Anchors (distribution/provenance)
- RD Team official download index (AKABAK/VACS docs + packages):  
  `https://www.randteam.de/Download/download.html`
- AKABAK ReadTheDocs changelog (contains official doc/package pointer context):  
  `https://akabak.readthedocs.io/en/latest/changelog/`

## Extracted Rules (with page anchors)
1. LE/BEM coupling uses `DrvGroup` on relevant components.
- AKABAK.pdf p.283-284: Transducer and RadImp connected to BEM should specify `DrvGroup`.

2. Example LE script topology for voltage driving includes `Def_Driving` and a resistor path.
- AKABAK.pdf p.741: Example shows `Def_Driving`, `Resistor 'Rg'`, `Driver ... DrvGroup=...`, `RadImp ... DrvGroup=...`.

3. Observation script syntax for RadImp normalized export.
- AKABAK.pdf p.739-740: `Radiation_Impedance ... RadImpType=Normalized ... <id> <grpA> <grpB> ID=...`.

4. ATH LE tags expected in cfg.
- Ath-4.8.2-UserGuide-2.pdf p.23: `LE.System`, `LE.Driver`, `LE.Voltage` semantics.

5. ATH note on `Def_Driving` insertion.
- Ath-4.8.2-UserGuide-2.pdf p.59: LE script should avoid explicit `Def_Driving`; ATH states insertion is automatic from `LE.Voltage`.

## Practical Reconciliation Used In Harness
- Post-ATH repair ensures:
  - LE script copied into ABEC project dir.
  - `[LEScript] Scriptname_LEScript` is non-empty and points to expected file.
- CFG renderer keeps production defaults fixed (`ABEC.AkabakMode=1`, `LE=generic25`, `LE.Voltage=1.0`);
  cfg-level LE experiments are therefore implemented as harness-only post-render patches.
- Experimental LE patch profiles are available for controlled A/B/C/D tests:
  - `baseline`
  - `driver_drvgroup`
  - `driver_drvgroup_def_driving`
  - `driver_drvgroup_def_driving_resistor`

## Observed Outcome In Real Runs
- LE patch variants changed script topology as intended.
- RadImp stayed zero in normalized mode and was reclassified as normalized baseline (not UI flow failure).
- Observation experiments:
  - `force_absolute` removed the Radiation Impedance graph from VACS in this setup (export mapping for `impedance` cannot resolve).
  - `drop_radimptype` retained Radiation Impedance graph but still produced normalized/all-zero output.
- Driving experiments (`DrvType/Value` matrix):
  - `Acceleration` (`1.0`, `2.83`, `10.0`), `Velocity=1.0`, `Displacement=1.0` all ran successfully.
  - RadImp remained normalized/all-zero across the full matrix.
- Strict non-zero gate (`--strict-nonzero-radimp`) produced no passing run in this pass:
  - classes observed: `radimp_normalized_zero_baseline`, `radimp_all_zero_unclassified`, `wrong_graph_exported`
  - observed `radimp_nonzero` count: `0`
