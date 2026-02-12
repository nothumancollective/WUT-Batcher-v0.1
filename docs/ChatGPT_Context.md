# Batch-Software – Struktur/Architektur (Kontext für ChatGPT)

Diese Datei ist dafür gedacht, **als Startkontext** in einen neuen Chat kopiert zu werden, damit das System schnell versteht, wie das Repo aufgebaut ist und wie der Workflow funktioniert.

Stand: 2026-02-10

---

## TL;DR

- Die Software ist ein **Orchestrator** für Batch-Simulationen: **ATH → (ABEC/AKABAK) → VACS Export → Dataset**.
- `app/` enthält **CLI + GUI** (Projektverwaltung, Batch-Definition, Run-Orchestrierung, Dataset-Import).
- `Runner/` enthält **Windows-UI-Automation** (AKABAK/VACS) und gilt als **Blackbox**.
- Persistente Daten liegen **außerhalb** des Repos unter `Documents/WUT-Batches/Projects/Project_<Pxxx>/...`.

---

## Begriffe / IDs

- **Version**: Eine konkrete ATH-Parameter-Kombination (= ein konkretes Horn). IDs wie `V001`.
- **Batch**: Sammlung vieler Versionen (entsteht aus Sweeps). IDs wie `B001`.
- **Project**: Rahmen/Constraints für alle Versionen + Historie (Batches, Dataset). IDs wie `P001`.

Konvention: `P001`, `B001`, `V001` (Validierung passiert teils in CLI, teils nur als Konvention).

---

## Repository-Struktur (wichtigste Teile)

```
Batch-Software/
  run_full_batch_v5.py          # 1-Command Windows-Orchestrator (Desktop-Ausgabe)
  start_gui.ps1                 # Startet GUI via Python 3.12 (fallback: py -3.12-64)
  app_config.json               # Lokale Pfade/Tools (Doctor checks; projects_root)
  app/                          # Orchestrator: CLI + GUI + Datenmodelle
    __main__.py                 # python -m app -> app.cli:main()
    cli.py                      # Subcommands: doctor/project/batch/dataset
    gui.py                      # PySide6 GUI (Orchestrator, keine UI-Automation)
    doctor_service.py           # Startup-/Umgebungschecks (+ logs/doctor_report.json)
    path_resolver.py            # Standard-Ordnerstruktur für Projekte/Batches
    models.py                   # JSON-Modelle: AppConfig/Project/Batch/DatasetManifest/...
    dataset_pipeline.py         # Import von Result_*.txt in SQLite + Manifest
    batch_planner.py            # Sweep-Logik + job_count (oat/factorial/both)
    parameter_registry.py       # Zentrale Parameterliste für GUI/Validierung
  Runner/                       # Windows Runner/Automation (Blackbox)
    wut_ath_batch_creator_v2.py  # Erzeugt Configs, ruft ATH, schreibt queue.csv + Result_*D.txt
    wut_abec_batch_runner.py     # UI-Automation: AKABAK/VACS, Exporte Result_*A/B/C...
    wut_abec_batch_runner_dry.py # Dry-Run (Dummy-Exports) zum Testen ohne Tools
  templates/                    # Template-Assets für Runner (Screenshots etc.)
  docs/                         # Konzepte + Beispiele (Batch/Project/Dataset)
  schemas/                      # JSON-Schemas (app_config/project/batch/dataset_manifest)
  logs/doctor_report.json       # Output vom Doctor (wird überschrieben)
```

---

## Persistente Daten (außerhalb des Repos)

Das Repo speichert Projekt-/Batch-Daten standardmäßig unter `projects_root` (aus `app_config.json` oder Defaults):

```
<projects_root>/
  Project_P001/
    project.json
    constraints.json
    batches/
      Batch_B001/
        batch.json
        Config/
        ATH Export/
        Resultate/
        Logs/
    dataset/
      dataset.sqlite
    dataset_manifest.json
```

Die Ordnerstruktur wird zentral in `app/path_resolver.py` erzeugt und von CLI/GUI wiederverwendet.

---

## Zentrale Dateiformate / Artefakte

### `app_config.json` (Repo-Root)

- Wird vom **Doctor** gelesen (Pfadchecks, Templates, Exes).
- `AppConfig` (in `app/models.py`) nutzt aktuell vor allem:
  - `app_name`
  - `projects_root`
- Weitere Keys (z. B. `ath_exe`, `akabak_dir`, `vacs_dir`, `ath_export_root`, `batch_results_root`) werden für **Doctor checks** genutzt.

### `project.json` + `constraints.json`

