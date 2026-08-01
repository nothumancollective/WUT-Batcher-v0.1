from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.cfg_renderer import render_cfg_text
from app.runners import AthRunner, parse_ath_dimensions
from app.runtime_orchestrator import _write_runtime_ath_cfg


OFFICIAL_DEMO1 = """; ATH 4.8.2 User Guide, section 6.1, pages 27-28
Throat.Profile = 1
Throat.Diameter = 25.4
Throat.Angle = 7
Coverage.Angle = 45
Length = 100
Term.s = 0.5
Term.n = 4.0
Term.q = 0.996
Morph.TargetShape = 0
Mesh.AngularSegments = 64
Mesh.LengthSegments = 20
Mesh.ThroatResolution = 4.0
Mesh.InterfaceResolution = 8.0
Mesh.InterfaceOffset = 5.0
Output.STL = 1
Output.ABECProject = 0
"""

PARAMETERS: dict[str, float | int] = {
    "Throat.Profile": 1,
    "Throat.Diameter": 25.4,
    "Throat.Angle": 7,
    "Coverage.Angle": 45,
    "Length": 100,
    "Term.s": 0.5,
    "Term.n": 4.0,
    "Term.q": 0.996,
    "Morph.TargetShape": 0,
    "Mesh.AngularSegments": 64,
    "Mesh.LengthSegments": 20,
    "Mesh.ThroatResolution": 4.0,
    "Mesh.InterfaceResolution": 8.0,
    "Mesh.InterfaceOffset": 5.0,
}

