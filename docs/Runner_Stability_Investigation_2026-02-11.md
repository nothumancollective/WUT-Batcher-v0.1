# Runner Stability Investigation (2026-02-11)

## Scope
- Target: `Runner/wut_abec_batch_runner.py` plus orchestration path in `app/cli.py`.
- Real test source: `Project_P005`, Batch `Batch_B001`.
- Goal: identify design-level fragility, test fixes iteratively in safe copies, and validate practical stability.
- Extension (same date): implement new naming convention and fully dynamic VACS window export:
  - `Result_<ver>A.txt` = ATH result (creator stage)
  - VACS exports start at `B` and continue dynamically (`B..Z, AA..`)

## Baseline Reproduction
- Baseline failing run (before fixes): `Project_P005/batches/Batch_B001`.
- Symptom: export drift on second plot window (`V001B`) with log pattern:
  - `Export form NOT found after F7.`
  - `Export as picture [] (TForm_Picture)` appears instead of `Data Export`.
- Secondary symptom: orchestrator crash while streaming logs (`UnicodeDecodeError`) masked the real runner failure.

## Identified Weaknesses

1. `W1` Export-focus drift between VACS child windows (high impact).
- Evidence: repeated failure at second/third export window while first export often succeeds.
- Root cause hypothesis confirmed in tests: focus/active target becomes unstable after child-window close sequence.

2. `W2` Encoding fragility in orchestration stream handling (high impact).
- `app/cli.py` decoded subprocess output with default locale; mixed bytes crashed streaming mode.

3. `W3` Encoding fragility in runner status/retry logging (high impact on some Python/console setups).
- Unicode symbols (`✓`, `⚠`, emoji) caused `UnicodeEncodeError` on CP1252 stdout.

4. `W4` Structural debt in runner export function (medium risk).
- `export_current_plot_to_file()` contains large dead/duplicated code regions from prior patch history.
- Not the direct runtime trigger in the active path, but increases maintenance and regression risk.

## Iterative Solution Testing

### Iteration A: Better plot targeting + F7 retry
- Change: use stored plot handle/center before F7, add retry + picture-dialog cleanup.
- Result: improved diagnostics, but still failed intermittently on later plot exports.

### Iteration B: Context menu fallback trigger
- Change: second trigger mode via context-menu sequence (after F7 fails).
- Result: insufficient alone; still drifted in failing runs.

### Iteration C: Encoding hardening
- Change set:
  - `app/cli.py` stream decode switched to byte-safe fallback decoding.
  - `Runner/status_tracker_v2.py` and `Runner/retry_handler_v2.py` converted to ASCII-safe logging.
- Result: no more decode/encode crashes; runner errors now visible and actionable.

### Iteration D (effective): keep VACS child windows open during one version export
- Change: stop closing each plot child with `Ctrl+F4` after each single export.
- Rationale: closing children was shifting focus to utility windows/dialog paths and caused trigger drift.
- Result: stable full exports across all windows (`A/B/C`) and all versions in repeated real runs.

### Iteration E (naming + dynamic windows + DPI hardening)
- Changes:
  - ATH creator switched from `Result_<ver>D.txt` to `Result_<ver>A.txt`.
  - VACS suffix allocation switched to dynamic export sequence starting at `B`.
  - VACS discovery/export logic updated to work with variable plot-window counts and write index mapping accordingly.
  - Added DPI-awareness bootstrap (`SetProcessDpiAwarenessContext` / fallback APIs) and reduced dependence on absolute screen assumptions.
  - Compatibility collection now reads ATH result incidents from `A` and legacy `D`.
  - Export validation now uses dynamic suffix discovery (index-driven if available), and ignores ATH `A` for VACS validation.

### Iteration F (structural cleanup in export path)
- Change:
  - Removed a large unreachable duplicate legacy block inside `export_current_plot_to_file()` in `Runner/wut_abec_batch_runner.py`.
- Rationale:
  - The duplicate code was not executed at runtime, but significantly increased maintenance complexity and regression risk.
- Result:
  - Active runtime behavior stayed unchanged, while export logic became auditable and easier to evolve safely.

## Final Implemented Changes

1. `Runner/wut_abec_batch_runner.py`
- Added stronger plot focusing before export trigger.
- Added guarded trigger modes and diagnostics for missing export dialog.
- Re-resolved child window by title before export click.
- **Critical fix:** removed per-export `close_childwindow_confirm()` call to prevent focus drift.
- Removed unreachable duplicate legacy code in `export_current_plot_to_file()`.

2. `app/cli.py`
- `run_and_log()` now streams subprocess output as bytes with robust fallback decoding.

3. `Runner/status_tracker_v2.py`
- Rewritten with ASCII-safe log output and same tracking semantics.
- Loader now accepts `utf-8-sig` (BOM-tolerant).

4. `Runner/retry_handler_v2.py`
- Rewritten with ASCII-safe logs, same retry/cleanup behavior.

5. `Runner/wut_ath_batch_creator_v2.py`
- Writes `Result_<ver>A.txt` (ATH result) instead of `Result_<ver>D.txt`.

6. `Runner/validators.py`
- Reworked for dynamic VACS suffix validation via `Result_<ver>_index.txt` or file discovery.
- No fixed `A/B/C` assumption anymore.

7. `app/compatibility_incidents.py`
- Reads ATH result incidents from both `Result_V*A.txt` (new) and `Result_V*D.txt` (legacy).

## Validation Runs (real runner)

### Failing reference runs (before final fix)
- `Batch_B001`, `Batch_B001_exp2`, `Batch_B001_exp4`: repeated failures at `B`/`C` exports after `F7`.

### Passing validation runs (after final fix)
- `Batch_B001_exp5`: completed `3/3` jobs, all `A/B/C` exports present, no retries.
- `Batch_B001_exp6`: repeated pass, completed `3/3` jobs, all `A/B/C` exports present, no retries.
- Status proof:
  - `.../Batch_B001_exp5/status.json` -> `completed=3, failed=0`
  - `.../Batch_B001_exp6/status.json` -> `completed=3, failed=0`

