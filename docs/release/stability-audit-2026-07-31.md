# Stability and integration audit — 2026-07-31

Status: implementation complete; final full-suite validation and synchronized
`main` integration are recorded at the end of this document.

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
- accepted changes were kept in small commits; final `main`/`origin/main`
  synchronization is recorded below.

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
| Native AKABAK import | Global UIA discovery, unsafe button retries and applying before the import report settled caused hangs or a real AKABAK access violation. A later native control reference also escaped into JSON diagnostics. | Scope discovery and modals to process-owned HWNDs, bound native messages, verify importer activity, require a complete stable report and persist only the control handle (`57a55c7`, `3c07775`, `77fa566`, `f6286d0`, `5cca792`). |
| Successful VACS handoff | The service asked the AKABAK driver to perform its default close even after a successful solve. That close correctly removed the owned VACS process before the following export stage could use it. | Preserve the solved VACS instance only across the successful AKABAK-to-export boundary; timeout and failure paths retain strict cleanup (`71332f0`). |
| Windows process output | Localized `tasklist` output occasionally contained byte `0x81`, which CP1252 cannot decode and which crashed subprocess reader threads during polling. | All high-frequency AKABAK/runtime process queries now decode with replacement at the diagnostic boundary (`5cca792`, `71332f0`). |
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
- Definitive five-repeat run on commit `71332f0`: 5/5 successful in 332.18 s
  wall time, with individual toolchain times of 41.03, 41.16, 41.31, 41.85
  and 41.03 s. The DB records 20 graphs, 120 points, 65/65 passing
  validations, 40 TXT files and the exact tested commit for every run.
- Real service batch after strict graph coverage/path staging: run
  `75e1bc08-576e-4ac6-9d16-2c652f69a1d7`, 5/5 versions successful. Each version
  produced H, V, D and radiation-impedance data with 40 frequency points and
  eight files (four raw plus four normalized exports).
- Post-timeout-fix single run:
  `007cd807-6637-4ca9-a510-b18d827cbd22`, success in 70.1 s. All seven stages
  passed; AKABAK heartbeats showed actual progress; four graphs/eight files
  were preserved; process and temporary-stage cleanup completed.
- Final service-handoff regression run
  `13b5ffcd-39dd-4320-86af-f5f5efb30cba`: all seven stages passed in
  192.84 s. It produced four graphs, 40 DB points and eight non-empty TXT
  files; stderr was empty and no tool process survived.

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

The final rerun on commit `71332f0` deliberately repeated the same two
materialized heavy variants after two additional real failures exposed the
native-diagnostic serialization and successful-VACS-handoff defects. The
definitive run was `fc00ac81-cc09-4fa6-8ce6-58cb78153f99`:

- 333.91 s wall time, return code 0 and `run_status=succeeded`;
- 14/14 stages `ok`, zero failed or timed-out stages;
- V001 and V002 both persisted with status `success`;
- eight current-run graphs and 256 graph points in the project DB;
- per version, three 59-line polar exports and one 61-line impedance export,
  each retained both raw and normalized (eight TXT files per version);
- two current-run ATH dimension rows reported by the runtime summary;
- empty stderr and no ATH, Gmsh, AKABAK or VACS process afterward.

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

- eight projects in the canonical `library.json` + `library.sqlite` +
  `projects/` layout;
- no root `global.sqlite` and no project with competing preferred/legacy DBs;
- 22 batch folders, 93 version folders and 25 normal run folders across the
  non-empty projects, plus five auxiliary ATH run folders;
- the original seven-project snapshot's eight copied databases passed
  `PRAGMA quick_check=ok`; the final structural audit found all nine expected
  database paths and zero errors;
- 37 historical duplicate immutable-plan groups: 28 in P0003 and three each in
  P0005, P0006 and P0007;
- no queued replication records in the inspected database snapshot.

Duplicate history was deliberately retained because versions can own different
runs and exports. The new reuse behavior prevents another equivalent cohort.

The sibling scan returns nine marker candidates: the active root, seven
February QA/UX/E2E roots, and the detached `Desktop\projects` container. It
also reports detached `Desktop\library.sqlite` as one index candidate. Inactive
candidates are not automatically classified as disposable. No cleanup or
migration was performed.

