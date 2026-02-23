# Polar Analyzer Changelog

- Phase 1: added additive `polar_*` schema, polar TXT parser/import expansion, and replication integration while keeping legacy graph tables intact.
- Phase 2: added VACS export dialog enforcement (verify/set/fail-fast), setter probe tooling, and probe reports for current environment.
- Probe limitation: current probe reports may show `dialog_not_found` unless rerun in a live VACS session where `TForm_Export` is reachable.
- 2026-02-23: added `docs/polar_export_h_plane_debug.md` with B006 pipeline evidence showing H-plane loss originates from persisted H inclination=90 and propagates through cfg/export/ingest.