- `project.json`: Metadaten + `constraints` (lightweight).
- `constraints.json`: enthält u. a. `template_family`, `limits`, optional `fixed_params` (wird für Sweep-Blocker genutzt).

### `batch.json`

- Enthält `selected_params`, `sweeps`, `mode` (`oat|factorial|both`) und `sim_export_settings`.
- `app/batch_planner.py` berechnet daraus den **job_count**.

### `queue.csv` + `Result_*.txt`

- `Runner/wut_ath_batch_creator_v2.py` erzeugt `Config/Vxxx.cfg`, ruft ATH, schreibt:
  - `queue.csv` (Jobs für Runner)
  - `Result_VxxxD.txt` (Device/Meta + Abec-Project-Pfad)
- `Runner/wut_abec_batch_runner.py` erzeugt in `Resultate/` typischerweise:
  - `Result_VxxxC.txt`, `Result_VxxxA.txt`, `Result_VxxxB.txt` (Exports aus VACS)

### Dataset (`dataset.sqlite` + `dataset_manifest.json`)

- `app/dataset_pipeline.py` scannt `batches/Batch_*/Resultate/` nach `Result_(Vxxx)(A|B|C|D).txt`
- Importiert Messwerte in SQLite (Tabellen: `versions`, `measurements`) und schreibt ein Manifest für inkrementelle Updates.

---

## Workflow (High-Level Datenfluss)

1) **doctor**
   - Prüft Verzeichnisse/Schreibrechte, Templates, (Windows) Tool-Exes und ggf. Zombie-Prozesse.
   - Output: `logs/doctor_report.json`

2) **project new/open**
   - Legt `Project_Pxxx/` an, schreibt `project.json` + `constraints.json`.

3) **batch create**
   - Schreibt `Batch_Bxxx/batch.json` und zeigt `job_count` (Sweep-Planung).

4) **batch run**
   - Ruft `Runner/wut_ath_batch_creator_v2.py` → `queue.csv` + `Result_*D.txt`
   - Ruft `Runner/wut_abec_batch_runner.py` → UI-Automation, Exporte `Result_*A/B/C...`
   - Logs liegen in `Batch_*/Logs/creator.log` und `Batch_*/Logs/runner.log` (CLI-Pfad).

5) **dataset build/update**
   - Parst `Result_*.txt`, schreibt/updated `dataset/dataset.sqlite` + `dataset_manifest.json`.

---

## Entry Points / Wie starten

### GUI (Windows, bevorzugt)

- `.\start_gui.ps1 -DoctorOnly -Verbose`
- `.\start_gui.ps1 -Verbose`

Direkt:
- `python -m app.gui --doctor-only`
- `python -m app.gui`

Hinweis: GUI speichert zusätzliche Pfade (z. B. `template_cfg`, `ath_exe`, `akabak_dir`, `vacs_dir`) in einer **globalen Settings-Datei** (über Qt AppConfigLocation, Datei: `app_settings.json`).

### CLI

- Hilfe: `python -m app --help`
- Doctor: `python -m app doctor --fix --kill-zombies`
- Projekt: `python -m app project new --project-id P001 --name "My Project" --template-family <family>`
- Batch: `python -m app batch create ...`
- Run (Windows): `python -m app batch run --project-id P001 --batch-id B001 ...`
- Dataset: `python -m app dataset build --project-id P001` / `update`

### One-command Batch (Windows, unabhängig von `app/`)

- `python .\run_full_batch_v5.py --template-cfg "C:\Tools\ATH\Test.cfg" --num 1 --show-desktop`
- Schreibt Standard-Ausgabe nach `Desktop/Batch-Ergebnisse/Batch_<timestamp>/...`

---

## Wichtige Constraints (für Änderungen/Weiterentwicklung)

- `Runner/` ist **Windows-UI-Automation** (AKABAK/VACS, pyautogui/pywinauto/OpenCV) und gilt als **Blackbox**: nur ändern, wenn explizit gefordert.
- `app/` ist die **Orchestrator-Schicht**: hier passieren Planung, File-IO, CLI/GUI, Dataset.
- Cross-Platform: CLI/GUI/Dataset können auch ohne Windows-Tools laufen; echte Runner-Ausführung ist **Windows-only**.

---

## Wenn du (ChatGPT) helfen sollst

Bitte:
- Frage zuerst nach dem Ziel (z. B. “Batch-Definition erweitern”, “Dataset-Import anpassen”, “GUI-Flow ändern”).
- Behandle Runner/Automation als Blackbox (außer ausdrücklich anders).
- Schlage Änderungen klein und nachvollziehbar vor (max. wenige Dateien; keine großen Refactors).
- Wenn Commands/Paths genannt werden: Windows-Pfade exakt, mit konkreten Beispielen.

