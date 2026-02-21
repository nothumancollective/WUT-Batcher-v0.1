from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.batch_export_panel import BatchExportPanel

try:
    from PySide6.QtWidgets import QApplication, QPushButton
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class BatchExportPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_panel_exposes_advanced_button(self) -> None:
        panel = BatchExportPanel()
        self.assertIsInstance(panel.advanced_btn, QPushButton)
        self.assertEqual(str(panel.advanced_btn.text()), "Advanced")

    def test_payload_contains_mesh_frequency_and_structured_specs(self) -> None:
        panel = BatchExportPanel()
        panel._advanced_state.spl.enabled = True  # type: ignore[attr-defined]
        panel.freq_start.setText("600")
        panel.freq_end.setText("14000")
        panel.num_points.setText("24")
        panel.mesh_frequency.setText("1200")
        payload = panel.sim_export_params_payload()
        self.assertEqual(float(payload["freq_start_hz"]), 600.0)
        self.assertEqual(float(payload["freq_end_hz"]), 14000.0)
        self.assertEqual(int(payload["num_points"]), 24)
        self.assertEqual(float(payload["mesh_frequency"]), 1200.0)
        self.assertTrue(bool(payload.get("auto_default_polar_exports")))
        specs = list(payload.get("export_specs", []))
        self.assertEqual(len(specs), 1)
        self.assertEqual(str(specs[0].get("graph_kind")), "spl")
        self.assertEqual(str(specs[0].get("format")), "txt")

    def test_payload_uses_default_polar_flag_when_no_manual_specs(self) -> None:
        panel = BatchExportPanel()
        payload = panel.sim_export_params_payload()
        specs = list(payload.get("export_specs", []))
        self.assertEqual(specs, [])
        self.assertTrue(bool(payload.get("auto_default_polar_exports")))
        self.assertEqual(panel.export_spec_count(), 3)

    def test_sweep_mode_roundtrip(self) -> None:
        panel = BatchExportPanel()
        panel.set_sweep_mode("combined")
        self.assertEqual(panel.sweep_mode_value(), "combined")
        panel.set_sweep_mode("invalid")
        self.assertEqual(panel.sweep_mode_value(), "single")

    def test_simulation_mode_roundtrip(self) -> None:
        panel = BatchExportPanel()
        panel.set_simulation_mode("infinite_baffle")
        payload = panel.sim_export_params_payload()
        self.assertEqual(str(payload.get("simulation_mode")), "infinite_baffle")

    def test_duplicate_polar_name_returns_fatal_issue(self) -> None:
        panel = BatchExportPanel()
        panel._advanced_state.polars[0].enabled = True  # type: ignore[attr-defined]
        panel._advanced_state.polars[1].enabled = True  # type: ignore[attr-defined]
        panel._advanced_state.polars[0].polar_name = "SPL_V"  # type: ignore[attr-defined]
        panel._advanced_state.polars[1].polar_name = "SPL_V"  # type: ignore[attr-defined]
        issues = panel.validation_issues()
        self.assertTrue(issues)
        self.assertEqual(str(issues[0].get("rule_id")), "export_duplicate_polar_name")

    def test_advanced_polar_payload_contains_norm_angle(self) -> None:
        panel = BatchExportPanel()
        panel._advanced_state.polars[0].enabled = True  # type: ignore[attr-defined]
        panel._advanced_state.polars[0].polar_name = "P1"  # type: ignore[attr-defined]
        panel._advanced_state.polars[0].norm_angle = 35  # type: ignore[attr-defined]
        payload = panel.sim_export_params_payload()
        specs = list(payload.get("export_specs", []))
        polar_specs = [item for item in specs if str(item.get("graph_kind", "")).lower() == "polar"]
        self.assertTrue(polar_specs)
        options = dict(polar_specs[0].get("options", {}) or {})
        self.assertEqual(int(options.get("norm_angle")), 35)

    def test_footer_copy_and_action_buttons_are_consistent(self) -> None:
        panel = BatchExportPanel()
        self.assertEqual(str(panel.default_export_hint.text()), "Default exports:")
        self.assertEqual(str(panel.default_export_chip.text()), "Polars (H/V/D)")
        self.assertEqual(panel.enclosure_btn.objectName(), "BatchPrimaryButton")
        self.assertEqual(panel.advanced_btn.objectName(), "BatchSecondaryButton")
        self.assertEqual(panel.enclosure_btn.height(), panel.advanced_btn.height())
        panel.resize(520, 250)
        panel._apply_footer_layout_mode()  # type: ignore[attr-defined]
        self.assertEqual(str(panel._footer_layout_mode), "compact")
        panel.resize(880, 250)
        panel._apply_footer_layout_mode()  # type: ignore[attr-defined]
        self.assertEqual(str(panel._footer_layout_mode), "wide")


if __name__ == "__main__":
    unittest.main()
