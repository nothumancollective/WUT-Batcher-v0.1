# Merge Notes: rebuild + polar-analyzer-ui (2026-02-25)

## Ausgangslage (Phase 0)
- Arbeitsbranch vor Integration: `wut-batcher/rebuild`
- `git status --short --branch`: `## wut-batcher/rebuild...origin/wut-batcher/rebuild` (clean)
- Die drei Project-UI-Commits sind lokal **und** auf Remote vorhanden:
  - `f9a5329` docs(ui): record rebuild merge preflight and dashboard audit
  - `b6ce02b` feat(ui): restructure dashboard top row and action panel
  - `7550ae1` feat(ui): add project constraints chip grid and editor focus flow
- `origin/wut-batcher/rebuild` zeigt diese drei Commits an der Spitze.
- `origin/feature/polar-analyzer-ui` hat separate Analyzer-/Iterate-/Final-Dim-/Score-Commits (Top: `a34bad6`).

## Integrationsstrategie
- Safe-Branch: `integrate/rebuild+polar` von `wut-batcher/rebuild`.
- Merge-Richtung: `origin/feature/polar-analyzer-ui` -> `integrate/rebuild+polar`.
- Ziel:
  - Analyzer-UI/Iterate/Final-Dim/Score erhalten
  - Project-Page-Redesign auf `rebuild` erhalten
  - Storage/Library-Pfadlogik nicht schwächen

## Konflikte und Entscheidungen
- Konfliktdateien:
  - `app/gui.py`
  - `ui/theme.py`
- Auflösung:
  - `app/gui.py`: Dashboard/Project-Page-Redesign aus `rebuild` beibehalten (Top-Row 2/3 + 1/3, Actions-Panel, keine alten Bottom-Bars). Cleanup bleibt nur als optionaler Dev-Button via `WUT_SHOW_CLEANUP_BUTTON=1`.
  - `ui/theme.py`: beide Änderungen zusammengeführt:
    - `SummaryChip`-Button-Styles (Project-Page-Chips)
    - Analyzer `CommandHeader`/`CommandIssuesChip`-Styles

## Validierung
- Phase-1 GUI-Smoke (offscreen) erfolgreich:
  - Project Dashboard rendert, Resize (`980x720`, `1320x860`) ohne Fehler
  - Actions vorhanden: `New`, `Edit`, `Clone`, `Manage`, `Export`
  - Analyzer öffnet mit Tabs `Explorer`, `Compare`, `Iterate`
  - Version-Information enthält `Dim (LxWxH)` und Score-Chip-Widget ist vorhanden
- Weiterführende Testläufe und eventuelle Stabilitätsfixes werden in den nächsten Abschnitten ergänzt.
