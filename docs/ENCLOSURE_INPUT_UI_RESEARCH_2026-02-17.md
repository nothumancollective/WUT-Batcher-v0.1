# Enclosure Input Format + UI Pattern Notes (2026-02-17)

## Scope
This note captures the verified `Mesh.Enclosure` input format and the UI strategy used on Project/Batch pages.

## ATH format findings (guide-backed)
Source: `C:\Users\maximilianheinze\Desktop\Ath-4.8.2-UserGuide-2.pdf`

- Section `4.1.5` / table overview (`p.21`) defines:
  - `Mesh.Enclosure = { ... }` object syntax
  - stock enclosure fields: `Spacing`, `Depth`, `EdgeRadius`, `EdgeType`, `FrontResolution`, `BackResolution`
  - plan mode: `Plan = <plan_item>` plus spacing/resolution fields
- Section `6.12.1` (`p.55`) states:
  - for stock enclosure, only `Depth` is mandatory
  - `FrontResolution` and `BackResolution` represent 4 quadrant values
  - fewer values are allowed and interpreted progressively by ATH
- Section `6.12.2` (`p.57-58`) shows:
  - plan-mode uses an external plan script block (`my_plan = { ... }`)
  - `Mesh.Enclosure = { Plan = my_plan ... }`
  - spacing semantics differ in plan mode (only top/bottom used in shown case)

## Implemented UI behavior
- `Mesh.Enclosure` stays an object editor (not flattened into unrelated cards).
- List-like fields (`Spacing`, `FrontResolution`, `BackResolution`) accept flexible input separators:
  - comma, semicolon, whitespace
- Placeholders and hints were aligned to fixed-vector expectations:
  - e.g. `v1, v2, v3, v4`
- Validation layer adds non-blocking warnings for:
  - non-numeric list entries
  - empty lists
  - list length > 4
  - plan-mode preview limitations

## Preview-specific decision
- Preview generation uses stock enclosure fallback if plan-mode cannot be fully materialized in generated CFG workflow.
- In that case, preview payload adds `preview_notes` to explain the downgrade.

## Modern UI pattern references
The implementation follows standard typed-input + inline validation patterns:

- Qt validators on text inputs:
  - https://doc.qt.io/qt-6/qvalidator.html
  - https://doc.qt.io/qt-6/qdoublevalidator.html
  - https://doc.qt.io/qt-6/qlineedit.html#setValidator
- Structured object editing pattern in forms (explicit field controls over raw text blobs):
  - https://doc.qt.io/qt-6/model-view-programming.html

Practical takeaway for this codebase:
- keep object/list inputs structured and validated at field level,
- avoid free-form JSON/text editing in main flow,
- surface format issues inline as helper/warn states rather than modal error spam.