## Automated validation

Before the final native fixes, repository-wide checkpoints completed with
`622 passed, 10 skipped` and later `666 passed, 10 skipped`. Focused suites
added during the later work also passed:

- setup/first-run and runtime-state isolation;
- Doctor service/CLI/GUI routing;
- library audit and duplicate-plan detection;
- VACS polling and export coverage;
- compatibility verification and timeout process-tree cleanup;
- 40 compatibility/DSL/UI/fuzz tests.

The definitive suite on commit `71332f0` completed with `670 passed, 10
skipped` in 243.00 s (269.5 s shell wall time). Its 9,235 warnings are all the
known Qt `QTableWidgetItem.setTextAlignment(int)` deprecation warnings; no new
runtime, resource or process warning was emitted.

## Residual risks and deliberate non-actions

- ATH can print harmless cleanup notices to stderr after successful output;
  success is determined by exit status and required artifacts, not an empty
  stderr stream.
- The test suite emits a large number of existing Qt/deprecation warnings.
  They are noisy but did not correlate with the reproduced runtime hangs.
- A Windows SQLite temp-cleanup lock first appeared transiently, then recurred
  on the exact final-commit suite. The repeated cause and correction are
  recorded in the 2026-08-01 follow-up below.
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

The content-preserving merge is `48c1869` with parents `e29f827` (validated
product tree plus evidence) and `532a351` (archived `main`). Its tree hash
`5f502fc6cba1d0b6ca1e5ecd0c316d6c92acb35a` is identical to the pre-merge
`e29f827` tree, so the history reconnect changed no product file.

The former local `main` is recoverable as tag
`archive/main-pre-20260731 -> 532a351`. Local `main` was moved to `48c1869`
and this documentation-only integration record was then committed on `main`.
The project-manager (`c5e6860`), batch-lineage (`0850f67`) and archived-main
heads are all ancestors of the resulting branch. Historical branches were
retained and the working tree was clean. That first integration step was local;
the accepted follow-up commits were subsequently synchronized to
`origin/main`.

## 2026-08-01 follow-up hardening

This addendum records the application-cold/warm repeats, the actual VM-reboot
repeat, and the additional faults found while making those repeats
deterministic. A reboot does not erase the persisted VACS user profile; a truly
fresh Windows/VACS profile remains a separate external validation point.

### Additional root causes and commits

