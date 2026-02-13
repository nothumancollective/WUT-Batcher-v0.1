# Compatibility Evidence Report

Generated from normalized ruleset `ath-geometry-constraints.v1.1`.

| rule_id | kind | evidence.type | confidence | refs | verification_plan |
|---|---|---:|---:|---|---|
| validity_length_required | validity | ath_doc | 0.95 | Ath 4.8.2 User Guide 4.1.1 Horn geometry (PDF p.18) p.18 | - |
| visibility_profile_osse | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_profile_osse', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_profile_not_osse | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_profile_not_osse', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_profile_circarc | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_profile_circarc', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_profile_not_circarc | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_profile_not_circarc', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_source_contours_override | visibility | ath_doc | 0.95 | Ath 4.8.2 User Guide 4.1.5 Acoustic Source definition (PDF p.22) p.22; Ath Application Note 1 (AP1) ESP integration (PDF p.3) p.3 | - |
| visibility_guidingcurve_enabled | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_guidingcurve_enabled', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_guidingcurve_disabled | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_guidingcurve_disabled', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_guidingcurve_superellipse | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_guidingcurve_superellipse', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_guidingcurve_superformula | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_guidingcurve_superformula', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| validity_guidingcurve_requires_dist_and_width | validity | hypothesis | 0.40 | - | Create a focused fixture for 'validity_guidingcurve_requires_dist_and_width', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| validity_explicit_requires_coverageangle | validity | hypothesis | 0.40 | - | Create a focused fixture for 'validity_explicit_requires_coverageangle', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_morph_off | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_morph_off', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_morph_on | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_morph_on', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_rollback_off | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_rollback_off', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_rollback_on | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_rollback_on', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_mesh_interfaceoffset_off | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_mesh_interfaceoffset_off', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| visibility_mesh_interfaceoffset_on | visibility | hypothesis | 0.40 | - | Create a focused fixture for 'visibility_mesh_interfaceoffset_on', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| sweepability_numeric_baseline | sweepability | hypothesis | 0.40 | - | Create a focused fixture for 'sweepability_numeric_baseline', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| runner_fixed_source_block | runner | hypothesis | 0.40 | - | Create a focused fixture for 'runner_fixed_source_block', execute rule evaluator and cross-check with ATH run logs to confirm behavior before promoting confidence. |
| fact:length_is_mandatory | semantics | ath_doc | 0.95 | Ath 4.8.2 User Guide 4.1.1 Horn geometry (PDF p.18) p.18 | - |
| fact:source_items_can_be_omitted | semantics | ath_doc | 0.90 | Ath-4.8.2-UserGuide-2.pdf 4.1.5 ABEC/BEM project settings p.22; Ath-4.8.2-UserGuide-2.pdf 6.1 The basics p.28 | - |
| fact:source_contours_override | semantics | ath_doc | 0.95 | Ath 4.8.2 User Guide 4.1.5 Acoustic Source definition (PDF p.22) p.22; Ath Application Note 1 (AP1) ESP integration (PDF p.3) p.3 | - |
| fact:ath_creates_subdirectory_per_script | semantics | ath_doc | 0.90 | Ath-4.8.2-UserGuide-2.pdf 4.1.6 Program output p.24; Ath-4.8.2-UserGuide-2.pdf 6.2 Running the program p.29 | - |
| fact:output_flags_stl_abecproject | semantics | ath_doc | 0.95 | Ath-4.8.2-UserGuide-2.pdf 4.1.6 Program output p.24; Ath-4.8.2-UserGuide-2.pdf 6.1 The basics p.28; Ath-4.8.2-UserGuide-2.pdf 6.3 Running BEM analysis p.31 | - |

## Summary
- doc-backed (`ath_doc`): 7
- hypotheses: 18
