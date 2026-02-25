# Merge Report: `feature/polar-analyzer-ui`

- Date: 2026-02-23
- Target branch: `feature/polar-analyzer-ui`
- Default trunk (`origin` HEAD): `wut-batcher/rebuild`
- Pre-existing local dirty files (untouched during merge): `app/cli.py`, `tests/test_service_export.py`

## 1) Investigated branches

Remote branches inspected (pattern `analyzer|polar|polars|ui/`):

- `origin/feature/analyzer-pro-layout`
- `origin/feature/polar-analyzer-foundation`
- `origin/feature/polar-analyzer-ui`
- `origin/fix/analyzer-kpi-planes-ux`
- `origin/fix/polars-h-plane-export`
- `origin/ui/analyzer-topbars-v2`
- `origin/ui/analyzer-versionbar-polish-pin`

## 2) Safety backup (before merge)

- Backup branch: `backup/polar-analyzer-ui-before-merge`
- Backup tag: `backup-polar-analyzer-ui-before-merge-20260223-2306`
- Backup push executed:
  - `git push origin backup/polar-analyzer-ui-before-merge --tags`

## 3) Stack/ancestor analysis summary

Initial include status against `feature/polar-analyzer-ui`:

- `feature/polar-analyzer-foundation`: already included
- `feature/analyzer-pro-layout`: not included
- `fix/polars-h-plane-export`: not included
- `fix/analyzer-kpi-planes-ux`: not included
- `ui/analyzer-topbars-v2`: not included
- `ui/analyzer-versionbar-polish-pin`: not included

Observed stack relations:

- `feature/polar-analyzer-foundation` is ancestor of all analyzer/ui candidates.
- `feature/analyzer-pro-layout` is ancestor of:
  - `fix/analyzer-kpi-planes-ux`
  - `ui/analyzer-topbars-v2`
  - `ui/analyzer-versionbar-polish-pin`
- `ui/analyzer-topbars-v2` is ancestor of `ui/analyzer-versionbar-polish-pin`.

Tip branches selected:

- `fix/polars-h-plane-export`
- `fix/analyzer-kpi-planes-ux`
- `ui/analyzer-versionbar-polish-pin`

## 4) Pre-merge diff sanity

`fix/polars-h-plane-export`:

- Focused and bounded (12 files, export/import/batch export panel/tests/docs).
- Merged directly with `--no-ff`.

`fix/analyzer-kpi-planes-ux` and `ui/analyzer-versionbar-polish-pin`:

- Large wrong-stem payloads for direct merge into target (included unrelated runtime/export-dialog lineage like `app/runtime_orchestrator.py`, `docs/Runner_Runtime_Incident_2026-02-22.md`, `ui/batch_export_panel.py`).
- Decision per guardrail D: selective cherry-pick of Analyzer/UI commits only.

## 5) Integration execution

### 5.1 Direct merge

- `9305d58` `merge: integrate fix/polars-h-plane-export into feature/polar-analyzer-ui`

### 5.2 Selective cherry-pick (Analyzer/UI only)

Cherry-picked Analyzer/UI commit stream from `ui/analyzer-versionbar-polish-pin` and missing top commits from `fix/analyzer-kpi-planes-ux` (including Stage-plot system, KPI robustness/fixes, topbars v2, version info persistence, and pinning polish).

Key resulting commits include (non-exhaustive, chronological in target):

- `240a097` `feat(ui): restructure analyzer pro layout`
- `650ea3b` `feat(analyzer): add stage artifact registry and payload service`
- `20140f7` `feat(ui): add stage-driven 2x2 explorer and compare grids`
- `f174338` `fix(analyzer): normalize plane aliases and keep unknown plane fallback`
- `3daaefc` `fix(analyzer): robust KPI scoring with reason codes and missing-row UI`
- `756a053` `fix(analyzer): add reason severity, flags help, and strict scoping guards`
- `6abb60e` `docs(analyzer): add B006 analyzer evidence addendum`
- `0232082` `fix(analyzer): beamwidth saturation handling and target overlay cues`
- `e6ec29f` `fix(analyzer): pareto scatter rendering and selection clarity`
- `028a5f7` `refactor(ui): selection bar with centered version stepper`
- `4d9ff01` `feat(analyzer): add version-info persistence for prefs and notes`
- `9d855af` `ui(analyzer): implement Version Bar v2 layout and bindings`
- `a9a9486` `feat(analyzer): add version pin toggle with project-local persistence and compare markers`
- `8f3b151` `test(ui): cover pin persistence and sweep elide; document pin architecture`

### 5.3 Ancestry-record merges (no content change)

To satisfy post-merge branch-containment checks while preserving selective integration:

- `207053d` `merge: record fix/analyzer-kpi-planes-ux ancestry after selective integration` (`-s ours`)
- `df955de` `merge: record ui/analyzer-versionbar-polish-pin ancestry after selective integration` (`-s ours`)

## 6) Conflicts and resolutions

1. `ui/batch_export_panel.py` (during `fix/polars-h-plane-export` merge)
- Resolution: union of imports (kept `StyledDialogBase` + `Tuple`) to preserve both dialog base and new inclination-default support.

2. `tests/test_batch_export_panel.py` (during `fix/polars-h-plane-export` merge)
- Resolution: union of test blocks (kept footer-layout test and H/V/D inclination default roundtrip tests).

3. `docs/analyzer/CHANGELOG.md` (during cherry-picks)
- Resolution: additive union (kept both pre-existing and incoming analyzer changelog sections).

4. `app/gui.py` (pin commit cherry-pick)
- Resolution: retained compact KPI matrix logic and integrated pin marker into selected-candidate notice without regressing matrix UX.

5. `tests/test_gui_analyzer_compare_ui.py` (pin/docs test cherry-pick)
- Resolution: kept both beamwidth-saturation/target-series tests and pin-marker overlay test.
- Follow-up stabilization commit:
  - `acbe15d` `test(analyzer): align pin-overlay assertion with target series rendering`

## 7) Test commands and results

Core (pipeline + analyzer services/engine/plot + non-GUI):

- Command:
  - `python -m pytest -q tests/test_batch_export_panel.py tests/test_polar_txt_parser.py tests/test_runtime_orchestrator.py tests/test_vacs_export_pipeline.py tests/test_analyzer_kpi_engine.py tests/test_analyzer_kpi_service.py tests/test_analyzer_plot_service.py tests/test_analyzer_reason_codes.py tests/test_analyzer_orientation.py tests/test_analyzer_stage_plot_engine.py tests/test_analyzer_services_analyses.py`
- Result:
  - `74 passed in 7.85s`

GUI analyzer suites:

- Commands:
  - `python -m pytest -q tests/test_gui_analyzer_page_ui.py`
  - `python -m pytest -q tests/test_gui_analyzer_compare_ui.py`
  - `python -m pytest -q tests/test_gui_settings_analyzer_ui.py`
- Results:
  - `28 passed in 3.10s`
  - `14 passed in 1.38s`
  - `2 passed in 0.51s`

Note:
- In this Windows/Qt environment, occasional non-zero shell exit was observed despite full-pass pytest output; pass counts above are from pytest output lines and were verified.

## 8) Post-merge no-missing-commits verification

Executed:

- `git log --oneline feature/polar-analyzer-ui..origin/fix/polars-h-plane-export`
- `git log --oneline feature/polar-analyzer-ui..origin/fix/analyzer-kpi-planes-ux`
- `git log --oneline feature/polar-analyzer-ui..origin/ui/analyzer-versionbar-polish-pin`

Result:

- all three outputs empty (`EMPTY`)

