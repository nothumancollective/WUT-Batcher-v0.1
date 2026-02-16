# LE Research Log

Date: 2026-02-16

## Local Primary Sources
- `C:\Users\maximilianheinze\Documents\Downloads\AKABAK.pdf`
  - p.283-284: LE/BEM coupling via `DrvGroup`.
  - p.432-433: Radiation Impedance and network inspection views in VACS.
  - p.480-481, p.493-494: Network inspection outputs (current/excursion/impedance).
  - p.537: LE script models include electrical driving-point impedance.
  - p.634: only first `Driving_Values` section is applied.
- `C:\Users\maximilianheinze\Desktop\Ath-4.8.2-UserGuide-2.pdf`
  - p.23: LE-related cfg fields (`LE`, `LE.System`, `LE.Driver`, `LE.Voltage`).
  - p.59: note about `Def_Driving` handling.

## Web Sources (Primary/Distribution Anchors)
- RD Team download/docs index:
  - https://www.randteam.de/Download/download.html
- AKABAK ReadTheDocs changelog pointer:
  - https://akabak.readthedocs.io/en/latest/changelog/
- AKABAK intro (official product context):
  - https://www.randteam.de/AKABAK3/akabak3_intro_2.html

## Practical Conclusions For This Pass
- RadImp alone is insufficient as sole LE-activation proof in this setup.
- A mutation sensitivity protocol is required to evidence LE impact robustly.
- Runner should keep production LE lock unchanged while harness runs perform controlled profile mutations.
