# ATH Experiment Data Inventory

- Generated at: 2026-02-14T16:25:34+00:00
- Database: `C:\Users\maximilianheinze\Desktop\WUT Batcher v0.1\reports\ath_experiments\ath_experiments.sqlite`
- Remaining NULL run_group rows: 0

## Relevant Data Model
- `experiment_runs`: outcomes, grouping (`run_group_id`, `seed`, `case_index`), ATH errors/warnings, file refs.
- `experiment_params`: Project-page input snapshot (`key`, `value_text/value_num`, `is_set`).
- `experiment_metrics`: observed dimensions/angles (`final_width_mm`, `final_height_mm`, `final_length_mm`, `avg_throat_angle_deg`).
- `experiment_compare`: compare-quality flags (`config_ok`, `no_ghosts`) and mismatch payloads.

## Tables and Columns
- `experiment_compare`: rows=116040, columns=run_id, config_ok, no_ghosts, missing_keys_required_json, missing_keys_optional_json, extra_keys_defaulted_json, extra_keys_ghost_json, mismatch_json
- `experiment_metrics`: rows=116040, columns=run_id, final_width_mm, final_height_mm, final_length_mm, avg_throat_angle_deg, derived_volume_m3, flags_json
- `experiment_params`: rows=6646524, columns=run_id, key, value_text, value_num, is_set
- `experiment_runs`: rows=116040, columns=run_id, created_at, seed, case_index, status, ath_exit_code, ath_error_kind, ath_error_message, ath_warning_count, cfg_path, horns_export_dir, stdout_path, stderr_path, notes, run_group_id, error_pattern_refined, compare_class_primary, compare_classes_json

## Run Groups (including legacy)
| run_group | seed | total | ok | ath_error | pipeline_error | skipped | min_case | max_case |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cmpfix2_smoke_20260214T1630Z | 2402 | 200 | 175 | 17 | 0 | 8 | 1 | 200 |
| cmpfix_smoke_20260214T1602Z | 2401 | 200 | 160 | 29 | 0 | 11 | 1 | 200 |
| legacy_5000_seed2026 | 2026 | 5000 | 4408 | 586 | 0 | 6 | 1 | 5000 |
| legacy_5000_seed2026_retry2 | 2026 | 50 | 44 | 6 | 0 | 0 | 1 | 50 |
| legacy_500_seed1337 | 1337 | 500 | 403 | 75 | 0 | 22 | 1 | 500 |
| legacy_500_seed1337_retry2 | 1337 | 20 | 18 | 2 | 0 | 0 | 1 | 20 |
| legacy_500_seed1337_retry3 | 1337 | 20 | 18 | 2 | 0 | 0 | 1 | 20 |
| pp100k_2100 | 2100 | 10000 | 7860 | 1842 | 0 | 298 | 1 | 10000 |
| pp100k_2101 | 2101 | 10000 | 7880 | 1834 | 0 | 286 | 1 | 10000 |
| pp100k_2102 | 2102 | 10000 | 7882 | 1844 | 0 | 274 | 1 | 10000 |
| pp100k_2103 | 2103 | 10000 | 7885 | 1847 | 0 | 268 | 1 | 10000 |
| pp100k_2104 | 2104 | 10000 | 7914 | 1799 | 0 | 287 | 1 | 10000 |
| pp100k_2105 | 2105 | 10000 | 7873 | 1837 | 0 | 290 | 1 | 10000 |
| pp100k_2106 | 2106 | 10000 | 7904 | 1815 | 0 | 281 | 1 | 10000 |
| pp100k_2107 | 2107 | 10000 | 7877 | 1837 | 0 | 286 | 1 | 10000 |
| pp100k_2108 | 2108 | 10000 | 7891 | 1845 | 0 | 264 | 1 | 10000 |
| pp100k_2109 | 2109 | 10000 | 7937 | 1789 | 0 | 274 | 1 | 10000 |
| pp10k_2026 | 2026 | 2000 | 1760 | 237 | 0 | 3 | 1 | 2000 |
| pp10k_2027 | 2027 | 2000 | 1765 | 226 | 0 | 9 | 1 | 2000 |
| pp10k_2028 | 2028 | 2000 | 1795 | 203 | 0 | 2 | 1 | 2000 |
| pp10k_2029 | 2029 | 2000 | 1780 | 216 | 0 | 4 | 1 | 2000 |
| pp10k_2030 | 2030 | 2000 | 1757 | 237 | 0 | 6 | 1 | 2000 |
| pp10k_smoke_2026 | 2026 | 50 | 43 | 7 | 0 | 0 | 1 | 50 |

## Top Error Patterns by run_group
- cmpfix2_smoke_20260214T1630Z: hard_cap_exceeded=14, diameter_over_100m=3
- cmpfix_smoke_20260214T1602Z: hard_cap_exceeded=12, compare_mismatch_exit0=10, diameter_over_100m=7
- legacy_5000_seed2026: hard_cap_exceeded=501, diameter_over_100m=78, ath_nonzero_exit=5
- legacy_5000_seed2026_retry2: hard_cap_exceeded=5, diameter_over_100m=1
- legacy_500_seed1337: hard_cap_exceeded=61, diameter_over_100m=14
- legacy_500_seed1337_retry2: hard_cap_exceeded=2
- legacy_500_seed1337_retry3: hard_cap_exceeded=2
- pp100k_2100: hard_cap_exceeded=905, unknown=790, diameter_over_100m=145
- pp100k_2101: hard_cap_exceeded=859, unknown=807, diameter_over_100m=166
- pp100k_2102: hard_cap_exceeded=863, unknown=814, diameter_over_100m=164
- pp100k_2103: hard_cap_exceeded=894, unknown=794, diameter_over_100m=156
- pp100k_2104: hard_cap_exceeded=841, unknown=799, diameter_over_100m=155
- pp100k_2105: hard_cap_exceeded=898, unknown=788, diameter_over_100m=148
- pp100k_2106: hard_cap_exceeded=839, unknown=809, diameter_over_100m=164
- pp100k_2107: hard_cap_exceeded=872, unknown=837, diameter_over_100m=127
- pp100k_2108: hard_cap_exceeded=874, unknown=813, diameter_over_100m=157
- pp100k_2109: hard_cap_exceeded=832, unknown=799, diameter_over_100m=157
- pp10k_2026: hard_cap_exceeded=203, diameter_over_100m=33, ath_nonzero_exit=1
- pp10k_2027: hard_cap_exceeded=184, diameter_over_100m=40, ath_nonzero_exit=1
- pp10k_2028: hard_cap_exceeded=167, diameter_over_100m=34, ath_nonzero_exit=2
- pp10k_2029: hard_cap_exceeded=180, diameter_over_100m=34, ath_nonzero_exit=1
- pp10k_2030: hard_cap_exceeded=208, diameter_over_100m=28, ath_nonzero_exit=1
- pp10k_smoke_2026: hard_cap_exceeded=6, diameter_over_100m=1
