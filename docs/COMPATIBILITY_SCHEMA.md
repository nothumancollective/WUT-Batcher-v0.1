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
  - `type`: `source|hypothesis`
  - `refs`: `{source, section, quote_hint}` list
  - `confidence`: float
  - `notes`: explanation
- `verification_plan`: required for hypotheses

## Evidence Facts
`semantic_facts` includes:
- `length_is_mandatory` (doc-backed if available in bundle)
- `source_items_can_be_omitted` (hypothesis until explicit citation exists)
- `source_contours_override` (doc-backed)
- `ath_creates_subdirectory_per_script` (hypothesis)
- `output_flags_stl_abecproject` (hypothesis)

## Determinism Guarantees
- Rule normalization is idempotent.
- Rule evaluation has no arbitrary Python execution.
- Explicit `unset` parameter states map to `not defined`.