### Passing validation runs (after naming-scheme extension)
- `Batch_B001_exp9`: completed `3/3` jobs, no retries.
- Result layout per version confirmed:
  - `Result_VxxxA.txt` (ATH)
  - `Result_VxxxB.txt`, `Result_VxxxC.txt`, `Result_VxxxD.txt` (VACS windows)
  - `Result_Vxxx_index.txt` (suffix/title map)

### Additional run after structural cleanup
- `Batch_B001_exp11`: failed early (`TimeoutError`) in solve stage for `V001` before VACS export started.
- Interpretation:
  - This run does **not** indicate an export-window regression.
  - It confirms a separate environment/timing instability in the solve readiness path (AKABAK/UI timing), which is outside the specific export drift fix.

## Residual Risks / Next Hardening

1. Solve readiness timing remains a separate risk path.
- `Batch_B001_exp11` showed timeout before export starts; this is likely AKABAK/UI readiness timing, not VACS export routing.
- Hardening candidate: explicit multi-signal readiness check (image + process-state + top-window-state) with adaptive timeout.

2. Remaining display-agnostic risk:
- UI automation is significantly less resolution/scale-coupled now, but end-to-end determinism still depends on VACS/AKABAK window modality and timing.
- This should be validated additionally on a second physical display profile (e.g., 1920x1080 @ 100%) because the current VM run was at 4K/150%.

3. pywinauto warning remains:
- `32-bit application should be automated using 32-bit Python`.
- Recommendation: provide optional 32-bit Python runner profile for maximal UI automation stability.

## Conclusion
- Primary instability (`second export window drift`) was design-related and reproducible.
- Best-performing fix was behavioral: keep child windows open while exporting all plots for a version.
- Combined with encoding hardening and dynamic export naming, runner now completes real multi-version runs reliably in repeated tests on the current VM.

## Update (2026-02-11, second hardening pass)

### What was changed
- `Runner/wut_abec_batch_runner.py`
  - Added stronger AKABAK modal handling:
    - dialog text extraction now includes `window.texts()`.
    - logs include button labels.
    - fatal dialogs (`Access violation`, `exception`, `fatal`) are detected and surfaced explicitly.
  - Added strict handling for stale `Open File` dialogs:
    - dedicated open-dialog discovery by PID.
    - forced close routines for `Open File` and `Import` dialogs.
    - runner now fails fast if these dialogs cannot be closed.
  - Added import-dialog instrumentation:
    - writes `Logs/akabak_import_dialog_controls.txt` to inspect real controls.
  - Added solve-loop hardening:
    - one-time `F5` retrigger if no start signal appears.
    - robust `locateOnScreen` wrapper to avoid `needle dimension(s) exceed...` crashes.
    - dynamic status-bar region recomputation each loop iteration.
    - optional soft fallback when status image matching fails.
  - Added VACS plot-timeout diagnostics (`vacs_windows_<ver>_plot_timeout.txt`) and F7 retrigger attempts.
  - Added clean-state startup per attempt (`AKABAK/VACS` cleanup before run).
- `Runner/status_tracker_v2.py`
  - Added `reset_for_new_run(...)`.
- `Runner/wut_abec_batch_runner.py` + `app/cli.py`
  - New default behavior: fresh batch run resets queue jobs to pending.
  - Optional resume mode:
    - runner: `--resume`
    - app CLI: `batch run --resume-runner`

### Live validation results (same day)
- Command used repeatedly:
  - `python -m app.cli batch run --project-id P005 --batch-id B001 --stream`
- Confirmed improvements:
  - stale `status.json` no longer causes silent skipping of `V001` (fresh run starts all jobs).
  - AKABAK fatal message is no longer ignored; it is logged explicitly with traceback context.
  - `needle dimension(s) exceed the haystack image or region dimensions` no longer crashes the solve loop after adding safe image matching.
- Remaining blocker:
  - `V001` consistently reaches `solve_start`, but no reliable solve-progress signal appears and no VACS plot windows are generated afterward.
  - Typical terminal failure in latest runs:
    - `Solve start not detected (no ready/processing signal).`
    - or downstream `VACS plot windows did not appear in time.`
  - Diagnostics show:
    - AKABAK main window often remains `Akabak-Demo - (new)`.
    - Import dialog is frequently not shown in these failing runs.
    - VACS timeout dump contains only `VacsViewer - (new)` + utility windows, no plot windows.

### Interpreted root cause
- The current unresolved path is no longer a simple export-window drift.
- The unstable segment is now earlier: deterministic project-open/import into AKABAK before solve.
- If no actual model import happens, `F5` gives no usable progression signal and `F7` yields no plot windows.

### Recommended next iteration
- Replace heuristic open/import flow with deterministic control-driven sequence based on dialog controls:
  - confirm model is loaded before `F5` (not only that dialogs closed).
  - add explicit post-open verification step (state assertion) and abort early when state is invalid.
- Add AKABAK-state probe independent of status-bar images (e.g., control-state/text-based) to reduce DPI/theme coupling further.

## AKABAK Temp-File Investigation (2026-02-11)

Ziel: Pruefen, ob AKABAK nach erfolgreichem Solve/F7 irgendwo automatisch Ergebnisdaten als Dateien (temp/hidden) ablegt, die wir direkt auswerten koennten, um den VACS-Export zu umgehen.

### Setup
- Controlled run mit 1 Job (V001) in einem temporaren Batch-Ordner:
  - `C:\Users\maximilianheinze\AppData\Local\Temp\Batch_AKABAK_TEMP_20260211_134501`
- Marker-Datei zur Diff-Baseline:
  - `C:\Users\maximilianheinze\AppData\Local\Temp\akabak_marker_20260211_134501.txt`
- Runner gestartet mit `PYTHONIOENCODING=utf-8`, weil die alte Runner-Version Unicode-Symbole auf CP1252 stdout schreibt.

