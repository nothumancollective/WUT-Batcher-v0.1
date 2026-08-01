from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.cfg_renderer import render_cfg_text
from app.runners import AthRunner, parse_ath_dimensions
from app.runtime_orchestrator import (
    _apply_sim_export_settings_to_cfg,
    _enforce_output_flag,
    _write_runtime_ath_cfg,
)


CASES: dict[str, dict[str, float | int]] = {
    "mouth_45_n4": {},
    "mouth_60_n4": {"Coverage.Angle": 60},
    "mouth_45_n6": {"Term.n": 6},
}

BASE_PARAMETERS: dict[str, float | int] = {
    "Length": 60,
    "Throat.Profile": 1,
    "Throat.Diameter": 25.4,
    "Throat.Angle": 7,
    "Coverage.Angle": 45,
    "Term.s": 0.5,
    "Term.n": 4,
    "Term.q": 0.996,
    "OS.k": 1,
    "Morph.TargetShape": 0,
    "Mesh.AngularSegments": 48,
    "Mesh.LengthSegments": 20,
    "Mesh.MouthResolution": 18,
    "Mesh.ThroatResolution": 10,
}

SIM_SETTINGS: dict[str, float | int | str] = {
    "freq_start_hz": 800,
    "freq_end_hz": 1600,
    "num_points": 4,
    "mesh_frequency": 1600,
    "simulation_mode": "free_standing",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _latest_generated_dir(output_root: Path) -> Path:
    candidates = [path for path in output_root.iterdir() if path.is_dir()]
    if not candidates:
        raise RuntimeError(f"ATH generated no output directory below {output_root}")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _mesh_payload(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    names: dict[int, str] = {}
    nodes: dict[int, tuple[float, float, float]] = {}
    triangles: list[tuple[int, tuple[int, int, int]]] = []
    index = 0
    while index < len(lines):
        token = lines[index].strip()
        if token == "$PhysicalNames":
            count = int(lines[index + 1])
            for row in lines[index + 2 : index + 2 + count]:
                parts = row.split(maxsplit=2)
                names[int(parts[1])] = parts[2].strip().strip('"')
            index += count + 2
        elif token == "$Nodes":
            count = int(lines[index + 1])
            for row in lines[index + 2 : index + 2 + count]:
                parts = row.split()
                nodes[int(parts[0])] = tuple(float(item) for item in parts[1:4])  # type: ignore[assignment]
            index += count + 2
        elif token == "$Elements":
            count = int(lines[index + 1])
            for row in lines[index + 2 : index + 2 + count]:
                parts = [int(item) for item in row.split()]
                tag_count = parts[2]
                if parts[1] == 2 and tag_count >= 1:
                    node_ids = tuple(parts[3 + tag_count :])
                    if len(node_ids) == 3:
                        triangles.append((parts[3], node_ids))  # type: ignore[arg-type]
            index += count + 2
        index += 1

    if not nodes or not triangles:
        raise RuntimeError(f"Mesh is empty or unsupported: {path}")
    coordinates = list(nodes.values())
    z_min = min(point[2] for point in coordinates)
    z_max = max(point[2] for point in coordinates)
    tol = max(1.0e-7, (z_max - z_min) * 1.0e-7)

    def endpoint_payload(z_value: float) -> dict[str, float | int]:
        selected = [point for point in coordinates if abs(point[2] - z_value) <= tol]
        max_x = max(abs(point[0]) for point in selected)
        max_y = max(abs(point[1]) for point in selected)
        radius = max(math.hypot(point[0], point[1]) for point in selected)
        envelope_radius = max(max_x, max_y)
        return {
            "z_mm": z_value,
            "node_count": len(selected),
            "max_abs_x_mm": max_x,
            "max_abs_y_mm": max_y,
            "max_radial_mm": radius,
            "equivalent_diameter_mm": 2.0 * envelope_radius,
            "equivalent_circle_area_mm2": math.pi * envelope_radius * envelope_radius,
        }

    group_areas: dict[str, float] = defaultdict(float)
    group_counts: dict[str, int] = defaultdict(int)
    for physical_id, node_ids in triangles:
        p0, p1, p2 = (nodes[node_id] for node_id in node_ids)
        u = tuple(p1[axis] - p0[axis] for axis in range(3))
        v = tuple(p2[axis] - p0[axis] for axis in range(3))
        cross = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        name = names.get(physical_id, str(physical_id))
        group_counts[name] += 1
        group_areas[name] += 0.5 * math.sqrt(sum(value * value for value in cross))

    return {
        "mesh_format": lines[1].strip() if len(lines) > 1 else "",
        "node_count": len(nodes),
        "triangle_count": len(triangles),
        "physical_names": names,
        "group_triangle_counts": dict(group_counts),
        "group_area_mm2": dict(group_areas),
        "z_length_mm": z_max - z_min,
        "throat_endpoint": endpoint_payload(z_min),
        "mouth_endpoint": endpoint_payload(z_max),
        "nodes": {str(node_id): list(point) for node_id, point in nodes.items()},
    }


def _artifact_manifest(generated: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in generated.rglob("*") if item.is_file()):
        rows.append(
            {
                "relative_path": path.relative_to(generated).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return rows


_GEO_POINT_RE = re.compile(
    r"^Point\(\d+\)=\{\s*([-+0-9.eE]+),\s*([-+0-9.eE]+),\s*([-+0-9.eE]+),"
)


def _inner_profile_from_geo(path: Path, *, nominal_length_mm: float) -> list[dict[str, float]]:
    """Read ATH's leading inner-horn point rings before the mouth centre point."""
    rings: dict[float, list[tuple[float, float]]] = defaultdict(list)
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _GEO_POINT_RE.match(raw_line.strip())
        if not match:
            continue
        x, y, z = (float(match.group(index)) for index in (1, 2, 3))
        if abs(x) <= 1.0e-9 and abs(y) <= 1.0e-9 and abs(z - nominal_length_mm) <= 1.0e-6:
            break
        rings[z].append((x, y))
    if not rings:
        raise RuntimeError(f"No leading ATH inner-profile rings found in {path}")
    return [
        {
            "z_mm": z,
            "normalized_z": z / nominal_length_mm,
            "radius_x_mm": max(abs(point[0]) for point in points),
            "radius_y_mm": max(abs(point[1]) for point in points),
        }
        for z, points in sorted(rings.items())
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run phase-2 ATH mouth/profile contract probes.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ath", type=Path, default=Path(r"C:\Tools\ATH\ath.exe"))
    parser.add_argument(
        "--template",
        type=Path,
        default=REPO_ROOT / "runner_test_cases" / "templates" / "smoke_fast_min.cfg",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_root = args.output_root.resolve()
    if output_root.exists():
        raise RuntimeError(f"Refusing to overwrite validation root: {output_root}")
    output_root.mkdir(parents=True)
    template_text = args.template.read_text(encoding="utf-8-sig")
    runner = AthRunner(args.ath)
    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": "ac28b3e7c573a8c1ed314f3e3638bfde23586cf3",
        "ath_executable": str(args.ath.resolve()),
        "ath_sha256": _sha256(args.ath),
        "template": str(args.template.resolve()),
        "template_sha256": _sha256(args.template),
        "base_parameters": BASE_PARAMETERS,
        "sim_settings": SIM_SETTINGS,
        "cases": {},
    }
    for case_name, overrides in CASES.items():
        case_root = output_root / case_name
        work = case_root / "work"
        output = case_root / "output"
        logs = case_root / "logs"
        work.mkdir(parents=True)
        output.mkdir(parents=True)
        parameters = {**BASE_PARAMETERS, **overrides}
        cfg = render_cfg_text(
            template_text=template_text,
            parameters=parameters,
            version_id=case_name,
        )
        cfg = _apply_sim_export_settings_to_cfg(
            cfg,
            sim_export_settings=SIM_SETTINGS,
            export_specs=[],
            runtime_parameters=parameters,
        )
        cfg = _enforce_output_flag(cfg, key="Output.ABECProject", value=1)
        cfg = _enforce_output_flag(cfg, key="Output.STL", value=0)
        cfg_path = work / f"{case_name}.cfg"
        cfg_path.write_text(cfg, encoding="utf-8")
        runtime_cfg = _write_runtime_ath_cfg(
            ath_work_dir=work,
            ath_export_root=output,
            ath_executable=args.ath,
        )
        started = time.perf_counter()
        result = runner.run_cfg(cfg_path, version_logs_dir=logs, workdir=work)
        elapsed = time.perf_counter() - started
        generated = _latest_generated_dir(output)
        mesh_candidates = list(generated.rglob("bem_mesh.msh"))
        if not mesh_candidates:
            mesh_candidates = [path for path in generated.rglob("*.msh") if path.is_file()]
        if not mesh_candidates:
            raise RuntimeError(f"No mesh found for {case_name}")
        mesh = mesh_candidates[0]
        geo = generated / "ABEC_FreeStanding" / "bem_mesh.geo"
        stdout_text = Path(result.stdout_log).read_text(encoding="utf-8", errors="replace")
        dimensions = parse_ath_dimensions(stdout_text)
        manifest["cases"][case_name] = {
            "overrides": overrides,
            "parameters": parameters,
            "runtime_cfg": runtime_cfg,
            "cfg_path": str(cfg_path),
            "cfg_sha256": _sha256(cfg_path),
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "elapsed_s": elapsed,
            "stdout_log": str(result.stdout_log),
            "stderr_log": str(result.stderr_log),
            "dimensions_mm": {
                "length": dimensions.horn_length_mm,
                "width": dimensions.horn_width_mm,
                "height": dimensions.horn_height_mm,
                "source": dimensions.raw_line,
            },
            "generated_dir": str(generated),
            "mesh_relative_path": mesh.relative_to(generated).as_posix(),
            "mesh_sha256": _sha256(mesh),
            "mesh": _mesh_payload(mesh),
            "inner_profile": _inner_profile_from_geo(
                geo, nominal_length_mm=float(parameters["Length"])
            ),
            "artifacts": _artifact_manifest(generated),
        }
        print(case_name, result.exit_code, round(elapsed, 3), dimensions)
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
