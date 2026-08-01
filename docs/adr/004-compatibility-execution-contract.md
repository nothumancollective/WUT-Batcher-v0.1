# ADR-004: Compatibility rules and execution contract

Status: accepted, 2026-08-01

## Decision

The existing ATH -> AKABAK -> VACS computation contract is unchanged. Planning
resolves one geometry and one driver revision, creates a canonical snapshot,
and passes `geometry_id` plus that snapshot through materialization and runtime.
The runner stages the snapshot's LE bytes in the run-owned workspace and records
the staged hash. It must not reread a mutable driver entry mid-run.

Compatibility additions are deliberately narrow and machine-readable. Each
finding has `rule_id`, severity, rationale and evidence type:

- `geometry_driver_kind_compatibility`: warning when a known pairing is unusual;
  never claim acoustic invalidity without evidence.
- `driver_le_network_required`: fatal only when the current AKABAK coupling is
  selected and no effective LE network exists.
- `driver_data_incomplete`: warning listing missing optional data.
- `driver_snapshot_integrity`: fatal when revision/network hashes do not match.

Legacy service calls without geometry/driver arguments use the deterministic
legacy geometry and built-in `generic25` through explicitly marked adapters.
Adapters emit provenance in persisted snapshots; they do not create hidden UI
state or a second execution path.

