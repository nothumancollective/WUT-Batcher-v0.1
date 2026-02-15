# Toolchain Baseline (test_cfg_baseline)

Date: 2026-02-15

## Command
`python -m app runner-test run --case test_cfg_baseline --repeats 1 --keep-exports true --test-profile fast --ath-exe "C:\Tools\ATH\ath.exe" --akabak-exe "C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe" --vacs-exe "C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe"`

## Latest Run
- `test_run_id`: `15aaccb8-6120-49ed-8b71-74b65c90a3dd`
- `status`: `failed`
- Failure class:
  - `Failed to open project in AKABAK`
  - diagnostics: `runner_test_workspace/logs/15aaccb8-6120-49ed-8b71-74b65c90a3dd/akabak/open_dialog_failure_20260215_172445.json`

## Preflight Baseline
- ATH executable:
  - `C:\Tools\ATH\ath.exe` (exists, executable)
- AKABAK executable:
  - `C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe` (exists, executable)
- VACS executable:
  - `C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe` (exists, executable)
- ATH export root hint:
  - `C:\Horns` (exists, writable)

## Stage Outcomes
- `preflight`: `ok`
- `resolve_case`: `ok`
- `generate_cfg`: `ok`
- `ath`: `ok`
- `post_ath_le_repair`: `ok`
- `pre_akabak_guard`: `ok` (required mesh exists: `input.msh`)
- `akabak open_project`: `failed` (dialog did not close)
- `safe_clean`: `ok` (cfg + ath_out only)

## Important Baseline Signals
- Harness-only fast profile overrides are persisted (`test_profile_applied` validation).
- Post-ATH LE repair assertions are passing:
  - `generic25.txt` copied
  - `Project.abec` patched to `Scriptname_LEScript=generic25.txt`
- Mesh pre-guard is passing (no `ath.msh missing` in this baseline).
