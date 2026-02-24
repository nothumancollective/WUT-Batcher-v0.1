from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import AnalysePage
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]


def _build_service(tmp_root: Path) -> OrchestratorService:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / "library"
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store)


def _set_stage(page: AnalysePage, stage_id: str) -> None:
    page._set_combo_current_by_data(page.stage_selector, stage_id)


def _sample_compare_plot_items() -> list[dict]:
    rows: list[dict] = []
    for idx in range(2):
        rows.append(
            {
                "candidate": {
                    "project_id": "P001",
                    "batch_id": f"B00{idx + 1}",
                    "run_id": f"R00{idx + 1}",
                    "version_id": f"V00{idx + 1}",
                    "planes": ["H", "V"],
                },
                "plot": {
                    "display_freqs_hz": [200.0, 500.0, 1000.0],
                    "display_matrix_db": [[0.0, -2.0, -4.0], [-1.0, -3.0, -5.0]],
                    "angles_deg": [-10.0, 10.0],
                    "ref_angle_deg": 0.0,
                    "stage_plot": {
                        "curves": {
                            "beamwidth": [
                                {"freq_hz": 200.0, "beamwidth_deg": 62.0},
                                {"freq_hz": 1000.0, "beamwidth_deg": 58.0},
                            ],
                            "e_cov": [
                                {"freq_hz": 200.0, "value": 0.42},
                                {"freq_hz": 1000.0, "value": 0.37},
                            ],
                            "di_proxy": [
                                {"freq_hz": 200.0, "value": 2.8},
                                {"freq_hz": 1000.0, "value": 3.2},
                            ],
                            "s_theta": [
                                {"freq_hz": 200.0, "value": 0.22},
                                {"freq_hz": 1000.0, "value": 0.28},
                            ],
                            "e_sym_shape": [
                                {"freq_hz": 200.0, "value": 0.18},
                                {"freq_hz": 1000.0, "value": 0.24},
                            ],
                            "r_off": [
                                {"freq_hz": 200.0, "value": 1.9},
                                {"freq_hz": 1000.0, "value": 4.4},
                            ],
                        },
                        "summary": {
                            "e_bw_mean": 1.2 + idx * 0.1,
                            "r_spill_mean": 0.12 + idx * 0.01,
                            "e_cov_mean": 0.4 + idx * 0.02,
                        },
                        "heatmap_overlays": {
                            "minus6_contour": [
                                {"freq_hz": 200.0, "left_angle_deg": -30.0, "right_angle_deg": 30.0}
                            ],
                            "target_half_window_deg": 30.0,
                        },
                    },
                },
            }
        )
    return rows


@unittest.skipIf(QApplication is None, "PySide6 is required")
class AnalyzerPlotUxRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_stage_tab_always_exposes_four_plot_tiles_in_explorer_and_compare(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_tiles_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            self.assertEqual(page.explorer_grid_layout.count(), 4)
            self.assertEqual(page.compare_grid_layout.count(), 4)
            for stage_id in ("concept", "stabilization", "final"):
                _set_stage(page, stage_id)
                self.app.processEvents()
                self.assertEqual(len(page._explorer_stage_panels), 4)
                self.assertEqual(len(page._compare_stage_panels), 4)
                self.assertFalse(
                    any(str(panel.get("kind") or "") == "placeholder" for panel in page._explorer_stage_panels.values())
                )
                self.assertFalse(
                    any(str(panel.get("kind") or "") == "placeholder" for panel in page._compare_stage_panels.values())
                )

    def test_compare_bottom_right_metric_is_stage_specific(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_bottom_right_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)

            _set_stage(page, "stabilization")
            self.app.processEvents()
            self.assertEqual(str(page._compare_stage_panels["D"].get("metric_key") or ""), "e_sym_shape")

            _set_stage(page, "final")
            self.app.processEvents()
            self.assertEqual(str(page._compare_stage_panels["D"].get("metric_key") or ""), "s_theta")

    def test_compare_overlay_legend_labels_are_only_v_numbers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_labels_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._compare_plot_items = _sample_compare_plot_items()
            page._selected_compare_slot_index = 0
            _set_stage(page, "concept")
            self.app.processEvents()
            page._render_compare_overlay()
            slot_b = page._compare_stage_panels["B"]
            labels = [str(row.get("label") or "") for row in list(slot_b["curve_canvas"]._series)]
            version_labels = [label for label in labels if label.strip()]
            self.assertTrue(version_labels)
            self.assertTrue(all(re.match(r"^V\d{3}$", label) for label in version_labels))

    def test_canvas_does_not_use_internal_duplicate_titles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_titles_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            for panel in list(page._explorer_stage_panels.values()) + list(page._compare_stage_panels.values()):
                for key in ("heatmap_canvas", "curve_canvas", "pareto_canvas"):
                    canvas = panel.get(key)
                    if canvas is None:
                        continue
                    self.assertEqual(str(canvas.text() or ""), "")

    def test_compare_renders_with_single_candidate_without_select_candidates_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_one_candidate_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            candidate = {
                "project_id": "P001",
                "batch_id": "B001",
                "run_id": "R001",
                "version_id": "V001",
                "planes": ["H", "V"],
                "kpi_score": 88.0,
            }
            page._set_compare_candidates([candidate])
            _set_stage(page, "stabilization")
            self.app.processEvents()
            page._compare_plot_items = [_sample_compare_plot_items()[0]]
            page._render_compare_visuals()
            status_b = str(page._compare_stage_panels["B"]["curve_canvas"]._status or "")
            status_d = str(page._compare_stage_panels["D"]["curve_canvas"]._status or "")
            self.assertNotIn("Select candidates", status_b)
            self.assertNotIn("Select candidates", status_d)

    def test_plane_selection_propagates_compare_redraw_calls(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_plane_redraw_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page.analysis_tabs.setCurrentWidget(page.compare_tab)
            page._set_compare_candidates(
                [
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
                        "kpi_score": 82.0,
                    },
                ]
            )
            page._compare_plot_items = _sample_compare_plot_items()
            _set_stage(page, "concept")
            self.app.processEvents()
            with (
                patch.object(page, "_render_compare_overlay", wraps=page._render_compare_overlay) as render_overlay,
                patch.object(page, "_render_compare_heatmap_selection", wraps=page._render_compare_heatmap_selection) as render_heatmap,
                patch.object(page, "_render_compare_focus_curve", wraps=page._render_compare_focus_curve) as render_focus,
                patch.object(page, "_render_compare_pareto", wraps=page._render_compare_pareto) as render_pareto,
            ):
                page._plane_buttons["V"].setChecked(True)
                self.app.processEvents()
                self.assertEqual(page._compare_plane(), "V")
                self.assertGreaterEqual(render_overlay.call_count, 1)
                self.assertGreaterEqual(render_heatmap.call_count, 1)
                self.assertGreaterEqual(render_focus.call_count, 1)
                self.assertGreaterEqual(render_pareto.call_count, 1)


if __name__ == "__main__":
    unittest.main()
