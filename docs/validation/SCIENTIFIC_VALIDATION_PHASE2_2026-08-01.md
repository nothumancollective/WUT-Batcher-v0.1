# Scientific Validation Phase 2 — frozen acceptance matrix

Date: 2026-08-01  
Branch: `codex/scientific-validation-phase2-2026-08-01`  
Baseline: `ac28b3e7c573a8c1ed314f3e3638bfde23586cf3`  
Status at creation: criteria frozen before the phase-2 result runs

## Scope and evidence vocabulary

This phase addresses only mesh-result convergence, mouth/profile propagation,
observation distance, the complete KPI data chain, and independent reference
checks. It does not add driver libraries, loudspeaker assemblies, CAD import, or
new product functionality.

Every conclusion uses one of these labels:

- **verified**: a reproducible test meets the predeclared numerical criterion;
- **plausibilized**: evidence agrees with the hypothesis but is not an independent
  numerical verification of the complete contract;
- **not validated**: required evidence is absent, ambiguous, or outside the test's
  applicability domain.

Criteria below may only be changed by a dated amendment that records the original
criterion, the reason, and whether any result was already visible. A failed
criterion is not relaxed merely to turn the result green.

## Frozen baseline

| Component | Exact baseline |
|---|---|
| WUT | `ac28b3e7c573a8c1ed314f3e3638bfde23586cf3` |
| ATH | `C:\Tools\ATH\ath.exe`; SHA-256 `639cb0184cf5dae233f3d2624cf279057a217da26948bde6d1d6510314b9a1e1` |
| Gmsh | `C:\Tools\ATH\gmsh.exe`; SHA-256 `0aeea78040f6c367e7718f05bb2ace05aa7f45912f9aee77353191c428e47d96` |
| AKABAK | 3.2.4.126; SHA-256 `f5c7621684d368ed5e9405c7ac958a8cb0b79522327a84425fd43d053e6e7e26` |
| VacsViewer | 2.1.3.33; SHA-256 `a3631c245d99e3e417bf9ccde5209d59b13fd81d97168e611ce4fbb360fa8623` |
| ATH template | `runner_test_cases/templates/smoke_fast_min.cfg`; repository blob at the baseline commit |

All generated files go below a run-specific `tmp/scientific_validation_phase2/<run-id>/`
directory. Product libraries and existing projects are read-only. Native process
cleanup is restricted to the recorded PID tree created or adopted by that run.

## Common reference case

Unless a row below overrides it, use a free-standing, quarter-symmetry ATH horn
with `Length=60 mm`, circular `Throat.Diameter=25.4 mm`,
`Throat.Profile=1`, `Coverage.Angle=45 deg`, `Term.s=0.5`, `Term.n=4`,
`Term.q=0.996`, `OS.k=1`, and `Morph.TargetShape=0`. Use four logarithmically
spaced solver points from 800 through 1600 Hz and `MeshFrequency=1600 Hz`.
Export unnormalized complex H/V/D polar pressure on 0…90 degrees (19 bins),
plus the available electrical/acoustical impedance graph. Retain raw TXT, rendered
CFG, ATH stdout/stderr, `.msh`, ABEC/LE/observation scripts, solver logs, hashes,
runtime, PID ledger, database copy, and compact numerical summaries.

Coordinates and units are interpreted as declared by the generated contracts:
ATH geometry and ABEC mesh coordinates in millimetres unless the generated script
explicitly converts them; observation distance in metres; angles in degrees;
frequency in hertz; complex pressure in pascals; SPL magnitude as
`20 log10(|p| / 20 µPa)` only where the raw quantity is absolute pressure.
The Analyzer's current stored polar transform is separately tested as
`20 log10(hypot(re, im))`, followed by angular reference subtraction.

## Predeclared matrix

### M1 — real mesh-result convergence

Only these four mesh inputs may vary:

| Level | AngularSegments | LengthSegments | MouthResolution (mm) | ThroatResolution (mm) |
|---|---:|---:|---:|---:|
| coarse | 24 | 12 | 24 | 14 |
| medium | 48 | 20 | 18 | 10 |
| fine | 72 | 28 | 12 | 8 |

The ATH guide defines Angular/Length values as counts and mouth/throat resolution
as nominal element size, so the levels are monotonically refined in all four
controls. Before accepting solver results, triangle and node counts must increase
strictly coarse → medium → fine, physical groups must remain identical, and all
non-mesh rendered inputs and generated LE/observation definitions must be equal.

Compare on the exact common frequency/angle intersection, with fine as reference:

| Quantity | Pass criterion |
|---|---|
| normalized H/V/D polar shape | medium–fine pooled RMS ≤ 0.75 dB and P95 absolute error ≤ 1.50 dB |
| axial absolute SPL | medium–fine RMS ≤ 0.75 dB and max absolute error ≤ 1.50 dB |
| -6 dB beamwidth | medium–fine mean absolute error ≤ 3.0 deg and max ≤ 6.0 deg; saturated widths excluded and reported |
| WUT `di_proxy` | medium–fine RMS ≤ 0.75 dB; explicitly not claimed as physical DI |
| convergence trend | pooled polar RMS(medium,fine) ≤ pooled polar RMS(coarse,medium), allowing `1e-9 dB` numerical slack |
| impedance | finite complex values on the same grid; medium–fine magnitude RMS ≤ 2.0% and max ≤ 5.0% relative to `max(|Z_fine|, 1e-9)` |
| completion/runtime | all three finish within the configured 40-minute hard limit; elapsed and CPU/resource snapshots reported, but no speed threshold |

If the selected AKABAK/VACS graph does not expose non-zero impedance for this
source definition, impedance convergence is **not validated** and M1 cannot be
reported as complete verification even if the pressure submatrix passes.

### G1 — mouth propagation

Run baseline `Coverage.Angle=45 deg` and variant `60 deg`, changing no other
source CFG value. Pass requires:

1. the rendered CFG contains the requested values exactly and ATH exits 0;
2. throat equivalent area differs by ≤ 0.1%, axial length by ≤ 0.02 mm, and
   physical-group names/counts are identical;
3. mouth equivalent diameter and area both increase, with area increase ≥ 15%;
4. ATH-reported mouth dimensions and the mesh mouth envelope agree within
   0.05 mm per reported dimension;
5. LE and observation scripts are byte-identical; solver scripts differ only in
   the expected geometry/mesh file content or hashes.

### G2 — profile propagation

Run baseline `Term.n=4` and variant `Term.n=6`, changing no other source CFG
value. Pass requires exact rendered values, ATH exit 0, equal physical groups,
throat equivalent area within 0.1%, axial length within 0.02 mm, and throat/mouth
endpoint envelopes within 0.05 mm. The interior radial envelope must nevertheless
change: maximum paired-slice difference ≥ 0.50 mm and at least 20% of comparable
interior slices differ by ≥ 0.10 mm. LE and observation scripts must be
byte-identical. This proves propagation and locality; it does not assert that one
profile is acoustically superior.

### O1 — observation distance and inverse-distance applicability

Solve one unchanged free-standing mesh and observe it at 3.0 m and 6.0 m with no
angular normalization. Origin, axis vector, H/V/D plane vectors, distance, SPL
reference, and excitation normalization must be extracted from generated scripts
and recorded—not inferred from the UI alone.

For each frequency, compute a conservative Fraunhofer eligibility check from the
maximum source aperture `D`, wavelength `lambda=c/f`, and
`r_F=2 D^2/lambda`. Apply the inverse-distance acceptance only when 3 m ≥ `r_F`
and the radiation pattern has no radial-shape warning. Eligible on-axis pressure
must change by `-6.020599913 dB ± 0.50 dB` from 3 m to 6 m. Normalized H/V/D
shape must remain invariant with pooled RMS ≤ 0.25 dB and P95 ≤ 0.50 dB.
Ineligible frequencies are reported, not judged against 6.0206 dB.

### K1 — complete KPI golden chain

Create a small repository-authored VACS-compatible complex TXT fixture with two
frequencies and distinct H, V, and D matrices; create a separate impedance fixture
that cannot enter pressure-polar queries. Expected values are calculated in a
standalone test helper from the literal complex samples, not copied from production
function output.

| Boundary | Pass criterion |
|---|---|
| TXT → parser | frequencies, angles, orientation, real and imaginary values equal parsed decimal values exactly as binary floats |
| parser → SQLite | row counts/keys exact; numeric values absolute error ≤ `1e-12`; H/V/D never cross-assigned |
| complex → magnitude | independent `20 log10(hypot(re,im))` error ≤ `1e-10 dB` |
| angular normalization | nearest requested reference bin subtraction error ≤ `1e-10 dB`; raw matrix unchanged |
| -6 dB beamwidth | independent linear-crossing result error ≤ `1e-9 deg`; limited/saturated flag exact |
| aggregate KPIs | `e_bw`, `b_pc_oct`, `e_cov`, `r_spill`, implemented `di_proxy`, smoothness/ripple, flags, and stage score error ≤ `1e-9` before the documented two-decimal score rounding |
| GUI value | exact selected run/plane and correct label/unit; displayed scalar differs by no more than half of its last shown decimal unit |
| impedance separation | impedance rows absent from polar matrices/KPIs and preserved in their own artifact path |

