# Capability Check (Phase 0)

Date: 2026-02-13  
Branch: `wut-batcher/rebuild`

## 1) Repo Reality Check

### AKABAK control
- `app/akabak_driver.py` exists and uses UIA session abstraction (`app/ui_automation/session.py`).
- Session is UIA-first (`pywinauto` with `backend="uia"`) with optional `uiautomation` fallback.
- Driver includes stateful methods (`open_project`, `run_solve`, `wait_for_completion`, `close`) and watchdog integration.
- Current runtime path (`app/runtime_orchestrator.py`) does **not** use this driver yet; it still uses subprocess runner (`AkabakRunner.run_project` in `app/runners.py`).

Verdict: **partial**.

### VACS export control
- `app/vacs_driver.py` exists with recipe loading (`ui_recipes/vacs/*.json`) and UIA actions (`open_results`, `open_graph`, `export_txt`).
- UI contracts exist (`app/ui_contracts/window_signatures.py`), recipe validator exists (`app/ui_automation/recipes.py`), inspector CLI exists (`ui inspect-akabak|inspect-vacs`).
- Current runtime path (`app/runtime_orchestrator.py`) does **not** use `VacsDriver`; it still launches VACS as subprocess (`VacsRunner.run_export`), then ingests whatever `*.txt` exists.

Verdict: **partial**.

### UI contracts / selectors / maps
- Present:
  - window signatures (`app/ui_contracts/window_signatures.py`)
  - recipes (`ui_recipes/vacs/*.json`)
  - modal watchdog (`app/ui_automation/watchdog.py`)
  - discovery commands (`python -m app ui inspect-akabak|inspect-vacs`)
- Missing as stable source-of-truth:
  - versioned `ui_maps` checked into repo for current AKABAK/VACS builds
  - graph catalog mapping by VACS version (`ui_maps/vacs/<version>/graph_catalog.json`)

### Actually proven end-to-end export types today
- Runtime ingestion currently proves only: “TXT files found in export folder are parsed and stored”.
- Parser fixtures currently include simple 1D examples (`SPL`, `IMP`) in `tests/fixtures/vacs/`.
- There is currently no runtime-guaranteed UIA graph-open/export flow bound to user-selected export semantics.

## 2) Missing artifacts/info for stable foreground E2E
- Real `ui_maps` captures for installed AKABAK/VACS versions (control identifiers + dialogs).
- Stable mapping from user export intent -> recipe/selector contract (currently implicit).
- Known modal dialog inventory + whitelist/recovery rules from real runs.
- Versioned graph catalog for VACS (graph_kind/variant/options -> selectors/export signatures).
- Runtime integration switch from subprocess-only to driver-based foreground orchestration.

## 3) Minimal next step to reach stable foreground mode
1. Capture `ui_maps` on this VM with real tools (`ui inspect-akabak`, `ui inspect-vacs`) and freeze versioned selectors.
2. Introduce semantic `ExportSpec` selection and map it to recipe IDs via a versioned VACS graph catalog.
3. Wire runtime to `AkabakDriver` + `VacsDriver` for one narrow supported path first (e.g. SPL TXT), fail-fast on unmapped specs.
4. Keep strict postconditions: expected file pattern must exist, otherwise explicit error + remediation hint.
