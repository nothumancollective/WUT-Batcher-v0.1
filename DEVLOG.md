# DEVLOG

## 2026-02-20
### Update: Fallback-Audit (Real-E2E) + deaktivierter non-funktionaler Interim-Rescue-Branch
#### Ziel
- Ermitteln, wie oft Fallbacks im normalen Runner-Ablauf wirklich genutzt werden.
- Non-funktionale Fallbacks im Produktionspfad deaktivieren, ohne robuste Fallback-Struktur zu verlieren.

#### Audit-Ergebnis (bestehende Logs)
- Aggregation ueber `external_vacs_export_save_all/run_*/summary.json`:
  - `142` Runs gesamt, `134` erfolgreich.
  - `fallback_used=true`: `0` (im produktiven `assume_vacs_ready`-Pfad kein fast->safe->rescue Treffer).
  - Runs mit `interim_reimport*`-Steps: `3`.
  - Diese `3` Interim-Runs waren ausschliesslich mit `assume_vacs_ready=false` und endeten mit `interim_reimport_failed`.
- Real-Workspace `real_runtime_e2e9/P001`:
  - `vacs.export_pipeline` zeigt in aktuellen Erfolgslaeufen `external_fallback_used=false`.

#### Real-E2E-Verifikation (neu)
- `run pipeline` auf `P001/B010_FASTCHECK`:
  - `run_id=d83d05f7-12a9-4f8d-9b14-185941c470b7`, `run_status=succeeded`, Version `V069`.
- `run pipeline` auf `P001/B010` (Default):
  - `run_id=ee1ea180-69dc-4b52-8a77-6385886549c7`, `run_status=succeeded`, Version `V070`.
- In beiden neuen Laeufen:
  - VACS-Export im `fast`-Pfad.
  - Kein Interim-Reimport.
  - `external_fallback_used=false`.

#### Fix
- `scripts/vacs_export_save_all.py`:
  - Auto-Mode-Rescue-Branch (`assume_vacs_ready=True` -> `assume_vacs_ready=False` + Interim-Reimport) ist jetzt standardmaessig deaktiviert.
  - Neuer opt-in Schalter: `--allow-interim-rescue`.
  - Wenn deaktiviert, wird explizit geloggt:
    - `safe_rescue_skipped.reason = "disabled_by_default"`
    - `safe_rescue_skipped.toggle = "--allow-interim-rescue"`

#### Warum diese Deaktivierung
- Im finalen Runner ist AKABAK in dieser Phase typischerweise bereits beendet; der Interim-Rescue-Pfad ist daher in diesem Kontext praktisch non-funktional und verlaengert nur die Fehlerlaufzeit.
- Der robuste Hauptfallback (`fast -> safe` mit `assume_vacs_ready=true`) bleibt erhalten.
- Fuer gezielte Diagnostik ist der alte Rescue-Weg weiterhin manuell aktivierbar (`--allow-interim-rescue`).

#### Tests
- `python -m py_compile scripts/vacs_export_save_all.py app/vacs_export_pipeline.py app/runtime_orchestrator.py app/akabak_driver.py`
- `python -m pytest tests/test_vacs_export_pipeline.py tests/test_runtime_orchestrator.py -q` -> `23 passed`
- Negativprobe (kein VACS bereit) ohne Rescue:
  - sauberer Abbruch mit `vacs_not_ready_after_f4` und `safe_rescue_skipped`, ohne Interim-Zweig.
- Negativprobe mit `--allow-interim-rescue`:
  - Rescue-Pfad wird wie erwartet wieder versucht (und in diesem Setup erwartbar `interim_reimport_failed`).

## 2026-02-20
### Update: AKABAK-Solve-Start Hardening (kein 600s-Haenger mehr bei leerem VACS)
#### Ursache
- Im Runtime-Flow konnte `run_solve` faelschlich als gestartet gelten, sobald nur `VacsViewer - (new)` erschien.
- Folge: `wait_for_completion` wartete bis zu 600s auf Graph-Import-Signale, obwohl faktisch kein echter Solve/Handoff lief.
- Open-Dialog Tier-A konnte ausserdem ohne verifizierten Dateiname als erfolgreich durchgehen.

#### Fix
- `app/akabak_driver.py`:
  - Solve-Start ist jetzt mehrstufig und robust:
    - starke Signale zuerst (`progress_window`, Worker-PID, VACS+Graphsignal)
    - Trigger-Ladder: `F4 -> F5 -> Solve-Menu (best effort) -> F4`
    - nur als letzte Stufe schwaches `new_vacs`-Signal.
  - `wait_for_completion` sendet bei fehlendem VACS-Graph-Handoff wiederholt `F7` (mit Intervall/Max-Versuchen).
  - Handoff-Stall-Abbruch jetzt bei `180s` statt fruehem Abbruch, damit schwere Defaults nicht falsch als Fehler gewertet werden.
  - Open-Dialog-Hardening:
    - Tier-A/Tier-B/Tier-C verlangen jetzt verifizierten Dateiname-Readback, bevor bestaetigt wird.
    - Tier-B priorisiert `SetDlgItemTextW(...,1148)` vor generischem `WM_SETTEXT` auf unsicheren Controls.
- `app/runtime_orchestrator.py` / `app/vacs_export_pipeline.py`:
  - Default-Polar-Exports nutzen eindeutige Varianten (`spl_h/spl_v/spl_d`).
  - External-`any_graph`-Mapping schreibt eindeutige Varianten (`external_XX`) und verhindert DB-Unique-Konflikte beim Ingest.

#### Verifikation
- Real-Run manuell (`manual_runtime_check_low`): alter 600s-Stall wurde in klare `solve_not_started`-Diagnose ueberfuehrt (schneller, deterministischer Fehlerpfad).
- `runner-test run --case test_cfg_baseline --repeats 1 --test-profile fast` bleibt gruen (`succeeded`, ~45s).
- Real-Run im echten Projektkontext (`real_runtime_e2e9/P001`, Batch `B010_FASTCHECK`) ist E2E gruen:
  - `run_id=cdaafc5d-ee00-4aa3-b5e3-8b85128f125c` -> `run_status=succeeded`.
- Real-Run im echten Projektkontext mit Original-Defaults (`real_runtime_e2e9/P001`, Batch `B010`) ist ebenfalls E2E gruen:
  - `run_id=5bd4076e-a7cf-4971-a1dd-df504b806136` -> `run_status=succeeded`.
- Unit-Regression:
  - `python -m pytest tests/test_vacs_export_pipeline.py tests/test_runtime_orchestrator.py -q` -> `23 passed`
## 2026-02-20
### Update: Harness-CFG an Runtime angeglichen + Free-Standing Default erzwungen
#### Ursache
- Runner-Harness hat die Sim/Export-Settings nicht in die CFG angereichert (anders als Runtime), dadurch fehlten Polar-Bloecke trotz `auto_default_polar_exports`.
- In einzelnen Testkontexten konnte weiterhin `infinite_baffle` auftauchen.

#### Fix
- `app/runner_test_harness.py`:
  - nutzt jetzt `_apply_sim_export_settings_to_cfg(...)` beim CFG-Bau (inkl. Polar-Bloecke aus ExportSpecs).
  - erzwingt fuer Harness-Tests `simulation_mode=free_standing` via `_enforce_free_standing_for_tests(...)`.
  - `simulation_mode_guard` loggt jetzt zusaetzlich `profile_effective_simulation_mode`.

#### Verifikation (real)
- Test-Run `8cdb1842-4f00-41c6-bf63-2bfd0d78b554`:
  - `generate_cfg`: `cfg_export_specs_count=3`, `effective_simulation_mode=free_standing`
  - VACS Fast-Export Snapshot: `graph_count=4` (3x Polar + 1x RadImp)
  - Run-Status: `succeeded`
## 2026-02-20
### Update: Fast-Mode Stabilitaet + Laufzeit (Graph-Vollstaendigkeit / Wartezeiten)
#### Ursache
- Fast-Export hat die Graph-Liste zu frueh einmalig gesnapshottet; spaet erscheinende Polars konnten fehlen (z. B. nur 1 Polar + RadImp).
- Interim-Reimport wartete auf heuristische Control-/Keyword-Grenzwerte, obwohl Graph-Fenster bereits vorhanden waren.
- AKABAK Open/Import hatte unnoetig lange Confirm-/Postcondition-Waits im haeufigen Erfolgsfall.

#### Fix
- `scripts/vacs_export_save_all.py`:
  - Fast-Mode ergaenzt um Graph-Stabilisierung (`_collect_graphs_until_stable_fast`) vor dem Export.
  - `assume_vacs_ready`-Scan mit kurzer Poll-Phase statt sofortigem fruehen Abbruch.
  - Logging ergaenzt (`graph_snapshot_stabilized`, `observed_counts`, `stable_elapsed_s`).
- `scripts/vacs_interim_reimport.py`:
  - Neue Metrik `graph_window_count` (direkte Erkennung von `TForm_DatGraph`/`TForm_DatContour`).
  - Reimport gilt als erfolgreich, sobald echte Graph-Fenster sichtbar sind.
  - Poll-Backoff gedeckelt (`<=0.35s`) fuer schnelleren Uebergang in den Export.
- `app/akabak_driver.py`:
  - Kuerzere Watchdog-Confirm-Wartezeit nach Interpreter-Aktionen.
  - Kuerzere Open-Dialog Close-/Postcondition-Waits.
  - Kuerzeres Open-Dialog Timeout im Primaerpfad.

#### Tests
- `python -m py_compile scripts/vacs_export_save_all.py scripts/vacs_interim_reimport.py app/akabak_driver.py app/vacs_export_pipeline.py`
- `python -m pytest tests/test_vacs_export_pipeline.py -q` -> `8 passed`
- `python -m pytest tests/test_runtime_orchestrator.py -q` -> `15 passed`
- `python -m pytest tests/test_runner_test_harness.py -q` -> `21 passed`
## 2026-02-19
### Update: Runner-Tests erzwingen vorerst `free_standing` (Infinite Baffle guard)
#### Ursache
- In Runner-Tests mit `simulation_mode=infinite_baffle` erzeugte AKABAK Fehler, weil die Position der Infinite Baffle im Test-Flow nicht definiert ist.

#### Fix
- `app/runner_test_profiles.py`:
  - Fast-Testprofil setzt `sim_export_overrides.simulation_mode = free_standing`.
- `app/runner_test_harness.py`:
  - Neues Validation-Logging `simulation_mode_guard` mit:
    - requested/effective Simulation Mode
    - Flag `forced_free_standing`
    - Grund `infinite_baffle_position_not_defined_in_test_flow`

#### Hinweis
- Infinite Baffle bleibt für den Produktionspfad unangetastet und wird später separat implementiert.
## 2026-02-19
### Update: Run-Abbruch behoben (VACS-Export + minimales Run-Template)
#### Ursache
- Nach Umstellung auf minimales `template_run.cfg` traten zwei Folgefehler in Real-Runs auf:
  - `run_id=26d5cbcf-c850-4990-86b6-9611944c9d7f`: externer VACS-Exporter scheiterte mit `AKABAK not attachable` (weil AKABAK bereits geschlossen war).
  - `run_id=b7aed416-aaa8-481b-b5fa-e71fb755c8f9`: VACS-Export lief, aber Mapping schlug fehl (`graph_kind=polar` erwartet, nur `Radiation Impedance` vorhanden).
- Root Cause:
  - Lifecycle-Konflikt zwischen AKABAK-Stage und externem VACS-Exporter.
  - Mit minimalem Template fehlten ABEC/Polar-Simulationsblöcke in der Run-CFG, daher wurde kein Polar-Graph erzeugt.

#### Fix
- `app/runtime_orchestrator.py`:
  - AKABAK-UI-Stage erweitert um `preserve_vacs_for_export`:
    - VACS wird nach Solve nicht sofort beendet, wenn direkt danach VACS-Export folgt.
  - Neue CFG-Anreicherung aus `sim_export_settings` + `export_specs`:
    - `ABEC.SimType`, `ABEC.f1`, `ABEC.f2`, `ABEC.NumFrequencies`, optional `ABEC.MeshFrequency`.
    - Polar-Blocks `ABEC.Polars:<polar_name>` inkl. `MapAngleRange`, `Distance`, `Offset`, `Inclination`.
- `app/vacs_export_pipeline.py`:
  - Externer Export wieder im `fast + --assume-vacs-ready` Pfad (passt nun zum erhaltenen VACS-Prozess zwischen AKABAK und Export).

#### Tests
- `python -m pytest tests/test_runtime_orchestrator.py tests/test_vacs_export_pipeline.py -q`
  - `21 passed`
- `python -m pytest tests/test_cli_run_sample.py tests/test_ath_driver_assets.py -q`
  - `9 passed`

#### Real E2E Verifikation
- Erfolgreicher Real-Run mit Default-Mesh/Export-Setup auf `P001/B003`:
  - `run_id=2b786edf-d2eb-41f8-8bb6-631e882ee50c`
  - `run_status=succeeded`
  - Versionen `V024`, `V025`, `V026`: ATH/AKABAK/VACS jeweils `ok`.
- Logbeleg: VACS wurde für Export erhalten und danach beendet (`kill_vacs_final` im externen Export-Summary).

## 2026-02-19
### Update: Run-Template auf `template_run.cfg` umgestellt (ohne Preview-Änderung)
#### Done
- Neue Datei `C:\Tools\ATH\template_run.cfg` angelegt mit minimalem Run-Block:
  - `Output.ABECProject = 1`
  - `Output.STL = 0`
  - `ABEC.AkabakMode = 1`
  - `LE = generic25`
  - `LE.Voltage = 1.0`
  - `LE.System = S1`
  - `LE.Driver = D1`
- Runtime-Template-Resolver in `app/runtime_orchestrator.py` angepasst:
  - Fallback-Reihenfolge beginnt jetzt mit `template_run.cfg` vor `test.cfg`.
- Preview-Template-Logik bleibt unverändert (`app/services.py`), d. h. kein Eingriff in den Preview-Pfad.

#### Validation
- `_resolve_template_cfg_path(None, ath_executable="C:\\Tools\\ATH\\ath.exe")` -> `C:\Tools\ATH\template_run.cfg`.
- `python -m pytest tests/test_runtime_orchestrator.py -q` -> `13 passed`.

## 2026-02-19
### Update: Incident Analyse `8386434c-a51f-4e01-82d3-21249f28e444` (VACS-Import Crash/Abbruch + Preview-Abweichung)
#### Befund (ohne Fix)
- Betroffener Run: `runner_test_workspace/real_runtime_e2e9/P001`, Batch `B003`, Status bleibt in DB auf `running`.
- Versionstand im Run: `V015` steht auf `akabak_ok`; nach AKABAK wurde VACS-Export nicht erfolgreich abgeschlossen.
- Externer VACS-Export meldet in `external_vacs_export_save_all/run_20260219_141822/summary.json`:
  - `ok = false`
  - `error = vacs_not_ready_after_f4`
  - `assume_vacs_ready_scan.candidates = []`.
- Gleichzeitig zeigt `akabak.driver.summary.json` für `V015`:
  - `vacs_cleanup.after_stage_pids = [1232]`
  - `vacs_cleanup.post_stage.terminated = [1232]`.
- Damit ist die unmittelbare Ursache konsistent: der Exportpfad erwartet eine bereits offene VACS-Instanz (`--assume-vacs-ready`), aber die AKABAK-Stage beendet VACS vorher deterministisch.

#### Preview vs. AKABAK-Mesh (Ursache der optischen Abweichung)
- Preview lief über `C:\Tools\ATH\preview_current.cfg` (UI-Preview), Run über versionierte CFG `P001_B003_V015_8386434c.cfg`.
- Die beiden CFGs sind fachlich nicht identisch:
  - Preview nutzt Fallback-Template `; autogenerated template` (bei `template_cfg = null`).
  - Batch-Run nutzt als effektives Template `C:\Tools\ATH\test.cfg`.
- Zusätzliche Drift im konkreten Fall:
  - Preview zeigt `Slot.Length = 10` (Draft-Wert),
  - Version `V015` lief mit Sweep-Wert `Slot.Length = 9`.
- ATH-stdout bestätigt unterschiedliche effektive Geometrie/Interpretation:
  - Preview: `fixed length: 120 mm`
  - Run V015: `fixed length: 135 mm`.

#### Antwort auf die 4 Fragen
- `1) Einstellungen korrekt übernommen?`
  - In die Run-CFG geschrieben: ja. Effektiv in ATH: teilweise anders wirksam durch anderes Template + Sweep-Versionierung.
- `2) Wer nutzt wirklich Defaults + deine Settings?`
  - Für echten Batchlauf: die versionierte Run-CFG + effektives Run-Template (`test.cfg`) + Sweep-Auflösung pro Version.
  - Für Preview: separater Preview-Pfad mit eigenem Fallback-Template/Minimal-Completion und STL-Flags.
- `3) Warum Darstellung unterschiedlich?`
  - Unterschiedlicher Templatepfad + unterschiedlicher Sweep-Stand + anderer Output-Modus (Preview STL vs. Run ABEC/Mesh).
- `4) Ursache für Absturz?`
  - VACS-Export startet im `assume-vacs-ready`-Modus, findet aber keine laufende/graph-befüllte VACS-Instanz mehr (`vacs_not_ready_after_f4`).

#### Vorschläge (noch ohne Implementierung)
- Export-Handshake vereinheitlichen: Entweder VACS nach AKABAK nicht sofort terminieren, oder Exporter ohne `--assume-vacs-ready` starten (interim/open-flow).
- Preview/Run-Template vereinheitlichen: Preview soll denselben effektiven Template-Resolver verwenden wie Runtime (`test.cfg`/`Tritonia.cfg` Auswahl).
- Preview klar als Draft-Version kennzeichnen: Anzeige, auf welchem Sweep-Punkt die Vorschau basiert (z. B. Draft vs. V015=Slot.Length 9).
- Robustheits-Guard für Run-Status: Wenn VACS-Export fehlschlägt, Run/Version deterministisch auf `vacs_failed/failed` finalisieren (kein `running`-Zombie).

## 2026-02-19
### Update: Incident Analyse `09d793e7-e49d-4bba-960e-809cbaa2e64d` (AKABAK Stop/Restart Loop)
#### Befund (Root Cause)
- Der Fehl-Run trat in `runner_test_workspace/real_runtime_e2e7/P002` auf.
- Nicht ATH/CFG/LE war die Primärursache, sondern ein bereits offener/stale `VACSVIEWER` Prozess.
- In beiden Fehl-Versionen (`V005`, `V006`) zeigt `solve_failure_*.json`:
  - `reason = solve_not_started`
  - `baseline.vacs_pids = [1820]` bereits vor neuem Solve
  - VACS-Fenster `VacsViewer - (new)` war schon vorhanden.
- Dadurch konnte der Start-Detektor keinen neuen Solve-Start eindeutig erkennen; der Lauf lief in Timeout und die Orchestrierung startete die nächste Version.

#### Verifikation der 4 Kernfragen
- `1) Batch-Settings übernommen?`
  - Für Geometrie/Mesh-Overrides: ja (z. B. `Slot.Length=10`, `Mesh.Quadrants=1`, `Mesh.ThroatResolution=5`, `Mesh.MouthResolution=10`, `Length=120` in `P002_B001_V005_09d793e7.cfg`).
- `2) ATH-Skript/CFG korrekt (Defaults + Overrides)?`
  - Ja: Template-Defaults blieben erhalten, Batch-Overrides wurden korrekt appended.
  - ATH-Lauf war erfolgreich (`ath_result.exit_code = 0`), Mesh/ABEC-Artefakte wurden erzeugt und synchronisiert.
  - LE-Binding war intakt (`le_driver_sync.status = ok`, `pre_akabak_le_driving_contract.ok = true`).
- `3) Keine Graph-Exports ausgewählt?`
  - Ja: `sim_export_settings.export_specs = []` (Batch `B001` in diesem Incident).
- `4) Warum bricht Simulation direkt ab?`
  - Technisch nicht "Solver-Crash", sondern Start-Erkennung schlägt fehl, weil stale VACS bereits offen war (`solve_not_started` + Timeout).

#### Fix-Status
- In `app/runtime_orchestrator.py` wurde ein deterministisches VACS-Cleanup vor und nach jedem AKABAK-UI-Stage ergänzt (`VACS_IMAGE_CANDIDATES`, `_list_process_ids_by_image`, `_terminate_process_ids`, `vacs_cleanup`).
- Re-Run derselben Serie nach Fix (`run_id=44063158-e674-4d50-bb49-8b119237e977`) lief für alle Versionen erfolgreich durch.

## 2026-02-18
### Update: Batch UI Corrections A–J (header reset, card reduction, advanced popups)
#### Done
- Replaced per-card text reset rows with header-level reset action icon:
  - reset action now sits in accordion header near chips/status.
  - removed vertical control rows (`Reset overrides in this block` / large `Advanced...`) from expanded cards.
- Batch card density updates:
  - reduced intra-row gaps and increased inter-column spacing in parameter grids.
  - removed extra section labels in mode-heavy cards (Throat Profile / GCurve).
  - mode controller labels normalized to `Mode` in expanded rows.
