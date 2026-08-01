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

from app.polar_txt_parser import parse_polar_legacy_complex_txt
from app.runners import parse_ath_dimensions


TARGET_NATIVE_IMAGES = {"ath.exe", "gmsh.exe", "akabak.exe", "vacsviewer_32.exe", "pythonw.exe"}
EXPECTED_DISTANCE_DB = -20.0 * math.log10(2.0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metadata_float(metadata: dict[str, str], key: str) -> float:
    return float(str(metadata[key]).strip().strip("'").strip('"'))


def _orientation(value: float) -> str:
    return {0.0: "H", 45.0: "D", 90.0: "V"}[float(value)]


def _mag_db(re_value: float, im_value: float) -> float:
    return 20.0 * math.log10(max(math.hypot(re_value, im_value), 1.0e-300))


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
        ["powershell", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = completed.stdout.strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    rows = parsed if isinstance(parsed, list) else [parsed]
    return [row for row in rows if str(row.get("Name") or "").lower() in TARGET_NATIVE_IMAGES]


def _observation_blocks(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks: list[dict[str, Any]] = []
    for chunk in re.split(r"(?m)^BE_Spectrum\s*$", text)[1:]:
        header = re.search(r'GraphHeader="([^"]+)"', chunk)
        distance = re.search(r"(?m)^\s*Distance=([-+0-9.eE]+)m\s*$", chunk)
        offset = re.search(r"(?m)^\s*Offset=([-+0-9.eE]+)mm\s*$", chunk)
        inclination = re.search(r"(?m)^\s*\d+\s+Inclination=([-+0-9.eE]+)", chunk)
        base_plane = re.search(r"(?m)^\s*BasePlane=([^\s]+)\s*$", chunk)
        polar_range = re.search(r"(?m)^\s*PolarRange=([^\r\n]+)", chunk)
        if not all((header, distance, offset, inclination, base_plane, polar_range)):
            continue
        blocks.append(
            {
                "graph_header": header.group(1),
                "distance_m": float(distance.group(1)),
                "offset_mm": float(offset.group(1)),
                "inclination_deg": float(inclination.group(1)),
                "base_plane": base_plane.group(1),
                "polar_range": polar_range.group(1).strip(),
            }
        )
    return blocks


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze the phase-2 3 m / 6 m real observation run.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--speed-of-sound", type=float, default=343.0)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    workspace = args.workspace.resolve()
    run_dirs = [path for path in (workspace / "exports").iterdir() if path.is_dir()]
    if len(run_dirs) != 1:
        raise RuntimeError(f"Expected one exported run, found {len(run_dirs)}")
    run_dir = run_dirs[0]
    run_id = run_dir.name
    snapshot = workspace / "logs" / run_id / "ath_input_snapshot"
    observation = snapshot / "observation.txt"
    stdout_log = workspace / "logs" / run_id / "ath" / "ath.stdout.log"
    dimensions = parse_ath_dimensions(stdout_log.read_text(encoding="utf-8", errors="replace"))
    aperture_m = float(dimensions.horn_width_mm or 0.0) / 1000.0
    if aperture_m <= 0.0:
        raise RuntimeError("ATH aperture width is unavailable")

    datasets: dict[tuple[str, float], Any] = {}
    export_rows: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("V001_anygraph*.txt")):
        parsed = parse_polar_legacy_complex_txt(path)
        level_type = str(parsed.metadata.get("Data_LevelType", "") or "").lower()
        export_rows.append(
            {
                "path": path.relative_to(workspace).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
                "level_type": parsed.metadata.get("Data_LevelType"),
                "distance_marker": parsed.metadata.get("Param_Coord_x1"),
                "inclination_marker": parsed.metadata.get("Param_Coord_x3"),
            }
        )
        if "soundpressure" not in level_type:
            continue
        distance = _metadata_float(parsed.metadata, "Param_Coord_x1")
        plane = _orientation(float(parsed.orientation_raw))
        datasets[(plane, distance)] = parsed
    expected_keys = {(plane, distance) for plane in "HVD" for distance in (3.0, 6.0)}
    if set(datasets) != expected_keys:
        raise RuntimeError(f"Unexpected polar dataset keys: {sorted(datasets)}")

    on_axis_rows: list[dict[str, Any]] = []
    shape_errors: list[float] = []
    plane_zero_consistency: dict[str, float] = {}
    all_frequencies: set[float] = set()
    for plane in "HVD":
        near = datasets[(plane, 3.0)]
        far = datasets[(plane, 6.0)]
        if near.angles_deg != far.angles_deg or near.freq_values != far.freq_values:
            raise RuntimeError(f"Grid mismatch for plane {plane}")
        angle_zero_index = min(range(len(near.angles_deg)), key=lambda index: abs(near.angles_deg[index]))
        for row_near, row_far in zip(near.rows, far.rows):
            frequency = float(row_near.freq_hz)
            all_frequencies.add(frequency)
            near_db = [
                _mag_db(re_value, im_value)
                for re_value, im_value in zip(row_near.re_values, row_near.im_values)
            ]
            far_db = [
                _mag_db(re_value, im_value)
                for re_value, im_value in zip(row_far.re_values, row_far.im_values)
            ]
            delta = far_db[angle_zero_index] - near_db[angle_zero_index]
            wavelength = float(args.speed_of_sound) / frequency
            fraunhofer_m = 2.0 * aperture_m * aperture_m / wavelength
            eligible = 3.0 >= fraunhofer_m
            on_axis_rows.append(
                {
                    "plane": plane,
                    "freq_hz": frequency,
                    "fraunhofer_m": fraunhofer_m,
                    "eligible": eligible,
                    "delta_db_6m_minus_3m": delta,
                    "absolute_error_from_inverse_distance_db": abs(delta - EXPECTED_DISTANCE_DB),
                }
            )
            near_norm = [value - near_db[angle_zero_index] for value in near_db]
            far_norm = [value - far_db[angle_zero_index] for value in far_db]
            shape_errors.extend(abs(a - b) for a, b in zip(near_norm, far_norm))

    # H/V/D must meet at the same on-axis point for each distance and frequency.
    for distance in (3.0, 6.0):
        maximum = 0.0
        reference = datasets[("H", distance)]
        zero_index = min(range(len(reference.angles_deg)), key=lambda index: abs(reference.angles_deg[index]))
        for row_index in range(len(reference.rows)):
            values = []
            for plane in "HVD":
                row = datasets[(plane, distance)].rows[row_index]
                values.append(complex(row.re_values[zero_index], row.im_values[zero_index]))
            maximum = max(maximum, max(abs(value - values[0]) for value in values[1:]))
        plane_zero_consistency[f"{distance:g}m_max_complex_delta_pa"] = maximum

    eligible_rows = [row for row in on_axis_rows if row["eligible"]]
    inverse_max_error = max(float(row["absolute_error_from_inverse_distance_db"]) for row in eligible_rows)
    shape_rms = math.sqrt(sum(value * value for value in shape_errors) / len(shape_errors))
    shape_p95 = _p95(shape_errors)
    blocks = _observation_blocks(observation)
    block_contract = (
        len(blocks) == 6
        and {(row["inclination_deg"], row["distance_m"]) for row in blocks}
        == {(inclination, distance) for inclination in (0.0, 45.0, 90.0) for distance in (3.0, 6.0)}
        and all(row["base_plane"] == "zx" and row["offset_mm"] == 65.0 and row["polar_range"] == "0,90,19" for row in blocks)
        and "NormalizingAngle" not in observation.read_text(encoding="utf-8", errors="replace")
    )

    with sqlite3.connect(workspace / "db" / "runner_test.sqlite") as conn:
        db_row = conn.execute(
            "SELECT test_run_id, status, started_at, finished_at FROM test_runs WHERE test_run_id=?",
            (run_id,),
        ).fetchone()
    if db_row is None:
        raise RuntimeError("Runner DB row is missing")
    remaining = _native_snapshot()
    checks = {
        "runner_status_succeeded": db_row[1] == "succeeded",
        "six_pressure_exports_present": len(datasets) == 6,
        "observation_contract_exact": block_contract,
        "all_frequencies_far_field_eligible": len(eligible_rows) == len(on_axis_rows),
        "inverse_distance_max_error_le_0_50_db": inverse_max_error <= 0.50,
        "normalized_shape_rms_le_0_25_db": shape_rms <= 0.25,
        "normalized_shape_p95_le_0_50_db": shape_p95 <= 0.50,
        "hvd_on_axis_complex_values_identical_le_1e_12_pa": max(plane_zero_consistency.values()) <= 1.0e-12,
        "no_relevant_native_processes_after": not remaining,
    }
    evidence = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "verified" if all(checks.values()) else "failed",
        "application_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "workspace": args.workspace.as_posix(),
        "run_id": run_id,
        "runner_db": {
            "test_run_id": db_row[0],
            "status": db_row[1],
            "started_at": db_row[2],
            "finished_at": db_row[3],
            "sha256": _sha256(workspace / "db" / "runner_test.sqlite"),
        },
        "observation_contract": {
            "source_path": observation.relative_to(workspace).as_posix(),
            "sha256": _sha256(observation),
            "blocks": blocks,
            "normalization_present": "NormalizingAngle" in observation.read_text(encoding="utf-8", errors="replace"),
            "interpreted_origin_mm": [0.0, 0.0, 65.0],
            "interpreted_reference_axis": "+z",
            "base_plane": "zx",
            "planes": {"H": "inclination 0 deg", "D": "inclination 45 deg", "V": "inclination 90 deg"},
            "coordinate_interpretation_status": "plausibilized from generated AKABAK contract and WUT plane mapping; exact Cartesian expansion not independently exposed by TXT",
        },
        "aperture_and_far_field": {
            "ath_stdout_sha256": _sha256(stdout_log),
            "aperture_diameter_m": aperture_m,
            "speed_of_sound_m_s": float(args.speed_of_sound),
            "criterion": "r_F = 2 D^2 / lambda; require 3 m >= r_F",
            "maximum_r_f_m": max(float(row["fraunhofer_m"]) for row in on_axis_rows),
        },
        "inverse_distance": {
            "expected_delta_db": EXPECTED_DISTANCE_DB,
            "rows": on_axis_rows,
            "maximum_absolute_error_db": inverse_max_error,
        },
        "normalized_shape_invariance": {
            "sample_count": len(shape_errors),
            "rms_db": shape_rms,
            "p95_absolute_db": shape_p95,
        },
        "plane_axis_consistency": plane_zero_consistency,
        "exports": export_rows,
        "checks": checks,
        "native_process_snapshot_after": remaining,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "checks": checks}, indent=2))


if __name__ == "__main__":
    main()
