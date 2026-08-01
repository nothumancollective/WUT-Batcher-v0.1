# Scientific validation phase 3 (2026-08-01)

## Frozen baseline and scope

- Repository baseline: `c7d0df7a812f8db27b6ee9ae654a1f436869d772`
- Branch: `codex/scientific-validation-phase3-2026-08-01`
- Native tools remain the installed, Phase-2-frozen ATH 4.8.2, Gmsh 4.14.0,
  AKABAK 3.2.4.126 and VACS Viewer 2.2. No installation, preference or Registry
  change is permitted.
- Exactly three native runs are budgeted: one coarse, one medium and one fine
  mesh of the same case. They jointly answer impedance and H/V beamwidth
  convergence. A fourth run is forbidden unless a distinct failure hypothesis is
  documented before it starts.
- Native workspaces live below `tmp/scientific_validation_phase3/`. Only compact
  summaries, hashes and reproduction inputs may enter Git.

This matrix was frozen before any Phase-3 native result was generated or opened.
Criteria may only be amended with a timestamped rationale that records which
results, if any, were already visible.

## Cause of the Phase-2 gaps

Phase 2 exported `Radiation_Impedance` with `RadImpType=Normalized` and the
self-reference `1001 1001`. AKABAK's installed official help defines this as
the dimensionless specific normalized BEM radiation impedance
`Zn = Za*S'/(rho*c)` of the driven boundary. The official scripting example
confirms that repeating the group number is valid self-impedance syntax. The
zero result was therefore not an electrical input-impedance result and was not
caused by an invalid self-reference.

The exact contract omission is visible in the frozen Phase-2 inputs:

- `generic25.txt` was repaired into the project and coupled to BEM group 1001;
- `observation.txt` contained only `Driving_Values`, normalized BEM
  `Radiation_Impedance`, and H/V/D `BE_Spectrum` sections;
- the Phase-2 CFG/template did not set `LE.System` or `LE.Driver`;
- consequently no LE network-inspection/electrical-input-impedance observation
  existed to export.

ATH 4.8.2's official guide section 6.13 states that `LE.System` and `LE.Driver`
identify the LE objects used in the observation script for excursion and
electrical impedance. Phase 3 therefore does not reinterpret the all-zero
normalized BEM curve as electrical impedance. It adds the documented
`LE.System=S1` and `LE.Driver=D1` contract and evaluates the resulting electrical
input-impedance observation. The old normalized radiation-impedance graph remains
a separate secondary output and must not be substituted for it.

## Frozen common native case

The three cases differ only in mesh controls. Geometry and solver/observation
contracts are fixed as follows:

- OS-SE profile: profile 1; throat diameter 25.4 mm; throat half-angle 7 deg;
  coverage half-angle 45 deg; length 60 mm; `Term.s=0.5`, `Term.n=4`,
  `Term.q=0.996`, `OS.k=1`, no morphing.
- LE: ATH `generic25`; `LE.System=S1`; `LE.Driver=D1`; 1.0 V RMS. The harness
  repair profile is `driver_drvgroup_def_driving_resistor`, preserving the
  established group-1001 BEM/LE coupling.
- Frequencies: 1000 to 4000 Hz, seven logarithmically spaced points, mesh
  frequency 4000 Hz.
- Observation origin/axis: ATH/ABEC `BE_Spectrum`, base plane `zx`, centre offset
  +65 mm on z, radius 3 m. H inclination is 0 deg; V is 90 deg.
- Both polar maps use signed `PolarRange=-90,90,37`, hence a 5 deg sampled grid
  including 0 deg and both sides of the main axis.
- Mesh levels:

| Level | Angular segments | Length segments | Mouth resolution | Throat resolution |
|---|---:|---:|---:|---:|
| coarse | 24 | 12 | 24 mm | 14 mm |
| medium | 48 | 20 | 18 mm | 10 mm |
| fine | 72 | 28 | 12 mm | 8 mm |

