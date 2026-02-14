# Range Suggestions v1.3

- Generated: 2026-02-14T15:30:00.653892+00:00
- Based on run groups: pp100k_2100, pp100k_2101, pp100k_2102, pp100k_2103, pp100k_2104, pp100k_2105, pp100k_2106, pp100k_2107, pp100k_2108, pp100k_2109
- Keys: 44

## Largest Width Changes vs v1.2
| key | v1.2_width | v1.3_width | delta |
|---|---:|---:|---:|
| `CircArc.Radius` | 1764.9153 | 1651.5224 | -113.3929 |
| `Morph.TargetHeight` | 1352.7320 | 1355.3003 | +2.5682 |
| `Morph.TargetWidth` | 1333.8945 | 1331.8597 | -2.0348 |
| `Slot.Length` | 162.4763 | 163.1138 | +0.6375 |
| `Mesh.ThroatSegments` | 13.0000 | 12.5000 | -0.5000 |
| `GCurve.Dist` | 558.3356 | 557.8911 | -0.4445 |
| `Length` | 808.8000 | 808.4284 | -0.3716 |
| `Throat.Diameter` | 84.8400 | 84.5048 | -0.3353 |
| `Rot` | 19.1524 | 18.8483 | -0.3042 |
| `GCurve.Width` | 766.4900 | 766.2228 | -0.2672 |
| `Throat.Ext.Length` | 128.5990 | 128.8547 | +0.2558 |
| `Morph.Rate` | 8.6189 | 8.3886 | -0.2303 |
| `Throat.Ext.Angle` | 19.6400 | 19.7387 | +0.0987 |
| `Morph.CornerRadius` | 46.6875 | 46.7590 | +0.0715 |
| `Mesh.RearResolution` | 17.8200 | 17.7578 | -0.0622 |

## Notes
- v1.3 keeps anti-spurious guard: only keys with >=3 run-groups and >=30 successful values per group are included.
- Safe bounds are descriptive envelopes, not hard UI blocks.
