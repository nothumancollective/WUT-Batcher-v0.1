# Post-100k Inventory

- Generated: 2026-02-14T15:30:20.671037+00:00
- Database: `reports\ath_experiments\ath_experiments.sqlite`
- Database size: 1,062,617,088 bytes
- 100k run_groups discovered: pp100k_2100, pp100k_2101, pp100k_2102, pp100k_2103, pp100k_2104, pp100k_2105, pp100k_2106, pp100k_2107, pp100k_2108, pp100k_2109

## Table Rows
- `experiment_compare`: 115,640
- `experiment_metrics`: 115,640
- `experiment_params`: 6,128,920
- `experiment_runs`: 115,640

## Indexes
- `experiment_compare.sqlite_autoindex_experiment_compare_1`: autoindex
- `experiment_metrics.ix_experiment_metrics_height_mm`: CREATE INDEX ix_experiment_metrics_height_mm ON experiment_metrics(final_height_mm)
- `experiment_metrics.ix_experiment_metrics_length_mm`: CREATE INDEX ix_experiment_metrics_length_mm ON experiment_metrics(final_length_mm)
- `experiment_metrics.ix_experiment_metrics_width_mm`: CREATE INDEX ix_experiment_metrics_width_mm ON experiment_metrics(final_width_mm)
- `experiment_metrics.sqlite_autoindex_experiment_metrics_1`: autoindex
- `experiment_params.ix_experiment_params_key`: CREATE INDEX ix_experiment_params_key ON experiment_params(key)
- `experiment_params.ix_experiment_params_value_num`: CREATE INDEX ix_experiment_params_value_num ON experiment_params(value_num)
- `experiment_params.sqlite_autoindex_experiment_params_1`: autoindex
- `experiment_runs.ix_experiment_runs_case_index`: CREATE INDEX ix_experiment_runs_case_index ON experiment_runs(case_index)
- `experiment_runs.ix_experiment_runs_error_kind`: CREATE INDEX ix_experiment_runs_error_kind ON experiment_runs(ath_error_kind)
- `experiment_runs.ix_experiment_runs_group`: CREATE INDEX ix_experiment_runs_group ON experiment_runs(run_group_id)
- `experiment_runs.ix_experiment_runs_status`: CREATE INDEX ix_experiment_runs_status ON experiment_runs(status)
- `experiment_runs.sqlite_autoindex_experiment_runs_1`: autoindex
- `experiment_runs.ux_experiment_runs_group_seed_case`: CREATE UNIQUE INDEX ux_experiment_runs_group_seed_case
        ON experiment_runs(run_group_id, seed, case_index)
        

## Run Group Counts
| run_group | seed | total | ok | ath_error | pipeline_error | skipped |
|---|---:|---:|---:|---:|---:|---:|
| legacy_5000_seed2026 | 2026 | 5000 | 4408 | 586 | 0 | 6 |
| legacy_5000_seed2026_retry2 | 2026 | 50 | 44 | 6 | 0 | 0 |
| legacy_500_seed1337 | 1337 | 500 | 403 | 75 | 0 | 22 |
| legacy_500_seed1337_retry2 | 1337 | 20 | 18 | 2 | 0 | 0 |
| legacy_500_seed1337_retry3 | 1337 | 20 | 18 | 2 | 0 | 0 |
| pp100k_2100 | 2100 | 10000 | 7860 | 1842 | 0 | 298 |
| pp100k_2101 | 2101 | 10000 | 7880 | 1834 | 0 | 286 |
| pp100k_2102 | 2102 | 10000 | 7882 | 1844 | 0 | 274 |
| pp100k_2103 | 2103 | 10000 | 7885 | 1847 | 0 | 268 |
| pp100k_2104 | 2104 | 10000 | 7914 | 1799 | 0 | 287 |
| pp100k_2105 | 2105 | 10000 | 7873 | 1837 | 0 | 290 |
| pp100k_2106 | 2106 | 10000 | 7904 | 1815 | 0 | 281 |
| pp100k_2107 | 2107 | 10000 | 7877 | 1837 | 0 | 286 |
| pp100k_2108 | 2108 | 10000 | 7891 | 1845 | 0 | 264 |
| pp100k_2109 | 2109 | 10000 | 7937 | 1789 | 0 | 274 |
| pp10k_2026 | 2026 | 2000 | 1760 | 237 | 0 | 3 |
| pp10k_2027 | 2027 | 2000 | 1765 | 226 | 0 | 9 |
| pp10k_2028 | 2028 | 2000 | 1795 | 203 | 0 | 2 |
| pp10k_2029 | 2029 | 2000 | 1780 | 216 | 0 | 4 |
| pp10k_2030 | 2030 | 2000 | 1757 | 237 | 0 | 6 |
| pp10k_smoke_2026 | 2026 | 50 | 43 | 7 | 0 | 0 |

