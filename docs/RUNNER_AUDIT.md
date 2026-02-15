# RUNNER Audit (IST-Stand)

Datum: 2026-02-15

## Scope

Gepruefte Module (Codepfade):
- `app/runtime_orchestrator.py`
- `app/runners.py`
- `app/akabak_driver.py`
- `app/vacs_driver.py`
- `app/vacs_export_pipeline.py`
- `app/ui_automation/session.py`
- `app/ui_automation/watchdog.py`
- `app/ui_contracts/window_signatures.py`
- `app/safe_cleanup.py`
- `app/vacs_txt_parser.py`
- `app/compat_engine.py`, `app/compatibility_service.py`, `app/cfg_renderer.py`, `app/version_resolver.py`
- `app/sql_dataset_store.py`
- `app/cli.py`

## Executive Summary

- Der Runner-Stack ist aktuell **hybrid**: 
  - `runtime_orchestrator` nutzt ATH/AKABAK/VACS ueber `subprocess`-Runner (`app/runners.py`).
  - Die VACS-Exportstrecke kann UIA-basiert laufen (`app/vacs_export_pipeline.py` -> `app/vacs_driver.py`).
- UIA-Bausteine sind vorhanden, aber **noch nicht als harter End-to-End-Contract** durchgezogen.
- **BLOCKER (Anforderung A verletzt):** `app/ui_automation/watchdog.py` erzeugt optional Screenshots via `PIL.ImageGrab`; `akabak_driver` und `vacs_driver` aktivieren das aktuell (`capture_screenshot=True`).
- Safe-Cleanup ist bereits guard-basiert, aber noch nicht auf dediziertes Runner-Test-Workspace-Modell zugeschnitten.
- Fuer tausende Runs fehlen noch zentrale Robustheitsbausteine: einheitliche zustandsbasierte Wait-API mit Backoff/Timeout-Diagnostik, Prozess-Ownership-Tracking, deterministische Window- und Graph-Contracts, tiefe Export-Validierung.

## A) No-Visual-Automation Audit

### Ergebnis
- `OK`: Keine Pixel-/Template-Matching- oder OCR-Entscheidungslogik in den aktiven `app/*`-Runnerpfaden gefunden.
- `BLOCKER`: Screenshot-Capture vorhanden und aktivierbar:
  - `app/ui_automation/watchdog.py`: `_try_capture_screenshot()` via `PIL.ImageGrab`.
  - `app/akabak_driver.py` und `app/vacs_driver.py`: `ModalDialogWatchdog(..., capture_screenshot=True)`.

### Bewertung
- Auch wenn Screenshots aktuell nur diagnostisch genutzt werden, verletzt dies die hier gesetzte harte Vorgabe "keine visuelle Automation / keine Screenshots" fuer Runner-Tests.
- Der Blocker ist technisch klar isoliert und kann ohne funktionalen UIA-Verlust entfernt werden.

## Capability Matrix (Ist)

| Pipeline-Step | Implementiert | Aktueller Mechanismus | Status | Luecke / Risiko |
|---|---|---|---|---|
| CFG Render | Ja | `runtime_orchestrator` -> `cfg_renderer.render_cfg_text` | PARTIAL | Kein dediziertes Runner-Testprofil (fast/low-res) |
| Compatibility Precheck | Ja | `version_resolver` + `compat_engine` + `compatibility_service` | PARTIAL | Harness-spezifische Preflight-Kette fehlt |
| ATH Run | Ja | `AthRunner` (`subprocess`) | PARTIAL | Keine stepwise Contracts/Signals, nur Exitcode+stdout |
| AKABAK Run | Ja | `AkabakRunner` (`subprocess`) im Orchestrator; separater UIA-Driver existiert | PARTIAL | Orchestrator nutzt nicht den UIA-Driver; keine UIA-State-Verifikation im Hauptpfad |
| VACS Export | Ja | Entweder `VacsRunner` (`subprocess`) oder UIA via `vacs_export_pipeline` | PARTIAL | UIA nur fuer gemappte Specs; Fallback unstrukturiert |
| TXT Ingest | Ja | `vacs_txt_parser` -> `sql_dataset_store.write_measurements` | PARTIAL | Nur Basisvalidierung; keine harte Plausibilitaetschecks |
| Cleanup | Ja | `guarded_delete_tree` auf `ath_work` | PARTIAL | Kein dediziertes Runner-Test-Workdir-Allowlistmodell |
| Run Persistence | Ja | `runs`, `run_versions`, `graphs`, `graph_series`, `graph_points` | PARTIAL | Keine `runner_test.sqlite` + test-run step telemetry Tabellen |

## Window Detection / Selector Strategy (Ist)

### Vorhandene Strategie
- UIA Session (`pywinauto` primar, `uiautomation` fallback), prozessgebunden via `process_id`.
- Signatures in `app/ui_contracts/window_signatures.py` mit:
  - `process_names`
  - `class_name_regex`
  - `control_type`
  - optional `title_regex`
- Driver (`akabak_driver`, `vacs_driver`) nutzt derzeit meist `find_window(title_regex, class_name_regex)` plus Prozessbindung ueber Session.

### Bewertung
- `PARTIAL`: Gute Basis, aber noch nicht voll "textunabhaengig".
- `Gap`: `automation_id`/`native handle` wird in der Laufsteuerung kaum als Primarselektor durchgezogen.
- `Gap`: `ui_contracts/akabak/*.json` und `ui_contracts/vacs/*.json` als stepweise Vertraege fehlen.

