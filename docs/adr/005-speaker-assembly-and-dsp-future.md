# ADR-005: Future speaker assemblies and DSP simulation

Status: proposed; deliberately not implemented

## Boundary

A future `SpeakerAssembly` may reference multiple immutable Geometry instances,
their transforms and driver snapshots. Normal, coaxial and other arrangements
must be expressed as explicit coordinate transforms and source assignments,
not folded into Geometry. The assembly owns no mutable driver-library link at
execution time.

A separate `SignalChainRevision` should describe input normalization, filters,
delay, polarity, gain, crossover topology and units. A system run snapshots the
assembly and signal-chain revisions, then generates solver inputs without
changing the validated single-geometry run contract.

Required pre-implementation work: coordinate/phase conventions, multi-source
solver evidence, electrical/acoustic power normalization, latency conventions,
validation fixtures, schema migration and UI workflow. No placeholder controls
or synthetic DSP results are exposed by the current release.

