# UI Field Ordering And Numeric Guardrails (2026-02-17)

## Scope
This note covers two outcomes:
1. Reordering/clustering of fields inside existing cards (Project + Batch) without moving keys between cards.
2. Research-backed guidance for hard numeric input constraints in modern UIs.

## 1) Implemented Ordering Changes

### Shared ordering layer
- Added shared priority map in `ui/form_schema.py`:
  - `field_display_priority(key)`
  - applied to:
    - mode-page key ordering (`_mode_stacks`)
    - object-property ordering (`_property_specs`)

### Project Page (`ui/form_builder.py`)
- Display sorting now prefers `field_display_priority`, then catalog order.
- Mode stacks (`Throat Profile`, `GCurve`) now render common/page fields in the same priority order.
- Mesh core ordering updated so required/high-impact mesh controls appear earlier:
  - `Mesh.ThroatResolution`, `Mesh.MouthResolution` before segment/detail controls.

### Batch Page (`ui/batch_parameter_form.py`)
- Same priority sort as Project Page.
- Added subgroup clustering inside existing cards:
  - `Basics`: `Primary`, `Throat`, `Throat Extension`, `Slot`, `Orientation`
  - `Morph`: `Mode`, `Target`, `Shape`, `Transition`
  - `Mesh`: `Topology`, `Required`, `Segments`, `Interfaces`, `Advanced`
- Existing card boundaries remain unchanged.

## 2) Modern Numeric Input Patterns (Research)

For robust "only guideline-conform" numeric inputs, modern UIs combine:

1. **Hard client constraints at control level**
   - constrained numeric widgets (`min/max/decimals/step`) instead of free text where possible.
   - Qt references:
     - `QDoubleValidator` (`setRange`, `setDecimals`, `StandardNotation`)  
       https://doc.qt.io/qt-6/qdoublevalidator.html
     - `QDoubleSpinBox` (`setRange`, `setDecimals`, `setSingleStep`, suffix/prefix)  
       https://doc.qt.io/qt-6/qdoublespinbox.html

2. **Immediate, textual feedback**
   - errors described in text near field and/or summary; not color-only.
   - accessibility references:
     - WCAG Error Identification (3.3.1)  
       https://www.w3.org/WAI/WCAG21/Understanding/error-identification
     - WCAG Input Assistance (3.3)  
       https://www.w3.org/WAI/WCAG21/Understanding/input-assistance.html

3. **Stateful helper/error text behavior**
   - helper text turns into error text after interaction.
   - Material reference:
     - Material text field states / error text behavior  
       https://material-web.dev/components/text-field/

4. **Server/engine validation remains authoritative**
   - UI blocks obvious invalid input early.
   - rule engine still validates final payload (defense in depth).

## 3) Concrete Application To WUT Batcher

Recommended enforcement stack for numeric fields:

1. `ScalarFieldEditor` keeps per-key min/max/decimals from ATH schema as first gate.
2. For integer-only ATH keys, use strict integer editor/validator only.
3. Enforce unit-aware precision:
   - e.g. angular keys (`deg/2`) with dedicated decimal caps.
4. Keep contextual warnings (safe-range hints) as soft guidance on top.
5. Always keep textual issue messages for accessibility and debuggability.

This aligns with current architecture: compatibility/range engines stay separate from widget-level hard input constraints.

