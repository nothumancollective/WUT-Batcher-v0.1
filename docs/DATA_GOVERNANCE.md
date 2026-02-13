# DATA GOVERNANCE

## Run Concept
- Every execution creates a new `run_id` (UUID) in `runs`.
- Lifecycle is tracked as `planned|running|succeeded|failed|aborted`.
- Metadata captured per run:
  - `git_commit`
  - `app_version`
  - `settings_hash`
  - `error_summary`

## Pinning Concept
- `runs.pinned = 1` means keep this run (baseline/final/reference).
- Optional `runs.tag` can label pinned runs.
- Unpinned runs are considered test data.

## Default Read Pattern
- Dashboard/service defaults should prefer succeeded runs only.
- For version-level views, use latest succeeded run per version:

```sql
WITH ranked AS (
  SELECT
    rv.version_id,
    rv.run_id,
    r.started_at,
    ROW_NUMBER() OVER (
      PARTITION BY rv.version_id
      ORDER BY r.started_at DESC, r.run_id DESC
    ) AS rn
  FROM run_versions rv
  JOIN runs r ON r.run_id = rv.run_id
  WHERE rv.project_id = :project_id
    AND rv.batch_id = :batch_id
    AND r.status = 'succeeded'
    AND rv.status IN ('success', 'dry_run_completed')
)
SELECT version_id, run_id, started_at
FROM ranked
WHERE rn = 1
ORDER BY version_id;
```

## Cleanup Workflow
Recommended workflow:
1. Run batch.
2. Pin good runs (`baseline`, `final`, etc.).
3. Cleanup test data (all unpinned runs).

CLI:
- Pin run: `python -m app runs pin <run_id> [--project-id P001] [--tag final]`
- Unpin run: `python -m app runs unpin <run_id> [--project-id P001]`
- Cleanup test data:
  - Preview: `python -m app runs cleanup-testdata --project-id P001 --dry-run`
  - Execute: `python -m app runs cleanup-testdata --project-id P001 --delete-exports`

## Cleanup Safety
- Pinned runs are never deleted by cleanup.
- Export deletion is allowlist-guarded to paths inside project root only.
- Dry-run does not mutate SQL or files.
- Every cleanup writes an audit log:
  - `<project>/logs/cleanup_<timestamp>.json`
