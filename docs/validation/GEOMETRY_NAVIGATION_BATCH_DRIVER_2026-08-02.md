# Geometry navigation and Batch Driver validation — 2026-08-02

## Scope and baseline

- Branch: `codex/geometry-tab-batch-driver-2026-08-02`
- Baseline: `bb444ec0b32ef6735e19e787074cf3a320678d35`
- Product boundary: navigation, Batch selection policy, additive persistence and
  Run-start Driver resolution only; no SpeakerAssembly, DSP, CAD or solver-model
  change.
- Canonical decision: `docs/adr/008-geometry-navigation-and-batch-driver-selection.md`.

## Visible isolated GUI smoke

The GUI was launched with `WUT_BATCHER_SETTINGS_PATH` pointing at the ignored
`tmp/geometry_tab_smoke` profile. No standard-library project was opened or
modified. The persistent navigation visibly contained `Project -> Geometry ->
Batch -> Analyse`.

1. Opened the Geometry tab and set `Smoke Audio Default CD`, revision
   `DR-DEFAULT-1`, as the selected Geometry's ready default.
2. Saved B001 `Geometry default smoke` with **Use Geometry default**.
3. Saved B002 `Explicit override smoke` with **Use explicit Driver revision** and
   `Smoke Audio Override CD`, revision `DR-OVERRIDE-1`.
4. Returned to Project, selected and edited B001, then B002. Both states reloaded
   correctly and displayed readiness, complete revision SHA-256 and LE SHA-256.
5. Closed the isolated GUI normally. Its exact PID 5056 was gone; the post-smoke
   relevant-process inventory was empty.

JSON and SQLite 2.10 agreed:

| Batch | Policy | Override | Geometry |
|---|---|---|---|
| B001 | `geometry_default` | empty | `G-56a025a1-f087-405c-95d7-5c25cc7f07ca` |
| B002 | `explicit_override` | `DR-OVERRIDE-1` | `G-56a025a1-f087-405c-95d7-5c25cc7f07ca` |

Both stored Batch snapshots are empty compatibility placeholders; effective
Driver bytes are resolved only for an immutable Run snapshot.

## Single native acceptance gate

Only one native run was made. A 3.4 MB copy of the previously accepted fast B012
fixture was placed at `C:\wut_nav_gate_20260802_r1`; the source fixture and the
productive library were read-only. The command was:

```powershell
python -m app run-sample --real `
  --library-root C:\wut_nav_gate_20260802_r1\library `
  --project-id P0001__40a6f067-5940-4146-b04f-04f0246b6472 `
  --batch-id B012
```

Run `f23aad8a-bc05-4451-9c92-f775dab27903` completed from
2026-08-01T22:49:19Z to 22:50:13Z. ATH, ABEC sync, LE repair/guard, mesh guard,
AKABAK and VACS all returned `ok`; VACS prepared 24 rows from four current files
without parse, mapping or missing-contract errors. Project SQLite contained one
impedance and three polar graph rows for this Run.

The immutable row recorded:

- `selection_source = geometry_default`;
- Geometry `G-affb44e5-840f-474f-b051-5747a33becbd`;
- revision `generic25-r1`, revision SHA-256
  `a28d2fd712afc2abff0990b80b781ef13a1339e0743e6af0129bd84bfbdea161`;
- Run snapshot SHA-256
  `90eb72cb70b374d22e29afba5fe3d2d87de4fa0c44a0b9caf75350aa98672d7a`;
- source LE SHA-256
  `3f8e1bacae6f50a4b02e9609f60d508d9c6552386707272dcf74babe945557be`;
- effective staged LE SHA-256
  `053701a2158347cdf3fdd242fc053de4a225bff93607b134efc5c80a6ed3ce9a`.

The ownership ledger observed root Python PID 14284, AKABAK PID 2336 and VACS
PID 7792. The driver closed its owned AKABAK/VACS tree with no remaining PID;
the final independent process snapshot was also empty. No global process-name
kill was used.

Compact machine-readable evidence is retained in
`docs/validation/evidence/geometry_navigation_batch_driver_2026-08-02.json`;
large native artifacts remain outside Git.
