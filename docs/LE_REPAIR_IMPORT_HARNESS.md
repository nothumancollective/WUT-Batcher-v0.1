# LE Repair + Import Harness

## Purpose
- Deterministic post-ATH LE repair before AKABAK import.
- UIA-only import validation using `Start Importing -> Apply`.
- Repeatable micro-harness for flake detection and diagnostics.

## Post-ATH LE Repair Contract
- Copy `generic25.txt` from `ATH/lib/drivers` into the ABEC project directory.
- Patch `Project.abec` idempotently:
- ensure section `[LEScript]`
- ensure `Scriptname_LEScript=generic25.txt`
- Assert before AKABAK import:
- script file exists in ABEC directory
- LEScript binding is non-empty
- LEScript binding matches expected script file name

Artifacts persisted in `runner_test.sqlite`:
- `le_driver`
- `abec_before_patch`
- `abec_after_patch`
- `le_repair_summary`
- validation: `post_ath_le_repair_assertions`

## CLI

Use existing exported ABEC:

```powershell
python -m app runner-test le-repair-import-only --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --ath-exe "C:\Tools\ATH\ath.exe" --abec-path "C:\Horns\test\ABEC_FreeStanding\Project.abec" --repeats 5
```

Run ATH first, then repair/import:

```powershell
python -m app runner-test le-repair-import-only --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --ath-exe "C:\Tools\ATH\ath.exe" --ath-cfg-path "C:\Tools\ATH\my_case.cfg" --repeats 5
```

## Postcondition Strategy
- Primary postcondition: `import_if_needed` contract (`Start Importing -> Apply` completion).
- LE-specific contract: ABEC LEScript binding is validated after repair.
- Additional UI-tree probe: interpreter search for `generic25` token is recorded as diagnostics (non-visual, non-blocking).

## RadImp Diagnosis (E2E Harness)
- Validation row: `radimp_diagnosis`
- Diagnostic classes:
- `sources_muted_dialog_seen`
- `solve_succeeded_radimp_all_zero`
- `observation_misconfigured_or_wrong_export`
- `radimp_nonzero_or_not_flagged`
- `radimp_not_requested`
