# LE/RadImp Solution Status

Date: 2026-02-16

## Implemented
- Post-ATH LE repair is enforced and idempotent:
  - copy `generic25.txt` into ABEC project folder (hash-aware)
  - patch `[LEScript] Scriptname_LEScript=generic25.txt`
  - persist `abec_before_patch`, `abec_after_patch`, `le_driver`, `le_repair_summary`
- Pre-AKABAK LE/Driving contract guard is active:
  - validates `solving.txt`/`observation.txt` presence
  - validates expected `DrvGroup` bindings
  - validates `Radiation_Impedance` section presence
- RadImp diagnosis model updated:
  - `sources_muted_dialog_seen`
  - `solve_not_completed_or_no_results`
  - `wrong_graph_exported`
  - `radimp_normalized_zero_baseline`
  - `radimp_all_zero_unclassified`
  - `radimp_nonzero`
- Strict target gate added:
  - `--strict-nonzero-radimp` fails run unless classification is `radimp_nonzero`.

## Evidence
- Stable baseline runner path is green (10/10) with UIA-only contracts.
- Strict non-zero campaign did not produce non-zero RadImp in tested scopes.
- Current strict classification distribution:
  - `radimp_normalized_zero_baseline`: 10
  - `radimp_all_zero_unclassified`: 9
  - `wrong_graph_exported`: 1
  - `radimp_nonzero`: 0

## Current Conclusion
- Runner robustness problems are resolved for baseline flow.
- Remaining blocker for target outcome is RadImp modeling/export semantics, not window-control instability.

## Primary References
- ATH User Guide (`Ath-4.8.2-UserGuide-2.pdf`), especially LE keys and LE driving notes.
- AKABAK manual (`AKABAK.pdf`), especially `Driving_Values`, `DrvGroup`, and `Radiation_Impedance` sections.
- Distribution provenance:
  - https://www.randteam.de/Download/download.html
  - https://akabak.readthedocs.io/en/latest/changelog/
