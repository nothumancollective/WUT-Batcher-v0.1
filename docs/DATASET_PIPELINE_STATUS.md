# Dataset Pipeline Status (Post-VACS Ingest)

## Scope
This note documents the current state of dataset ingestion after VACS export, the architectural decision, and the hardening changes implemented in this pass.

## 1) Status Quo Analysis

Current runtime path (`app/runtime_orchestrator.py`) already writes data in stages:

1. Planning stage:
- versions + resolved parameter snapshot persisted via SQL writer
- unset semantics already persisted (`version_params.is_set=0`)

2. ATH stage:
- ATH stdout parsed (`parse_ath_dimensions`)
- horn dimensions persisted in `ath_dimensions`

3. VACS stage:
- export files parsed via `vacs_txt_parser`
- rows persisted to `graphs`, `graph_series`, `graph_points`

Gaps found before this pass:
- VACS ingest used only file parsing (`*.txt`) and did not trust the authoritative ExportSpec mapping from the VACS export pipeline result.
- This could misclassify `graph_kind` when file headers/titles are ambiguous or misleading.
- No explicit contract check for missing mapped files or graph-kind mismatch against requested ExportSpec.

## 2) Ingestion Timing Decision

Decision: keep **multi-stage ingestion** (not a single end-of-run write).

Why:
- Better failure isolation and resumability.
- Faster debugging and incremental persistence.
- Clear step ownership:
  - plan metadata at materialization time,
  - ATH outputs after ATH,
  - graph data only after VACS export.

## 3) Robust + Fast Method

Method implemented:

1. Contract-first ingest for VACS exports
- If `run_vacs_export_specs` returns mapped exports, ingest uses those files as the authoritative set.
- Contract metadata (`spec_id`, `graph_kind`, `variant`, entry/details/plugin) is attached into export metadata.

2. Deterministic graph-kind assignment
- `graph_kind` in SQL now prefers ExportSpec mapping over parser inference.
- `graph_type` still stores parser-detected raw graph signature for diagnostics.

3. Fail-fast integrity gates
- Missing mapped file(s) => ingest reports `missing_contract_files`.
- Confident graph-kind conflict (e.g. expected SPL, parsed impedance hints) => `mapping_errors`.
- Runtime marks VACS stage failed if parse errors, mapping errors, missing contract files, or zero prepared rows.

4. Speed characteristics
- In contract mode, ingest uses mapped outputs directly (no full-directory blind dependency).
- Directory scan is retained only for optional diagnostics (`ignored_unmapped_files`) and fallback mode.

## 4) Implemented Code Changes

- `app/runtime_orchestrator.py`
  - Added export-contract extraction helpers.
  - Added graph-kind mismatch classifier.
  - Extended `_ingest_vacs_exports(..., vacs_export_summary=...)`.
  - Enforced stage failure on mapping/missing contract violations.

- `tests/test_runtime_orchestrator.py`
  - Added test: ExportSpec mapping overrides parser graph-kind.
  - Added test: graph-kind mismatch causes deterministic VACS failure and no graph rows.

## 5) Data Coverage After This Pass

Per version/run, SQL now contains:
- resolved ATH parameters + unset semantics (`versions`/`version_params`)
- ATH dimensions (`ath_dimensions`)
- VACS graph payloads (`graphs`, `graph_series`, `graph_points`)
- Export contract context in graph metadata (spec + mapping diagnostics)

Remaining optional enrichments (not required for correctness):
- Persist ATH console key-value extraction beyond dimensions.
- Persist file hashes for exported TXT in production dataset path.
- Cross-step provenance table for explicit stage lineage.
