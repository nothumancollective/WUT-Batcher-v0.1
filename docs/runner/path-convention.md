# Runner Path & Artifact Convention (Authoritative)

Date: 2026-02-26  
Status: active convention for `wut-batcher/rebuild` runtime pipeline

## 1) Root types

- `app_root`:
  - repository/application root (code, scripts, static assets)
  - must not contain mutable user-run data
- `tools_root`:
  - external tool installations (`ATH`, `AKABAK`, `VACS`) resolved from user settings
  - must stay outside Project Library
- `library_root`:
  - portable user data root managed by `StorageManager`
  - contains `library.sqlite` + `projects/`
- `project_root`:
  - `<library_root>/projects/<project_folder>`
  - contains project JSON, project DB, versions, batches, runs
- `run_root`:
  - `<project_root>/runs/<run_id>/`
  - run-scoped metadata and diagnostics anchor for one batch execution

## 2) Canonical layout (current branch)

```text
<project_root>/
  db/project.sqlite
  versions/<version_id>/
    cfg/
      input.cfg
      <runtime_cfg_basename>.cfg
    ath_work/
      <runtime_cfg_basename>.cfg
      ath.cfg
    abec/
      Project.abec
      *.msh (if generated/copied)
    exports/<run_id>/
      *.txt
    logs/
      ath.stdout.log
      ath.stderr.log
      ath.runner.log
      ath.abec_sync.json
      pre_akabak_*.json
      vacs.export_pipeline.json
      pipeline.stage_debug.jsonl
  runs/
    <run_id>/
      pipeline.stage_debug.jsonl
    ath_export/
      <runtime_cfg_stem>/
        *(ATH-exported files if used by ATH build/profile)*
```

## 3) Invariants

- All stage paths are resolved from one runtime context (`PathContext`/`RunLayout`) created once per run.
- Writer/reader parity is mandatory:
  - if stage A writes `X`, stage B must read the exact `X` path from the same context object.
- No implicit repo-relative runtime roots for artifacts.
- No silent cleanup/runtime root fallback in GUI runs.
- Stage failures must report missing/invalid expected paths explicitly.

## 4) Stage mapping (inputs/outputs)

| Stage | Inputs | Outputs | Canonical paths |
|---|---|---|---|
| Batch planning | project/batch definitions | planned versions | DB + manifests only |
| ATH cfg generation | template + version params | static + runtime cfg | `versions/<V>/cfg/*` |
| ATH execution | runtime cfg + `ath_work` | ATH logs + generated artifacts | workdir `versions/<V>/ath_work`; logs `versions/<V>/logs/*`; export root `runs/ath_export/<cfg_stem>/` |
| Final dimensions export | ATH stdout | dimensions rows in DB | project DB + library DB mirror |
| ATH ABEC sync | expected ABEC artifact | canonical ABEC in version dir | target `versions/<V>/abec/Project.abec` |
| Post-ATH LE repair | canonical ABEC | LE-repaired ABEC + diagnostics | `versions/<V>/abec/*`, `versions/<V>/logs/le_repair_summary.json` |
| Pre-AKABAK guards | canonical ABEC + mesh refs | guard diagnostics | `versions/<V>/logs/pre_akabak_*.json` |
| AKABAK simulation | canonical ABEC | stage result summary | `versions/<V>/logs/*` + downstream process state |
| VACS export | canonical ABEC + export specs | exported TXT + export summary | `versions/<V>/exports/<run_id>/*`, `versions/<V>/logs/vacs.export_pipeline.json` |
| DB integration | VACS TXT exports | graph/measurement rows | project DB + library DB mirror |

## 5) Legacy/discovery policy

- Primary rule: deterministic direct paths first; discovery only as bounded fallback.
- Allowed bounded discovery:
  - within context-defined roots for the current version/run only (no global scans, no cleanup folder scans).
- Fallback must be explicit in logs:
  - include searched roots/candidates and selected path.
- Long-term migration direction:
  - shrink discovery usage to zero where tool output naming is deterministic.

## 6) Idempotency and safety

- Re-running the same batch creates a new `run_id` and isolated run diagnostics.
- Stage re-entry must not corrupt existing version artifacts; updates are overwrite-safe for canonical files (`Project.abec`, stage logs) and append-safe for run logs.
- Cleanup is explicit and guarded; never delete outside allowed context roots.
