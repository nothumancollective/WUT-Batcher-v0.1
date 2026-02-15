# generic25 (LE) in AKABAK: Where It Is and How To Restore

Date: 2026-02-15

## Executive Summary
- `generic25` is not a built-in "AKABAK default component" that lives inside the AKABAK install folder.
- It is an ATH-provided Lumped Element (LE) driver script file named `generic25.txt`.
- When `LE = generic25` is set in an ATH CFG, ATH is supposed to copy `generic25.txt` into the target ABEC project directory and configure the project to use it.
- If you cannot find `generic25` in AKABAK, the practical fix is to ensure `generic25.txt` exists in the ABEC project directory you are importing/solving, or to repair the ATH installation layout so the copy step works.

## Evidence (Local VM)
- ATH ships the driver script here:
  - `C:\Tools\ATH\lib\drivers\generic25.txt`
- Runner compatibility mode forces these keys in generated CFGs:
  - `ABEC.AkabakMode = 1`
  - `LE = generic25`
  - `LE.Voltage = 1.0`
  - Source: `app/constants.py`

## Evidence (ATH User Guide)
ATH 4.8.2 User Guide, section "6.13 Adding lumped element models" describes:
- Setting `LE = generic25` instructs ATH to copy `generic25.txt` from its drivers library into the target ABEC project directory and configure the ABEC project to use this script.
- This is the mechanism by which `generic25` becomes available to the AKABAK/ABEC toolchain.

Local copy referenced on this VM:
- `C:\Tools\ATH\doc\Ath-4.8.2-UserGuide.pdf` (hit on PDF page 59)

## Why It Can "Disappear" in AKABAK
Common reasons (observed/likely in practice):
1. The ABEC project directory does not contain `generic25.txt` even though `config.txt` says `LE = generic25`.
2. ATH cannot find its drivers library to perform the copy (e.g. installation folder layout differs from what ATH expects).
3. You are looking for `generic25` in AKABAK UI lists, but the script is meant to be provided via files in the ABEC project directory (or via ATH-managed library copy), not necessarily as a visible "default network" item.

## Restore Options (Deterministic)

### Option A: Fix the ABEC project folder (fastest)
For an existing ABEC export folder that contains `Project.abec` and `config.txt`:
1. Copy `generic25.txt` into the same directory as `Project.abec`.
   - Source on this VM: `C:\Tools\ATH\lib\drivers\generic25.txt`
2. Re-run the AKABAK import flow:
   - `Start Importing` -> `Apply`
3. Verify the file is present (precondition):
   - `Test-Path "<abec_dir>\generic25.txt"`

This makes the dependency explicit and avoids relying on global install paths.

### Option B: Repair the ATH driver-library layout (long-term)
If ATH is expected to copy drivers automatically but does not:
1. Verify that the driver script exists in the ATH installation.
2. Ensure the ATH installation layout matches what your ATH build expects for its driver library.
   - Some docs refer to a `bin\lib\drivers` location relative to the ATH executable.
3. Re-run ATH to regenerate the ABEC project and confirm it now includes `generic25.txt`.

## Related Precondition (Not generic25, but blocks the same flow)
If AKABAK import fails with missing mesh artifacts (e.g. `ath.msh`), that is independent of `generic25` and must be resolved first (typically Gmsh path / meshing).

## “Always Available” In AKABAK (What Is and Isn’t Possible)
If by “default option in AKABAK” you mean a built-in entry that appears in AKABAK menus/component pickers without any project context:
- `generic25.txt` does not appear to be shipped as an AKABAK internal default library item.
- It is an ATH/ABEC LE script. In practice it is consumed by ABEC projects (and therefore AKABAK’s ABEC import flow) via the filesystem.

What you can do reliably:
1. Make `generic25.txt` available in a stable, user-owned “AKABAK library” folder so it is always one click away in file dialogs, regardless of where you started AKABAK from.
2. Ensure every ABEC project you import/solve contains the file locally (portable), or points to it via a stable absolute path (non-portable).

### Recommended Setup: User Library Folder
Create a stable folder in your user profile, e.g.:
- `%USERPROFILE%\Documents\AKABAK_Library\drivers\generic25.txt`

Then:
1. Copy the ATH-provided file into that folder.
2. (Optional) Point AKABAK’s start/initial folder in `Akabak.ini` to this library folder to make dialogs open there by default.

This improves manual workflows, but ABEC import still requires the script to be resolvable by the ABEC project (see next section).

### Recommended Setup: Always Resolvable For ABEC Import
To make ABEC import succeed regardless of where the ABEC project came from:
- Preferred: copy `generic25.txt` into each ABEC project directory (portable).
- Alternative: modify the ABEC/LE script reference to an absolute path in your library folder (works locally, breaks portability).

## Quick Commands (Copy/Paste)
Check presence:
```powershell
Test-Path "C:\Tools\ATH\lib\drivers\generic25.txt"
Test-Path "<ABEC_PROJECT_DIR>\generic25.txt"
```

Copy into an ABEC project dir:
```powershell
Copy-Item "C:\Tools\ATH\lib\drivers\generic25.txt" "<ABEC_PROJECT_DIR>\generic25.txt"
```
