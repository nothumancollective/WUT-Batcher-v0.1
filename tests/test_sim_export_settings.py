from __future__ import annotations

import unittest

from app.models import SimExportSettings


class SimExportSettingsTests(unittest.TestCase):
    def test_mesh_frequency_roundtrip(self) -> None:
        payload = {
            "freq_start_hz": 500.0,
            "freq_end_hz": 16000.0,
            "num_points": 32,
            "mesh_frequency": 1100.0,
            "simulation_mode": "infinite_baffle",
            "export_specs": [
                {
                    "id": "preset_spl",
                    "tool": "vacs",
                    "graph_kind": "spl",
                    "variant": "main",
                    "format": "txt",
                    "options": {},
                    "output_name_template": "{version_id}_{graph_kind}.{format}",
                }
            ],
        }
        settings = SimExportSettings.from_dict(payload)
        self.assertEqual(settings.mesh_frequency, 1100.0)
        self.assertEqual(settings.simulation_mode, "infinite_baffle")
        back = settings.to_dict()
        self.assertEqual(back.get("mesh_frequency"), 1100.0)
        self.assertEqual(back.get("simulation_mode"), "infinite_baffle")


if __name__ == "__main__":
    unittest.main()
