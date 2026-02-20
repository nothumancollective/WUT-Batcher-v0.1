# 01 Findings

## F-001: FileNotFoundError spam during preview/batch validation path
- Classification: `substantial_bug`
- Paths:
  - `app/gui.py:3431`
  - `app/gui.py:3483`
  - `app/services.py:1310`
  - `app/project_storage.py:162`
- Evidence:
  - `audit/STATUS.md:90`
  - `audit/STATUS.md:102`
  - `audit/STATUS.md:114`
  - `audit/STATUS.md:126`
  - `audit/STATUS.md:127` (traceback block ends and test output continues with `ok`)
- Repro steps:
  - `python -m unittest discover -s tests -v *> audit/data/unittest_full_output.txt` (historical run artifact; do not rerun unbounded in this audit).
  - Inspect traceback section captured in `audit/STATUS.md`.
- Recommended fix:
  - In batch-draft validation path, handle missing project IDs explicitly and downgrade to structured UI validation issue instead of emitting traceback.
  - Add a guard path before `repo.load_project(...)` for transient/deleted temp projects.

## F-002: gmsh hang makes S07 runtime unstable
- Classification: `runtime_stability`
- Paths:
  - `app/cli.py:380`
  - `app/projectpage_ath_experiment.py:3562`
  - `app/runtime_orchestrator.py:367`
  - `app/runtime_orchestrator.py:373`
  - `app/runtime_orchestrator.py:435`
- Evidence:
  - `audit/data/scenario_runs_raw.json:348` (`"returncode": null`)
  - `audit/data/scenario_runs_raw.json:349` (`"timed_out": true`)
  - `audit/data/scenario_runs_raw.json:350` (`"duration_s": 3600.035`)
  - `audit/DEVLOG.md:71`
  - `audit/DEVLOG.md:74`
  - `audit/DEVLOG.md:78`
  - `audit/DEVLOG.md:79`
- Repro steps:
  - Run recorded S07 command from `audit/scenarios.md` (`S07_projectpage_ath_experiment_min`).
  - Observe 3600s timeout and manual gmsh termination evidence in DEVLOG.
- Recommended fix:
  - Add explicit gmsh subprocess watchdog/timeout + process-tree termination in runtime orchestration.
  - Persist per-stage timeout diagnostics (gmsh spawn/start/exit) into structured scenario result JSON so hangs are machine-detectable.

## F-003: stale docs point to missing runtime paths/files
- Classification: `documentation_drift`
- Paths:
  - `docs/ChatGPT_Context.md:13`
  - `docs/ChatGPT_Context.md:32`
  - `docs/ChatGPT_Context.md:33`
  - `docs/ChatGPT_Context.md:45`
- Evidence:
  - `audit/00_inventory.md:45`
  - `audit/00_inventory.md:46`
  - `audit/00_inventory.md:47`
  - `audit/00_inventory.md:49`
  - `audit/00_inventory.md:50`
  - `audit/00_inventory.md:51`
- Repro steps:
  - `rg -n "Runner/|run_full_batch_v5\\.py|start_gui\\.ps1" docs/ChatGPT_Context.md`
  - `Test-Path Runner`
  - `Test-Path run_full_batch_v5.py`
  - `Test-Path start_gui.ps1`
- Recommended fix:
  - Update docs to current `app/` and `scripts/` production entrypoints from `audit/00_inventory.md`.
  - Move deprecated path references into an explicit legacy appendix (or remove them).

## F-004: silent exception risk (tracebacks in UI tests while test stream continues)
- Classification: `test_signal_integrity`
- Paths:
  - `app/gui.py:3431`
  - `app/gui.py:3507`
  - `tests/test_preview_pipeline.py:294`
- Evidence:
  - `audit/STATUS.md:90` (traceback starts in test output)
  - `audit/STATUS.md:102`
  - `audit/STATUS.md:114`
  - `audit/STATUS.md:126`
  - `audit/STATUS.md:127` (`ok` immediately after traceback)
- Repro steps:
  - Use captured output artifact in `audit/STATUS.md` (from historical unittest run) showing traceback emission without immediate test abort.
- Recommended fix:
  - Add a test harness hook that fails on unhandled Qt/event-loop exceptions or stderr traceback emission.
  - In GUI timer callbacks, convert recoverable exceptions into explicit UI state and telemetry counters instead of raw traceback printing.