### Execution
- ATH Creator generiert ABEC-Projekt:
  - `C:\Horns\V001\ABEC_FreeStanding\Project.abec`
- Runner-Ablauf bis Solve:
  - `Solve fertig: V001` war im Run-Log sichtbar.
- Danach wurde F7 nach VACS getriggert; VACS Export schlug fehl (Datei erschien nicht), ist aber fuer diese Frage unerheblich: wir wollten sehen, ob AKABAK/VACS intern Dateien erzeugt.

### Findings (filesystem diff nach Marker)
- `C:\Horns\V001\...` enthaelt nur Input-Dateien und die vom Creator geschriebenen Dateien:
  - `config.txt`, `Project.abec`, `nodes.txt`, `driver.txt`, `solving.txt`, `observation.txt`
  - Keine zusaetzlichen Result-/Cache-Dateien (keine `*.dat/*.bin/*.vcs/*.tmp` etc.).
- `%TEMP%` (`C:\Users\...\AppData\Local\Temp`) zeigte ausserhalb des Batch-Ordners keine neuen/veraenderten Dateien im Zeitfenster.
- `AppData\Local\RDTeam\` (z.B. `Akabak.ini`, `VACS.ini`) wurde im Zeitfenster nicht als Ergebnis-Artifact beschrieben (keine neuen Datenfiles).
- Installationsordner `C:\Program Files (x86)\RDTeam\AKABAK` und `...\VACSVIEWER_32` hatten keine neuen/veraenderten Dateien im Zeitfenster.

### Conclusion
- In diesem Testlauf legt AKABAK (und auch VACS) die eigentlichen Ergebnisdaten nicht automatisch als Dateien auf Disk ab, die man einfach "abgreifen" koennte.
- Das passt zum beobachteten Verhalten: der Datenfluss scheint zur Visualisierung/Export eher ueber IPC/DDE zwischen AKABAK und VacsViewer zu laufen, und die ASCII-Dateien entstehen erst durch den expliziten Export.

### Practical Implication
- "VACS Export komplett sparen" durch das Lesen versteckter Temp-Dateien ist mit dem aktuellen Pipeline-Setup sehr unwahrscheinlich.
- Wenn wir VACS umgehen wollen, brauchen wir stattdessen eine explizite, deterministische Export-Quelle:
  - Entweder AKABAK/ABEC direkt so konfigurieren, dass es Ergebnisdaten nach Solve automatisch in Files schreibt (falls durch Observation/Solver-Syntax moeglich).
  - Oder den Export weiterhin ueber VacsViewer machen, aber den Export-Pfad technisch stabiler machen (z.B. 32-bit Python fuer 32-bit VACS/AKABAK Automation, robustere Dialog-Steuerung).

## VACS Import Artifact Investigation (2026-02-11)

Ziel: Pruefen, ob VacsViewer beim Import der AKABAK/ABEC Daten (F7 in AKABAK) irgendwelche verwertbaren Dateien (Cache/Temp/Results) auf Disk ablegt, die man ohne den fehleranfaelligen UI-Export auslesen koennte.

### Method (controlled import-only probe)
- Import-only automation (kein VACS "Export Data"/"Save..." Schritt):
  - `tools/vacs_import_probe.py` oeffnet `Project.abec` in AKABAK, startet Solve (F5), sendet danach F7 und prueft heuristisch, ob Plot-Fenster in VACS auftauchen (`import_detected=1/0`).
- Filesystem diff via Marker-Zeitstempel:
  - `tools/vacs_import_filesystem_probe.ps1` setzt Marker-Zeit, fuehrt den Import-Probe aus und listet danach alle Dateien mit `LastWriteTime >= markerTime` in typischen Ablageorten.
- Scanned roots (targeted):
  - `%LOCALAPPDATA%\\RDTeam`
  - `%APPDATA%\\RDTeam` (falls vorhanden)
  - `C:\\ProgramData\\RDTeam` (falls vorhanden)
  - `%LOCALAPPDATA%\\VirtualStore`
  - `C:\\Horns\\V001\\ABEC_FreeStanding` (Projektordner)
  - `C:\\Horns\\V001`
  - `%TEMP%`: nur Eintraege/Unterordner, die seit Marker `LastWriteTime` geaendert hatten (um Temp nicht komplett rekursiv zu scannen)

### Runs
- 2026-02-11 14:06-14:08: `import_detected=1`, Probe exit code `0`.
- 2026-02-11 14:09-14:12: `import_detected=1`, Probe exit code `0`, Prozesse bewusst offen gelassen waehrend Scan (`-KeepProcesses`), danach manuell beendet.
- Logs/TSV liegen unter: `%TEMP%\\vacs_import_probe\\`

### Findings
- In beiden Runs tauchten nach erfolgreichem Import (`import_detected=1`) keine neuen/veraenderten Dateien in den gescannten RDTeam/VirtualStore/Projekt/Horns-Verzeichnissen auf.
- Auch in `%TEMP%` wurden ausser den Probe-eigenen Marker/Log/TSV-Dateien keine weiteren neuen/veraenderten Eintraege erkannt.

### Conclusion
- VacsViewer legt die importierten Ergebnisdaten in diesem Workflow sehr wahrscheinlich nicht als persistente Dateien ab (kein beobachtbarer Cache/Temp-Artifact im Filesystem).
- Das unterstuetzt die Hypothese: AKABAK -> VACS Datenuebergabe passiert primär in-memory/IPC, und die Dateien entstehen erst beim expliziten Export.
- Einschraenkung: extrem kurzlebige Temp-Dateien, die im gleichen Zeitfenster erzeugt und wieder geloescht werden, koennen mit diesem Marker-basierten Scan prinzipbedingt durchrutschen (dafuer waere Process/File-IO Tracing wie ProcMon notwendig).

### Follow-up: Akabak.ini `SaveResultFiles_Tmp` flag
- Observation: `C:\\Users\\maximilianheinze\\AppData\\Local\\RDTeam\\Akabak.ini` enthaelt `SaveResultFiles_Tmp=0` (Default in dieser Umgebung).
- Test: Flag temporär auf `SaveResultFiles_Tmp=1` gesetzt, dann denselben import-only Probe ausgefuehrt.
- Result: Trotz `import_detected=1` erschienen weiterhin keine neuen/veraenderten Dateien ausserhalb der Probe-eigenen Logs/Marker/TSV (kein beobachtbares Ergebnis-/Tempfile in RDTeam/Temp/Projekt/Horns).
- Safety: INI wurde nach dem Test wieder auf den Originalzustand restauriert (`SaveResultFiles_Tmp=0`).

### Follow-up: Kurzlebige Tempfiles (ProcMon / FileSystemWatcher)
- ProcMon (Sysinternals Process Monitor) wuerde auch extrem kurzlebige Create/Write/Delete Events zeigen, benoetigt aber Admin-Rechte (Kernel-Treiber).
  - In dieser Session ohne Admin-Rechte lieferte ein ProcMon-Capture nur einen CSV-Header ohne Events (keine verwertbare Aussage moeglich).
- Fallback ohne Admin: `tools/vacs_import_fswatch_probe.ps1` (FileSystemWatcher in den relevanten Ordnern).
  - Watch roots: `%LOCALAPPDATA%\\RDTeam`, `%LOCALAPPDATA%\\VirtualStore`, Projektordner, `%TEMP%` (TEMP gefiltert).
  - Ergebnis: waehrend `import_detected=1` wurden keine (relevanten) Datei-Create/Change/Delete/Rename Events in diesen Roots beobachtet.

### ProcMon (Admin) - HowTo (kurz)
Wenn ProcMon als Administrator laeuft, kann man die Frage "schreibt VACS/AKABAK irgendwo Dateien beim Import?" sauber beantworten:
- ProcMon starten: auf ARM64 Windows `tools/sysinternals/Procmon64a.exe` als Admin.
- Filter setzen (Filter -> Filter...):
  - `Process Name` `is` `akabak.exe` -> `Include`
  - `Process Name` `is` `vacsviewer_32.exe` -> `Include`
  - optional: `Process Name` `is` `procmon64a.exe` -> `Exclude`
- Capture Reset: `Ctrl+X` (Clear) und `Ctrl+E` (Start Capture).
- Import ausloesen (Runner/Probe): `python tools/vacs_import_probe.py --project-abec C:\Horns\V001\ABEC_FreeStanding\Project.abec ...`
- Capture stoppen: `Ctrl+E`, dann `File -> Save...` als CSV.
- Auswertung der CSV: `python tools/procmon_analyze_csv.py --csv <export.csv>`.

### ProcMon (Admin) - Findings aus realem Capture
- Capture source: `tools/procmon_vacs_admin.CSV` (vom Benutzer erstellt waehrend: AKABAK Projekt offen -> Solve -> F7 Import nach VACS).
- Rows (gefiltert auf Prozesse): `86842`
- Observed operations (nur diese 14): `CreateFile` + `WriteFile` + `SetRenameInformationFile` + diverse `Reg*` (Registry open/query/set/enum).
- Key result: **VACS schreibt beim Import keine Dateien**.
  - `vacsviewer_32.exe`: `Top file writes (heuristic): none`
  - `akabak.exe`: `WriteFile`/`SetRenameInformationFile` betrafen ausschliesslich Windows Explorer Icon-/Thumb-Cache, nicht RDTeam/VACS/Resultate.
- Kein Hinweis auf file-basierte IPC:
  - Keine `\\Device\\NamedPipe\\...` oder `\\Device\\Mailslot\\...` Pfade in diesem Capture.
- Gelesene Konfig (typisch):
  - `C:\\Users\\maximilianheinze\\AppData\\Local\\RDTeam\\VACS.ini`
  - `C:\\Users\\maximilianheinze\\AppData\\Local\\RDTeam\\Akabak.ini`
  - zusaetzlich `C:\\ProgramData\\RDTeam\\VACS.ini` / `C:\\ProgramData\\RDTeam\\Akabak.ini`

Conclusion: auch mit Admin-Prozess-/File-IO Tracing gibt es keinen Hinweis, dass VACS beim Import versteckte Ergebnisdateien persistiert, die man ohne den Export-Schritt nutzen koennte.

## V3 Prototype Runner (stepwise, no screenshot matching)

Ziel: Ein separater Runner (neue Datei) der die "urspruengliche" Runner-Version nicht veraendert, aber die instabilsten Teile (AKABAK project-open + solve detection + F7 confirmation + VACS import detection) robust macht, ohne DPI-/Screenshot-Abhaengigkeit.

### Implemented building blocks (2026-02-11)
- Datei: `Runner/wut_abec_batch_runner_v3.py` (neu)
- Load verification (AKABAK):
  - Project geladen gilt als verifiziert, wenn der AKABAK-Window-Title den Token `ABEC_FreeStanding` (aus dem Projektpfad) enthaelt.
  - Wichtige Erkenntnis: es koennen mehrere AKABAK Main-Windows parallel existieren (`Akabak-Demo - (new)` + `Akabak-Demo - <Project>`). Der V3-Prototyp bevorzugt deshalb immer das Window, dessen Title den Projekt-Token enthaelt.
- Solve detection (AKABAK) ohne Bilder:
  - Liest die groesste `TMemo` (Log Calc) im AKABAK-Fenster und erkennt Solve-Completion ueber `Calculation time` im Tail + Quiet-Periode.
  - Wenn der Log nach F5 nicht mehr aendert, aber bereits `Calculation time` im Tail enthaelt, wird das als "already solved" behandelt.
- F7 -> VACS (AKABAK Confirmations):
  - Beobachtung: AKABAK zeigt beim F7 teils *mehrere* Confirm-Dialoge (`Confirm` #32770 und `Confirmation` / `TForm_OperationQuery`). Ohne das Wegklicken importiert VACS nicht.
  - V3 bestaetigt daher alle `Confirm/Confirmation/Bestätigen` Dialoge (Enter) best-effort.
- Import verification (VACS) ohne Export:
  - Liest VACS UIA-Descendants und sammelt Plot-Titel (z.B. `Radiation Impedance - ...`, `LE (scripts) - ...`).
  - Damit kann man sicher feststellen: Import hat wirklich stattgefunden (und haengt nicht blind in einem Timeout).
- Export-dialog probe (VACS):
  - `IO -> Export data...` kann durch modale/transiente VACS-Forms blockiert sein (z.B. `TForm_Picture`, `TForm_Export`, `TForm_Edit`), die das Main-Window disabled lassen.
  - V3 schliesst daher alle `TForm_*` ausser `TForm_DatMain` bevor es `menu_select("IO->Export data...")` ausfuehrt.

### How to run (local probe with attached project)
- Project: `C:\\Horns\\Test\\ABEC_FreeStanding\\Project.abec`
- Import probe: `python Runner\\wut_abec_batch_runner_v3.py --project-abec C:\\Horns\\Test\\ABEC_FreeStanding\\Project.abec --to-vacs --export-probe`

### Follow-up Fixes after failing clean runs
- Problem observed:
  - AKABAK startup/example popup could remain open and interfere with deterministic key flow.
  - F7 confirmation handling used global title matching and could target non-AKABAK windows.
  - Solve completion check was too broad (`Calculation time`) and could finish early before real `BEM solved`.
- Fixes in `Runner/wut_abec_batch_runner_v3.py`:
  - Close AKABAK startup forms (`Example Files`/welcome-like forms) before project open.
  - Restrict F7 confirmation dialog handling to AKABAK process PID only.
  - Solve completion now requires that `BEM solved` count increases after F5 (not only `Calculation time` text).

### Verification (clean start)
- Command:
  - `python Runner\\wut_abec_batch_runner_v3.py --clean --project-abec C:\\Horns\\Test\\ABEC_FreeStanding\\Project.abec --solve --to-vacs --export-probe`
- Result:
  - AKABAK load OK (`Akabak-Demo - ABEC_FreeStanding`)
  - Solve detected robustly (`solve_duration_s` around 12s in test)
  - VACS import detected (`vacs_plot_count=3`)
  - Export dialog reachable (`export_dialog_title='Data Export'`)

### V3 Export hardening (child-window safety + wrong-window recovery)
- Problem (reproduced):
  - Export often used the wrong graph or got stuck when transient VACS windows (`TForm_Export`, `TForm_Edit`, `TForm_Picture`) stayed open and disabled the main menu.
  - Pure focus clicks were not sufficient; VACS could still export a previously active graph.
- Implemented in `Runner/wut_abec_batch_runner_v3.py`:
  - Added process-bound VACS guardrails:
    - enumerate VACS windows by PID and close unexpected `TForm_*` blockers before each export action.
  - Added robust graph targeting:
    - detect graph windows via UIA (`class=TForm_DatGraph`, `control_type=Window`).
    - activate graph by title before export.
  - Added export recovery loop:
    - if `IO -> Export data...` is disabled/fails, recover focus and retry instead of hanging.
  - Added save-dialog robustness:
    - click `&Save...`, drive `#32770` save dialog directly, write absolute path, handle overwrite prompts.
  - Added correctness verification:
    - parse `Graph_Caption` from the exported file.
    - if caption does not match requested graph title, rotate active graph (`Ctrl+F6`) and retry.
    - this avoids silent wrong-graph exports.
  - New CLI options:
    - `--export-all-dir <dir>`: export all discovered VACS graph windows.
    - `--export-prefix <name>`: filename prefix for export batch.