- Throat Profile behavior:
  - R-OSSE visibility is now controller-driven by `Throat.Profile=R-OSSE` (no advanced toggle dependency).
  - R-OSSE editor rendered as compact two-column inline controls (no extra details frame).
- GCurve behavior:
  - removed explicit card-level advanced toggle; superformula mode now drives advanced parameter visibility.
- Mesh behavior:
  - mesh advanced parameters removed from main card surface and moved to a dedicated advanced dialog.
  - added compact in-card `Advanced` action button to open that dialog.
  - moved `Mesh.InterfaceOffset` into mesh advanced dialog scope.
- Enclosure restructuring:
  - removed Enclosure card from main batch parameter surface.
  - added `Simulate Enclosure` button in Exports section to open enclosure dialog.
- Validation/summary refinements:
  - warning presentation remains in top-right validation card with full warning text retained.
  - error/incomplete counts surfaced in center estimate card.
- Preview/action polish:
  - preview loader roundness increased and slider visuals aligned with dark UI language.
  - batch scrollbars made thinner.

#### Validation
- `python -m compileall app ui`

### Update: Batch UI Follow-up Corrections (layout, validation surfacing, action bar)
#### Done
- Batch segment rows:
  - removed extra per-row headings for wide segmented controls.
  - tightened internal row spacing and increased inter-column gap in sub-block grids.
  - kept segmented controller rows full-width to avoid clipping under 1920x1080.
- Batch validation surfacing:
  - moved warning emphasis into the top-right `Validation` card with dedicated batch styling.
  - warning text keeps full message content (not shortened teaser only).
  - moved `Errors` and `Incomplete` counters into the center `Estimate` card line.
- Batch top summary layout:
  - moved `Version preview · Export specs · Mode` line into the center `Estimate` card (first line under title).
  - removed `Variable Parameters` heading above the parameter area.
  - increased top summary card height and tightened vertical page spacing.
- Batch bottom bar:
  - removed duplicated warning/status messaging from bottom bar.
  - added `Project Manager` button on the bottom-left (moved from status bar).
  - reordered right-side actions to: `Back to Dashboard`, `Save Batch`, `Run Batch`.
  - `Run Batch` now receives a subtle green ready-state when configuration is runnable.
- Batch control styling:
  - adjusted batch combo popup styling and dropdown arrows.
  - adjusted spinner arrow rendering/size for better visibility.
  - rounded preview loader appearance to match batch theme language.
- Preview framing:
  - tightened initial camera distance (roughly 2x closer than previous state).

#### Validation
- `python -m compileall app ui`

### Update: Robustness Hotfixes (STL hook, foreground API, preview/run diagnostics)
#### Done
- Removed deprecated Qt foreground API usage in `app/gui.py`:
  - dropped `QApplication.setActiveWindow(...)` calls from window focus helpers.
- Hardened preview worker diagnostics in `app/gui.py`:
  - preview cancel/start termination failures are now logged (debug), not silently swallowed.
  - startup preview-cache cleanup errors are now logged as warnings.
- Switched STL export hook to deterministic default in `app/services.py`:
  - `ATH_STL_EXPORT_DIRECTIVE` now defaults to `Output.STL = 1`.
  - removed inactive TODO-block fallback insertion for STL export hook.
  - idempotent hook behavior remains intact.
- Improved run-adjacent exception visibility in `app/services.py`:
  - process termination fallback now logs debug/warn details.
  - preview runtime cfg backup/restore/unlink failures now emit warnings.

#### Tests
- `tests/test_service_export.py`
- `tests/test_preview_pipeline.py`
- `tests/test_runtime_orchestrator.py`
- `tests/test_ui_e2e_stress_runs.py`

### Update: Run-Pipeline Integration (per-version cleanup contract + sync gate)
#### Done
- Runtime pipeline (`app/runtime_orchestrator.py`) now creates a dedicated per-version runtime CFG:
  - `<project>/versions/<V>/cfg/<project>_<batch>_<version>_<run8>.cfg`
  - canonical snapshot `cfg/input.cfg` remains for traceability.
- Version state now records run-manifest data:
  - `run_cfg_path`, `ath_export_dir`, parameter/constraint/sweep snapshots.
- Added persistence sync gate for version finalization:
  - if SQL dual-write reports `global_synced=false`, version is marked failed and cleanup is skipped.
- Cleanup policy changed to version-scoped targets only:
  - runtime cfg file cleanup
  - ATH export subfolder cleanup (`<ath_export_root>/<runtime_cfg_stem>`)
  - no destructive broad cleanup.
- CLI run-sample cleanup validation aligned with new artifact model.

#### Tests
- `tests/test_runtime_orchestrator.py` extended:
  - dry-run manifest coverage
  - runtime cfg + ATH export subfolder cleanup coverage.
- Regression:
  - `tests/test_service_export.py`
  - `tests/test_cli_run_sample.py`
  - `tests/test_sql_dataset_store.py`
  - `tests/test_version_resolver.py`
  - `tests/test_project_storage_and_tidy.py`

### Update: Final UI Optimization Pass (Project Manager / Batch / Preview)
#### Done
- Project Manager tile selection polish:
  - removed bright selection fill artifacts by forcing transparent selection highlight and preserving border-only active state.
- Batch top-right validation UX:
  - warning/error snippets now sorted and shown as multi-line teaser.
  - hover tooltip shows extended sorted issue list.
- Batch warning hover helpers:
  - field-level warnings now append structured hover helper text on affected controls (including sweep button).
- Batch layout tuning:
  - batch name width now matches summary-card width.
  - right column ratio updated: larger preview area, reduced export card height.
- Sweep behavior updates:
  - enabled controller sweeps for `Throat.Profile`, `GCurve.Type`, `Morph.TargetShape`.
  - disabled mesh sweeps (`Mesh.*`) for current iteration.
  - added enum-sweep guardrails (only allowed enum boundary values are emitted).
- Preview robustness:
  - controller inference for partial drafts in preview normalization (`Throat.Profile`, `GCurve.Type`, `Morph.TargetShape`) to reduce false OS-SE preview failures when controller is temporarily unset.
- Save/Run usability:
  - Save/Run remain clickable once batch name is set; blocker reasons are communicated via tooltip/dialog instead of silent disablement.
- Startup glitch mitigation:
  - removed splash titlebar dark-mode call (frameless splash).
  - added `CREATE_NO_WINDOW` for doctor/version subprocess calls on Windows to suppress transient console-window flicker.
- Dashboard constraint-card redraw stabilization:
  - avoided unnecessary full grid rebuilds on unchanged width/content to reduce visual blinking.

#### Tests
- `tests/test_batch_page_ui.py`
- `tests/test_project_manager_ui.py`
- `tests/test_preview_pipeline.py`
- `tests/test_batch_export_panel.py`
- `tests/test_gui_project_fixed_keys.py`
- `tests/test_service_export.py`
## 2026-02-17
### Update: Batch Run/Preview Reliability + Enclosure Input Hardening
#### Done
- Run-flow stabilization in `app/gui.py`:
  - Batch `Run` button is now interactable as soon as a batch name is present.
  - Run path no longer forces dashboard navigation before execution.
  - Added guarded exception handling around `run_batch(...)` to avoid silent UI dead-ends.
- Project thumbnail capture implemented from live preview:
  - first run captures preview canvas and stores:
    - `<project_dir>/_meta/project_preview.png`
  - Project Manager tiles now prefer this image over the placeholder tile art.
- Sweep robustness fix:
  - compatibility layer now applies a deterministic numeric fallback when rules return empty `sweepable_keys`.
  - prevents false “all sweep buttons disabled” states in early/incomplete drafts.
- Enclosure formatting and preview resilience:
  - added normalization for `Mesh.Enclosure` list fields (`Spacing`, `FrontResolution`, `BackResolution`) with flexible separators.
  - stock defaults injected for preview stability when needed.
  - plan-mode downgrade for preview STL is made explicit via `preview_notes`.
  - software preview renderer can show enclosure overlay bounds for immediate visual feedback.
- Input UX improvements for enclosure lists:
  - placeholders/hints now match vector-like inputs.
  - parser accepts comma/semicolon/whitespace tokenization.

#### Tests
- `tests/test_batch_page_ui.py`
- `tests/test_preview_pipeline.py`
- `tests/test_batch_validation_alignment_fuzz.py`
- `tests/test_service_export.py`

#### Docs
- Updated `docs/BATCH_UI.md` (auto-preview, thumbnail capture, sweep fallback, enclosure behavior).
- Added `docs/ENCLOSURE_INPUT_UI_RESEARCH_2026-02-17.md` with ATH guide-backed format notes and modern UI references.

### Update: Field Ordering + Numeric Guardrail Research
#### Done
- Introduced shared field display ordering (`field_display_priority`) in `ui/form_schema.py`.
- Applied ordering consistently to:
  - Project form rendering (`ui/form_builder.py`)
  - Batch form rendering (`ui/batch_parameter_form.py`)
  - Mode-page and object-property ordering.
- Added card-internal subgroup clustering on Batch page for better scanability:
  - Basics, Morph, Mesh subgroup buckets.
- Added research doc for modern hard numeric input constraints:
  - `docs/UI_FIELD_ORDERING_AND_NUMERIC_GUARDRAILS_2026-02-17.md`

#### Impact
- Mandatory/high-impact inputs are surfaced earlier in each card.
- Project and Batch now present consistent ordering semantics.
- Numeric guardrail strategy is documented with Qt + accessibility references.

### Update: Contextual Safe-Range Analysis For ATH Experiments
#### Done
- Added context-stratified range extraction:
  - module: `app/contextual_range_analysis.py`
  - CLI: `python -m app ath-experiments contextual-ranges`
- New output artifacts:
  - `reports/ath_experiments/range_suggestions.contextual.v1.json`
  - `reports/ath_experiments/range_suggestions.contextual.v1.md`
- Stratification axes:
  - `profile` (`osse|circarc|rosse`)
  - `gcurve` (`none|se|sf`)
  - `morph` (`off|shape1|shape2`)
  - `enclosure` (`off|on`)
- `UiValidationEngine` now consumes contextual ranges when available and falls back to global ranges otherwise.

#### Impact
- Improves warning precision of safe-range hints without changing ATH compatibility rule semantics.
- Keeps existing range pipeline compatible while enabling context-aware refinement.

### Update: Preview Runtime MeshCmd + Enclosure Tier Integration
#### Done
- Fixed preview ATH runtime mesh command behavior in `app/services.py`:
  - preview now writes a gmsh wrapper command when gmsh.exe is detected
  - resolved repeated `ATH preview run timed out after 90s` caused by bare gmsh invocation mode
- Fixed CFG list serialization in `app/cfg_renderer.py` for ATH object blocks:
  - list values now render as CSV (`a, b, c`) instead of JSON arrays (`[a, b, c]`)
  - critical for object fields like `Mesh.Enclosure.Spacing`
- Integrated enclosure into two-tier completion model:
  - `ath_minimal`: fills `Mesh.Enclosure.Depth` only when enclosure is enabled without `Plan`
  - `policy_minimal`: tracks enclosure requirements via `policy_missing_by_block.enclosure`
    - requires `Mesh.Enclosure.Depth` for pre-defined enclosure mode
    - requires `Mesh.Enclosure.Plan` for plan mode
- Extended Batch default-apply path to merge enclosure defaults (`Mesh.Enclosure.*`) analog to `R-OSSE`.
- Added coverage:
  - `tests/test_preview_pipeline.py` (enclosure seed/policy behavior)
  - `tests/test_m5_planner_renderer.py` (object-list CSV formatting)
  - `tests/test_batch_page_ui.py` (enclosure default merge in UI)

#### Evidence
- Investigation output:
  - `reports/enclosure_investigation/enclosure_dims_20260217T215223Z.json`
  - `reports/enclosure_investigation/enclosure_dims_20260217T215223Z.md`
- In profile-wide preview checks, enclosure variants stayed STL-feasible; preview dimensions remained unchanged in tested setup.

### Update: Two-Tier Preview Minimal Definition (ATH-Minimal vs Policy-Minimal)
#### Done
- Introduced explicit two-tier completion semantics in `app/services.py`:
  - `ath_minimal`:
    - used by STL preview auto-completion only
    - fills only the smallest set needed for robust preview generation
    - keeps undefined values undefined whenever ATH defaults can safely apply
  - `policy_minimal`:
    - non-fatal interpretability layer (for future run-time UX prompts)
    - computes missing recommended keys and corresponding default proposals
- Preview payload now includes:
  - `completion_tier`
  - `policy_missing_keys`
  - `policy_default_values`
- Added service API groundwork for later Run-Batch dialog flow:
  - `OrchestratorService.evaluate_batch_default_policy(...)`
- Reduced preview over-completion behavior:
  - `GCurve.Width` remains the ATH-minimal fallback for guiding-curve runs
  - `GCurve.Dist` is no longer force-added in the minimal tier
  - R-OSSE normalization no longer expands all defaults unless explicitly requested
- Updated tests:
  - `tests/test_preview_pipeline.py` extended for two-tier semantics and policy-gap reporting.

### Update: GCurve Tier Refinement (Superellipse/Superformula)
#### Done
- Refined tier behavior for `GCurve.Type`:
  - `ath_minimal` now applies type-aware defaults for preview robustness:
    - type=1 (Superellipse): `GCurve.Dist`, `GCurve.Width`
    - type=2 (Superformula): `GCurve.Dist`, `GCurve.Width`, `GCurve.SF.*`
  - avoids unstable `GCurve.Dist=0` fallback by using explicit ATH-minimal defaults.
- Refined `policy_minimal` requirement model for GCurve:
  - type=1 requires: `GCurve.Dist`, `GCurve.Width`, `GCurve.AspectRatio`, `GCurve.SE.n`
  - type=2 requires: `GCurve.Dist`, `GCurve.Width`, `GCurve.AspectRatio`, `GCurve.SF.a/b/m1/m2/n1/n2/n3`
  - `GCurve.Rot` remains optional.
- Policy-gap reporting now reflects user-input completeness (not masked by ATH-minimal completion).

### Update: Morph Tier Refinement + Run-Time Default Prompt
#### Done
- Refined `policy_minimal` for morph-on states:
  - when `Morph.TargetShape` is `1` or `2`, policy layer now treats full morph block as required:
    - `Morph.TargetWidth`, `Morph.TargetHeight`, `Morph.CornerRadius`,
      `Morph.FixedPart`, `Morph.Rate`, `Morph.AllowShrinkage`.
- Kept `ath_minimal` morph behavior intentionally lightweight:
  - selecting morph mode alone does not force extra morph keys for preview generation.
- Added run-time policy-default flow in Batch UI:
  - new compact frameless dialog on Run with two main actions:
    - `Show undefined` (highlights unresolved fields in subtle blue)
    - `Use defaults` (applies policy defaults into draft and continues run flow)
  - dialog is styled in the same frameless shell language as advanced/export dialogs.
- Added helper methods in Batch form/page to:
  - persist/clear manual blue highlights,
  - apply default values to currently unset fields.

### Update: Minimal Completion Search Tooling (DB + ATH Oracle)
#### Done
- Added new search module: `app/minimal_completion_search.py`.
  - Models the task as constrained black-box minimization (`minXY > 0` per included card).
  - Generates scenarios for steps 1-6 and optional step-7 combination matrix.
  - Uses `ath_experiments.sqlite` successful runs as seed pool.
  - Supports two modes:
    - DB-observed (fast)
    - ATH-verified greedy minimization (robust STL oracle)
  - Persists summary JSON/Markdown and oracle cache.
- Added CLI command:
  - `python -m app ath-experiments minimal-completion-search`
  - options include `--verify-ath`, `--all-combinations`, `--scenario-filter`, run-group and budget controls.
- Added documentation:
  - `docs/MINIMAL_COMPLETION_SEARCH.md` with model explanation and run commands.
  - Oracle classification clarified: `stl` / `noStl` / `athFail`.
  - ATH-verify now uses unique cfg/export basenames per evaluation for deterministic STL-path attribution.
  - Added adaptive required-field completion before ATH oracle calls (stepwise "rantasten").
  - Added compatibility-vs-ATH alignment counters in summary output.
  - Added CLI option `--mesh-cmd` for explicit MeshCmd override in ATH verify runs.

### Update: Preview Minimal Completion + R-OSSE Normalization
#### Done
- Preview parameter assembly hardened in app/services.py:
  - ignores unset batch values for resolver preview input
  - adds iterative minimal-completion fallback for required parameters (resolver-issue driven, catalog/default based)
  - keeps explicit user inputs unchanged while filling only missing required keys
- R-OSSE preview normalization fixed:
  - internal UI selector Throat.Profile=2 is removed before ATH cfg render
  - R-OSSE object receives safe default completion for missing fields
- Mesh preview normalization added:
  - Mesh.InterfaceOffset / Mesh.InterfaceDraw are normalized to list values
  - list lengths are aligned to Mesh.SubdomainSlices when available
- Preview payload diagnostics extended with auto_completed keys.
- Tests extended/updated:
  - tests/test_preview_pipeline.py now covers R-OSSE normalization and preview payload assembly behavior.

## 2026-02-12
### Done
- Rebuild branch checked (`wut-batcher/rebuild` already active).
- Repository baseline analyzed:
  - Existing sweep planner, CFG renderer, compatibility engine, dataset importer inspected.
  - Current tests executed successfully (`13/13` passing).
- `ARCHITECTURE.md` created with Ist/Soll analysis and backlog.

### Next
- Introduce explicit domain-level `VersionSpec` and central resolver with `single|combined` semantics and `unset` handling.
- Add blocking compatibility validation during resolution.
- Start implementing target project storage layout and deterministic project-wide version IDs.

### Risks / Open Points
- Current snapshot references Runner automation in docs, but no `Runner/` directory exists in repo.
- Real ATH/AKABAK/VACS executable paths and invocation contracts are not yet validated in this workspace.

### Update 1
#### Done
- Added explicit execution-domain models:
  - `VersionSpec`, `ResolutionIssue`, `ResolveVersionsResult` in `app/models.py`.
- Implemented central resolver `app/version_resolver.py`:
  - deterministic version expansion (`single` and `combined`)
  - `unset_parameters` tracking for omitted ATH fields
  - project/batch/version compatibility blocking via `compat_engine`
  - deterministic project-wide version ID allocation with existing-ID carry-forward.
- Added machine-readable compatibility registry support in `app/compat_rules.py`.
- Implemented new target storage layer in `app/project_storage.py`:
  - `projects/<project_id>/...` structure
  - immutable project constraint enforcement
  - batch persistence and version materialization with placeholders/log paths.
- Implemented tidy dataset writer in `app/tidy_dataset.py`:
  - tidy CSV outputs for version parameters, measurements, ATH dimensions
  - schema output
  - optional parquet materialization when `pyarrow` is available
  - project table export (`tables/project_versions.csv`).
- Added high-level planner orchestration `app/batch_orchestrator.py`.
- Extended CLI with `plan materialize` command.
- Added tests:
  - `tests/test_version_resolver.py`
  - `tests/test_project_storage_and_tidy.py`
  - `tests/test_runners.py`
  - `tests/test_compat_rules.py`
- Full suite green: `21/21` tests passing.

#### Next
- Wire ATH runner into the new orchestration path as first concrete runtime step.
- Add ATH stdout dimension extraction into tidy writer flow.
- Add AKABAK/VACS runner staging hooks after ATH step.

#### Risks / Open Points
- Real ATH/AKABAK/VACS invocation flags are not validated yet in this repo snapshot.
- Runner wrappers are subprocess-safe but currently require explicit executable/path contracts from environment.

### Update 2
#### Done
- Added runtime stage orchestrator `app/runtime_orchestrator.py`.
  - Executes staged flow per version (`ATH -> AKABAK -> VACS`) with per-stage status persistence.
  - Renders CFG per version and parses ATH dimensions into tidy dataset rows.
- Extended CLI with `run pipeline` command for staged execution.
- Added runtime test `tests/test_runtime_orchestrator.py` (simulated ATH executable), suite now `22/22` green.

#### Next
- Bind real executable/automation contracts from the VM environment into `run pipeline` invocation.
- Integrate TXT export normalization from runtime stage into tidy measurement writer end-to-end.

#### Risks / Open Points
- AKABAK/VACS stages are currently subprocess wrappers and still need concrete UI-automation or CLI bridge contracts.
- Without real tool paths and flags, runtime behavior beyond ATH simulation remains environment-dependent.

### Update 3 (SQL + GUI Addendum)
#### Done
- Data storage switched to SQL-first architecture:
  - Added `app/sql_dataset_store.py` and made `app/tidy_dataset.py` a SQL-backed alias.
  - Implemented project DB + global DB dual-write with retry queue (`replication_queue`).
  - Implemented required MVP tables:
    - `projects`, `batches`, `versions`, `version_params`, `ath_dimensions`, `graphs`, `graph_points`.
  - Added explicit unset persistence (`version_params.is_set = 0`) and CFG reconstruction helpers.
- Orchestrator integration:
  - `app/batch_orchestrator.py` now registers project/batch/version data into SQL and writes table export from SQL.
  - `app/runtime_orchestrator.py` now updates version status/duration in SQL and writes ATH dimensions directly per version.
