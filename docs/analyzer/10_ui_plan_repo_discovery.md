# Analyzer UI Plan (Repo Discovery Baseline)
> Produced as a repo-grounded planning artifact before Analyzer UI implementation (UI-0 discovery-only).

# Analyzer UI Plan (Phase UI-0: Discovery + Structure)

## Scope
- This document is discovery and UI architecture only.
- No Analyzer UI code is implemented in this phase.
- KPI and workflow requirements are grounded in `C:\Users\maximilianheinze\Desktop\Batch Analyser KPI Research.md` (sections `Analyzer-UI und Datenpipeline`, `Minimaler KPI-Satz fuer MVP`, `Phase 2`, `Entwicklungsworkflow`).

## Branch Setup
- Base branch verified: `wut-batcher/rebuild`.
- New branch created and pushed: `feature/polar-analyzer-ui`.

## 1) Repo Discovery Inventory

### 1.1 UI Shell, Entry Points, Navigation
- Python module entry delegates to CLI:
  - `app/__main__.py:3`
  - `app/cli.py:357` (`cmd_gui`)
- GUI launch path:
  - `app/cli.py:358` imports `launch_gui`
  - `app/gui.py:3734` (`launch_gui`)
- Main shell is `QMainWindow` + `QStackedWidget`:
  - `app/gui.py:2590` (`class MainWindow`)
  - `app/gui.py:2636` (`self.stack = QStackedWidget()`)
  - `app/gui.py:2642`..`app/gui.py:2645` existing pages added to stack
- Existing stack pages:
  - `DashboardPage` (`app/gui.py:1113`)
  - `ProjectPage` (`app/gui.py:1502`)
  - `BatchPage` (`app/gui.py:1873`)
  - `RunPage` (`app/gui.py:2320`)
- Navigation is signal-driven page switching in `MainWindow`:
  - `show_dashboard` (`app/gui.py:3125`)
  - `show_project` (`app/gui.py:3130`)
  - `show_batch` (`app/gui.py:3136`)
  - `show_run` (`app/gui.py:3142`)
- Separate project chooser window exists:
  - `ProjectManagerWindow` (`app/gui.py:2418`)
  - `GuiController` orchestrates ProjectManager <-> MainWindow (`app/gui.py:3620`)

### 1.2 Existing Dashboard Placement Options for Analyzer Entry
- Current Dashboard action areas:
  - Batch actions (`New/Edit/Clone`) in `DashboardPage` (`app/gui.py:1154`..`app/gui.py:1162`)
  - Export/runs/cleanup button row (`app/gui.py:1178`..`app/gui.py:1186`)
  - Settings footer button (`app/gui.py:1192`)
- Current "run management" dialog entry is from Dashboard:
  - signal wiring in `MainWindow._connect_page_signals` (`app/gui.py:2683`..`app/gui.py:2685`)

### 1.3 Data Access Paths (`project.sqlite` + `global.sqlite`)
- Project filesystem resolution:
  - `resolve_project_paths` (`app/project_storage.py:72`)
  - `ProjectRepository` (`app/project_storage.py:136`)
- SQL dataset writer/store:
  - `SqlDatasetStore` (`app/sql_dataset_store.py`)
  - DB paths initialized in ctor:
    - `project.sqlite` (`app/sql_dataset_store.py:117`)
    - `global.sqlite` (`app/sql_dataset_store.py:118`)
  - Both DBs initialized on writer startup (`app/sql_dataset_store.py:125`..`app/sql_dataset_store.py:126`)
- Service layer access:
  - `OrchestratorService` (`app/services.py:1273`)
  - reads currently project-centric (`app/services.py:1675`, `app/services.py:1746`)
  - global replay/sync exists (`app/services.py:1778`)
- Legacy alias:
  - `TidyDatasetWriter` is `SqlDatasetStore` alias (`app/tidy_dataset.py:8`)

### 1.4 Query + Transaction Patterns
- Connection helper with commit/rollback boundary:
  - `_open_conn` (`app/sql_dataset_store.py:136`)
- Write replication pattern:
  - `_dual_write` project-first then global (`app/sql_dataset_store.py:898`)
  - global write failures queued in `replication_queue`
- Existing run/version list reads:
  - `list_runs` in store (`app/sql_dataset_store.py:2228`)
  - `latest_successful_run_per_version` (`app/sql_dataset_store.py:2314`)
  - service fallback direct sqlite read for versions (`app/services.py:1713`)

