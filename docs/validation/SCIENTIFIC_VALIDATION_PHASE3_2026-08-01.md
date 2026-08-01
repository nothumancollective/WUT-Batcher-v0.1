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
