# Setup

## Python
- Verified runtime in this VM: `Python 3.12` (`C:\Users\maximilianheinze\AppData\Local\Programs\Python\Python312-arm64\python.exe`).
- Recommended workflow is a local virtual environment per repo.

## Create Virtual Environment (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run App
```powershell
python -m app gui
```

## VS Code (Run and Debug)
- Create the venv + install deps (see above), then open the folder in VS Code.
- Select interpreter: `.venv\Scripts\python.exe`
- Use **Run and Debug** and pick `WUT Batcher: GUI` (launch configs live in `.vscode/launch.json`).

Optional theme preview:
```powershell
python -m app theme preview
```

## Run Tests
```powershell
python -m unittest discover -s tests -v
```

## Git Hooks (Auto Push)
Run once per local clone:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_git_hooks.ps1
```
This configures `core.hooksPath=.githooks` and enables push defaults so `post-commit` auto-push can run.
Set `WUT_NO_AUTO_PUSH=1` in your shell if you need to temporarily disable auto-push.

## Notes
- GUI requires `PySide6`.
- If `python -m app gui` fails with missing Qt packages, reinstall from `requirements.txt`.

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
