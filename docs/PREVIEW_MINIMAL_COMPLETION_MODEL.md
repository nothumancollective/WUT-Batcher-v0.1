# Preview Minimal Completion Model

## Goal
The preview pipeline must always render an STL as long as ATH can produce one, while keeping user input semantics clear.

To avoid overfilling hidden values and to keep run behavior explicit, preview completion is split into two tiers:

- `ath_minimal`
  - Only adds the smallest set required to keep STL preview generation robust.
  - May use ATH defaults implicitly.
  - Used only for preview rendering.
- `policy_minimal`
  - Computes which parameters are still undefined from a UI/policy perspective.
  - Produces default proposals for these keys (used by Run popup: `Show undefined` / `Use defaults`).
  - Does not silently mutate user configuration.

Implementation entry points:
- `app/services.py`
  - `_preview_seed_parameters(...)` -> `ath_minimal`
  - `_preview_policy_seed_parameters(...)` -> policy basis
  - `_missing_preview_policy_keys(...)` -> policy gaps
  - `_policy_defaults_for_missing_keys(...)` -> proposed default values

## Current Behavior (Verified)

### Base/Profile + Mesh
- `Length` remains the core fallback in `ath_minimal` when no profile-object path is present.
- `policy_minimal` always checks profile-specific requirements and mesh baseline requirements.
- Profile handling:
  - `OS-SE` (`Throat.Profile=1`) -> policy requires `Throat.Profile`, `Length`, `OS.k`, `Term.s`, `Term.n`, `Term.q`.
  - `Circular Arc` (`Throat.Profile=3`) -> policy requires `Throat.Profile`, `Length`, `CircArc.TermAngle`, `CircArc.Radius`.
  - `R-OSSE` -> policy requires full `R-OSSE` object key set (`R`, `r0`, `a0`, `a`, `k`, `r`, `m`, `b`, `q`).
- Mesh policy baseline currently includes:
  - `Mesh.ThroatResolution`
  - `Mesh.MouthResolution`
  - `Mesh.Quadrants`

### GCurve (Type-Aware)
- `ath_minimal`
  - `GCurve.Type=1` (Superellipse): auto-fills `GCurve.Dist`, `GCurve.Width` if missing.
  - `GCurve.Type=2` (Superformula): auto-fills `GCurve.Dist`, `GCurve.Width`, and `GCurve.SF.*`.
- `policy_minimal`
  - `Type=1`: requires `GCurve.Dist`, `GCurve.Width`, `GCurve.AspectRatio`, `GCurve.SE.n`.
  - `Type=2`: requires `GCurve.Dist`, `GCurve.Width`, `GCurve.AspectRatio`, `GCurve.SF.a/b/m1/m2/n1/n2/n3`.
  - `GCurve.Rot` stays optional.

### Morph
- `ath_minimal`
  - Does not force morph details for preview generation.
  - Allows preview with only target-shape selection.
- `policy_minimal`
  - If `Morph.TargetShape` in `{1,2}`, policy marks full morph set as undefined if missing:
    - `Morph.TargetWidth`
    - `Morph.TargetHeight`
    - `Morph.CornerRadius`
    - `Morph.FixedPart`
    - `Morph.Rate`
    - `Morph.AllowShrinkage`

### Enclosure
- `ath_minimal`
  - If `Mesh.Enclosure` is set and `Plan` is not set, preview seed injects `Depth` when missing.
  - Default used: `Mesh.Enclosure.Depth = 180`.
- `policy_minimal`
  - If `Mesh.Enclosure` is set and `Plan` is empty -> requires `Mesh.Enclosure.Depth`.
  - If `Mesh.Enclosure.Plan` is set -> requires `Mesh.Enclosure.Plan` only (no forced `Depth`).
  - Missing keys are exposed under policy block `enclosure`.

Implementation notes:
- `policy_missing_by_block` is returned in preview/default-policy payloads with blocks:
  - `profile`, `mesh`, `gcurve`, `morph`, `enclosure`.
- `Use defaults` merge logic in Batch form now supports:
  - `R-OSSE.*` and `R-OSSE` object
  - `Mesh.Enclosure.*` and `Mesh.Enclosure` object

## Morph Investigation Findings
Source:
- `reports/morph_circle_investigation/morph_circle_matrix.json`
- `reports/morph_circle_investigation/morph_circle_matrix.md`

Observed across 48 ATH-verified runs:
- `Morph.TargetShape=1` (rectangle morph) consistently changes geometry.
- `Morph.TargetShape=2` (circle morph) changes geometry primarily when the baseline outline is non-circular.
- For multiple scenarios, changing `Morph.TargetWidth/TargetHeight` under `TargetShape=2` had no measurable geometry delta.
- This supports:
  - keeping `ath_minimal` light for preview resilience,
  - keeping strict explicitness in `policy_minimal`.

## UI Contract
- Preview rendering always uses `ath_minimal` completion.
- Run action checks `policy_minimal` gaps:
  - `Show undefined` -> highlights unresolved fields in blue.
  - `Use defaults` -> applies proposed defaults and continues run.

This keeps preview robust while preserving user control for final run semantics.

## Enclosure Investigation Findings
Sources:
- `reports/enclosure_investigation/enclosure_dims_20260217T215223Z.json`
- `reports/enclosure_investigation/enclosure_dims_20260217T215223Z.md`
- ATH guide sections 6.12.1/6.12.2 (pre-defined vs. plan enclosure)

Observed in profile-wide preview runs (OS-SE / Circular Arc / R-OSSE):
- All tested enclosure variants produced valid STL.
- The exported STL bounding dimensions remained unchanged for enclosure toggles/variants in these runs.
- Operationally this means:
  - preview STL can stay stable even when enclosure fields change,
  - enclosure completion still needs to be explicit in policy to avoid hidden run assumptions.

Practical conclusion:
- keep enclosure handling in policy tier (explicitness),
- keep preview tier minimally permissive (robust rendering),
- document that current STL preview is not a reliable visual indicator for enclosure effect.

## Known Limits (Current)
- Compatibility ruleset itself is not changed by this model; this is orchestration/UI policy on top of resolver outputs.
- Current STL export behavior (in tested setup) does not visibly encode enclosure deltas in preview dimensions.
