# Stability and integration audit — 2026-07-31

Status: implementation complete; final full-suite validation and local `main`
integration are recorded at the end of this document.

## Scope and guardrails

This pass covered repository history, the previous audits, automated tests,
real visible ATH/AKABAK/VacsViewer runs, compatibility warnings, external-tool
setup and the active Project Library.

Safety rules used throughout:

- all destructive experiments ran under ignored `tmp/` libraries;
- no external tool was downloaded, upgraded or reinstalled;
- no project, version or database was deleted or migrated;
- production database integrity was checked on copies, not by repairing live
  databases;
- production-library inspection was read-only apart from Doctor's temporary
  create/delete writeability sentinel;
- each real run started with no known tool process and ended with no ATH,
  Gmsh, AKABAK or VacsViewer process;
- auto-push was disabled for every commit; this audit does not push.

## Branch archaeology and integration decision

The former `main` head (`532a351`) is an archive/revert line and is not the
current product tree. The active product history continued through
`wut-batcher/rebuild` (`fd84201`). The newest Project Manager line ended at
`c5e6860`, while runner/device-dimension changes continued separately on
`feature/batch-lineage-graph` (`0850f67`).

The integration branch was therefore created from `c5e6860`, protected with
tag `safety/pre-20260731-stability-integration`, and merged with the lineage
branch in `d3b19fc`. Earlier analyzer, storage, UI and runner feature branches
are already ancestors of that product line. This avoids cherry-picking the
same features again or reviving the archived tree.

Finalization policy:

1. keep the integrated product files as authoritative;
2. restore the useful backup workflow from archived `main`;
3. join the archived `main` ancestry with a content-preserving merge;
4. move the local `main` reference to the validated integration head;
5. retain old branch references as historical evidence instead of deleting
   them without an explicit cleanup decision.

## Root causes and corrections

| Area | Observed failure mode | Correction |
| --- | --- | --- |
| Sweep planning | Combined sweeps could expand without a safe bound and fuzz validation could effectively hang. | Bound expansion and reject oversized plans (`e520a8b`). Numeric JSON inputs are normalized consistently (`fd9dee9`). |
| Tool paths | Unquoted Gmsh invocation failed on Windows paths; discovery could disagree between setup and runtime. | Safe Gmsh command generation (`d2e7e03`) and shared existing-install discovery (`4e9af30`). |
| VACS requests | The runtime requested RadImp-incompatible options and accepted partial graph coverage as success. | Options now depend on graph class (`12b1f6c`); requested H/V/D/impedance coverage is mandatory (`18e56b0`); actionable export failures are retained (`1633bec`). |
| Windows path length | VACS exports failed in normal service projects although short harness paths worked. | Stage exports through a short temporary path, then copy into the project-owned destination (`041d14e`). |
| AKABAK ownership | A pre-existing or second AKABAK process was mistaken for the worker, producing false running/hung signals. | Track only stage-owned process signals and refuse unsafe overlap (`3008574`). |
| Slow solves | One fixed timeout treated real CPU progress like a hang and provided no useful telemetry. | Record solve heartbeats (`1f17612`); timeout is inactivity-based while progress continues, with a bounded hard limit (`c2d930b`). |
| Failure cleanup | VacsViewer was left open after AKABAK failure; process-exit races could fail cleanup itself. | Close VACS on failed upstream stages (`a916eec`) and tolerate already-exited process races (`dc57350`). |
| UI polling | Recursive UIA descendant scans became slow/unstable while AKABAK and VACS were busy. | Use bounded native HWND enumeration and consider all diagnostic windows before selecting maxima (`46bc0b5`, `dfc947d`). |
| Version storage | Re-running an unchanged batch materialized another immutable version cohort. | Reuse the canonical existing version (`5c35a57`); audit historical duplicates read-only (`97d2ac9`). |
| Compatibility messages | ATH experiment hypotheses appeared like proven incompatibility warnings. | Evidence-backed constraints remain warnings; hypotheses are explicitly non-blocking hints (`2b52bda`). |
| Diagnostics | CLI Doctor inspected obsolete `app_config.json` concepts instead of live GUI/runtime settings. | CLI and GUI now share `SettingsStore` checks (`ace3226`). |
| Real compatibility verifier | A bare `gmsh.exe` opened the GUI, timeout cleanup omitted descendants, and `--no-sql` still created a nested DB. | Run `gmsh.exe %f -`, kill the owned process tree, and instantiate no writer in no-SQL mode (`23fe465`). |

The runtime also now has one authoritative library-root contract (`a877015`,
`0faf932`), materializes graph exports without losing requested features, and
avoids opening a second VACS copy during failure handling.

## Real on-screen evidence

All tests below used the already installed executables:

- ATH: `C:\Tools\ATH\ath.exe`
- Gmsh: `C:\Tools\ATH\gmsh.exe`
- AKABAK: `C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe`
- VacsViewer: `C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe`

### Fast and repeated batches

- Baseline visible end-to-end run: success in 46.87 s, four requested VACS
  graphs and four raw exports, clean process exit.
- Five-repeat runner harness: 5/5 successful, 20/20 requested exports, roughly
  46 s per run, no surviving tool process.
- Real service batch after strict graph coverage/path staging: run
  `75e1bc08-576e-4ac6-9d16-2c652f69a1d7`, 5/5 versions successful. Each version
  produced H, V, D and radiation-impedance data with 40 frequency points and
  eight files (four raw plus four normalized exports).
- Post-timeout-fix single run:
  `007cd807-6637-4ca9-a510-b18d827cbd22`, success in 70.1 s. All seven stages
  passed; AKABAK heartbeats showed actual progress; four graphs/eight files
  were preserved; process and temporary-stage cleanup completed.

