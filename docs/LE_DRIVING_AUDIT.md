# LE Driving Audit (ATH -> AKABAK -> VACS)

## Scope
- Reviewed modules: `app/runner_test_harness.py`, `app/akabak_driver.py`, `app/vacs_export_pipeline.py`, `app/vacs_txt_parser.py`, `app/runtime_orchestrator.py`, `app/services.py`, `app/runner_test_db.py`, `app/cli.py`.
- Focus: ATH launch context, ABEC discovery, preflight/validation coverage, missing LE-driving contracts.

## Current State
- ATH launch:
  - Harness writes `ath.cfg` into run-local folder and executes ATH with `workdir=<ath_run_dir>` (`runner_test_harness`).
  - Runtime pipeline executes ATH with `workdir=<version>/ath_work` (`runtime_orchestrator`).
  - Export service executes ATH with `workdir=<export_dir>` (`services.export_version`).
- ABEC detection:
  - Harness locates generated ABEC via recursive search in the ATH run dir (`_locate_abec_file`).
  - Runtime path assumes canonical project layout (`versions/<id>/abec/Project.abec`).
  - Export service copies newest generated ABEC to `<export_dir>/Project.abec`.
- Existing validations:
  - Pre-AKABAK mesh guard from `[MeshFiles]` references (`_parse_abec_mesh_requirements`).
  - Export validations: file existence, size/point thresholds, monotonic x, finite values, all-zero detection, graph-kind mismatch.
  - Micro-harnesses exist for:
    - `open-dialog-only`
    - `import-start-apply-only`
- UI automation style:
  - Non-visual UIA/handle-based flow.
  - Deterministic `Start Importing -> Apply` flow in `AkabakDriver.import_if_needed`.

## Gap Identified Before This Pass
- Post-ATH LE binding contract was incomplete:
  - `generic25.txt` copy could be missing.
  - `Project.abec` could contain empty `[LEScript] Scriptname_LEScript`.
  - No mandatory fail-fast assertion that both are valid before AKABAK import.

## Implemented in This Pass
- Central post-ATH LE repair contract introduced in `app/ath_driver_assets.py`:
  - copy `generic25.txt` to ABEC dir (hash-aware/idempotent),
  - patch `Project.abec` to enforce `[LEScript] Scriptname_LEScript=generic25.txt` (idempotent),
  - assert script existence + non-empty binding + exact expected filename,
  - optional diagnostics snapshots (`Project.abec` before/after + summary JSON).
- Integrated into:
  - harness (`post_ath_le_repair` step + DB artifacts/validation),
  - runtime pipeline (`post_ath_le_repair` stage),
  - export service (manifest stores repair result).

## Artifacts That Must Be Persisted (LE/Driving Reliability)
- Always persist:
  - repaired `Project.abec` path and hash,
  - copied `generic25.txt` path and hash,
  - LE repair summary payload (copy result, patch result, assertion states),
  - `Project.abec` before/after snapshots for diff-based diagnosis.
- On AKABAK import failure:
  - interpreter/open-dialog diagnostics dumps,
  - UI observation snapshot with window signatures and dump paths.
- For RadImp debug:
  - observation script evidence (`observation.txt` path + RadImp markers),
  - exported graph classification and all-zero metrics,
  - modal dialog history (especially muted-source hints).
