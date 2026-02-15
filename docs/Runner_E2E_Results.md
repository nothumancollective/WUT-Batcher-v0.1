# Runner E2E Results (Current Pass)

Date: 2026-02-15

## Baseline Case
- Case: `test_cfg_baseline`
- Template CFG: `C:\Tools\ATH\test.cfg`
- Profile: `fast` (harness-only)

## Full E2E (latest)
- Run id: `15aaccb8-6120-49ed-8b71-74b65c90a3dd`
- Outcome: `failed`
- Failure point: AKABAK `open_project`

## Verified Improvements In This Pass
- ATH runtime config is now generated per run:
  - local `ath.cfg` + local `input.cfg`
  - mesh generation precondition is satisfied (`input.msh` present)
- Post-ATH LE repair is active and passing:
  - `generic25.txt` copied
  - `Project.abec` LEScript binding patched and asserted
- Pre-AKABAK mesh guard now passes in baseline run.

## Micro-Harness Runs (AKABAK)
- `open-dialog-only` latest single run:
  - run id: `6adf03a6-8a20-439d-9958-d854d9872c9e`
  - outcome: `failed` (dialog remains open)
- `open-dialog-only` latest single run with detailed control dump:
  - run id: `1f623ea8-6aa7-4950-a42f-bc8f8861454f`
  - outcome: `failed` (path readback correct, no dialog close)
- `import-start-apply-only` latest single run:
  - run id: `ea0d03e1-6e1e-4536-b4cb-ceef63c08328`
  - outcome: `failed` (post-apply timeout, no state change)

## Status
- No green full E2E run yet in this pass.
- Current blocker is narrowed to AKABAK open dialog close behavior under strict contract.
