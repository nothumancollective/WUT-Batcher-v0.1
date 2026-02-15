# RUNNER Test Harness

## Ziel

Der Harness fuehrt isolierte Runner-Tests in einem dedizierten Workspace aus und schreibt jeden Lauf in eine persistente `runner_test.sqlite`.

Pipeline pro Run:
- preflight
- cfg generation (inkl. compatibility check + TestProfile)
- ATH
- AKABAK (UIA)
- VACS export (UIA)
- ingest
- validation
- safe clean

## Verzeichnislayout

Root: `runner_test_workspace/`
- `cfg/` erzeugte temporaere CFGs
- `ath_out/` ATH-Ausgabe pro Run/Version
- `exports/` VACS TXT-Exporte pro Run
- `logs/` Lauf- und UIA-Logs
- `db/runner_test.sqlite` persistente Test-Historie

Alle Harness-Artefakte bleiben in diesem Root.

## Safe Clean Policy

Safe clean nutzt nur Guard-Funktionen mit absoluten Pfaden:
- `guarded_delete_file_in_workspace(...)`
- `guarded_delete_tree_in_workspace(...)`

Erzwingt:
- absolute targets
- target unterhalb `runner_test_workspace`
- parent/name checks (z. B. `ath_out/<run_version>`)
- denylist-Pruefung

Gelöscht wird pro Run:
- erzeugte CFG in `cfg/`
- ATH-Ausgabeordner in `ath_out/`
- optional Exportordner in `exports/` (nur wenn `--keep-exports false`)

## Runner_Test DB

Datei: `runner_test_workspace/db/runner_test.sqlite`

Kern-Tabellen (projekt-kompatibel):
- `runs`, `versions`, `run_versions`, `ath_dimensions`
- `graphs`, `graph_series`, `graph_points`

Harness-Tabellen:
- `test_runs`
- `test_cases`
- `test_run_steps`
- `ui_observations`
- `artifacts`
- `validations`

Jeder Lauf bekommt eine neue `test_run_id` (UUID).

## TestProfile: `fast`

Der Harness wendet standardmaessig `runner_test_profile=fast` an.

Parameter-Overrides (nur Harness, nicht Produktions-Runs):
- `Mesh.AngularSegments = 24`
- `Mesh.LengthSegments = 16`
- `Mesh.CornerSegments = 4`
- `Mesh.ThroatSegments = 2`
- `Mesh.ThroatResolution = 12.0`
- `Mesh.MouthResolution = 24.0`
- `Mesh.RearResolution = 30.0`

Simulation-Overrides:
- `freq_start_hz = 800`
- `freq_end_hz = 4000`
- `num_points = 6`

Begruendung:
- reduziert Mesh-/Frequenzauflösung fuer schnellere Testzyklen
- behält validen ATH->AKABAK->VACS Toolflow bei

Verification Plan (im Profil hinterlegt):
1. gleiche Case einmal mit `fast` und einmal baseline laufen lassen, Step-Dauern vergleichen
2. sicherstellen, dass Exporte weiterhin nicht leer sind und Frequenzachse monoton bleibt

Persistenz:
- Profil + effektive Overrides werden pro Lauf in `test_runs.tool_versions` und `validations` (`test_profile_applied`) gespeichert.

## CLI Nutzung

### Dry-Run (ohne Toolstart)

```powershell
python -m app runner-test run --case smoke_fast --dry-run
```

### E2E mit Tools

```powershell
python -m app runner-test run --case smoke_fast --repeats 5 --keep-exports true --test-profile fast --ath-exe "C:\\Tools\\ATH\\ATH.exe" --akabak-exe "C:\\Tools\\AKABAK\\AKABAK.exe" --vacs-exe "C:\\Tools\\VACS\\vacsviewer_32.exe"
```

Defaults:
- `--repeats 1`
- `--keep-exports true`
- `--test-profile fast`
- `--workspace-root runner_test_workspace`
- `--cases-root runner_test_cases`

## Sample Case

Beispiel-Case liegt unter:
- `runner_test_cases/smoke_fast.json`

## UI Contracts (Stubs)

Contract-Stubs fuer window/child-window Vertraege:
- `ui_contracts/akabak/solve_flow.contract.json`
- `ui_contracts/vacs/export_txt_flow.contract.json`

Diese Stubs dienen als Ausgangspunkt fuer step-spezifische Contract-Haertung.

## DB-Inspection (Quick Queries)

```sql
SELECT test_run_id, started_at, finished_at, status FROM test_runs ORDER BY started_at DESC;
SELECT test_run_id, step_name, status, started_at, finished_at FROM test_run_steps ORDER BY rowid DESC;
SELECT test_run_id, validation_name, status, message FROM validations ORDER BY validation_id DESC;
SELECT run_id, version_id, status FROM run_versions ORDER BY created_at DESC;
```

## Wichtige Hinweise

- Keine visuelle Automation im Runner-Flow: kein OCR, kein Pixel-Matching, keine Screenshot-Entscheidungen.
- UIA-basierte Steuerung bleibt process-aware.
- Bei fehlenden/inkonsistenten UI-Vertraegen wird fail-fast mit Diagnostik in `logs/` und DB-Events ausgefuehrt.
