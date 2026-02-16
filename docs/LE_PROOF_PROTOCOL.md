# LE Proof Protocol (Composite KPI)

Date: 2026-02-16

## Primary Proof Strategy
- A/B sensitivity test with same geometry and controlled LE script mutations.
- Profiles:
  - `control`
  - `mut_electrical`
  - `mut_motor`

Mutations happen only in run-local copied driver file under harness artifacts. Tool installation files are never patched.

## Decision Logic
1. Estimate control noise floor from pairwise control-run curve deltas.
2. Compute mutation effect size against controls.
3. Threshold policy:
- `threshold = max(5 * control_noise_floor, absolute_min_floor)`
- default absolute minima:
  - SPL delta RMS: `0.25 dB`
  - Impedance delta RMS: `0.05` (normalized)
4. Classify:
- `le_active_confirmed`: at least one mutation profile exceeds threshold robustly.
- `le_active_not_evidenced`: technically valid runs but no mutation exceeds threshold.
- `le_active_inconclusive`: insufficient evidence (e.g. dry-run).
- `le_proof_invalid`: technical preconditions violated (missing valid controls, etc.).

## Bias Guards
- Fixed seed randomization of run order (`--matrix-seed`).
- Blind metric computation from DB curve data only (no UI labels in scoring path).
- Positive control gate: SPL must be non-trivial in controls.
- Persist full evidence payload in DB/artifacts per run.

## Command
```powershell
python -m app runner-test le-proof-matrix --case test_cfg_baseline --profiles "control,mut_electrical,mut_motor" --repeats-per-profile 3 --matrix-seed 20260216 --keep-exports true --test-profile fast
```