### 1.5 Existing Worker Thread Infrastructure
- GUI background workers use `QThread` + `QObject` workers:
  - `_BatchPreviewWorker` (`app/gui.py:102`)
  - `_BatchRunWorker` (`app/gui.py:169`)
  - worker startup with `thread.started.connect(worker.run)`:
    - run worker (`app/gui.py:2793`..`app/gui.py:2795`)
    - preview worker (`app/gui.py:2862`..`app/gui.py:2864`)
- No `QRunnable`/`QThreadPool` patterns in current app code.

### 1.6 Plotting and Table Model Reality
- Existing visualization stack:
  - Custom STL viewer with Qt3D and software fallback (`ui/stl_preview_widget.py:1`, `ui/stl_preview_widget.py:20`)
  - Batch preview host (`ui/batch_preview_placeholder.py:24`)
- No existing polar/line plotting library in runtime requirements (`requirements.txt` only includes PySide6 + UI automation deps).
- Table model patterns:
  - Production UI mainly uses `QListWidget` and `QTableWidget`.
  - `QTableWidget` usage in form tooling (`ui/form_builder.py:1318`)
  - `QStandardItemModel` appears only in theme preview utility (`ui/theme_preview.py:10`, `ui/theme_preview.py:89`).

### 1.7 Export Enforcement Constraint (Relevant for Analyzer Data Trust)
- VACS export dialog controls are currently configured as non-settable (`settable=False`) and enforced verify-only + fail-fast:
  - control specs (`app/vacs_export_enforcer.py:102`, `app/vacs_export_enforcer.py:106`..`app/vacs_export_enforcer.py:162`)
  - fail-fast branch when mismatch and not settable (`app/vacs_export_enforcer.py:583`..`app/vacs_export_enforcer.py:584`)
  - behavior doc (`docs/vacs_export_enforcement.md`)

## 2) DB and Query Reality for Analyzer MVP

### 2.1 Confirmed Polar Schema in Repo
- Polar tables are present in schema init and migration:
  - `polar_measurements` DDL (`app/sql_dataset_store.py:294`, `app/sql_dataset_store.py:723`)
  - `polar_points` DDL (`app/sql_dataset_store.py:321`, `app/sql_dataset_store.py:753`)
- Relevant indices:
  - measurement: `idx_polar_meas_version`, `idx_polar_meas_run`, `idx_polar_meas_batch`, `idx_polar_meas_orientation`, `uq_polar_meas_identity` (`app/sql_dataset_store.py:403`..`app/sql_dataset_store.py:408`)
  - points: `idx_polar_points_polar_freq`, `idx_polar_points_polar_angle_freq`, `idx_polar_points_polar_angle` (`app/sql_dataset_store.py:409`..`app/sql_dataset_store.py:411`)
- Runtime ingestion writes both legacy and polar tables:
  - `_ingest_vacs_exports` + `write_polar_measurement` path (`app/runtime_orchestrator.py:1261`..`app/runtime_orchestrator.py:1512`)

### 2.2 Sample DB Grounding (Local Repo Artifacts)
- Sample DB with polar data:
  - `runner_test_workspace/polar_e2e_smoke/run_20260221_143529/lib/P_SMOKE/dataset/project.sqlite`
  - observed: `polar_measurements=3`, `polar_points=912`, orientations `H/V/D`, `freq_count=16`, `angle_count=19`.
- Additional sample with polar data:
  - `cleanup/runtime/postmerge_lib/P001/dataset/project.sqlite`
  - observed same shape: 3 measurements, 912 points for one run/version.
- Older runtime DBs in repo may not have polar tables yet (e.g. `runner_test_workspace/real_runtime_e2e9/...`), so Analyzer must handle "no polar schema/data" gracefully.

### 2.3 MVP Query Set (Minimum Required)

#### Q0: Polar schema presence guard
```sql
SELECT name
FROM sqlite_master
WHERE type='table' AND name IN ('polar_measurements', 'polar_points');
```
- Purpose: fast fail with clear UI empty-state if project DB is pre-polar schema.

#### Q1: Batch list with polar availability (project-scoped)
```sql
SELECT
  pm.project_id,
  pm.batch_id,
  COUNT(*) AS measurement_count,
  COUNT(DISTINCT COALESCE(pm.run_id, '')) AS run_count,
  COUNT(DISTINCT pm.version_id) AS version_count,
  MAX(pm.created_at) AS last_imported_at
FROM polar_measurements pm
WHERE pm.project_id = ?
GROUP BY pm.project_id, pm.batch_id
ORDER BY pm.batch_id;
```
- Expected rows: one row per batch with polar data (typically low tens).
- Uses `idx_polar_meas_batch`.