- Safe cleanup implementation:
  - Added `app/safe_cleanup.py` with guarded delete rules.
  - Runtime now attempts cleanup only for per-version `ath_work` folders under strict allowlist/deny-path checks.
- Export regeneration from SQL:
  - Added `app/services.py` with core methods:
    - `create_project`, `create_batch`, `resolve_versions`, `run_batch`, `export_version`.
  - Dashboard export path uses SQL parameter states and omits unset params from CFG via `omit_keys`.
- GUI skeleton (PySide6 orchestrator-only):
  - Added `app/gui.py` with splash -> doctor checks -> Project Manager flow.
  - Added main window with hidden stacked work areas (`DASHBOARD`, `PROJECT`, `BATCH`, `RUN`).
  - Added statusbar detail click behavior and About dialog trigger (`WUT BATCHER`).
  - Added Settings dialog backed by persistent config (`app/settings_store.py`).
  - Added CLI command `python -m app gui`.
- CFG renderer extension:
  - Added `omit_keys` support in `app/cfg_renderer.py` for exact unset omission.
- Tests added/updated:
  - `tests/test_sql_dataset_store.py`
  - `tests/test_safe_cleanup.py`
  - `tests/test_service_export.py`
  - Updated SQL expectations in existing storage/runtime tests.
- Full suite status: `28/28` passing.

#### Next
- Bind real VM ATH/AKABAK/VACS invocation details in runtime and GUI settings defaults.
- Integrate real VACS TXT parsing into `graphs` + `graph_points` write path during run.
- Replace STL CFG TODO hook with verified ATH STL export directive.

#### Risks / Open Points
- Exact ATH STL export directive is still unknown; export currently inserts explicit TODO block in CFG.
- AKABAK/VACS runtime stages are subprocess-capable but still depend on concrete environment contracts for production runs.

### Update 4 (UI Theme Addendum)
#### Done
- Added centralized theme token system:
  - `ui/theme_tokens.py` as source of truth for near-black palette, spacing, radii, typography.
- Added robust Qt theming layer:
  - `ui/theme.py` with `build_palette()`, `build_stylesheet()`, `apply_theme()`.
  - Global style uses `Fusion` + dark `QPalette` + targeted QSS.
- Implemented Windows dark titlebar handling:
  - Qt-way env setup before app start (`QT_QPA_PLATFORM=windows:darkmode=1`).
  - Win32 fallback via `DwmSetWindowAttribute` (attribute 20 then 19).
  - Function: `apply_windows_dark_titlebar(window)`; non-Windows no-op.
- Added theme preview window:
  - `ui/theme_preview.py`
  - launch via CLI: `python -m app theme preview`.
- Integrated new theme stack into GUI:
  - `app/gui.py` now uses `apply_theme()` and titlebar dark-mode application for splash, project manager, and main window.
  - Removed direct styling dependency on legacy-only theme implementation.
- Added backward-compat wrapper:
  - `app/gui_theme.py` now proxies new theme API.

#### Validation
- CLI routes:
  - `python -m app --help` includes `theme`
  - `python -m app theme --help` includes `preview`
- Test suite remains green: `28/28`.

#### Risks / Open Points
- Final visual polish (exact spacing/rhythm, panel density) still requires iterative tuning against real screen captures.
- Win32 titlebar behavior can vary by OS build; fallback path is implemented, but should be visually verified on target VM build.

### Update 5 (Continue Pass)
#### Done
- Priority A: SQL dual-write hardened with atomic plan-bundle operation.
  - Added `upsert_plan_bundle` operation in `app/sql_dataset_store.py`.
  - Added `write_plan_bundle(project,batch,versions)` to commit project+batch+versions in one transaction per DB target.
  - `app/batch_orchestrator.py` now uses bundle-write instead of three separate writes.
  - Added global retry sync service API `OrchestratorService.sync_global_db()`.
  - Added CLI command `dataset sync-global` for replaying pending mirror writes.
- Priority B: UI skeleton polish.
  - Applied dark titlebar handling to Settings/About dialogs on show.
  - Project Manager now opens maximized for fullscreen-like workflow.
- Priority C: run-loop cleanup guard hardening.
  - Added `expected_dir_name` guard to `guarded_delete_tree()`.
  - Runtime cleanup now enforces target dir name `ath_work`.

#### Tests / Validation
- Unit tests expanded and green: `31/31`.
  - Added/extended tests for bundle-write, sync summary, and cleanup dir-name guard.
- Smoke test (service/DB without GUI):
  - created sample project + batch
  - verified `project.sqlite`, `global.sqlite`, batch/version artifacts
  - global sync replay ran clean (`processed=0`, `failed=0`).
- GUI smoke note:
  - not executable in current env because `PySide6` is missing (`ModuleNotFoundError`).

#### Open Point
- ATH STL export flag still unknown; TODO hook remains intentionally in code until verified.

### Update 6 (Next Pass: GUI Runtime + VACS SQL + Dry-Run Contracts)
#### Done
- Environment/runtime baseline completed.
  - Verified Python runtime source on VM (`Python312-arm64`, no repo venv, no conda).
  - Added dependency manifest: `requirements.txt` with `PySide6`.
  - Added setup guide: `SETUP.md` (venv, install, app run, tests).
  - GUI smoke validated:
    - `python -c "import PySide6; print(PySide6.__version__)"`
    - GUI controller/theme/titlebar probe completed without crash.
- VACS TXT export integration into SQL implemented.
  - Added parser: `app/vacs_txt_parser.py`.
  - Runtime now executes VACS in version-local exports dir and ingests TXT exports into:
    - `graphs`
    - `graph_points`
  - Parse failures/no export files after successful VACS process now mark version `vacs_failed` to prevent false-success runs.
  - Added fixtures and parser tests:
    - `tests/fixtures/vacs/result_v001spl.txt`
    - `tests/fixtures/vacs/result_v001imp.txt`
    - `tests/test_vacs_txt_parser.py`
  - Added runtime integration test for VACS->SQL write path.
- End-to-end contract hardening (without tool dependency) implemented.
  - Added deterministic runtime `dry_run` mode (`run_batch_pipeline(..., dry_run=True)`).
  - Service `run_batch()` now auto-falls back to dry-run when ATH/AKABAK/VACS executables are not all available.
  - Dry-run still executes resolver/materialization, CFG generation, SQL status writes, and cleanup guard evaluation.
  - Cleanup guard extended with `perform_delete=False` for safe dry-run evaluation.
- Doctor checks upgraded for executable validation.
  - `run_doctor_checks(..., tool_paths=...)` supports explicit settings-driven executable paths.
  - Executable check now enforces existence + file + executable.
  - Splash doctor now runs against configured settings paths.
  - Added doctor unit tests.

#### Validation
- Focused tests:
  - parser/runtime/cleanup/service/doctor: `15/15` passing.
- Full suite:
  - `39/39` passing.
- Deterministic dry-run contract smoke:
  - resolver -> cfg -> sql -> cleanup-guard path executed
  - result reported `dry_run=true` and cleanup reason `dry_run_no_delete`.

#### Open Point
- ATH STL export directive remains unknown; TODO hook intentionally retained in `app/services.py`.

### Milestone
- Milestone: GUI runnable + VACS ingest + dry-run contracts

### Update 7 (Sub-Milestone: Sample E2E Command + Success Status)
#### Done
- Added CLI command: `python -m app run-sample`
  - creates or reuses project/batch and runs a minimal one-version pipeline
  - mode control: `--real` or `--dry-run` (auto-fallback to dry-run if tools are not fully executable)
  - uses settings tool paths (`ath_exe`, `akabak_exe`, `vacs_exe`) as source of truth
  - validates post-run contracts directly against project SQL + runtime summary:
    - `versions.status`
    - `ath_dimensions`
    - `graphs` + `graph_points`
    - guarded cleanup result
    - core artifact paths
  - returns deterministic JSON report and non-zero exit code when checks fail.
- Runtime final success state normalized:
  - final version status is now `success` (instead of `completed`) when all stages pass.
- Added tests:
  - `tests/test_cli_run_sample.py` (dry-run success + real-mode-missing-tools failure path).

#### Validation
- `python -m unittest tests.test_cli_run_sample tests.test_runtime_orchestrator -v` -> passing.
- `python -m app run-sample --library-root .tmp_sample_lib` -> dry-run contract report returned `ok: true`.

### Update 8 (Sub-Milestone: Export Regeneration + UI Wiring)
#### Done
- Export path hardened in `OrchestratorService.export_version()`:
  - CFG regeneration still uses SQL parameter states with explicit unset omission.
  - ABEC export now requires ATH regeneration run and expects generated `.abec` artifact from export workspace.
  - Missing ATH executable for STL/ABEC now fails fast with clear error.
- STL export hook isolated for future patching:
  - single constant `ATH_STL_EXPORT_DIRECTIVE` controls final STL directive injection.
  - until known, deterministic TODO hook remains idempotent.
- Added service API for export UI:
  - `list_versions(project_id, batch_id=None)` reads version rows from project SQL.
- Dashboard UI integration:
  - replaced inline export fields with modal `ExportDialog` (batch/version + STL/ABEC).
  - export errors are surfaced in status bar detail instead of crashing flow.
- Run view and status UX:
  - run page now displays active mode (`real` or `dry-run`).
  - startup doctor status now shows concise failure/warn message with click-through details in status bar.

#### Validation
- `python -m unittest tests.test_service_export tests.test_cli_run_sample -v` -> passing.
- GUI smoke including new export dialog/theme/titlebar path passed.
- Full test suite remains green (`45/45`).

#### Real-Tools Check
- Executed `python -m app run-sample --real`.
- Result: tools unavailable in current settings (`ath_exe`, `akabak_exe`, `vacs_exe` not configured), real run skipped with deterministic error payload.

### Update 9 (Real-Tools Attempt with Provided Paths)
#### Done
- Validated tool executables from provided folders:
  - `C:\Tools\ATH\ath.exe`
  - `C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe`
  - `C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe`
- Stored those paths in user settings and executed:
  - `python -m app run-sample --real --library-root <repo>\\real_tools_library`

#### Result
- Real run reached ATH stage and failed before AKABAK/VACS:
  - stage result: `ath failed`
  - ATH stderr: `ath.cfg: No such file or directory`
- Manual verification in ATH workdir showed ATH then starts but hits mesh invocation issue:
  - `error: gmsh call status = 1`
  - shell parse indicates space-path handling issue for mesh command (`C:\Program ...`)

#### Open Blocker
- Current ATH integration contract is incomplete for this environment:
  - runner must prepare ATH runtime control file expectations (`ath.cfg`) per workdir
  - runner/config must normalize mesh command invocation (gmsh path with spaces) to non-interactive reliable execution
- Until this is implemented, deterministic dry-run remains the reliable validation path in this VM snapshot.

### Update 10 (Compatibility Rules Hardening v1.1)
#### Done
- Fixed semantic inconsistency in guiding-curve rule:
  - `validity_guidingcurve_requires_dist_and_width` now uses fatal requirements (`require(GCurve.Dist)`, `require(GCurve.Width)`) instead of warn action.
- Added in-memory schema migration and normalization:
  - new module `app/compat_schema.py`
  - migrates `ath-geometry-constraints.v1` -> `ath-geometry-constraints.v1.1`
  - adds per-rule fields: `kind`, `applies_to`, `evidence`, optional `verification_plan`
  - enriches runner restrictions with `kind/applies_to/evidence`
  - seeds `semantic_facts` evidence records.
- Added evidence policy wiring:
  - doc-backed evidence for `Length` mandatory and `Source.Contours` override where references exist in knowledge bundle
  - hypotheses with confidence <= 0.5 + verification plans for unbacked facts/rules.
- Added ignored semantics support:
  - new action `note_ignored(key, because)`
  - Source override rule now emits ignored notes for `Source.Shape/Radius/Curv`.
- Reworked DSL evaluation for determinism/security:
  - replaced runtime `eval(...)` execution with restricted AST interpreter
  - explicit unset (`param_states` with `is_set=0`) treated as not defined.
- Updated compatibility export:
  - `app/compat_rules.py` now exports schema 1.1 fields and semantic facts.

#### Tests
- Added:
  - `tests/test_compat_schema.py`
  - extended `tests/test_m2_compat_engine.py`
  - extended `tests/test_compat_rules.py`
- Full suite remains green: `50/50`.

#### Docs
- Added `docs/COMPATIBILITY_SCHEMA.md`.
- Replaced corrupted `docs/Rules.md` with updated rule/evidence/DSL guidance.

### Update 11 (Compatibility Verification + Evidence Completion)
#### Done
- Evidence hardening completed from ATH official docs:
  - semantic facts for `Output.STL`/`Output.ABECProject`, auto subdirectory behavior, and omitted `Source.*` defaults now carry `ath_doc` evidence with `{doc, section, page, quote_hint}` refs.
  - normalization now preserves doc-backed fallback evidence instead of downgrading missing rule evidence to hypothesis.
- Added deterministic compatibility verification harness:
  - new module `app/compat_verification.py` builds minimal CFG cases, executes ATH, checks artifacts/exit behavior, writes JSON report.
  - SQL persistence added via new table `compat_verification_results` in both project/global DB dual-write flow.
  - CLI command added: `python -m app compat verify`.
- DSL engine adversarial hardening:
  - fixed bool semantics so explicit `UNSET` is false in evaluator truthiness.
  - added dedicated adversarial tests in `tests/test_compat_engine_dsl.py` for precedence, negation, dotted/missing keys, escaped warn strings, numeric edge cases, and eval denylist checks.
- Added evidence report:
  - `docs/COMPATIBILITY_EVIDENCE_REPORT.md` generated from normalized schema with rule/fact evidence status and hypothesis coverage.

#### Validation
- Full suite green: `59/59` tests passing.
- Harness tests green with ATH stub and SQL persistence.

#### Open Points
- Most behavior rules are still hypothesis-backed and require either direct ATH doc citation per rule or dedicated executable verification cases to promote confidence.

### Update 12 (Compatibility in Product Reality)
#### Done
- Added central `CompatibilityService` (`app/compatibility_service.py`) to keep UI orchestrator-only:
  - rules-driven `visible_keys`, `locked_keys`, `sweepable_keys`
  - enriched issues with `rule_id`, `severity`, `evidence_type`, inferred `field_key`
  - batch draft evaluation via resolver preview (strict=False)
- UI integration in `app/gui.py`:
  - PROJECT and BATCH pages now render a rules-driven Compatibility panel (visible/locked/sweepable + top issues)
  - locked fields shown as disabled list with tooltip `Locked by runner mode`
  - Save/Run now show a Validation Summary (Top 5 + details) using engine/service issues only
  - fatal issues block save/create; no duplicate validation logic in UI
- CFG emitter/runtime contract hardened:
  - `OrchestratorService.create_batch()` now strips runner-locked keys from user-selected params/sweeps before planning
  - renderer contract unchanged but covered with stronger tests
  - fixed missing `json` import in `cfg_renderer` for list/dict formatting
- Compat regression workflow expanded:
  - `compat verify` now supports modes:
    - `--mode quick` (6 deterministic fast cases)
    - `--mode full` (all defined cases)
  - `--hypothesis-only` to skip doc-backed facts
  - results continue to persist in SQL table `compat_verification_results`

#### Validation
- Full suite green: `63/63`.
- GUI module import smoke passed (`gui_import_ok`).

#### Verify Usage
- Quick run:
  - `python -m app compat verify --mode quick`
- Full run:
  - `python -m app compat verify --mode full`
- Hypothesis-only quick run:
  - `python -m app compat verify --mode quick --hypothesis-only`
- SQL result location:
  - project DB: `<library>/<project_id>/dataset/project.sqlite` table `compat_verification_results`
  - mirrored global DB: `<library>/global.sqlite` table `compat_verification_results`

### Update 13 (UI Automation Contracts: AKABAK + VACS, No Pixel Scanning)
#### Done
- Added UIA contract foundation (no image/pixel matching):
  - `app/ui_contracts/window_signatures.py` with robust signatures (process/class/control/automation_id based, title regex not sole selector)
  - `app/ui_automation/session.py` with `pywinauto` primary backend and `uiautomation` fallback
  - `app/ui_automation/watchdog.py` for modal dialog monitoring, whitelist handling, unknown-dialog debug capture, strict timeouts
- Added deterministic drivers with state-machine style APIs and structured logs:
  - `app/akabak_driver.py`
  - `app/vacs_driver.py`
  - idempotent method contracts and pre/postcondition checks
- Added versioned VACS export recipes:
  - `ui_recipes/vacs/export_spl.txt.json`
  - `ui_recipes/vacs/export_impedance.txt.json`
  - recipe schema validation in `app/ui_automation/recipes.py`
- Added UI inspection CLI commands:
  - `python -m app ui inspect-akabak`
  - `python -m app ui inspect-vacs`
  - outputs written to `ui_maps/` (summary + tree dump artifacts)
- Added documentation:
  - `docs/UI_AUTOMATION_CONTRACTS.md` (update workflow for `ui_maps` + recipes, strict no-pixel policy)

#### Tests
- Added contract tests:
  - `tests/test_ui_automation_contracts.py` (recipes/signatures/inspector dry-run)
- Added optional integration tests (env gated):
  - `tests/test_ui_automation_integration_optional.py` (`WUT_UIA_INTEGRATION=1`)
- Full suite status after changes: `69/69` passing, `2` optional integration tests skipped by default.

### Update 14 (SQL Graph Schema Upgrade for Polar/Series Data)
#### Done
- Upgraded SQL dataset schema to `2.2` with series-aware model:
  - added `graph_series(series_id, graph_id, series_kind, angle_deg, label, meta_json, created_at)`
  - upgraded `graph_points` to `series_id` foreign key + optional `y_imag`
  - extended `graphs` with semantic columns (`graph_kind`, `x_axis`, `y_axis`, `meta_json`) while keeping legacy fields for compatibility
- Added in-place migration logic for legacy DBs:
  - detects old `graph_points(graph_id, ...)`
  - creates default per-graph series rows
  - migrates points losslessly to new schema
- Added performance indices:
  - `idx_graph_points_series_x (series_id, x_value)`
  - `idx_graph_series_graph_angle (graph_id, angle_deg)`
  - `idx_graphs_version_kind (version_id, graph_kind)`
- Updated CLI row counting to join `graph_points -> graph_series -> graphs` for version-scoped checks.

#### Tests
- Added migration regression test:
  - `tests/test_sql_dataset_store.py::test_migrates_legacy_graph_points_schema_to_series_model`
- Extended storage smoke assertions with `graph_series` row counts.

### Update 15 (VACS Polar/Complex TXT Ingestion)
#### Done
- Extended `app/vacs_txt_parser.py` from flat point parsing to series-aware parsing:
  - new model: `VacsGraph -> VacsSeries[] -> VacsSeriesPoint[]`
  - supports per-series markers (e.g. `Series=Angle:30`)
  - extracts `angle_deg` for polar slices
  - parses optional third numeric column into `y_imag` for complex-valued exports
- Updated runtime ingestion (`app/runtime_orchestrator.py`) to write:
  - graph metadata to `graphs`
  - per-angle/per-curve rows to `graph_series`
  - point data with optional imaginary part to `graph_points`
  - includes `meta_json/export_meta` persistence for reproducible provenance.

#### Tests
- Added fixtures:
  - `tests/fixtures/vacs/result_v001polar.txt` (3 angles x 5 freqs)
  - `tests/fixtures/vacs/result_v001polar_complex.txt` (complex samples)
- Added parser coverage:
  - `tests/test_vacs_txt_parser.py` polar + complex parsing assertions
- Added run-loop integration coverage:
  - `tests/test_runtime_orchestrator.py::test_pipeline_ingests_polar_series_into_sql`

### Update 16 (Run Governance + Cleanup Test Data)
#### Done
- Added run-tracking foundation in SQL schema (`2.3`):
  - `runs` lifecycle table with pin/tag and metadata (`git_commit`, `app_version`, `settings_hash`, `error_summary`)
  - `run_versions` table for per-version status per run
  - `versions.version_config_hash` (SHA-256 over canonical effective params with unset semantics)
  - `graphs.run_id` + uniqueness constraints for anti-duplicate behavior inside a run
  - `graph_series` uniqueness constraints (graph/angle/label)
- Runtime now creates a `run_id` per execution and writes lifecycle updates (`running` -> `succeeded|failed`).
- Output rows are tied to runs:
  - `graphs` include `run_id`
  - `ath_dimensions` migrated to `(run_id, version_id)` identity
- Added helper queries/services:
  - latest succeeded run per version (`latest_successful_run_per_version`)
  - run listing (`list_runs`)
  - default service version listing now prefers latest succeeded run data.

#### Cleanup / Pinning
- CLI added:
  - `runs pin <run_id> [--project-id] [--tag]`
  - `runs unpin <run_id> [--project-id]`
  - `runs cleanup-testdata [--project-id] [--delete-exports] [--dry-run]`
- Cleanup deletes only unpinned runs and dependent rows, optionally deletes run-linked export files (inside project root only), and writes audit logs:
  - `<project>/logs/cleanup_<timestamp>.json`

