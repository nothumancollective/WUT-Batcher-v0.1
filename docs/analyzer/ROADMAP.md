# Analyzer Roadmap (Planning Stage)

**Last updated:** 2026-02-21  
**Scope:** Documentation roadmap only. No UI/KPI implementation is included here.

This roadmap defines phased delivery for the Analyzer feature from navigation skeleton to future geometry-layer readiness.
It is aligned to current project state:
- Polar ingestion exists (`H/V/D` complex data in SQLite).
- Analyzer docs baseline exists.
- Analyzer UI and KPI engine are not implemented yet.

## Test and Runtime Constraints (Global)

### CI test batches (hard cap)
- CI and automated regression fixtures must use **max 5 runs per batch**.
- CI must validate structure, query correctness, cancellation, and cache behavior on small datasets.
- CI must not attempt full-batch heavy compute or long-running BEM workloads.

### Real user batches (runtime reality)
- Real-world batches may reach **~200 runs**.
- Large-batch handling must use:
  - incremental compute
  - persisted and in-memory caching
  - on-demand detail expansion
- Analyzer interactions must avoid blocking full recompute on each selection/filter change.

## Phase Plan (A-G)

## Phase A - Navigation Skeleton
Goal:
- Introduce Analyzer mode/page into the existing app shell without implementing KPI logic.

Scope:
- Bottom mode integration for `Analyse`.
- Basic page routing and empty-state scaffolding.
- Global/page-local action separation preserved.

Acceptance criteria:
- Analyzer page is reachable from app navigation.
- Existing Project/Batch flows remain unaffected.
- No KPI computations are triggered in this phase.

## Phase B - Batch Review Structure
Goal:
- Establish the first Analyzer subview focused on one batch at a time.

Scope:
- `Batch Review` subview with:
  - batch/run selection scaffolding
  - filter/sort placeholders
  - plot placeholders (no final KPI engine required)
- Data loading wired to existing polar tables.

Acceptance criteria:
- User can open a batch and list candidate runs with polar data.
- UI remains responsive during data fetches via background workers.
- No heavy full-batch recompute on row selection.

Status update (2026-02-22):
- Analyzer Batch Review IA was re-laid out for plot-first usability (compact toolbar, control tiles, segmented Explorer/Compare navigation, details dialog).
- Project-local scope is now explicit in UI; per-page project selector was removed.

## Phase C - Candidate Pool (Cross-Batch Compare)
Goal:
- Enable cross-batch shortlisting and comparison planning before heavy compute layers.

Scope:
- `Candidate Pool` subview with:
  - pin/shortlist runs across batches
  - compare selected pinned runs
  - persistent shortlist metadata design
- Cross-batch view is read/compare first (not compute-heavy).

Acceptance criteria:
- User can pin runs from different batches into one pool.
- Pinned runs are viewable and comparable in one place.
- Selecting/adding/removing candidates does not trigger heavy recompute.

Status update (2026-02-22):
- Compare workflow now uses fixed `C1..C5` shortlist slots with stable colors and compact overlay/heatmap presentation.
- Multi-candidate plotting remains worker-driven and cache-backed.

## Phase D - Incremental Compute and Cache Framework
Goal:
- Create compute/caching infrastructure required for scaling to large batches.

Scope:
- Incremental job orchestration for KPI calculations.
- Cache key/version strategy (algorithm revision aware).
- Progress/cancel flow for background compute.

Acceptance criteria:
- KPI compute can run in chunks and resume incrementally.
- Cache hits avoid unnecessary recompute for unchanged inputs.
- Cancellation is functional and leaves cache/state consistent.

## Phase E - KPI Engine MVP (Structured, Not New Math)
Goal:
- Implement MVP KPI set already defined in docs without inventing new formulations.

Scope:
- Wire KPI calculations using documented definitions from:
  - `01_kpi_foundations.md`
  - `03_kpi_scoring_model.md`
- Integrate KPI columns and basic ranking/filtering in Batch Review.

Acceptance criteria:
- MVP KPI values render in Analyzer table and update predictably.
- Ranking/filtering uses cached + incremental compute paths.
- CI remains on <=5-run fixtures; large-batch behavior validated with local/manual profiling only.

## Phase F - Performance Hardening and Reliability
Goal:
- Ensure Analyzer remains responsive for real-world (~200-run) usage.

Scope:
- Query optimization and cache sizing.
- UI responsiveness tuning (table/plot interaction paths).
- Load-shedding policy for expensive operations.

Acceptance criteria:
- Analyzer remains interactive under large-batch data with incremental compute enabled.
- Expensive operations are explicitly on-demand.
- No requirement for heavy CI full-batch tests.

## Phase G - Geometry Layer Readiness
Goal:
- Prepare Analyzer to operate with future geometry selection model.

Scope:
- Documentation and interface contracts for geometry context propagation.
- Compatibility planning with future `Merge` mode and geometry-aware navigation.

Acceptance criteria:
- Analyzer docs and interfaces are geometry-context ready.
- No breaking changes required for existing Batch/Analyzer behavior when geometry layer starts.
- Geometry-layer implementation remains separately scoped.

## Process Discipline for This Roadmap
- Any Analyzer scope change must update `docs/analyzer/CHANGELOG.md`.
- Any UI scope change must update `docs/analyzer/02_ui_architecture.md`.
- Any KPI/compute scope change must update relevant structured docs (`01_kpi_foundations.md`, `03_kpi_scoring_model.md`, and this roadmap as needed).
