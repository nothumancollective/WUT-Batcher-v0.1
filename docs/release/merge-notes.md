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

## Phase 2: Tests und Stabilität
- `python -m pytest -q` (Repo-Root) bricht in Collection mit Legacy-Artefakten unter `cleanup/p1_runtime/failures/*.txt` (UTF-16/Decode-Fehler) ab.
- Zielgerichtete Integrationsläufe:
  - `python -m pytest tests/test_dashboard_constraints_ui.py tests/test_project_manager_ui.py tests/test_gui_analyzer_page_ui.py tests/test_gui_analyzer_compare_ui.py tests/test_gui_modebar_ui.py -q`
  - Ergebnis: `83 passed`
- Zusätzliche Fixes für Integrationsstabilität:
  - `AnalysePage.closeEvent` ergänzt, ruft `shutdown()` auf (beendet Worker sauber beim Widget-Close, verhindert SQLite-Lock bei Temp-Cleanup unter Windows).
  - Score-Metrik-Label in Version-Information auf rechtsbündige Ausrichtung vereinheitlicht (`AlignRight | AlignVCenter`) entsprechend bestehender Test- und UI-Erwartung.
- Hinweis:
  - Ein Voll-Lauf `python -m pytest tests -q` wurde gestartet, aber in dieser Session per Timeout beendet; die oben genannten relevanten Integrations-Suiten sind grün.

## Pytest collection failure (cleanup artifacts)
- Verifiziert am aktuellen `wut-batcher/rebuild` nach `git fetch origin`:
  - `git status -sb`: `## wut-batcher/rebuild...origin/wut-batcher/rebuild [ahead 272]`
  - `python -m pytest -q` reproduziert Collection-Fehler vor Testausf�hrung.
- Fehlerursache:
  - Doctest/pytest sammelt `cleanup/p1_runtime/failures/*.txt` ein.
  - Diese Dateien sind nicht UTF-8 (Byte `0xff` bei Position 0), daher `UnicodeDecodeError` in `pathlib.read_text` w�hrend Collection.
- Beispielpfad aus dem Trace:
  - `cleanup/p1_runtime/failures/test_advanced_toggle_hides_advanced_rows_by_default.txt`
- Konsequenz:
  - Testlauf wird in der Collection abgebrochen (`Interrupted: 8 errors during collection`), bevor eigentliche Tests starten.

## Pytest hygiene fix (cleanup excluded)
- Added repository pytest configuration in `pytest.ini`.
- `cleanup` is now part of `norecursedirs`, so pytest will not recurse into legacy runtime-artifact folders.
- This keeps current doctest/test behavior elsewhere unchanged and only removes non-product artifact folders from discovery.
- Rationale: `cleanup/p1_runtime/failures/*.txt` are legacy failure snapshots with non-UTF8 encoding and are not runtime code/tests.
- Expected effect: `python -m pytest -q` no longer aborts during collection because of cleanup text artifacts.
