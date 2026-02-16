# LE Rules Extract (ATH + AKABAK)

Date: 2026-02-16

## Local Sources
- `C:\Users\maximilianheinze\Documents\Downloads\AKABAK.pdf`
- `C:\Users\maximilianheinze\Desktop\Ath-4.8.2-UserGuide-2.pdf`

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
- Experimental LE patch profiles are available for controlled A/B/C/D tests:
  - `baseline`
  - `driver_drvgroup`
  - `driver_drvgroup_def_driving`
  - `driver_drvgroup_def_driving_resistor`

## Observed Outcome In Real Runs
- LE patch variants changed script topology as intended.
- RadImp stayed zero in normalized mode and was reclassified as normalized baseline (not UI flow failure).