### Verification (end-to-end with export per graph)
- Command:
  - `python Runner\\wut_abec_batch_runner_v3.py --clean --project-abec C:\\Horns\\Test\\ABEC_FreeStanding\\Project.abec --solve --solve-timeout-s 600 --to-vacs --vacs-timeout-s 180 --export-all-dir tmp_export_probe5 --export-prefix testrun`
- Result:
  - Flow completed through all stages (AKABAK load -> solve -> F7 import -> VACS export loop).
  - 3 export files created with distinct, validated graph captions:
    - `tmp_export_probe5\\testrun_01_LE_scripts_-_LE_Spectrum_2.txt` -> `Graph_Caption='LE (scripts) - LE_Spectrum #2'`
    - `tmp_export_probe5\\testrun_02_LE_scripts_-_LE_Spectrum_3.txt` -> `Graph_Caption='LE (scripts) - LE_Spectrum #3'`
    - `tmp_export_probe5\\testrun_03_Radiation_Impedance_-_Radiation_Impedance_1.txt` -> `Graph_Caption='Radiation Impedance - Radiation_Impedance #1'`
- Interpretation:
  - The new loop no longer silently exports the same graph repeatedly.
  - Wrong-window states are actively cleaned, which prevents the previous dead-end behavior.

## Research: AKABAK Completion + VACS Export Semantics (2026-02-11)

