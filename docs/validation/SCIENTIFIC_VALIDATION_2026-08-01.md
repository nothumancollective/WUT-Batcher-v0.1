# Scientific Validation 2026-08-01

- Status: active
- Baseline date: 2026-08-01
- Baseline commit: `e0ac543a1e8e7d048bc7764c4ca75f5778e0aeef`
- Evidence integration commit: `5f4c6cfff6e608718d77fb696e5a946fbe6c7f65`
- Production-GUI/LE baseline commit: `ea9a81112b054da1f4dcb906f58948335301ff61`
- Observation fixes: `cca2d538189299e045cdafee229ee4377e1eb1e1`,
  `7c2b7d7a676783096e590f2d94f9d1b4be6f75f2`
- Source branch: `codex/scientific-validation-2026-08-01` (integrated into `main`)

## Scope and evidence labels

This round determines whether WUT transfers horn geometry, lumped-element
driving, solver/observation settings and VACS results correctly through the
complete pipeline. It does not claim absolute correctness without independent
evidence.

Every conclusion uses one of these labels:

- **verified**: directly demonstrated by inspectable inputs/artifacts and an
  independent calculation, exact contract check or matched standalone run;
- **plausibilized**: consistent with documentation and observed behavior, but
  not yet independently reproduced to the required numerical tolerance;
- **unvalidated**: insufficient evidence or a deliberately deferred external
  condition.

## Frozen environment

### Application and platform

- WUT baseline: `e0ac543a1e8e7d048bc7764c4ca75f5778e0aeef`
- Windows 11 Pro ARM64, build `26200`
- Python `3.12.2` ARM64
- SQLite `3.43.1`
- PySide6 `6.10.2`
- Windows session boot: `2026-08-01 04:34:01 +02:00`

### Native tools

| Tool | Exact executable/version evidence | SHA-256 |
| --- | --- | --- |
| ATH | `C:\Tools\ATH\ath.exe`; generated `config.txt` marker `Ath version V2025-06` | `639CB0184CF5DAE233F3D2624CF279057A217DA26948BDE6D1D6510314B9A1E1` |
| Gmsh | `C:\Tools\ATH\gmsh.exe`; CLI version `4.15.0` | `0AEEA78040F6C367E7718F05BB2ACE05AA7F45912F9AEE77353191C428E47D96` |
| AKABAK | `C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe`; file version `3.2.4.126`, product `3.2` | `F5C7621684D368ED5E9405C7AC958A8CB0B79522327A84425FD43D053E6E7E26` |
| VACS | `C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe`; file version `2.1.3.33`, product `2.1` | `A3631C245D99E3E417BF9CCDE5209D59B13FD81D97168E611CE4FBB360FA8623` |

The installed `Ath-4.8.2-UserGuide.pdf` is a documentation source only; its
version is not used as evidence for the newer ATH binary.

### Effective WUT settings

Source: `C:\Users\maximilianheinze\.wut_batcher\config.json`, SHA-256
`7707EA0A2D287DD15824A69A7DC7FDC01408F6B8D98EAE3EA209D3A358708579`.

- production library: `C:\Users\maximilianheinze\Desktop\WUT Project Library`
- background automation: disabled
- simulation timeout: 10 minutes
- Analyzer source: project
- Analyzer cache: balanced, 240 MB, last 5
- ATH/AKABAK/VACS paths: the exact executables listed above
- template CFG: unset

The production library and persisted user settings are read-only evidence in
this round. They must not be rewritten by validation runs.

## Isolation and process invariants

All new cases use:

- validation root: `tmp/scientific_validation_e0ac543/`
- isolated library: `tmp/scientific_validation_e0ac543/library/`
- standalone references: `tmp/scientific_validation_e0ac543/standalone/`
- WUT runs: `tmp/scientific_validation_e0ac543/wut/`
- comparison outputs: `tmp/scientific_validation_e0ac543/comparisons/`

Each native test records pre/post CPU, RAM, PID, parent PID, executable path
and start time. Only the exact owned process tree may be stopped. An unknown
AKABAK/VACS instance blocks the case. A true VM/profile-first VACS session is
externally deferred; application-cold and warm starts remain in scope.

## Validation contracts

The evidence chain is evaluated in this order:

