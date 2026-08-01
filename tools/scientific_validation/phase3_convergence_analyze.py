from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.analyzer.cache import AnalyzerCachePolicy, AnalyzerPlotCache
from app.analyzer.plot_service import AnalyzerPlotService
from app.models import Batch, Project, ProjectConstraints, VersionSpec
from app.polar_txt_parser import parse_polar_legacy_complex_txt
from app.tidy_dataset import TidyDatasetWriter
from app.vacs_txt_parser import parse_vacs_txt_file


LEVELS = ("coarse", "medium", "fine")
PLANES = ("H", "V")
TOOLCHAIN = {
    "ATH": {"version": "4.8.2", "path": Path(r"C:\Tools\ATH\ath.exe")},
    "Gmsh": {"version": "4.14.0", "path": Path(r"C:\Tools\ATH\gmsh.exe")},
    "AKABAK": {"version": "3.2.4.126", "path": Path(r"C:\Program Files (x86)\RDTeam\AKABAK\AKABAK.exe")},
    "VacsViewer": {"version": "2.1.3.33", "path": Path(r"C:\Program Files (x86)\RDTeam\VACSVIEWER_32\VACSVIEWER_32.exe")},
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


def _phase_delta_deg(left: complex, right: complex) -> float:
    delta = math.degrees(math.atan2(left.imag, left.real) - math.atan2(right.imag, right.real))
    return abs((delta + 180.0) % 360.0 - 180.0)


def _run_dir(workspace: Path) -> tuple[str, Path]:
    run_dirs = [path for path in (workspace / "exports").iterdir() if path.is_dir()]
    if len(run_dirs) != 1:
        raise RuntimeError(f"expected one export run below {workspace}, found {len(run_dirs)}")
    return run_dirs[0].name, run_dirs[0]


def _pressure_matrix(parsed: Any) -> tuple[list[float], list[float], list[list[float]], list[list[float]]]:
    frequencies = [float(row.freq_hz) for row in parsed.rows]
    angles = [float(value) for value in parsed.angles_deg]
    absolute_by_frequency = [
        [20.0 * math.log10(max(math.hypot(re_value, im_value) / 20.0e-6, 1.0e-300))
         for re_value, im_value in zip(row.re_values, row.im_values)]
        for row in parsed.rows
    ]
    absolute = [
        [absolute_by_frequency[freq_index][angle_index] for freq_index in range(len(frequencies))]
        for angle_index in range(len(angles))
    ]
    zero_index = min(range(len(angles)), key=lambda index: abs(angles[index]))
    normalized = [
        [absolute[angle_index][freq_index] - absolute[zero_index][freq_index] for freq_index in range(len(frequencies))]
        for angle_index in range(len(angles))
    ]
    return frequencies, angles, absolute, normalized


def _crossing(a0: float, y0: float, a1: float, y1: float, target: float = -6.0) -> float:
    if y1 == y0:
        return (a0 + a1) / 2.0
    return a0 + (target - y0) * (a1 - a0) / (y1 - y0)


def _independent_beamwidth(angles: list[float], values: list[float]) -> dict[str, Any]:
    zero_index = min(range(len(angles)), key=lambda index: abs(angles[index]))
    if abs(angles[zero_index]) > 1.0e-9 or values[zero_index] < -6.0:
        return {"eligible": False, "reason": "zero_axis_missing_or_below_target"}
    left = None
    for index in range(zero_index, 0, -1):
        if values[index] >= -6.0 and values[index - 1] < -6.0:
            left = _crossing(angles[index], values[index], angles[index - 1], values[index - 1])
            break
    right = None
    for index in range(zero_index, len(angles) - 1):
        if values[index] >= -6.0 and values[index + 1] < -6.0:
            right = _crossing(angles[index], values[index], angles[index + 1], values[index + 1])
            break
    if left is None or right is None or not (angles[0] < left < 0.0 < right < angles[-1]):
        return {"eligible": False, "reason": "two_strict_interior_crossings_missing", "left": left, "right": right}
    return {"eligible": True, "left_deg": left, "right_deg": right, "beamwidth_deg": right - left}


def _load_level(workspace: Path) -> dict[str, Any]:
    run_id, exports = _run_dir(workspace)
    impedance_path = None
    polars: dict[str, tuple[Path, Any]] = {}
    export_rows = []
    for path in sorted(exports.glob("V001_anygraph*.txt")):
        graph = parse_vacs_txt_file(path)
        metadata = dict(graph.export_meta.get("metadata", {}) or {})
        export_rows.append({"path": path, "sha256": _sha256(path), "metadata": metadata})
        if str(metadata.get("Data_BaseUnit", "")).strip().lower() == "ohm" and "System=S1" in str(metadata.get("Data_Legend", "")):
            impedance_path = path
        if str(metadata.get("Data_LevelType", "")).strip().lower() == "soundpressure":
            polar = parse_polar_legacy_complex_txt(path)
            plane = {0.0: "H", 90.0: "V"}.get(float(polar.orientation_raw))
            if plane:
                polars[plane] = (path, polar)
    if impedance_path is None or set(polars) != set(PLANES):
        raise RuntimeError(f"incomplete exports: impedance={impedance_path}, planes={sorted(polars)}")

    impedance_graph = parse_vacs_txt_file(impedance_path)
    impedance = [
        {"freq_hz": float(point.x_value), "re_ohm": float(point.y_value), "im_ohm": float(point.y_imag or 0.0)}
        for series in impedance_graph.series for point in series.points
    ]
    with closing(sqlite3.connect(workspace / "db" / "runner_test.sqlite")) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute(
            "SELECT status, git_commit, notes, started_at, finished_at FROM test_runs WHERE test_run_id=?", (run_id,)
        ).fetchone()
        if run is None:
            raise RuntimeError(f"run row missing: {run_id}")
        db_impedance = conn.execute(
            """
            SELECT gp.x_value, gp.y_value, gp.y_imag
            FROM graphs g JOIN graph_series gs ON gs.graph_id=g.graph_id
            JOIN graph_points gp ON gp.series_id=gs.series_id
            WHERE g.run_id=? AND lower(g.y_unit)='ohm'
            ORDER BY gp.point_index
            """, (run_id,),
        ).fetchall()
        test_case = json.loads(conn.execute("SELECT batch_settings_json FROM test_cases LIMIT 1").fetchone()[0])
    runtime = None
    text = str(run["notes"] or "")
    if "completed in " in text:
        runtime = float(text.split("completed in ", 1)[1].split("s", 1)[0])
    snapshot = workspace / "logs" / run_id / "ath_input_snapshot"
    return {
        "workspace": workspace,
        "run_id": run_id,
        "status": str(run["status"]),
        "git_commit": str(run["git_commit"]),
        "runtime_s": runtime,
        "started_at": str(run["started_at"]),
        "finished_at": str(run["finished_at"]),
        "impedance_path": impedance_path,
        "impedance": impedance,
        "db_impedance": [dict(row) for row in db_impedance],
        "polars": polars,
        "exports": export_rows,
        "mesh_parameters": {key: value for key, value in test_case["selected_params"].items() if key.startswith("Mesh.")},
        "contract_hashes": {name: _sha256(snapshot / name) for name in ("Project.abec", "solving.txt", "observation.txt", "generic25.txt")},
    }


def _write_analysis_db(root: Path, runs: dict[str, dict[str, Any]]) -> tuple[Path, dict[str, Any]]:
    project_root = root / "library" / "P_SCI_P3_ANALYSIS"
    project_root.mkdir(parents=True, exist_ok=True)
    writer = TidyDatasetWriter(project_root, library_root=project_root.parent)
    project = Project(
        project_id="P_SCI_P3_ANALYSIS",
        name="Scientific Phase 3 Analysis Chain",
        root_path=str(project_root),
        constraints=ProjectConstraints(project_id="P_SCI_P3_ANALYSIS"),
    )
    db_checks: dict[str, Any] = {}
    for level, run in runs.items():
        batch_id = f"B_{level.upper()}"
        version_id = f"V_{level.upper()}"
        batch = Batch(batch_id=batch_id, project_id=project.project_id)
        version = VersionSpec(
            project_id=project.project_id,
            batch_id=batch_id,
            version_id=version_id,
            sweep_mode="single",
            sequence_index=1,
            parameters=dict(run["mesh_parameters"]),
        )
        writer.write_plan_bundle(project=project, batch=batch, versions=[version])
        for plane in PLANES:
            path, parsed = run["polars"][plane]
            points = []
            for freq_index, row in enumerate(parsed.rows):
                for angle_index, angle in enumerate(parsed.angles_deg):
                    points.append({
                        "freq_index": freq_index, "angle_index": angle_index,
                        "freq_hz": float(row.freq_hz), "angle_deg": float(angle),
                        "re": float(row.re_values[angle_index]), "im": float(row.im_values[angle_index]),
                    })
            writer.write_polar_measurement(
                measurement={
                    "project_id": "P_SCI_P3_ANALYSIS", "batch_id": batch_id, "version_id": version_id,
                    "run_id": run["run_id"], "orientation": plane, "orientation_raw": parsed.orientation_raw,
                    "norm_angle_deg": 0.0, "data_level_type": "SoundPressure", "data_base_unit": "Pa",
                    "data_absc_unit": "Hz", "freq_min_hz": 1000.0, "freq_max_hz": 4000.0,
                    "freq_count": len(parsed.rows), "angle_min_deg": -90.0, "angle_max_deg": 90.0,
                    "angle_step_deg": 5.0, "angle_count": len(parsed.angles_deg),
                    "angles_deg_json": json.dumps(parsed.angles_deg), "source_file": str(path),
                    "file_hash": _sha256(path), "export_meta_json": json.dumps(parsed.metadata, sort_keys=True),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }, points=points,
            )
        imp_graph = parse_vacs_txt_file(run["impedance_path"])
        writer.write_measurements([
            {
                "project_id": "P_SCI_P3_ANALYSIS", "batch_id": batch_id, "version_id": version_id,
                "run_id": run["run_id"], "graph_type": "electrical_input_impedance", "graph_kind": "impedance",
                "variant": "generic25_S1", "x_name": "Frequency", "y_name": "Impedance",
                "x_unit": "Hz", "y_unit": "ohm", "source_file": str(run["impedance_path"]),
                "series_kind": "curve", "series_label": "Impedance, System=S1", "point_index": index,
                "x_value": point.x_value, "y_value": point.y_value, "y_imag": point.y_imag,
                "export_meta": imp_graph.export_meta,
            }
            for index, point in enumerate(imp_graph.series[0].points)
        ])

        cache = AnalyzerPlotCache(AnalyzerCachePolicy(mode="low", size_limit_mb=0, keep_last_n=1))
        service = AnalyzerPlotService(cache)
        db_checks[level] = {}
        for plane in PLANES:
            payload = service.load_plane_plot_payload(
                db_path=writer.project_db_path, project_id="P_SCI_P3_ANALYSIS", batch_id=batch_id,
                run_id=run["run_id"], version_id=version_id, plane=plane,
                band_low_hz=1000.0, band_high_hz=4000.0,
            )
            db_checks[level][plane] = payload
    return writer.project_db_path, db_checks


def _pair_impedance(left: list[dict[str, float]], right: list[dict[str, float]]) -> dict[str, float]:
    left_map = {row["freq_hz"]: complex(row["re_ohm"], row["im_ohm"]) for row in left}
    right_map = {row["freq_hz"]: complex(row["re_ohm"], row["im_ohm"]) for row in right}
    frequencies = sorted(set(left_map) & set(right_map))
    differences = [left_map[f] - right_map[f] for f in frequencies]
    relative_rms = math.sqrt(sum(abs(value) ** 2 for value in differences) / sum(abs(right_map[f]) ** 2 for f in frequencies))
    magnitude_relative = [abs(abs(left_map[f]) - abs(right_map[f])) / abs(right_map[f]) for f in frequencies]
    phases = [_phase_delta_deg(left_map[f], right_map[f]) for f in frequencies if abs(right_map[f]) >= 1.0]
    return {
        "complex_relative_rms": relative_rms,
        "magnitude_relative_max": max(magnitude_relative),
        "phase_mae_deg": sum(phases) / len(phases),
        "phase_max_deg": max(phases),
    }


def _pair_beamwidth(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    frequencies = sorted(set(left) & set(right))
    errors = [abs(left[f] - right[f]) for f in frequencies]
    return {"count": len(errors), "mae_deg": sum(errors) / len(errors), "max_deg": max(errors)}


def main() -> None:
    parser = argparse.ArgumentParser()
    for level in LEVELS:
        parser.add_argument(f"--{level}", type=Path, required=True)
    parser.add_argument("--phase2-mesh-evidence", type=Path, required=True)
    parser.add_argument("--analysis-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    runs = {level: _load_level(getattr(args, level).resolve()) for level in LEVELS}
    phase2 = json.loads(args.phase2_mesh_evidence.read_text(encoding="utf-8"))
    analysis_db, analyzer = _write_analysis_db(args.analysis_root.resolve(), runs)

    beamwidth: dict[str, dict[str, dict[float, float]]] = {}
    analyzer_max_delta = 0.0
    db_polar_max_delta = 0.0
    for level, run in runs.items():
        beamwidth[level] = {}
        for plane in PLANES:
            _path, parsed = run["polars"][plane]
            frequencies, angles, _absolute, normalized = _pressure_matrix(parsed)
            rows = {}
            for freq_index, frequency in enumerate(frequencies):
                independent = _independent_beamwidth(angles, [row[freq_index] for row in normalized])
                if independent["eligible"]:
                    rows[frequency] = float(independent["beamwidth_deg"])
            beamwidth[level][plane] = rows
            analyzer_rows = {float(row["freq_hz"]): float(row["beamwidth_deg"]) for row in analyzer[level][plane]["beamwidth_curve"]}
            analyzer_max_delta = max(analyzer_max_delta, *(abs(rows[f] - analyzer_rows[f]) for f in rows))
            for angle_index in range(len(angles)):
                for freq_index in range(len(frequencies)):
                    db_polar_max_delta = max(
                        db_polar_max_delta,
                        abs(float(analyzer[level][plane]["matrix_db"][angle_index][freq_index]) - normalized[angle_index][freq_index]),
                    )

    impedance_db_max = max(
        abs(float(raw[key]) - float(db[db_key]))
        for run in runs.values()
        for raw, db in zip(run["impedance"], run["db_impedance"])
        for key, db_key in (("freq_hz", "x_value"), ("re_ohm", "y_value"), ("im_ohm", "y_imag"))
    )
    coarse_medium_imp = _pair_impedance(runs["coarse"]["impedance"], runs["medium"]["impedance"])
    medium_fine_imp = _pair_impedance(runs["medium"]["impedance"], runs["fine"]["impedance"])
    beam_pairs = {
        plane: {
            "coarse_medium": _pair_beamwidth(beamwidth["coarse"][plane], beamwidth["medium"][plane]),
            "medium_fine": _pair_beamwidth(beamwidth["medium"][plane], beamwidth["fine"][plane]),
        }
        for plane in PLANES
    }

    mesh_parameters = {level: runs[level]["mesh_parameters"] for level in LEVELS}
    expected_mesh_parameters = {
        "coarse": {"Mesh.AngularSegments": 24, "Mesh.LengthSegments": 12, "Mesh.MouthResolution": 24, "Mesh.ThroatResolution": 14},
        "medium": {"Mesh.AngularSegments": 48, "Mesh.LengthSegments": 20, "Mesh.MouthResolution": 18, "Mesh.ThroatResolution": 10},
        "fine": {"Mesh.AngularSegments": 72, "Mesh.LengthSegments": 28, "Mesh.MouthResolution": 12, "Mesh.ThroatResolution": 8},
    }
    contracts_equal = all(
        len({runs[level]["contract_hashes"][name] for level in LEVELS}) == 1
        for name in ("Project.abec", "solving.txt", "observation.txt", "generic25.txt")
    )
    nontrivial = all(
        any(math.hypot(row["re_ohm"], row["im_ohm"]) >= 1.0 for row in runs[level]["impedance"])
        and any(abs(row["im_ohm"]) >= 0.01 for row in runs[level]["impedance"])
        for level in LEVELS
    )
    checks = {
        "all_runs_succeeded": all(runs[level]["status"] == "succeeded" for level in LEVELS),
        "mesh_parameters_match_frozen_matrix": mesh_parameters == expected_mesh_parameters,
        "mesh_topology_reused_phase2_strictly_refined": all(
            phase2["mesh_levels"][left][key] < phase2["mesh_levels"][right][key]
            for left, right in (("coarse", "medium"), ("medium", "fine")) for key in ("nodes", "triangles")
        ),
        "contracts_byte_identical": contracts_equal,
        "I1_nontrivial_electrical_impedance_ohm": nontrivial,
        "I2_medium_fine_complex_rms_le_0p02": medium_fine_imp["complex_relative_rms"] <= 0.02,
        "I2_medium_fine_magnitude_max_le_0p05": medium_fine_imp["magnitude_relative_max"] <= 0.05,
        "I2_medium_fine_phase_mae_le_2deg": medium_fine_imp["phase_mae_deg"] <= 2.0,
        "I2_medium_fine_phase_max_le_5deg": medium_fine_imp["phase_max_deg"] <= 5.0,
        "I2_convergence_trend": medium_fine_imp["complex_relative_rms"] <= coarse_medium_imp["complex_relative_rms"] + 1.0e-9,
        "I2_raw_parser_runner_db_le_1e_9": impedance_db_max <= 1.0e-9,
        "B1_all_seven_two_sided_crossings_H": all(len(beamwidth[level]["H"]) == 7 for level in LEVELS),
        "B1_all_seven_two_sided_crossings_V": all(len(beamwidth[level]["V"]) == 7 for level in LEVELS),
        "B2_medium_fine_H": beam_pairs["H"]["medium_fine"]["mae_deg"] <= 3.0 and beam_pairs["H"]["medium_fine"]["max_deg"] <= 6.0,
        "B2_medium_fine_V": beam_pairs["V"]["medium_fine"]["mae_deg"] <= 3.0 and beam_pairs["V"]["medium_fine"]["max_deg"] <= 6.0,
        "B2_convergence_trend_H": beam_pairs["H"]["medium_fine"]["mae_deg"] <= beam_pairs["H"]["coarse_medium"]["mae_deg"] + 1.0e-9,
        "B2_convergence_trend_V": beam_pairs["V"]["medium_fine"]["mae_deg"] <= beam_pairs["V"]["coarse_medium"]["mae_deg"] + 1.0e-9,
        "B2_raw_parser_analysis_db_analyzer_matrix_le_1e_9db": db_polar_max_delta <= 1.0e-9,
        "B2_independent_vs_analyzer_width_le_1e_9deg": analyzer_max_delta <= 1.0e-9,
    }
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analysis_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, capture_output=True, check=True).stdout.strip(),
        "status": "verified" if all(checks.values()) else "failed_frozen_criteria",
        "criteria_commit": "cdc022c",
        "observation_repair_commit": "7150d75",
        "toolchain": {
            name: {
                "version": item["version"],
                "path": str(item["path"]),
                "sha256": _sha256(item["path"]),
                "bytes": item["path"].stat().st_size,
            }
            for name, item in TOOLCHAIN.items()
        },
        "runs": {
            level: {
                key: runs[level][key] for key in ("run_id", "status", "git_commit", "runtime_s", "started_at", "finished_at", "mesh_parameters", "contract_hashes")
            } | {
                "exports": [{"path": row["path"].name, "sha256": row["sha256"], "metadata": row["metadata"]} for row in runs[level]["exports"]],
                "electrical_input_impedance_ohm": runs[level]["impedance"],
            }
            for level in LEVELS
        },
        "mesh_topology_provenance": {
            "source": args.phase2_mesh_evidence.as_posix(),
            "reason": "identical frozen geometry and mesh-control tuples; native harness cleanup intentionally removes generated meshes",
            "levels": phase2["mesh_levels"],
        },
        "impedance": {"coarse_medium": coarse_medium_imp, "medium_fine": medium_fine_imp, "runner_db_max_abs_delta": impedance_db_max},
        "beamwidth_deg": {level: {plane: [{"freq_hz": f, "value": v} for f, v in sorted(beamwidth[level][plane].items())] for plane in PLANES} for level in LEVELS},
        "beamwidth_pairs": beam_pairs,
        "chain": {"analysis_db": _repo_relative(analysis_db), "polar_matrix_max_abs_db": db_polar_max_delta, "beamwidth_max_abs_deg": analyzer_max_delta},
        "checks": checks,
        "classification": {
            "electrical_impedance_convergence": "verified" if all(value for key, value in checks.items() if key.startswith("I")) else "failed",
            "beamwidth_convergence": "verified" if all(value for key, value in checks.items() if key.startswith("B")) else "failed",
            "normalized_bem_radiation_impedance": "separate_all_zero_secondary_output_not_reclassified",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "checks": checks, "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
