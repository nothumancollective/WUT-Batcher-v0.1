# Analyzer Stage Migration E2E Smoketest

Date: 2026-02-24
Branch: `feature/polar-analyzer-ui`

## Environment

- Python offscreen UI smoke (`QT_QPA_PLATFORM=offscreen`)
- Real on-disk project datasets (no synthetic DB for smoke assertions):
  - `cleanup/runtime/postmerge_lib/P021/dataset/project.sqlite`
  - `runner_test_workspace/polar_e2e_smoke/run_20260221_143529/lib/P_SMOKE/dataset/project.sqlite`

## Steps and observations

### 1) Stage selector migration verification (UI)

Executed `AnalysePage` with real run payloads from service.

Observed selector items:
- `concept`
- `stabilization`
- `final`

No `shaping` option present.

### 2) H/V/D availability verification

#### Dataset A: `P021/B006` (postmerge runtime data)

- Service rows: 8
- Selected row planes: `['V', 'D']`
- Plane buttons:
  - `H`: disabled
  - `V`: enabled
  - `D`: enabled

DB inventory for this dataset confirms only `V` and `X3_45` exist for B006; no H rows are present.

#### Dataset B: `P_SMOKE/B_SMOKE` (real smoke runtime data)

- Service rows: 1
- Selected row planes: `['H', 'V', 'D']`
- Plane buttons:
  - `H`: enabled
  - `V`: enabled
  - `D`: enabled

This confirms Analyzer shows H when H exists in imported data.

### 3) Compare path smoke

For `P021/B006`, compare shortlist rendering and overlay/pareto render calls executed without exceptions.

Observed:
- shortlist table populated (`rowCount=5` with empty placeholders beyond selected rows)
- no crash in compare overlay render
- no crash in pareto render

## Conclusion

- Stage migration is active in UI and service flow (`Concept/Stabilization/Final`).
- Final-stage defaults are polar-only.
- H-plane visibility behavior is data-correct:
  - hidden/disabled when H data is missing in DB
  - available when H data exists in DB.
- No smoke-level crashes observed in Explorer/Compare update paths.

## Known limitations

- This smoke run is offscreen and scripted (not an interactive desktop click-through session).
- Full manual interactive UX validation should still be performed on a local desktop run.