1. UI/project/batch/version values and units;
2. rendered ATH CFG and effective/defaulted parameters;
3. ATH geometry, mesh, ABEC files and dimension report;
4. imported AKABAK definitions, LE file and source coupling;
5. solver frequency/mesh/medium/boundary settings;
6. observation origin, axis, distance, plane and normalization;
7. current VACS graph identity and raw complex TXT export;
8. project/global database rows;
9. Analyzer normalization, interpolation, beamwidth/DI and KPI values.

Before each numerical benchmark, its tolerance is written into the comparison
manifest. Exact textual contracts and discrete identities require equality.
Round-trip complex values use an initially proposed absolute tolerance of
`1e-12`; this threshold must be confirmed against the actual TXT precision
before it can become a gate. Solver-result tolerances are not frozen until the
standalone and WUT cases are proven to use identical meshes and settings.

## Planned benchmark matrix

| ID | Question | Method | Initial status |
| --- | --- | --- | --- |
| G-01 | Are throat, mouth, length and profile transferred exactly? | Artifact contract plus one-parameter ATH A/B cases | length/throat verified; mouth/profile unvalidated |
| G-02 | Is mesh orientation and source-side topology preserved? | Mesh/ABEC semantic parser and signed-coordinate checks | verified for the quarter-model cases |
| LE-01 | Is `generic25` present, imported and actually coupled? | Exact file/reference checks plus controlled electrical/motor mutation | loaded, coupled and active response verified for the recorded baseline |
| S-01 | Are frequency grid and solver settings exact? | Generated-file inspection and standalone/WUT equality | generated settings and log grid verified for the recorded case; independent solver equivalence unvalidated |
| S-02 | Is the mesh sufficiently converged? | Three predeclared resolution levels; runtime/error table | unvalidated |
| O-01 | Are origin, axis, planes, distance and reference correct? | Observation-file inspection, axis tests and distance doubling | H/V/D, distance, offset and normalization file contract verified; physical distance/axis tests unvalidated |
| V-01 | Does VACS export only current graphs and full complex values? | Exact graph signatures and raw-TXT checks | verified for production-GUI case B008; acoustic correctness remains separate |
| D-01 | Is raw TXT to DB lossless? | Pointwise raw/parser/SQLite comparison | verified for B008 in both databases, max absolute delta 0 |
| A-01 | Are Analyzer plots/KPIs numerically correct? | Synthetic golden data and independent small calculations | magnitude, normalization and beamwidth primitives verified; aggregate KPI chain unvalidated |

## Completed ATH geometry and mesh contract probe

The isolated baseline probe is reproducible with
`tools/scientific_validation/ath_contract_probe.py`. Its compact committed
result is
[`evidence/ath_contracts_2026-08-01.json`](evidence/ath_contracts_2026-08-01.json).
The evidence records the SHA-256 of the original full manifest as
`CC516C40D50318AE1B030E21B6D903917FE5C7B0433F291C7648AFED410F05B2`;
the large generated meshes remain below the ignored validation root.

Six standalone ATH cases completed with exit code 0 and no timeout. No native
tool process remained after the suite. The verified contracts are:

- changing `Length` from 120 mm to 160 mm changed ATH's reported length from
  exactly 120.0 mm to 160.0 mm and scaled the reported width from 419.58 mm to
  558.57 mm;
- changing `Throat.Diameter` from 32 mm to 40 mm changed the driver-group mesh
  area by a factor of 1.562516, matching the expected squared-diameter ratio
  1.5625 within 0.0011%;
- every parsed mesh retained the four required physical groups `SD1G0`,
  `SD1D1001`, `SD2G0` and `I1-2`;
- all mesh coordinates were non-negative in x/y, consistent with the declared
  `Sym=xy` quarter model;
- the driver-group oriented normal sum points in +z into the horn domain, while
  the interface normal points in -z toward Subdomain1, consistent with the
  documented AKABAK element-domain convention;
- the three resolution cases produced distinct, ordered mesh densities: 1,186
  nodes / 2,252 triangles (fine), 846 / 1,576 (medium), and 669 / 1,224
  (coarse).

This verifies G-01 for length and throat transfer, and verifies G-02 for the
declared quarter-model topology and orientation. Mouth/profile transfer is not
yet independently parameterized. The resolution cases verify that the controls
change mesh density as intended, but they do **not** establish S-02 convergence;
that still requires a predeclared result-error comparison across the three
meshes.

