from __future__ import annotations

import json
from pathlib import Path

from app import cli


def test_geometry_migration_cli_defaults_to_read_only_dry_run(tmp_path: Path, capsys) -> None:
    project = tmp_path / "P0001__legacy"
    project.mkdir()
    (project / "project.json").write_text(
        json.dumps({"project_id": "P0001__legacy", "name": "Legacy", "constraints": {}}),
        encoding="utf-8",
    )
    report = tmp_path / "reports" / "migration.json"
    args = cli.build_parser().parse_args([
        "library", "migrate-geometries", "--project-root", str(project),
        "--report-path", str(report),
    ])

    assert args.func(args) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert payload["completed"] is False
    assert not (project / "geometries").exists()
    assert json.loads(capsys.readouterr().out)["dry_run"] is True


def test_geometry_migration_cli_requires_explicit_backup_for_apply(tmp_path: Path, capsys) -> None:
    project = tmp_path / "P0001__legacy"
    project.mkdir()
    (project / "project.json").write_text(
        json.dumps({"project_id": "P0001__legacy", "name": "Legacy", "constraints": {}}),
        encoding="utf-8",
    )
    args = cli.build_parser().parse_args([
        "library", "migrate-geometries", "--project-root", str(project), "--apply",
    ])

    assert args.func(args) == 2
    assert "--backup-root is required" in capsys.readouterr().out
    assert not (project / "geometries").exists()
