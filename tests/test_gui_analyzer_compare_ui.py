from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import AnalysePage
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtWidgets import QApplication, QComboBox, QTableWidget
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QComboBox = None  # type: ignore[assignment]
    QTableWidget = None  # type: ignore[assignment]


def _build_service(tmp_root: Path) -> OrchestratorService:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / "library"
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store)


@unittest.skipIf(QApplication is None, "PySide6 is required")
class AnalyzerCompareUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _sample_runs_payload(self, project_id: str) -> dict:
        return {
            "mode": "runs",
            "project_id": project_id,
            "batch_id": "B001",
            "runs": [
                {
                    "project_id": project_id,
                    "batch_id": "B001",
                    "run_id": "R001",
                    "version_id": "V001",
                    "planes": ["H", "V"],
                    "kpi_score": 88.0,
                    "kpi_b_pc_oct": 2.0,
                    "kpi_e_bw": 1.2,
                    "kpi_e_cov": 0.8,
                    "kpi_r_spill": 0.12,
                    "kpi_flags_count": 0,
                },
                {
                    "project_id": project_id,
                    "batch_id": "B002",
                    "run_id": "R010",
                    "version_id": "V010",
                    "planes": ["H", "V", "D"],
                    "kpi_score": 77.0,
                    "kpi_b_pc_oct": 1.8,
                    "kpi_e_bw": 1.5,
                    "kpi_e_cov": 0.9,
                    "kpi_r_spill": 0.21,
                    "kpi_flags_count": 1,
                },
            ],
        }

    def test_save_and_load_analysis_roundtrip_restores_compare_set(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2c_compare_save_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Compare Save", {})
            page = AnalysePage(service=service)
            page.set_project_context(project.project_id)
            page._apply_runs_payload(self._sample_runs_payload(project.project_id))
            page._set_compare_candidates(page._selected_row_payloads() or [page._all_run_rows[0]])

            with patch("app.gui.QInputDialog.getText", return_value=("Analysis A", True)):
                page._save_compare_analysis()

            analyses = service.analyzer_list_analyses(project_id=project.project_id)
            self.assertEqual(len(analyses), 1)

            page._compare_candidates = []
            page._update_compare_slots()
            page._refresh_saved_analyses()
            self.assertGreater(page.compare_analysis_selector.count(), 0)
            page.compare_analysis_selector.setCurrentIndex(0)
            page._load_selected_analysis()

            self.assertGreaterEqual(page.compare_slots_table.rowCount(), 1)
            first_run = page.compare_slots_table.item(0, 2)
            self.assertIsNotNone(first_run)
            assert first_run is not None
            self.assertIn(first_run.text(), {"R001", "R010"})

    def test_autopick_result_is_capped_to_five_candidates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2c_compare_autopick_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            payload = {
                "candidates": [
                    {
                        "project_id": "P001",
                        "batch_id": f"B{idx:03d}",
                        "run_id": f"R{idx:03d}",
                        "version_id": f"V{idx:03d}",
                        "kpi_score": 90.0 - idx,
                    }
                    for idx in range(1, 8)
                ]
            }
            page._autopick_request_id = 1
            page._on_autopick_finished(1, payload)
            self.assertLessEqual(page.compare_slots_table.rowCount(), 5)
            self.assertEqual(page.compare_slots_table.rowCount(), 5)

    def test_compare_tab_contains_slots_table_and_saved_selector(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2c_compare_layout_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            slots_table = page.findChild(QTableWidget, "AnalyzerCompareSlotsTable")
            saved_selector = page.findChild(QComboBox, "AnalyzerAnalysisSelector")
            self.assertIsNotNone(slots_table)
            self.assertIsNotNone(saved_selector)


if __name__ == "__main__":
    unittest.main()