#### GUI
- Dashboard additions:
  - `Runs verwalten...` dialog (pin/unpin)
  - `Testdaten aufraeumen...` dialog (preview, delete-exports toggle, `DELETE` confirmation)
- Pin button tooltip:
  - `Markiert einen Run als Ergebnis, das behalten werden soll.`

#### Tests
- Added:
  - `tests/test_runs_governance.py`
  - `tests/test_cli_runs_tools.py`
- Extended:
  - `tests/test_runtime_orchestrator.py`
  - `tests/test_sql_dataset_store.py`
- Full suite green: `83/83` passing, `2` optional integration tests skipped.

### Update 17 (PROJECT Form UX Finalization)
#### Done
- PROJECT page cleaned up for constraints-only workflow:
  - removed `Project Compatibility` panel from PROJECT view
  - removed `Back to Dashboard` and PROJECT-side `Show details` actions
  - PROJECT creation no longer blocks on compatibility `fatal` draft issues
- Form widgets upgraded to nullable, unset-safe controls:
  - new `NullableNumericInput` with empty-as-unset semantics and comma-decimal normalization
  - new nullable enum/bool/text controls with explicit clear behavior
  - per-field `Set` checkboxes removed across form fields
  - `Mesh.Enclosure` remains the only object toggle (`Enable Enclosure`)
- Layout and style polish:
  - unified compact numeric input widths
  - transparent label backgrounds (no dark text boxes)
  - improved segmented-mode selected state styling (checked/hover/pressed)
  - status bar adjusted as a single bottom line with left status and right brand label

#### Tests
- Updated/extended GUI contract tests:
  - `tests/test_project_form_ui.py`
  - covers nullable numeric mapping, ruleset-driven visibility switching, unset serialization, and PROJECT page button/panel cleanup

### Update 18 (PROJECT Layout/Selection Corrections)
#### Done
- PROJECT form layout switched to two columns (`Geometry | Mesh`) with separate scroll containers to reduce vertical scroll pressure.
- Geometry/Mesh card ordering fixed:
  - Geometry: `Basics -> Throat Profile -> Morph -> GCurve -> Rollback`
  - Mesh: `Core -> Enclosure`
- Removed `Source.*` and `OSSE` object block from PROJECT UI to avoid duplicated/conflicting parameter presentation.
- Selection controls refactored:
  - removed extra `x` clear buttons
  - segmented controls now clear on second click of the active option
- `Mesh.Enclosure` changed from checkbox to segmented `disabled/enabled`; detail fields hide and unset when disabled.
- `Rollback` changed to segmented `disabled/enabled`; `Rollback.Angle/Exp/StartAt` now use contextual disclosure and are unset when disabled.
- Input UX fixes:
  - ensured `optional` is placeholder only (not literal field text)
  - validated numeric entry remains editable
  - unified input widths with and without units using fixed total-width input rows.

#### Tests
- Expanded `tests/test_project_form_ui.py` with coverage for:
  - two-column layout presence
  - required geometry/mesh card order
  - source removal + single `R-OSSE` presence
  - segment second-click clear behavior
  - placeholder/editability regression guard
  - absence of `x` clear buttons in selection controls

### Update 19 (PROJECT Input Stability + Context UX Polish)
#### Done
- Fixed nullable numeric validator patterns so digits are accepted while placeholder text is visible.
  - `optional` remains placeholder-only; empty text now consistently maps to `unset`.
  - numeric parsing still normalizes locale decimal comma to dot on serialization.
- Added centralized hint helpers (`ui/hints.py`) and wired schema placeholders/tooltips through them.
  - numeric placeholders simplified to `optional`
  - list placeholders standardized to `e.g. 1,2,3`
  - expression placeholders use short examples (or fallback example) instead of long inline prose
- GCurve mode UX updated to three explicit options:
  - `no GCurve` -> `GCurve.Type` unset (explicit coverage mode)
  - `Superellipse` -> `GCurve.Type = 1`
  - `Superformula` -> `GCurve.Type = 2`
- Introduced reusable inset `ContextFrame` styling/component and applied it to conditional sections:
  - `R-OSSE` mode details
  - Morph details (shown only when `Morph.TargetShape != 0`)
  - Rollback details (shown only when rollback enabled)
  - GCurve common/mode details
  - Enclosure object details
- Converted bool control presentation to segmented optional controls (`off/on`) for PROJECT consistency.
  - includes `Morph.AllowShrinkage` (no checkbox look)
- Reduced control widths and grid spacing; disabled horizontal scrollbars on both PROJECT columns to prevent sideways scrolling.

#### Tests
- Extended `tests/test_project_form_ui.py` with:
  - horizontal scrollbar policy checks
  - GCurve three-option mode + unset payload check
  - Morph contextual frame disclosure + segmented bool control assertion
  - context-frame presence assertion
- Regression suite status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 20 (PROJECT Visual Polish + Layout Cleanup)
#### Done
- Removed nested dark overlay artifacts in PROJECT subblocks:
  - switched generic `QWidget` background styling to transparent
  - kept tone/border responsibility on explicit containers (`QGroupBox`, `ContextFrame`)
  - refined `ContextFrame` to a subtle inset style (no heavy dark fill)
- Reduced clipping risk and tightened layout spacing:
  - removed rigid grid minimum-width constraints
  - reduced sub-grid margins/spacing and slightly tightened control widths
  - kept horizontal scrollbars disabled in both PROJECT columns
- Throat mode sections polished:
  - ensured mode page headers resolve to `OS-SE` and `Circular Arc`
  - removed extra nested R-OSSE mode wrapper; R-OSSE now shows a single inset `Details` frame below selector
- Mesh/Core alignment cleanup:
  - custom core renderer with one aligned control column
  - selection controls (`Mesh.Quadrants`, `Mesh.RearShape`) and following inputs share the same left control anchor

#### Tests
- Extended `tests/test_project_form_ui.py`:
  - verifies throat page headers (`OS-SE`, `Circular Arc`) and absence of extra `R-OSSE` mode header frame
- Regression status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 21 (PROJECT Form Metrics + Unit/Placeholder Alignment)
#### Done
- Introduced centralized form layout metrics in `ui/form_metrics.py`:
  - shared label width, input width, label->input gap, column gap, row gap, and margins
  - reusable grid configurators for single-column control rows and two-column form rows
- Restored two-column subforms where regressions occurred:
  - `Mesh/Core` now uses selection rows on top + two-column form grid below
  - left control anchor stays aligned between selection rows and form rows
  - `GCurve Common` and mode-specific pages (including Superformula) render as two-column grids again
- Removed redundant Enclosure inner row label (`Mesh Enclosure`) by rendering object editor directly under `Enclosure` group title.
- Placeholder/text alignment normalization:
  - numeric and text inputs are explicitly left-aligned
  - `optional` now aligns consistently with all other placeholders
- Unit handling polish:
  - expression/list text inputs now support inline unit suffix labels (fixes missing unit on `Slot.Length`)
  - half-angle unit overrides applied where documentation confirms half-angle semantics:
    - `Throat.Angle`, `Throat.Ext.Angle`, `Coverage.Angle` -> `deg/2`
    - `R-OSSE.a0`, `R-OSSE.a` -> `deg/2`

#### Tests
- Expanded `tests/test_project_form_ui.py` coverage for:
  - Mesh/Core two-column structure and control-anchor alignment
  - removal of redundant Enclosure label
  - Slot.Length unit visibility (`mm`)
  - half-angle unit overrides
  - placeholder left alignment
  - two-column rendering for GCurve Common/Superformula
- Regression status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 22 (PROJECT Layout Corrections Follow-up)
#### Done
- Geometry/Mesh top sections switched from collapsible toggles to static section headers.
- `Projekt erstellen` action moved to the lower-right side of PROJECT page.
- Input width/spacing pass:
  - reduced input width further and unified widths across fields with and without unit suffix
  - reserved a fixed suffix slot in text/numeric inputs so visual input width is consistent
  - tightened global label->input gap to match Mesh/Core horizontal rhythm
- Mesh/Core adjusted:
  - kept selection rows on top
  - balanced two-column form body by splitting remaining fields across left/right columns
- GCurve mode UX:
  - hidden empty `Common` frame when `GCurve.Type` is unset (`no GCurve`)
  - mode page stack switched to auto-sizing widget to avoid oversized blank vertical space for smaller pages
- Unit display parity:
  - `deg/2` now visibly renders in input suffix for half-angle fields
  - Slot expression units remain shown via suffix slot (`Slot.Length -> mm`)

#### Tests
- Expanded `tests/test_project_form_ui.py` for:
  - non-collapsible Geometry/Mesh headers
  - right-aligned create button in PROJECT page
  - uniform input widths (with/without unit)
  - hidden GCurve `Common` frame in `no GCurve` mode
  - balanced Mesh/Core two-column labels
  - explicit `deg/2` suffix visibility checks
- Regression status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 23 (PROJECT Fine Tuning: Anchoring, Header Cleanup, Unit Clipping)
#### Done
- Responsive layout behavior adjusted:
  - inner form column gaps remain fixed while window growth now increases outer spacing (column-to-column spacing and section content margins).
  - group blocks are width-capped and left/top anchored to avoid internal horizontal drift.
- Mesh/Core refinement:
  - right-column trailing blank row removed by rebalancing left/right field assignment.
- Dynamic height/anchoring improvements:
  - mode stacks (`Throat Profile`, `GCurve`) use auto-sizing pages and top-anchored container layouts.
  - page switching now updates stack/group geometry immediately.
  - `Throat.Profile` now has an explicit unset page (no OS-SE page shown when profile is cleared).
- Header visual cleanup:
  - context headings switched to `ContextTitle` (bold, transparent background).
  - group-box title styling forced transparent and bold to remove remaining dark header artifacts.
- Unit suffix clipping fix:
  - increased reserved unit suffix width so `deg/2` renders fully without clipping.

#### Tests
- `tests/test_project_form_ui.py` extended and updated for:
  - `Throat.Profile` unset hides OS-SE page content
  - `deg/2` suffix visibility assertions
  - Mesh/Core balanced two-column counts
  - non-collapsible section headers and create-button alignment regression guards remain green
- Regression status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 24 (PROJECT Follow-up Corrections)
#### Done
- Header styling scope corrected:
  - block titles (`QGroupBox::title`) remain bold
  - inner/context titles switched back to non-bold style (`ContextTitle`) to avoid emphasizing under-block labels
- Mesh/Core column count normalized:
  - moved `Mesh.InterfaceOffset` to `Enclosure` group mapping
  - Core body now renders `6/6` label rows consistently
- Mode block sizing refined:
  - mode stacks now apply fixed current-page height on switch for deterministic vertical shrink/grow
  - keeps Throat/GCurve block height synced to active subblock state
- Width behavior tightened:
  - block group width fixed to a shared form width hint
  - prevents inner-column spacing drift while window grows (extra room is absorbed by outer margins/gaps)

#### Tests
- `tests.test_project_form_ui`: passing
- compatibility/storage/runtime targeted suites: passing

### Update 25 (PROJECT Alignment + Coverage Move + Fullscreen Open)
#### Done
- Main workflow window now opens in fullscreen when creating/opening a project from Project Manager.
- PROJECT header alignment pass:
  - increased left margin for page title area
  - project-name input moved into a two-column top grid and fixed to geometry block width
  - create button placed in mirrored right-column container so it aligns to mesh block right edge while keeping bottom row position
- Geometry/Mesh section headers now inherit the same horizontal inset as their block stacks, keeping headings left-aligned with block edges.
- `Coverage.Angle` moved out of `no GCurve` mode page into `Basics`:
  - `no GCurve` subblock removed (empty page)
  - `Coverage.Angle` shown only when `GCurve.Type` is unset
  - `Coverage.Angle` hidden/unset when a guiding-curve mode is selected
- Mode layout behavior refined:
  - fixed-width group boxes to keep horizontal width constant across mode changes
  - vertical size still follows active subblock/page height

#### Tests
- Extended `tests/test_project_form_ui.py` with:
  - coverage-angle visibility behavior in basics vs gcurve mode
  - absence of `no GCurve` context heading block
  - updated project-button alignment assertion for new grid layout
- Regression status:
  - `tests.test_project_form_ui`: passing
  - compatibility/storage/runtime targeted suites: passing

### Update 26 (PROJECT Window Controls + Placeholder 0 + Scrollbar Polish)
#### Done
- Replaced PROJECT main-window open mode from true fullscreen to native maximized window mode:
  - keeps standard Windows titlebar controls (minimize / maximize / close) available
  - applied consistently for both "open existing project" and "new project"
- Unified PROJECT form placeholders for editable text-based controls to `0`:
  - numeric, expression, list and text inputs now all show `0` when unset/empty
  - placeholder remains visual-only; unset semantics stay unchanged (`is_set=0`, value `NULL`)
- Added dedicated PROJECT column scroll-area styling (`Geometry` and `Mesh`) for cleaner dark UI:
  - transparent track, slimmer handle, rounded thumb, no arrow buttons
  - keeps horizontal scrolling disabled as before

#### Tests
- `python -m unittest tests.test_project_form_ui -v` (all passing)

### Update 27 (PROJECT Segments: Forced No/Disabled Fallbacks)
#### Done
- Added field-specific segmented-control fallback behavior for PROJECT mode selectors:
  - `Morph.TargetShape`: defaults to `no morph` and cannot end in unselected state.
  - `GCurve.Type`: defaults to `no GCurve` and cannot end in unselected state.
  - `Rollback`: defaults to `disabled` and cannot end in unselected state.
  - `Mesh.Enclosure` toggle: defaults to `disabled` and cannot end in unselected state.
- Re-click behavior updated for these controls:
  - when a non-default option is clicked again, selection now returns automatically to the fallback (`no...` / `disabled`).
  - clicking the fallback itself no longer clears to empty for these controls.
- Kept existing clear-to-unset behavior for unrelated segmented controls (e.g. `Throat.Profile`) unchanged.

#### Tests
- `python -m unittest tests.test_project_form_ui -v` (30 tests passing)

### Update 28 (PROJECT Page ATH Pipeline Test Harness)
#### Done
- Added isolated real-run harness for PROJECT-page constraints:
  - new module `app/projectpage_ath_test.py`
  - uses PROJECT form schema + `ParameterForm` + `CompatibilityService` to build the same constraints draft structure as UI
  - resolves one version via existing resolver path (`resolve_versions`) and renders CFG via existing renderer (`render_cfg_text`)
  - writes CFGs to `C:\Tools\ATH\ProjectPageATHTestN.cfg`
  - runs ATH real via `AthRunner`, writes runtime `ath.cfg`, detects newest export folder in `C:\Horns`
  - parses generated CFG and exported `config`/`config.txt`, compares against expected UI-set values (+ allowed mandatory globals), reports missing/extra/mismatch keys
  - writes per-run JSON reports and suite summary to `reports/projectpage_ath_test/`
- Added CLI entrypoint:
  - `python -m app projectpage-ath-test`
  - options: `--ath-exe`, `--template-cfg`, `--cfg-dir`, `--export-root`, `--reports-root`, `--count`
- Added parser/compare unit tests:
  - `tests/test_projectpage_ath_test.py`

#### Tests
- `python -m py_compile app/projectpage_ath_test.py app/cli.py tests/test_projectpage_ath_test.py`
- `python -m unittest tests.test_projectpage_ath_test -v`

### Update 29 (Rollback Off + Mesh Mapping + R-OSSE Normalization)
#### Done
- Rollback disabled for current ATH mode:
  - PROJECT form schema omits `Rollback*` fields.
  - PROJECT page shows explicit notice: `Rollback is not supported in this ATH version. Use R-OSSE profile instead.`
  - ruleset replaced rollback visibility toggle logic with:
    - permanent rollback hide rule
    - fatal validity rule when rollback is explicitly enabled.
- Resolver now carries PROJECT mesh `limits` into resolved version parameters, so `Mesh.*` set on PROJECT can be rendered into CFG.
- CFG renderer now emits object parameters as ATH blocks, including deterministic `R-OSSE = { ... }` serialization order.
- ATH config parser and comparison normalization improved:
  - supports empty object assignment patterns (`R-OSSE =` followed by member lines),
  - compares with optional-missing prefixes (currently `Mesh.*` in exported config),
  - separates `extra_keys_defaulted` from `extra_keys_ghost` in reports.
- ATH harness suite adjusted to 6 rollback-free autonomous cases with conservative geometry.

#### Tests
- `python -m unittest tests.test_project_form_ui tests.test_m2_compat_engine -v`
- `python -m unittest tests.test_version_resolver -v`
- `python -m unittest tests.test_m5_planner_renderer tests.test_projectpage_ath_test -v`

### Update 30 (PROJECT ATH Experiment Harness v1)
#### Done
- Added large-scale experiment harness:
  - `app/projectpage_ath_experiment.py`
  - CLI command: `python -m app projectpage-ath-experiment`
  - deterministic seeded generation with safe/exploratory mix (`70/30` target).
- Harness uses the existing PROJECT UI data path only:
  - `ParameterForm -> CompatibilityService -> resolve_versions -> render_cfg_text -> ATH`.
- Added persistent experiment dataset:
  - SQLite at `reports/ath_experiments/ath_experiments.sqlite`
  - tables: `experiment_runs`, `experiment_params`, `experiment_metrics`, `experiment_compare`
  - indexes on status/error/keys/numeric dimensions.
- Added ATH stdout/stderr parsing and classification:
  - parses final width/height/length and average mesh throat angle
  - normalizes units (`m` -> `mm`)
  - classifies known error patterns and warning counts
  - applies dimension thresholds (`max-dim` warn, `hard-cap` fail).
- Added report outputs:
  - per-run JSON: `reports/ath_experiments/cases/run_XXXX/report.json`
  - copied raw logs: `reports/ath_experiments/logs/run_XXXX_stdout.txt|stderr.txt`
  - aggregate outputs:
    - `reports/ath_experiments/summary.json`
    - `reports/ath_experiments/summary.md`
    - `reports/ath_experiments/range_suggestions.v1.json`
- Added compatibility experiment documentation and machine-readable draft rule skeleton:
  - `docs/COMPATIBILITY_EXPERIMENT_NOTES.md`
  - `app/knowledge/ath/experimental_rules.v1.json`

#### Tests
- `python -m py_compile app/projectpage_ath_experiment.py app/cli.py`
- `python -m unittest tests.test_projectpage_ath_experiment tests.test_projectpage_ath_test -v`

### Update 31 (PROJECT UI Risk States + Hover Helper Refinement)
#### Done
- Unified PROJECT field-risk pipeline integrated in UI:
  - source merge from normative compatibility issues + experiment hints (`range_suggestions`, `compat_rule_candidates`)
  - deterministic per-field merge policy: `fatal > warn > ok > neutral`.
- Added debounced live-validation update path for PROJECT draft changes.
- Added persistent `fieldState` styling hooks:
  - input-level outlines for `ok` (green), `warn` (amber), `fatal` (red), `neutral`.
  - existing green "conform" state preserved.
- Reworked helper behavior to avoid layout jumps:
  - removed inline per-field helper lines that changed row height
  - kept compact field badges (`!` / `x`) next to inputs
  - introduced hover helper popup with severity styling and placement by column side.
- Helper text normalization:
  - clean English output (no "Experiment..." prefix)
  - display-only decimal formatting to 2 places in helper popup.
- Numeric input normalization:
  - decimal comma is normalized to decimal dot in numeric editors (`123,45 -> 123.45`)
  - matches ATH/CFG decimal notation expectations.

#### Notes
- Compatibility semantics/rules were not changed in this pass.
- Only UI presentation and interaction around existing issue outputs were changed.

#### Tests
- `python -m unittest tests.test_ui_validation_ranges tests.test_ui_validation_candidates -v`
- `python -m unittest tests.test_project_form_ui -v`

### Update 32 (PROJECT Accordion Redesign: Header Row, Chips, Section Status)
#### Done
- Replaced minimal accordion header with full row-item header component:
  - title + summary chips (collapsed state) + status badge + chevron
  - full-row click target + keyboard toggle (`Enter` / `Space`) support.
- Kept per-column exclusive expand behavior:
  - opening one section collapses others in the same column
  - values remain preserved while sections collapse.
- Added section-level status aggregation from existing field issues:
  - counts per section (`ok/warn/fatal`)
  - fatal dominance for section badge (`x n`), warn badge (`! n`)
  - summary chips clipped to max 3 with `+N` overflow indicator.
- Styling refinement for calmer hierarchy:
  - section severity emphasis moved primarily to header accent/badge
  - expanded section frame uses subtle warn/fatal tone (no loud full-block warning style).
- Vertical rhythm/spacing pass:
  - more top space between project-name row and column headers
  - larger, more intentional header rows to reduce "thin/unfinished" appearance.

#### Tests
- Extended `tests/test_project_form_ui.py` with:
  - accordion collapse behavior + value persistence assertions
  - section-level warning/fatal badge dominance assertions
  - collapsed-chip overflow (`+N`) assertions
- Regression status:
  - `tests.test_project_form_ui`: passing
  - `tests.test_ui_validation_ranges`: passing
  - `tests.test_ui_validation_candidates`: passing

