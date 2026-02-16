# LE Proof Matrix Report

Date: 2026-02-16

## Command
```powershell
python -m app runner-test le-proof-matrix --case test_cfg_baseline --profiles "control,mut_electrical,mut_motor" --repeats-per-profile 1 --keep-exports true --test-profile fast --matrix-seed 20260216 --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"
```

## Matrix Metadata
- `matrix_id`: `8878622b-9c75-48ff-8b22-8cc63a89eae5`
- `le_integration_diagnosis`: `le_active_confirmed`
- `threshold_policy`:
  - `spl_delta_rms >= 0.25`
  - `impedance_delta_rms >= 0.05`

## Run IDs
- `control`: `f1117950-bb82-4049-a99a-9e1f1e5dce43`
- `mut_electrical`: `8c26adac-4094-4e53-9758-b5e94d7aec8a`
- `mut_motor`: `5b844f8e-f8bc-4436-b4ee-93e47e1c7ec5`

## Effect Sizes
- `mut_electrical`:
  - `spl_delta_rms = 0.250374733444921` (passes threshold)
  - `impedance_delta_rms = 0.0`
- `mut_motor`:
  - `spl_delta_rms = 0.5543950365469512` (passes threshold)
  - `impedance_delta_rms = 0.0`

## Interpretation
- Composite proof is positive: LE mutation profiles changed SPL curves beyond control noise floor.
- RadImp remained normalized/all-zero baseline in these runs, therefore RadImp is retained as secondary KPI.

## Artifacts
- Report JSON:
  - `runner_test_workspace/logs/le_proof_matrix/8878622b-9c75-48ff-8b22-8cc63a89eae5/le_proof_comparison_report.json`
- Curve diff CSV:
  - `runner_test_workspace/logs/le_proof_matrix/8878622b-9c75-48ff-8b22-8cc63a89eae5/le_proof_curve_diff.csv`