## Bekannte Dialoge / Modal Handling (Ist)

- `ModalDialogWatchdog` hat eine generische Allowlist-Regel (`warning|notice|confirm|akabak|vacs` + `proceed|continue|overwrite|already exists|ok`).
- Bei unbekannten Dialogen: JSON-Debug-Artefakt + optional Screenshot + Exception.

Bewertung:
- `PARTIAL`: Unknown-dialog fail-fast ist vorhanden.
- `Risk`: Generische Muster sind fuer tausende Runs zu breit; step-spezifische modale Vertrage fehlen.

## Graph-Typen / Export-Mapping (Ist)

- Export-Semantik: `ExportSpec` + `ui_maps/vacs/<version>/graph_catalog.json`.
- Builtin Plugins aktuell: `spl`, `impedance` (`app/vacs_exporters/builtin.py`).
- Parser kann auch multi-series/polar/complex-Daten ingestieren (`vacs_txt_parser`).

Bewertung:
- `PARTIAL`: Framework ist da.
- `Gap`: End-to-End deterministische Zuordnung Graph-Kind <-> Exportdatei fuer mehr als die aktuell gemappten Typen ist nicht vollstaendig.
- `Gap`: Mismatch-Detektor (Header sagt X, Spec sagt Y) fehlt.

## Validierungen (Ist)

### Vorhanden
- Exportdatei existiert (plugin validation / datei pattern).
- Ingest failt bei 0 Punkten (`No numeric graph points found`).
- Pipeline markiert Stage als failed bei Parse-Fehlern oder fehlenden Exportfiles.

### Fehlend (harte Requirements)
- Dateigroesse > Schwellwert.
- Punktzahl > Schwellwert pro Exportspec.
- X-Monotonie (z. B. Frequenzachse).
- NaN/Inf-Flood Detection.
- Range-Sanity (z. B. nicht alle Y=0).
- AKABAK-spezifisch "solver not run" / "no result loaded" Signale als explizite Validation.

## Safe Cleanup / Deletion Safety (Ist)

### Vorhanden
- `guarded_delete_tree` erzwingt:
  - Existenz + Directory
  - nicht equal allowed root
  - target unterhalb `allowed_root`
  - optional `expected_dir_name`
  - optionale `deny_paths`

### Luecken gegen Zielbild
- Kein dediziertes `runner_test_workspace` als harter Root fuer alle Testartefakte.
- Keine strikt zentrale Allowlist + globale Denylist (Repo root, User Home, System dirs, Tool install dirs) fuer den Harness.
- Cleanup currently fokussiert auf `ath_work`; kein artefaktweises Policy-Modell (CFG/ATH-Output/Exports getrennt).

## Risiken fuer tausende Runs

1. `P0` Feste Sleeps in UIA-Flows (`time.sleep(0.5)` etc.) statt zentraler zustandsbasierter Wait-Strategie.
2. `P0` Kein globales step-telemetry Modell (retry count, detection attempts, timeout snapshots) im Runner-Test-DB-Schema.
3. `P0` Kein process ownership ledger: started PIDs sind nicht systematisch fuer teardown/kill-last-resort verwaltet.
4. `P1` Selector-Vertraege zu titel-/regex-lastig; wenig AutomationId/Handle-priorisierte Aktionen.
5. `P1` Graph-Mapping und Validierung nicht streng genug fuer breite Graph-Varianten.
6. `P1` Hauptorchestrator nutzt fuer AKABAK noch subprocess-Launch statt UIA-State-Machine.
7. `P2` Artefaktakkumulation ueber Langlaeufe (logs/exports) ohne dedizierte Harness-Retention-Policy.

## Priorisierte TODOs (Roadmap-fertig)

### P0 (Blocker / sofort)
1. Screenshot-Erzeugung aus Runner-UIA-Stack entfernen/deaktivieren (no-visual-policy hart durchsetzen).
2. Runner-Test-Workspace einfuehren (`runner_test_workspace/...`) mit hard-guarded delete API.
3. Runner_Test SQLite einfuehren (test_runs, test_cases, test_run_steps, ui_observations, artifacts, validations).
4. Zentrales `wait_until` mit Backoff/Timeout-Snapshot implementieren und harte Sleeps ersetzen.

### P1 (robustheit)
1. Stepweise UI Contracts als JSON (`ui_contracts/akabak/*.json`, `ui_contracts/vacs/*.json`) mit required windows/dialogs/actions.
2. Deterministische Window-Signatures pro Schritt (pid + class + control_type + automation_id + handle fallback).
3. Graph mismatch detector + striktes ExportSpec/Graph-Kind-Mapping.
4. Harte Export-/Signal-Validierungen (size, points, monotonic x, NaN/Inf, all-zero check).

### P2 (scale/perf)
1. `runner_test_profile=fast` (Mesh/Resolution/Segmentation/Frequency Overrides) nur im Harness.
2. Persistiere aktives TestProfile + effektive Overrides pro Testlauf in Runner_Test DB.
3. Wiederholungsmodus (`--repeats N`) mit Flake-Metriken und Failure-Kategorisierung.

## Phase-2 Entry Criteria (aus Audit abgeleitet)

- Vor Start E2E-Harness muessen mindestens umgesetzt sein:
  - no-visual-policy enforcement (Screenshot blockiert),
  - workspace-safe cleanup guards,
  - runner_test SQLite Grundschema,
  - Harness dry-run CLI fuer deterministische Vorpruefung.

---

Dieses Dokument ist rein auditiv; keine funktionalen Aenderungen in diesem Commit.
