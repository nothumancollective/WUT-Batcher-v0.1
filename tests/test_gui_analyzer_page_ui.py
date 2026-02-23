from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import (
    ANALYZER_PLOT_STYLE,
    AnalysePage,
    HeatmapCanvas,
    MainWindow,
    _AnalyzerRunDetailsDialog,
    _should_render_minus6_angle,
    apply_analyzer_plot_margins,
)
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QPushButton, QTableWidget, QTabWidget, QToolButton, QFrame
except ImportError:  # pragma: no cover
    Qt = None  # type: ignore[assignment]
    QApplication = None  # type: ignore[assignment]
    QComboBox = None  # type: ignore[assignment]
    QDialog = None  # type: ignore[assignment]
    QLabel = None  # type: ignore[assignment]
    QPushButton = None  # type: ignore[assignment]
    QTableWidget = None  # type: ignore[assignment]
    QTabWidget = None  # type: ignore[assignment]
    QToolButton = None  # type: ignore[assignment]
    QFrame = None  # type: ignore[assignment]


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
            project = service.create_project("Analyzer Nav", {})
            window.load_project(project)
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
            run_selector = page.findChild(QComboBox, "AnalyzerRunSelector")
            stage_selector = page.findChild(QComboBox, "AnalyzerStageCombo")
            target_selector = page.findChild(QComboBox, "AnalyzerTargetPresetCombo")
            band_selector = page.findChild(QComboBox, "AnalyzerBandPresetCombo")
            compute_btn = page.findChild(QPushButton, "AnalyzerComputeKpisButton")
            exclude_flagged = page.findChild(QToolButton, "AnalyzerExcludeFlaggedCheck")
            versions_btn = page.findChild(QToolButton, "AnalyzerVersionsButton")
            prev_btn = page.findChild(QToolButton, "AnalyzerVersionPrevButton")
            next_btn = page.findChild(QToolButton, "AnalyzerVersionNextButton")
            self.assertIsNotNone(batch_selector)
            self.assertIsNotNone(run_table)
            self.assertIsNotNone(run_selector if run_selector is not None else page.run_selector)
            self.assertIsNotNone(stage_selector)
            self.assertIsNotNone(target_selector)
            self.assertIsNotNone(band_selector)
            self.assertIsNotNone(compute_btn)
            self.assertIsNotNone(exclude_flagged)
            self.assertIsNotNone(versions_btn)
            self.assertIsNotNone(prev_btn)
            self.assertIsNotNone(next_btn)
            self.assertIsNone(page.findChild(QToolButton, "AnalyzerKpiPopoverButton"))
            assert run_table is not None
            self.assertEqual(run_table.selectionMode(), QTableWidget.ExtendedSelection)
            assert exclude_flagged is not None
            self.assertTrue(exclude_flagged.isCheckable())

    def test_stage_plot_canvases_apply_shared_plot_style_and_axis_labels(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_plot_style_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            heatmap_canvas = page._explorer_stage_panels["A"]["heatmap_canvas"]
            curve_canvas = page._explorer_stage_panels["B"]["curve_canvas"]
            self.assertTrue(str(heatmap_canvas._x_label).strip())
            self.assertTrue(str(heatmap_canvas._y_label).strip())
            curve_canvas.set_series(
                series=[
                    {
                        "label": "",
                        "show_legend": False,
                        "points": [{"freq_hz": 1000.0, "value": 1.0}, {"freq_hz": 2000.0, "value": 1.5}],
                    }
                ],
                x_scale_mode="log",
                x_label="Frequency (Hz, log)",
                y_label="Beamwidth error (deg)",
            )
            self.app.processEvents()
            self.assertTrue(str(curve_canvas._x_label).strip())
            self.assertTrue(str(curve_canvas._y_label).strip())
            self.assertEqual(tuple(heatmap_canvas._applied_plot_margins), apply_analyzer_plot_margins(has_legend=False))
            self.assertEqual(tuple(curve_canvas._applied_plot_margins), apply_analyzer_plot_margins(has_legend=False))

    def test_controls_row_uses_three_equal_tiles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_three_tiles_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            layout = page.analyzer_controls_row.layout()
            self.assertIsNotNone(layout)
            assert layout is not None
            self.assertEqual(layout.count(), 3)
            self.assertEqual(layout.stretch(0), 1)
            self.assertEqual(layout.stretch(1), 2)
            self.assertEqual(layout.stretch(2), 1)
            self.assertTrue(hasattr(page, "kpi_controls_tile"))
            self.assertEqual(len(getattr(page, "display_slot_frames", [])), 2)
            self.assertFalse(page.loading_label.isVisible())
            self.assertEqual(str(page.analysis_controls_tile.property("analyzerSurface") or ""), "1")
            self.assertEqual(str(page.kpi_controls_tile.property("analyzerSurface") or ""), "2")
            self.assertEqual(str(page.display_controls_tile.property("analyzerSurface") or ""), "1")

    def test_version_info_uses_dividers_and_plane_frame_is_flat_segment_container(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_dividers_segments_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            dividers = page.findChildren(QFrame, "AnalyzerInfoDivider")
            self.assertGreaterEqual(len(dividers), 2)
            flat_plane_frames = [
                frame
                for frame in page.findChildren(QFrame, "AnalyzerDisplaySlotFrame")
                if bool(frame.property("analyzerPlaneFlat"))
            ]
            self.assertEqual(len(flat_plane_frames), 1)
            self.assertTrue(bool(page.custom_band_low_label.property("analyzerBandEdgeLabel")))
            self.assertTrue(bool(page.custom_band_high_label.property("analyzerBandEdgeLabel")))

    def test_version_info_metric_values_are_right_aligned_for_compact_scanability(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_metric_alignment_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            for value_label in page._version_info_metric_labels.values():
                self.assertEqual(int(value_label.alignment() & Qt.AlignRight), int(Qt.AlignRight))
                self.assertTrue(bool(value_label.property("analyzerMetricValue")))

    def test_plot_titles_and_tile_gaps_use_compact_analyzer_style(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_plot_title_compact_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            panel = page._explorer_stage_panels["A"]
            title = panel["title_label"]
            self.assertTrue(bool(title.property("analyzerPlotTitle")))
            self.assertEqual(page.explorer_grid_layout.horizontalSpacing(), int(ANALYZER_PLOT_STYLE.tile_gap_px))
            self.assertEqual(page.explorer_grid_layout.verticalSpacing(), int(ANALYZER_PLOT_STYLE.tile_gap_px))
            self.assertEqual(page.compare_grid_layout.horizontalSpacing(), int(ANALYZER_PLOT_STYLE.tile_gap_px))
            self.assertEqual(page.compare_grid_layout.verticalSpacing(), int(ANALYZER_PLOT_STYLE.tile_gap_px))

    def test_mirrored_minus6_contour_filter_defaults_to_hidden(self) -> None:
        self.assertFalse(
            _should_render_minus6_angle(-20.0, angle_min=0.0, angle_max=90.0, show_mirrored=False)
        )
        self.assertTrue(
            _should_render_minus6_angle(-20.0, angle_min=0.0, angle_max=90.0, show_mirrored=True)
        )

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
            self.assertEqual(run_id_item.text(), "B001/V001")
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

    def test_filter_toggle_chip_labels_stay_static_when_toggled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_filter_chip_static_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            self.assertEqual(page.exclude_flagged_check.text(), "Exclude flagged")
            self.assertEqual(page.exclude_warnings_check.text(), "Exclude warnings")
            page.exclude_flagged_check.setChecked(True)
            page.exclude_warnings_check.setChecked(True)
            self.assertEqual(page.exclude_flagged_check.text(), "Exclude flagged")
            self.assertEqual(page.exclude_warnings_check.text(), "Exclude warnings")

    def test_missing_kpi_rows_show_missing_flag_text(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_missing_kpi_") as tmp:
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
                        "kpi_score": None,
                        "kpi_reason_codes": ["MISSING_KPI_ROWS"],
                    }
                ],
            }
            page._apply_runs_payload(payload)
            self.assertEqual(page.run_table.item(0, page.COL_SCORE).text(), "--")
            self.assertEqual(page.run_table.item(0, page.COL_FLAGS).text(), "missing")

    def test_run_selection_updates_selection_bar_stepper(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_summary_") as tmp:
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
                        "planes": ["H", "V", "D"],
                        "freq_count": 401,
                        "angle_count": 37,
                        "norm_angle_deg": 0.0,
                        "kpi_score": 88.2,
                        "kpi_e_bw": 1.5,
                        "kpi_e_cov": 0.9,
                        "kpi_r_spill": 0.13,
                    }
                ],
            }
            page._apply_runs_payload(payload)
            self.assertIn("B001/V001", page.versions_btn.text())
            self.assertTrue(page.run_details_btn.isEnabled())

    def test_selection_bar_keeps_version_details_and_refresh_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_selection_actions_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            self.assertEqual(page.run_details_btn.text(), "Version Details")
            self.assertEqual(page.compute_btn.text(), "Refresh KPIs")
            self.assertIsNone(page.findChild(QToolButton, "AnalyzerKpiPopoverButton"))
            self.assertFalse(page.run_summary_run_chip.isVisible())
            self.assertFalse(page.run_summary_planes_chip.isVisible())
            self.assertFalse(page.run_summary_score_chip.isVisible())
            self.assertFalse(page.run_summary_flags_chip.isVisible())

    def test_sweep_value_label_is_single_line_elided_with_tooltip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_sweep_elide_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page.resize(1920, 1080)
            page.show()
            self.app.processEvents()
            payload = {
                "project_id": "P001",
                "batch_id": "B001",
                "version_id": "V001",
                "run_id": "R001",
                "planes": ["H", "V", "D"],
                "sweep_parameters": {
                    "Throat.Len": 120.0,
                    "GCurve.AspectRatio": 1.45,
                    "Morph.Coverage": 60.0,
                    "Mesh.AngleStep": 2.0,
                },
            }
            page._update_version_information_panel(payload)
            self.app.processEvents()
            self.assertFalse(page.version_sweep_value_label.wordWrap())
            self.assertNotIn("\n", str(page.version_sweep_value_label.text() or ""))
            self.assertIn("Throat.Len", str(page.version_sweep_value_label.toolTip() or ""))
            self.assertGreaterEqual(int(page.version_info_col3.minimumWidth()), 220)
            self.assertGreaterEqual(int(page.version_sweep_value_label.width()), int(page.version_info_col2.width()) - 12)

    def test_version_bar_height_is_stable_across_selection_and_filter_updates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_version_bar_stable_") as tmp:
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
                        "planes": ["H", "V", "D"],
                        "kpi_score": 9.38,
                        "sweep_parameters": {"Throat.Len": 120.0},
                    },
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R002",
                        "version_id": "V002",
                        "planes": ["H", "V", "D"],
                        "kpi_score": 8.91,
                        "sweep_parameters": {
                            "Throat.Len": 130.0,
                            "GCurve.AspectRatio": 1.45,
                            "Morph.Coverage": 60.0,
                            "Mesh.AngleStep": 2.0,
                        },
                    },
                ],
            }
            page.resize(1800, 1000)
            page.show()
            page._apply_runs_payload(payload)
            self.app.processEvents()

            base_height = int(page.analyzer_controls_row.height())
            self.assertGreater(base_height, 0)

            page.exclude_flagged_check.setChecked(True)
            self.app.processEvents()
            self.assertEqual(int(page.analyzer_controls_row.height()), base_height)

            page.exclude_warnings_check.setChecked(True)
            self.app.processEvents()
            self.assertEqual(int(page.analyzer_controls_row.height()), base_height)

            page.run_table.selectRow(1)
            self.app.processEvents()
            self.assertEqual(int(page.analyzer_controls_row.height()), base_height)

            page.run_table.selectRow(0)
            self.app.processEvents()
            self.assertEqual(int(page.analyzer_controls_row.height()), base_height)
            page.close()

    def test_version_bar_widgets_are_updated_in_place(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_version_bar_in_place_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            payload_a = {
                "project_id": "P001",
                "batch_id": "B001",
                "version_id": "V001",
                "run_id": "R001",
                "planes": ["H", "V", "D"],
                "kpi_score": 9.38,
                "sweep_parameters": {"Throat.Len": 120.0},
            }
            payload_b = {
                "project_id": "P001",
                "batch_id": "B001",
                "version_id": "V002",
                "run_id": "R002",
                "planes": ["H", "V", "D"],
                "kpi_score": 8.71,
                "sweep_parameters": {"Throat.Len": 132.0, "Morph.Coverage": 55.0},
            }
            refs = {
                "row": page.analyzer_controls_row,
                "scores": page.version_info_scores_col,
                "col1": page.version_info_col1,
                "col2": page.version_info_col2,
                "col3": page.version_info_col3,
                "sweep": page.version_sweep_value_label,
                "ath": page.version_ath_params_value_label,
            }
            page._update_version_information_panel(payload_a)
            self.app.processEvents()
            page._update_version_information_panel(payload_b)
            self.app.processEvents()
            self.assertIs(refs["row"], page.analyzer_controls_row)
            self.assertIs(refs["scores"], page.version_info_scores_col)
            self.assertIs(refs["col1"], page.version_info_col1)
            self.assertIs(refs["col2"], page.version_info_col2)
            self.assertIs(refs["col3"], page.version_info_col3)
            self.assertIs(refs["sweep"], page.version_sweep_value_label)
            self.assertIs(refs["ath"], page.version_ath_params_value_label)

    def test_version_note_persists_per_project_batch_version(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_note_persist_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Analyzer Notes UI", {})
            paths = service.repo.project_paths(project.project_id, ensure=True)

            from app.tidy_dataset import TidyDatasetWriter

            writer = TidyDatasetWriter(paths.project_dir, library_root=service.settings.library_root)
            measurement = {
                "project_id": project.project_id,
                "batch_id": "B001",
                "version_id": "V001",
                "run_id": "R001",
                "graph_id": None,
                "orientation": "H",
                "orientation_raw": 0.0,
                "norm_angle_deg": 0.0,
                "data_level_type": "SPL",
                "data_base_unit": "dB",
                "data_absc_unit": "Hz",
                "freq_min_hz": 200.0,
                "freq_max_hz": 800.0,
                "freq_count": 2,
                "angle_min_deg": -30.0,
                "angle_max_deg": 30.0,
                "angle_step_deg": 60.0,
                "angle_count": 2,
                "angles_deg_json": "[-30, 30]",
                "source_file": "V001_H.txt",
                "file_hash": "hash_note_ui",
                "export_meta_json": "{}",
                "created_at": "2026-02-23T10:00:00+00:00",
            }
            points = [
                {"freq_index": 0, "angle_index": 0, "freq_hz": 200.0, "angle_deg": -30.0, "re": 0.7, "im": 0.0},
                {"freq_index": 0, "angle_index": 1, "freq_hz": 200.0, "angle_deg": 30.0, "re": 0.7, "im": 0.0},
            ]
            writer.write_polar_measurement(measurement=measurement, points=points)

            page = AnalysePage(service=service)
            page.set_project_context(project.project_id)
            rows = service.analyzer_list_polar_runs(project_id=project.project_id, batch_id="B001", source="project")
            page._apply_runs_payload({"mode": "runs", "project_id": project.project_id, "batch_id": "B001", "runs": rows})
            page.version_note_edit.setPlainText("keep this candidate")
            page._persist_pending_version_note()

            page_reload = AnalysePage(service=service)
            page_reload.set_project_context(project.project_id)
            rows_reload = service.analyzer_list_polar_runs(project_id=project.project_id, batch_id="B001", source="project")
            page_reload._apply_runs_payload(
                {"mode": "runs", "project_id": project.project_id, "batch_id": "B001", "runs": rows_reload}
            )
            self.assertEqual(str(page_reload.version_note_edit.toPlainText() or ""), "keep this candidate")
            page.close()
            page_reload.close()

    def test_version_pin_persists_per_project_batch_version_run_and_marks_compare_slot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_pin_persist_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Analyzer Pin UI", {})
            payload = {
                "mode": "runs",
                "project_id": project.project_id,
                "batch_id": "B001",
                "runs": [
                    {
                        "project_id": project.project_id,
                        "batch_id": "B001",
                        "run_id": "R001",
                        "version_id": "V001",
                        "planes": ["H", "V", "D"],
                    }
                ],
            }
            page = AnalysePage(service=service)
            page.set_project_context(project.project_id)
            page._apply_runs_payload(payload)
            self.assertFalse(page.version_pin_btn.isChecked())
            page.version_pin_btn.click()
            self.app.processEvents()
            self.assertTrue(page.version_pin_btn.isChecked())

            page_reload = AnalysePage(service=service)
            page_reload.set_project_context(project.project_id)
            page_reload._apply_runs_payload(payload)
            self.assertTrue(page_reload.version_pin_btn.isChecked())
            page_reload._set_compare_candidates([dict(payload["runs"][0])])
            selection_text = str(page_reload.compare_slots_table.item(0, 1).text() or "")
            self.assertIn("[PIN]", selection_text)
            page.close()
            page_reload.close()

    def test_ath_param_visibility_pref_persists_per_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_ath_pref_") as tmp:
            service = _build_service(Path(tmp))
            project = service.create_project("Analyzer ATH Pref", {})
            page = AnalysePage(service=service)
            page.set_project_context(project.project_id)
            page._set_ath_param_visibility("Throat.Profile", True)
            page._set_ath_param_visibility("GCurve.Type", True)

            page_reload = AnalysePage(service=service)
            page_reload.set_project_context(project.project_id)
            self.assertIn("Throat.Profile", page_reload._ath_visible_param_keys)
            self.assertIn("GCurve.Type", page_reload._ath_visible_param_keys)
            page.close()
            page_reload.close()

    def test_version_stepper_arrows_navigate_and_disable_at_edges(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_stepper_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            payload = {
                "mode": "runs",
                "project_id": "P001",
                "batch_id": "B001",
                "runs": [
                    {"project_id": "P001", "batch_id": "B001", "run_id": "R001", "version_id": "V001", "planes": ["H"]},
                    {"project_id": "P001", "batch_id": "B001", "run_id": "R002", "version_id": "V002", "planes": ["H"]},
                    {"project_id": "P001", "batch_id": "B001", "run_id": "R003", "version_id": "V003", "planes": ["H"]},
                ],
            }
            page._apply_runs_payload(payload)
            self.assertFalse(page.version_prev_btn.isEnabled())
            self.assertTrue(page.version_next_btn.isEnabled())
            page.version_next_btn.click()
            self.app.processEvents()
            self.assertIn("B001/V002", page.versions_btn.text())
            self.assertTrue(page.version_prev_btn.isEnabled())
            page.version_next_btn.click()
            self.app.processEvents()
            self.assertIn("B001/V003", page.versions_btn.text())
            self.assertFalse(page.version_next_btn.isEnabled())

    def test_unknown_plane_token_is_kept_as_fallback_plane(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_unknown_plane_") as tmp:
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
                        "planes": ["X3_17.5"],
                        "freq_count": 101,
                        "angle_count": 19,
                    }
                ],
            }
            page._apply_runs_payload(payload)
            selected_rows = page._selected_row_payloads()
            self.assertEqual(len(selected_rows), 1)
            selected = dict(selected_rows[0])
            self.assertEqual(page._available_planes(selected), ["X3_17.5"])
            self.assertEqual(page._selected_plane(), "X3_17.5")

    def test_toolbar_has_single_visible_compute_button(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_compute_btn_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            compute_buttons = [
                btn
                for btn in page.findChildren(QPushButton, "AnalyzerComputeKpisButton")
            ]
            self.assertEqual(len(compute_buttons), 1)
            self.assertIs(compute_buttons[0], page.compute_btn)
            self.assertEqual(int(page.compute_btn.minimumHeight()), int(page.versions_btn.minimumHeight()))
            self.assertEqual(int(page.compute_btn.maximumHeight()), int(page.versions_btn.maximumHeight()))
            self.assertTrue(bool(page.compute_btn.property("analyzerAction")))

    def test_clamp_default_is_minus_20_db(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_clamp_default_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            self.assertEqual(float(page.heatmap_clamp_min_spin.value()), -20.0)

    def test_versions_button_opens_picker_and_updates_selection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_versions_popover_") as tmp:
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
                        "kpi_score": 80.0,
                    },
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R002",
                        "version_id": "V002",
                        "planes": ["H", "V", "D"],
                        "kpi_score": 90.0,
                    },
                ],
            }
            page._apply_runs_payload(payload)
            target = dict(payload["runs"][1])
            with patch("app.gui._AnalyzerVersionPickerDialog.exec", autospec=True, return_value=QDialog.Accepted) as exec_mock:
                with patch(
                    "app.gui._AnalyzerVersionPickerDialog.selected_payload",
                    autospec=True,
                    return_value=target,
                ):
                    page._open_version_picker()
            self.assertEqual(exec_mock.call_count, 1)
            current_item = page.run_table.item(page.run_table.currentRow(), 0)
            self.assertIsNotNone(current_item)
            assert current_item is not None
            self.assertEqual(current_item.text(), "B001/V002")

    def test_heatmap_orientation_places_positive_angles_up(self) -> None:
        canvas = HeatmapCanvas()
        canvas.resize(360, 240)
        matrix = [
            [-30.0, -30.0, -30.0],
            [0.0, 0.0, 0.0],
        ]
        canvas.set_heatmap_data(
            matrix=matrix,
            freqs_hz=[200.0, 1000.0, 5000.0],
            angles_deg=[-10.0, 10.0],
            clamp_enabled=True,
            clamp_min_db=-30.0,
            show_raw_bins=False,
            ref_angle_deg=0.0,
            status="",
        )
        pixmap = canvas.pixmap()
        self.assertIsNotNone(pixmap)
        assert pixmap is not None
        image = pixmap.toImage()
        top = image.pixelColor(170, 70)
        bottom = image.pixelColor(170, 165)
        top_luma = int(top.red()) + int(top.green()) + int(top.blue())
        bottom_luma = int(bottom.red()) + int(bottom.green()) + int(bottom.blue())
        self.assertGreater(top_luma, bottom_luma)

    def test_details_dialog_open_path_is_callable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_details_") as tmp:
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
                        "run_id": "R100",
                        "version_id": "V100",
                        "planes": ["H", "V"],
                        "freq_count": 64,
                        "angle_count": 9,
                    }
                ],
            }
            page._apply_runs_payload(payload)
            with patch("app.gui._AnalyzerRunDetailsDialog.exec", autospec=True, return_value=0) as exec_mock:
                page._open_run_details_dialog()
                self.assertEqual(exec_mock.call_count, 1)

    def test_run_details_dialog_shows_zero_norm_angle_value(self) -> None:
        payload = {
            "project_id": "P001",
            "batch_id": "B001",
            "run_id": "R001",
            "version_id": "V001",
            "planes": ["H", "V"],
            "norm_angle_deg": 0.0,
            "norm_angle_source": "batch_export_settings",
            "norm_angle_note": "Derived from batches.sim_export_params export_specs[].options.norm_angle.",
        }
        dialog = _AnalyzerRunDetailsDialog(payload=payload, parent=None)
        texts = [label.text() for label in dialog.findChildren(QLabel)]
        # Fallback-safe assertion: 0.00 must be present and the field must not collapse to '--'.
        self.assertIn("0.00", texts)

    def test_explorer_compare_tabs_switch_without_errors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2x_tabs_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            tabs = page.findChild(QTabWidget, "AnalyzerPlotTabs")
            self.assertIsNotNone(tabs)
            assert tabs is not None
            self.assertGreaterEqual(tabs.count(), 2)
            tabs.setCurrentIndex(1)
            self.assertEqual(tabs.tabText(tabs.currentIndex()).lower(), "compare")
            tabs.setCurrentIndex(0)
            self.assertEqual(tabs.tabText(tabs.currentIndex()).lower(), "explorer")

    def test_stage_switch_updates_explorer_2x2_titles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_stage_grid_titles_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            self.assertEqual(sorted(page._explorer_stage_panels.keys()), ["A", "B", "C", "D"])
            self.assertIn("Beamwidth Error", page._explorer_stage_panels["B"]["title_label"].text())
            for idx in range(page.stage_selector.count()):
                if str(page.stage_selector.itemData(idx) or "") == "stabilization":
                    page.stage_selector.setCurrentIndex(idx)
                    break
            self.assertIn("DI Proxy", page._explorer_stage_panels["B"]["title_label"].text())
            self.assertIn("Pattern Smoothness", page._explorer_stage_panels["C"]["title_label"].text())
            self.assertIn("Plane Consistency", page._explorer_stage_panels["D"]["title_label"].text())

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
                "angles_deg": [-10.0, 10.0],
                "beamwidth_curve": [
                    {"freq_hz": 200.0, "beamwidth_deg": 60.0},
                    {"freq_hz": 400.0, "beamwidth_deg": 62.0},
                ],
                "ref_angle_deg": 0.0,
                "insufficient_bw": False,
                "message": "",
                "stage_plot": {
                    "curves": {
                        "beamwidth": [
                            {"freq_hz": 200.0, "beamwidth_deg": 60.0},
                            {"freq_hz": 400.0, "beamwidth_deg": 62.0},
                        ],
                        "e_bw": [
                            {"freq_hz": 200.0, "value": 0.5},
                            {"freq_hz": 400.0, "value": 0.8},
                        ],
                        "e_cov": [{"freq_hz": 200.0, "value": 0.3}],
                        "r_spill": [{"freq_hz": 200.0, "value": 0.1}],
                    },
                    "heatmap_overlays": {
                        "minus6_contour": [
                            {"freq_hz": 200.0, "left_angle_deg": -30.0, "right_angle_deg": 30.0},
                            {"freq_hz": 400.0, "left_angle_deg": -31.0, "right_angle_deg": 31.0},
                        ],
                        "target_half_window_deg": 30.0,
                    },
                },
            }
            with patch.object(service, "analyzer_load_stage_plot_payload", autospec=True, return_value=fake_plot) as load_mock:
                page._start_plot_request()
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    self.app.processEvents()
                    if "ready" in page.plot_loading_label.text().lower():
                        break
                    if page._plot_thread is None:
                        break
                    time.sleep(0.01)
                self.app.processEvents()
                self.assertGreaterEqual(load_mock.call_count, 1)
                self.assertIn("ready", page.plot_loading_label.text().lower())
                pixmap = page.heatmap_canvas.pixmap()
                self.assertIsNotNone(pixmap)
                assert pixmap is not None
                self.assertFalse(pixmap.isNull())
                self.assertEqual(float(page.heatmap_canvas._target_half_window_deg or 0.0), 30.0)
                self.assertGreater(len(page.heatmap_canvas._minus6_contour), 0)
                curve_series = list(page._explorer_stage_panels["B"]["curve_canvas"]._series)
                self.assertGreaterEqual(len(curve_series), 1)
                self.assertNotIn("Selected", [str(item.get("label") or "") for item in curve_series])

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

            with patch.object(service, "analyzer_load_stage_plot_payload", autospec=True, side_effect=_slow_loader):
                page.run_table.selectRow(0)
                page._start_plot_request()
                page.run_table.selectRow(1)
                page._start_plot_request()
                deadline = time.time() + 3.0
                while time.time() < deadline and page._plot_thread is not None:
                    self.app.processEvents()
                    time.sleep(0.01)
                self.app.processEvents()
                self.assertIn(
                    page.plot_loading_label.text().lower(),
                    {"plot ready.", "ready.", "plot request canceled.", "loading h plane...", "canceling plot request..."},
                )


if __name__ == "__main__":
    unittest.main()
