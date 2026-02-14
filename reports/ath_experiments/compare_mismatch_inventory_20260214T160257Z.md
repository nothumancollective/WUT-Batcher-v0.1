# Compare Mismatch Inventory

- Generated: 2026-02-14T16:02:57+00:00
- Selector: `cmpfix_smoke_20260214T1602Z`
- Runs processed: 10
- Rows updated (classification backfill): 0

## Subclass Counts
- cmp_unknown: 10

## Top Keys Overall (Top 30)
- Mesh.InterfaceDraw: 5
- Mesh.SubdomainSlices: 5
- Mesh.ZMapPoints: 4
- GCurve.SF: 3

## Top Keys by Subclass
- cmp_unknown: Mesh.InterfaceDraw=5, Mesh.SubdomainSlices=5, Mesh.ZMapPoints=4, GCurve.SF=3

## Example Runs (3 per class)
- cmp_unknown:
  - run_id=ath_exp_2401_0013_bd7be7728b group=cmpfix_smoke_20260214T1602Z missing_required=0 extra_ghost=0 first_mismatch=Mesh.InterfaceDraw
  - run_id=ath_exp_2401_0021_d474b1b2be group=cmpfix_smoke_20260214T1602Z missing_required=0 extra_ghost=0 first_mismatch=GCurve.SF
  - run_id=ath_exp_2401_0024_aa6ae81013 group=cmpfix_smoke_20260214T1602Z missing_required=0 extra_ghost=0 first_mismatch=Mesh.InterfaceDraw