Ziel: Antworten auf
1) Wie erkennt der Runner, dass AKABAK fertig ist (ohne fixed timer)?
2) Was exportiert VACS/VacsViewer genau und was ist fuer unser Ziel ("tidy data" ueber alle Versionen/Batches) sinnvoll?

### 1) AKABAK: Wie wird "fertig" erkannt (V3 Runner)?

Status in `Runner/wut_abec_batch_runner_v3.py`:
- Kein fixer Sleep-Timer fuer "Solve fertig".
- Dynamische Erkennung ueber den AKABAK Log-Text (TMemo "Log Calc"):
  - Baseline: Runner liest vor `F5` den aktuell groessten `TMemo`-Text und zaehlt die Vorkommen von `BEM solved`.
  - Start: es wird innerhalb `start_timeout_s` erwartet, dass sich der TMemo-Text aendert (Signal: Solve hat begonnen).
  - Completion: Solve gilt erst als fertig, wenn
    - `BEM solved`-Count gegenueber Baseline angestiegen ist, und
    - der Log fuer mindestens `quiet_s` Sekunden unveraendert blieb (Quiet Window).
- Timeouts (um Haenger zu vermeiden):
  - `--solve-timeout-s` (Default: 25min) ist ein *harte Obergrenze*. Bei groesseren Projekten muss dieser Wert hoer gesetzt werden.
  - `start_timeout_s` (Default: 15s) ist *nur* fuer den Start-Signal-Check relevant; bei sehr langsamen Starts kann auch dieser hoeher gesetzt werden.

