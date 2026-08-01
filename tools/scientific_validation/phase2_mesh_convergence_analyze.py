from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.analyzer.plot_service import compute_beamwidth_curve
from app.analyzer.stage_plot_engine import compute_di_proxy_curve
from app.polar_txt_parser import parse_polar_legacy_complex_txt
from app.vacs_txt_parser import parse_vacs_txt_file


TARGET_NATIVE_IMAGES = {"ath.exe", "gmsh.exe", "akabak.exe", "vacsviewer_32.exe", "pythonw.exe"}
LEVELS = ("coarse", "medium", "fine")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in values) / len(values))


def _p95(values: list[float]) -> float:
    ordered = sorted(float(value) for value in values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _native_snapshot() -> list[dict[str, Any]]:
    command = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CreationDate | "
        "ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command], check=True, capture_output=True, text=True
    )
    raw = completed.stdout.strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    rows = parsed if isinstance(parsed, list) else [parsed]
    return [row for row in rows if str(row.get("Name") or "").lower() in TARGET_NATIVE_IMAGES]


def _orientation(value: float) -> str:
    return {0.0: "H", 45.0: "D", 90.0: "V"}[float(value)]


def _pressure_matrix(parsed: Any) -> tuple[list[float], list[float], list[list[float]], list[list[float]]]:
    freqs = [float(row.freq_hz) for row in parsed.rows]
    angles = [float(value) for value in parsed.angles_deg]
    absolute_by_freq: list[list[float]] = []
    for row in parsed.rows:
        absolute_by_freq.append(
            [
                20.0 * math.log10(max(math.hypot(re_value, im_value) / 20.0e-6, 1.0e-300))
                for re_value, im_value in zip(row.re_values, row.im_values)
            ]
        )
    matrix = [[absolute_by_freq[freq_idx][angle_idx] for freq_idx in range(len(freqs))] for angle_idx in range(len(angles))]
    zero_index = min(range(len(angles)), key=lambda index: abs(angles[index]))
    normalized = [
        [matrix[angle_idx][freq_idx] - matrix[zero_index][freq_idx] for freq_idx in range(len(freqs))]
        for angle_idx in range(len(angles))
    ]
    return freqs, angles, matrix, normalized


def _single_run(workspace: Path) -> dict[str, Any]:
    run_dirs = [path for path in (workspace / "exports").iterdir() if path.is_dir()]
    if len(run_dirs) != 1:
        raise RuntimeError(f"Expected one run in {workspace}, found {len(run_dirs)}")
    run_dir = run_dirs[0]
    run_id = run_dir.name
    pressures: dict[str, Any] = {}
    impedance_path: Path | None = None
    exports: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("V001_anygraph*.txt")):
        header = path.read_text(encoding="utf-8-sig", errors="replace")[:1200]
        is_pressure = "Data_LevelType=SoundPressure" in header
        exports.append(
            {"path": path.relative_to(workspace).as_posix(), "sha256": _sha256(path), "bytes": path.stat().st_size}
        )
        if is_pressure:
            parsed = parse_polar_legacy_complex_txt(path)
            pressures[_orientation(parsed.orientation_raw)] = parsed
        elif "Data_LevelType=Impedance" in header:
            impedance_path = path
    if set(pressures) != {"H", "V", "D"} or impedance_path is None:
        raise RuntimeError(f"Incomplete exports in {workspace}: planes={sorted(pressures)}, impedance={impedance_path}")

    snapshot = workspace / "logs" / run_id / "ath_input_snapshot"
    with sqlite3.connect(workspace / "db" / "runner_test.sqlite") as conn:
        run_row = conn.execute(
            "SELECT status, git_commit, notes, started_at, finished_at FROM test_runs WHERE test_run_id=?", (run_id,)
        ).fetchone()
        steps = conn.execute(
            "SELECT step_name, status, started_at, finished_at FROM test_run_steps WHERE test_run_id=? ORDER BY started_at, step_name",
            (run_id,),
        ).fetchall()
    if run_row is None:
        raise RuntimeError(f"Missing DB row for {run_id}")
    runtime_match = re.search(r"completed in ([0-9.]+)s", str(run_row[2] or ""))
    impedance = parse_vacs_txt_file(impedance_path)
    impedance_points = [point for series in impedance.series for point in series.points]
    return {
        "workspace": workspace,
        "run_id": run_id,
        "status": run_row[0],
        "git_commit": run_row[1],
        "runtime_s": float(runtime_match.group(1)) if runtime_match else None,
        "started_at": run_row[3],
        "finished_at": run_row[4],
        "steps": [
            {"name": row[0], "status": row[1], "started_at": row[2], "finished_at": row[3]} for row in steps
        ],
        "pressures": pressures,
        "impedance": [
            {"freq_hz": point.x_value, "re": point.y_value, "im": point.y_imag or 0.0} for point in impedance_points
        ],
        "exports": exports,
        "contract_hashes": {
            name: _sha256(snapshot / name) for name in ("Project.abec", "solving.txt", "observation.txt", "generic25.txt")
        },
        "db_sha256": _sha256(workspace / "db" / "runner_test.sqlite"),
    }


