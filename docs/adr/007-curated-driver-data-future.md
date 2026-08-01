# ADR-007: Future curated driver data sources

Status: proposed; deliberately not implemented

## Boundary

Future source connectors may only ingest explicitly permitted, traceable data.
Every imported revision must record the source URL/document, retrieval time,
file hash, licence/use note, original units, transformation log and trust state.
Manufacturer data, measured data and user assertions remain distinguishable.

Connectors must not scrape or download by default. They require a reviewed
source allowlist, licence policy, schema mapping, validation report, conflict
handling and a reproducible cache policy. Missing values remain null; derived
values must state formula, assumptions and uncertainty. In particular, no
generic T/S-to-AKABAK-LE conversion is authorized by this ADR.

The current JSON import/export contract is the manual, provenance-preserving
boundary until those requirements are satisfied.