| Area | Reproduced failure | Correction |
| --- | --- | --- |
| Late AKABAK startup popup | `TForm_ExampleFiles` could reappear after import and outlive the original startup-modal phase. | Close the exact process-owned class after import as well (`c538f60`). |
| LE coupling | The smoke case could inherit an unstable or incomplete driver/coupling definition. | Pin and apply the verified LE repair/coupling profile (`e846e72`, `ab2db9f`). |
| Solve-to-VACS timing | VACS could be requested before AKABAK had stably returned from a solve; slow post-processing exhausted the re-import budget. | Require stable reactivation, keep retry budget after solve, and use bounded delayed re-imports (`8f708f0`, `fc50907`, `f4ce113`, `f4a34f7`, `43439d6`, `4c338de`). |
| Invalid acoustic success | An all-zero acoustic export could pass structural checks. | Reject unclassified zero-valued acoustic output (`eee4aab`). |
| Localized Save As | German modern `Speichern unter` dialogs appeared before their filename edit was discoverable; the fallback could press Save without proving the requested path. | Recognize localized dialogs, retry exact Win32/UIA filename discovery, and never confirm until the path is set (`da2cf53`, `c17200f`, `895b4e9`, `155bb64`). |
| Native serialization | Concurrent harness/service runs could contend for single-instance AKABAK/VACS and COM state. | Serialize native pipelines and the E2E harness across processes (`dd355f6`, `7fca36d`). |
| Process handles and cleanup | A transient process handle could be closed too early; successful `taskkill` could be reported failed while the exact PID was still exiting. | Preserve native handles and poll the exact PID after termination (`7499d95`, `d206db4`). |
| Cleanup ownership | Helper cleanup still contained broad or baseline-delta behavior. | Retain only run-owned VACS cleanup and remove global helper kills (`be87a64`, `9887148`). |
| Doctor write safety | Normal CLI/GUI Doctor runs wrote a fixed `.doctor_write_test` file even without `--fix`; the legacy kill option used image-wide `taskkill /IM`. | Default checks are read-only, active probes use unique temporary names only with `--fix`, and unowned name-wide cleanup is refused (`cb0fd7c`, `e0a1897`). |
| Slow solve window lifecycle | AKABAK could recreate or hide its main/solve window after import or during long progress polling. | Refresh recreated solve-window identities and restore the exact hidden process-owned main window (`85e1671`, `0a587e2`). |
| Harness resource timeout | The heavier V002 case reached the old 1,200 s hard limit while CPU time and heartbeats still advanced. | Keep product/UI defaults unchanged, but set the `resource` harness profile to 20 minutes inactivity / 40 minutes hard limit and verify forwarding in fast tests (`9bc68f2`). |
| UI stress fixture | The fake LE fixture contained literal `\\n` tokens and was correctly rejected by the hardened driver guard. | Emit real line breaks in the fixture without weakening production validation (`4d2dbe4`). |
| Analyzer database handle | The SQLite context manager completed transactions but did not guarantee immediate native-handle closure on Windows; two full suites exposed temporary project cleanup locks. | Explicitly close the plot-loader connection and enforce that contract in a regression test (`d9e4563`). |
| Post-solve VACS budget | A completed AKABAK solve could still be reported as a solve timeout while the separately bounded VACS handoff was slow. | Isolate the post-solve VACS timeout from solve progress (`674a8a7`). |
| Analyzer curve semantics | One-sided beamwidth arrays could be paired with the wrong frequency axis, while impedance traces could enter pressure-polar selection and a delayed clear reset the chosen target color. | Align one-sided axes, isolate pressure from impedance, and preserve the target-color preference (`334515a`, `9402802`, `315005d`). |
| Generated CFG robustness | UTF-8 BOMs could leak into rendered ATH input, and long project-scoped CFG names consumed the remaining Windows/VACS path budget. | Strip BOMs before rendering and shorten project-scoped CFG names (`af3170c`, `009ff04`). |
| Qt UI/test lifecycle | A lineage hover passed the wrong Qt point type; fixed-duration animation waits and unclosed top-level Analyzer pages made combined suites load-sensitive and could end in `0xC0000409`. | Convert the hover point explicitly, poll animation completion, and close pages during teardown (`8fba634`, `43aa4aa`, `cc3e631`). |
| Settings-test isolation | A GUI regression fixture could replace the real user settings profile while trying to isolate it. | Redirect settings through the supported isolated override without touching the profile (`f2a72b8`). |
| Legacy VACS path budgets | The old Save As dialog needs a conservative 240-character interaction path, but applying that same cap to the final Windows destination rejected valid paths. | Keep the dialog-stage cap at 240 and allow final paths up to the Windows 259-character boundary (`0426a87`). |

### Final runner-harness evidence

The bounded `resource` profile added in `39e00d7` uses 28 angular by 18
length segments, throat/mouth/rear resolutions 14/26/32, and eight frequency
points from 600 Hz to 6 kHz. Commit `9bc68f2` gives this profile a 20-minute
inactivity budget and a 40-minute hard limit. The `baseline` profile applies
no geometry/frequency overrides and retains the ten-minute timeout; the
general product default and UI were not changed.

Resource repeat workspace:
`tmp/real_e2e_native_akabak_20260801_root_d206db4_resource2_final_r1`.

- two of two runs succeeded on exactly `d206db4`;
- individual toolchain times: 139.61 s and 231.22 s;
- 26/26 steps and 26/26 validations were `ok`;
- eight graphs, eight series, 64 points and 32 artifacts were persisted;
- each run exported and verified 4/4 current VACS graphs;
- exact VACS PIDs 7460 and 9592 were terminated, with no cleanup failure;
- 23 resource snapshots recorded up to 100% CPU; free physical memory stayed
  between 1775.4 and 2417.2 MB;
- the wrapper returned 0 and the post-exit native-tool list was empty.