#### Q2: Run/version row list for selected batch (table backbone)
```sql
SELECT
  pm.project_id,
  pm.batch_id,
  pm.version_id,
  COALESCE(pm.run_id, '') AS run_id,
  COUNT(*) AS plane_count,
  GROUP_CONCAT(pm.orientation, ',') AS planes_csv,
  MIN(pm.freq_count) AS freq_count_min,
  MAX(pm.freq_count) AS freq_count_max,
  MIN(pm.angle_count) AS angle_count_min,
  MAX(pm.angle_count) AS angle_count_max,
  AVG(pm.norm_angle_deg) AS norm_angle_deg_avg,
  MAX(pm.created_at) AS imported_at,
  r.started_at,
  r.finished_at,
  r.status AS run_status,
  r.pinned,
  r.tag,
  rv.status AS run_version_status,
  rv.duration_seconds
FROM polar_measurements pm
LEFT JOIN runs r
  ON r.run_id = pm.run_id
LEFT JOIN run_versions rv
  ON rv.run_id = pm.run_id
 AND rv.version_id = pm.version_id
WHERE pm.project_id = ?
  AND pm.batch_id = ?
GROUP BY pm.project_id, pm.batch_id, pm.version_id, COALESCE(pm.run_id, '')
ORDER BY imported_at DESC;
```
- Expected rows: one row per run+version with polar data.
- 200-run batch planning baseline:
  - if 1 version per run: ~200 rows
  - if multi-version runs: up to run_count * versions_per_run.

#### Q3: Plane metadata for selected run+version row
```sql
SELECT
  pm.polar_id,
  pm.orientation,
  pm.orientation_raw,
  pm.norm_angle_deg,
  pm.freq_count,
  pm.angle_count,
  pm.freq_min_hz,
  pm.freq_max_hz,
  pm.angle_min_deg,
  pm.angle_max_deg,
  pm.angle_step_deg,
  pm.angles_deg_json,
  pm.created_at
FROM polar_measurements pm
WHERE pm.project_id = ?
  AND pm.batch_id = ?
  AND pm.version_id = ?
  AND COALESCE(pm.run_id, '') = ?
ORDER BY pm.orientation;
```
- Expected rows: normally 3 (`H`, `V`, `D`), but must support missing planes.

#### Q4: Full matrix fetch for selected plane (for heatmap + KPI compute)
```sql
SELECT
  freq_index,
  angle_index,
  freq_hz,
  angle_deg,
  re,
  im
FROM polar_points
WHERE polar_id = ?
ORDER BY freq_index, angle_index;
```
- Expected rows per plane: `freq_count * angle_count`.
- Observed sample: `16 * 19 = 304`.
- Planning baseline for 200 runs, 3 planes, 16x19:
  - `200 * 3 * 304 = 182400` point rows.

#### Q5: Fast slice query for overlays/diagnostics (avoid full matrix reload)
```sql
SELECT freq_hz, re, im
FROM polar_points
WHERE polar_id = ?
  AND angle_index = ?
ORDER BY freq_hz;
```
- Uses `idx_polar_points_polar_angle_freq`.
- Expected rows: `freq_count`.

#### Q6: Fast frequency slice (diagnose selected band/feature)
```sql
SELECT angle_index, angle_deg, re, im
FROM polar_points
WHERE polar_id = ?
  AND freq_index = ?
ORDER BY angle_index;
```
- Uses PK prefix on `(polar_id, freq_index, angle_index)`.
- Expected rows: `angle_count`.

### 2.4 Query Performance Notes
- Verified index-backed plans on sample DB:
  - batch list query uses `idx_polar_meas_batch`.
  - angle slice uses `idx_polar_points_polar_angle_freq`.
  - full matrix uses PK index on `polar_points`.
- Grouped run list (`Q2`) uses temp b-tree for `GROUP BY/ORDER BY imported_at`; acceptable for MVP but can be optimized later with precomputed run-level summary table.

### 2.5 project.sqlite vs global.sqlite in UI
- Current application read path is project-first (service methods load per project DB).
- Recommendation:
  - default Analyzer datasource: `project.sqlite`.
  - optional toggle: `global compare` for cross-project benchmarking.
- Global compare must surface caveat:
  - `global.sqlite` can lag if replication queue has pending items in project DB.

## 3) Analyzer Information Architecture

