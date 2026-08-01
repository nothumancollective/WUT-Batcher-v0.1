from dataclasses import replace
from pathlib import Path

from app.driver_library import DriverLibrary
from app.geometry_domain import Geometry
from app.geometry_driver_compat import validate_geometry_driver


def test_compatibility_rules_are_evidence_labelled_and_narrow(tmp_path: Path) -> None:
    network = tmp_path / "generic25.txt"
    network.write_text("System 'S1'\n", encoding="utf-8")
    library = DriverLibrary(tmp_path / "library")
    revision = library.seed_generic25(network)
    snapshot = library.snapshot(revision.revision_id)
    geometry = Geometry(geometry_id="G1", project_id="P1", name="HF", role="hf_horn")

    assert validate_geometry_driver(geometry, snapshot) == []
    missing = validate_geometry_driver(geometry, None)
    assert missing[0].rule_id == "driver_le_network_required"
    assert missing[0].severity == "fatal"
    assert missing[0].evidence_type == "execution_contract"

    tampered = replace(snapshot, snapshot_hash="bad")
    findings = validate_geometry_driver(geometry, tampered)
    assert any(item.rule_id == "driver_snapshot_integrity" and item.severity == "fatal" for item in findings)