ASSIGN_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*([^;]*?)\s*$")
VERTEX_RE = re.compile(
    r"^\s*vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*$",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assignments(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = ASSIGN_RE.match(line)
        if match:
            result[match.group(1)] = match.group(2).strip()
    return result


def _semantic(value: str) -> str | float:
    try:
        return float(value)
    except ValueError:
        return value.strip().strip('"').strip("'")


def _stl_vertices(path: Path) -> tuple[int, list[tuple[float, float, float]]]:
    raw = path.read_bytes()
    if raw.startswith(b"$MeshFormat"):
        return _gmsh22_binary_vertices(path, raw)
    if len(raw) >= 84:
        count = struct.unpack_from("<I", raw, 80)[0]
        if len(raw) == 84 + 50 * count:
            vertices = []
            for facet in range(count):
                offset = 84 + facet * 50 + 12
                vertices.extend(struct.unpack_from("<3f", raw, offset + vertex * 12) for vertex in range(3))
            return count, sorted(vertices)
    vertices = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        match = VERTEX_RE.match(line)
        if match:
            vertices.append(tuple(float(match.group(index)) for index in (1, 2, 3)))
    if not vertices or len(vertices) % 3:
        raise RuntimeError(f"Unsupported or malformed STL: {path}")
    return len(vertices) // 3, sorted(vertices)


def _gmsh22_binary_vertices(
    path: Path, raw: bytes
) -> tuple[int, list[tuple[float, float, float]]]:
    """Read the binary Gmsh 2.2 payload ATH may emit with an .stl suffix."""

    def line_after(marker: bytes) -> tuple[bytes, int]:
        marker_start = raw.find(marker)
        if marker_start < 0:
            raise RuntimeError(f"Missing {marker!r} in {path}")
        start = raw.find(b"\n", marker_start) + 1
        end = raw.find(b"\n", start)
        if start <= 0 or end < 0:
            raise RuntimeError(f"Malformed line after {marker!r} in {path}")
        return raw[start:end].strip(), end + 1

    node_count_raw, cursor = line_after(b"$Nodes")
    node_count = int(node_count_raw)
    vertices: list[tuple[float, float, float]] = []
    node_record = struct.Struct("<i3d")
    for _ in range(node_count):
        _tag, x, y, z = node_record.unpack_from(raw, cursor)
        cursor += node_record.size
        vertices.append((x, y, z))

    element_count_raw, cursor = line_after(b"$Elements")
    element_count = int(element_count_raw)
    consumed = 0
    triangle_count = 0
    while consumed < element_count:
        element_type, block_count, tag_count = struct.unpack_from("<3i", raw, cursor)
        cursor += 12
        node_count_by_type = {
            1: 2, 2: 3, 3: 4, 4: 4, 5: 8, 6: 6, 7: 5,
            8: 3, 9: 6, 10: 9, 11: 10, 15: 1,
        }
        if element_type not in node_count_by_type:
            raise RuntimeError(f"Unsupported Gmsh element type {element_type} in {path}")
        integers_per_element = 1 + tag_count + node_count_by_type[element_type]
        cursor += 4 * integers_per_element * block_count
        consumed += block_count
        if element_type == 2:
            triangle_count += block_count
    return triangle_count, sorted(vertices)


def _bounds(vertices: list[tuple[float, float, float]]) -> dict[str, list[float]]:
    return {
        axis: [min(point[index] for point in vertices), max(point[index] for point in vertices)]
        for index, axis in enumerate("xyz")
    }


def _run_case(root: Path, cfg_text: str, ath: Path) -> dict[str, Any]:
    work = root / "work"
    output = root / "output"
    logs = root / "logs"
    work.mkdir(parents=True)
    cfg_path = work / "demo1.cfg"
    cfg_path.write_text(cfg_text, encoding="utf-8")
    runtime_cfg = _write_runtime_ath_cfg(
        ath_work_dir=work,
        ath_export_root=output,
        ath_executable=ath,
    )
    result = AthRunner(ath).run_cfg(cfg_path, version_logs_dir=logs, workdir=work)
    stdout = Path(result.stdout_log).read_text(encoding="utf-8", errors="replace")
    dimensions = parse_ath_dimensions(stdout)
    stl_files = sorted(output.rglob("*.stl"))
    if len(stl_files) != 1:
        raise RuntimeError(f"Expected one STL below {output}, got {stl_files}")
    facet_count, vertices = _stl_vertices(stl_files[0])
    return {
        "cfg_path": str(cfg_path),
        "cfg_sha256": _sha256(cfg_path),
        "runtime_cfg": runtime_cfg,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "stdout_log": result.stdout_log,
        "stderr_log": result.stderr_log,
        "dimensions_mm": {
            "width": dimensions.horn_width_mm,
            "height": dimensions.horn_height_mm,
            "length": dimensions.horn_length_mm,
            "source": dimensions.raw_line,
        },
        "stl_path": str(stl_files[0]),
        "stl_sha256": _sha256(stl_files[0]),
        "facet_count": facet_count,
        "vertex_count": len(vertices),
        "bounds_mm": _bounds(vertices),
        "vertices": vertices,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ath", type=Path, default=Path(r"C:\Tools\ATH\ath.exe"))
    args = parser.parse_args()
    root = args.output_root.resolve()
    if root.exists():
        raise RuntimeError(f"Refusing to overwrite {root}")
    root.mkdir(parents=True)

    rendered = render_cfg_text(OFFICIAL_DEMO1, PARAMETERS, "official_demo1")
    direct = _run_case(root / "standalone", OFFICIAL_DEMO1, args.ath)
    wut = _run_case(root / "wut_rendered", rendered, args.ath)
    direct_vertices = direct.pop("vertices")
    wut_vertices = wut.pop("vertices")
    if len(direct_vertices) != len(wut_vertices):
        coordinate_error = None
    else:
        coordinate_error = max(
            abs(left[axis] - right[axis])
            for left, right in zip(direct_vertices, wut_vertices)
            for axis in range(3)
        )

    source_assignments = _assignments(OFFICIAL_DEMO1)
    rendered_assignments = _assignments(rendered)
    mismatches = {
        key: {"source": source_assignments[key], "rendered": rendered_assignments.get(key)}
        for key in source_assignments
        if key not in rendered_assignments
        or _semantic(source_assignments[key]) != _semantic(rendered_assignments[key])
    }
    additions = sorted(set(rendered_assignments) - set(source_assignments))
    expected_additions = ["ABEC.AkabakMode", "LE", "LE.Voltage"]
    guide_dimension_pass = all(
        abs(float(case["dimensions_mm"][axis]) - expected) <= 0.05
        for case in (direct, wut)
        for axis, expected in (("width", 269.4), ("height", 269.4), ("length", 100.0))
    )
    geometry_pass = (
        direct["facet_count"] == wut["facet_count"]
        and direct["vertex_count"] == wut["vertex_count"]
        and coordinate_error is not None
        and coordinate_error <= 1.0e-9
    )
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "title": "ATH 4.8.2 User Guide",
            "path": r"C:\Tools\ATH\doc\Ath-4.8.2-UserGuide.pdf",
            "sha256": _sha256(Path(r"C:\Tools\ATH\doc\Ath-4.8.2-UserGuide.pdf")),
            "sections": ["6.1 pages 27-28", "6.2 page 29"],
            "reported_dimensions_mm": {"width": 269.4, "height": 269.4, "length": 100.0},
        },
        "ath": {"path": str(args.ath.resolve()), "sha256": _sha256(args.ath)},
        "standalone": direct,
        "wut_rendered": wut,
        "comparison": {
            "semantic_assignment_mismatches": mismatches,
            "additional_active_assignments": additions,
            "expected_additional_assignments": expected_additions,
            "max_sorted_coordinate_abs_error_mm": coordinate_error,
            "guide_dimension_pass": guide_dimension_pass,
            "geometry_equivalence_pass": geometry_pass,
            "assignment_contract_pass": not mismatches and additions == expected_additions,
        },
    }
    payload["status"] = "verified" if all(
        (
            direct["exit_code"] == 0,
            not direct["timed_out"],
            wut["exit_code"] == 0,
            not wut["timed_out"],
            guide_dimension_pass,
            geometry_pass,
            not mismatches,
            additions == expected_additions,
        )
    ) else "failed"
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest), "status": payload["status"], "comparison": payload["comparison"]}, indent=2))


if __name__ == "__main__":
    main()