### Resource-intensive two-version batch

The stress batch swept horn length across two variants and used 400–16000 Hz,
32 frequency points, 2000 Hz mesh frequency, three polar planes with 37 angular
samples each, plus radiation impedance.

An early run exposed the global-PID and fixed-timeout defects. After those
fixes, the isolated on-screen capture ran from 20:57:12 to 21:02:49 local time:

- run ID: `a44abeb9-cd8f-4a14-9a4d-2f157b2efffa`;
- result: `succeeded`, process return code 0;
- V001 and V002: ATH, ABEC synchronization, LE repair, LE/mesh guards,
  AKABAK and VACS all `ok`;
- zero timed-out stages and two persisted ATH dimension rows;
- each version exported three SPL polar graphs plus one impedance graph, with
  four raw and four normalized files;
- no simulation-tool processes remained afterward.

The capture started after `dfc947d`, so it validates the final native VACS
readiness polling rather than the earlier recursive UIA implementation.

### VACS discovery edge case

A separate visible blank-VacsViewer probe verified that helper/editor HWNDs are
not mistaken for completed graph windows. Native polling inspected all windows,
reported the blank state correctly, and closed the single owned VACS process.

## Compatibility logic

The compatibility suite passed 40 focused tests, including rule evaluation,
DSL behavior, UI presentation and fuzz cases. The evidence report currently
contains seven ATH-document-backed facts and 18 experiment-derived hypotheses.
Only the former can create compatibility warnings; the latter are labelled as
evidence hints.

Real ATH verification after process-tree and Gmsh corrections:

- quick profile: 6/6 passed, no timeout, correct STL/ABEC combinations, no
  nested project DB under `--no-sql`;
- full profile: 8/8 passed, no timeout, source-default and output-flag behavior
  matched expectations;
- no ATH or Gmsh process remained after either profile.

## Tool setup and licensing boundary

The setup assistant exposes status and detection in both CLI and Settings. It
auto-opens Settings only when a first launch is incomplete. It can repair only
missing/stale configured paths and never replaces a valid one.

ATH, AKABAK and VACS remain manual-download tools, with official links and
license summaries shown before the user leaves WUT. Gmsh can be installed via
`winget` only after explicit confirmation, and only if discovery finds no
existing copy. On this VM `setup status`, `setup detect` and the Gmsh install
preflight all reused the installed copies; nothing was installed.

Official references:

- ATH: <https://www.at-horns.eu/download.html>
- AKABAK: <https://www.randteam.de/AKABAK3/Index.html>
- VACS: <https://randteam.de/VACS/Index.html>
- R&D Team licensing: <https://randteam.de/Commercial/Licenses.html>
- Gmsh: <https://gmsh.info/>

## Project Library audit

The active root is `C:\Users\maximilianheinze\Desktop\WUT Project Library`.
The final read-only structural audit found:

- seven projects in the canonical `library.json` + `library.sqlite` +
  `projects/` layout;
- no root `global.sqlite` and no project with competing preferred/legacy DBs;
- 20 batch folders, 91 version folders and 23 normal run folders across the
  non-empty projects, plus four auxiliary ATH run folders;
- eight copied databases with `PRAGMA quick_check=ok`;
- 37 historical duplicate immutable-plan groups: 28 in P0003 and three each in
  P0005, P0006 and P0007;
- no queued replication records in the inspected database snapshot.

Duplicate history was deliberately retained because versions can own different
runs and exports. The new reuse behavior prevents another equivalent cohort.

The desktop also contains seven February QA/UX/E2E library roots, a detached
`Desktop\projects` container with one old project, and a detached
`Desktop\library.sqlite`. They are inactive candidates, not automatically
classified as disposable. No cleanup or migration was performed.

## Automated validation

Before the final integration-only documentation changes, the repository-wide
suite completed with `622 passed, 10 skipped` in 249.01 s. Focused suites added
during the later work also passed:

- setup/first-run and runtime-state isolation;
- Doctor service/CLI/GUI routing;
- library audit and duplicate-plan detection;
- VACS polling and export coverage;
- compatibility verification and timeout process-tree cleanup;
- 40 compatibility/DSL/UI/fuzz tests.

The definitive post-documentation full-suite result is appended during final
branch integration.

## Residual risks and deliberate non-actions

- ATH can print harmless cleanup notices to stderr after successful output;
  success is determined by exit status and required artifacts, not an empty
  stderr stream.
- The test suite emits a large number of existing Qt/deprecation warnings.
  They are noisy but did not correlate with the reproduced runtime hangs.
- One Windows SQLite temp-cleanup lock appeared once during an earlier full
  suite, then did not reproduce in 48 focused analyzer tests or the next full
  run. No speculative data-layer change was made without a repeatable cause.
- Historical duplicate versions and detached library candidates remain. Any
  destructive deduplication or migration must first define run/export
  ownership and create a recoverable backup.
- Real UI automation remains sensitive to external user interaction. The
  runtime now rejects unsafe pre-existing AKABAK overlap and confines process
  cleanup to PIDs owned by the current stage.

## Operational checks

```powershell
python -m app doctor
python -m app setup status
python -m app library audit --scan-siblings
python -m app compat verify --mode quick --library-root .\tmp\compat-check --no-sql
python -m pytest -q
```

For reproducible real runs, use an isolated Project Library, close unrelated
AKABAK/VACS instances first, keep the desktop session unlocked and inspect the
per-run `pipeline.stage_debug.jsonl` plus AKABAK solve heartbeats before
classifying a long solve as hung.

## Final integration record

Pending final full-suite validation and the content-preserving archived-main
history merge.
