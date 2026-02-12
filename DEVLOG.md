# DEVLOG

## 2026-02-12
### Done
- Rebuild branch checked (`wut-batcher/rebuild` already active).
- Repository baseline analyzed:
  - Existing sweep planner, CFG renderer, compatibility engine, dataset importer inspected.
  - Current tests executed successfully (`13/13` passing).
- `ARCHITECTURE.md` created with Ist/Soll analysis and backlog.

### Next
- Introduce explicit domain-level `VersionSpec` and central resolver with `single|combined` semantics and `unset` handling.
- Add blocking compatibility validation during resolution.
- Start implementing target project storage layout and deterministic project-wide version IDs.

### Risks / Open Points
- Current snapshot references Runner automation in docs, but no `Runner/` directory exists in repo.
- Real ATH/AKABAK/VACS executable paths and invocation contracts are not yet validated in this workspace.
