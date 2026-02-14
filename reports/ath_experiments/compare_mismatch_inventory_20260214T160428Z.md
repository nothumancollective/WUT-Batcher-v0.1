# Compare Mismatch Inventory

- Generated: 2026-02-14T16:04:28+00:00
- Selector: `all`
- Runs processed: 8060
- Rows updated (classification backfill): 10

## Subclass Counts
- cmp_structure_mismatch_object: 5234
- cmp_value_mismatch_numeric: 2463
- cmp_missing_required: 363

## Top Keys Overall (Top 30)
- Morph.AllowShrinkage: 2632
- Mesh.InterfaceDraw: 2184
- Mesh.SubdomainSlices: 2184
- Mesh.ZMapPoints: 1838
- GCurve.SF: 1366

## Top Keys by Subclass
- cmp_missing_required: Mesh.InterfaceDraw=16, Mesh.SubdomainSlices=16, GCurve.SF=5
- cmp_structure_mismatch_object: Mesh.InterfaceDraw=2168, Mesh.SubdomainSlices=2168, Mesh.ZMapPoints=1838, GCurve.SF=1361, Morph.AllowShrinkage=169
- cmp_value_mismatch_numeric: Morph.AllowShrinkage=2463

## Example Runs (3 per class)
- cmp_missing_required:
  - run_id=ath_exp_2100_0070_ef81899e44 group=pp100k_2100 missing_required=9 extra_ghost=10 first_mismatch=None
  - run_id=ath_exp_2100_0188_8976ceee7c group=pp100k_2100 missing_required=9 extra_ghost=10 first_mismatch=None
  - run_id=ath_exp_2100_0258_39209094f9 group=pp100k_2100 missing_required=9 extra_ghost=10 first_mismatch=None
- cmp_structure_mismatch_object:
  - run_id=ath_exp_2100_0059_bdde3cab5a group=pp100k_2100 missing_required=0 extra_ghost=0 first_mismatch=Mesh.ZMapPoints
  - run_id=ath_exp_2100_0082_6f29cc6de8 group=pp100k_2100 missing_required=0 extra_ghost=0 first_mismatch=Mesh.InterfaceDraw
  - run_id=ath_exp_2100_0106_0342f85f57 group=pp100k_2100 missing_required=0 extra_ghost=0 first_mismatch=GCurve.SF
- cmp_value_mismatch_numeric:
  - run_id=ath_exp_2100_0030_051ffef755 group=pp100k_2100 missing_required=0 extra_ghost=0 first_mismatch=Morph.AllowShrinkage
  - run_id=ath_exp_2100_0134_6a533360f0 group=pp100k_2100 missing_required=0 extra_ghost=0 first_mismatch=Morph.AllowShrinkage
  - run_id=ath_exp_2100_0168_772d2c086e group=pp100k_2100 missing_required=0 extra_ghost=0 first_mismatch=Morph.AllowShrinkage
