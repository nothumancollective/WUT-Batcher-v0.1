# Scientific Validation 2026-08-01

Status: active  
Baseline date: 2026-08-01  
Baseline commit: `e0ac543a1e8e7d048bc7764c4ca75f5778e0aeef`  
Working branch: `codex/scientific-validation-2026-08-01`

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
| G-01 | Are throat, mouth, length and profile transferred exactly? | Artifact contract plus one-parameter ATH A/B cases | unvalidated |
| G-02 | Is mesh orientation and source-side topology preserved? | Mesh/ABEC semantic parser and signed-coordinate checks | unvalidated |
| LE-01 | Is `generic25` present, imported and actually coupled? | Exact file/reference checks plus controlled electrical/motor mutation | plausibilized by historical LE proof; current baseline unvalidated |
| S-01 | Are frequency grid and solver settings exact? | Generated-file inspection and standalone/WUT equality | unvalidated |
| S-02 | Is the mesh sufficiently converged? | Three predeclared resolution levels; runtime/error table | unvalidated |
| O-01 | Are origin, axis, planes, distance and reference correct? | Observation-file inspection, axis tests and distance doubling | unvalidated |
| V-01 | Does VACS export only current graphs and full complex values? | Exact graph signatures and raw-TXT checks | plausibilized by stability gates; numerical path unvalidated |
| D-01 | Is raw TXT to DB lossless? | Pointwise raw/parser/SQLite comparison | unvalidated |
| A-01 | Are Analyzer plots/KPIs numerically correct? | Synthetic golden data and independent small calculations | unvalidated |

## External references

Primary sources are preferred: installed ATH documentation, official
AKABAK/VACS documentation and official example projects. Web references and
licenses are recorded next to each reproduced benchmark. No third-party asset
is committed unless redistribution is explicitly permitted.

## Current conclusion

Only the environment and isolation contract are **verified** at this point.
The historical native stability gates prove reproducible execution and current
graph export, but they do not by themselves prove scientific correctness.
