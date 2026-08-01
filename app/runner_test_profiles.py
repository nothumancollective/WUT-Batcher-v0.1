"""Runner test profiles for bounded and reproducible harness execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from app.ath_knowledge import load_ath_knowledge


@dataclass(frozen=True)
class RunnerTestProfile:
    profile_id: str
    parameter_overrides: Dict[str, Any]
    sim_export_overrides: Dict[str, Any]
    simulation_timeout_minutes: int
    rationale: str
    verification_plan: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "parameter_overrides": dict(self.parameter_overrides),
            "sim_export_overrides": dict(self.sim_export_overrides),
            "simulation_timeout_minutes": int(self.simulation_timeout_minutes),
            "rationale": self.rationale,
            "verification_plan": dict(self.verification_plan),
        }


FAST_PROFILE = RunnerTestProfile(
    profile_id="fast",
    parameter_overrides={
        "Mesh.AngularSegments": 24,
        "Mesh.LengthSegments": 16,
        "Mesh.CornerSegments": 4,
        "Mesh.ThroatSegments": 2,
        "Mesh.ThroatResolution": 12.0,
        "Mesh.MouthResolution": 24.0,
        "Mesh.RearResolution": 30.0,
    },
    sim_export_overrides={
        "freq_start_hz": 800.0,
        "freq_end_hz": 4000.0,
        "num_points": 6,
        "simulation_mode": "free_standing",
    },
    simulation_timeout_minutes=10,
    rationale=(
        "Reduce mesh density and frequency sampling for harness runs so the ATH->AKABAK->VACS cycle "
        "completes faster while preserving valid toolchain semantics."
    ),
    verification_plan={
        "hypothesis": "coarser mesh + fewer frequency points reduce runtime without breaking exports",
        "tests": [
            "Run same case with profile=fast and profile=baseline once and compare ATH+AKABAK step durations.",
            "Verify fast profile still produces non-empty parsed exports and monotonic frequency axis.",
        ],
    },
)


RESOURCE_PROFILE = RunnerTestProfile(
    profile_id="resource",
    parameter_overrides={
        "Mesh.AngularSegments": 28,
        "Mesh.LengthSegments": 18,
        "Mesh.CornerSegments": 4,
        "Mesh.ThroatSegments": 2,
        "Mesh.ThroatResolution": 14.0,
        "Mesh.MouthResolution": 26.0,
        "Mesh.RearResolution": 32.0,
    },
    sim_export_overrides={
        "freq_start_hz": 600.0,
        "freq_end_hz": 6000.0,
        "num_points": 8,
        "simulation_mode": "free_standing",
    },
    simulation_timeout_minutes=20,
    rationale=(
        "Exercise a larger mesh and wider frequency grid than the fast smoke profile while keeping "
        "one native solve inside the harness hard timeout on the validation VM."
    ),
    verification_plan={
        "hypothesis": "the bounded higher-workload profile remains stable across two sequential native runs",
        "tests": [
            "Run two sequential ATH->AKABAK->VACS cycles with profile=resource.",
            "Verify every run produces non-empty parsed exports and leaves no owned native process behind.",
            "Compare wall time and peak resource use with the five-run fast batch.",
        ],
    },
)


BASELINE_PROFILE = RunnerTestProfile(
    profile_id="baseline",
    parameter_overrides={},
    sim_export_overrides={},
    simulation_timeout_minutes=10,
    rationale="Preserve all case and template inputs for explicit reference and convergence runs.",
    verification_plan={
        "hypothesis": "the baseline profile does not mutate caller-provided settings",
        "tests": [
            "Compare input and effective parameter dictionaries exactly.",
            "Use only when the native runtime budget is known to accommodate the selected template.",
        ],
    },
)


SCIENTIFIC_PROFILE = RunnerTestProfile(
    profile_id="scientific",
    parameter_overrides={},
    sim_export_overrides={},
    simulation_timeout_minutes=20,
    rationale=(
        "Preserve declared scientific case inputs exactly while allowing the validated "
        "20-minute inactivity budget for real convergence and reference runs."
    ),
    verification_plan={
        "hypothesis": "scientific cases retain every declared input and receive only the larger timeout budget",
        "tests": [
            "Compare caller and effective parameter dictionaries exactly.",
            "Compare caller and effective simulation/export dictionaries exactly.",
            "Verify the harness reports a 20-minute solver timeout budget.",
        ],
    },
)


_PROFILES: Dict[str, RunnerTestProfile] = {
    "baseline": BASELINE_PROFILE,
    "fast": FAST_PROFILE,
    "resource": RESOURCE_PROFILE,
    "scientific": SCIENTIFIC_PROFILE,
}


def get_runner_test_profile(profile_id: str) -> RunnerTestProfile:
    key = str(profile_id or "").strip().lower() or "fast"
    if key not in _PROFILES:
        raise KeyError(f"Unknown runner test profile: {profile_id}")
    return _PROFILES[key]


def apply_runner_test_profile(
    *,
    profile_id: str,
    parameters: Dict[str, Any],
    sim_export_settings: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    profile = get_runner_test_profile(profile_id)
    merged_parameters = dict(parameters)
    merged_parameters.update(profile.parameter_overrides)

    merged_sim = dict(sim_export_settings)
    merged_sim.update(profile.sim_export_overrides)

    bundle = load_ath_knowledge()
    catalog_keys = {
        str(item.get("key"))
        for item in list(bundle.catalog.get("parameters", []) or [])
        if isinstance(item, dict) and str(item.get("key", "")).strip()
    }
    effective_overrides: Dict[str, Any] = {}
    unknown_override_keys = []
    for key, value in profile.parameter_overrides.items():
        if key in catalog_keys:
            effective_overrides[key] = value
        else:
            unknown_override_keys.append(key)

    metadata = {
        "profile": profile.to_dict(),
        "applied_parameter_overrides": effective_overrides,
        "applied_sim_export_overrides": dict(profile.sim_export_overrides),
        "unknown_catalog_keys": unknown_override_keys,
    }
    return merged_parameters, merged_sim, metadata
