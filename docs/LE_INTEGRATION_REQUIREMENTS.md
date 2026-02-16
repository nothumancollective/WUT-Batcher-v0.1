# LE Integration Requirements

Date: 2026-02-16  
Scope: Runner test harness and preparation pipeline only (no production driver selector yet).

## Business Goal
- Prepare the batcher for future selectable LE driver models (multi-driver feature), starting with `generic25`.

## Technical Goal (Current Pass)
- Prove that the LE script is not only referenced, but has measurable effect in simulation output.
- Treat `RadImp` as a secondary KPI; do not use RadImp-only as proof of LE activation.

## In Scope
- Harness CLI and diagnostics (`runner-test`).
- Post-ATH LE repair + mutation profiles in run-local ABEC artifacts.
- Composite LE proof telemetry in `runner_test.sqlite`.
- Evidence docs and reproducible run protocol.

## Out of Scope
- Production UI for selecting arbitrary LE drivers.
- Changing production lock semantics (`LE=generic25`, `LE.Voltage=1.0`).
- Visual automation (forbidden).

## Definition Of Done
- Composite LE diagnosis exists per run: `le_active_confirmed` / `le_active_inconclusive` / `le_active_not_evidenced` / `le_proof_invalid`.
- `runner_test.sqlite` persists:
  - `le_proof_noise_floor`
  - `le_proof_effect_size`
  - `le_integration_diagnosis`
- Artifacts persisted:
  - `le_mutated_driver`
  - `le_proof_comparison_report`
  - `le_proof_curve_diff`
- Reproducible matrix command available:
  - `python -m app runner-test le-proof-matrix ...`
