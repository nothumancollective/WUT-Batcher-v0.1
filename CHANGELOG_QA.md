# CHANGELOG_QA

## 2026-02-18

### Pipeline
- Batch-Run fuehrt jetzt pro Version eine eigene Runtime-CFG (`cfg/<runtime>.cfg`) aus.
- `version.json` enthaelt jetzt Run-Manifest-Felder (`run_cfg_path`, `ath_export_dir`, Snapshots).
- Persistenz-Sync wird vor Cleanup geprueft; bei unsynchronem Global-Mirror wird Version als failed markiert.

### Cleanup
- Per-Version Cleanup wurde auf den geforderten Scope umgestellt:
  - Runtime-CFG
  - ATH-Export-Unterordner
- Bei Fehlern bleibt Cleanup aus (Diagnose-Artefakte bleiben erhalten).

### CLI/Checks
- `run-sample` Cleanup-Validierung an den neuen Cleanup-Vertrag angepasst.

### Tests
- Runtime-Orchestrator um neue Integrations- und Cleanup-Regressionstests erweitert.
