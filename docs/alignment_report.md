# Alignment Report

## Phase 1 - Bestandsaufnahme

### Source-of-Truth Regel
- Verbindlich ist `docs/Roadmap.md`.
- `docs/roadmap_codex_checklist.md` ist ein nachgelagerter Implementierungsplan und darf `docs/Roadmap.md` nicht ueberschreiben.

### Vorgefundene Aenderungen (Ist-Stand vor Korrektur)
- `docs/roadmap_codex_checklist.md` war bereits auf runner-kompatible Ordnernamen ausgerichtet (`Config`, `ATH Export`, `Resultate`, `Logs`).
- `docs/roadmap_codex_checklist.md` enthielt eigene Definitionssektionen statt klarer Referenz auf die verbindlichen Begriffe aus `docs/Roadmap.md`.
- Eine explizite Mapping-Sektion (Roadmap -> Checklist) fehlte.
- `docs/Roadmap.md` hatte keine zentrale, kompakte Begriffsstelle fuer alle vier Kernbegriffe.

### Konflikte/Abweichungen (vor Korrektur)

#### (a) Begriffe/Definitionen
- Begriffsdrift-Risiko durch doppelte Definitionen in beiden Dokumenten.
- `Dataset` war in `docs/Roadmap.md` nicht zentral als verbindliche Definition gebuendelt.

#### (b) Pfade/Ordner/Dateinamen (Doku-Vorgaben)
- Runner-kompatible Batch-Namen waren nicht als Source-of-Truth-Ableitung dokumentiert.

#### (c) Reihenfolge/Milestones/Abhaengigkeiten
- Fehlendes explizites "erst Roadmap, dann Checklist"-Mapping.

#### (d) Architekturentscheidungen
- Roadmap enthaelt GUI-Tech-Entscheidung (Tkinter vs. PySide6), die Checklist war Qt-zentriert.

---

## Phase 2-3 - Korrekturen (Doku-only)

### Durchgefuehrte Anpassungen
- `docs/Roadmap.md` ergaenzt um zentralen Abschnitt `Begriffe (Source of Truth)` mit den verbindlichen Definitionen fuer Version, Batch, Projekt und Dataset.
- `docs/roadmap_codex_checklist.md` auf reine Ableitung aus `docs/Roadmap.md` umgestellt.
- Eigene Begriffsdefinitionen in der Checklist entfernt; stattdessen Referenz auf `docs/Roadmap.md`.
- Mapping-Sektion hinzugefuegt: `Roadmap.md` Milestones -> Checklist-Module (`C0` bis `C7`).
- Reihenfolge und Gates explizit dokumentiert (insbesondere GUI-Entscheidung vor GUI-Umsetzung).

### Ergebnis
- Begriffe sind konsistent und zentralisiert.
- Milestone-Abfolge ist als Workflow nutzbar.
- Die Checklist erzeugt keine abweichende Prioritaet mehr gegenueber der Roadmap.

---

## Phase 4 - Environment Check (Doku-only)

- Neue Datei: `docs/setup_check.md`
- Enthalten:
  - Python/Pip-Pruefkommandos
  - Beispiel-Importchecks
  - CLI-Smoke-Checks
  - erwartete Ergebnisse und typische Fehlerbilder
- Keine Installationen, keine Systemaenderungen.

---

## Phase 5 - Abschlussstatus

### Status
- OK: Dokumente sind kompatibel und als sequenzieller Workflow nutzbar.

### DECISION REQUIRED
- Keine offenen Punkte.


### DECISION REQUIRED (2026-02-09, M10.2)
- Aufloesung erfolgt: User hat Option 1 bestaetigt.
- `docs/Roadmap.md` wurde aus `HEAD` wiederhergestellt und M10.2-Umsetzung danach fortgesetzt.

---

## Phase 6 - Code Consistency Check (2026-02-09)

### Ergebnis
- CLI (M4), Batch-Definition/Job-Count (M7), Dataset Build/Update (M9), GUI bis M11.1 sind im Code vorhanden.
- Abweichungen aus Phase 6 behoben (PathResolver-Doku angepasst, Doctor implementiert).

### How to use (Reihenfolge)
1. `docs/Roadmap.md` lesen und als verbindliche Reihenfolge nutzen.
2. Danach `docs/roadmap_codex_checklist.md` als Task-Feingranularisierung pro Milestone verwenden.
3. `docs/setup_check.md` vor oder bei Start eines Milestones fuer Read-only Umgebungspruefung nutzen (Windows: `py -3`/`python`, macOS/Linux: `python3`).
4. Bei Konflikt immer `docs/Roadmap.md` priorisieren.

### DECISION REQUIRED (2026-02-10, M11.3 Recovery)
- Ursache: `app/gui.py` wurde waehrend eines Patch-Timeouts temporaer auf 0 Bytes gesetzt.
- Aufloesung: Datei wurde neu aufgebaut und der M11.3-Stand erneut verifiziert (Import, py_compile, doctor-only, offscreen Run-Monitor-Smoke).
- Status: geschlossen, keine offenen Entscheidungen.

---

## Phase 7 - Vollpruefung Codebasis (2026-02-10)

### Verifizierter Implementierungsstand
- M0 bis M11.3 sind im Code umgesetzt und lauffaehig (CLI + Datenfluss + GUI-Orchestrierung).
- M11.4 (Dataset Buttons) ist ebenfalls im GUI-Code umgesetzt:
  - Trigger `dataset build/update`
  - Progressanzeige
  - Summary-Update im Manifest
- `docs/Roadmap.md` und `docs/roadmap_codex_checklist.md` wurden auf diesen Stand synchronisiert.

### Durchgefuehrte technische Checks
- `python3 -m py_compile app/*.py run_full_batch_v5.py` -> erfolgreich.
- `python3 -m app --help` -> erfolgreich.
- `python3 -m app.gui --doctor-only --verbose` -> erfolgreich (WARN auf non-Windows erwartbar).
- CLI-Smoke in isoliertem `/tmp`-Workspace:
  - `project new/list/open`
  - `batch create`
  - `batch run --no-run`
  - `dataset build/update`
  - Ergebnis: erfolgreich, keine Laufzeitfehler.

### Offene technische Risiken / Inkonsistenzen
- (geschlossen, 2026-02-10) Dataset-Keying ist auf `batch_id + version_id` umgestellt.
  - SQLite-Keys und Manifest-Index verhindern Ueberschreiben bei gleichen `Vxxx` ueber mehrere Batches.
- (geschlossen, 2026-02-10) `batch create` validiert Projekt- und Constraint-Existenz vor dem Schreiben.
  - Verwaiste `Batch_*` ohne `project.json` werden damit verhindert.
- (geschlossen, 2026-02-10) Pfadkonventionen sind konsolidiert.
  - Resolver und Run-Orchestrierung verwenden Runner-kompatibel `Config/ATH Export/Resultate/Logs`.
- Betrieb auf SMB-Share bleibt grundsaetzlich fragil (File-Watcher/Indexing/Locking), auch wenn Git aktuell wieder konsistent ist.

### Status
- Gesamtstatus: nutzbar mit bekannten Restpunkten.
- DECISION REQUIRED: keine (nur priorisierte technische Folgeaufgaben fuer Hardening).