### Update 33 (PROJECT Action Bar + Summary Panel + Tooltip Accent Styling)
#### Done
- Added a sticky PROJECT action bar above the global `QStatusBar`:
  - left: status pill (`Ready to create`, `Warnings: n`, `Fix errors: n`, `Checking constraints...`, `Creating project...`, `Constraints locked for this project`)
  - optional hint text and `View issues` action when warnings/errors exist
  - right: primary CTA moved to `Create Project`.
- Clarified status responsibilities:
  - action bar now owns user-facing draft state on Project Page
  - bottom `QStatusBar` remains for technical/transient messages.
- Added compact summary/info panel under project name:
  - explains constraint locking after creation
  - shows `Errors: n • Warnings: n`
  - shows mode chips (Throat/Morph/GCurve/Enclosure) for quick context.
- Improved collapsed-state density:
  - reduced geometry/mesh column gap
  - aligned project-name row with the left column grid for cleaner rhythm.
- Updated helper popup styling to reduce visual noise:
  - removed heavy warning border look
  - neutral popup border + severity accent strip.

#### Tests
- `python -m unittest tests.test_project_form_ui -v`
- `python -m unittest tests.test_ui_validation_ranges tests.test_ui_validation_candidates -v`

### Update 34 (PROJECT Responsive UX + Deterministic Issues Navigation)
#### Done
- Added responsive baseline for PROJECT columns:
  - switched form columns to `QSplitter` with per-column internal scrolling
  - kept bottom action area visible while columns resize
  - set main window minimum size (`1120x760`) to avoid unusable cramped states.
- Improved PROJECT top layout alignment and rhythm:
  - aligned `Project Name` row with left content column
  - adjusted top spacing so title/name/summary card read as a structured header area.
- Reduced visual density issues in section content:
  - mesh/core grid spacing increased (especially label-input rhythm in right-side fields)
  - field labels switched to single-line with tooltip fallback to avoid wrapped labels pushing rows unpredictably.
- Introduced deterministic UI issue model (presentation-only, no compat semantic changes):
  - new `app/project_issue_model.py` classifies issues into `error`, `warn`, `incomplete`
  - fatal "required missing" on unset fields now shown as `incomplete` (neutral) instead of immediate red error state
  - stable ordering: errors -> warnings -> incomplete.
- Reworked `View issues` behavior:
  - added on-page `ProjectIssuesPanel` listing all issues grouped by severity
  - clicking an issue opens the correct accordion section, scrolls to the field, focuses it, and applies a short subtle flash.
- Refined action bar behavior (not a second status bar):
  - compact issue counts (`errors · warnings · incomplete`)
  - concise state copy for ready/incomplete/warn/error/creating/locked/validating
  - create button disabled for `error` or `incomplete` with explicit tooltip reason.
- Accordion section state chips/badges now communicate progress:
  - `unset`, `ok`, `warn`, `fatal`, `incomplete` states represented via subtle tokenized badge/chip styling.

#### Manual QA Checklist
- Fullscreen:
  - two-column layout remains stable, action bar visible above OS status bar
  - section badges/chips update with field changes.
- Restore-down window:
  - no global page collapse; column scrolling stays inside Geometry/Mesh columns
  - bottom action bar remains visible and usable.
- Issues navigation:
  - `View issues` shows full grouped list (no random single issue)
  - clicking list item expands target accordion and focuses target field.
- Create CTA:
  - disabled for errors and incomplete required fields
  - enabled when only warnings are present.

#### Tests
- `python -m unittest tests.test_project_issue_model tests.test_project_form_ui tests.test_ui_validation_ranges tests.test_ui_validation_candidates -v`
- `python -m py_compile app/gui.py ui/form_builder.py ui/theme.py app/project_issue_model.py`

### Update 35 (PROJECT Layout Cleanup: No Splitter Handle + In-Card Issues Popover)
#### Done
- Removed draggable middle column splitter behavior on Project Page:
  - replaced splitter-based column container with fixed-gap two-column `QHBoxLayout`
  - both Geometry and Mesh columns are now `QSizePolicy.Expanding`
  - fixed inter-column spacing keeps the center gap stable (no giant middle void).
- Moved "View issues" into the top summary card (right side of card header):
  - clicking opens an anchored popup issues viewer (`Qt.Popup`) instead of adding a new page area
  - popup lists all issues grouped and ordered by severity (Errors, Warnings, Incomplete)
  - selecting an issue expands the right accordion section, scrolls to the field, and focuses it.
- Corrected fresh-start mode defaults:
  - `Throat.Profile` now starts unset (no implicit OS-SE preselection).
- Added smooth accordion expand/collapse animation:
  - body height animation (`OutCubic`, ~180ms)
  - subtle opacity fade for smoother perceived transitions.
- Reduced expanded-section density without redesign:
  - tighter inner margins/row spacing in section bodies
  - non-wrapping labels with tooltip fallback to avoid multi-line label drift
  - mesh core horizontal spacing tuned to avoid label/input crowding in right column.
- Updated minimum baseline for no-scroll target:
  - main window minimum size now `1280x800` for Project Page usability baseline.

#### Manual QA Checklist
- Fullscreen:
  - no draggable handle between Geometry and Mesh columns
  - top summary card keeps "View issues" button inline; opening issues does not change page height
  - accordion transitions are smooth (no hard snap).
- Restore-down:
  - columns remain readable with fixed middle gap
  - action bar remains visible and usable.
- Issue navigation:
  - popup shows deterministic grouped list (no random single issue)
  - clicking issue opens section and focuses target field.
- Defaults:
  - fresh project starts with `Throat Profile = unset` (no OS-SE preselected).

#### Tests
- `python -m unittest tests.test_project_issue_model tests.test_project_form_ui tests.test_ui_validation_ranges tests.test_ui_validation_candidates -v`
- `python -m py_compile app/gui.py ui/form_builder.py ui/form_metrics.py ui/theme.py app/project_issue_model.py`

### Update 36 (PROJECT Dense Top Area + Embedded In-Card Issues + Compact Superformula Grid)
#### Done
- Freed top vertical space:
  - removed redundant top-panel `Errors/Warnings/Incomplete` line (counts remain in sticky bottom bar only)
  - removed standalone `Project Name` caption row label; input now uses placeholder + tooltip.
- Reworked top chips into a strict single-line strip:
  - chips do not wrap
  - overflow collapsed as `+N`.
- Replaced issues overlay behavior with embedded in-card issues viewer:
  - top info card now has internal left/right structure
  - right side hosts toggleable embedded issues panel with internal scrolling
  - toggle animation uses `QPropertyAnimation` (`OutCubic`, ~190ms) on width/opacity
  - card height remains fixed while issues view opens/closes.
- Reduced Geometry/Mesh middle gap:
  - constant non-stretch spacing reduced to a compact range.
- Reduced left-column expanded height pressure:
  - introduced responsive compact grid for `GCurve -> Superformula` fields
  - uses 3 columns when width allows, falls back to 2 columns on narrow width.

#### Tests
- `python -m unittest tests.test_project_form_ui tests.test_project_issue_model tests.test_ui_validation_ranges tests.test_ui_validation_candidates -v`
- `python -m py_compile app/gui.py ui/form_builder.py ui/theme.py ui/form_metrics.py tests/test_project_form_ui.py`

### Update 37 (Pre-Change Verification Checklist for Compact Project Page Pass)
#### Current State Check (before implementation)
- Requirement 1 (Issues subsection inside top InfoBar, header-toggle only): **Not implemented**
  - Current state: top InfoBar uses a separate `View issues` / `Hide issues` button and an embedded panel area, but no subsection-style header row with chevron toggle semantics.
- Requirement 2 (3-column input layout for all LEFT subsections): **Partially implemented**
  - Current state: only `GCurve -> Superformula` uses a compact grid; other Geometry subsection bodies still render as 2-column grids.
- Requirement 3 (main columns exactly 2/3 left and 1/3 right, no stretchy middle gap): **Not implemented**
  - Current state: columns use stretch weights `6:5` with a reduced fixed spacing, not the required `2:1` split.
- Requirement 4 (shorter InfoBar + chips one-line + no extra status line): **Partially implemented**
  - Current state: redundant top counts line already removed and chips use single-line overflow (`+N`), but InfoBar still keeps two description lines and remains taller than required.

### Update 38 (PROJECT Compact Pass: InfoBar Issues Subsection + 3-Column Geometry + 2:1 Main Split)
#### What was wrong
- Issues in the top panel were still controlled by a separate button instead of a real subsection-style header toggle.
- Geometry subsections still used mostly 2-column field layouts, causing extra vertical growth.
- Main Geometry/Mesh content split was not the requested fixed test ratio (`2/3` vs `1/3`).
- InfoBar still consumed too much height due to two description lines.

#### What changed
- `app/gui.py`
  - Replaced top-right button-driven issues area with an in-card, right-anchored issues subsection:
    - header row (`Issues` + `E/W/I` counts + chevron)
    - click header to expand/collapse (no standalone hide button)
    - scrollable grouped issue list in subsection body
    - row click still focuses the exact field and opens the right accordion section.
  - Reduced summary InfoBar height and content density:
    - fixed height reduced to a compact size
    - one description line retained
    - chips stay single-row with existing overflow behavior.
- `ui/form_builder.py`
  - Main column split changed to `2:1` (Geometry : Mesh).
  - Geometry subsection bodies switched to dense `ResponsiveCompactGrid` usage broadly:
    - 3 columns in normal/wide mode
    - fallback to 2 columns for compact widths
    - reduced intra-section spacing for lower vertical footprint.
- `ui/theme.py`
  - Added styling for new InfoBar issues subsection/header/body objects.
  - Kept existing green/yellow/red semantics unchanged.
- `tests/test_project_form_ui.py`
  - Updated assertions for embedded subsection behavior.
  - Added checks for Geometry 3-column rendering and InfoBar subsection toggle behavior.

#### Manual test checklist
- Fullscreen:
  - open PROJECT page
  - verify InfoBar is compact and chips remain one line (`+N` on overflow)
  - open one Geometry + one Mesh section; page should avoid vertical scrollbar in normal use.
- Windowed/restore-down:
  - verify Geometry and Mesh keep `2:1` width relationship with moderate fixed center gap
  - toggle Issues via InfoBar subsection header (right side), not by overlay/popover.
- Issue navigation:
  - trigger multiple severities
  - open Issues subsection, click a row, verify focus jumps to the target field and correct accordion opens.

### Update 39 (InfoBar Issues Anchoring + Mesh Core Label Contract)
#### What was wrong
- Top InfoBar issues area could clip rows when warnings were present and the toggle looked too heavy.
- Issues width did not reliably expand left up to the Mesh column boundary on resize.
- In `Mesh -> Core`, right-column labels/inputs were not following the same spacing contract as left column, causing cramped label rendering (e.g. `Mesh InterfaceResolution`).

#### What changed
- `app/gui.py`
  - Reworked the issues toggle into a compact `QToolButton`-style header (`Issues` / `Issues (N)`), replacing the oversized framed look.
  - Kept issues embedded inside the InfoBar (no overlay), with left-expanding body animation (`maximumWidth`, `InOutCubic`).
  - Added deterministic width calculation against Mesh column boundary:
    - computes target expanded width from right issues anchor to Mesh column left edge on resize.
  - Increased internal panel resilience:
    - scroll area keeps rows visible (no clipping)
    - issue rows use elided text with full tooltip.
- `ui/form_builder.py`
  - Added `ElidedFixedLabel` for non-wrapping, elided labels with tooltips.
  - Updated `Mesh -> Core` grid to a strict two-column row contract for both sides:
    - fixed label width
    - fixed label-to-input gap
    - matched spacing left/right so labels no longer wrap under inputs.
- `ui/theme.py`
  - Styled compact issues toggle (`QToolButton`) and adjusted embedded issues panel text emphasis for readability.

#### Verification
- `python -m py_compile app/gui.py ui/form_builder.py ui/theme.py`
- `python -m unittest tests.test_project_form_ui -v`

## 2026-02-15 - Runner Harness hardening pass (Phase 1+2 and Phase 3 kickoff)

Commits:
- `55a338c` docs: add runner status audit and capability matrix
- `c18f63b` runner-test: add isolated workspace layout and strict cleanup guards
- `cbafcb5` runner-test: add persistent runner_test.sqlite schema and store
- `a2e2266` runner-test: add harness skeleton and CLI run entry
- `f89601f` runner-test: implement full E2E harness with fast profile and hard validations

Highlights:
- Added isolated `runner_test_workspace` with strict guarded cleanup (absolute path + workspace boundary checks).
- Added dedicated `runner_test.sqlite` with test-run telemetry (`test_runs`, `test_run_steps`, `ui_observations`, `artifacts`, `validations`) plus project-compatible run/graph tables.
- Added `runner-test run` CLI command and sample case model wiring.
- Upgraded harness from dry skeleton to full ATH -> AKABAK(UIA) -> VACS(UIA) -> ingest -> validate -> safe clean pipeline.
- Added `runner_test_profile=fast` overrides for low-resolution/quick test execution and persisted effective overrides in DB records.
- Added hard export/data validation checks (size, point thresholds, monotonic x, finite values, zero-series, graph-kind mismatch).
- Added central state-based `wait_until` backoff utility and replaced key fixed sleeps in AKABAK/VACS flows.
- Removed screenshot capture from runner watchdog flow; diagnostics remain UIA/control-dump based.
- Added UI contract stubs under `ui_contracts/akabak` and `ui_contracts/vacs`.

Validation executed:
- `python -m py_compile app/runner_test_harness.py app/runner_test_profiles.py app/ui_automation/waits.py`
- `python -m unittest tests.test_runner_test_workspace tests.test_runner_test_db tests.test_runner_test_profiles tests.test_runner_test_harness tests.test_cli_runner_test tests.test_ui_waits tests.test_vacs_export_pipeline tests.test_runtime_orchestrator tests.test_cli_run_sample tests.test_cli_runs_tools tests.test_ui_automation_contracts -v`

## 2026-02-15 - Runner real VM pass (contract-first AKABAK stabilization)

### Update 40 (Real E2E run + deterministic AKABAK open/import hardening)
#### Why
- Real VM E2E failed in AKABAK project-open stage with incomplete diagnostics.
- AKABAK had a startup blocker window (`TForm_ExampleFiles`) and a modal interpreter/open-file chain that needed strict non-visual contracts.

#### What changed
- `app/akabak_driver.py`
  - Switched AKABAK session startup to `prefer_start=True` to avoid attaching stale external processes.
  - Added deterministic startup modal handling:
    - detect `TForm_ExampleFiles` child window
    - close via handle-based `WM_CLOSE`
    - wait for disappearance (no blind sleeps).
  - Replaced fragile `Ctrl+O` open attempt with command-driven ABEC import flow:
    - send `WM_COMMAND` (`Import ABEC project`, id `113`)
    - wait for interpreter (`TForm_Interpreter`)
    - trigger `Open ABEC Project` control using non-visual keyboard message path
    - wait for open-file dialog (`#32770`) and set filename (`SetDlgItemTextW` id `1148`)
    - hard-fail if open dialog does not close after non-visual confirmation attempts.
  - `import_if_needed()` now handles interpreter state:
    - detects `Start Importing`
    - triggers via non-visual key message and waits for interpreter closure.
  - Error messages now include actionable detail (`repr`) instead of empty exceptions.
- `app/ui_contracts/window_signatures.py`
  - Added AKABAK signatures:
    - `akabak_interpreter_window` (`TForm_Interpreter`)
    - `akabak_open_file_dialog` (`#32770`, `Edit(1148)`, `Button(1)`)
  - Updated main/successor class regexes to real VM classes (`TForm_Main`, `TForm_DatMain`, broader progress/export dialog classes).
- `ui_contracts/akabak/solve_flow.contract.json`
  - Added interpreter + open-file required window contracts.
  - Added startup modal rule for `TForm_ExampleFiles`.
- `app/ui_automation/session.py`
  - Added `prefer_start` option for deterministic session ownership.
- `app/vacs_driver.py`
  - Enabled `prefer_start=True` for isolation parity with AKABAK.

#### Validation
- Unit tests:
  - `python -m unittest tests.test_runner_test_harness tests.test_cli_runner_test tests.test_ui_automation_contracts -v`
- Syntax checks:
  - `python -m py_compile app/akabak_driver.py app/ui_automation/session.py app/ui_contracts/window_signatures.py app/vacs_driver.py app/cli.py app/runner_test_harness.py app/ui_automation/discover.py app/ui_automation/watchdog.py`
- Real VM E2E:
  - `python -m app runner-test run --case smoke_fast --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`
  - `test_run_id`: `6bcfdb6e-916d-4762-8791-725c1d81c887`
  - Result: `failed` at AKABAK open-project with explicit non-visual dialog-close blocker:
    - `ABEC open-file dialog did not close after non-visual confirmation attempts.`

#### Additional hardening in same pass
- `app/runner_test_harness.py`
  - Register AKABAK started PID immediately after open/connect (not only after solve completion), so failing open/import runs are still process-tracked.
  - `safe_clean` now executes explicit started-PID teardown attempts and logs `process_cleanup` telemetry per PID.
- `app/ui_automation/session.py`
  - `close()` now force-terminates only harness-started pywinauto processes when graceful closure is insufficient.

#### Artifacts
- Failure report updated:
  - `docs/Runner_E2E_Failure_Report.md`
- UI dump evidence:
  - `runner_test_workspace/logs/6bcfdb6e-916d-4762-8791-725c1d81c887/ui_discover/akabak_discover_tree_20260215_034947.json`

## 2026-02-15 - Runner hardening pass (legacy evidence + open-dialog micro-harness)

### Update 41 (Legacy evidence extraction)
#### What changed
- Added semantic legacy behavior extraction (read-only source analysis):
  - `docs/LEGACY_RUNNER_BEHAVIOR.md`
  - `docs/legacy_runner_actions.json`
- Captured AKABAK/VACS semantic sequences, modal/dialog inventory, success signals, and known failure classes.
- Explicitly documented prohibited legacy mechanisms (visual automation, tab-count macros) as non-adopted evidence only.

#### Validation
- JSON validity check:
  - `python -m json.tool docs/legacy_runner_actions.json`

### Update 42 (Open-dialog-only harness + CLI)
#### What changed
- Added micro-harness mode for AKABAK open dialog only:
  - `app/runner_test_harness.py`: `run_runner_test_open_dialog_only(...)`
  - `app/cli.py`: `runner-test open-dialog-only` command
- Added persistent DB telemetry for micro-harness runs:
  - `test_runs`, `test_run_steps`, `ui_observations`, `artifacts`, `validations`
- Added tests:
  - `tests/test_runner_test_harness.py`
  - `tests/test_cli_runner_test.py`

#### Validation
- `python -m unittest tests.test_runner_test_harness tests.test_cli_runner_test`

### Update 43 (AKABAK open-dialog contract/handler hardening)
#### What changed
- Updated AKABAK open-file contract and selector requirements:
  - `ui_contracts/akabak/solve_flow.contract.json`
  - `app/ui_contracts/window_signatures.py`
- Implemented deterministic tier ladder in AKABAK open-file submit:
  - Tier A UIA value/invoke
  - Tier B Win32 message path
  - Tier C scoped keys with focus verification
- Added hard postcondition:
  - dialog closed AND project-loaded signal present

#### Validation
- `python -m py_compile app/akabak_driver.py app/ui_contracts/window_signatures.py`
- `python -m unittest tests.test_runner_test_harness tests.test_cli_runner_test tests.test_ui_automation_contracts`

### Update 44 (Failure diagnostics + persistence)
#### What changed
- Added open-dialog failure diagnostics dump files (`json` + `txt`) in AKABAK log dir.
- Persisted diagnostics into `runner_test.sqlite` as artifacts + UI observations.
- Added docs:
  - `docs/AKABAK_OPEN_DIALOG.md`

#### Validation
- `python -m py_compile app/akabak_driver.py app/runner_test_harness.py`
- `python -m unittest tests.test_runner_test_harness tests.test_cli_runner_test tests.test_ui_automation_contracts`

### Update 45 (Real VM stabilization results)
#### What changed
- Stabilized AKABAK open-dialog trigger path by adding main-menu deterministic open fallback (`File->Open project...`) before interpreter fallback.
- Added fail-fast import modal detection in `import_if_needed` with modal detail capture and deterministic primary-button invoke.
- Updated run result docs:
  - `docs/Runner_E2E_Results.md`
  - `docs/Runner_E2E_Failure_Report.md`

#### Real VM runs
- Open-dialog micro-harness, repeats=5:
  - command: `python -m app runner-test open-dialog-only --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --abec-path "runner_test_workspace\\tmp\\real_abec\\ath\\Project.abec" --repeats 5 --workspace-root "runner_test_workspace"`
  - run_ids: `b052b8fd-bdc7-410d-b860-dab479ae55ce`, `8780c294-1ccb-49ea-b1e2-65eb7ee294fb`, `875bcd90-2248-42d2-b5aa-9cb2c7685bc6`, `35afe2b6-ddf2-4b09-aadc-7a1645000058`, `accdf7e0-9960-406f-b9b7-bbf83fba9d57`
  - result: 5/5 succeeded