def _pair_metrics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    shape_errors: list[float] = []
    axial_errors: list[float] = []
    beamwidth_errors: list[float] = []
    di_errors: list[float] = []
    beamwidth_rows = 0
    beamwidth_excluded = 0
    for plane in "HVD":
        left_parsed = left["pressures"][plane]
        right_parsed = right["pressures"][plane]
        left_freqs, left_angles, left_abs, left_norm = _pressure_matrix(left_parsed)
        right_freqs, right_angles, right_abs, right_norm = _pressure_matrix(right_parsed)
        if left_freqs != right_freqs or left_angles != right_angles:
            raise RuntimeError(f"Polar grid mismatch for {plane}")
        zero_index = min(range(len(left_angles)), key=lambda index: abs(left_angles[index]))
        for angle_idx in range(len(left_angles)):
            for freq_idx in range(len(left_freqs)):
                shape_errors.append(abs(left_norm[angle_idx][freq_idx] - right_norm[angle_idx][freq_idx]))
        for freq_idx in range(len(left_freqs)):
            axial_errors.append(abs(left_abs[zero_index][freq_idx] - right_abs[zero_index][freq_idx]))

        left_bw = {row["freq_hz"]: row for row in compute_beamwidth_curve(freqs_hz=left_freqs, angles_deg=left_angles, matrix_db=left_norm)}
        right_bw = {row["freq_hz"]: row for row in compute_beamwidth_curve(freqs_hz=right_freqs, angles_deg=right_angles, matrix_db=right_norm)}
        for frequency in sorted(set(left_bw) & set(right_bw)):
            beamwidth_rows += 1
            if bool(left_bw[frequency].get("saturated")) or bool(right_bw[frequency].get("saturated")):
                beamwidth_excluded += 1
                continue
            beamwidth_errors.append(abs(float(left_bw[frequency]["beamwidth_deg"]) - float(right_bw[frequency]["beamwidth_deg"])))

        left_di = {row["freq_hz"]: row["value"] for row in compute_di_proxy_curve(
            freqs_hz=left_freqs, angles_deg=left_angles, matrix_db=left_norm, target_deg=90.0, norm_angle_deg=None
        )}
        right_di = {row["freq_hz"]: row["value"] for row in compute_di_proxy_curve(
            freqs_hz=right_freqs, angles_deg=right_angles, matrix_db=right_norm, target_deg=90.0, norm_angle_deg=None
        )}
        di_errors.extend(abs(float(left_di[freq]) - float(right_di[freq])) for freq in sorted(set(left_di) & set(right_di)))
    return {
        "polar_sample_count": len(shape_errors),
        "normalized_polar_rms_db": _rms(shape_errors),
        "normalized_polar_p95_abs_db": _p95(shape_errors),
        "axial_spl_rms_db": _rms(axial_errors),
        "axial_spl_max_abs_db": max(axial_errors),
        "beamwidth_candidate_count": beamwidth_rows,
        "beamwidth_excluded_saturated_or_inferred_count": beamwidth_excluded,
        "beamwidth_comparable_count": len(beamwidth_errors),
        "beamwidth_mean_abs_deg": sum(beamwidth_errors) / len(beamwidth_errors) if beamwidth_errors else None,
        "beamwidth_max_abs_deg": max(beamwidth_errors) if beamwidth_errors else None,
        "di_proxy_rms_db": _rms(di_errors),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze three-level real mesh convergence evidence.")
    parser.add_argument("--coarse", type=Path, required=True)
    parser.add_argument("--medium", type=Path, required=True)
    parser.add_argument("--fine", type=Path, required=True)
    parser.add_argument("--ath-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    workspaces = {level: getattr(args, level).resolve() for level in LEVELS}
    runs = {level: _single_run(path) for level, path in workspaces.items()}
    ath_manifest_path = args.ath_manifest.resolve()
    ath_manifest = json.loads(ath_manifest_path.read_text(encoding="utf-8"))
    mesh_rows: dict[str, dict[str, Any]] = {}
    for level in LEVELS:
        case = ath_manifest["cases"][f"mesh_{level}"]
        mesh_rows[level] = {
            "nodes": int(case["mesh"]["node_count"]),
            "triangles": int(case["mesh"]["triangle_count"]),
            "mesh_sha256": case["mesh_sha256"],
            "physical_groups": sorted(case["mesh"]["physical_names"].values()),
            "ath_elapsed_s": case["elapsed_s"],
        }
    topology_monotonic = (
        mesh_rows["coarse"]["nodes"] < mesh_rows["medium"]["nodes"] < mesh_rows["fine"]["nodes"]
        and mesh_rows["coarse"]["triangles"] < mesh_rows["medium"]["triangles"] < mesh_rows["fine"]["triangles"]
    )
    groups_equal = len({tuple(mesh_rows[level]["physical_groups"]) for level in LEVELS}) == 1
    contracts_equal = all(
        len({runs[level]["contract_hashes"][name] for level in LEVELS}) == 1
        for name in ("Project.abec", "solving.txt", "observation.txt", "generic25.txt")
    )
    coarse_medium = _pair_metrics(runs["coarse"], runs["medium"])
    medium_fine = _pair_metrics(runs["medium"], runs["fine"])

    impedance_rows = {level: runs[level]["impedance"] for level in LEVELS}
    impedance_finite = all(
        math.isfinite(float(row[axis])) for level in LEVELS for row in impedance_rows[level] for axis in ("freq_hz", "re", "im")
    )
    impedance_nonzero = any(
        math.hypot(float(row["re"]), float(row["im"])) > 0.0 for level in LEVELS for row in impedance_rows[level]
    )
    pressure_checks = {
        "all_runs_succeeded": all(runs[level]["status"] == "succeeded" for level in LEVELS),
        "topology_strictly_refined": topology_monotonic,
        "physical_groups_identical": groups_equal,
        "solver_observation_and_le_contracts_identical": contracts_equal,
        "medium_fine_polar_rms_le_0_75_db": medium_fine["normalized_polar_rms_db"] <= 0.75,
        "medium_fine_polar_p95_le_1_50_db": medium_fine["normalized_polar_p95_abs_db"] <= 1.50,
        "medium_fine_axial_rms_le_0_75_db": medium_fine["axial_spl_rms_db"] <= 0.75,
        "medium_fine_axial_max_le_1_50_db": medium_fine["axial_spl_max_abs_db"] <= 1.50,
        "medium_fine_di_proxy_rms_le_0_75_db": medium_fine["di_proxy_rms_db"] <= 0.75,
        "polar_convergence_trend": medium_fine["normalized_polar_rms_db"] <= coarse_medium["normalized_polar_rms_db"] + 1.0e-9,
        "all_runtimes_below_2400_s": all(float(runs[level]["runtime_s"] or math.inf) <= 2400.0 for level in LEVELS),
    }
    beamwidth_status = (
        "verified"
        if medium_fine["beamwidth_comparable_count"] > 0
        and float(medium_fine["beamwidth_mean_abs_deg"]) <= 3.0
        and float(medium_fine["beamwidth_max_abs_deg"]) <= 6.0
        else "not_validated_all_available_widths_are_flagged_saturated_or_one_sided_inferred"
    )
    impedance_status = "verified" if impedance_finite and impedance_nonzero else "not_validated_all_exported_values_are_zero"
    remaining = _native_snapshot()
    pressure_verified = all(pressure_checks.values()) and not remaining
    overall_status = (
        "verified"
        if pressure_verified and beamwidth_status == "verified" and impedance_status == "verified"
        else "pressure_convergence_verified_mesh_convergence_incomplete"
        if pressure_verified
        else "failed"
    )
    evidence = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": overall_status,
        "application_commit_at_analysis": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "ath_manifest": args.ath_manifest.as_posix(),
        "ath_manifest_sha256": _sha256(ath_manifest_path),
        "mesh_levels": mesh_rows,
        "runs": {
            level: {
                "workspace": getattr(args, level).as_posix(),
                "run_id": runs[level]["run_id"],
                "status": runs[level]["status"],
                "git_commit": runs[level]["git_commit"],
                "runtime_s": runs[level]["runtime_s"],
                "started_at": runs[level]["started_at"],
                "finished_at": runs[level]["finished_at"],
                "steps": runs[level]["steps"],
                "contract_hashes": runs[level]["contract_hashes"],
                "db_sha256": runs[level]["db_sha256"],
                "exports": runs[level]["exports"],
            }
            for level in LEVELS
        },
        "pair_metrics": {"coarse_medium": coarse_medium, "medium_fine": medium_fine},
        "pressure_checks": pressure_checks,
        "pressure_convergence_status": "verified" if pressure_verified else "failed",
        "beamwidth_status": beamwidth_status,
        "beamwidth_note": "The frozen matrix excludes saturated widths; WUT flags every 0..90 symmetry-inferred width as saturated, leaving no admissible pair.",
        "impedance": {
            "finite": impedance_finite,
            "any_nonzero": impedance_nonzero,
            "values": impedance_rows,
            "status": impedance_status,
        },
        "native_process_snapshot_after": remaining,
        "no_relevant_native_processes_after": not remaining,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": overall_status, "pair_metrics": evidence["pair_metrics"], "impedance_status": impedance_status}, indent=2))


if __name__ == "__main__":
    main()