The implementation's `di_proxy` is local-window mean dB minus all-angle mean dB.
It is validated only as that software metric, not as a solid-angle-integrated
physical directivity index.

### R1 — independent primary references

Reference semantics against the official ATH 4.8.2 guide, installed AKABAK 3.2.4
help/examples or R&D Team documentation, and official VACS format/feature
documentation. External files are not committed unless their license explicitly
permits redistribution; otherwise record URL, retrieval date, hash, settings, and
derived comparison only.

At least one standalone/reference-versus-WUT numerical case is attempted. A
simulation-to-measurement comparison is attempted only if a primary, citable data
set discloses geometry, driver/excitation, environment, distance, normalization,
gating/smoothing, and reuse terms. Otherwise it remains **not validated**, rather
than substituting a visually similar plot.

Numerical acceptance must be defined for the selected reference before its WUT
result is opened. In the absence of a source-provided uncertainty, the default is
frequency-grid equality, normalized-curve RMS ≤ 1.0 dB, P95 ≤ 2.0 dB, and reported
pointwise maximum (not a pass gate because narrow cancellation notches can dominate).

### E1 — final production-path regression gate

After focused and full automated tests, run exactly one fast representative batch
through the normal Batcher GUI/service/worker path. Pass requires visible final
`done`/success status, every configured VACS TXT export present and current,
matching database rows, Analyzer access to the selected result and a checked scalar,
and zero remaining relevant ATH/Gmsh/AKABAK/VACS/Python worker PIDs from the run's
ownership ledger. No heavy E2E repetition is part of this phase.

## Primary sources frozen for interpretation

- ATH 4.8.2 User Guide: <https://at-horns.eu/release/Ath-4.8.2-UserGuide.pdf>
- AKABAK introduction and installed-help pointer:
  <https://www.randteam.de/AKABAK3/AKABAK-Introduction.html> and
  <https://www.randteam.de/AKABAK3/AKABAK-Help-Instructions.html>
- AKABAK known issues: <https://www.randteam.de/AKABAK3/AKABAK-KnownIssues.html>
- VACS documentation/features: <https://www.randteam.de/VACS/VACS-Docs.html> and
  <https://www.randteam.de/VACS/VACS-Features.html>
- COMSOL acoustics and near/far-field documentation, used only for the general
  inverse-distance/far-field criterion:
  <https://www.comsol.com/multiphysics/acoustics> and
  <https://doc.comsol.com/6.3/doc/com.comsol.help.aco/aco_ug_pressure.05.141.html>

These references establish terminology and test applicability. They do not by
themselves verify WUT's numerical output.

## Amendment A1 — profile endpoint semantics (after first result visibility)

Time: 2026-08-01, after the first three ATH-only geometry runs. This amendment is
deliberately recorded instead of silently rewriting G1/G2. At amendment time the
following results were already visible: ATH reported 164.52 mm mouth width for
`Term.n=4`, 153.61 mm for `Term.n=6`, and 250.02 mm for
`Coverage.Angle=60`; all three nominal lengths were 60.00 mm.

The original G2 criterion incorrectly required the mouth endpoint to remain within
0.05 mm when `Term.n` changes. The official ATH guide identifies `Term.n` as a
parameter of the OS-SE profile formula and states in its tutorial that outer
dimensions result from length and the defined profile(s). Therefore a changed
mouth size is an expected possible consequence of changing `Term.n`, not evidence
of non-local parameter leakage.

G2 is superseded only as follows:

- nominal length (ATH's reported device length) must remain within 0.02 mm;
- throat driver-group area must remain within 0.1%;
- the mouth endpoint is allowed to change and must agree between ATH's reported
  width and the leading inner-profile mesh/`.geo` envelope within 0.05 mm;
- the inner profile must change with maximum paired normalized-slice radius
  difference ≥ 0.50 mm and at least 20% of comparable interior samples differing
  by ≥ 0.10 mm;
- physical groups remain identical, observation and solving scripts remain
  byte-identical, and `Project.abec` may differ only by the geometry mesh filename.

G1's “axial length” is clarified as ATH's nominal device length. A free-standing
BEM mesh includes rear-wall/interface geometry outside `0…Length`, so total mesh
z-extent is retained as evidence but is not a measurement of the horn's nominal
axial length. All other frozen G1/G2 criteria remain unchanged.
