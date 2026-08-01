from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any


TARGET_NATIVE_IMAGES = {
    "ath.exe",
    "gmsh.exe",
    "akabak.exe",
    "vacsviewer_32.exe",
    "pythonw.exe",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.split(";", 1)[0].strip()
        if not line or "=" not in line or line.endswith("{"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _changed_keys(a: dict[str, str], b: dict[str, str]) -> list[str]:
    return sorted(key for key in set(a) | set(b) if a.get(key) != b.get(key))


def _artifact(case: dict[str, Any], relative_path: str) -> dict[str, Any]:
    for row in case["artifacts"]:
        if row["relative_path"] == relative_path:
            return row
    raise KeyError(relative_path)


def _driver_area(case: dict[str, Any]) -> float:
    matches = [
        float(value)
        for key, value in case["mesh"]["group_area_mm2"].items()
        if "D1001" in key
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one D1001 driver group, got {len(matches)}")
    return matches[0]


def _relative_delta(a: float, b: float) -> float:
    return abs(float(b) - float(a)) / max(abs(float(a)), 1.0e-12)


def _normalised_project_text(case: dict[str, Any]) -> str:
    generated = Path(case["generated_dir"])
    text = (generated / "ABEC_FreeStanding" / "Project.abec").read_text(
        encoding="utf-8", errors="replace"
    )
    return re.sub(r"(?m)^C0=.*?\.msh,M1\s*$", "C0=<GEOMETRY>.msh,M1", text)


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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze phase-2 ATH mouth/profile evidence.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    manifest_path = args.manifest.resolve()
    try:
        source_manifest = manifest_path.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        source_manifest = manifest_path.as_posix()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest["cases"]["mouth_45_n4"]
    mouth = manifest["cases"]["mouth_60_n4"]
    profile = manifest["cases"]["mouth_45_n6"]

    configs = {
        name: _config_values(Path(case["generated_dir"]) / "config.txt")
        for name, case in manifest["cases"].items()
    }
    base_groups = sorted(base["mesh"]["physical_names"].values())
    base_area = _driver_area(base)

    mouth_width_base = float(base["dimensions_mm"]["width"])
    mouth_width_variant = float(mouth["dimensions_mm"]["width"])
    mouth_geo_base = 2.0 * float(base["inner_profile"][-1]["radius_x_mm"])
    mouth_geo_variant = 2.0 * float(mouth["inner_profile"][-1]["radius_x_mm"])
    mouth_area_base = math.pi * (0.5 * mouth_geo_base) ** 2
    mouth_area_variant = math.pi * (0.5 * mouth_geo_variant) ** 2

    profile_a = list(base["inner_profile"])
    profile_b = list(profile["inner_profile"])
    if [row["normalized_z"] for row in profile_a] != [row["normalized_z"] for row in profile_b]:
        raise RuntimeError("Profile z grids do not match; explicit interpolation is required")
    interior_deltas = [
        abs(float(row_a["radius_x_mm"]) - float(row_b["radius_x_mm"]))
        for row_a, row_b in zip(profile_a, profile_b)
        if 0.0 < float(row_a["normalized_z"]) < 1.0
    ]
    profile_fraction = sum(delta >= 0.10 for delta in interior_deltas) / len(interior_deltas)

    obs_equal_mouth = _artifact(base, "ABEC_FreeStanding/observation.txt")["sha256"] == _artifact(
        mouth, "ABEC_FreeStanding/observation.txt"
    )["sha256"]
    solve_equal_mouth = _artifact(base, "ABEC_FreeStanding/solving.txt")["sha256"] == _artifact(
        mouth, "ABEC_FreeStanding/solving.txt"
    )["sha256"]
    obs_equal_profile = _artifact(base, "ABEC_FreeStanding/observation.txt")["sha256"] == _artifact(
        profile, "ABEC_FreeStanding/observation.txt"
    )["sha256"]
    solve_equal_profile = _artifact(base, "ABEC_FreeStanding/solving.txt")["sha256"] == _artifact(
        profile, "ABEC_FreeStanding/solving.txt"
    )["sha256"]
    project_local_mouth = _normalised_project_text(base) == _normalised_project_text(mouth)
    project_local_profile = _normalised_project_text(base) == _normalised_project_text(profile)

    mouth_checks = {
        "ath_exit_zero": all(int(row["exit_code"]) == 0 and not bool(row["timed_out"]) for row in (base, mouth)),
        "only_coverage_angle_changed": _changed_keys(configs["mouth_45_n4"], configs["mouth_60_n4"])
        == ["Coverage.Angle"],
        "throat_driver_area_relative_delta_le_0_001": _relative_delta(base_area, _driver_area(mouth)) <= 0.001,
        "nominal_length_delta_mm_le_0_02": abs(
            float(base["dimensions_mm"]["length"]) - float(mouth["dimensions_mm"]["length"])
        )
        <= 0.02,
        "physical_groups_identical": base_groups == sorted(mouth["mesh"]["physical_names"].values()),
        "mouth_area_increase_ge_0_15": mouth_area_variant / mouth_area_base - 1.0 >= 0.15,
        "stdout_geo_width_error_mm_le_0_05": max(
            abs(mouth_width_base - mouth_geo_base), abs(mouth_width_variant - mouth_geo_variant)
        )
        <= 0.05,
        "observation_byte_identical": obs_equal_mouth,
        "solving_byte_identical": solve_equal_mouth,
        "project_diff_geometry_reference_only": project_local_mouth,
    }
    profile_width = float(profile["dimensions_mm"]["width"])
    profile_geo_width = 2.0 * float(profile["inner_profile"][-1]["radius_x_mm"])
    profile_checks = {
        "ath_exit_zero": all(int(row["exit_code"]) == 0 and not bool(row["timed_out"]) for row in (base, profile)),
        "only_term_n_changed": _changed_keys(configs["mouth_45_n4"], configs["mouth_45_n6"]) == ["Term.n"],
        "throat_driver_area_relative_delta_le_0_001": _relative_delta(base_area, _driver_area(profile)) <= 0.001,
        "nominal_length_delta_mm_le_0_02": abs(
            float(base["dimensions_mm"]["length"]) - float(profile["dimensions_mm"]["length"])
        )
        <= 0.02,
        "physical_groups_identical": base_groups == sorted(profile["mesh"]["physical_names"].values()),
        "stdout_geo_width_error_mm_le_0_05": max(
            abs(mouth_width_base - mouth_geo_base), abs(profile_width - profile_geo_width)
        )
        <= 0.05,
        "interior_max_delta_mm_ge_0_50": max(interior_deltas) >= 0.50,
        "interior_fraction_delta_ge_0_10_mm_ge_0_20": profile_fraction >= 0.20,
        "observation_byte_identical": obs_equal_profile,
        "solving_byte_identical": solve_equal_profile,
        "project_diff_geometry_reference_only": project_local_profile,
    }

    remaining = _native_snapshot()
    evidence = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "verified" if all(mouth_checks.values()) and all(profile_checks.values()) and not remaining else "failed",
        "baseline_commit": manifest["baseline_commit"],
        "source_manifest": source_manifest,
        "source_manifest_sha256": _sha256(manifest_path),
        "ath_sha256": manifest["ath_sha256"],
        "template_sha256": manifest["template_sha256"],
        "mouth_contract": {
            "changed_config_keys": _changed_keys(configs["mouth_45_n4"], configs["mouth_60_n4"]),
            "baseline_width_mm": mouth_width_base,
            "variant_width_mm": mouth_width_variant,
            "baseline_geo_width_mm": mouth_geo_base,
            "variant_geo_width_mm": mouth_geo_variant,
            "mouth_area_increase_fraction": mouth_area_variant / mouth_area_base - 1.0,
            "throat_area_relative_delta": _relative_delta(base_area, _driver_area(mouth)),
            "checks": mouth_checks,
            "status": "verified" if all(mouth_checks.values()) else "failed",
        },
        "profile_contract": {
            "changed_config_keys": _changed_keys(configs["mouth_45_n4"], configs["mouth_45_n6"]),
            "baseline_width_mm": mouth_width_base,
            "variant_width_mm": profile_width,
            "variant_geo_width_mm": profile_geo_width,
            "interior_slice_count": len(interior_deltas),
            "interior_max_radius_delta_mm": max(interior_deltas),
            "interior_fraction_delta_ge_0_10_mm": profile_fraction,
            "throat_area_relative_delta": _relative_delta(base_area, _driver_area(profile)),
            "checks": profile_checks,
            "status": "verified" if all(profile_checks.values()) else "failed",
        },
        "physical_groups": base_groups,
        "native_process_snapshot_after_analysis": remaining,
        "no_relevant_native_processes_after_analysis": not remaining,
        "notes": [
            "Total free-standing mesh z extent includes rear/interface geometry and is not nominal horn length.",
            "Term.n mouth endpoint semantics follow amendment A1 in the frozen matrix document.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
