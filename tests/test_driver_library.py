from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from app.driver_library import DriverDefinition, DriverLibrary, DriverRevision


def _network(tmp_path: Path, name: str = "driver.txt") -> Path:
    path = tmp_path / name
    path.write_bytes(b"System 'S1'\r\nDriver 'D1'\r\n")
    return path


def test_generic25_seed_is_hashed_snapshot_and_read_only(tmp_path: Path) -> None:
    source = _network(tmp_path)
    library = DriverLibrary(tmp_path / "library")
    revision = library.seed_generic25(source)
    again = library.seed_generic25(source)
    snapshot = library.snapshot(revision.revision_id)

    assert again.revision_id == revision.revision_id
    assert snapshot.verify()
    assert snapshot.driver["read_only"] is True
    assert snapshot.le_network_hash == revision.le_network_hash
    with pytest.raises(ValueError, match="read-only"):
        library.create_revision("generic25", parameters={}, provenance={})
    with pytest.raises(ValueError, match="cannot be archived"):
        library.archive("generic25")


def test_user_driver_crud_revision_duplicate_archive_and_search(tmp_path: Path) -> None:
    library = DriverLibrary(tmp_path / "library")
    definition = DriverDefinition(
        driver_id="D-custom", manufacturer="Example", model="CD 1", kind="compression_driver"
    )
    revision = DriverRevision(
        revision_id="DR-custom-1", driver_id=definition.driver_id, revision_number=1,
        parameters={"exit_diameter": {"value": 0.0254, "unit": "m"}},
        provenance={"source_url": "https://example.invalid/data.pdf", "trust": "user_asserted"},
    )
    created = library.create_definition(definition, revision)
    next_revision = library.create_revision(
        definition.driver_id,
        parameters={"exit_diameter": {"value": 0.0254, "unit": "m"}, "re": {"value": 6.2, "unit": "ohm"}},
        provenance={"source": "manual", "trust": "user_asserted"},
    )
    duplicate, duplicate_revision = library.duplicate(definition.driver_id)

    assert created.revision_hash
    assert next_revision.revision_number == 2
    assert library.list_definitions(query="example", kind="compression_driver")
    assert duplicate.driver_id != definition.driver_id
    assert duplicate_revision.revision_number == 1
    library.archive(duplicate.driver_id)
    assert duplicate.driver_id not in {item.driver_id for item in library.list_definitions()}
    assert duplicate.driver_id in {item.driver_id for item in library.list_definitions(include_archived=True)}


def test_cone_driver_json_round_trip_preserves_asset_and_unknown_extensions(tmp_path: Path) -> None:
    source_library = DriverLibrary(tmp_path / "source")
    digest, _, _ = source_library.store_le_asset(_network(tmp_path, "cone.le"))
    definition = DriverDefinition(
        driver_id="D-cone", manufacturer="Example", model="Mid 8", kind="cone_driver"
    )
    revision = DriverRevision(
        revision_id="DR-cone-1", driver_id="D-cone", revision_number=1,
        parameters={
            "re": {"value": 5.8, "unit": "ohm"},
            "moving_mass": {"value": None, "unit": "kg"},
        },
        provenance={"source": "user", "licence_note": "private data", "trust": "user_asserted"},
        le_network_hash=digest, le_network_name="cone.le", completeness="simulation_ready",
        extensions={"vendor_field": "preserve me"},
    )
    source_library.create_definition(definition, revision)
    exported = source_library.export_json(definition.driver_id)

    target = DriverLibrary(tmp_path / "target")
    report = target.import_json(exported)
    assert report.ok, report.errors
    imported = target.get_revision(report.revision_id or "")
    snapshot = target.snapshot(imported.revision_id)
    assert snapshot.verify()
    assert imported.parameters["moving_mass"]["value"] is None
    assert imported.extensions["vendor_field"] == "preserve me"


@pytest.mark.parametrize("payload, message", [
    ({"schema": "wrong", "schema_version": 1}, "schema"),
    ({
        "schema": "wut.driver-library", "schema_version": 1,
        "definition": asdict(DriverDefinition(driver_id="D-x", manufacturer="", model="X")),
        "revisions": [asdict(DriverRevision(
            revision_id="DR-x", driver_id="D-x", revision_number=1,
            parameters={"re": {"value": 1.0, "unit": "made-up-unit"}},
        ))],
    }, "unsupported"),
])
def test_import_rejects_bad_schema_or_units(tmp_path: Path, payload: dict, message: str) -> None:
    report = DriverLibrary(tmp_path / "library").import_json(payload)
    assert not report.ok
    assert message in " ".join(report.errors)

