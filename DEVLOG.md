# DEVLOG

## 2026-02-12
### Done
- Rebuild branch checked (`wut-batcher/rebuild` already active).
- Repository baseline analyzed:
  - Existing sweep planner, CFG renderer, compatibility engine, dataset importer inspected.
  - Current tests executed successfully (`13/13` passing).
- `ARCHITECTURE.md` created with Ist/Soll analysis and backlog.

### Next
- Introduce explicit domain-level `VersionSpec` and central resolver with `single|combined` semantics and `unset` handling.
- Add blocking compatibility validation during resolution.
- Start implementing target project storage layout and deterministic project-wide version IDs.

### Risks / Open Points
- Current snapshot references Runner automation in docs, but no `Runner/` directory exists in repo.
- Real ATH/AKABAK/VACS executable paths and invocation contracts are not yet validated in this workspace.

### Update 1
#### Done
- Added explicit execution-domain models:
  - `VersionSpec`, `ResolutionIssue`, `ResolveVersionsResult` in `app/models.py`.
- Implemented central resolver `app/version_resolver.py`:
  - deterministic version expansion (`single` and `combined`)
  - `unset_parameters` tracking for omitted ATH fields
  - project/batch/version compatibility blocking via `compat_engine`
  - deterministic project-wide version ID allocation with existing-ID carry-forward.
- Added machine-readable compatibility registry support in `app/compat_rules.py`.
- Implemented new target storage layer in `app/project_storage.py`:
  - `projects/<project_id>/...` structure
  - immutable project constraint enforcement
  - batch persistence and version materialization with placeholders/log paths.
- Implemented tidy dataset writer in `app/tidy_dataset.py`:
  - tidy CSV outputs for version parameters, measurements, ATH dimensions
  - schema output
  - optional parquet materialization when `pyarrow` is available
  - project table export (`tables/project_versions.csv`).
- Added high-level planner orchestration `app/batch_orchestrator.py`.
- Extended CLI with `plan materialize` command.
- Added tests:
  - `tests/test_version_resolver.py`
  - `tests/test_project_storage_and_tidy.py`
  - `tests/test_runners.py`
  - `tests/test_compat_rules.py`
- Full suite green: `21/21` tests passing.

#### Next
- Wire ATH runner into the new orchestration path as first concrete runtime step.
- Add ATH stdout dimension extraction into tidy writer flow.
- Add AKABAK/VACS runner staging hooks after ATH step.

#### Risks / Open Points
- Real ATH/AKABAK/VACS invocation flags are not validated yet in this repo snapshot.
- Runner wrappers are subprocess-safe but currently require explicit executable/path contracts from environment.

### Update 2
#### Done
- Added runtime stage orchestrator `app/runtime_orchestrator.py`.
  - Executes staged flow per version (`ATH -> AKABAK -> VACS`) with per-stage status persistence.
  - Renders CFG per version and parses ATH dimensions into tidy dataset rows.
- Extended CLI with `run pipeline` command for staged execution.
- Added runtime test `tests/test_runtime_orchestrator.py` (simulated ATH executable), suite now `22/22` green.

#### Next
- Bind real executable/automation contracts from the VM environment into `run pipeline` invocation.
- Integrate TXT export normalization from runtime stage into tidy measurement writer end-to-end.

#### Risks / Open Points
- AKABAK/VACS stages are currently subprocess wrappers and still need concrete UI-automation or CLI bridge contracts.
- Without real tool paths and flags, runtime behavior beyond ATH simulation remains environment-dependent.