- Full E2E smoke, repeats=1:
  - command: `python -m app runner-test run --case smoke_fast --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`
  - run_id: `b0bdcff9-ae45-4915-84ac-48862af5a058`
  - result: failed fast with import modal `Cannot find Mesh-File ...\ath\ath.msh`

### Update 46 (Import Start/Apply micro-harness + deterministic postcondition)
#### What changed
- AKABAK import flow hardened to contract-first primary path:
  - `Start Importing` -> wait Apply ready -> `Apply`
  - hard postcondition: `interpreter_closed` OR `start_button_disabled`
  - deterministic modal classification and fail-fast on missing mesh modal
- Added import failure diagnostics dump in AKABAK driver:
  - `import_failure_<timestamp>.json`
  - `import_failure_<timestamp>_main_window.txt`
  - `import_failure_<timestamp>_interpreter_window.txt`
- Added new micro-harness + CLI:
  - `runner-test import-start-apply-only`
  - DB persistence for steps/validations/artifacts/ui observations
- Extended full E2E AKABAK exception persistence to include both open-dialog and import diagnostics.
- Updated docs/contracts:
  - `ui_contracts/akabak/solve_flow.contract.json`
  - `docs/AKABAK_OPEN_DIALOG.md`
  - `docs/RUNNER_TEST_HARNESS.md`
  - `docs/RUNNER_STATUS.md`
  - `docs/Runner_E2E_Results.md`
  - `docs/Runner_E2E_Failure_Report.md`

#### Validation
- Static/tests:
  - `python -m py_compile app\\akabak_driver.py app\\runner_test_harness.py app\\cli.py tests\\test_runner_test_harness.py tests\\test_cli_runner_test.py`
  - `python -m unittest tests.test_runner_test_harness tests.test_cli_runner_test`
- Real VM run (`import-start-apply-only`, repeats=5):
  - command: `python -m app runner-test import-start-apply-only --abec-path "runner_test_workspace\\tmp\\real_abec\\ath\\Project.abec" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --repeats 5 --workspace-root "runner_test_workspace"`
  - run_ids:
    - `4aa8f411-0769-4939-b4ac-b789452d275a`
    - `75c0323f-c1a8-44f5-b305-bf8114bcef76`
    - `7821d89f-f445-4da1-9c97-33ffa505b49a`
    - `63ec0d8e-3723-49a3-852e-f5b6b25fe4d3`
    - `6f0568ce-139b-4ac7-ad15-bb1b0d69eef7`
  - result: 0/5 success, but deterministic classification in all 5 runs (`Cannot find Mesh-File ...\\ath\\ath.msh`)
- Real VM full E2E smoke (latest guard check):
  - command: `python -m app runner-test run --case smoke_fast --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`
  - run_id: `9bdda5f1-904e-4d71-acee-77eb96107aa5`
  - result: failed fast at `pre_akabak_guard_missing_mesh_artifact`

### Update 47 (LE driving audit + post-ATH repair contract)
#### What changed
- Added focused audit note:
  - `docs/LE_DRIVING_AUDIT.md`
- Implemented centralized post-ATH LE repair helper:
  - `app/ath_driver_assets.py`
  - copy `generic25.txt` into ABEC folder (hash-aware)
  - patch `Project.abec` idempotently to `Scriptname_LEScript=generic25.txt`
  - fail-fast assertions and optional diagnostics snapshots
- Wired repair into:
  - `app/runner_test_harness.py`
  - `app/runtime_orchestrator.py`
  - `app/services.py`

#### Validation
- `python -m py_compile app\\ath_driver_assets.py app\\runner_test_harness.py app\\runtime_orchestrator.py app\\services.py app\\cli.py app\\akabak_driver.py`
- `python -m unittest tests.test_m5_planner_renderer -q`

### Update 48 (LE repair/import micro-harness + CLI)
#### What changed
- Added new micro-harness:
  - `runner-test le-repair-import-only`
  - optional ATH run (`--ath-cfg-path`) or reuse existing ABEC (`--abec-path` / `--reuse-export-dir`)
  - persists LE repair artifacts + assertions + AKABAK import telemetry
- Added CLI integration:
  - `app/cli.py`
- Added docs:
  - `docs/LE_REPAIR_IMPORT_HARNESS.md`
- Added tests:
  - `tests/test_ath_driver_assets.py`
  - extended `tests/test_runner_test_harness.py`
  - extended `tests/test_cli_runner_test.py`

#### Validation
- `python -m py_compile app\\ath_driver_assets.py app\\runner_test_harness.py app\\cli.py`
- `python -m unittest tests.test_ath_driver_assets tests.test_runner_test_harness tests.test_cli_runner_test -q`

### Update 49 (RadImp diagnosis classification + AKABAK watchdog capture)
#### What changed
- Added AKABAK watchdog event capture for deterministic diagnosis:
  - `app/akabak_driver.py` (`watchdog_events`)
- Added E2E RadImp diagnosis stage in harness:
  - validation row `radimp_diagnosis`
  - classes:
    - `sources_muted_dialog_seen`
    - `solve_succeeded_radimp_all_zero`
    - `observation_misconfigured_or_wrong_export`
    - `radimp_nonzero_or_not_flagged`
    - `radimp_not_requested`
- Increased import wait ceilings from 30s to 60s in `import_if_needed` to reduce late-dialog timeouts without fixed sleeps.

#### Real VM run
- command:
  - `python -m app runner-test le-repair-import-only --repeats 5 --abec-path "C:\\Horns\\test\\ABEC_FreeStanding\\Project.abec" --akabak-exe "C:\\Program Files (x86)\\RDTeam\\AKABAK\\AKABAK.exe" --ath-exe "C:\\Tools\\ATH\\ATH.exe"`
- result:
  - LE repair assertions passed
  - failures were in AKABAK import postcondition path (intermittent apply-timeout / no explicit LE text in UI tree)
  - run_ids:
    - `0bfde103-6a72-49f7-922b-20ec65c19396`
    - `a16e4051-bbb4-4cfa-8f57-b10c5827bf19`
    - `0a496085-c365-4120-8930-253fcbd778cd`
    - `4a92e571-222c-4188-b669-57ae4beda83b`
    - `33a7dc2c-2018-42bf-bfec-844230fd2f88`

### Update 50 (Recovery: manual interrupt classified as aborted)
#### What changed
- Manual-interrupt recovery applied for run:
  - `f5688841-63bb-40dd-85e0-d2b78d97ba2e`
- Updated Runner_Test DB state:
  - `test_runs.status = aborted`
  - `test_runs.notes += manual_interrupt_user_error`
  - added `test_run_steps.step_name = manual_recovery_mark`
- Added recovery documentation:
  - `docs/RUNNER_RECOVERY_NOTE.md`

#### Validation
- Verified run status is `aborted` in `runner_test_workspace/db/runner_test.sqlite`.
- Verified process ledger is empty at recovery time (`runner_test_workspace/logs/process_ledger.json`).
- Verified no non-ledger AKABAK process was force-terminated by recovery logic.

### Update 51 (Baseline case + ATH runtime cfg + AKABAK open-dialog diagnostics hardening)
#### What changed
- Added baseline runner-test case:
  - `runner_test_cases/test_cfg_baseline.json`
  - uses `C:\Tools\ATH\test.cfg` + `ath_export_root` hint `C:\Horns`
- Hardened harness preflight telemetry:
  - executable probes (exists/executable/size/mtime)
  - export-root probe (exists/writable)
  - persisted into `test_runs.tool_versions`
- Hardened ATH stage in harness:
  - writes local `input.cfg` and local runtime `ath.cfg` per run
  - persists `ath_runtime_cfg` artifact
  - creates output root folder deterministically so ATH mesh generation works
- Added mesh-missing classification in pre-AKABAK guard:
  - `mesher_missing_meshcmd`
  - `mesher_executable_missing`
  - `mesher_execution_failed`
  - `ath_output_mesh_artifact_missing`
- Tightened AKABAK open/import diagnostics:
  - interpreter button states + report text readback in import failure dumps
  - open-dialog attempts now log postcondition snapshot (`dialog_closed`, titles, signal, methods)
  - open dialog control dump now captures real `#32770` tree with controls

#### Real VM runs in this pass
- Full baseline run (latest): `15aaccb8-6120-49ed-8b71-74b65c90a3dd`
  - ATH + LE repair + mesh guard are green
  - blocked at AKABAK open dialog close postcondition
- Open-dialog micro runs (strict contract) still red:
  - `6adf03a6-8a20-439d-9958-d854d9872c9e`
  - `1f623ea8-6aa7-4950-a42f-bc8f8861454f`
- Import-start-apply micro run still red:
  - `ea0d03e1-6e1e-4536-b4cb-ceef63c08328`

#### Validation
- `python -m unittest tests.test_ath_driver_assets tests.test_runner_test_harness tests.test_cli_runner_test`
- repeated targeted real VM runs via:
  - `runner-test run --case test_cfg_baseline ...`
  - `runner-test open-dialog-only ...`
  - `runner-test import-start-apply-only ...`

### Update 52 (VACS child-window discovery, 3-round probe)
#### Done
- Executed 3-round VACS discovery pass focused on child windows and context dialogs.
- Captured stable UI signatures and menu taxonomy from real imported-graph state.
- Added documentation:
  - `docs/VACS_WINDOW_DISCOVERY.md`
- Key observed classes/signatures:
  - main: `TForm_DatMain`
  - workspace: `MDIClient` (`Arbeitsbereich`)
  - child graph windows: `TForm_DatGraph`, `TForm_DatContour`
  - editor windows: `TForm_Editor`
  - context/modals: `TForm_Confirm`, `#32770` (`Warning`, Save project prompt with `Yes/No/Cancel`)

#### Real VM evidence
- Reimport runs used for starting state:
  - `runner_test_workspace/logs/interim_reimport/vacs_interim_reimport_20260215_214604.json`
  - `runner_test_workspace/logs/interim_reimport/vacs_interim_reimport_20260215_215451.json`
- UI-discover artifacts:
  - `runner_test_workspace/logs/vacs_probe/round1/...`
  - `runner_test_workspace/logs/vacs_probe/round2/...`
  - `runner_test_workspace/logs/vacs_probe/round3/ui_final/vacs_discover_tree_20260215_220355.json`

#### Known instability
- Deep interactive probe paths (child activation + immediate export-dialog interaction) timed out in rounds 1/2.
- This is logged as a probe robustness issue; next pass should isolate it in a dedicated `vacs-export-only` micro-harness with strict per-step timeout contracts.

### Update 53 (VACS Data Export discovery, 5 rounds)
#### Done
- Added standalone diagnostics runner:
  - `scripts/vacs_export_dialog_rounds.py`
- Executed full 5-round export discovery run:
  - `runner_test_workspace/logs/vacs_export_rounds/run_20260215_232004/summary.json`
- Added detailed report:
  - `docs/VACS_EXPORT_DIALOG_DISCOVERY.md`

#### Key findings
- `Data Export` is stable as:
  - title: `Data Export`
  - class: `TForm_Export`
- Export trigger robust path:
  - child `F7` / main `F7` / `WM_COMMAND id=52`
- Menu path `IO->Export data...` can be disabled while hotkey/command still works.
- Save control is custom control (not plain UIA Button):
  - class: `TRzBitBtn`
  - text: `Save...` (`&Save...` in win32 text)
- Pitfall dialog reproduced:
  - `Graph range` (`TForm_CurvesRange`) via `Graph->Range` and graph double-click.

#### Caveats
- Graceful VACS shutdown remained flaky in probe context; force-kill fallback used in diagnostics path.
- Contour double-click did not create a separate modal in this session (possible in-place child state change only).

### Update 54 (VACS export ultra-speed pass + COM registration check)
#### Done
- Implemented hot-path performance optimizations in `scripts/vacs_export_save_all.py`:
  - fast top-level window scan helper (`win32` first) for dialog detection
  - faster `Data Export` discovery polling
  - faster `Save As` discovery polling
  - fast confirm-drain path for modal confirms
  - fast save path in `Save As` (`quick=True`) while keeping file postcondition checks
  - reduced per-step sleep/poll overhead in the export loop
- Kept strict non-visual control strategy:
  - process-scoped windows, class/control signatures, win32 handle operations
  - no pixel/OCR/coordinate decisions
- Added and validated fast mode orchestration in script (`--mode fast`, `--mode auto` fallback behavior retained).

#### COM / RegServer check
- Executed: `VACSVIEWER_32.exe /RegServer` (outside repo, reversible action).
- Verified outcome with direct interim test (`open via AKABAK`, `disallow-existing-vacs`):
  - COM error persisted (`vacs_com_registration_missing`).
- Environment note:
  - session is non-admin (`is_admin=False`), so machine-wide COM registration may not be fully applied.

#### Real VM evidence (selected runs)
- Fast mode successful runs:
  - `run_20260216_022159` (~53.35s, `ok=true`)
  - `run_20260216_022728` (~47.52s, `ok=true`)
  - `run_20260216_023342` (**21.77s**, `ok=true`, 4 exports)
- Intermittent RPC failures (known flake class):
  - `run_20260216_023121` (`AKABAK RPC server unavailable`)
  - `run_20260216_023412` (`AKABAK RPC server unavailable`)
  - `run_20260216_023510` (`AKABAK RPC server unavailable`)
- Auto fallback confirmation:
  - `run_20260216_023723` (`ok=true`, `fallback_used=true`, but significantly slower).

#### Validation
- `python -m py_compile scripts/vacs_export_save_all.py scripts/vacs_interim_reimport.py`
- Multiple real executions:
  - `python scripts/vacs_export_save_all.py --mode fast ...`
  - `python scripts/vacs_export_save_all.py --mode auto ...`
  - `python scripts/vacs_interim_reimport.py --open-vacs-via-akabak --disallow-existing-vacs ...`

### Update 55 (Fast reentry point after RPC + transient handle hardening)
#### Done
- Added deterministic reentry ladder in `run_once_fast` (`scripts/vacs_export_save_all.py`):
  - primary: interim attach-only (`--skip-open-vacs-via-akabak`)
  - reentry: interim via AKABAK menu (`Options -> Open VACS...`)
  - final fallback: relaxed attach-only retry
  - plus late-accept guard when graph windows are already visible
- Hardened signature extraction against transient/invalid Win32 handles:
  - `_sig()` now wraps attribute access defensively to prevent hard crashes during fast top-level scans.

#### Why
- Fast mode was very quick but could fail hard when AKABAK showed intermittent RPC modal.
- Goal was a safe and deterministic reentry point without immediately falling back to the slow full-safe export path.

#### Validation (real VM)
- command:
  - `python scripts/vacs_export_save_all.py --mode fast --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe" --export-dir "C:\Horns\test\ABEC_FreeStanding\Results" --output-dir "runner_test_workspace/logs/vacs_export_save_all" --max-runtime-s 240`
- run:
  - `run_20260216_025403`
- result:
  - primary interim failed with RPC modal
  - reentry stage `interim_reimport_reentry_open_via_akabak` succeeded
  - 4 exports written, `ok=true`

### Update 56 (Primary path swap + AKABAK speed pass)
#### Done
- Switched VACS fast mode reentry order based on measured reliability:
  - primary now uses AKABAK menu handshake (`Open VACS...`)
  - reentry fallback uses attach-only
  - final fallback uses relaxed menu handshake
- Kept fast export hot path unchanged (top-level detection + fast save/confirm handling).
- AKABAK driver speed/robustness updates in `app/akabak_driver.py`:
  - `_solve_signal_snapshot(include_vacs_ui=...)` added to avoid expensive VACS UI scans during solve-start detection.
  - `run_solve` changed to dual-trigger start (`UIA F4` + `hwnd F4`) then single bounded wait.
  - solve-start wait tuned for faster reaction (`initial_interval_s=0.05`, capped backoff).
  - start condition tightened: `vacs_process_started` now requires `new_vacs` (no immediate success from stale VACS PID alone).
  - completion wait polling tuned (`initial_interval_s=0.08`, capped backoff) for faster end detection without fixed sleeps.

#### Why
- Fast attach-only primary was statistically weak in this VM and often fell into RPC dialogs.
- AKABAK solve start previously could spend long fallback windows before trying the second F4 trigger.

#### Validation (real VM)
- Fast VACS run after primary swap:
  - `run_20260216_030017` (`ok=true`)
  - primary interim (`open_vacs_via_akabak`) succeeded directly
  - total around ~24s for 4 exports
- Runner baseline run to exercise AKABAK flow with new solve logic:
  - `test_run_id=43ef4dae-cdfe-44d9-8f39-d276df19f93c`
  - AKABAK stages reached `run_solve` and `wait_for_completion` successfully (see `akabak_driver.log.jsonl`)
  - run failed later in VACS export validation pattern (`^Result_.*SPL.*\\.txt$`) - unrelated to solve-start optimization

### Update 57 (AKABAK solve-start timeout hardening after aggressive fast-window regression)
#### Done
- Adjusted `app/akabak_driver.py::run_solve` from a single aggressive start wait to a two-tier start strategy:
  - tier 1 fast wait (`<=6s`) after dual F4 trigger (`UIA` + `hwnd PostMessage`)
  - tier 2 extended wait (`<=30s`) with a second dual F4 retry
- Kept non-visual behavior and backoff polling (no fixed sleeps introduced).
- Preserved tightened stale-VACS protection (`new_vacs` only for `vacs_process_started` signal).

#### Why
- Real baseline run showed false negative on solve-start when the VM/toolchain reacted slower than the reduced timeout window.
- The fast path stays fast on good runs, while the extended tier prevents premature aborts.

#### Validation
- Syntax check:
  - `python -m py_compile app/akabak_driver.py`
- Real baseline run after patch:
  - `test_run_id=dc30a051-a816-49cf-ba51-6004592e798e`
  - result: still failed at solve-start timeout (`30s`) in this specific environment state
  - key observation: pre-existing VACS process (`pid 9020`) was already active in baseline snapshot, indicating external state contamination risk for this run.
- Note:
  - `pytest` not available in current Python env (`No module named pytest`), so no local unit suite execution in this pass.

### Update 58 (Preflight contamination guard + pytest environment bootstrap)
#### Done
- Installed `pytest` in the active Python environment (`python -m pip install pytest`).
- Replaced unsafe preflight behavior that previously forced global AKABAK shutdown.
- Added deterministic unmanaged-process scan in `app/runner_test_harness.py`:
  - scans running `AKABAK.exe`, `VACSVIEWER_32.exe`, `VACSVIEWER.exe`
  - compares against harness-owned PIDs from `process_ledger.json`
  - blocks run early when unmanaged tool processes are detected.
- Added tracker helper `owned_pids()` and reusable process-list helper.
- Applied guard consistently to:
  - `run_runner_test_harness`
  - `run_runner_test_open_dialog_only`
  - `run_runner_test_import_start_apply_only`
  - `run_runner_test_le_repair_import_only`

#### Why
- Recent failures showed contaminated VM state (externally started VACS/AKABAK) causing false-negative solve detection.
- Guardrails require process safety: only harness-owned processes may be managed by harness logic.

#### Validation
- `python -m py_compile app/runner_test_harness.py`
- `python -m pytest tests/test_runner_test_harness.py tests/test_cli_runner_test.py tests/test_cli_runs_tools.py tests/test_cli_vacs_tools.py tests/test_cli_run_sample.py -q`
  - `13 passed`
- Real guard proof:
  - started AKABAK manually, then executed `runner-test open-dialog-only`
  - run failed at preflight with clear note:
    - `unmanaged AKABAK/VACS process detected; close manual tool windows and retry`

### Update 59 (VACS export filename contract + leak-safe exception cleanup)
#### Done
- Fixed VACS TXT export success criteria in `app/vacs_driver.py`:
  - primary success signal is now exact `output_file` existence with non-zero size
  - legacy recipe `file_pattern` remains as fallback acceptance path
  - avoids false failures when harness uses deterministic filenames like `V001_spl.txt`.
- Hardened VACS exception path in `run_runner_test_harness`:
  - captures VACS PID snapshot before/after export stage
  - on exception, newly spawned VACS PIDs are registered as harness-owned
  - those PIDs are then guaranteed to be cleaned in `safe_clean`, preventing unmanaged carry-over into the next run.
- Added failed `vacs_export` step telemetry on exception with leaked PID diagnostics.

#### Why
- Baseline run failed with:
  - `Export file pattern not satisfied: ^Result_.*SPL.*\\.txt$`
  even though export naming was intentionally case-driven.
- A failed export before driver meta registration could leave a VACS process behind, which then blocked the next run via unmanaged-process guard.

#### Validation
- `python -m py_compile app/vacs_driver.py app/runner_test_harness.py`
- `python -m pytest tests/test_vacs_export_pipeline.py tests/test_cli_vacs_tools.py tests/test_cli_runner_test.py tests/test_runner_test_harness.py -q`
  - all passed.
- Observed unmanaged legacy blocker still present from pre-fix run:
  - `VACSVIEWER_32.exe` pid `996` (must be closed once manually before next clean baseline run).

