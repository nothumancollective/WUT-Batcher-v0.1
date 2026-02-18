# QA_REPORT

## Ziel / Scope
- Pipeline-Integration P0-P6 fuer den Batch-Run stabilisieren (Versionen -> CFG -> Runner -> Persistenz -> Cleanup).
- Danach Regression/QA auf Runtime-, Service- und zentrale UI-Flows.

## Environment
- OS: Windows (PowerShell)
- Python: `python -m pytest`
- Repo: `c:\Users\maximilianheinze\Desktop\WUT Batcher v0.1`
- Wichtige Module:
  - `app/runtime_orchestrator.py`
  - `app/services.py`
  - `app/cli.py`
  - `tests/test_runtime_orchestrator.py`

## Datenfluss (Versionen-Loop)
1. `materialize_batch_plan(...)` erzeugt deterministische Versionen inkl. `version_id`.
2. Pro Version wird CFG aus Constraint+Batch+Sweep aufgeloest (`version.json.parameters`) und gerendert.
3. Es werden zwei CFGs geschrieben:
   - `versions/<V>/cfg/input.cfg` (Snapshot)
   - `versions/<V>/cfg/<runtime_basename>.cfg` (Run-CFG fuer ATH)
4. Runner-Stages laufen pro Version (ATH -> optional AKABAK -> optional VACS).
5. Persistenz in SQL (Projekt-DB + Global-DB Spiegel) wird auf `global_synced` geprueft.
6. Cleanup nur bei erfolgreicher Version **und** synchroner Persistenz:
   - Run-CFG loeschen
   - ATH-Export-Unterordner loeschen (`<ath_export_root>/<runtime_cfg_stem>`)
7. Bei Stage-Fehler oder Sync-Fehler: kein Cleanup, Artefakte bleiben fuer Diagnose.

## Testfaelle (ausgefuehrt)
- `python -m pytest tests/test_runtime_orchestrator.py tests/test_service_export.py tests/test_cli_run_sample.py -q`
  - Ergebnis: `18 passed`
- `python -m pytest tests/test_sql_dataset_store.py tests/test_version_resolver.py tests/test_project_storage_and_tidy.py tests/test_runtime_orchestrator.py tests/test_service_export.py -q`
  - Ergebnis: `34 passed`
- `python -m pytest tests/test_batch_page_ui.py tests/test_project_form_ui.py tests/test_project_manager_ui.py tests/test_gui_project_fixed_keys.py tests/test_preview_pipeline.py -q`
  - Ergebnis: `84 passed, 6 skipped`

## Findings (Bugliste)
1. Cleanup-Vertrag war nicht P0-konform: bisher wurde nur `ath_work` bereinigt.
2. Pipeline beruecksichtigte `global_synced` nicht fuer per-version Erfolg/Cleanup.
3. Kein expliziter per-version Runtime-CFG/ATH-Export-Manifest-Pfad in `version.json`.

## Fixes
- Per-version Runtime-CFG mit stabilem Basename eingefuehrt und in `version.json` protokolliert.
- Cleanup auf Zielvertrag umgestellt:
  - `cfg/<runtime>.cfg`
  - ATH-Export-Unterordner
- Persistenz-Sync-Gating eingefuehrt:
  - bei `global_synced=false` wird Version als failed behandelt und Cleanup unterdrueckt.
- CLI-Run-Sample Cleanup-Checks auf neue Cleanup-Artefakte aktualisiert.
- Regressionstests erweitert:
  - Runtime-Manifest in Dry-Run
  - Cleanup von Runtime-CFG + ATH-Export-Subfolder bei erfolgreichem Run

## Offene Risiken / TODO
- Echte End-to-End Tool-Integration mit realem ATH/AKABAK/VACS in produktiver Toolchain (nicht nur Runner-Mocks/Stubs) bleibt als separater Integrationsblock.
- Dual-Write ist weiterhin project-first + global-mirror mit Retry-Queue; semantische "2PC-Atomizitaet" ueber beide DBs ist nicht implementiert.

## QA Artefakte / Cleanup
- Registry-Datei angelegt: `qa_artifacts.json`.
- In diesem Durchlauf wurden keine `QA__*` Artefakte erzeugt -> kein Loeschlauf erforderlich.
- Cleanup Report:
  - geloescht: `0`
  - behalten: `0`
  - unklar/manuell: `0`

## UI E2E Stress (Interactive)
### Durchlauf 1
- Flow: Project Manager -> New Project -> Constraints -> Create -> New Batch -> 2 Sweeps -> Preview (2 Updates) -> Run.
- Ergebnis: erfolgreich.
- Nachweise:
  - Run-Status `succeeded`
  - persistierte `run_versions` in Projekt-DB und Global-DB
  - per-version Cleanup von Runtime-CFG + ATH-Export-Subfolder.

### Durchlauf 2
- Gleiches End-to-End Muster mit neuem Projekt und neuem Batch.
- Ergebnis: erfolgreich.
- Nachweise:
  - Preview erneut aktualisiert
  - konsistente Version-IDs und Statuskette je Version.

### Durchlauf 3
- Gleiches End-to-End Muster mit drittem Projekt/Batch.
- Ergebnis: erfolgreich.
- Nachweise:
  - `run_status=succeeded`
  - keine DB-Inkonsistenz
  - Cleanup-Regeln eingehalten.

### Gefundene Probleme und Fix
- Problem: Windows-Dateilock im Test-Teardown auf `global.sqlite` (Temp-Workspace).
- Fix: deterministischer UI-Teardown im E2E-Stresstest (`preview worker stop`, Widget cleanup, retry-cleanup).

### Stability
- Status: **GREEN**
- Kriterien erfuellt:
  - 3 vollstaendige UI-E2E Runs hintereinander ohne funktionale Fehler
  - Persistenz/Versionen-Loop/Cleanup pro Version validiert
  - Preview mehrfach erfolgreich aktualisiert.
