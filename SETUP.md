# Setup

## Python environment

WUT Batcher is currently validated with Python 3.12 on Windows. Use a local
virtual environment per clone:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## External simulation tools

WUT Batcher does not silently download or redistribute ATH, AKABAK or VACS.
Their license and download decisions remain with the user. The setup assistant
detects existing installations first and never overwrites a valid configured
path:

```powershell
python -m app setup status
python -m app setup detect
```

The same actions are available under **Settings > Tool setup**. On a genuinely
incomplete first launch, Settings opens automatically and shows the missing
tools. It does not open on machines whose setup is already complete.

Official sources and current setup policy:

- ATH: manual download from <https://www.at-horns.eu/download.html>. The
  publisher describes personal, non-commercial freeware use and a separate
  commercial-license path.
- AKABAK: manual download from <https://www.randteam.de/AKABAK3/Index.html>.
  The free/demo workflow has result-saving restrictions; check the R&D Team
  license terms before commercial product development.
- VacsViewer/VACS: manual download from <https://randteam.de/VACS/Index.html>.
  The free viewer has project-saving restrictions; check the R&D Team license
  terms before commercial product development.
- Gmsh: open-source dependency from <https://gmsh.info/>. WUT can install it
  with `winget` only after explicit confirmation. Existing copies, including a
  `gmsh.exe` next to ATH, are detected first, so the operation does not install
  a duplicate.

Optional, explicit Gmsh install:

```powershell
python -m app setup install-gmsh --yes
```

Do not use `--yes` until `python -m app setup status` reports Gmsh as missing.

## Run the application

```powershell
python -m app gui
```

In VS Code, select `.venv\Scripts\python.exe` and use the
`WUT Batcher: GUI` launch configuration from `.vscode/launch.json`.

Optional theme preview:

```powershell
python -m app theme preview
```

## Health and storage diagnostics

The Doctor reads the same user settings as the GUI and writes its default
report under `~/.wut_batcher/logs/doctor_report.json`:

```powershell
python -m app doctor
```

The Project Library audit is read-only. `--scan-siblings` reports possible old
or test libraries without selecting, migrating or deleting them:

```powershell
python -m app library audit --scan-siblings
```

Real ATH compatibility verification uses an isolated library root. Add
`--no-sql` when only filesystem evidence is wanted:

```powershell
python -m app compat verify --mode quick --library-root .\tmp\compat-check --no-sql
```

## Run tests

```powershell
python -m pytest -q
```

Focused unittest runs remain supported where useful, but pytest is the
repository-wide validation entry point.

## Git Hooks (Auto Push)
Run once per local clone:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_git_hooks.ps1
```
This configures `core.hooksPath=.githooks` and enables push defaults so `post-commit` auto-push can run.
Set `WUT_NO_AUTO_PUSH=1` in your shell if you need to temporarily disable auto-push.

## Notes

- GUI requires `PySide6`.
- If `python -m app gui` fails with missing Qt packages, reinstall the Python
  dependencies from `requirements.txt`; do not reinstall external simulation
  tools that `setup status` already finds.

## Unattended Night Run (PROJECT-only ATH, 100k)
Start in a persistent PowerShell/Windows Terminal session from repo root:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\night_pp100k.ps1
```
The script runs 10 blocks (`pp100k_2100`..`pp100k_2109`, 10k each), stops on non-zero exit, and logs to `reports/ath_experiments/night_pp100k.log`.

Resume a single block after interruption:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\night_pp100k_resume.ps1 -Seed 2104 -RunGroup pp100k_2104 -Cases 10000
```

Re-run only aggregation (after all blocks):
```powershell
python -m app projectpage-ath-experiment --cases 0 --seed 0 --run-group pp100k_aggregate_YYYYMMDD_HHMMSS --aggregate-run-groups pp100k_2100,pp100k_2101,pp100k_2102,pp100k_2103,pp100k_2104,pp100k_2105,pp100k_2106,pp100k_2107,pp100k_2108,pp100k_2109 --reports-root reports/ath_experiments --cleanup-files false --preclean-files false --cleanup-cases never --cleanup-log never --history-snapshots true
```
