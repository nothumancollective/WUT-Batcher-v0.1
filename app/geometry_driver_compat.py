"""Evidence-labelled geometry/driver execution compatibility findings."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.driver_library import DriverSnapshot
from app.geometry_domain import Geometry


@dataclass(frozen=True)
class CompatibilityFinding:
    rule_id: str
    severity: str
    message: str
    rationale: str
    evidence_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_geometry_driver(geometry: Geometry, snapshot: DriverSnapshot | None, *, requires_le_network: bool = True) -> list[CompatibilityFinding]:
    findings: list[CompatibilityFinding] = []
    if snapshot is None:
        severity = "fatal" if requires_le_network else "warning"
        findings.append(CompatibilityFinding(
            "driver_le_network_required" if requires_le_network else "driver_data_incomplete",
            severity, "No driver snapshot is selected.",
            "The current AKABAK coupling requires a staged LE network." if requires_le_network else "A driver is optional for this operation.",
            "execution_contract",
        ))
        return findings
    kind = str(snapshot.driver.get("kind") or "future_unknown")
    if geometry.role == "hf_horn" and kind == "cone_driver":
        findings.append(CompatibilityFinding(
            "geometry_driver_kind_compatibility", "warning",
            "A cone driver is assigned to an HF horn geometry.",
            "This is unusual but not proven acoustically invalid, so execution is not blocked.",
            "domain_heuristic",
        ))
    if requires_le_network and not snapshot.le_network_hash:
        findings.append(CompatibilityFinding(
            "driver_le_network_required", "fatal", "The selected driver revision has no LE network.",
            "The validated AKABAK path needs an explicit LE network; no T/S conversion is inferred.",
            "execution_contract",
        ))
    if str(snapshot.revision.get("completeness") or "incomplete") != "simulation_ready":
        findings.append(CompatibilityFinding(
            "driver_data_incomplete", "warning", "Driver revision is marked incomplete.",
            "Missing optional values remain visible and are never defaulted.", "declared_completeness",
        ))
    if not snapshot.verify():
        findings.append(CompatibilityFinding(
            "driver_snapshot_integrity", "fatal", "Driver snapshot hash verification failed.",
            "Execution must use exactly the revision and LE bytes selected at planning time.", "sha256",
        ))
    return findings