Uniform release-repeat workspace:
`tmp/real_e2e_native_akabak_20260801_root_d206db4_fast5_release_g1`.

- five of five runs succeeded on exactly `d206db4` (no mid-batch commit drift);
- individual toolchain times: 129.80, 114.65, 185.64, 130.19 and 122.71 s;
- 65/65 steps and 65/65 validations were `ok`;
- 20 graphs, 20 series, 120 points and 80 artifacts were persisted;
- all 20 VACS exports were present, non-empty and verified; every export
  summary reported 4 successful and zero failed graphs;
- exact VACS PIDs 12628, 8940, 10020, 8080 and 12676 were terminated with no
  cleanup failure;
- 41 resource snapshots recorded 51-100% total CPU and 1783.7-2389.2 MB free
  physical memory; free memory was 2155.6 MB before and 2389.2 MB after;
- wrapper return code was 0, status was `clean_exit`, and both the guarded
  post-exit ledger and an independent CIM query found zero native tool
  processes.

Visible captures during these gates showed the expected horn meshes, six or
eight requested frequency rows, active percentage progress, and final AKABAK
`Ready / 100%` with all solve phases green. Long runs were classified by
heartbeats, CPU-time growth and visible progress rather than wall time alone.

After the VM reboot, two additional isolated native runs on `6f720f3` repeated
the complete ATH -> Gmsh/ABEC -> AKABAK -> VACS path:

- `tmp/real_e2e_post_reboot_20260801_6f720f3`: V001 succeeded in 73.25 s,
  both requested exports were verified, exact VACS PID 9552 was terminated,
  and no native process remained;
- `tmp/real_e2e_post_reboot_20260801_6f720f3_vacs_visible`: V001 succeeded in
  366.09 s, both requested exports were verified, exact VACS PID 4484 was
  terminated, and no native process remained. AKABAK heartbeats and CPU time
  advanced for roughly 275 s before the visible VACS handoff, confirming a slow
  healthy solve rather than a hang;
- the visible evidence is retained as
  `tmp/screen_6f720f3_post_reboot_e2e.png` and
  `tmp/screen_6f720f3_post_reboot_vacs_foreground.png`; the latter shows the
  expected Mic Polar and Radiation Impedance graph windows.

An additional heavier service scenario is preserved under
`tmp/real_service_heavy2_e0a1897_20260801_r3`. It used a 72-by-28 mesh,
32 frequencies from 400 Hz to 16 kHz, two 90/120 mm versions, H/V/D plus
impedance, and the then-current ten-minute setting (600 s inactivity,
1,200 s hard limit):

- V001 completed in 999.26 s, exported four current VACS graphs, and persisted
  four graphs/series, 128 points and eight files;
- V002 continued to emit progress heartbeats and accumulate AKABAK CPU time up
  to the old 1,200 s hard limit, then timed out in a controlled manner;
- the scenario therefore returned 2 and is **not** reported as two of two
  successful; its true result is V001 success, V002 old-budget timeout;
- the owned VACS/AKABAK processes were cleaned and the recorded final native
  count was zero.

No completed post-budget Heavy-2 retest is claimed. Several V002-only attempts
after the budget increase were terminated outside the product pipeline by the
execution backend (including a wrapper/shell reap near 896 s and a scheduled
task status `0xffffffff`). The 282.84 s `674a8a7` artifact and later
`85e1671`/`0a587e2` attempts are therefore aborted non-gates: they prove
neither product success nor product failure. Repeating the same long helper
again risked another uncontrolled orphan, so the evidence remains the V001
success, the controlled old-budget V002 timeout, progressing heartbeats/CPU,
and passing focused tests for timeout forwarding and hard-limit arithmetic.

### Process-hygiene invariant

Every real test must start and end with an explicit process/resource snapshot.
Ownership requires exact PID, executable path, parent relation and start time;
parent/child creation order is checked so Windows PID reuse cannot create a
false tree. Only owned PIDs may be terminated. Unknown/manual native tools
block the next test, and global image-name cleanup is prohibited.

