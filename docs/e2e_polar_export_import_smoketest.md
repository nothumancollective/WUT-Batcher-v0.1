# E2E Polar Export -> Import Smoke Test

## 1) Test Context
- Date (UTC): `2026-02-21T14:36:20.835197+00:00`
- Branch: `feature/polar-analyzer-foundation`
- Commit: `dc72727074fa4af61b18a44c9e783b315d05d0fa`
- Mode: ingestion-only smoke using real previously exported Mic_Polar TXT files (fallback path)
- Source export run folder: `C:\Users\maximilianheinze\Desktop\WUT Batcher v0.1\cleanup\runtime\postmerge_lib\P001\versions\V006\exports\38887698-bdba-44d0-b450-7ea7400d56c3`
- Raw evidence JSON: `C:\Users\maximilianheinze\Desktop\WUT Batcher v0.1\runner_test_workspace\polar_e2e_smoke\run_20260221_143529\smoke_result.json`

## 2) Identifiers
- Project ID: `P_SMOKE`
- Batch ID: `B_SMOKE`
- Version ID: `VSMOKE`
- Run ID: `RUN_20260221_143529`
- Project DB: `C:\Users\maximilianheinze\Desktop\WUT Batcher v0.1\runner_test_workspace\polar_e2e_smoke\run_20260221_143529\lib\P_SMOKE\dataset\project.sqlite`
- Global DB: `C:\Users\maximilianheinze\Desktop\WUT Batcher v0.1\runner_test_workspace\polar_e2e_smoke\run_20260221_143529\lib\global.sqlite`

## 3) Exported Files + Header Keys
- Exactly 3 Mic_Polar files were used (H/V/D planes).

| File | Data_Format | Param_Coord_x2 present | Param_Coord_x3 |
|---|---|---|---|
| `C:\Users\maximilianheinze\Desktop\WUT Batcher v0.1\runner_test_workspace\polar_e2e_smoke\run_20260221_143529\lib\P_SMOKE\versions\VSMOKE\exports\RUN_20260221_143529\V006_anygraph_01_Mic_Polar_-_BE_Spectrum_2.txt` | `Complex` | `yes` | `42` |
| `C:\Users\maximilianheinze\Desktop\WUT Batcher v0.1\runner_test_workspace\polar_e2e_smoke\run_20260221_143529\lib\P_SMOKE\versions\VSMOKE\exports\RUN_20260221_143529\V006_anygraph_02_Mic_Polar_-_BE_Spectrum_3.txt` | `Complex` | `yes` | `0` |
| `C:\Users\maximilianheinze\Desktop\WUT Batcher v0.1\runner_test_workspace\polar_e2e_smoke\run_20260221_143529\lib\P_SMOKE\versions\VSMOKE\exports\RUN_20260221_143529\V006_anygraph_03_Mic_Polar_-_BE_Spectrum_4.txt` | `Complex` | `yes` | `90` |

## 4) DB Verification (project.sqlite)
- `polar_measurements` count for version/run: `3`
- Orientation counts: `{'D': 1, 'H': 1, 'V': 1}` (expected `{'D':1,'H':1,'V':1}`)

### Measurement Rows
- `polar_id=P1763a5c2a212fc65` `orientation=D` `orientation_raw=42.0` `freq_count=16` `angle_count=19`
- `polar_id=Pcac1c42230aa50bc` `orientation=H` `orientation_raw=0.0` `freq_count=16` `angle_count=19`
- `polar_id=Pd18a6a452c253f0b` `orientation=V` `orientation_raw=90.0` `freq_count=16` `angle_count=19`

### Point Count Equality Checks
| polar_id | orientation | expected freq_count*angle_count | actual points | ok |
|---|---|---|---|---|
| `P1763a5c2a212fc65` | `D` | `304` | `304` | `True` |
| `Pcac1c42230aa50bc` | `H` | `304` | `304` | `True` |
| `Pd18a6a452c253f0b` | `V` | `304` | `304` | `True` |

### angle_deg + angles_deg_json checks
- `angles_deg_json` is present on all 3 `polar_measurements` rows.
- `polar_points.angle_deg` NULL count is 0 for each `polar_id`.
- Orientation mapping evidence:
  - `orientation_raw=0` -> `orientation=H`
  - `orientation_raw=90` -> `orientation=V`
  - `orientation_raw=42` -> `orientation=D`
- Sample point row: `polar_id=P1763a5c2a212fc65`, `freq_hz=500.0`, `angle_deg=0.0`, `re=0.01953987`, `im=0.01255534`

## 5) global.sqlite Verification
- Consolidation executed: `yes`
- `polar_measurements` count for version/run: `3`
- `polar_points` count for version/run: `912`

## 6) Outcome
- Result: `PASS`
- Next action: run the same smoke path against a freshly live-exported run when VACS session is available, to confirm end-to-end including export runtime in one pass.
