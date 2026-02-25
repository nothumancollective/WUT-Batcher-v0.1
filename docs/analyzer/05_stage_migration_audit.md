# Analyzer Stage Migration Audit (Phase 0)

Date: 2026-02-24
Branch: `feature/polar-analyzer-ui`
Scope: discovery-only audit before stage migration implementation.

## Current State (Code)

### Stage list definitions
- `app/analyzer/presets.py:37` defines stage presets: `concept`, `shaping`, `stabilization`.
- `app/analyzer/presets.py:57` sets `DEFAULT_STAGE_ID = "shaping"`.
- `app/gui.py:4961` populates stage selector with `("concept", "shaping", "stabilization", "final")`.

### Stage plot mappings
- `app/gui.py:517` `STAGE_EXPLORER_LAYOUTS` currently has:
  - `concept`: `heatmap`, `e_bw`, `e_cov`, `r_spill`
  - `shaping`: `heatmap`, `e_bw`, `e_cov`, `r_spill`
  - `stabilization`: `heatmap`, `di_proxy`, `s_theta`, `e_sym_shape`
  - `final`: `heatmap`, `r_off`, `impedance_loading`, `phase_gd`
- `app/gui.py:544` `STAGE_COMPARE_OVERLAY_KEY` maps:
  - `concept -> beamwidth`, `shaping -> beamwidth`, `stabilization -> di_proxy`, `final -> r_off`
- `app/gui.py:564` `STAGE_PARETO_DEFAULTS` maps:
  - `concept -> (e_bw, r_spill)`
  - `shaping -> (e_bw, e_cov)`
  - `stabilization -> (di_proxy, s_theta)`
  - `final -> (r_off, e_cov)`

### Stage computation and artifact dependencies
- `app/analyzer/stage_plot_engine.py:357` computes stage-2-like curves for both `stabilization` and `final`: `di_proxy`, `s_theta`, `e_sym_shape`.
- `app/analyzer/stage_plot_engine.py:379` adds `r_off` only in `final`.
- `app/services.py:2651` requests artifact statuses for `POLAR`, `SPL_FR`, `IMPEDANCE`, `PHASE_GD`.
- `app/services.py:2671` special-cases `final` with fallback empty curves for missing `IMPEDANCE` / `PHASE_GD`.
- `app/gui.py:6968` and `app/gui.py:7040` still include display labels/messages for `impedance_loading` and `phase_gd`.

### Plane availability path
- `app/services.py:2250` aggregates available orientations with `GROUP_CONCAT(DISTINCT pm.orientation)`.
- `app/services.py:2281` normalizes these via `_normalize_orientation_tokens` (calls `dedupe_orientations`).
- `app/analyzer/orientation.py:39` canonical mapping:
  - `0 -> H`
  - `90 -> V`
  - `42/45 -> D`
- `app/analyzer/orientation.py:62` query aliases include canonical and `X3_*` forms.
- `app/gui.py` plane availability relies on normalized row `planes` from service payload.

## Current State (Live DB Evidence)

Dataset checked: `cleanup/runtime/postmerge_lib/P021/dataset/project.sqlite`

SQL used:

```sql
SELECT batch_id, orientation, COUNT(*)
FROM polar_measurements
GROUP BY batch_id, orientation
ORDER BY batch_id, orientation;
```

Observed output:

| batch_id | orientation | count |
|---|---|---:|
| B001 | V | 1 |
| B001 | X3_45 | 1 |
| B002 | V | 1 |
| B002 | X3_45 | 1 |
| B003 | V | 1 |
| B003 | X3_45 | 1 |
| B004 | V | 1 |
| B004 | X3_45 | 1 |
| B005 | V | 3 |
| B005 | X3_45 | 3 |
| B006 | V | 8 |
| B006 | X3_45 | 8 |
| B008 | V | 5 |
| B008 | X3_45 | 5 |

Interpretation:
- This dataset currently has no `H` / `X3_0` rows.
- H-plane absence in Analyzer for these batches is data-availability-driven, not immediately a UI-only hide issue.

Integrity check SQL:

```sql
SELECT pm.polar_id, pm.batch_id, pm.version_id, COALESCE(pm.run_id,''),
       pm.orientation, pm.freq_count, pm.angle_count,
       COUNT(pp.polar_id) AS point_count,
       (pm.freq_count * pm.angle_count) AS expected_count
FROM polar_measurements pm
LEFT JOIN polar_points pp ON pp.polar_id = pm.polar_id
GROUP BY pm.polar_id
ORDER BY pm.batch_id, pm.version_id, pm.orientation
LIMIT 50;
```

Observed:
- All sampled rows matched `point_count == expected_count`.

## Target State (Requested)

1. Stage model reduced to exactly 3 stages:
- `Concept`, `Stabilization`, `Final`.
- `Shaping` removed from selector, defaults, presets, docs.

2. Polar-only stage surfaces:
- No impedance/phase/GD stage references in defaults/mappings for Explorer/Compare.
- Final stage based on polar metrics (`r_off`, `s_theta`, `e_sym_shape`, guardrails), not non-polar artifacts.

3. H-plane handling:
- Keep canonical/alias mapping correct.
- Show H when H rows exist.
- Do not fabricate H from unrelated tokens.

## Unknowns / Risks (before implementation)

1. Some docs and UI helper text still mention `concept/shaping` and impedance/phase placeholders; these must be synchronized without breaking existing compare defaults.
2. Existing project datasets (for example P021 batches listed above) may legitimately have no H rows; post-fix validation must include at least one dataset containing real H to verify end-to-end H visibility.
3. Any existing saved analyses referencing `stage=shaping` need safe fallback handling to avoid load-time regressions.