One separately launched Heavy-2 service process overlapped an early Pytest
attempt after the native release gate had already finished. It started 53
seconds after the Fast-5 post-exit snapshot, so it did not contaminate that
gate, but it held the native serialization lock and reduced free RAM. The fake
LE fixture was corrected independently. A Windows SQLite cleanup lock later
recurred without native-tool overlap, which made the plot-loader handle leak a
repeatable cause rather than a one-off; `d9e4563` closes it explicitly.

The definitive clean suite on `d9e4563`, with no native process or Heavy
wrapper in the pre-state, completed with 725 passed, 10 skipped and zero
failures in 693.89 s. A later same-product-tree repeat completed with the same
725/10 result in 597.50 s.

The final Stable-HEAD gate on `5f4c6cf` completed with **735 passed, 10 skipped
and zero failures in 851.10 s**. Pytest returned 0; HEAD and the clean worktree
were identical before and after; the final WUT-GUI/ATH/Gmsh/AKABAK/VACS counts
were all zero. A narrowly scoped watcher stopped one independently launched
`pythonw -m app gui` (PID 12700, parent 12508) 72 s after test start; it matched
no other process and prevented the recurring external debug launcher from
contaminating this repeat. The wrapper wall time was 959.21 s. The 9,235
warnings are the existing Qt `QTableWidgetItem.setTextAlignment(int)`
deprecations.

### Setup, Doctor and library follow-up

`setup status` reports ready with no missing key and reuses all four installed
tools. ATH, AKABAK and VACS remain manual-link installations with license
summaries; Gmsh remains explicit opt-in Winget only. Nothing was installed or
reconfigured.

The final 2026-08-01 structural audit found eight canonical projects, zero
errors and 37 historical `duplicate_version_plan` warnings. P0008 contains one
batch, one version and one run with no duplicate warning; the next project
counter is 9. The audit listed nine sibling candidates and one detached index
without inferring authority or changing them. SHA-256, length and timestamps of
`library.json` and `library.sqlite`, plus the library-root timestamp, were exact
before and after. No migration, deletion or deduplication was performed.

The pre-fix Doctor invocation created and deleted its fixed probe in the active
library, changing only the root directory timestamp to
`2026-08-01T08:19:36.5127719Z`; no probe file or project-data change remained.
The real post-fix check left that timestamp byte-for-byte unchanged and
reported that the active write probe was skipped. Doctor process reporting
also treats an unowned AKABAK/VACS instance as contamination and never kills
it by image name.

### VACS first-process-start boundary

The two known startup notes are exact `TForm_Editor` children sourced from
`Vacs_Welcome.rtf` and `VACSVIEWER.rtf`. Their `Skip this note next time` links
persist `Skip_WelcomeScript` and `Skip_VacsViewerScript`, respectively, but the
already-open editor must still be closed. They are not COM-registration
dialogs. The application-cold and warm repeats in the current Windows session
showed no such editors and reached four graphs directly. A truly fresh
VM/profile first VACS session remains a documented external validation point,
not a blocker for this release.

### Scientific validation boundary

The reproducible ATH contract probe and evidence are recorded in
`docs/validation/SCIENTIFIC_VALIDATION_2026-08-01.md` and
`docs/validation/evidence/ath_contracts_2026-08-01.json` (`5f4c6cf`). Six
standalone ATH cases exited 0 without timeout. They verify length and throat
transfer, required physical groups, quarter-model coordinate signs and normal
orientation, and ordered mesh-density controls. They do not yet prove mouth or
profile transfer, mesh convergence, standalone-vs-WUT solver-result equality,
observation numerics, VACS complex round-trip/DB losslessness, or Analyzer
golden-value correctness; those items remain explicitly unvalidated or
plausibilized rather than being inferred from stability alone.

### Final branch state

At the final code gate, `main` and `origin/main` both pointed to `5f4c6cf` and
the worktree was clean. Of 51 inspected non-main refs, every product, UI,
analyzer, storage, cleanup, integration and scientific-validation ref was an
ancestor of `main`. Only the intentionally historical `audit/2026-02-20` and
`audit/2026-02-21-legacy-census` refs (local and remote) were not ancestors.
The former main remains recoverable as
`archive/main-pre-20260731 -> 532a351`.
