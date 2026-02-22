from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import AnalysePage, MainWindow
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QPushButton, QTableWidget
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QCheckBox = None  # type: ignore[assignment]
    QComboBox = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]
    QTableWidget = None  # type: ignore[assignment]


def _build_service(tmp_root: Path) -> OrchestratorService:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / "library"
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store)


@unittest.skipIf(QApplication is None, "PySide6 is required")
class AnalyzerPageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_analyse_modebar_opens_analyzer_page(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui1c_nav_") as tmp:
            service = _build_service(Path(tmp))
            window = MainWindow(service)
            with patch.object(window.analyse_page, "refresh_data", autospec=True) as refresh_mock:
                window.analyse_mode_button.click()
                self.assertIs(window.stack.currentWidget(), window.analyse_page)
                self.assertTrue(window.analyse_mode_button.isChecked())
                self.assertEqual(refresh_mock.call_count, 1)
            window.close()

    def test_left_pane_contains_batch_selector_and_run_table(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui1c_layout_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            batch_selector = page.findChild(QComboBox, "AnalyzerBatchCombo")
            run_table = page.findChild(QTableWidget, "AnalyzerRunTable")
            stage_selector = page.findChild(QComboBox, "AnalyzerStageCombo")
            target_selector = page.findChild(QComboBox, "AnalyzerTargetPresetCombo")
            band_selector = page.findChild(QComboBox, "AnalyzerBandPresetCombo")
            compute_btn = page.findChild(QPushButton, "AnalyzerComputeKpisButton")
            exclude_flagged = page.findChild(QCheckBox, "AnalyzerExcludeFlaggedCheck")
            self.assertIsNotNone(batch_selector)
            self.assertIsNotNone(run_table)
            self.assertIsNotNone(stage_selector)
            self.assertIsNotNone(target_selector)
            self.assertIsNotNone(band_selector)
            self.assertIsNotNone(compute_btn)
            self.assertIsNotNone(exclude_flagged)
            assert run_table is not None
            self.assertEqual(run_table.selectionMode(), QTableWidget.ExtendedSelection)

    def test_selecting_batch_requests_background_run_load(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui1c_batch_change_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._selector_sync_guard = True
            page.batch_selector.clear()
            page.batch_selector.addItem("B001", "B001")
            page.batch_selector.addItem("B002", "B002")
            page.batch_selector.setCurrentIndex(0)
            page._selector_sync_guard = False
            with patch.object(page, "_request_runs_for_selected_batch", autospec=True) as request_mock:
                page.batch_selector.setCurrentIndex(1)
                self.assertEqual(request_mock.call_count, 1)

    def test_run_table_populates_from_mocked_worker_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui1c_rows_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._metadata_request_id = 7
            payload = {
                "mode": "runs",
                "project_id": "P001",
                "batch_id": "B001",
                "runs": [
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R001",
                        "version_id": "V001",
                        "planes": ["H", "V", "D"],
                        "freq_count": 401,
                        "angle_count": 19,
                        "norm_angle_deg": 10.0,
                        "kpi_score": 87.5,
                        "kpi_b_pc_oct": 2.2,
                        "kpi_e_bw": 1.4,
                        "kpi_e_cov": 0.8,
                        "kpi_r_spill": 0.11,
                        "kpi_flags_count": 0,
                        "kpi_flagged": False,
                        "imported_at": "2026-02-21T10:00:00+00:00",
                        "created_at": "2026-02-21T09:45:00+00:00",
                        "source_files": ["result_v001polar.txt"],
                        "file_hashes": ["hash001"],
                    }
                ],
            }
            page._on_metadata_ready(7, payload)
            self.assertEqual(page.run_table.rowCount(), 1)
            run_id_item = page.run_table.item(0, 0)
            planes_item = page.run_table.item(0, 2)
            self.assertIsNotNone(run_id_item)
            self.assertIsNotNone(planes_item)
            assert run_id_item is not None and planes_item is not None
            self.assertEqual(run_id_item.text(), "R001")
            self.assertEqual(planes_item.text(), "H/V/D")
            self.assertEqual(page.run_table.item(0, 6).text(), "87.50")
            self.assertEqual(page.run_table.item(0, 7).text(), "2.20")

    def test_filter_controls_reduce_rows_by_flag_and_score(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2a_filter_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            payload = {
                "mode": "runs",
                "project_id": "P001",
                "batch_id": "B001",
                "runs": [
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R001",
                        "version_id": "V001",
                        "planes": ["H", "V"],
                        "freq_count": 101,
                        "angle_count": 19,
                        "norm_angle_deg": 0.0,
                        "kpi_score": 92.0,
                        "kpi_flags_count": 0,
                        "kpi_flagged": False,
                    },
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R002",
                        "version_id": "V002",
                        "planes": ["H", "V"],
                        "freq_count": 101,
                        "angle_count": 19,
                        "norm_angle_deg": 0.0,
                        "kpi_score": 55.0,
                        "kpi_flags_count": 2,
                        "kpi_flagged": True,
                    },
                ],
            }
            page._apply_runs_payload(payload)
            self.assertEqual(page.run_table.rowCount(), 2)
            page.exclude_flagged_check.setChecked(True)
            self.assertEqual(page.run_table.rowCount(), 1)
            page.exclude_flagged_check.setChecked(False)
            page.min_score_spin.setValue(90.0)
            self.assertEqual(page.run_table.rowCount(), 1)
            page.min_score_spin.setValue(95.0)
            self.assertEqual(page.run_table.rowCount(), 0)

    def test_run_selection_loads_explorer_plot_in_background(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2b_plot_load_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            payload = {
                "mode": "runs",
                "project_id": "P001",
                "batch_id": "B001",
                "runs": [
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R001",
                        "version_id": "V001",
                        "planes": ["H", "V"],
                        "freq_count": 64,
                        "angle_count": 9,
                    }
                ],
            }
            page._apply_runs_payload(payload)
            fake_plot = {
                "cache_hit": False,
                "display_freqs_hz": [200.0, 400.0, 800.0],
                "display_matrix_db": [[0.0, -2.0, -4.0], [-1.0, -3.0, -6.0]],
                "beamwidth_curve": [
                    {"freq_hz": 200.0, "beamwidth_deg": 60.0},
                    {"freq_hz": 400.0, "beamwidth_deg": 62.0},
                ],
                "ref_angle_deg": 0.0,
                "insufficient_bw": False,
                "message": "",
            }
            with patch.object(service, "analyzer_load_plot_payload", autospec=True, return_value=fake_plot) as load_mock:
                page._start_plot_request()
                deadline = time.time() + 2.0
                while time.time() < deadline and page._plot_thread is not None:
                    self.app.processEvents()
                    time.sleep(0.01)
                self.app.processEvents()
                self.assertGreaterEqual(load_mock.call_count, 1)
                self.assertIn("ready", page.plot_loading_label.text().lower())
                pixmap = page.heatmap_canvas.pixmap()
                self.assertIsNotNone(pixmap)
                assert pixmap is not None
                self.assertFalse(pixmap.isNull())

    def test_switching_runs_during_plot_load_keeps_ui_stable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2b_plot_switch_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            payload = {
                "mode": "runs",
                "project_id": "P001",
                "batch_id": "B001",
                "runs": [
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R001",
                        "version_id": "V001",
                        "planes": ["H", "V"],
                        "freq_count": 64,
                        "angle_count": 9,
                    },
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R002",
                        "version_id": "V002",
                        "planes": ["H", "V"],
                        "freq_count": 64,
                        "angle_count": 9,
                    },
                ],
            }
            page._apply_runs_payload(payload)

            def _slow_loader(*_args, **kwargs):
                cancel_check = kwargs.get("cancel_check")
                for _ in range(30):
                    if callable(cancel_check) and bool(cancel_check()):
                        raise RuntimeError("canceled")
                    time.sleep(0.005)
                return {
                    "cache_hit": False,
                    "display_freqs_hz": [200.0, 400.0],
                    "display_matrix_db": [[0.0, -1.0], [-2.0, -3.0]],
                    "beamwidth_curve": [{"freq_hz": 200.0, "beamwidth_deg": 60.0}],
                    "ref_angle_deg": 0.0,
                    "insufficient_bw": True,
                    "message": "",
                }

            with patch.object(service, "analyzer_load_plot_payload", autospec=True, side_effect=_slow_loader):
                page.run_table.selectRow(0)
                page._start_plot_request()
                page.run_table.selectRow(1)
                page._start_plot_request()
                deadline = time.time() + 3.0
                while time.time() < deadline and page._plot_thread is not None:
                    self.app.processEvents()
                    time.sleep(0.01)
                self.app.processEvents()
                self.assertIn(page.plot_loading_label.text().lower(), {"plot ready.", "ready.", "plot request canceled."})


if __name__ == "__main__":
    unittest.main()
