# Stability Checkpoint 2026-02-21

Checkpoint date: 2026-02-21  
Trunk: `wut-batcher/rebuild`  
Head at checkpoint: `8a85bfc`

## Merged PRs #3-#8
- PR #8: `8a85bfc` (`2026-02-21`) - Merge pull request #8 from `cleanup/2026-02-22-quarantine-legacy`
- PR #7: `c59f24f` (`2026-02-21`) - Merge pull request #7 from `fix/2026-02-22-ath-experiment-exitcode`
- PR #6: `e44e813` (`2026-02-21`) - Merge pull request #6 from `fix/2026-02-21-preview-tests`
- PR #5: `cfa9669` (`2026-02-21`) - Merge pull request #5 from `fix/2026-02-21-batchpage-ui-tests`
- PR #4: `05c24e3` (`2026-02-21`) - Merge pull request #4 from `cleanup/2026-02-21-p1`
- PR #3: `a3effe2` (`2026-02-21`) - Merge pull request #3 from `cleanup/2026-02-20-p0`

Source command:
- `git log --merges --format="%h|%ad|%s" --date=short`

## Current Production CLI Surface
Source: `audit/production_surface.md` (from audit snapshot commit `9c5081f`).

Production commands:
- `doctor`
- `dataset build`
- `dataset update`
- `dataset sync-global`
- `plan materialize`
- `run pipeline`
- `run-sample`
- `gui`
- `runs pin`
- `runs unpin`
- `runs cleanup-testdata`

Production GUI entrypoints/flows:
- entrypoint: `app/gui.py:3759` (`main`) -> `app/gui.py:3734` (`launch_gui`)
- main run/export flow: save batch (`app/gui.py:3166`), run batch (`app/gui.py:3296`), export version (`app/gui.py:3398`)

## Bounded Test Baseline
Command:
- `python tools/audit/run_tests_bounded.py`

Latest result (this checkpoint run):
- exit code: `0`
- discovered: `330`
- selected: `184`
- skipped by default filter: `146`
- subprocess runs: `19`
- observed failures/errors: `0/0`

## Smoke Commands and Expected Behavior
- `python -m app --help`
  - expected: exit `0`, parser/entrypoint loads without runtime execution.
- `python -m app doctor --report-path <temp path>`
  - expected: JSON doctor output written to report path.
  - exit semantics: `0` unless doctor overall status is `fail` (then non-zero, currently `3`).
- `python -m app run-sample --dry-run --library-root <temp path>`
  - expected: dry-run orchestration only (no external tools), summary JSON printed.
  - exit semantics: `0` when dry-run checks pass; non-zero (currently `3`) on failed assertions.

## Operator Note
- Manual Run&Debug batch run succeeded cleanly.

## Related Manual External Verification
- See `cleanup/P2_PROD_FLOW_VERIFICATION.md` for the single-shot manual production-flow external verification procedure (`run pipeline`, strict timeout and persisted-status checks).

