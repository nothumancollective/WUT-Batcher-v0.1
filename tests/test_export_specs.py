from __future__ import annotations

import unittest

from app.export_specs import dump_export_specs, parse_export_specs


class ExportSpecsTests(unittest.TestCase):
    def test_parse_explicit_export_specs(self) -> None:
        specs = parse_export_specs(
            {
                "export_specs": [
                    {
                        "id": "exp_spl",
                        "tool": "vacs",
                        "graph_kind": "spl",
                        "format": "txt",
                        "options": {"delimiter": "tab"},
                        "output_name_template": "{version_id}_{graph_kind}.{format}",
                    }
                ]
            }
        )
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].id, "exp_spl")
        self.assertEqual(specs[0].graph_kind, "spl")
        self.assertEqual(specs[0].format, "txt")
        dumped = dump_export_specs(specs)
        self.assertEqual(dumped[0]["id"], "exp_spl")

    def test_parse_legacy_exports_fallback(self) -> None:
        specs = parse_export_specs(
            {
                "exports": {
                    "spl": {"enabled": True, "params": {"delimiter": "tab"}},
                    "phase": {"enabled": False},
                }
            }
        )
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].graph_kind, "spl")
        self.assertEqual(specs[0].id, "legacy_spl")


if __name__ == "__main__":
    unittest.main()