All three meshes must preserve identical physical-group names, solver settings,
observation definitions and LE semantics. Node and triangle counts must increase
strictly coarse < medium < fine.

## Frozen criteria matrix

| ID | Hypothesis | Independent reference/check | Frozen tolerance and pass/fail rule |
|---|---|---|---|
| I1 | The coupled `generic25` system produces a nontrivial electrical input impedance. | ATH guide 4.8.2 section 6.13; generated observation contract; AKABAK/VACS graph metadata. | A graph explicitly identified as LE/electrical input impedance (not `Radiation_Impedance`) must exist for every level. Unit must be ohm or metadata must unambiguously define electrical impedance. Every complex sample is finite; at least one `|Z| >= 1 ohm`; at least one point has `|Im(Z)| >= 0.01 ohm`. Otherwise I1 fails. |
| I2 | Electrical impedance converges with mesh refinement. | Independent complex arithmetic on raw TXT, then parser and SQLite lookup by run/version/graph identity. | Use all seven common frequencies. Complex relative RMS `sqrt(sum(|Zm-Zf|^2)/sum(|Zf|^2)) <= 0.02`; maximum relative magnitude error `<= 0.05`; circular phase MAE `<= 2 deg` and maximum `<= 5 deg` where `|Zf|>=1 ohm`. Medium-fine complex RMS must be no greater than coarse-medium plus `1e-9`. Raw-parser and parser-DB real/imag differences each `<=1e-9 ohm`. |
| B1 | Signed H and V maps contain genuine -6 dB crossings rather than range-edge saturation or symmetry inference. | Independent on-axis normalization and piecewise-linear interpolation in dB between adjacent angular samples. | For every evaluated frequency and each plane, one negative-angle and one positive-angle crossing of -6.000 dB must lie strictly inside (-90,90). Width is `theta_positive - theta_negative`; neither side may be inferred or clamped. At least 5 of 7 frequencies per plane must qualify; failure is reported per plane. |
| B2 | H/V beamwidth converges with mesh refinement. | Independent B1 calculation versus `compute_beamwidth_curve`, then raw polar -> parser -> SQLite -> Analyzer. | On common eligible frequencies, medium-fine MAE `<=3 deg` and maximum `<=6 deg`, separately for H and V. For each plane, medium-fine MAE must be no greater than coarse-medium plus `1e-9`. Independent and Analyzer widths must agree within `1e-9 deg`; raw-parser and parser-DB levels within `1e-9 dB` after the same pressure conversion. H and V are never pooled to manufacture a pass. |
| P1 | The observed change is a mesh effect, not a changed contract. | SHA-256 and semantic extraction of CFG, `Project.abec`, solving, observation and LE snapshots. | Geometry/solver/observation/LE settings listed above are identical except mesh controls and mesh filename; physical groups identical; all runs succeed; each runtime is below the configured 40-minute hard limit. |
| M1 | A public primary measurement source is adequate for a numeric comparison. | Official ATH/AKABAK/VACS material, developer-published project data, peer-reviewed paper supplement, or manufacturer raw data. | Before inspecting numeric agreement, the source must provide reusable numeric complex impedance and/or polar/SPL data, exact horn and driver identity/geometry, frequency and angle grids, measurement distance/origin/axis, environment and gating/windowing, stimulus/reference/normalization, calibration, and clear lawful accessibility. Missing any mandatory field rejects it for numeric comparison; plot digitization is prohibited. |

No I2 pass is allowed from the known normalized-zero BEM graph. If ATH 4.8.2
still does not generate its documented LE impedance observation despite the
explicit system/driver tags, that is a failed model/export contract, not numeric
convergence. A fourth native run would then require a new, documented hypothesis.

## Measurement-comparison fallback protocol

If no source passes M1, simulation-to-measurement remains **not validated** and
the final evidence will record the search rather than inventing data. A future
comparison package must contain:

