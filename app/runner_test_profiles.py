"""Runner test profiles for fast/low-resolution harness execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from app.ath_knowledge import load_ath_knowledge


@dataclass(frozen=True)
class RunnerTestProfile:
    profile_id: str
    parameter_overrides: Dict[str, Any]
    sim_export_overrides: Dict[str, Any]
    rationale: str
    verification_plan: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "parameter_overrides": dict(self.parameter_overrides),
            "sim_export_overrides": dict(self.sim_export_overrides),
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


_PROFILES: Dict[str, RunnerTestProfile] = {
    "fast": FAST_PROFILE,
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
