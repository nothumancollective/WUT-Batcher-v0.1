# Compatibility Schema

## Version
- Runtime schema: `ath-geometry-constraints.v1.1`.
- Input compatibility: `ath-geometry-constraints.v1` is migrated in-memory.

## Migration Rules
- `scope=validity` -> `kind=validity`, `applies_to=["version"]`
- `scope=visibility` -> `kind=visibility`, `applies_to=["project","batch"]`
- `scope=sweepability` -> `kind=sweepability`, `applies_to=["batch"]`
- `runner_restrictions` -> `kind=runner`, `applies_to=["project"]`

## Rule Object (v1.1)
- `id`: stable rule identifier
- `scope`: legacy scope field
- `kind`: semantic category
- `applies_to`: list of affected pipeline layers
- `when`: restricted DSL condition
- `then`: action list
- `severity`: `fatal|warn|info`
- `rationale`: human-readable explanation
- `evidence`: object
  - `type`: `ath_doc|hypothesis`
  - `refs`: `{doc, section, page, quote_hint}` list
  - `confidence`: float
  - `notes`: explanation
- `verification_plan`: required for hypotheses

## Evidence Facts
`semantic_facts` includes:
- `length_is_mandatory` (doc-backed if available in bundle)
- `source_items_can_be_omitted` (doc-backed from User Guide defaults/tutorial)
- `source_contours_override` (doc-backed)
- `ath_creates_subdirectory_per_script` (doc-backed from Program Output + Running sections)
- `output_flags_stl_abecproject` (doc-backed from Program Output/Tutorial sections)

## Determinism Guarantees
- Rule normalization is idempotent.
- Rule evaluation has no arbitrary Python execution.
- Explicit `unset` parameter states map to `not defined`.
- Verification harness persists run outcomes into `compat_verification_results`.
