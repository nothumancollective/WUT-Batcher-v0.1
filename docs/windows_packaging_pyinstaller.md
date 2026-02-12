# Windows Packaging (PyInstaller)

## Ziel
- Reproduzierbares Packaging der GUI/CLI fuer Windows.
- Keine Aenderungen an Runner-Automation, nur Packaging/Distribution.

## Build Environment
1. Windows 10/11 x64.
2. Python 3.12 (empfohlen, identisch zur Entwicklungsumgebung).
3. Virtuelle Umgebung aktivieren.
4. Abhaengigkeiten installieren:
```powershell
python -m pip install --upgrade pip
python -m pip install pyinstaller pyside6
```

## Preflight
```powershell
python -m app --help
python -m app.gui --doctor-only --verbose
python -m py_compile app\gui.py app\cli.py
```

## PyInstaller (One-Folder)
```powershell
pyinstaller --noconfirm --clean --name Batch-Software-GUI --onedir --windowed --collect-all PySide6 --add-data "templates;templates" --add-data "app\assets;app\assets" app\gui.py
```

## PyInstaller (CLI)
```powershell
pyinstaller --noconfirm --clean --name Batch-Software-CLI --onedir app\__main__.py
```

## Qt/PySide6 Pitfalls
1. Fehlende Qt-Plugins (`platforms`, `styles`, `imageformats`) fuehren zu Startfehlern.
2. Bei Plugin-Fehlern Build mit `--collect-all PySide6` wiederholen.
3. SVG/PNG Assets muessen mit `--add-data` explizit eingebunden sein.
4. Beim Test immer aus `dist\...` starten, nicht aus Source-Root.

## Smoke Test aus `dist`
```powershell
.\dist\Batch-Software-CLI\Batch-Software-CLI.exe --help
.\dist\Batch-Software-GUI\Batch-Software-GUI.exe --doctor-only --verbose
```

## Release-Hinweise
- `app_settings.json` liegt pro User im Config-Verzeichnis und gehoert nicht ins Paket.
- Projektdateien bleiben portabel; maschinenspezifische Pfade bleiben in Settings.
