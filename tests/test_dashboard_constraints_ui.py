from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import ConstraintSummaryGrid, DashboardPage

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QFrame, QListWidgetItem, QPushButton, QSplitter, QToolButton
except ImportError:  # pragma: no cover
    Qt = None  # type: ignore[assignment]
    QApplication = None  # type: ignore[assignment]
    QFrame = None  # type: ignore[assignment]
    QListWidgetItem = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]
    QSplitter = None  # type: ignore[assignment]
    QToolButton = None  # type: ignore[assignment]


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

    def test_dashboard_workspace_split_contains_batch_list_and_lineage_pane(self) -> None:
        page = DashboardPage()
        splitter = page.findChild(QSplitter, "DashboardWorkspaceSplitter")
        self.assertIsNotNone(splitter)
        assert splitter is not None
        self.assertEqual(splitter.count(), 2)
        sizes = splitter.sizes()
        self.assertEqual(len(sizes), 2)
        self.assertTrue(all(int(value) > 0 for value in sizes))
        self.assertEqual(page.constraints_summary.height(), 104)

    def test_constraints_bar_drawer_toggle_is_enabled_for_dense_payload(self) -> None:
        page = DashboardPage()
        payload = {
            "fixed_params": {
                "Length": 220.0,
                "Throat.Profile": 1,
                "Morph.TargetShape": 2,
                "GCurve.Type": 1,
                "Coverage.Angle": 60.0,
                "Throat.Diameter": 30.0,
                "Term.Planar": 1,
                "CircArc.Radius": 18.0,
            },
            "limits": {},
            "param_states": [{"param_name": "Mesh.Enclosure", "is_set": 1, "value": {"Depth": 180.0}}],
        }
        page.resize(1280, 860)
        page.set_constraints_payload(payload)
        self.app.processEvents()
        toggle = page.constraints_summary.drawer_toggle_btn
        self.assertIsNotNone(toggle)
        assert isinstance(toggle, QToolButton)
        self.assertTrue(toggle.isEnabled())
        toggle.click()
        self.app.processEvents()
        self.assertTrue(bool(page._constraints_drawer_expanded))

    def test_lineage_pane_renders_graph_nodes_for_batches(self) -> None:
        page = DashboardPage()
        rows = [
            {
                "batch_id": "B001",
                "batch_name": "Parent",
                "created_at": "2026-02-26T10:00:00+00:00",
                "created_via": "manual",
                "parent_batch_id": None,
                "created_from_version_id": None,
            },
            {
                "batch_id": "B002",
                "batch_name": "Child",
                "created_at": "2026-02-26T10:10:00+00:00",
                "created_via": "iterate",
                "parent_batch_id": "B001",
                "created_from_version_id": "V001",
            },
        ]
        page.set_batch_lineage_rows(rows)
        self.app.processEvents()
        self.assertGreaterEqual(len(page.lineage_pane.scene.items()), 3)
        self.assertIn("B001", page.lineage_pane._node_items)
        self.assertIn("B002", page.lineage_pane._node_items)

    def test_lineage_node_activation_selects_batch_and_emits_edit_request(self) -> None:
        page = DashboardPage()
        item = QListWidgetItem("B001 | Parent")
        item.setData(Qt.UserRole, "B001")
        page.batch_list.addItem(item)
        page.set_batch_lineage_rows(
            [
                {
                    "batch_id": "B001",
                    "batch_name": "Parent",
                    "created_at": "2026-02-26T10:00:00+00:00",
                    "created_via": "manual",
                    "parent_batch_id": None,
                    "created_from_version_id": None,
                }
            ]
        )
        seen: list[str] = []
        page.request_edit_batch.connect(seen.append)
        page.lineage_pane.batch_activated.emit("B001")
        self.app.processEvents()
        self.assertEqual(seen, ["B001"])
        current = page.batch_list.currentItem()
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(str(current.data(Qt.UserRole)), "B001")


if __name__ == "__main__":
    unittest.main()
