# 02 Cleanup Plan

## Evidence Baseline
- Production entrypoints/orchestrators: `audit/00_inventory.md:11`, `audit/00_inventory.md:23`, `audit/00_inventory.md:31`.
- DB families: `audit/00_inventory.md:34`, `audit/00_inventory.md:39`.
- Bounded tests execution baseline: `audit/tests_summary.md:11`, `audit/tests_summary.md:12`, `audit/tests_summary.md:13`, `audit/tests_summary.md:18`, `audit/tests_summary.md:20`.
- Findings baseline: `audit/01_findings.md:3`, `audit/01_findings.md:25`, `audit/01_findings.md:49`, `audit/01_findings.md:72`.
- gmsh instability evidence: `audit/DEVLOG.md:71`, `audit/DEVLOG.md:74`, `audit/DEVLOG.md:78`.
- Stale docs mismatch evidence: `audit/00_inventory.md:44`.

## Production Surface Definition
Minimal runtime surface to ship (all executable paths currently used in scenarios):
- Entrypoints:
  - `app/__main__.py:3`
  - `app/cli.py:1834`
  - `app/gui.py:3759`
  - `scripts/vacs_export_save_all.py:2297`
  - `scripts/vacs_export_dialog_rounds.py:589`
  - `scripts/vacs_interim_reimport.py:921`
  - `ui/theme_preview.py:115`
- Core orchestrators/services:
  - `app/services.py:1848`
  - `app/runtime_orchestrator.py:1258`
  - `app/projectpage_ath_experiment.py:3562`
  - `app/runner_test_harness.py:1` (module-level harness orchestration used in S05/S06 traces)
- Required DB families:
  - Project/global DB: `app/sql_dataset_store.py:139`
  - Runner test DB: `app/runner_test_db.py:75`
  - ATH experiments DB: `app/projectpage_ath_experiment.py:1137`

## P0 (Blockers, do first)
1. Harden gmsh/ATH stage timeout and kill behavior.
   - Scope:
     - `app/runtime_orchestrator.py:367`
     - `app/runtime_orchestrator.py:373`
     - `app/runtime_orchestrator.py:435`
     - `app/projectpage_ath_experiment.py:3562`
   - Action:
     - Add explicit gmsh subprocess watchdog with process-tree termination and stage-level structured error output.
   - Why now:
     - S07 reached 3600s timeout and required manual unblocking (`audit/01_findings.md:25`).
   - Risk:
     - Medium (touches external-process control).
   - Expected runtime impact (estimate):
     - Worst-case hang cap reduction from ~3600s to configured timeout window (<10 minutes).

2. Promote hidden UI tracebacks into explicit failure signals.
   - Scope:
     - `app/gui.py:3431`
     - `app/gui.py:3507`
     - `tests/test_preview_pipeline.py:294`
   - Action:
     - Fail tests on unhandled GUI/event-loop tracebacks; add structured GUI error channel for batch-draft validation path.
   - Why now:
     - Tracebacks are present while test stream continues (`audit/01_findings.md:72`).
   - Risk:
     - Medium (may surface currently masked failures).
   - Expected runtime impact (estimate):
     - Neutral to slight positive (less noisy retries/debugging loops).

3. Align stale docs with real runtime surface.
   - Scope:
     - `docs/ChatGPT_Context.md:13`
     - `docs/ChatGPT_Context.md:32`
     - `docs/ChatGPT_Context.md:33`
     - `docs/ChatGPT_Context.md:45`
   - Action:
     - Replace missing `Runner/` / `run_full_batch_v5.py` / `start_gui.ps1` references with current entrypoints from `audit/00_inventory.md`.
   - Why now:
     - Prevents operators from invoking non-existent flow (`audit/01_findings.md:49`).
   - Risk:
     - Low.
   - Expected runtime impact (estimate):
     - Indirect positive (fewer dead-end operator runs).

## P1 (Isolate complexity, medium risk)
1. Isolate non-core CLI surfaces behind explicit optional group.
   - Scope:
     - `app/cli.py:1452`
     - `app/cli.py:1564`
     - `app/cli.py:1703`
   - Action:
     - Separate ATH experiment admin and analysis subcommands into dedicated module import path (`app/cli_ath_experiments.py`) loaded lazily by command selection.
   - Evidence:
     - High parser out-degree/orchestration concentration in CLI (`audit/00_inventory.md:28`).
   - Risk:
     - Medium.
   - Expected runtime impact (estimate):
     - Faster CLI startup and reduced import churn for non-ATH commands.

2. Isolate UI automation and VACS script pathways from core run pipeline.
   - Scope:
     - `app/cli.py:1750`
     - `app/ui_automation/session.py:1`
     - `scripts/vacs_export_save_all.py:2297`
     - `scripts/vacs_export_dialog_rounds.py:589`
     - `scripts/vacs_interim_reimport.py:921`
   - Action:
     - Keep these as optional operational tools and avoid implicit dependency in base CLI commands.
   - Evidence:
     - Dedicated S10 surface; not needed for S01-S06/S09 core CLI flows (`audit/scenario_results.md`).
   - Risk:
     - Medium.
   - Expected runtime impact (estimate):
     - Reduced accidental UI automation initialization in non-UI workflows.

3. Normalize scenario/test status semantics.
   - Scope:
     - `app/cli.py:175`
     - `app/cli.py:618`
     - `app/cli.py:380`
   - Action:
     - Ensure command exit code reflects internal failure states (currently several scenarios report fail status in payload while returning `0`).
   - Evidence:
     - `S04`, `S06`, `S09` marked unstable with fail payload signals (`audit/scenario_results.md`).
   - Risk:
     - Medium (changes automation expectations).
   - Expected runtime impact (estimate):
     - Faster CI diagnosis; fewer false-green runs.

## P2 (Cleanup/refactor candidates, lower urgency)
1. Separate DB ownership boundaries by command family.
   - Scope:
     - `app/sql_dataset_store.py:139`
     - `app/runner_test_db.py:75`
     - `app/projectpage_ath_experiment.py:1137`
   - Action:
     - Introduce explicit repository interfaces per DB family and ban cross-family writes.
   - Evidence:
     - Multiple DB families active in inventory (`audit/00_inventory.md:39`).
   - Risk:
     - Medium-low.
   - Expected runtime impact (estimate):
     - Lower lock contention and clearer migration paths.

2. Documentation + legacy isolation pass.
   - Scope:
     - `docs/ChatGPT_Context.md`
     - `docs/DATASET_PIPELINE_STATUS.md`
     - `docs/LE_RESEARCH_LOG.md`
   - Action:
     - Move legacy instructions into explicit `legacy/` docs section; keep operational docs aligned with `app/` and `scripts/` runtime.
   - Evidence:
     - Already observed mismatch in `audit/00_inventory.md:44`.
   - Risk:
     - Low.
   - Expected runtime impact (estimate):
     - Operational clarity and reduced human-error runtime churn.

3. Cold-code deletion candidates only after additional hit-mapping pass.
   - Scope:
     - Candidate modules not touched in scenarios/tests (to be derived from coverage + bounded runner map).
   - Action:
     - Require `production_hot/production_warm/test_only/cold` classification before deleting.
   - Evidence:
     - Bounded suite currently executed with skip filters (`audit/tests_summary.md:8`, `audit/tests_summary.md:13`), so UI-heavy surfaces still need explicit targeted validation before deletion.
   - Risk:
     - Medium (false-positive deletion risk).
   - Expected runtime impact (estimate):
     - Potentially high after safe classification.