## Normal production-GUI and VACS round-trip baseline

The committed machine-readable evidence is
[`evidence/gui_vacs_roundtrip_b008_2026-08-01.json`](evidence/gui_vacs_roundtrip_b008_2026-08-01.json).
It records a complete one-version batch through the actual GUI-created
service/worker, not the runner-test CLI. The GUI was launched as
`pythonw -m app gui` with only the supported settings-path override directed
to the isolated profile. Neither the production nor isolated settings file
changed during the run.

B008/V008 (`914edb8e-78a1-4c33-bdc5-9df3bdc72ad2`) completed in 360.13 s.
The visible run page reached `Version 1/1`, `Mode: real`, `ETA: done` and
`Run finished for B008`; `version.json` reported `success`, while the run rows
in the global and project databases reported `succeeded`. The exact owned
AKABAK, VACS and export-helper processes ended, the GUI was then closed
normally, and the independent post-state contained zero relevant processes.

VACS exposed three current `Mic Polar` graph windows and one current
`Radiation Impedance` window. All four exports succeeded and passed the
pipeline's file verification without fallback. Each raw file was byte-equal
to its semantic `x_*.txt` copy. An independent line parser then compared the
TXT numbers to both SQLite databases without calling WUT's parser/importer:

- all 342 complex polar samples (3 planes x 6 frequencies x 19 angles) were
  identical, including H/V/D orientation, frequency and angle metadata;
- all 24 graph samples (four graphs x six frequencies) were identical;
- the maximum absolute difference was exactly 0;
- the relevant global and project database tables were row-for-row identical.

This verifies V-01 for current graph identity and full complex export in this
production case, and verifies D-01 for the complete exported data set. It does
not infer that the simulated acoustic values, observation placement,
normalization or Analyzer-derived metrics are correct; those remain separate
contracts below.

## Current LE-network activation proof

The compact evidence is
[`evidence/le_observation_contracts_2026-08-01.json`](evidence/le_observation_contracts_2026-08-01.json).
On application commit `ea9a811`, three real ATH -> AKABAK -> VACS runs executed
in randomized matrix order: control, electrical mutation and motor mutation.
All three succeeded and ended with zero relevant processes. Their retained
`Project.abec`, `solving.txt` and `observation.txt` files are bit-identical;
only `generic25.txt` differs. Project, solving, observation and LE script agree
on `generic25.txt`, 1 V RMS, the `D1` source and driver group `1001`.

An independent parser, separate from WUT's comparison code, recalculated the
axis pressure magnitude from every raw H/V/D TXT row. Across 18 points it
reproduced the harness results exactly: 0.225259745 Pa RMS for the electrical
mutation and 0.507164598 Pa RMS for the motor mutation. The latter exceeds the
predeclared absolute 0.25 Pa effect floor. All twelve raw/semantic file pairs
were byte-identical. This verifies that the recorded LE file is not merely
present but is loaded and affects the acoustic result.

The normalized radiation-impedance graph stayed at zero and is deliberately
not used as LE evidence. Only one current repeat per profile was run, so the
0.25 Pa floor is a policy threshold rather than a newly measured noise floor.
The retained snapshots also do not include all three meshes after safe cleanup;
identical geometry/profile inputs and post-ATH mutation make equal meshes
strongly plausible, but the report does not claim three retained mesh hashes.
Absolute acoustic accuracy of the driver model remains unvalidated.

## Solver and observation contracts

The recorded LE control case generated `f1=800 Hz`, `f2=4000 Hz`, six
logarithmic frequencies, `Dim=3D`, `MeshFrequency=200 Hz`, `Sym=xy`, a 1 mm
mesh scale and an exterior subdomain. The exported grid
`800, 1103.784, 1522.923, 2101.222, 2899.119, 4000 Hz` agrees with the
independent geometric-grid calculation to at most 0.000346 Hz, below the TXT
rounding precision. S-01 is therefore verified as a generated-file and result
grid contract for this case. It does not prove independent solver equivalence,
medium defaults, damping correctness or convergence.