### Update 60 (Final-run handoff: use F4-opened VACS directly, no second open/reimport)
#### Done
- Implemented `--assume-vacs-ready` path in `scripts/vacs_export_save_all.py`:
  - scans existing VACS processes
  - selects ready VACS main window with graph child windows
  - skips interim reimport (`Open VACS`/`F7`) and starts export loop immediately.
- Wired runner export pipeline to use this mode:
  - `app/vacs_export_pipeline.py` now calls external exporter with `--assume-vacs-ready` in harness flow.
- Kept non-visual control flow and deterministic fallbacks; no pixel/OCR/coordinate logic added.
- Extended graph-kind alias mapping in harness validation:
  - `Sound pressure` now accepted as SPL (`app/runner_test_harness.py`).

#### Why
- In final runner path, AKABAK `F4` already opens and populates VACS; reopening/reimporting introduced unnecessary instability and latency.
- Baseline evidence showed false SPL mismatch because parsed graph type was `Sound pressure`.

#### Validation
- `python -m py_compile scripts/vacs_export_save_all.py app/vacs_export_pipeline.py app/runner_test_harness.py`
- `python -m pytest tests/test_vacs_export_pipeline.py tests/test_runner_test_harness.py tests/test_cli_runner_test.py tests/test_cli_vacs_tools.py -q`
  - all passed.
- Real baseline runs:
  - `b02388cc-54cb-49bb-a2f4-0a44c8947825`: AKABAK+VACS export path successful; remaining failures were validation-only.
  - `404bfb68-40e2-4dbe-857c-90f82f9d7780`: `export_quality:spl=ok`; remaining blocker is `impedance` all-zero + `radimp_diagnosis` failed.

### Update 61 (LE A/B/C/D matrix + normalized RadImp classification + repeat stability)
#### Done
- Added LE repair profile support to harness/CLI:
  - `baseline`
  - `driver_drvgroup`
  - `driver_drvgroup_def_driving`
  - `driver_drvgroup_def_driving_resistor`
- Implemented LE script profile patching in `app/ath_driver_assets.py` (idempotent, hash-aware copy remains intact).
- Added persistent diagnostics artifacts in full E2E harness:
  - `ath_input_project`, `ath_input_solving`, `ath_input_observation`, `ath_input_le_script`
  - `abec_tree_snapshot` after AKABAK solve
- Extended RadImp validation logic in `app/runner_test_harness.py`:
  - all-zero impedance export is accepted when metadata indicates normalized RadImp baseline
  - new diagnosis class: `radimp_normalized_zero_baseline`
- Hardened preflight/process behavior:
  - wait/backoff for transient unmanaged AKABAK/VACS processes
  - register VACS pids that are already alive before export (spawned by AKABAK/F4), so cleanup can terminate them deterministically

#### Why
- Real runs showed RadImp remained all-zero across LE script variants while SPL was non-zero.
- Export evidence showed the correct graph was selected (`Radiation_Impedance #5`) and marked normalized.
- Previous hard-fail on all-zero RadImp was generating false negatives for this normalized baseline mode.
- Repeats were intermittently blocked by leftover unmanaged VACS pids between sequential runs.

#### Validation
- Unit tests:
  - `python -m pytest tests/test_ath_driver_assets.py tests/test_runner_test_harness.py tests/test_cli_runner_test.py -q`
  - `16 passed`
- Real E2E matrix runs:
  - A baseline: `92d37a9a-fcff-4f73-880b-c647f9c94451`
  - B drvgroup: `f2cc10a8-c2fe-4e3a-b389-c24a6e887957`
  - C drvgroup+def_driving: `159eef18-4a67-4727-afc1-19bbda645c25`
  - D doc-like topology: `427c4a22-7fdb-4f8d-a963-54dbda0c8091`
  - all showed normalized RadImp zero signature with successful flow.
- Green baseline after classifier/process fixes:
  - single run: `ec32ba97-70b4-4c6d-aa6c-a1632bb183ac` (`succeeded`)
  - repeats=3: `3515ef82-c38c-4d97-89f7-124a7b1febef`, `577b29f0-4abe-4af6-82ca-fbf95805e8d5`, `e2ebbcf8-9b88-4313-ab2a-5423516ba2f4` (all `succeeded`)

#### Docs
- Updated: `docs/TOOLCHAIN_BASELINE.md`
- Updated: `docs/RADIMP_BASELINE_REPORT.md`
- Added: `docs/LE_RULES_EXTRACT.md`

### Update 62 (RadImp observation-profile experiments + default baseline confirmation)
#### Done
- Added harness observation patch profiles (post-ATH, test-only):
  - `default`
  - `force_absolute`
  - `drop_radimptype`
- Wired new CLI option:
  - `runner-test run --radimp-observation-profile <profile>`
- Added deterministic observation patch step + DB telemetry/artifacts:
  - step: `post_ath_observation_patch`
  - validation: `post_ath_observation_patch_assertions`
  - artifact: `observation_patch_summary`
- Added unit tests for observation patch helper.

#### Why
- We needed a controlled, reproducible way to test whether non-normalized RadImp observation settings produce non-trivial values, without changing production pipeline semantics.

#### Validation
- Unit tests:
  - `python -m pytest tests/test_runner_test_harness.py tests/test_cli_runner_test.py tests/test_ath_driver_assets.py -q`
  - `18 passed`
- Real runs:
  - `default`: `e4648f14-2d45-48cc-8590-59c6812b9dcc` (`succeeded`)
  - `force_absolute`: `3f03e9cf-36d7-4bc1-8a0d-743555f90091` (`failed`: no impedance graph available for export mapping)
  - `drop_radimptype`: `5afeefcb-ac24-46a9-9f55-e21807586f8e` (`failed` by validation; RadImp remained all-zero)
- Stable baseline re-check (`default`, repeats=3):
  - `f09efdc4-60fc-4fcc-be4d-e1ee5b7e6b12` (`succeeded`)
  - `c917fcf1-927c-4bb8-aca6-ff0cafa25de0` (`succeeded`)
  - `67f9f99b-2961-42f6-8646-fca2f793ec6f` (`succeeded`)

#### Outcome
- In this environment/configuration, tested observation-profile changes did not yield non-zero RadImp exports.
- Runner robustness remains green on default profile; issue is narrowed to modeling/observation semantics, not UI automation flow.

#### Docs
- Updated: `docs/RADIMP_BASELINE_REPORT.md`
- Updated: `docs/TOOLCHAIN_BASELINE.md`
- Updated: `docs/LE_RULES_EXTRACT.md`

### Update 63 (Driving_Values/DrvType hypothesis matrix)
#### Done
- Added dedicated driving observation patch layer in harness (`post_ath_driving_patch`):
  - profiles: `default`, `accel_2p83`, `accel_10`, `accel_0p1`, `velocity_1`, `displacement_1`
- Added matrix mode:
  - `python -m app runner-test radimp-driving-matrix ...`
  - executes profile list sequentially and returns per-run outcome incl. `radimp_diagnosis` + `export_quality:impedance`.
- Added CLI support:
  - `runner-test run --driving-observation-profile ...`
  - `runner-test radimp-driving-matrix --profiles ... --repeats-per-profile ...`
- Added DB telemetry/artifacts:
  - validation `post_ath_driving_patch_assertions`
  - artifact `driving_patch_summary`

#### Why
- We needed an evidence-backed way to test whether changing only `Driving_Values` (`DrvType`/`Value`) can break out of normalized RadImp zero baseline.

#### Validation
- Tests:
  - `python -m pytest tests/test_runner_test_harness.py tests/test_cli_runner_test.py -q`
  - `16 passed`
- Real matrix run:
  - command: `runner-test radimp-driving-matrix` with profiles `default,accel_2p83,accel_10,velocity_1,displacement_1`
  - run_ids:
    - `8854f9dd-b0ac-4df2-9d8b-238ae3105d00`
    - `13114a8a-6ca6-4cca-9fd1-4cf57f2c12ba`
    - `a00eef05-0624-4f5e-8c53-ce0222639f25`
    - `42920920-1b53-47ef-8f24-c8428deb5992`
    - `781979c4-b2aa-466f-8512-6f201e91bfe6`
  - all profiles completed successfully.
- Snapshot proof confirms profile values were actually patched in `observation.txt`.

#### Outcome
- RadImp remained normalized/all-zero across the full Driving_Values matrix.
- This further narrows the remaining issue to model/observation semantics beyond `Driving_Values` tuning.

#### Docs
- Added: `docs/RADIMP_DRIVING_MATRIX_REPORT.md`
- Updated: `docs/RADIMP_BASELINE_REPORT.md`
- Updated: `docs/TOOLCHAIN_BASELINE.md`
- Updated: `docs/LE_RULES_EXTRACT.md`

### Update 64 (3-scope LE/RadImp diagnostics: cfg + observation + driving)
#### Done
- Added harness-only cfg scope patching in `app/runner_test_harness.py`:
  - new profile axis `cfg_le_profile` (`default`, `le_voltage_2p83`, `le_voltage_10`, `le_voltage_0p1`)
  - deterministic `LE.Voltage` patch on generated cfg (post-render, test-only)
  - persisted validation: `cfg_le_profile_applied`
  - persisted artifact (when patched): `cfg_patch_summary`
- Added combined matrix mode:
  - `runner-test radimp-3scope-matrix`
  - evaluates combinations across cfg/observation/driving scopes and returns per-run validation outcomes.
- Added CLI wiring:
  - `runner-test run --cfg-le-profile ...`
  - `runner-test radimp-3scope-matrix ...`
- Added tests:
  - cfg patch unit test
  - 3-scope matrix dry-run test
  - CLI test for `radimp-3scope-matrix`

#### Why
- We needed to expand diagnostics beyond LE script and observation-only hypotheses and explicitly test cfg-level LE voltage impact without changing production defaults.

#### Validation
- Tests:
  - `python -m pytest tests/test_runner_test_harness.py tests/test_cli_runner_test.py -q`
  - `19 passed`
- Real 3-scope runs:
  - 2x2x2 matrix (`cfg=default|le_voltage_2p83`, `radimp=default|force_absolute`, `driving=default|accel_2p83`)
  - additional `cfg=le_voltage_10` runs with `radimp=default`, `driving=default|accel_2p83`
  - run IDs documented in `docs/RADIMP_3SCOPE_MATRIX_REPORT.md`

#### Outcome
- `cfg_le_profile` patching is active and verified (`detected_le_voltage_after` persisted).
- For successful runs under `radimp=default`, RadImp remains normalized/all-zero baseline.
- `force_absolute` combinations consistently fail at VACS graph mapping (`impedance` graph not resolved), independent of cfg profile.

#### Docs
- Added: `docs/RADIMP_3SCOPE_MATRIX_REPORT.md`
- Added: `docs/LE_CFG_SCOPE_RESEARCH.md`

### Update 65 (force_absolute mapping hardening + pre-AKABAK LE/Driving contract guard)
#### Done
- Hardened external VACS mapping in `app/vacs_export_pipeline.py`:
  - mapping now scores candidates by title/path and exported TXT metadata (`Data_LevelType`, `Data_Legend`)
  - added deterministic error payload with `available_graphs` evidence when mapping fails
  - exported mapping details now persist source metadata (`source_data_level_type`, `source_data_legend`, `mapping_score`)
- Added fail-fast LE/Driving contract guard before AKABAK start in `app/runner_test_harness.py`:
  - validation + step: `pre_akabak_le_driving_contract` / `pre_akabak_le_driving_guard`
  - checks solving/observation presence, expected `DrvGroup`, and `Radiation_Impedance` entries
- Updated VACS contract file to concrete signatures (`ui_contracts/vacs/export_txt_flow.contract.json` v2).
- Added/updated tests:
  - `tests/test_vacs_export_pipeline.py` (metadata-based mapping + deterministic failure evidence)
  - `tests/test_runner_test_harness.py` (pre-AKABAK LE/Driving contract guard parsing)

#### Why
- `force_absolute` runs failed with ambiguous `graph_kind` mapping errors.
- We needed deterministic evidence for root cause classification and stricter preconditions before AKABAK/VACS stages.

#### Validation
- Tests:
  - `python -m pytest tests/test_vacs_export_pipeline.py tests/test_runner_test_harness.py tests/test_cli_runner_test.py -q`
  - `26 passed`
- Real runs:
  - `runner-test run --radimp-observation-profile force_absolute --repeats 3`
    - run_ids: `92e5c3a5-22a6-418f-b02e-0a11af0abfdd`, `82e14f06-36d8-49f9-b6cb-6ef064bbbc2e`, `b10d2224-d7e9-4ded-97b6-b2ac8d418122`
    - deterministic failure signature: only `SoundPressure` candidate graphs available for impedance mapping.
  - `runner-test radimp-3scope-matrix` repeats-per-combo=2:
    - cfg `default|le_voltage_2p83`, radimp `default|force_absolute`, driving `default|accel_2p83`
    - default profile combos stable success; force_absolute combos stable deterministic failure with identical evidence pattern.
  - cfg extension repeats-per-combo=2:
    - cfg `le_voltage_10`, radimp `default|force_absolute`, driving `default`
    - default stable success; force_absolute stable deterministic failure.

#### Docs
- Updated: `docs/RADIMP_3SCOPE_MATRIX_REPORT.md`
- Updated: `docs/LE_CFG_SCOPE_RESEARCH.md`
- Updated: `docs/UI_AUTOMATION_CONTRACTS.md`
- Added: `docs/RADIMP_3SCOPE_RUNBOOK.md`

### Update 66 (Strict non-zero RadImp gate + bias-safe matrix + stability reruns)
#### Done
- Harness diagnostics/classification hardening in `app/runner_test_harness.py`:
  - Added strict target gate flag: `strict_nonzero_radimp`
  - Added/normalized diagnosis classes:
    - `sources_muted_dialog_seen`
    - `solve_not_completed_or_no_results`
    - `wrong_graph_exported`
    - `radimp_normalized_zero_baseline`
    - `radimp_all_zero_unclassified`
    - `radimp_nonzero`
  - Added export-stage fallback diagnosis persistence for `VacsExportPipelineError` (wrong graph mapping now persists as `radimp_diagnosis` instead of generic failure only).
  - Added manual-interference preflight abort classification (`HarnessManualInterferenceError` -> run status `aborted`).
- Matrix bias controls:
  - `run_runner_test_radimp_3scope_matrix` now supports randomized combo order with deterministic seed.
  - CLI wiring added:
    - `--strict-nonzero-radimp`
    - `--no-randomize-order`
    - `--matrix-seed`
- Test updates:
  - Added/updated harness and CLI tests for new diagnosis classes, strict gate, and matrix seed metadata.
  - Target suites green.

#### Validation (tests)
- `python -m pytest tests/test_runner_test_harness.py tests/test_cli_runner_test.py tests/test_vacs_export_pipeline.py -q`
  - `29 passed`

#### Validation (real VM runs)
- Strict baseline run (expected fail if RadImp remains zero):
  - `4747aaa6-f41a-4566-9912-74edd5391535`
  - `strict_nonzero_radimp=failed`
  - `radimp_diagnosis=radimp_normalized_zero_baseline`
- Strict force-absolute run with deterministic mapping failure classification:
  - `31bd2c95-29a0-49f4-ab3c-63ea932992d5`
  - `radimp_diagnosis=wrong_graph_exported`
  - evidence persisted (`available_graphs`, `Data_LevelType=SoundPressure`)
- Bias-safe strict 3-scope campaign (`--matrix-seed 20260216`):
  - strict rows: `20`
  - class counts:
    - `radimp_normalized_zero_baseline`: `10`
    - `radimp_all_zero_unclassified`: `9`
    - `wrong_graph_exported`: `1`
    - `radimp_nonzero`: `0`
- Stability re-check (non-strict baseline):
  - repeats=3 green:
    - `9cfd8364-12b1-405a-9576-d64d8a9ed802`
    - `9e44fb2d-9bc2-4bce-b880-9352927361f3`
    - `6dfdccd0-6b0c-4ba3-b55d-39eb00f3951e`
  - repeats=10 green:
    - `5fa745e8-8885-4ec2-a421-68b6966081de`
    - `8b04fab7-5161-4388-8c34-b1e6c7b69809`
    - `3756bd6d-7669-4cdd-aa93-b27ae0b518c5`
    - `a2f9667d-d852-432e-9a43-c1afeb5d5f31`
    - `5c07e3de-3e20-4d4c-bb27-4b75518bce29`
    - `0a96afd2-bcd2-4e65-a45e-2ea4b9690acf`
    - `783ffd0d-2df6-4332-bd97-3877b2ad0b68`
    - `5a915552-d2c4-4b1b-be95-6c6e5ea1ccfa`
    - `f2304c75-44c0-43db-ae61-5e16df7c50f3`
    - `8be59014-353d-4ca6-926f-aca7f17f136b`

#### Docs
- Updated: `docs/RUNNER_RECOVERY_NOTE.md`
- Updated: `docs/TOOLCHAIN_BASELINE.md`
- Updated: `docs/LE_CFG_SCOPE_RESEARCH.md`
- Updated: `docs/LE_RULES_EXTRACT.md`
- Updated: `docs/RADIMP_3SCOPE_RUNBOOK.md`
- Updated: `docs/RADIMP_3SCOPE_MATRIX_REPORT.md`
- Updated: `docs/RADIMP_BASELINE_REPORT.md`
- Added: `docs/RUNNER_E2E_GREEN.md`
- Added: `docs/LE_SOLUTION.md`

### Update 67 (Composite LE proof matrix + mutation profiles + registry prep)
#### Done
- Extended LE patching in `app/ath_driver_assets.py`:
  - Added harness mutation profiles: `mut_electrical`, `mut_motor`.
  - Mutations are applied only to run-local copied LE script (never tool-install files).
  - Persisted mutated parameter names in `driver_patch` result payload.
- Added new harness command in `app/runner_test_harness.py`:
  - `run_runner_test_le_proof_matrix(...)`
  - Randomized seeded run scheduling across profiles.
  - Control noise-floor + mutation effect-size computation from persisted curve data.
  - Composite diagnosis: `le_active_confirmed`, `le_active_inconclusive`, `le_active_not_evidenced`, `le_proof_invalid`.
  - Persisted validations:
    - `le_proof_noise_floor`
    - `le_proof_effect_size`
    - `le_integration_diagnosis`
  - Persisted artifacts:
    - `le_mutated_driver`
    - `le_proof_comparison_report`
    - `le_proof_curve_diff`
- Added CLI wiring in `app/cli.py`:
  - `runner-test le-proof-matrix`
  - flags: `--profiles`, `--repeats-per-profile`, `--strict-le-proof`, `--matrix-seed`, `--no-randomize-order`.
- Added harness-side LE registry prep:
  - `app/le_driver_registry.py` with `LEDriverSpec`
  - `app/knowledge/le/driver_registry.v1.json` (initial `generic25` entry)
- Added/updated docs:
  - `docs/LE_INTEGRATION_REQUIREMENTS.md`
  - `docs/LE_PROOF_PROTOCOL.md`
  - `docs/LE_RESEARCH_LOG.md`
  - updated `docs/LE_RULES_EXTRACT.md`
  - updated `docs/RADIMP_BASELINE_REPORT.md`
  - updated `runner_test_cases/test_cfg_baseline.json` (`le_proof` block)

#### Why
- RadImp-only was not sufficient as primary LE activation proof.
- We needed a deterministic, bias-aware, reproducible composite proof path while keeping production LE lock unchanged.

#### Validation
- `python -m pytest tests/test_ath_driver_assets.py tests/test_runner_test_harness.py tests/test_cli_runner_test.py -q`
  - `33 passed`
- `python -m pytest tests/test_cli_run_sample.py tests/test_cli_runs_tools.py tests/test_cli_vacs_tools.py tests/test_runner_test_harness.py tests/test_cli_runner_test.py tests/test_ath_driver_assets.py -q`
  - `37 passed`

### Update 68 (Real LE proof matrix smoke run)
#### Done
- Executed real `le-proof-matrix` run on VM tools with profiles:
  - `control`
  - `mut_electrical`
  - `mut_motor`
- Matrix result:
  - `matrix_id=8878622b-9c75-48ff-8b22-8cc63a89eae5`
  - `le_integration_diagnosis=le_active_confirmed`

#### Evidence
- Run IDs:
  - control: `f1117950-bb82-4049-a99a-9e1f1e5dce43`
  - mut_electrical: `8c26adac-4094-4e53-9758-b5e94d7aec8a`
  - mut_motor: `5b844f8e-f8bc-4436-b4ee-93e47e1c7ec5`
- Effect sizes vs control:
  - `mut_electrical.spl_delta_rms=0.250374733444921` (>= 0.25 threshold)
  - `mut_motor.spl_delta_rms=0.5543950365469512` (>= 0.25 threshold)
  - impedance deltas remained `0.0` in this pass.

#### Outcome
- Composite proof path confirms LE influence on SPL curves for this baseline setup.
- RadImp stays a secondary KPI and remains normalized/all-zero baseline in these runs.

#### Docs
- Added: `docs/LE_PROOF_MATRIX_REPORT.md`

### Update 69 (UI-only Compatibility Rework for Project/Batch)
#### Done
- Removed UI-specific prevention fields from compatibility service outputs.
  - No `prevented_keys`, `prevented_reasons`, `ui_hint_trigger_key` in rule service responses.