## Top Error Patterns by Run Group
- `legacy_5000_seed2026`: hard_cap_exceeded=501, diameter_over_100m=78, ath_nonzero_exit=5, numeric_overflow=2
- `legacy_5000_seed2026_retry2`: hard_cap_exceeded=5, diameter_over_100m=1
- `legacy_500_seed1337`: hard_cap_exceeded=61, diameter_over_100m=14
- `legacy_500_seed1337_retry2`: hard_cap_exceeded=2
- `legacy_500_seed1337_retry3`: hard_cap_exceeded=2
- `pp100k_2100`: hard_cap_exceeded=905, unknown=790, diameter_over_100m=145, ath_nonzero_exit=1, numeric_overflow=1
- `pp100k_2101`: hard_cap_exceeded=859, unknown=807, diameter_over_100m=166, numeric_overflow=2
- `pp100k_2102`: hard_cap_exceeded=863, unknown=814, diameter_over_100m=164, ath_nonzero_exit=3
- `pp100k_2103`: hard_cap_exceeded=894, unknown=794, diameter_over_100m=156, ath_nonzero_exit=3
- `pp100k_2104`: hard_cap_exceeded=841, unknown=799, diameter_over_100m=155, ath_nonzero_exit=4
- `pp100k_2105`: hard_cap_exceeded=898, unknown=788, diameter_over_100m=148, ath_nonzero_exit=3
- `pp100k_2106`: hard_cap_exceeded=839, unknown=809, diameter_over_100m=164, ath_nonzero_exit=3
- `pp100k_2107`: hard_cap_exceeded=872, unknown=837, diameter_over_100m=127, ath_nonzero_exit=1
- `pp100k_2108`: hard_cap_exceeded=874, unknown=813, diameter_over_100m=157, ath_nonzero_exit=1
- `pp100k_2109`: hard_cap_exceeded=832, unknown=799, diameter_over_100m=157, ath_nonzero_exit=1
- `pp10k_2026`: hard_cap_exceeded=203, diameter_over_100m=33, ath_nonzero_exit=1
- `pp10k_2027`: hard_cap_exceeded=184, diameter_over_100m=40, ath_nonzero_exit=1, numeric_overflow=1
- `pp10k_2028`: hard_cap_exceeded=167, diameter_over_100m=34, ath_nonzero_exit=2
- `pp10k_2029`: hard_cap_exceeded=180, diameter_over_100m=34, ath_nonzero_exit=1, numeric_overflow=1
- `pp10k_2030`: hard_cap_exceeded=208, diameter_over_100m=28, ath_nonzero_exit=1
- `pp10k_smoke_2026`: hard_cap_exceeded=6, diameter_over_100m=1

## Artifact Status
- latest `summary.json` run_group_id: `pp100k_aggregate_20260214_160319`
- latest summary analysis_run_groups: pp100k_2100, pp100k_2101, pp100k_2102, pp100k_2103, pp100k_2104, pp100k_2105, pp100k_2106, pp100k_2107, pp100k_2108, pp100k_2109
- latest summary is pp100k aggregate: True
- `summary.json`: exists=True size=65583 last_write=2026-02-14T15:04:03.788394+00:00
- `summary.md`: exists=True size=3635 last_write=2026-02-14T15:04:00.988881+00:00
- `range_suggestions.v1.json`: exists=True size=199946 last_write=2026-02-14T15:04:00.984864+00:00
- `range_suggestions.v1.1.json`: exists=True size=199946 last_write=2026-02-14T15:04:00.988881+00:00
- `range_suggestions.v1.2.json`: exists=True size=25354 last_write=2026-02-14T15:04:00.988881+00:00
- `compat_rule_candidates.v1.json`: exists=True size=15185 last_write=2026-02-14T15:04:03.720765+00:00
- `mode_error_matrix.json`: exists=True size=2130 last_write=2026-02-14T15:04:00.988881+00:00
- `data_inventory.md`: exists=True size=4555 last_write=2026-02-14T15:04:01.236938+00:00
- `precision_plan.md`: exists=True size=2505 last_write=2026-02-14T15:04:03.719023+00:00
- history snapshots: summary=14 range=14
- cleanup dirs: cases files=0, log files=0
