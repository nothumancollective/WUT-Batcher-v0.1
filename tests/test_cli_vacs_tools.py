from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.cli import main


class CliVacsToolsTests(unittest.TestCase):
    def test_vacs_discover_graphs_dry_run_writes_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_root = Path(tmp_dir) / "ui_maps" / "vacs"
            rc = main(
                [
                    "vacs",
                    "discover-graphs",
                    "--vacs-version",
                    "testbuild",
                    "--catalog-root",
                    str(catalog_root),
                    "--dry-run",
                ]
            )
            self.assertEqual(rc, 0)
            catalog_path = catalog_root / "testbuild" / "graph_catalog.json"
            self.assertTrue(catalog_path.exists())


if __name__ == "__main__":
    unittest.main()