## 3.1 Navigation Placement (Proposed, Repo-Aligned)
- Add a new `AnalyzerPage` into existing `MainWindow.stack` (same pattern as existing four pages).
- Add Dashboard entry button `Open Analyzer` in the existing export/actions area (near run management), because Dashboard is current operational hub.
- Add `Back to Dashboard` action inside Analyzer page to match current page pattern.

## 3.2 MVP Page Layout (Wireframe in Words)

Single Analyzer page, split in 3 functional zones:

1. Top Control Bar
- Batch selector.
- Datasource toggle: `Project` (default) / `Global Compare`.
- Stage mode switch:
  - `Stage 1: Concept/Shaping`
  - `Stage 2: Stabilization`
  - `Stage 3: Resonance/Final`
- Normalization mode selector for plots:
  - `On-axis`
  - `Max in +-X deg`
  - `Power-normalized`
- Frequency band preset + custom range.
- `Refresh KPIs`, `Cancel`, progress indicator.

2. Left Pane: Candidate Table + Filters
- Filter chips/fields for KPI thresholds and flags.
- Sortable run/version table (single + multi-select).
- MVP visible columns (max 5 KPI columns):
  - `B_PC`
  - `E_BW`
  - `Jump/Collapse`
  - `E_cov`
  - `R_spill` (with optional switch to `Q_beam`)
- Metadata columns (non-KPI): `run_id`, `version_id`, `planes`, `status`, `imported_at`, `pinned/tag`.

3. Right Pane: Diagnostics + Compare
- Upper panel: Polar Heatmap/Contour with plane tabs `H | V | D`.
- Middle panel: Beamwidth vs frequency (overlay H/V/D + target + tolerance band).
- Lower panel: KPI detail + compare controls.
  - KPI click-through diagnostics.
  - Selected-run overlay controls.
  - shortlist/iteration actions.

## 3.3 Panel -> Data Requirements

### Control Bar
- Needs: list of batches with polar data (`Q1`), stage state, datasource state, normalization mode.

### Candidate Table
- Needs: run/version rows (`Q2`) + KPI scalar cache (or computed values).
- Needs fast client-side sort/filter once rows are loaded.

### Heatmap Panel
- Needs: selected row plane metadata (`Q3`) and selected plane matrix (`Q4`).
- Needs downsampled render matrix cache for responsive redraw.

### Beamwidth Panel
- Needs: per-plane beamwidth curves computed from selected plane data.
- Needs target beamwidth profile + tolerance config.

### KPI Detail / Compare Panel
- Needs: selected KPI values + optional curve snippets.
- Needs multi-selected run IDs and preloaded curves for overlay.
- Needs shortlist state (can map to existing run pin/tag for MVP).

## 3.4 KPI Presentation Mapping (MVP vs Phase 2)

### MVP KPI Columns (exact set requested)
1. `B_PC` (pattern-control bandwidth)
2. `E_BW` (beamwidth target error)
3. `Jump/Collapse` flags
4. `E_cov` (coverage uniformity)
5. `R_spill` or `Q_beam`

### Stage Emphasis (MVP behavior)
- Stage 1 (`Concept/Shaping`):
  - emphasize/sort by `B_PC`, then `E_BW`, then flags.
  - de-emphasize phase-derived diagnostics.
- Stage 2 (`Stabilization`):
  - emphasize `E_cov`, `R_spill`/`Q_beam`, and flags.
  - keep `E_BW` visible for guardrail.
- Stage 3 (`Resonance/Final`):
  - keep MVP KPIs visible, but expose Phase 2 slots in side panel/table chooser.

### Phase 2 KPI Slots (planned, not MVP-computed by default)
- `S_theta`
- `R_off`
- `S_DI`
- `E_sym_shape`
- optional `S_GD`

## 3.5 Critical User Workflows

### A) Find Candidates
1. Select batch.
2. Choose stage mode.
3. Apply filter thresholds (KPI + flags).
4. Sort table by stage-default ranking.
5. Shortlist via pin/tag (reuse `runs.pinned` + `runs.tag`) or local shortlist list.

### B) Compare Runs
1. Multi-select rows in candidate table.
2. Choose plane (`H/V/D`) and plot mode.
3. Overlay beamwidth curves and selected diagnostic slices.
4. Limit active overlays (recommended <= 5) to keep redraw smooth.

### C) Diagnose
1. Click KPI cell/flag in row.
2. UI jumps/focuses relevant panel:
  - Beamwidth issue -> beamwidth chart at offending band.
  - Jump/Collapse flag -> highlight freq region.
  - Spill issue -> heatmap with outside-coverage emphasis.