- Added UI-side compatibility adapter:
  - new `ui/compat_ui_adapter.py`
  - derives `compat_ui_state` (`hidden_keys`, `blocked_options`, cause/helper mapping) from compatibility snapshots.
- Project/Batch interaction flow updated:
  - blocked segmented options emit `blocked_interaction`
  - click on blocked option flashes primary cause field in subtle blue
  - fast debounce + batch reconcile pass to remove stale hidden payload values.
- Fixed transient batch validation noise:
  - removed temporary `batch_param_not_visible` conflicts after mode switches by revalidate-after-hide reconcile.
- Policy updates in GUI:
  - Project: incomplete no longer blocks create.
  - Batch: save allowed on incomplete; run blocked on incomplete/fatal.
- Theme states added for compatibility UX:
  - `compatBlocked`, `compatBlockedOption`, `compatCauseFlash`.

#### Tests
- Added/updated UI coverage:
  - blocked option interaction and cause propagation (Project + Batch)
  - hidden-field reset behavior when visibility changes
  - project incomplete action policy expectations updated
- Full suite green:
  - `236 passed, 5 skipped`.

#### Docs
- Updated:
  - `docs/BATCH_UI.md` (rule/UI separation + reconcile pass)
  - `docs/PROJECT_UI.md` (compatibility UX policy)

## 2026-02-16
### Update (Dataset Pipeline Hardening: Post-VACS Ingest)
#### Done
- Reviewed runtime dataset flow and confirmed staged persistence model:
  - plan/versions at materialization
  - ATH dimensions after ATH
  - graph ingest after VACS export
- Hardened `app/runtime_orchestrator.py` VACS ingest to be contract-first:
  - consumes `run_vacs_export_specs` export mapping (`spec/entry/output_path`)
  - assigns `graph_kind` from ExportSpec mapping (authoritative), not only parser inference
  - carries mapping context into stored metadata (`spec_id`, entry/details/plugin)
- Added deterministic integrity checks before SQL write acceptance:
  - `missing_contract_files`
  - `mapping_errors` on confident graph-kind conflicts
  - stage fails on parse errors/mapping errors/missing contract files/zero rows
- Added documentation:
  - `docs/DATASET_PIPELINE_STATUS.md` (status, architecture decision, method, implementation)

#### Tests
- Extended `tests/test_runtime_orchestrator.py` with:
  - `test_pipeline_prefers_export_spec_mapping_for_graph_kind`
  - `test_pipeline_marks_vacs_failed_on_graph_kind_mismatch`

#### Notes
- Legacy `app/dataset_pipeline.py` remains untouched in this pass.
- Existing unrelated local changes were not modified by this pass:
  - `app/ui_automation/watchdog.py`
  - `ui_contracts/akabak/solve_flow.contract.json`
  - `docs/AKABAK_IMPORT_SOLVE.md`

### Update (Dataset Federation Readiness Prep)
#### Done
- SQL schema bumped to `2.4` and extended for future server federation:
  - `federation_profile`
  - `federation_sync_state`
  - `federation_export_jobs`
  - `federation_tombstones`
- Added automatic federation identity bootstrap on DB init (`installation_id`, anonymized user id, namespace).
- Added tombstone generation when unpinned runs are deleted (`cleanup_unpinned_runs`).
- Added new store APIs:
  - `load_federation_profile()`
  - `update_federation_profile(...)`
  - `update_federation_sync_state(...)`
  - `record_federation_export_job(...)`
- Added documentation:
  - `docs/DATASET_FEDERATION_READINESS.md`

#### Tests
- Extended `tests/test_sql_dataset_store.py`:
  - federation profile bootstrap + consent update
  - tombstone write on run cleanup

## 2026-02-16
### Baseline (Batch UI Rework Start)
#### Done
- Confirmed clean repository baseline after separate AKABAK contract commit.
- Re-ran critical regression subset before Batch-UI work:
  - `tests/test_runtime_orchestrator.py`
  - `tests/test_service_export.py`
  - `tests/test_cli_run_sample.py`
- Result: `16 passed` (no failures).

#### Next
- Implement Batch-UI rework in scoped commits:
  - parameter form scaffold
  - sweep controls and payload mapping
  - export presets + advanced panel
  - ETA estimation from SQL history
  - compatibility sweep parse issue reporting
  - docs + tests

### Update 8 (Batch UI Rework)
#### Done
- Batch page reworked from JSON textareas to structured project-style UI.
  - Added `ui/batch_parameter_form.py` with per-field base input + sweep toggle (`start/end/steps`).
  - Added `ui/batch_export_panel.py` with presets (`SPL/Impedance/Polar`) and advanced export-spec table.
  - Added `ui/batch_preview_placeholder.py` (`Preview (.stl)` coming-soon card).
- Batch page layout now mirrors project visual language:
  - summary panel + severity hint
  - two-column body (parameters left, preview/export right)
  - action bar with save/run gating and status pill
- Batch runtime ETA added to summary:
  - SQL helper `list_recent_success_durations()`
  - service API `estimate_batch_runtime()` using median history durations
  - debounced draft re-evaluation wiring in GUI
- Compatibility hardening:
  - invalid sweep definitions now emit `sweep_parse_failed`
  - sweep parse failures force `version_count_preview=0` (no silent ignore)
- Dashboard actions:
  - `Edit Batch` and `Clone Batch` now load real drafts into Batch page.
- New tests:
  - `tests/test_batch_page_ui.py`
  - `tests/test_compatibility_service_batch_sweep_validation.py`
  - `tests/test_eta_estimator.py`

#### Validation
- Targeted regression run:
  - `tests/test_runtime_orchestrator.py`
  - `tests/test_service_export.py`
  - `tests/test_cli_run_sample.py`
  - plus new Batch/ETA/compat tests
- Result: passing (`20 passed` on focused run).

#### Docs
- Added `docs/BATCH_UI.md`.
- Updated:
  - `docs/PROJECT_UI.md`
  - `docs/Wizard_Batch_FieldHints_And_EmptySeverity_Design.md`
  - `docs/ath_update_todo_log.md`
- Replaced unreadable `docs/Wizard_Batch_Optionality_Analysis.md` with valid Markdown pointer.

### Update 9 (Batch UI Korrekturpaket V2)
#### Done
- Batch top summary cards now enforce equal third-width behavior on resize.
- Batch body layout now enforces left/right split near 2/3 : 1/3 with right column width lock.
- Batch parameter rows updated:
  - labels no longer append `(<key>)`
  - `Core` card title rendered as `Mesh`
  - sweep uses segmented button style with green active border
  - active sweep locks/dims base editor
- `R-OSSE` now uses a dedicated single-column object details block and is only shown when `Throat.Profile == R-OSSE`.
- Export panel reworked to structured graph cards:
  - preset buttons (`SPL`, `Impedance`, `Polar`)
  - no free-text advanced table
  - per-graph guide dialog with repo-verified static defaults
  - sweep mode moved into export panel
  - new `mesh_frequency` field included in payload/model
- Compatibility service now returns deterministic proactive fatal-prevention metadata:
  - `prevented_keys`
  - `prevented_reasons`
  - `ui_hint_trigger_key`

#### Tests
- Added:
  - `tests/test_batch_export_panel.py`
  - `tests/test_compatibility_service_batch_fatal_prevention.py`
  - `tests/test_sim_export_settings.py`
- Extended:
  - `tests/test_batch_page_ui.py`

## 2026-02-17
### Update 70 (Batch UI Docs Sync + Behavior Clarification)
#### Done
- Updated `docs/BATCH_UI.md` to match current implementation in code.
  - documents strict 3-card top strip + 2/3 : 1/3 body sizing
  - documents sweep button behavior (active lock/dim, inline inputs, defaults)
  - documents current preview placeholder behavior (`show preview` -> `update preview`)
  - documents structured export panel (`SPL/Impedance/Polar`, guide dialogs, `mesh_frequency`)
  - documents Batch warning/fatal/incomplete field-risk coloring flow (`UiValidationEngine` + `apply_ui_risks`)
  - documents reconcile + sanitize flow that avoids transient `batch_param_not_visible` issues
  - documents sanitization rule that uses current batch compatibility state so valid sweeps are preserved
- Updated `docs/PROJECT_UI.md` companion section and policy wording.
  - clarified project create policy: blocked on `fatal`, allowed on `warn`/`incomplete`
  - updated Batch companion notes to current export/preview implementation
  - added reconcile/sanitize note for Batch compatibility flow

#### Notes
- This update supersedes older text in historical entries that mentioned UI-prevention fields directly in compatibility service outputs.
### Update 71 (Batch UI Korrekturen: Export, Layout, Validierung)
#### Done
- Batch Name input width is now pinned to one third of the available Batch page width.
- Startup flicker/glitch mitigation improved:
  - dark titlebar application moved to explicit show-time window hooks
  - risk helper popup parent anchored to the form widget.
- Batch parameter form refinements:
  - GCurve subgroup headers (`Superellipse`, `Superformula`) are visibility-driven and hide when no matching fields are visible.
  - Enclosure toggle no longer produces the disclosure helper text under the control.
- Export panel redesigned to requested compact UX:
  - top-row `Simulation Mode` (`Free Standing`, `Infinite Baffle`)
  - integer-only `Freq Start [Hz]`, `Freq End [Hz]`, `Points`
  - integer-only optional `Mesh Freq [Hz]`
  - segmented graph preset buttons (`SPL`, `Impedance`, `Polar`) without grouped title boxes
  - compact `Advanced` button that opens structured cards (no JSON/free-text editing)
  - advanced cards for `SPL`, `Impedance`, and up to 3 `Polar` exports with ATH-style fields (including `Polars Name`)
  - touching advanced graph settings deactivates corresponding presets.
- Added export-side validation issue generation for duplicate active polar names:
  - fatal issue id: `export_duplicate_polar_name`.
- Wired export validation issues into Batch validation flow:
  - draft summary/action gating now includes export validation output
  - save/run dialog validation includes export validation output.

#### Tests
- Updated/extended:
  - `tests/test_batch_export_panel.py`
  - `tests/test_sim_export_settings.py`
  - `tests/test_batch_page_ui.py`
- Targeted runs executed with `PYTHONPATH=.`:
  - `tests/test_batch_export_panel.py` -> pass
  - `tests/test_sim_export_settings.py` -> pass
  - `tests/test_batch_page_ui.py` -> pass
  - `tests/test_batch_validation_alignment_fuzz.py` -> pass
  - `tests/test_gui_project_fixed_keys.py` -> pass
  - `tests/test_ui_validation_ranges.py` -> pass
### Update 72 (Batch UI Polish: Layout, Advanced Dialog, Tiles, Sweep Robustness)
#### Done
- Export panel layout polished for symmetry and clipping safety:
  - structured 3-column settings grid
  - balanced rows for simulation/sweep/mesh frequency and frequency start/end/points
  - compact preset + advanced action row without clipping at typical window sizes.
- Preview panel polish:
  - adjusted margins/min-height to prevent preview button clipping at panel bottom.
- Advanced export dialog refined:
  - frameless shell with in-dialog `X` close (no native title bar)
  - scrollable content area for full card visibility
  - removed Variant/Format dropdowns (pipeline-fixed `txt`/`main` behavior)
  - Polar cards include `Norm Angle`.
- Project Manager project list switched from plain list to tile-like icon grid:
  - placeholder preview tile per project
  - project name rendered in tile header
  - double-click open support retained with current selection behavior.
- Sweep robustness fix:
  - incomplete sweep drafts are no longer emitted to payload until `start/end/steps` are valid
  - avoids transient parse-fatal churn while keeping sweep UI active.

#### Tests
- Added: `tests/test_project_manager_ui.py`
- Extended:
  - `tests/test_batch_page_ui.py` (sweep robustness cases)
  - `tests/test_batch_export_panel.py` (polar `norm_angle` payload)
- Targeted runs passed:
  - `tests/test_batch_export_panel.py`
  - `tests/test_batch_page_ui.py`
  - `tests/test_project_manager_ui.py`
  - `tests/test_sim_export_settings.py`
  - `tests/test_batch_validation_alignment_fuzz.py`
  - `tests/test_gui_project_fixed_keys.py`

### Update 73 (Startup Crash Fix + Docs Sync)
#### Done
- Fixed GUI startup crash caused by missing theme color token lookup:
  - root cause: `ui/theme.py` referenced `warning_text`, but token set only provides `warning_text_muted`.
  - fix: sweep warning style now uses `warning_text_muted`.
- Verified GUI launch path again via CLI entrypoint:
  - `python -m app gui`
- Synced UI docs for current status:
  - Batch UI notes now include the startup-token fix under troubleshooting.
  - Project UI notes now explicitly mention the summary-right validation teaser panel.

#### Validation
- `python -m py_compile ui/theme.py`
- `PYTHONPATH=. pytest tests/test_batch_export_panel.py -q`

### Update 74 (Batch STL Preview + Sweep/UI Fixes)
#### Done
- Implemented real Batch STL preview with background generation pipeline:
  - new service pipeline entry: `OrchestratorService.generate_preview_stl(...)`
  - hard-path runtime for preview cfg + ATH export:
    - cfg written to `C:\\Tools\\ATH\\preview_current.cfg`
    - ATH output observed under `C:\\Horns\\...`
  - STL export flags enforced in generated cfg:
    - `Output.STL = 1`
    - `Output.ABECProject = 0`
  - generated STL copied to local preview cache:
    - `%LOCALAPPDATA%\\WUTBatcher\\preview_cache\\`
    - naming: `horn_preview_<timestamp>_<cfgHash>.stl`
    - retention: keep last 10 STL files
    - startup cache cleanup: remove files older than 7 days (cache dir only)
- Added non-blocking preview worker in GUI:
  - `QThread`-based `_BatchPreviewWorker`
  - cancellation/obsolete handling when toggled off or restarted
  - loader state in preview canvas while generation is in-flight
- Replaced preview placeholder with actual preview panel + controls:
  - toggle `On/Off`
  - `Update Preview` action
  - inline error text (non-modal)
  - last successful mesh remains visible on failures
- Added STL renderer widget:
  - `ui/stl_preview_widget.py`
  - transparent background + light glossy material
  - orbit/zoom controls
  - binary/ascii STL parsing without additional heavy deps
- Sweep/UI fixes:
  - sweep buttons and sweep input fields aligned to uniform control height/width
  - sweep blink/toggle state handling hardened for repeated toggles and reset paths
- Export dropdown theming refined for dark mode:
  - styled drop-down arrow, popup view, selection/disabled states for Batch export combos

#### Validation
- `python -m py_compile app/services.py app/gui.py ui/batch_preview_placeholder.py ui/stl_preview_widget.py ui/batch_parameter_form.py ui/batch_export_panel.py ui/theme.py`
- `PYTHONPATH=. pytest tests/test_batch_page_ui.py tests/test_batch_export_panel.py tests/test_project_form_ui.py -q`
- `PYTHONPATH=. pytest tests/test_batch_validation_alignment_fuzz.py tests/test_project_validation_alignment_fuzz.py tests/test_gui_project_fixed_keys.py -q`

### Update 75 (Preview E2E Stabilization + Auto Refresh)
#### Done
- Reworked Batch preview UX to auto-refresh mode:
  - removed manual preview toggle/update controls from preview card
  - preview now auto-requests on batch draft changes (debounced in `MainWindow`)
  - removed filename/status line under canvas so the mesh viewport uses maximal panel height
- Added robust software STL renderer fallback when Qt3D is unavailable:
  - `ui/stl_preview_widget.py` now renders STL triangles in a translucent QWidget painter fallback
  - keeps orbit drag + wheel zoom behavior without Qt3D modules
- Hardened preview generation for compatibility/UI edge cases:
  - preview resolver path stays best-effort
  - when resolver reports `batch_param_not_visible`, those keys are ignored for preview fallback generation
  - result payload now includes `ignored_hidden_keys` for diagnostics
- Aligned compatibility visibility for `Mesh.InterfaceOffset`:
  - removed enclosure-only visibility gate in ATH ruleset (`visibility_mesh_interfaceoffset_*`)
  - `Mesh.InterfaceOffset` now no longer triggers false `batch_param_not_visible` for the validated guide-style OS-SE baseline
- Investigated OS-SE/Coverage baseline + morph rectangle case against local ATH files:
  - reproduced and validated with `C:\\Tools\\ATH\\Tritonia.cfg`
  - documented findings and source links in `docs/PREVIEW_INVESTIGATION_2026-02-17.md`

#### Validation
- `python -m compileall app/services.py app/gui.py ui/batch_preview_placeholder.py ui/stl_preview_widget.py`
- `python -m pytest tests/test_preview_pipeline.py -q`
- `python -m pytest tests/test_batch_page_ui.py tests/test_service_export.py -q`

## 2026-02-20
### Update 76 (Cross-Page UI Language Alignment + Run Fullscreen)
#### Done
- Applied Batch-style visual language to Dashboard and Project pages while keeping the Project two-column form layout intact.
  - Dashboard now uses card/action-bar composition and button hierarchy (`BatchPrimaryButton`, `BatchSecondaryButton`, `BatchGhostButton`).
  - Project action CTA now follows the Batch primary button style.
- Updated Project Manager interaction styling to remove blue accents:
  - tile hover now uses thicker neutral border only (no white/filled hover)
  - selected tile border moved to neutral gray
  - action buttons use dedicated neutral style (`ProjectManagerButton`).
- Improved Project Manager horn thumbnail framing:
  - preview tiles now use center-cropped zoom rendering for a closer default horn view.
- Reworked Run page presentation and run flow behavior:
  - run screen redesigned as centered dark shell with cleaner status hierarchy
  - run starts in true fullscreen presentation mode
  - window is forced topmost/foreground at run start and restored after run
  - run state helpers added (`running`, `finished`, `failed`) and back-to-dashboard action enabled after completion.

#### Validation
- `python -m compileall app ui`
- `python -m pytest tests/test_project_manager_ui.py tests/test_project_form_ui.py -q`
- `python -m pytest tests/test_batch_page_ui.py -q` (known pre-existing failures in current branch; unrelated to this pass)

## 2026-08-01
### Update 77 (Native Stability Closure + Process Ownership)
#### Done
- Reconnected all product branch heads on `main` without dropping product-tree
  content; historical/audit branches and recovery tag were retained.
- Hardened AKABAK/VACS automation around exact startup popups, recreated/hidden
  main windows, post-solve VACS handoff, localized Save As dialogs, progress
  heartbeats and bounded delayed retries.
- Enforced run-owned PID cleanup using executable path, parent relation and
  start time; global image-name cleanup is prohibited and contaminated starts
  block instead of killing unknown applications.
- Preserved the installed ATH/Gmsh/AKABAK/VACS setup and added a read-only
  default Doctor path. No tool was reinstalled or reconfigured.
- Audited the active library (7 canonical projects, 0 errors, 37 historical
  duplicate-plan warnings) and left detached/inactive libraries untouched.
- Added bounded `fast`, `resource` and `baseline` runner profiles. The resource
  profile now uses 20 minutes inactivity / 40 minutes hard limit; product/UI
  defaults remain unchanged.
- Reproduced a Windows Analyzer cleanup lock and fixed the underlying SQLite
  plot connection so the native database handle is closed deterministically.
- Documented the two exact VACS startup-note signatures; true fresh-VM/profile
  validation remains explicitly deferred.

#### Real gates
- Resource batch: 2/2 full ATH -> AKABAK -> VACS cycles succeeded, 8/8 current
  exports persisted, exact native cleanup verified.
- Fast batch: 5/5 cycles succeeded, 20/20 exports persisted, exact native
  cleanup verified.
- Separate heavier service case: V001 succeeded; V002 reached the old
  20-minute hard limit with advancing CPU/heartbeats and was controlledly
  stopped. This is not reported as 2/2 success and was not rerun as a gate.

#### Automated validation
- Focused AKABAK/profile/harness checks: 80 passed.
- Analyzer handle and UI regression group: 53 passed.
- Definitive clean full suite on `d9e4563`: 725 passed, 10 skipped, 0 failed
  in 693.89 s (9,235 existing Qt deprecation warnings).

### Update 78 (Production GUI Acceptance + VACS/DB Round Trip)
#### Done
- Completed a representative fast real-tool batch through the normal Batcher
  GUI and its production service/worker start path.
- Verified the final visible GUI state, successful version/run records, four
  current VACS graph exports and exact owned-process cleanup.
- Proved each raw VACS TXT is byte-identical to its semantic export copy.
- Independently compared every exported numeric value with both SQLite
  stores: 342/342 complex polar samples and 24/24 graph samples matched
  exactly (`max_abs_delta = 0`), and the relevant global/project rows were
  identical.
- Classified two earlier disappearing GUI attempts as externally terminated
  by the parallel full-suite watcher, not as application crashes; definitive
  GUI acceptance was serialized after the suite.

#### Evidence
- `docs/validation/evidence/gui_vacs_roundtrip_b008_2026-08-01.json`
- Run `914edb8e-78a1-4c33-bdc5-9df3bdc72ad2`, B008/V008: 360.13 s,
  GUI `done`, DB `succeeded`, 4/4 exports, zero relevant post-state processes.