Praktische Konsequenz:
- Das Verhalten skaliert mit Projekt-/Rechenzeit, solange `--solve-timeout-s` gross genug ist.
- Wenn AKABAK in bestimmten Projekten keinen vernuenftig lesbaren "BEM solved" Log schreibt (oder der Runner das falsche TMemo erwischt), muessen wir die Completion-Signale erweitern (z.B. zusaetzlich Statusbar/Window-state/Progress-Dialog).

### 2) VACS/VacsViewer: Graph-Typen, Datenmodell, Exportformate

#### Quellen (Recherche)
- Website (R&D-Team VACS):
  - `https://www.randteam.de/VACS/Index.html`
  - `https://www.randteam.de/VACS/VACS-Features.html`
  - `https://www.randteam.de/VACS/VACS-Docs.html` (inkl. Import Control Settings PDFs)
  - `https://www.randteam.de/VACS/VACS-License.html`
- Lokale VacsViewer Installationsdoku (aus dieser VM):
  - `C:\\Program Files (x86)\\RDTeam\\VACSVIEWER_32\\Vacs - Getting Started.pdf`
  - `C:\\Program Files (x86)\\RDTeam\\VACSVIEWER_32\\VACS_Readme.txt`
  - `C:\\Program Files (x86)\\RDTeam\\VACSVIEWER_32\\VACS.chm` (Help; automated extraction fehlgeschlagen, aber in-app per Help-Menue nutzbar)

#### Graph-Typen (relevant fuer "welche Daten existieren")
Aus "Getting Started" + Website-Features:
- Curve/Cartesian graphs (klassische Kurven)
- Polar plots (z.B. Winkelabhaengigkeiten)
- Contour plots (z.B. frequency/directivity plots; 2D-Visualisierung ueber einen Parameter wie "Axial Angle")
- Balloon plots (3D directivity / hochaufloesende Richtdiagramme)
- Processing/Derived graphs: VACS verarbeitet typischerweise aus dem "Original" Graph; fuer weitere Verarbeitung wird dupliziert.

Hinweis aus "Getting Started" (relevant fuer grosse Batches):
- VACS ist als 32-bit und 64-bit verfuegbar; 32-bit ist fuer Normalbetrieb ok, 64-bit ist fuer sehr grosse Datenmengen (z.B. hochaufloesende Balloon-Messungen) gedacht.
- Import in Contours/Directivity: die Quelldaten sollten identische Abszisse (z.B. identische Frequenzliste) ueber alle Dateien haben, sonst wird das Contour-Mapping schnell inkonsistent.

Implikation fuer unsere Pipeline:
- ABEC/VACS-Imports, die wir aktuell sehen (z.B. `LE_Spectrum`, `Radiation Impedance`) sind Curve/Cartesian Graphs.
- Fuer Directivity/Mehrpositionsdaten sind Contour/Balloon relevant und erfordern, dass Parameter-Informationen (z.B. Winkel/Radius) beim Export nicht verloren gehen.

#### Datenmodell (Import Control Settings - Textformat)
Die Import-/Export-Engine von VACS arbeitet mit einem "Import Control Settings" Metadatenblock plus Datenmatrix.
In den PDFs (Import Control Settings Part 1/2) werden u.a. beschrieben:
- Daten-Typisierung ueber Tags:
  - `Data_Format=` (z.B. `Complex`, `LeveldB`, `LeveldB_Phase`, `Ampl_Rms_Phase`, ...)
  - `Data_Domain=` (z.B. `Frequency`, `Time`, ...)
  - `Data_LevelType=` (z.B. `Peak`, `Rms`, `SoundPressure`, `Impedance10`, ...)
  - `Data_AbscUnit=`, `Data_BaseUnit=` (Einheiten)
  - `Data_Legend=` (Kurven-Legende; essentiell fuer Identifikation)
- Matrix-/Mehrkurvenfaelle:
  - Matrixformat mit gleicher Abszisse in Spalte 1 ist explizit vorgesehen und u.a. fuer Directivity-Daten praktisch.
- Parameter an Kurven (Import Control Settings Part 2):
  - `Param_...` (z.B. `Param_Coord_x1..x5`, `Param_Coord_Type`, `Param_Coord_AngularFormat`, `Param_Drv`, `Param_Param`, ...)
  - Parameter werden als Kurven-Eigenschaften verstanden und sind u.a. Quelle fuer y-Achse bei 3D/Contour-Plots.

#### Exportformate: Text vs Binary (und was VacsViewer typischerweise liefert)
Text (wie unsere aktuellen Exportfiles aus `IO -> Export data...`):
- Enthalten zusaetzlich Graph-Metadaten (aus realen Exports beobachtet):
  - `Graph_Type=...`, `Graph_Caption=...`, Achsen-Legenden/Units/Ranges, `Graph_BodeType=...`
- Enthalten einen Data-Block:
  - `StartString_Data=Data`, `EndString_Data=Data_End` (oder andere Strings je nach Einstellungen)
  - Danach Data-Matrix: bei `Data_Format=Complex` typischerweise `x, real, imag` (Frequenz plus Real/Imag)

