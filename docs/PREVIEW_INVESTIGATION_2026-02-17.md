# Preview Investigation (2026-02-17)

## Context
Requested checks for this batch-style configuration:

```cfg
Throat.Profile = 1
Throat.Diameter = 25.4
Throat.Angle = 7
Coverage.Angle = 45
Length = 100
Term.s = 0.5
Term.n = 4.0
Term.q = 0.996
Morph.TargetShape = 0
Mesh.AngularSegments = 64
Mesh.LengthSegments = 20
Mesh.ThroatResolution = 4.0
Mesh.InterfaceResolution = 8.0
Mesh.InterfaceOffset = 5.0
```

and for the same baseline with `Morph.TargetShape = 1` (rectangle mode).

## Reproduction Summary
- Service-level preview generation with the above config reproduces a compatibility issue for one key:
  - `batch_param_not_visible` on `Mesh.InterfaceOffset`
- Despite this issue, STL generation can still succeed when preview fallback logic is active.
- The key reason for intermittent preview failures was robustness gaps around hidden/incompatible keys in fallback parameter assembly.

## Key Findings
1. `Mesh.InterfaceOffset` visibility mismatch:
- Current local ruleset hides/shows `Mesh.InterfaceOffset` based on `Mesh.Enclosure`.
- ATH parameter docs describe `Mesh.InterfaceOffset` in relation to `Mesh.SubdomainSlices` (same list length), not enclosure-only semantics.
- This mismatch is the direct source of `batch_param_not_visible` in the tested configuration.

2. Preview should remain productive under UI/compatibility transients:
- Preview is best-effort visualization and should avoid failing hard due stale/hidden keys.
- Ignoring `batch_param_not_visible` keys in preview fallback input is a safe robustness measure.

3. Local ATH references:
- `C:\Tools\ATH\Tritonia.cfg` confirms common OS-SE + morph usage patterns and STL flag usage.
- Local smoke template in repo (`runner_test_cases/templates/smoke_fast_min.cfg`) aligns with the baseline OS-SE/Coverage/Term setup and successfully renders.

## Implemented Changes
- Preview fallback now extracts `batch_param_not_visible` keys from resolver issues and drops them from preview generation input.
- Result payload now exposes `ignored_hidden_keys` for debugging.
- Preview runtime now writes `MeshCmd` via a gmsh wrapper command when gmsh.exe is detected.
  - This avoids ATH runs hanging on direct gmsh invocation without arguments.
- CFG renderer now serializes list values in ATH-native CSV form inside object blocks.
  - Example: `Spacing = 30, 30, 30, 200` (instead of JSON array notation).

## Evidence Sources
- Local:
  - `C:\Tools\ATH\Tritonia.cfg`
  - `runner_test_cases/templates/smoke_fast_min.cfg`
  - `app/knowledge/ath/ruleset.v1.json`
  - `app/knowledge/ath/catalog.v1.json`
- Web:
  - ATH docs overview: https://www.ath-horns.eu/en/ath-4-8-user-guide/
  - ATH doc mirror (manual index): https://sphericalhorns.net/2020/12/17/ath4-manual/
  - ATH doc mirror (termination): https://sphericalhorns.net/2020/12/17/ath4-docu-termination/
  - Local ruleset mirror for visibility rules context: https://raw.githubusercontent.com/si-traxx/WUT-Batcher/main/app/knowledge/ath/ruleset.v1.json

## Rule Alignment Applied
- `app/knowledge/ath/ruleset.v1.json` was updated so `Mesh.InterfaceOffset` is no longer force-hidden behind `Mesh.Enclosure`.
- Result:
  - the provided guide-style configuration no longer produces `batch_param_not_visible` for `Mesh.InterfaceOffset`
  - `evaluate_batch_definition(...)` reports `version_count_preview = 1` for both `Morph.TargetShape = 0` and `Morph.TargetShape = 1` in the tested case
  - preview generation succeeds for both variants
