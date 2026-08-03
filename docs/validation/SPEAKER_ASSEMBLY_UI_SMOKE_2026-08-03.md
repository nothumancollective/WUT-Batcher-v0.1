# SpeakerAssembly visible UI smoke - 2026-08-03

## Scope and isolation

- Branch baseline: `df8ed555761c954469a87490471dc08dce205ea0`.
- Feature commits under test: `2a7770e`, `477e82f`, `979d45e` plus the final
  documentation commit.
- UI path: Project -> Geometry -> Speaker Assemblies.
- An isolated temporary settings file and library under
  `tmp/speaker_assembly_smoke_20260803` were used. No production library data,
  solver preferences, registry entry or external installation was changed.
- The smoke-owned Python GUI was PID 9876 and exited normally. A separate
  pre-existing user debug GUI (PID 6064) was identified and deliberately left
  untouched. No process-name cleanup was used.

## On-screen operations and result

The visible Qt UI created Assembly
`SA-0ae32cdd-a66b-4c53-823c-de74421b2dd7` with two instances. It then closed
and reopened the manager, edited the second instance, moved it above the first,
closed and reopened again, and verified the persisted order and values.

| Order | Instance | Arrangement | Translation (m) | Rotation (deg) |
|---:|---|---|---|---|
| 0 | Coaxial offset instance | coaxial | (0.035, 0.020, 0) | (12.5, 0, 0) |
| 1 | Normal mid instance | normal | (0, 0, 0) | (0, 0, 0) |

Both instances referenced Geometry
`G-5fb2911d-fdf6-4582-9584-3549c43e13eb`. Their canonical immutable Geometry
snapshot hash was
`c56fb51f11aa42b6c916bc88bf583bf3be5bd019fb095436d869066bab1dfef9`.
The final `assembly.json` SHA-256 was
`8760acd332a088ff3d13e9b9792190df4fd370104ba536a58357ebc72b95e9dd`.

The edit changed only placement metadata. Reopening showed the unchanged
Geometry snapshot hash, confirming that the service does not silently
re-snapshot a Geometry for a pure instance edit. The final JSON retained stable
instance IDs and compact order indexes 0 and 1.

## Acceptance

Passed: real navigation, create, add two instances, normal/coaxial selection,
non-trivial SI transform, save, reload, edit, reorder, second reload and normal
process exit. Native ATH/AKABAK/VACS execution was intentionally omitted because
SpeakerAssembly is not coupled to the validated Runner in this milestone.
