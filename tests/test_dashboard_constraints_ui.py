from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import ConstraintSummaryGrid, DashboardPage

try:
    from PySide6.QtWidgets import QApplication, QFrame, QPushButton
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QFrame = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class DashboardConstraintUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_constraint_grid_has_five_columns_and_chip_opens_editor_signal(self) -> None:
        grid = ConstraintSummaryGrid()
        grid.set_constraints_payload(
            {
                "fixed_params": {"Length": 220.0, "Throat.Profile": 1, "Morph.TargetShape": 2, "GCurve.Type": 1},
                "limits": {},
                "param_states": [{"param_name": "Mesh.Enclosure", "is_set": 1, "value": {"Depth": 180.0}}],
            }
        )
        dividers = grid.findChildren(QFrame, "ConstraintColumnDivider")
        self.assertEqual(len(dividers), 4)

        captured: list[str] = []
        grid.request_open_editor.connect(captured.append)
        osse_button = None
        for button in grid.findChildren(QPushButton):
            if str(button.text()).strip() == "OSSE":
                osse_button = button
                break
        self.assertIsNotNone(osse_button)
        assert osse_button is not None
        osse_button.click()
        self.assertEqual(captured[-1], "Throat.Profile")

    def test_dashboard_action_wiring_remains_callable(self) -> None:
        page = DashboardPage()
        hit: list[str] = []
        page.request_new_batch.connect(lambda: hit.append("new"))
        page.request_manage_runs.connect(lambda: hit.append("manage"))
        page.request_open_export_dialog.connect(lambda: hit.append("export"))
        page.new_batch_btn.click()
        page.manage_runs_btn.click()
        page.export_btn.click()
        self.assertEqual(hit, ["new", "manage", "export"])


if __name__ == "__main__":
    unittest.main()