1. machine-readable complex electrical impedance (`frequency_Hz, real_ohm,
   imag_ohm`) and/or polar pressure (`frequency_Hz, angle_deg, real_Pa, imag_Pa`;
   magnitude/phase is acceptable with declared phase convention);
2. exact horn geometry or immutable model/source revision plus driver identity,
   diaphragm/throat reference plane and any adapter/phase-plug details;
3. right-handed coordinate system, acoustic origin, forward axis, H/V plane
   definitions, angle sign, microphone distance and near-/far-field declaration;
4. stimulus voltage and RMS/peak convention, source impedance, SPL reference,
   microphone/interface calibration and environmental temperature/humidity;
5. environment and boundary conditions, microphone technique, time window/gate,
   window family/length, smoothing and frequency resolution;
6. raw or losslessly exported CSV/TSV/TXT/FRD/ZMA data, provenance hash, licence
   or explicit permission, and enough metadata to reproduce normalization.

Comparison tolerances must be frozen for the specific accepted data set before
WUT output is evaluated. Simulation/setup uncertainty and manufacturing/driver
spread must be separated from software error.

## Amendment A1 - explicit ATH LE observation block after diagnostic run 1

Time: 2026-08-01, after only the first coarse diagnostic result was visible and
before starting medium or fine. That run (`fc0eaf9b-6b2f-426d-ab3f-f9d9960b584a`)
succeeded in 45.12 s and produced valid signed H/V maps, but its frozen ATH
snapshot proved that ATH 4.8.2 still omitted `LE_Spectrum` despite the explicit
`LE.System=S1` and `LE.Driver=D1` inputs. Only normalized BEM
`Radiation_Impedance` was present. I1 therefore failed for that run exactly as
predeclared; no tolerance is changed and the zero BEM curve is not relabelled.

Read-only string inspection of the exact frozen `C:\Tools\ATH\ath.exe` then
recovered ATH's own embedded output template:

```text
LE_Spectrum
  System='%s'; AnalysisType=Impedance
  Range_min=0; Range_max=50
  GraphHeader='DrvImp'; BodeType=Ampl_Phase; ID=2002
```

The new hypothesis is that ATH's conditional emission is broken or bypassed in
this invocation, while AKABAK can still consume ATH's own documented block once
it is inserted after ATH generation and after the existing LE repair. The
harness-only `le_electrical_impedance` observation profile now appends that exact
block idempotently with `System='S1'`; it does not alter geometry, solver, LE
parameters, the BEM coupling or any pass tolerance.

The first run is retained as diagnostic evidence. The permitted fourth native
run is now justified in advance: repeat coarse once with the exact observation
block, then run medium and fine once each. These three post-amendment runs form
the convergence matrix. If the coarse repeat does not yield a distinct nonzero
`DrvImp` graph, I1/I2 fail and medium/fine will not be spent on that hypothesis.

## Final results

The post-amendment matrix passed every frozen numerical criterion. Compact
machine-readable results and all raw-file hashes are in
`evidence/phase3_convergence_2026-08-01.json`; large native workspaces remain
under ignored `tmp/scientific_validation_phase3/`.

| Level | Run | Wall time | Electrical `|Z|` range | H beamwidth 1/4 kHz | V beamwidth 1/4 kHz |
|---|---|---:|---:|---:|---:|
| coarse | `ef3d2618-366e-4f0d-a131-30656c484f84` | 43.99 s | 8.642-25.226 ohm | 157.767 / 62.074 deg | 157.689 / 62.110 deg |
| medium | `cdd27004-1012-4118-9136-273440177e9e` | 60.12 s | 8.641-25.231 ohm | 158.531 / 61.731 deg | 158.418 / 61.873 deg |
| fine | `70c8e5f1-cdfa-4424-8e51-9fd58153ae08` | 63.04 s | 8.644-25.233 ohm | 158.837 / 61.786 deg | 158.900 / 61.812 deg |