The production B008 request contained `norm_angle=20` for H/V/D, but commit
`ea9a811` neither rendered `NormAngle` into the ATH polar blocks nor persisted
it in `polar_measurements`; every stored value was null. This was a verified
data-flow defect, not an acoustic inference. Commit `cca2d53` now renders the
value, including valid 0 degrees. A real isolated ATH-only run exited 0 and
translated the three `NormAngle = 20` CFG values into three
`NormalizingAngle=20` observation entries for inclinations 0, 90 and 45
degrees. No ATH process remained.

Commit `7c2b7d7` separately repairs the VACS Save-All metadata path: the source
H/V/D token selects the matching batch polar specification. A common fallback
is accepted only if all configured plane angles are equal; an orientation-free
divergent set remains null. The end-to-end importer regression stores 30
degrees for a D export configured as H=10, V=20, D=30. This verifies the
normalization contract from UI configuration through ATH observation and from
VACS contract through SQLite. A fresh long AKABAK/VACS run was intentionally
not repeated; the user explicitly excluded another long solver gate after the
completed matrix.

ATH's generated observations also confirm H/V/D inclinations 0/90/45 degrees,
polar range 0..90 with 19 points, distance 3 m and offset 65 mm in the isolated
post-fix case. The official ATH guide defines distance from the origin, offset
along z in millimetres, inclination 0 as horizontal and 90 as vertical. These
file and unit contracts are verified. A physical distance-doubling result test,
far-/near-field sensitivity and independent origin/axis benchmark remain
unvalidated.

## Analyzer numerical primitives

The synthetic golden tests independently cover `20*log10(hypot(re, im))`,
normalization to an explicitly stored reference angle and linearly interpolated
minus-6-dB beamwidth. The one-sided 0/-3/-8/-15 dB example crosses at 16
degrees and is correctly mirrored to a 32-degree full beamwidth; saturated
cases are marked as inferred. These primitives are verified. The complete
multi-plane DI proxy, smoothing, stage aggregation and UI presentation chain
has not yet been benchmarked against an external numerical dataset, so A-01
is only partially verified.

## External references

Primary sources are preferred: installed ATH documentation, official
AKABAK/VACS documentation and official example projects. Web references and
licenses are recorded next to each reproduced benchmark. No third-party asset
is committed unless redistribution is explicitly permitted.

Sources used in this round:

- [official ATH 4.8.2 User Guide](https://at-horns.eu/release/Ath-4.8.2-UserGuide.pdf):
  `ABEC.Polars`, frequency/mesh settings, distance, offset, inclination,
  normalization and LE coupling semantics;
- [official ATH site](https://at-horns.eu/) and
  [download/licensing page](https://www.at-horns.eu/download.html): ATH is
  offered free for personal non-commercial use; commercial use requires a
  licence. No ATH binary, guide or example asset is copied into this repo;
- [official AKABAK introduction](https://randteam.de/AKABAK3/AKABAK-Introduction.html)
  and [technical specifications](https://www.randteam.de/AKABAK3/AKABAK-TechSpec.html):
  BEM/LEM coupling, mesh import, observation flow and automatic VACS link;
- [official VACS page](https://randteam.de/VACS/Index.html) and
  [R&D Team licence matrix](https://randteam.de/Commercial/Licenses.html):
  VacsViewer can export individual datasets but cannot save VACS project
  files; demo/pro versions share modelling features, with persistence limits.

The official R&D Team news page listed AKABAK 3.3.2 b144 in June 2026, while
this frozen VM uses 3.2.4.126. No upgrade was attempted because it would alter
the validated toolchain and may require licence-aware manual installation.
The version gap is a remaining compatibility risk, not evidence of a defect in
the current baseline.

## Current conclusion

The environment and isolation contract, length/throat geometry transfer, the
declared quarter-model mesh topology/orientation, production GUI/worker
lifecycle, active LE coupling, recorded solver grid, H/V/D observation-file
contract, polar normalization data flow, current VACS graph identity, complex
TXT preservation, dual-DB persistence and core Analyzer math are **verified**
for the recorded cases. No absolute acoustic-accuracy claim follows from
those contracts. Mouth/profile parameter isolation, result convergence,
independent solver equivalence, physical distance/axis response, complete KPI
aggregation and simulation-versus-measurement comparison remain explicitly
**unvalidated**.
