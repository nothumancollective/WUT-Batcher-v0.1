from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.library_audit import audit_library_root, discover_library_candidates


class LibraryAuditTests(unittest.TestCase):
    def _make_library(self, root: Path) -> Path:
        library = root / "WUT Project Library"
        project = library / "projects" / "P0001__1652d97a-8f8a-43ed-a10a-6b49f6f16c9b"
        (project / "db").mkdir(parents=True)
        (library / "library.json").write_text(
            json.dumps({"library_uid": "x", "schema_version": 1}), encoding="utf-8"
        )
        (library / "library.sqlite").write_bytes(b"sqlite-placeholder")
        (project / "db" / "project.sqlite").write_bytes(b"sqlite-placeholder")
        (project / "project.json").write_text(
            json.dumps(
                {
                    "display_number": "P0001",
                    "project_uid": "1652d97a-8f8a-43ed-a10a-6b49f6f16c9b",
                }
            ),
            encoding="utf-8",
        )
        return library

    def test_canonical_library_audits_ok_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library = self._make_library(Path(tmp_dir))
            before = sorted(str(path.relative_to(library)) for path in library.rglob("*"))
            report = audit_library_root(library)
            after = sorted(str(path.relative_to(library)) for path in library.rglob("*"))
            self.assertEqual(report["status"], "ok")
            self.assertTrue(report["read_only"])
            self.assertEqual(report["project_count"], 1)
            self.assertEqual(before, after)

    def test_parallel_project_databases_are_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library = self._make_library(Path(tmp_dir))
            project = next((library / "projects").iterdir())
            (project / "dataset").mkdir()
            (project / "dataset" / "project.sqlite").write_bytes(b"legacy")
            report = audit_library_root(library)
            codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("parallel_project_databases", codes)
            self.assertEqual(report["status"], "error")

    def test_sibling_discovery_marks_active_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            parent = Path(tmp_dir)
            library = self._make_library(parent)
            rows = discover_library_candidates(parent, active_root=library)
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["active"])
            self.assertEqual(rows[0]["layout"], "canonical")

    def test_sibling_discovery_finds_detached_projects_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            parent = Path(tmp_dir)
            detached = parent / "projects"
            (detached / "P0001__1652d97a-8f8a-43ed-a10a-6b49f6f16c9b").mkdir(parents=True)
            rows = discover_library_candidates(parent)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["layout"], "detached_projects_container")
            self.assertEqual(rows[0]["project_count"], 1)


if __name__ == "__main__":
    unittest.main()
