# PROJECT UI (Form-Based Constraints)

## Scope
- Replaces raw JSON textareas on the PROJECT page with a metadata-driven PySide6 form UI.
- Sources of truth:
  - `app/knowledge/ath/catalog.v1.json`
  - `app/knowledge/ath/ruleset.v1.json`
  - `app/compat_engine.py` / `app.compatibility_service.CompatibilityService`

## Implementation
- Schema: `ui/form_schema.py`
  - Builds `FieldSpec` definitions from ATH catalog metadata.
  - Derives visibility-mode relations from ruleset visibility rules.
  - Extends `Throat.Profile` UI options to `OS-SE / R-OSSE / Circular Arc`.
- Builder: `ui/form_builder.py`
  - Maps field types to Qt widgets:
    - `float/int -> NullableNumericInput` (empty allowed, locale `,` normalized to `.`)
    - `enum -> segmented buttons (<=4) or combo`
    - `bool -> tri-state optional checkbox` (`unset/true/false`)
    - `ex -> nullable line edit` (short example placeholder + tooltip semantics)
    - `list -> nullable line edit` (`e.g. 1,2,3`)
    - `object -> nested property subform` (segmented toggle for `Mesh.Enclosure`)
  - Uses two side-by-side columns (`Geometry | Mesh`) with dedicated scroll areas.
  - Geometry order: `Basics -> Throat Profile -> Morph -> GCurve -> Rollback`.
  - Mesh order: `Core -> Enclosure`.
  - Supports unset semantics without per-field `Set` toggles and serializes to `param_states`.
- Integration: `app/gui.py`
  - PROJECT page now emits draft payload from form (`fixed_params`, `limits`, `param_states`).
  - Compatibility actions drive progressive disclosure (show/hide).
  - Project creation is not blocked by draft compatibility issues.

## Storage
- `ProjectConstraints` now persists `param_states` (`app/models.py`).
- `create_project` and compatibility preview flow preserve and evaluate `param_states`.

## Notes
- PROJECT page no longer renders a dedicated compatibility panel and no longer includes `Back to Dashboard` / `Show details` actions.
- Source fields (`Source.*`) and `OSSE` object block are intentionally hidden from PROJECT UI to avoid duplication/conflicts.
- `Throat.Profile = 2 (R-OSSE)` is treated as UI mode selector; it is kept in `param_states` for UI/rules evaluation and omitted from rendered fixed CFG key map.
- TODO verification hook:
  - Confirm final production mapping strategy for R-OSSE mode against ATH export behavior (UI mode value vs. pure object-block mapping).
