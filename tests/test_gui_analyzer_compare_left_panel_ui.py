from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import AnalysePage
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    Qt = None  # type: ignore[assignment]
    QTest = None  # type: ignore[assignment]
    QApplication = None  # type: ignore[assignment]


def _build_service(tmp_root: Path) -> OrchestratorService:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / "library"
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store)


def _header_labels(page: AnalysePage) -> list[str]:
    return [
        str(page.compare_slots_table.horizontalHeaderItem(i).text() or "")
        for i in range(page.compare_slots_table.columnCount())
    ]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class AnalyzerCompareLeftPanelUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _sample_candidates(self) -> list[dict]:
        return [
            {
                "project_id": "P001",
                "batch_id": "B001",
                "run_id": "R001",
                "version_id": "V001",
                "kpi_score": 88.0,
                "kpi_b_pc_oct": 2.0,
                "kpi_e_bw": 1.3,
                "kpi_e_cov": 0.8,
                "kpi_r_spill": 0.11,
                "kpi_di_proxy": 2.8,
                "kpi_s_theta": 0.28,
                "kpi_e_sym_shape": 0.14,
                "kpi_r_off": 2.1,
                "planes": ["H", "V"],
            },
            {
                "project_id": "P001",
                "batch_id": "B002",
                "run_id": "R002",
                "version_id": "V002",
                "kpi_score": 84.0,
                "kpi_b_pc_oct": 1.8,
                "kpi_e_bw": 1.7,
                "kpi_e_cov": 1.0,
                "kpi_r_spill": 0.19,
                "kpi_di_proxy": 2.3,
                "kpi_s_theta": 0.35,
                "kpi_e_sym_shape": 0.20,
                "kpi_r_off": 2.6,
                "planes": ["H", "V", "D"],
            },
        ]

    def test_compare_table_has_five_fixed_slots(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_compare_left_slots_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            self.assertEqual(page.compare_slots_table.rowCount(), 5)
            self.assertEqual(page.compare_slots_table.item(0, 0).text(), "V---")
            self.assertEqual(page.compare_slots_table.item(4, 0).text(), "V---")

    def test_stage_switch_updates_compare_kpi_columns(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_compare_left_stage_cols_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._set_compare_candidates(self._sample_candidates())

            page._set_combo_current_by_data(page.stage_selector, "concept")
            self.app.processEvents()
            concept_headers = _header_labels(page)
            self.assertIn("Pattern Ctrl (oct)", concept_headers)
            self.assertIn("BW Err (deg)", concept_headers)

            page._set_combo_current_by_data(page.stage_selector, "stabilization")
            self.app.processEvents()
            stabilization_headers = _header_labels(page)
            self.assertIn("DI Trend (dB)", stabilization_headers)
            self.assertIn("Plane Consistency", stabilization_headers)
            self.assertNotIn("BW Err (deg)", stabilization_headers)

            page._set_combo_current_by_data(page.stage_selector, "final")
            self.app.processEvents()
            final_headers = _header_labels(page)
            self.assertIn("Off-axis Ripple (dB)", final_headers)
            self.assertIn("Smoothness", final_headers)
            self.assertNotIn("DI Trend (dB)", final_headers)

    def test_clicking_slot_updates_active_candidate_and_heatmap_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_compare_left_active_slot_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._set_compare_candidates(self._sample_candidates())

            page.compare_slots_table.selectRow(1)
            self.app.processEvents()

            self.assertEqual(page._selected_compare_slot_index, 1)
            self.assertEqual(page.compare_heatmap_selector.currentIndex(), 1)
            self.assertEqual(int(page.compare_heatmap_selector.currentData()), 1)

    def test_remove_slot_clears_row_without_crash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_compare_left_remove_slot_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._set_compare_candidates(self._sample_candidates())

            page._remove_compare_candidate(0)

            self.assertEqual(page.compare_slots_table.rowCount(), 5)
            first_item = page.compare_slots_table.item(0, 0)
            second_item = page.compare_slots_table.item(1, 0)
            self.assertIsNotNone(first_item)
            self.assertIsNotNone(second_item)
            assert first_item is not None
            assert second_item is not None
            self.assertEqual(first_item.text(), "V002")
            self.assertEqual(second_item.text(), "V---")

    def test_compare_drawer_width_contract_and_no_horizontal_scroll(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_compare_drawer_width_contract_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._set_compare_candidates(self._sample_candidates())
            page.show()
            self.app.processEvents()
            page._set_compare_drawer_expanded(True)
            self.app.processEvents()
            for width, height in ((1920, 1080), (1366, 768), (1100, 700)):
                page.resize(width, height)
                self.app.processEvents()
                workspace_width = max(int(page.compare_workspace.width()), 1)
                expanded_width = int(page.compare_drawer.width())
                self.assertGreaterEqual(expanded_width, int(workspace_width * 0.50))
                self.assertLessEqual(expanded_width, int(workspace_width * 0.72))
                self.assertEqual(page.compare_slots_table.horizontalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
            page._set_compare_drawer_expanded(False)
            self.app.processEvents()
            self.assertGreaterEqual(int(page.compare_drawer.width()), 72)
            self.assertLessEqual(int(page.compare_drawer.width()), 96)

    def test_remove_column_remains_reachable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_compare_left_remove_reachable_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._set_compare_candidates(self._sample_candidates())
            page.resize(1366, 768)
            page.show()
            self.app.processEvents()
            headers = _header_labels(page)
            remove_col = headers.index("Remove")
            button = page.compare_slots_table.cellWidget(0, remove_col)
            self.assertIsNotNone(button)
            self.assertGreaterEqual(page.compare_slots_table.columnWidth(remove_col), 70)
            assert button is not None
            self.assertLessEqual(button.sizeHint().width(), page.compare_slots_table.columnWidth(remove_col))

    def test_compare_drawer_collapsed_compact_rows_show_v_tokens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_compare_drawer_compact_v_tokens_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._set_compare_candidates(self._sample_candidates())
            page.show()
            self.app.processEvents()
            page._set_compare_drawer_expanded(False)
            self.app.processEvents()
            first_btn = page.compare_drawer_compact_buttons[0]
            second_btn = page.compare_drawer_compact_buttons[1]
            self.assertIn("V001", first_btn.text())
            self.assertIn("V002", second_btn.text())
            self.assertNotIn("B001", first_btn.text())


if __name__ == "__main__":
    unittest.main()