### A - electrical impedance convergence: verified

- The exported graph is `LE_Spectrum`, legend `Impedance, System=S1`, base unit
  `ohm`; it is distinct from the all-zero dimensionless BEM
  `Radiation_Impedance` graph.
- All seven 1000-4000 Hz complex samples are finite and nontrivial for every
  mesh. The raw TXT parser and runner SQLite real/imag/frequency values agree
  exactly (maximum delta 0).
- Coarse-medium complex relative RMS is 0.0005154; medium-fine improves to
  0.0002738 (0.0274%). Medium-fine maximum relative magnitude error is
  0.0004713 (0.0471%). Phase MAE is 0.00841 deg and maximum 0.01923 deg.
- Thus the 2% complex RMS, 5% magnitude, 2/5 deg phase and convergence-trend
  gates pass with substantial margin.

This verifies the electrical input impedance of the tested `generic25`/S1
network from 1-4 kHz. It does not validate a physical compression driver's
parameter accuracy, and it does not convert the separate BEM normalized-zero
curve into a meaningful radiation-impedance result.

### B - H/V beamwidth convergence: verified

- All seven frequencies in all six H/V polar maps have explicit negative- and
  positive-angle -6.000 dB crossings strictly inside -90...+90 deg. No width is
  saturated, clamped or symmetry-inferred.
- H medium-fine MAE/max are 0.3291/0.4819 deg, improving from
  0.5486/0.7649 deg coarse-medium.
- V medium-fine MAE/max are 0.2793/0.4824 deg, improving from
  0.6184/0.7875 deg coarse-medium.
- Raw TXT was parsed into a fresh production-schema SQLite database through
  `TidyDatasetWriter`; `AnalyzerPlotService` reloaded it. The maximum normalized
  matrix difference versus independent conversion is `2.84e-14 dB`; independent
  versus Analyzer beamwidth differs by at most `2.56e-13 deg`.

The native harness intentionally deletes meshes after its owned-process cleanup.
Mesh topology counts therefore reuse Phase 2's compact evidence for the exactly
same four mesh-control tuples: 178/302, 251/428 and 375/660 nodes/triangles.
Current runner DB snapshots prove those tuples, and Project/solving/observation/LE
snapshots are byte-identical between the three runs. This is explicit provenance,
not a claim that deleted Phase-3 mesh bytes were re-hashed.

### C - simulation versus measurement: remains open

The primary-source review is recorded in
`evidence/phase3_measurement_source_review_2026-08-01.json`. Official ATH pages
for the Extended-Throat work, ST260 and A460D provide useful geometry, simulation
or measurement figures but not reusable numeric arrays plus every required setup
field. R&D Team's official studies and already-installed AKABAK example package
contain relevant model projects/comparison presentations, but no reusable
CSV/FRD/ZMA measurement data set satisfying M1. The primary AkAbak compression
driver paper likewise has figures without a machine-readable supplement suitable
for this WUT case.

Accordingly no graph was digitized and no numeric agreement was invented.
Simulation-to-measurement is **not validated**. The frozen fallback protocol above
is the exact acquisition contract for a future comparison.

## Classification and remaining boundaries

- Electrical input-impedance mesh convergence for this coupled `generic25` case:
  **verified**.
- Full signed H/V -6 dB beamwidth mesh convergence for this case: **verified**.
- TXT -> production SQLite -> Analyzer beamwidth chain for these real native
  polars: **verified**.
- ATH's omission of its own embedded `LE_Spectrum` observation: **verified
  reproducible** and narrowly repaired in the harness observation profile. This
  is test/runtime-contract support, not a new product feature.
- Dimensionless normalized BEM radiation impedance for this topology:
  **not validated** (still a separate all-zero secondary graph).
- Simulation agreement with physical measurements: **not validated** pending a
  source satisfying M1.
