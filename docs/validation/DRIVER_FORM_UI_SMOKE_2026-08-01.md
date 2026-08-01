# Driver form UI smoke — 2026-08-01

## Scope and isolation

- Baseline: `ec7ac7d2c27e451ecab6f9c6c8cb0bf91a1f7a97`
- Branch: `codex/driver-form-editor-2026-08-01`
- Isolated settings: `tmp/driver_ui_smoke_2/settings.json`
- Isolated library: `tmp/driver_ui_smoke_2/library`
- No ATH, AKABAK or VACS run was started because runner code was unchanged.

The GUI process was started from this feature worktree and owned as PID 13592.
The temporary library and source LE file were outside version control. The
application was closed normally and the owned PID no longer existed afterward.

## Visible workflow and result

The normal Project → Geometries & Drivers → Driver Library path was used in a
visible 1920×1032 Windows session. The custom Compression form was exercised in
a 720×680 window. Its grouped fields remained reachable through scrolling.

1. Created user driver `Custom | Smoke Model` through the form.
2. Selected `smoke_driver.le` through the Qt file picker.
3. Preview showed 42 bytes and SHA-256
   `63494ce2c4663a79b8296db282bf6e2b0cf904ba355077562136cfea6b2f547d`.
4. Saved revision 1 as simulation-ready.
5. Created revision 2 without replacing the LE file. The library showed two
   revisions and retained the same content hash.
6. Selected revision 2 in the Geometry default-driver selector. It appeared
   immediately as `ready`; the status displayed the LE file and full hash.
7. Persisted the selection with **Set Default Driver**, then opened the Geometry.
   The dashboard status changed to the selected Geometry ID.

Afterward, the original source file still existed with 42 bytes and the same
SHA-256. This confirms that the UI/service path copied rather than moved it.

## Picker regression found and fixed

The first isolated visible attempt exposed a nested-dialog deadlock in the
native Windows file picker: the WUT window became non-responsive. Only that
owned GUI PID was stopped. The picker now explicitly uses Qt's non-native dialog
for this nested modal path. The repeat smoke completed the full workflow above.

## Coverage boundary

Automated tests cover Compression and Cone forms, explicit units, absent values,
validation failures, safe LE preview/ingestion, source preservation, revision
and hash behavior, built-in immutability and Geometry assignment. The visible
smoke validates navigation, small-window scrolling, the real picker, revision
creation and Geometry selection. Acoustic simulation behavior was deliberately
not re-tested in this UI-only change.
