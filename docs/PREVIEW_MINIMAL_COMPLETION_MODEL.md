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

## Known Limits (Current)
- Enclosure-specific tier rules are not yet modeled in this document version.
- Compatibility ruleset itself is not changed by this model; this is orchestration/UI policy on top of resolver outputs.

