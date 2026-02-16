# Wizard/Batch Field Hints + Empty Severity Design (2026-02-10)

Status: analysis/design only, no code changes in this step.

## Scope

Requested:
1. Better gray placeholder texts in empty fields (correct technical meaning, plus useful start recommendations).
2. Visual highlight for empty fields that would later trigger:
- warning -> yellow outline/text accent
- fatal -> red outline/text accent

The highlight should be subtle (modern), not full background fill.

## Source Basis

Primary source in repo:
- `app/knowledge/ath/catalog.v1.json` (contains normalized ATH guide info with section/page refs)
- `app/knowledge/ath/ruleset.v1.json` (normative validity rules used by app)

Referenced ATH guide sections via catalog/ruleset metadata:
- ATH 4.8.2 User Guide 2.1.2, 4.1.1, 4.1.2, 4.1.3, 4.1.4

Related local analysis:
- `docs/Wizard_Batch_Optionality_Analysis.md`

## Findings (Parameter semantics relevant for placeholders)

Important examples from catalog:
- `Coverage.Angle`: explicit coverage half-angle; guide example `40 + 10*cos(p)^2`.
- `Throat.Angle`: throat opening half-angle (not full angle), default `0`.
- `Length`: in expliziter Parametrik mandatory; bei OSSE/R-OSSE Blockdefinition kann die Laenge aus dem Block kommen.
- `GCurve.Dist`: `<0,1` interpreted as fraction of horn length, `>1` as mm.
- `GCurve.Width`: absolute width in mm.
- `Rollback.Angle`: angle relative to axis, `180` means half circle.
- `Morph.TargetWidth`/`Morph.TargetHeight`: `0` means keep raw size.

## Proposed Placeholder/Text Strategy

### A) Non-dropdown numeric/expr fields

Use short gray placeholder with this pattern:
- semantic hint first
- optional guide/default starter after semicolon

Example pattern:
- `"<meaning>; z. B. <starter>"`

Proposed key hints (first implementation set):
- `Throat.Angle`: `Halbwinkel [deg]; Start: 0`
- `Coverage.Angle`: `Halbwinkel [deg]; z. B. 40 + 10*cos(p)^2`
- `Length`: `Axiale Laenge [mm]; z. B. 80`
- `GCurve.Dist`: `Abstand Guiding Curve (<1=Anteil, >1=mm); z. B. 0.6`
- `GCurve.Width`: `Absolute Breite [mm]; z. B. 200`
- `Rollback.Angle`: `Winkel zur Achse [deg]; Start: 180`
- `Morph.TargetWidth`: `Zielbreite [mm]; 0 = roh`
- `Morph.TargetHeight`: `Zielhoehe [mm]; 0 = roh`

Notes:
- For keys with catalog `default`, show `Start: <default>`.
- For keys without default, use guide example if present; otherwise only semantic hint.
- Keep placeholders compact; longer explanation goes into tooltip/WhatsThis.

### B) Dropdown fields

Dropdowns have no placeholder in Qt, so use:
- existing short labels (already implemented)
- add tooltip on combo itself for semantics where needed

Examples:
- `Throat.Profile`: "1 = OS-SE (Term.*), 3 = Circular arc (CircArc.*)"
- `GCurve.Type`: "Not set = explicit coverage mode"
- `Morph.TargetShape`: "0 No morph, 1 Rectangle, 2 Circle"

### C) Batch sweep fields (base/start/target)

For sweep table inputs:
- base/start/target stay empty by default
- placeholder should mirror same key hint as wizard, optionally with mode:
  - base: `Basiswert; <key hint>`
  - start: `Sweep Start; <key hint>`
  - target: `Sweep Ziel; <key hint>`

## Empty-Field Severity Highlight (Warn/Fatal)

### Rule-derived empty severities in current ruleset

Fatal when empty:
- `Length` (wenn weder `OSSE` noch `R-OSSE` gesetzt ist)
- `GCurve.Dist` and `GCurve.Width` if `GCurve.Type` is set

Warn when empty:
- `Coverage.Angle` if `GCurve.Type` is not set

### UI behavior proposal

Field visual state (empty only):
- neutral: default border
- warn-empty: thin yellow border (`#F2C94C`) + subtle yellow helper text
- fatal-empty: thin red border (`#FF5C5C`) + subtle red helper text

No full fill color, only outline + helper line below.

Recommended helper texts:
- warn: `Empfohlen: Wert setzen, sonst spaeter Warnung.`
- fatal: `Pflichtfeld im aktuellen Modus: bitte ausfuellen.`

### Evaluation logic proposal

Project Wizard:
- On every change, build temporary `fixed_params` draft.
- Evaluate empty-state severities context-aware:
  - `Length` empty -> fatal (nur ohne OSSE/R-OSSE)
  - `GCurve.Type` set and (`GCurve.Dist` or `GCurve.Width` empty) -> fatal
  - `GCurve.Type` not set and `Coverage.Angle` empty -> warn

Batch Builder:
- Evaluate against effective baseline:
  - constraints fixed values + current batch row values
- If a key is empty in batch but already fixed in constraints, no empty warning/fatal highlight in batch row.
- Apply same fatal/warn rules to currently visible sweepable rows.

## Collision Check

No collision with existing compatibility logic:
- Rules remain normative in `ruleset.v1.json`.
- New visuals are derived from existing rules, not a second rule system.
- Optionality design remains intact (empty means "not set", except context-driven mandatory/fatal keys).

No collision with RunnerMode fixed source block:
- concerns different keys (`ABEC.AkabakMode`, `LE`, `LE.Voltage`) and remains unchanged.

## Implementation Plan (next step)

1. Add field-hint helper in GUI that composes placeholder text from catalog metadata + small override map.
2. Add tooltip texts for selected dropdowns.
3. Add empty severity evaluator (context-aware, using current draft values).
4. Add subtle warning/fatal style application to wizard and batch numeric fields.
5. Keep existing global validity report and save/run blocking unchanged.
6. Add GUI contract tests for:
- placeholder generation for key samples (`Coverage.Angle`, `Throat.Angle`)
- severity mapping for empty fields (`Length`, guiding-curve case, explicit coverage case)

## Acceptance Criteria for implementation

- Placeholder texts are technically correct (especially half-angle semantics).
- Empty warning/fatal fields are visibly distinguishable (yellow/red border), without full fill.
- Logic is context-aware (e.g., `Coverage.Angle` warning disappears when `GCurve.Type` is set).
- No change to parameter keys, rule IDs, or runner restrictions.

## Implementation Status (2026-02-16)

Implemented from this design in current Batch UI:
- Batch page moved from JSON textareas to structured inputs.
- Per-field sweep UI implemented (`base`, `start`, `end`, `steps`) with inline reveal via sweep checkbox.
- Preview placeholder panel added (`Coming soon`, disabled actions).
- Summary + action-bar severity states aligned with PROJECT page style.
- Compatibility state now directly gates field visibility/locking/sweepability.

Not implemented yet from this design note:
- Dedicated contextual placeholder enrichment from catalog semantics for every batch field.
- Empty-field warn/fatal border accents in batch form (rule-derived visual state layer).
