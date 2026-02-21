# Polar Analyzer Changelog

- Phase 1: added additive `polar_*` schema, polar TXT parser/import expansion, and replication integration while keeping legacy graph tables intact.
- Phase 2: added VACS export dialog enforcement (verify/set/fail-fast), setter probe tooling, and probe reports for current environment.
- Probe limitation: current probe reports may show `dialog_not_found` unless rerun in a live VACS session where `TForm_Export` is reachable.