### D) Iterate
1. Mark best runs (pin/tag or shortlist).
2. Export shortlist report (CSV/JSON): run/version IDs, stage, KPI snapshot, notes.
3. Feed shortlist IDs back into next batch design iteration.

## 4) UI Performance + Responsiveness Plan

### 4.1 Compute Placement (On-demand vs Cached)
- No existing `run_metrics` table exists in repo for analyzer KPIs.
- MVP compute strategy:
  - on-demand compute for selected rows (first use).
  - in-memory cache for scalar KPIs and frequently opened matrices.
- Additive persisted cache plan (Phase 2 recommended):
  - new table (proposal): `analyzer_kpi_cache`
  - key: `(project_id, batch_id, version_id, run_id, stage_mode, algorithm_rev, datasource)`
  - payload: scalar KPIs + optional compact curve summaries + compute timestamp.
  - algorithm revision field enables deterministic invalidation.

### 4.2 Threading Strategy
- Reuse current app pattern (`QObject` worker in `QThread`) for Analyzer:
  - `AnalyzerListWorker` for `Q1/Q2` + batch KPI prefetch.
  - `AnalyzerPlaneWorker` for `Q3/Q4` fetch + matrix preparation.
  - `AnalyzerKpiWorker` for KPI batch compute jobs.
- Cancellation model:
  - request-id guard (same pattern as preview worker).
  - cancel button sets current worker canceled flag.
- Progress model:
  - list load: indeterminate progress.
  - KPI batch compute: determinate by completed rows / total rows.

### 4.3 Caching Strategy (UI Layer)
- Matrix cache (bounded LRU):
  - key: `(datasource, project_id, batch_id, version_id, run_id, orientation, normalization_mode)`
  - value: axis arrays + magnitude matrix (`float32`).
  - suggested bound: 6-10 matrices.
- Downsample cache:
  - key extends matrix key with render bucket (e.g. target pixels or max bins).
  - value: downsampled grid for heatmap redraw.
- KPI scalar cache:
  - key per run/version/stage mode.
  - value: MVP scalar columns + flags + timestamps.

### 4.4 Memory/Throughput Controls
- Lazy load:
  - never preload all `polar_points` for whole batch.
  - load full matrix only for selected run/plane.
- Chunk strategy for large matrices:
  - if matrix rows exceed threshold, stream by `freq_index` chunks.
- Resampling/downsampling policy:
  - preserve native data for KPI compute.
  - downsample only for rendering.
  - apply consistent internal log-frequency grid for batch comparisons.

### 4.5 Cheap vs Expensive Operations

Cheap:
- `Q1/Q2/Q3` metadata queries.
- table sorting/filtering on cached scalars.
- single angle or frequency slice query (`Q5/Q6`).

Medium:
- first-time per-plane matrix load + magnitude transform.
- MVP scalar KPI compute (`B_PC`, `E_BW`, flags, `E_cov`, `R_spill/Q_beam`) per row.

Expensive:
- batch-wide KPI recompute over all rows.
- multi-run overlay with many selections.
- Phase 2 metrics (`S_theta`, `R_off`, `S_DI`, `S_GD`) especially with phase processing.
- global compare over many projects.

## 5) Open Questions and Risks
- Charting implementation choice is open: repo has no existing polar/line plotting library; need decision for UI-1 (custom Qt paint/QtCharts/new dependency).
- Existing production UI does not yet use `QAbstractTableModel` sorting/filtering patterns; introducing one is likely required for Analyzer table scale.
- Some historical project DBs in repo have no `polar_*` tables; Analyzer must show a migration/no-data state instead of hard failure.
- Global compare can show stale data if project `replication_queue` has pending writes.
- `Q2` grouped query can require temp b-tree; if batch sizes grow, a run-level summary/cache table should be prioritized.
- Final shortlist export format (CSV only vs CSV+JSON) should be fixed before UI-1.
- Exact target beamwidth profile source (fixed defaults vs per-project config) is not yet defined in current repo data model.

## 6) Implementation-Ready Summary for UI-1
- Add one new stack page (`Analyzer`) integrated into existing `MainWindow` navigation.
- Start with one-page MVP layout (control bar + candidate table + diagnostics pane).
- Implement the 6 SQL reads above as additive read-side DAO/service methods (no write-path changes).
- Implement stage mode behavior as column emphasis/sort/filter presets first, then advanced KPI expansion in Phase 2.
- Keep datasource default to `project.sqlite`, with optional `global compare` toggle.
