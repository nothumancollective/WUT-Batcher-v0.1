from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.cfg_renderer import render_cfg_text
from app.runners import AthRunner, parse_ath_dimensions
from app.runtime_orchestrator import (
    _apply_sim_export_settings_to_cfg,
    _enforce_output_flag,
    _write_runtime_ath_cfg,
)


DEFAULT_CASES: dict[str, dict[str, float | int]] = {
    "length_120": {},
    "length_160": {"Length": 160},
    "throat_40": {"Throat.Diameter": 40},
    # ATH's resolution controls are target sizes: smaller values create the
    # denser mesh.  The case names below describe the resulting mesh density.
    "mesh_fine": {
        "Mesh.AngularSegments": 24,
        "Mesh.LengthSegments": 12,
        "Mesh.MouthResolution": 12,
        "Mesh.ThroatResolution": 8,
    },
    "mesh_medium": {},
    "mesh_coarse": {
        "Mesh.AngularSegments": 72,
        "Mesh.LengthSegments": 28,
        "Mesh.MouthResolution": 24,
        "Mesh.ThroatResolution": 14,
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_msh(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    names: dict[int, str] = {}
    nodes: dict[int, tuple[float, float, float]] = {}
    elements: list[tuple[int, tuple[int, ...]]] = []
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
                nodes[int(parts[0])] = (
                    float(parts[1]),
                    float(parts[2]),
                    float(parts[3]),
                )
            index += count + 2
        elif token == "$Elements":
            count = int(lines[index + 1])
            for row in lines[index + 2 : index + 2 + count]:
                parts = [int(item) for item in row.split()]
                element_type = parts[1]
                tag_count = parts[2]
                if element_type != 2 or tag_count < 1:
                    continue
                node_ids = tuple(parts[3 + tag_count :])
                if len(node_ids) == 3:
                    elements.append((parts[3], node_ids))
            index += count + 2
        index += 1

    coordinates = list(nodes.values())
    group_counts: dict[str, int] = defaultdict(int)
    normal_sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    areas: dict[str, float] = defaultdict(float)
    group_extents: dict[str, dict[str, float]] = {}
    for physical_id, node_ids in elements:
        name = names.get(physical_id, str(physical_id))
        points = tuple(nodes[node_id] for node_id in node_ids)
        p0, p1, p2 = points
        u = tuple(p1[axis] - p0[axis] for axis in range(3))
        v = tuple(p2[axis] - p0[axis] for axis in range(3))
        cross = (
            (u[1] * v[2]) - (u[2] * v[1]),
            (u[2] * v[0]) - (u[0] * v[2]),
            (u[0] * v[1]) - (u[1] * v[0]),
        )
        group_counts[name] += 1
        areas[name] += 0.5 * math.sqrt(sum(value * value for value in cross))
        for axis in range(3):
            normal_sums[name][axis] += cross[axis]
        flattened = [coordinate for point in points for coordinate in point]
        xs, ys, zs = flattened[0::3], flattened[1::3], flattened[2::3]
        bounds = group_extents.setdefault(
            name,
            {
                "x_min": math.inf,
                "x_max": -math.inf,
                "y_min": math.inf,
                "y_max": -math.inf,
                "z_min": math.inf,
                "z_max": -math.inf,
            },
        )
        bounds["x_min"] = min(bounds["x_min"], *xs)
        bounds["x_max"] = max(bounds["x_max"], *xs)
        bounds["y_min"] = min(bounds["y_min"], *ys)
        bounds["y_max"] = max(bounds["y_max"], *ys)
        bounds["z_min"] = min(bounds["z_min"], *zs)
        bounds["z_max"] = max(bounds["z_max"], *zs)

    return {
        "mesh_format": lines[1].strip() if len(lines) > 1 else "",
        "node_count": len(nodes),
        "triangle_count": len(elements),
        "physical_names": names,
        "group_triangle_counts": dict(group_counts),
        "group_area_mm2": dict(areas),
        "group_oriented_normal_sums": dict(normal_sums),
        "group_extents_mm": group_extents,
        "extents_mm": {
            "x_min": min(row[0] for row in coordinates),
            "x_max": max(row[0] for row in coordinates),
            "y_min": min(row[1] for row in coordinates),
            "y_max": max(row[1] for row in coordinates),
            "z_min": min(row[2] for row in coordinates),
            "z_max": max(row[2] for row in coordinates),
        },
    }


def _latest_generated_dir(output_root: Path) -> Path:
    candidates = [path for path in output_root.iterdir() if path.is_dir()]
    if not candidates:
        raise RuntimeError(f"ATH generated no output directory below {output_root}")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run isolated ATH geometry and mesh contract probes."
    )
    parser.add_argument("--ath", type=Path, default=Path(r"C:\Tools\ATH\ath.exe"))
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(r"C:\Tools\ATH\template_run.cfg"),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--case",
        action="append",
        choices=tuple(DEFAULT_CASES),
        dest="cases",
        help="Run only this case; repeat the option to select more than one.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_root = args.output_root.resolve()
    if output_root.exists():
        raise RuntimeError(f"Refusing to overwrite validation root: {output_root}")
    output_root.mkdir(parents=True)
    template_text = args.template.read_text(encoding="utf-8-sig")
    base: dict[str, float | int] = {
        "Coverage.Angle": 55,
        "Length": 120,
        "Throat.Diameter": 32,
        "Mesh.AngularSegments": 48,
        "Mesh.LengthSegments": 20,
        "Mesh.MouthResolution": 18,
        "Mesh.ThroatResolution": 10,
    }
    sim = {
        "freq_start_hz": 400,
        "freq_end_hz": 4000,
        "num_points": 8,
        "mesh_frequency": 1000,
        "simulation_mode": "free_standing",
    }
    runner = AthRunner(args.ath)
    manifest: dict[str, object] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ath_executable": str(args.ath.resolve()),
        "ath_sha256": _sha256(args.ath),
        "template": str(args.template.resolve()),
        "template_sha256": _sha256(args.template),
        "cases": {},
    }
    selected_cases = args.cases or list(DEFAULT_CASES)
    case_results: dict[str, object] = manifest["cases"]  # type: ignore[assignment]
    for case_name in selected_cases:
        case_root = output_root / case_name
        work = case_root / "work"
        output = case_root / "output"
        logs = case_root / "logs"
        work.mkdir(parents=True)
        output.mkdir(parents=True)
        parameters = {**base, **DEFAULT_CASES[case_name]}
        cfg = render_cfg_text(
            template_text=template_text,
            parameters=parameters,
            version_id=case_name,
        )
        cfg = _apply_sim_export_settings_to_cfg(
            cfg,
            sim_export_settings=sim,
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
        config = next(generated.rglob("config.txt"))
        project = next(generated.rglob("Project.abec"))
        mesh_candidates = list(generated.rglob("bem_mesh.msh"))
        if not mesh_candidates:
            mesh_candidates = [path for path in generated.rglob("*.msh") if path.is_file()]
        mesh = mesh_candidates[0]
        stdout_text = Path(result.stdout_log).read_text(encoding="utf-8", errors="replace")
        dimensions = parse_ath_dimensions(stdout_text)
        case_results[case_name] = {
            "parameters": parameters,
            "sim_export_settings": sim,
            "runtime_cfg": runtime_cfg,
            "cfg_path": str(cfg_path),
            "cfg_sha256": _sha256(cfg_path),
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "elapsed_s": elapsed,
            "generated_dir": str(generated),
            "generated_config_sha256": _sha256(config),
            "project_abec_sha256": _sha256(project),
            "mesh_sha256": _sha256(mesh),
            "dimensions_mm": {
                "length": dimensions.horn_length_mm,
                "width": dimensions.horn_width_mm,
                "height": dimensions.horn_height_mm,
                "source": dimensions.raw_line,
            },
            "mesh_stats": _parse_msh(mesh),
        }
        print(case_name, result.exit_code, round(elapsed, 3), dimensions)
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
