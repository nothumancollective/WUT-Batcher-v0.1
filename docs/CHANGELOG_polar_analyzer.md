# Polar Analyzer Changelog

- Phase 1: added additive `polar_*` schema, polar TXT parser/import expansion, and replication integration while keeping legacy graph tables intact.
- Phase 2: added VACS export dialog enforcement (verify/set/fail-fast), setter probe tooling, and probe reports for current environment.
- Probe limitation: current probe reports may show `dialog_not_found` unless rerun in a live VACS session where `TForm_Export` is reachable.
- 2026-02-23: added `docs/polar_export_h_plane_debug.md` with B006 pipeline evidence showing H-plane loss originates from persisted H inclination=90 and propagates through cfg/export/ingest.
- 2026-02-23: batch export UI defaults now use per-plane inclinations H=0, V=90, D=45 in advanced polar cards and default polar specs; payload round-trip tests added in `tests/test_batch_export_panel.py`.
- 2026-02-23: runtime and harness default polar specs now use explicit inclinations H=0, V=90, D=45; external any-graph export filenames now append orientation token (`_H/_V/_D` or `X3_*`) from TXT metadata for stable plane identity.
- 2026-02-23: orientation normalization now treats both `Param_Coord_x3=42` and `45` as diagonal (`D`) for backward compatibility while moving defaults to 45.
- 2026-02-23: added cfg-generation regression coverage for three polar specs (H/V/D inclinations) and documented analyzer-facing export recommendations in `docs/polar_db_schema.md`.
- 2026-02-23: runtime export-spec resolution now applies a narrow legacy normalization for `adv_polar_1..3` batches (`Polars H/V/D` with old 90/90/42 pattern) to emit H=0 and D=45 without requiring Runner/export-script changes.
