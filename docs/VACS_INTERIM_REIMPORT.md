# VACS Interim Re-Import Script (Standalone)

## Zweck
Schneller Zwischenlauf fuer VACS-Driver-Tests ohne erneuten ATH/AKABAK-Solve pro Durchgang.

Skript:
- `scripts/vacs_interim_reimport.py`

## Geplanter Ablauf
1. An AKABAK (laufend) andocken.
2. VACS bevorzugt ueber AKABAK-Menue (`Options -> Open VACS...`) oeffnen/verbinden.
3. In AKABAK `F7` triggern.
4. EdgeLength-Warnung per `Yes` bestaetigen.
5. Auf Re-Import in VACS warten (Graph-Signal aus UI-Struktur).
6. Optional VACS schliessen und Save-Prompt mit `No` beantworten.

CLI-Hinweis:
- Standard ist jetzt `AKABAK-started VACS` (kein Attach an extern gestartete VACS-Instanz).
- Wenn VACS bereits offen ist, darf der Skriptlauf diese bestehende Instanz nutzen (Fallback).
- Kein erzwungenes Frisch-Starten von VACS im Default (`--force-fresh-vacs` ist optional).

## Wichtiger Hinweis fuer spaetere Integration
- Datei-/Namenskonventionen der Import-/Export-Artefakte muessen vor Produktivschritt noch finalisiert werden (TODO).

## Aktueller Teststatus (real VM)
- Setup (`Import + Solve + VACS Graphen vorhanden`) funktioniert.
- Interim-Skript behandelt:
  - EdgeLength-Dialog korrekt,
  - Save-Dialog in VACS (embedded modal) korrekt.
- Aktueller Blocker (vor Umstellung auf AKABAK-started VACS):
  - Nach `F7` trat wiederholt AKABAK-Modal auf:
    - `Der RPC-Server ist nicht verfuegbar.`
  - In diesem Zustand kam kein Re-Import in VACS zustande (`controls_count` blieb bei ~52 statt ~151).

Bekannter Zusammenhang:
- Extern gestartetes VACS (Desktop/Terminal) kann den RPC-Fehler triggern.
- Ueber AKABAK gestartetes VACS vermeidet den Fehler in den beobachteten Faellen.

Aktueller reproduzierbarer Workaround im Skript:
- Wenn AKABAK beim `Open VACS...` den COM-Dialog meldet, aber eine VACS-Instanz bereits laeuft,
  wird diese Instanz angebunden und der F7-Reimport dennoch erfolgreich durchgefuehrt.

Referenz-Logs:
- `runner_test_workspace/logs/interim_reimport/vacs_interim_reimport_20260215_213645.json`
- `runner_test_workspace/logs/interim_reimport/vacs_interim_reimport_20260215_212433.json`
- `runner_test_workspace/logs/interim_reimport/vacs_interim_reimport_20260215_210437.json`
- `runner_test_workspace/logs/interim_reimport/vacs_interim_reimport_20260215_210351.json`