Binary (Import Control Settings Part 3):
- Gleiche Semantik wie Textformat, aber Datenwerte in Binary-Blocks.
- In der Doku steht explizit, dass VACS das Binary-Format auch ueber Import/Export-Engine und ueber COM-Interface unterstuetzt.
- (Relevanz fuer uns: koennte mittelfristig ein UI-unabhaengiger Exportpfad sein, wenn VacsViewer/COM in unserer Umgebung nutzbar ist.)

Internet-Doku (Download/Arbeitskopie in dieser VM):
- `tmp_vacs_research\\ImportControl_Part1.pdf` (Text-Format, Data_* Tags)
- `tmp_vacs_research\\ImportControl_Part2.pdf` (Param_* / Koordinaten / 3D-Parameter)
- `tmp_vacs_research\\ImportControl_Part3.pdf` (Binary-Format + Stream_* Tags + Hinweis COM interface)

### Empfehlung: Was exportieren fuer "tidy data" ohne Datenverlust/ohne Muell?

Kurzfassung:
- Fuer unsere aktuellen ABEC-Imports (Curve-Graphs): Export als *VACS Text format* ist sinnvoll und hinreichend.
- Fuer Directivity/Mehrpositionsdaten (Contour/Balloon): Export muss `Param_...` enthalten, sonst verliert man die Zuordnung (Winkel/Koordinaten/Driving).

Konkrete Empfehlung (heute, mit VacsViewer):
- Pro Version und pro Graph-Fenster eine Textdatei exportieren (wie V3 es tut).
- Beim Parsing ins "tidy data" speichern:
  - Identitaet: `version`, `graph_caption` (aus `Graph_Caption`), `curve_legend` (aus `Data_Legend`)
  - Werte: Abszisse (`Data_AbscUnit` + erste Spalte; meist Hz/Frequency), plus Ordinaten
    - bei `Data_Format=Complex`: `real`, `imag` als getrennte Spalten (verlustfrei)
  - Kontext/Metadaten: `Data_Format`, `Data_Domain`, `Data_LevelType`, `Data_BaseUnit`, ggf. `Graph_BodeType`
  - fuer Contour/Balloon (wenn vorhanden): alle `Param_...` Tags als Spalten/JSON mitschreiben

Was *nicht* exportieren (um "Datenmull" zu vermeiden):
- Bild-Exports (`Export as picture`) sind fuer tidy data unbrauchbar.
- Matrix/Single-File Aggregationen nur dann nutzen, wenn wir den Parser gezielt darauf auslegen (sonst wird es schwerer zuzuordnen).

## A/B Audit: Export-Anforderungen vs. aktuelle Implementierung (2026-02-11)

Ziel dieser Pruefung:
- A) Entsprechen die aktuellen VACS-Exporte den tidyData-Anforderungen?
- B) Koennen wir dynamisch alle Graphen aus AKABAK/VACS verarbeiten?

### A) Erfuellen die aktuellen Exporte die Anforderungen?

#### A1. Was ist im Exportfile heute enthalten?
Praktischer Check mit realen VACS-Text-Exports (`tmp_export_probe5\\*.txt`):
- Vorhanden in allen geprueften Dateien:
  - `Graph_Type`, `Graph_Caption`, `Graph_BodeType`
  - `Data_Format`, `Data_Domain`, `Data_LevelType`
  - `Data_AbscUnit`, `Data_BaseUnit`, `Data_Legend`
- Damit ist die *Datei selbst* fuer eine saubere Zuordnung grundsaetzlich geeignet.

#### A2. Was exportiert VACS standardmaessig NICHT mit?
Check am Dialog `Data Export` (VacsViewer, Default-Status):
- `Export of graph view`: **AN**
- `Export of parameters`: **AUS**
- Konsequenz:
  - Fuer normale Kurven (aktuelle ABEC-Faelle) ist das oft ok.
  - Fuer Contour/Balloon/Directivity kann dadurch `Param_*`-Kontext fehlen (Koordinaten/Winkel/Driving), was fuer tidyData relevant ist.

#### A3. Verarbeitet unser Dataset-Importer diese Informationen vollstaendig?
Status `app/dataset_pipeline.py`:
- Importiert aktuell nur numerisch:
  - pro Zeile nur erste zwei Zahlen (`freq_hz`, `value`)
- Dadurch gehen bei `Data_Format=Complex` Informationen verloren:
  - `imag` (und ggf. abgeleitete Phase) wird nicht uebernommen.
- `Graph_Caption`, `Data_Legend`, `Data_*`, `Graph_*`, `Param_*` werden derzeit nicht in die Mess-Tabellen geschrieben.

Bewertung A:
- **Teilweise erfuellt**.
- Exportdateien haben die noetigen Metadaten, aber die aktuelle tidyData-Pipeline nutzt sie nicht vollstaendig und verliert komplexe Ordinaten.

### B) Dynamik: koennen wir alle Graphen robust verarbeiten?

#### B1. Dynamik im Export-Lauf
Status `Runner/wut_abec_batch_runner.py`:
- `export_variant_in_vacs(...)` versucht dynamische Fenstererkennung und suffix-basierten Export.
- Suffix-Generierung geht ueber `A..Z` (mit Skip `D`) und danach auf Doppelsuffix (`AA`, `AB`, ...).

#### B2. Harte Luecken in der End-to-End-Dynamik
1) Graph-Discovery ist heuristisch fragil:
- Auswahl basiert auf Titelmustern `\" - \"` und `\"#\"` in `main.descendants()`.
- In Tests lieferte dieser Filter fuer die aktuellen Plots TreeItems statt MDI-Graph-Windows (`TForm_DatGraph`), was je nach UI-Zustand zu Fehlfokus fuehren kann.

2) Dataset-Import versteht aktuell nur Ein-Buchstaben-Suffixe:
- Regex: `^Result_(V\\d+)([A-Za-z])(?:\\.txt)?$`
- Folge:
  - `Result_V001E.txt` wird erkannt.
  - `Result_V001AA.txt` wird **ignoriert** (nicht importiert).

