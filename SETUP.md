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

## Notes
- GUI requires `PySide6`.
- If `python -m app gui` fails with missing Qt packages, reinstall from `requirements.txt`.
