# LE CFG Scope Research (ATH + AKABAK)

Date: 2026-02-16

## Objective
Check whether missing/incorrect cfg-level LE parameters could explain persistent RadImp zero outputs.

## Local Primary Sources
- `C:\Users\maximilianheinze\Desktop\Ath-4.8.2-UserGuide-2.pdf`
- `C:\Users\maximilianheinze\Documents\Downloads\AKABAK.pdf`

## Evidence Extract (keyword scan + page anchors)
1. ATH User Guide p.23
- Documents LE cfg knobs:
  - `LE` (script file)
  - `LE.System`
  - `LE.Driver`
  - `LE.Voltage`

2. ATH User Guide p.59
- States ATH handles LE driving insertion based on `LE.Voltage` in the generated workflow.
- Implication: editing LE script with ad-hoc custom driving syntax is high risk.

3. AKABAK.pdf p.739-740
- Documents `Radiation_Impedance` and `RadImpType` usage in observation definitions.
- Confirms normalized RadImp is an explicit mode.

4. AKABAK.pdf p.634
- Notes only first occurrences of sections like `Driving_Values` are applied.
- Explains why deterministic single-section patching is required.

5. AKABAK.pdf p.741
- Shows reference topology with `Def_Driving` + resistor path as a known pattern.

## Internet Research
- Additional web search did not yield higher-confidence primary material than the local AKABAK/ATH manuals for this specific LE+ABEC path.
- Decision: rely on local primary docs and reproducible harness evidence for this pass.

## Repo/Renderer Constraint Check
- `app/constants.py` + `app/cfg_renderer.py` enforce mandatory source block defaults for normal rendering:
  - `ABEC.AkabakMode = 1`
  - `LE = generic25`
  - `LE.Voltage = 1.0`
- Conclusion: cfg-level LE experiments must be harness-only post-render patches to avoid changing production semantics.

## Implemented Research Outcome
- Added harness-only `cfg_le_profile` with deterministic patching and DB evidence:
  - `default`
  - `le_voltage_2p83`
  - `le_voltage_10`
  - `le_voltage_0p1`
- Added combined matrix runner to test cfg + observation + driving scopes together.

## Current Factual Outcome
- CFG LE voltage changes are applied and verified in run artifacts.
- RadImp remains normalized/all-zero in successful default observation runs.
- `force_absolute` observation profile currently fails due VACS graph mapping (`impedance` graph not resolved), independent of cfg LE voltage.

## Next Verification Focus
- Keep cfg scope fixed to known-good (`default` or `le_voltage_2p83`) and isolate VACS graph mapping under non-normalized RadImp observation.
- Add contract-level evidence for graph identity before export (window signature + graph metadata alignment).