3) Validierung ist noch auf altes C/A/B-Schema ausgerichtet:
- `Runner/validators.py` erwartet fest `C`, `A`, `B`.
- Bei Projekten mit anderer Graph-Zahl/-Art kann der Run trotz valider Exporte als fehlerhaft markiert werden.

4) Post-Export-Handling schliesst Child-Window pro Export:
- `close_childwindow_confirm()` nach jedem Export erhoeht das Risiko fuer Fokusdrift bei vielen/unterschiedlichen Graphformen.

Bewertung B:
- **Teilweise erfuellt**.
- Fuer die bisher genutzten Graphfaelle funktioniert es oft, aber fuer "jede Graph-Art" und grosse variable Graph-Anzahlen ist die Pipeline aktuell noch nicht durchgaengig robust.

### Kurzfazit (A/B)
- A) Exportdateien sind inhaltlich nah am Ziel, aber der Import in tidyData ist derzeit zu verlustbehaftet (Metadaten/Complex/Param fehlen).
- B) Dynamischer Export ist angelegt, aber nicht end-to-end konsistent (Discovery-Heuristik, Validator, Dataset-Regex fuer `AA+`).

### Konkrete technische ToDos (naechster Schritt)
1) `dataset_pipeline` auf formatbewussten Parser umstellen:
- `Data_Format` auswerten, `real/imag/phase/value` sauber belegen.
- `Graph_Caption`, `Data_Legend`, `Data_*`, `Graph_*`, `Param_*` persistent speichern.
2) Resultat-Dateinamenerkennung auf Multi-Letter erweitern:
- z.B. `^Result_(V\\d+)([A-Za-z]{1,3})(?:\\.txt)?$`
3) Export-Validation dynamisieren:
- statt fest `C/A/B` gegen `Result_<ver>_index.txt` bzw. gefundene Suffixe pruefen.
4) Graph-Discovery auf echte Graph-Windows einschaerfen:
- `TForm_DatGraph`/Window-Controls priorisieren statt Title-only Descendants.

## Umsetzung (kleinschrittig) + Validierung (2026-02-11)

### Schritt 1: Multi-Letter Suffixe + Index-gesteuerte Dynamik
- Umsetzung:
  - `app/dataset_pipeline.py`
    - `Result_(Vxxx)(suffix)` akzeptiert jetzt auch Multi-Letter-Suffixe (`AA`, `AB`, ...).
    - `Result_<ver>_index.txt` wird erkannt und als Erwartungsmenge fuer Exporte verwendet.
    - Harte Erwartung `A/B/C` entfernt; Erwartung ist jetzt dynamisch.
- Validierung:
  - `python -m unittest tests.test_dataset_pipeline_dynamic_outputs -v`
  - Ergebnis: Tests fuer Multi-Letter + Index-gesteuerte Auswahl bestanden.

### Schritt 2: Formatbewusster Parser + Metadatenpersistenz
- Umsetzung:
  - `app/dataset_pipeline.py`
    - Neuer parser fuer VACS-Textstruktur (`Data`/`Data_End`, `Data_Format`, `Param_*`).
    - Unterstuetzung fuer `Complex` (`real/imag`) und `Phase`-Formate.
    - Neue Tabelle `measurement_meta` fuer `Graph_Caption`, `Data_Legend`, `Data_*`, `Graph_*`, `Param_*`.
- Validierung:
  - Erweiterte Unit-Tests in `tests/test_dataset_pipeline_dynamic_outputs.py`
  - Ergebnis: Complex-Werte (`real/imag`) und Metadaten wurden korrekt in SQLite geschrieben.

### Schritt 3: Dynamischer Export-Validator
- Umsetzung:
  - `Runner/validators.py` neu strukturiert:
    - Suffixe aus `Result_<ver>_index.txt`, sonst aus vorhandenen `Result_<ver>*.txt`.
    - Keine harte C/A/B-Annahme mehr.
    - Sanity Checks fuer `Data_Format` und `Data_Legend`.
- Validierung:
  - `python -m unittest tests.test_validators_dynamic tests.test_dataset_pipeline_dynamic_outputs -v`
  - Ergebnis: alle Tests bestanden.

### Schritt 4: Robustere Graph-Discovery im Legacy Runner
- Umsetzung:
  - `Runner/wut_abec_batch_runner.py`
    - `export_variant_in_vacs(...)` priorisiert jetzt echte `TForm_DatGraph`-Fenster.
    - Fallback bleibt auf Titelheuristik fuer Altfaelle.
    - Per-Export `close_childwindow_confirm()` entfernt (bekannte Fokusdrift-Quelle).
- Validierung (Integration):
  - Realer Probe-Lauf mit `Project.abec`:
    - AKABAK load -> solve -> F7 -> Export ueber Legacy-Funktion.
    - Ergebnis: `Result_V999A/B/C.txt` + `Result_V999_index.txt` erfolgreich erzeugt.

### Schritt 5: CLI/GUI Kennzahl + Dry-Run-Test konsolidiert
- Umsetzung:
  - `app/dataset_pipeline.py`
    - `ImportSummary` erweitert um `metadata_rows`.
    - `measurement_meta`-Upsert liefert jetzt die Anzahl geschriebener Meta-Zeilen.
  - `app/cli.py`
    - `dataset build`/`dataset update` geben jetzt zusaetzlich `metadata=<count>` aus.
  - `app/gui.py`
    - Parser fuer Dataset-Output liest jetzt auch `metadata=...`.
    - Manifest-`last_summary` enthaelt jetzt ebenfalls `metadata`.
  - `tests/test_m7_dry_run_smoke.py`
    - Erwartung auf aktuelles Dry-Run-Exportschema korrigiert (`A/B/C`, kein `D`).
- Validierung:
  - `python -m unittest tests.test_m7_dry_run_smoke tests.test_validators_dynamic tests.test_dataset_pipeline_dynamic_outputs tests.test_m9_compatibility_incidents -v`
  - Ergebnis: alle 9 Tests bestanden.
