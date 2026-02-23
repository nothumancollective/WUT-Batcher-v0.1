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
            first_run = page.compare_slots_table.item(0, 1)
            self.assertIsNotNone(first_run)
            assert first_run is not None
            self.assertIn(first_run.text(), {"B001/V001", "B002/V010"})

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

    def test_autopick_accepts_score_key_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2c_compare_autopick_score_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            payload = {
                "candidates": [
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R001",
                        "version_id": "V001",
                        "score": 87.5,
                    }
                ],
                "message": "Auto-picked 1 candidate(s).",
            }
            page._autopick_request_id = 2
            page._on_autopick_finished(2, payload)
            self.assertEqual(page.compare_slots_table.item(0, 2).text(), "87.50")

    def test_compare_tab_contains_slots_table_and_saved_selector(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2c_compare_layout_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            slots_table = page.findChild(QTableWidget, "AnalyzerCompareSlotsTable")
            saved_selector = page.findChild(QComboBox, "AnalyzerAnalysisSelector")
            self.assertIsNotNone(slots_table)
            self.assertIsNotNone(saved_selector)
            self.assertTrue(hasattr(page, "compare_kpi_panel"))
            self.assertFalse(page.compare_table.isVisible())
            self.assertIn("heatmap", page.compare_heatmap_selector.toolTip().lower())

    def test_compare_add_and_remove_candidate_updates_shortlist(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_ui2c_compare_slots_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            payload = self._sample_runs_payload("P001")
            page._apply_runs_payload(payload)
            page._set_compare_candidates([payload["runs"][0]])
            self.assertEqual(page.compare_slots_table.item(0, 1).text(), "B001/V001")
            page._remove_compare_candidate(0)
            self.assertEqual(page.compare_slots_table.item(0, 1).text(), "--")

    def test_compare_heatmap_selector_updates_canvas(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_stage_compare_heatmap_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            candidates = [
                {
                    "project_id": "P001",
                    "batch_id": "B001",
                    "run_id": "R001",
                    "version_id": "V001",
                    "planes": ["H", "V"],
                    "kpi_score": 88.0,
                },
                {
                    "project_id": "P001",
                    "batch_id": "B002",
                    "run_id": "R002",
                    "version_id": "V002",
                    "planes": ["H", "V"],
                    "kpi_score": 81.0,
                },
            ]
            page._set_compare_candidates(candidates)
            page._compare_plot_items = [
                {
                    "candidate": dict(candidates[0]),
                    "plot": {
                        "display_freqs_hz": [200.0, 500.0, 1000.0],
                        "display_matrix_db": [[0.0, -2.0, -4.0], [-1.0, -3.0, -5.0]],
                        "angles_deg": [-10.0, 10.0],
                        "ref_angle_deg": 0.0,
                        "stage_plot": {
                            "heatmap_overlays": {
                                "minus6_contour": [
                                    {"freq_hz": 200.0, "left_angle_deg": -30.0, "right_angle_deg": 30.0}
                                ],
                                "target_half_window_deg": 30.0,
                            }
                        },
                    },
                },
                {
                    "candidate": dict(candidates[1]),
                    "plot": {
                        "display_freqs_hz": [200.0, 500.0, 1000.0],
                        "display_matrix_db": [[-2.0, -3.0, -6.0], [-1.0, -2.0, -4.0]],
                        "angles_deg": [-10.0, 10.0],
                        "ref_angle_deg": 0.0,
                        "stage_plot": {
                            "heatmap_overlays": {
                                "minus6_contour": [
                                    {"freq_hz": 200.0, "left_angle_deg": -24.0, "right_angle_deg": 24.0}
                                ],
                                "target_half_window_deg": 20.0,
                            }
                        },
                    },
                },
            ]
            page.compare_heatmap_selector.setCurrentIndex(1)
            page._render_compare_heatmap_selection()
            pixmap = page.compare_heatmap_canvas.pixmap()
            self.assertIsNotNone(pixmap)
            assert pixmap is not None
            self.assertFalse(pixmap.isNull())

    def test_plane_controls_keep_h_visible_with_missing_plane_reason(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_stage_plane_missing_h_") as tmp:
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
                        "planes": ["V", "D"],
                        "kpi_reason_codes": ["MISSING_PLANE"],
                    }
                ],
            }
            page._apply_runs_payload(payload)
            h_button = page._plane_buttons["H"]
            self.assertFalse(h_button.isHidden())
            self.assertFalse(h_button.isEnabled())
            self.assertIn("MISSING_PLANE", h_button.toolTip())
            self.assertIn("includes H/V/D", h_button.toolTip())

    def test_reason_severity_summary_is_shown_in_details_and_enables_help(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_stage_reason_help_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            row = {
                "project_id": "P001",
                "batch_id": "B001",
                "run_id": "R001",
                "version_id": "V001",
                "planes": ["V", "D"],
                "kpi_score": 80.0,
                "kpi_flags_count": 0,
                "kpi_reason_items": [
                    {
                        "code": "MISSING_PLANE",
                        "severity": "warn",
                        "summary": "Missing H plane.",
                        "action": "Re-export H plane.",
                    }
                ],
            }
            page._set_details(row)
            self.assertTrue(page.flags_help_btn.isEnabled())
            reason_text = page._detail_labels["kpi_reason_codes"].text()
            self.assertIn("[WARN] MISSING_PLANE", reason_text)

    def test_compare_candidate_identity_includes_project_scope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_stage_compare_project_scope_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            candidates = [
                {"project_id": "P001", "batch_id": "B001", "run_id": "R001", "version_id": "V001", "kpi_score": 88.0},
                {"project_id": "P002", "batch_id": "B001", "run_id": "R001", "version_id": "V001", "kpi_score": 77.0},
            ]
            page._set_compare_candidates(candidates)
            self.assertEqual(len(page._compare_candidates), 2)

    def test_compare_shortlist_score_survives_runs_refresh_merge(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_stage_compare_score_merge_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            payload = self._sample_runs_payload("P001")
            page._apply_runs_payload(payload)
            page._set_compare_candidates(payload["runs"])
            self.assertEqual(page.compare_slots_table.item(0, 2).text(), "88.00")
            page._apply_runs_payload(payload)
            self.assertEqual(page.compare_slots_table.item(0, 2).text(), "88.00")

    def test_compare_kpi_matrix_renders_c1_to_c5_values(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_stage_compare_kpi_matrix_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            candidates = []
            for idx in range(5):
                candidates.append(
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": f"R{idx+1:03d}",
                        "version_id": f"V{idx+1:03d}",
                        "score": 90.0 - idx,
                        "kpi_b_pc_oct": 2.0 + idx * 0.1,
                        "kpi_e_bw": 1.0 + idx,
                        "kpi_e_cov": 0.5 + idx * 0.05,
                        "kpi_r_spill": 0.1 + idx * 0.01,
                        "kpi_flags_count": idx,
                    }
                )
            page._set_compare_candidates(candidates)
            self.assertEqual(page.compare_kpi_matrix.rowCount(), 6)
            self.assertEqual(page.compare_kpi_matrix.columnCount(), 6)
            self.assertEqual(page.compare_kpi_matrix.item(0, 1).text(), "90.00")
            self.assertEqual(page.compare_kpi_matrix.item(5, 5).text(), "4")

    def test_beamwidth_overlay_includes_target_series_and_saturation_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_stage_compare_bw_sat_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._compare_overlay_curve_key = "beamwidth"
            page._compare_plot_items = [
                {
                    "candidate": {"batch_id": "B001", "version_id": "V001"},
                    "plot": {
                        "stage_plot": {
                            "curves": {
                                "beamwidth": [
                                    {"freq_hz": 1000.0, "beamwidth_deg": 180.0, "saturated": True},
                                    {"freq_hz": 2000.0, "beamwidth_deg": 170.0, "saturated": True},
                                ]
                            }
                        }
                    },
                }
            ]
            page._render_compare_overlay()
            status = str(getattr(page.compare_overlay_canvas, "_status", ""))
            self.assertIn("Saturated bins", status)
            series = list(getattr(page.compare_overlay_canvas, "_series", []) or [])
            self.assertTrue(any("Target" in str(item.get("label") or "") for item in series))

    def test_compare_overlay_labels_include_pin_marker_for_pinned_candidates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_stage_compare_pin_overlay_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._compare_plot_items = [
                {
                    "candidate": {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R001",
                        "version_id": "V001",
                        "version_pinned": True,
                    },
                    "plot": {
                        "stage_plot": {
                            "curves": {
                                "beamwidth": [
                                    {"freq_hz": 1000.0, "beamwidth_deg": 60.0},
                                    {"freq_hz": 2000.0, "beamwidth_deg": 50.0},
                                ]
                            }
                        }
                    },
                }
            ]
            page._render_compare_overlay()
            labels = [str(series.get("label") or "") for series in list(page.compare_overlay_canvas._series)]
            self.assertTrue(any("[PIN]" in label for label in labels))

    def test_pareto_scatter_does_not_fill_plot_area_with_last_candidate_color(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_stage_pareto_fill_guard_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._selected_compare_slot_index = 2
            points = []
            for idx in range(5):
                points.append(
                    {
                        "label": f"C{idx+1}",
                        "x_value": 24.0 + idx,
                        "y_value": 0.12 - (idx * 0.001),
                        "color": (192, 132, 252) if idx == 4 else (93, 168, 255),
                        "selected": idx == 2,
                    }
                )
            page.compare_pareto_canvas.resize(640, 320)
            page.compare_pareto_canvas.set_points(points=points, x_label="Beamwidth Error", y_label="Spill")
            pixmap = page.compare_pareto_canvas.pixmap()
            self.assertIsNotNone(pixmap)
            assert pixmap is not None
            image = pixmap.toImage()
            center = image.pixelColor(image.width() // 2, image.height() // 2)
            # Regression guard: rectangle fill bug painted the full plot with last-candidate color.
            self.assertNotEqual((center.red(), center.green(), center.blue()), (192, 132, 252))
            stored_points = list(getattr(page.compare_pareto_canvas, "_points", []) or [])
            self.assertTrue(any(bool(item.get("selected")) for item in stored_points))


if __name__ == "__main__":
    unittest.main()
