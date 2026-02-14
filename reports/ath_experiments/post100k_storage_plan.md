# Post-100k Storage Plan

- Generated: 2026-02-14T15:30:20.669757+00:00
- DB size: 1,062,617,088 bytes
- SQLite pragmas: journal_mode=delete, page_size=4096, page_count=259428, freelist_count=0

## Observed Query Costs
| query | rows | elapsed_ms |
|---|---:|---:|
| run_group_outcomes | 21 | 10.67 |
| top_errors | 70 | 40.88 |
| key_coverage | 53 | 17608.54 |
| mode_matrix_pp100k | 54 | 2345.17 |

## Why Queries Slow Down
- `experiment_params` has >6M rows; full key-coverage scans dominate runtime.
- Mode/error matrix currently pivots params per run on demand.

## Concrete Optimizations
1. Add composite index `experiment_params(run_id, key, is_set, value_num)`.
2. Add composite index `experiment_runs(run_group_id, status, ath_error_kind)`.
3. Materialize rollups per run_group (key coverage, mode matrix, error classes).
4. For long ingestion windows, consider WAL mode + periodic checkpoints (with backup policy).
5. For 1M+ runs, partition by epoch (`ath_experiments_YYYYQX.sqlite`) and aggregate across DBs.
6. Keep per-case files disabled/cleaned; commit only aggregate artifacts and snapshots to Git.
