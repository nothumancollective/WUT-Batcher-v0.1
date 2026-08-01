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

Safe clean umfasst Datei- und Prozessbesitz. Für Dateien nutzt es nur
Guard-Funktionen mit absoluten Pfaden:
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

Für jeden echten nativen Lauf gilt zusätzlich:

- vor dem Start werden PID, Parent-PID, Executable-Pfad, Startzeit, CPU und RAM
  aller relevanten Tools erfasst;
- nur Prozesse, die der aktuelle Lauf gestartet oder anhand dieser Identität
  übernommen hat, dürfen beendet werden;
- PID-Abstammung muss auch zeitlich stimmen (Kindstart nicht vor Elternstart),
  damit Windows-PID-Wiederverwendung keine falschen Prozessbäume erzeugt;
- fremde oder nicht eindeutig zuordenbare AKABAK-/VACS-Instanzen blockieren den
  Test statt namensweit beendet zu werden;
- vor dem Folgefall und am Batchende werden Prozess-, Fenster- und
  Ressourcenzustand erneut erfasst; eigene Reste sind ein Testfehler;
- `taskkill /IM`, globale Prozessnamen-Kills und ungebundene "Zombie"-Bereinigung
  sind für aktuelle Runner-Tests unzulässig.

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
- `simulation_timeout_minutes = 10`

Begruendung:
- reduziert Mesh-/Frequenzauflösung fuer schnellere Testzyklen
- behält validen ATH->AKABAK->VACS Toolflow bei

Verification Plan (im Profil hinterlegt):
1. gleiche Case einmal mit `fast` und einmal baseline laufen lassen, Step-Dauern vergleichen
2. sicherstellen, dass Exporte weiterhin nicht leer sind und Frequenzachse monoton bleibt

Persistenz:
- Profil + effektive Overrides werden pro Lauf in `test_runs.tool_versions` und `validations` (`test_profile_applied`) gespeichert.

## Weitere TestProfile

`baseline` wendet keine Harness-Overrides an. Es dient als unveränderte
Referenz für die effektiven Werte des Case/Templates.

`resource` erhöht die Last kontrolliert, ohne den Zwei-Fall-Stresstest
unbegrenzt werden zu lassen:

- `Mesh.AngularSegments = 28`
- `Mesh.LengthSegments = 18`
- `Mesh.CornerSegments = 4`
- `Mesh.ThroatSegments = 2`
- `Mesh.ThroatResolution = 14.0`
- `Mesh.MouthResolution = 26.0`
- `Mesh.RearResolution = 32.0`
- `freq_start_hz = 600`
- `freq_end_hz = 6000`
- `num_points = 8`
- `simulation_timeout_minutes = 20`

Der Ressourcenwert wird vom Harness als 1.200 Sekunden Inaktivitätsgrenze an
den AKABAK-Treiber weitergegeben; dessen begrenzte Hard-Limit-Logik ergibt
2.400 Sekunden. Diese Änderung gilt nur für das Harness-Profil `resource`.
Der allgemeine Produktstandard und die UI-Vorgabe bleiben bei zehn Minuten
und weiterhin konfigurierbar.

Das Profil ist für den geforderten ressourcenintensiveren Repeat mit maximal
zwei Einzelsimulationen vorgesehen. Profilname und effektive Werte werden wie
bei `fast` in DB und Validierungen gespeichert.

## CLI Nutzung

### Dry-Run (ohne Toolstart)

```powershell
python -m app runner-test run --case smoke_fast --dry-run
```

### E2E mit Tools

```powershell
python -m app runner-test run --case smoke_fast --repeats 5 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe" --template-cfg "C:\Tools\ATH\test.cfg"
```

Defaults:
- `--repeats 1`
- `--keep-exports true`
- `--test-profile fast`
- alternative Profile: `baseline`, `resource`
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

## AKABAK Open-Dialog Micro-Harness

```powershell
python -m app runner-test open-dialog-only --akabak-exe "C:\Tools\AKABAK\AKABAK.exe" --abec-path "C:\path\to\Project.abec" --repeats 5
```

Der Micro-Harness testet nur:
- AKABAK Start
- Open-Dialog oeffnen
- Pfad setzen + bestaetigen (Tier A/B/C non-visual)
- Dialog schliesst + project-loaded signal
- AKABAK sauber beenden
## AKABAK Import-Start-Apply Micro-Harness

```powershell
python -m app runner-test import-start-apply-only --akabak-exe "C:\Tools\AKABAK\AKABAK.exe" --abec-path "C:\path\to\Project.abec" --repeats 5
```

Der Micro-Harness testet nur:
- AKABAK Start + Projekt oeffnen
- Interpreter-Flow: `Start Importing` -> `Apply`
- Postcondition: Interpreter geschlossen ODER `Start Importing` deaktiviert
- deterministische Modal-Erkennung (z. B. missing mesh) mit Fail-Fast
- AKABAK sauber beenden

Diagnostik bei Fehler:
- Import-Dumps unter `runner_test_workspace/logs/<test_run_id>/akabak/import_failure_*.json`
- Persistenz in DB:
- `artifacts.kind = akabak_failure_diagnostics`
- `validations.validation_name = import_start_apply_postcondition`
