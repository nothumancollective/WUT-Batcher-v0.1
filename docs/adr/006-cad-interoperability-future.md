# ADR-006: Future CAD import, meshing and hierarchical export

Status: proposed; deliberately not implemented

## Boundary

CAD import must preserve the original document and its hash, declared units,
coordinate system and component hierarchy. Automatic horn recognition may only
produce an acoustic Geometry after the user verifies throat, mouth, axis,
interior volume, boundaries and watertightness. Remeshing is a distinct,
versioned derivation with tool version, tolerances and provenance.

STEP, Fusion and Inventor export should originate from an explicit assembly
model and retain stable component identities. Export must not imply that an ATH
surface is a production-ready solid. Native proprietary formats require a
licensed local integration; neutral STEP is the portable interchange target.

Required pre-implementation work: supported CAD dialects, unit/axis contract,
topology diagnostics, internal-volume selection UX, meshing convergence gates,
licensing review and round-trip test corpus. None is implemented here.

