# Minimal Completion Search (ATH STL)

## Ziel
Dieses Tool sucht minimale Parameter-Sets (`minXY`) pro UI-Kartenkombination, sodass ATH eine STL erzeugt.

Es unterstützt zwei Modi:
1. `DB-observed` (schnell): nimmt nur erfolgreiche Seeds aus `ath_experiments.sqlite` und berechnet beobachtete Minima.
2. `ATH-verified` (langsam, robust): prüft Kandidaten mit echten ATH-Runs und minimiert greedy über eine STL-Oracle-Funktion.

## Problemklasse
Das ist ein **black-box constrained combinatorial optimization**:
- Entscheidungsvariablen: welche Keys in einer Szenario-Konfiguration gesetzt sind
- Nebenbedingungen:
  - Szenario-Selektoren (z. B. `Throat.Profile=2`)
  - `minXY > 0` für jede enthaltene Karte
- Feasibility-Oracle: ATH-Lauf erzeugt eine nicht-leere STL
- Ziel: lexikographische Minimierung der Key-Anzahlen je Karte

Formal (pro Szenario):  
`min (extra_keys, count(profile), count(basics), count(mesh), count(morph), count(gcurve), count(enclosure), total_keys)`  
unter Feasibility-Constraint `ATH(params) -> STL exists`.

## Abdeckung der Schritte 1-7
Standardmäßig (`--all-combinations` aus):
- Step 1: `minProfile + minBasic`
- Step 2: `minProfile + minBasic + minMesh`
- Step 3: `minProfile + minBasic + minMesh + minMorph`
- Step 4: `minProfile + minBasic + minMesh + minGCurve`
- Step 5: `minProfile + minBasic + minMesh + minEnclosure`
- Step 6: `minProfile + minBasic + minMesh + minMorph + minGCurve`

Mit `--all-combinations`:
- Step 7 Matrix: zusätzliche Kombinationen über optionalen Kartenraum.

## CLI
Subcommand:
`python -m app ath-experiments minimal-completion-search`

Wichtige Optionen:
- `--reports-root` Pfad mit `ath_experiments.sqlite` (Default: `reports/ath_experiments`)
- `--output-root` Zielordner für Reports/Cache (Default: `reports/minimal_completion`)
- `--run-group` run_group Filter (`all` oder csv)
- `--seed-run-limit` Anzahl erfolgreicher DB-Seeds
- `--max-seed-candidates` Kandidaten pro Szenario
- `--verify-ath` aktiviert echten ATH-Oracle-Lauf
- `--max-eval-per-scenario` Budget für Oracle-Evaluierungen pro Szenario
- `--scenario-filter` nur Szenarien mit Teilstring im `scenario_id`
- `--all-combinations` Step-7 Matrix aktivieren
- `--ath-exe`, `--template-cfg` Overrides für ATH-Verify-Modus

## Empfohlene Ausführung
1. Schnellstart (nur beobachtete Minima):
```powershell
python -m app ath-experiments minimal-completion-search `
  --seed-run-limit 20000 `
  --max-seed-candidates 12 `
  --output-root reports/minimal_completion
```

2. Robuster Verifikationslauf auf einem Teilbereich:
```powershell
python -m app ath-experiments minimal-completion-search `
  --verify-ath `
  --scenario-filter s2_profile1_basic_mesh `
  --seed-run-limit 5000 `
  --max-seed-candidates 8 `
  --max-eval-per-scenario 200 `
  --output-root reports/minimal_completion_verify
```

3. Vollständiger, zeitintensiver Lauf:
```powershell
python -m app ath-experiments minimal-completion-search `
  --verify-ath `
  --all-combinations `
  --seed-run-limit 40000 `
  --max-seed-candidates 12 `
  --max-eval-per-scenario 300 `
  --output-root reports/minimal_completion_full
```

## Outputs
Im `output-root`:
- `minimal_completion_summary_<timestamp>.json`
- `minimal_completion_summary_<timestamp>.md`
- `oracle_cache.sqlite` (ATH-Oracle-Cache)
- `logs/<scenario_id>/...` (ATH stdout/stderr/runner logs)

## Hinweise
- `ATH-verified` kann lang laufen (viele Oracle-Calls).
- Bei `exit_code=0` aber fehlender STL wird `stl_not_found` im Fehlerpfad protokolliert.
- Für R-OSSE wird `Throat.Profile=2` vor dem ATH-Render entfernt (ATH-intern inkompatibler UI-Selektor), `R-OSSE` bleibt gesetzt.
