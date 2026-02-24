from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import AnalysePage, MetricCurveCanvas, _traffic_status_color, apply_plot_theme, compute_plot_layout_geometry
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QBuffer = None  # type: ignore[assignment]
    QIODevice = None  # type: ignore[assignment]
    Qt = None  # type: ignore[assignment]
    QIcon = None  # type: ignore[assignment]
    QTest = None  # type: ignore[assignment]
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


def _icon_png_bytes(icon: QIcon, size: int = 14) -> bytes:
    if QBuffer is None or QIODevice is None:
        return b""
    pixmap = icon.pixmap(size, size)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def _pixmap_png_bytes(canvas, size: int = 16) -> bytes:
    if QBuffer is None or QIODevice is None:
        return b""
    pixmap = canvas.pixmap()
    if pixmap is None:
        return b""
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


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

    def test_layout_geometry_keeps_x_axis_title_below_tick_labels(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_layout_geom_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            canvases = [
                page._explorer_stage_panels["A"]["heatmap_canvas"],
                page._explorer_stage_panels["B"]["curve_canvas"],
                page._compare_stage_panels["C"]["pareto_canvas"],
            ]
            for width, height in ((960, 480), (680, 360), (520, 280)):
                for canvas in canvases:
                    canvas.resize(width, height)
                    self.app.processEvents()
                    theme = apply_plot_theme(canvas, has_legend=False, context="test")
                    layout = compute_plot_layout_geometry(width=canvas.width(), height=canvas.height(), theme=theme)
                    gap = int(theme.get("x_axis_label_gap_px", 0))
                    self.assertGreaterEqual(int(layout["x_axis_label_top"]), int(layout["x_tick_label_bottom"]) + gap)
                    self.assertLessEqual(
                        int(layout["x_axis_label_top"]) + int(layout["x_axis_label_height"]),
                        int(canvas.height()),
                    )

    def test_canvas_outer_background_is_transparent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_transparent_bg_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            heatmap = page._explorer_stage_panels["A"]["heatmap_canvas"]
            curve = page._explorer_stage_panels["B"]["curve_canvas"]
            pareto = page._compare_stage_panels["C"]["pareto_canvas"]
            for canvas in (heatmap, curve, pareto):
                canvas.resize(520, 300)
            heatmap.clear_heatmap("No heatmap data.")
            curve.clear_series("Curve not available.")
            pareto.clear_points("Pareto unavailable.")
            self.app.processEvents()
            for canvas in (heatmap, curve, pareto):
                pixmap = canvas.pixmap()
                self.assertIsNotNone(pixmap)
                image = pixmap.toImage()
                # Corners must stay transparent: no opaque full-canvas black slab.
                self.assertLessEqual(int(image.pixelColor(1, 1).alpha()), 10)
                self.assertLessEqual(int(image.pixelColor(max(image.width() - 2, 1), 1).alpha()), 10)

    def test_target_overlay_visibility_floor_is_stage_invariant(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_target_visibility_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._set_compare_candidates(
                [
                    {
                        "project_id": "P001",
                        "batch_id": "B001",
                        "run_id": "R001",
                        "version_id": "V001",
                        "planes": ["H", "V"],
                        "kpi_score": 88.0,
                    }
                ]
            )
            page._compare_plot_items = [_sample_compare_plot_items()[0]]
            for stage_id in ("concept", "stabilization", "final"):
                _set_stage(page, stage_id)
                self.app.processEvents()
                page._render_compare_visuals()
                self.app.processEvents()
                heatmap = page._compare_stage_panels["A"]["heatmap_canvas"]
                self.assertGreaterEqual(int(getattr(heatmap, "_target_shade_alpha", 0)), 44)
                self.assertGreaterEqual(int(getattr(heatmap, "_target_boundary_alpha", 0)), 180)

    def test_analyzer_help_buttons_use_info_icon(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_info_icon_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            expected_info = QIcon(":/icons/info.svg")
            expected_settings = QIcon(":/icons/settings.svg")
            info_bytes = _icon_png_bytes(expected_info)
            settings_bytes = _icon_png_bytes(expected_settings)
            self.assertTrue(info_bytes)
            self.assertNotEqual(info_bytes, settings_bytes)
            self.assertEqual(_icon_png_bytes(page.flags_help_btn.icon()), info_bytes)
            for panel in list(page._explorer_stage_panels.values()) + list(page._compare_stage_panels.values()):
                help_btn = panel.get("help_btn")
                self.assertEqual(_icon_png_bytes(help_btn.icon()), info_bytes)

    def test_metric_band_toggle_state_flows_into_curve_style_profile(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_metric_band_toggle_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            self.assertTrue(bool(page._show_metric_bands))
            self.assertTrue(bool(page._metric_band_smooth))
            stabilization_profile = page._curve_style_profile(
                stage_id="stabilization",
                metric_key="di_proxy",
                context="explorer",
            )
            self.assertIn("show_band", stabilization_profile)
            self.assertTrue(bool(stabilization_profile.get("show_band")))
            self.assertTrue(bool(stabilization_profile.get("band_smooth")))
            page._apply_analysis_config({"show_metric_bands": False})
            self.assertFalse(bool(page._show_metric_bands))
            stabilization_profile_disabled = page._curve_style_profile(
                stage_id="stabilization",
                metric_key="di_proxy",
                context="explorer",
            )
            self.assertFalse(bool(stabilization_profile_disabled.get("show_band")))
            page._apply_analysis_config({"show_metric_bands": True, "metric_band_smooth": False})
            stabilization_profile_blocks = page._curve_style_profile(
                stage_id="stabilization",
                metric_key="di_proxy",
                context="explorer",
            )
            self.assertTrue(bool(stabilization_profile_blocks.get("show_band")))
            self.assertFalse(bool(stabilization_profile_blocks.get("band_smooth")))

    def test_auto_scale_button_exists_and_changes_scaling_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_auto_scale_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            self.assertIsNotNone(page.auto_scale_btn)
            self.assertFalse(bool(page._auto_scale_enabled))
            stable_range = page._resolve_axis_range(axis_key="test:axis", values=[0.0, 1.0, 2.0])
            self.assertIsNotNone(stable_range)
            page.auto_scale_btn.setChecked(True)
            self.app.processEvents()
            self.assertTrue(bool(page._auto_scale_enabled))
            auto_range = page._resolve_axis_range(axis_key="test:axis", values=[10.0, 12.0])
            self.assertIsNotNone(auto_range)
            assert stable_range is not None
            assert auto_range is not None
            self.assertGreater(float(auto_range[0]), float(stable_range[0]))

    def test_stage_switch_applies_full_angle_smoothness_defaults(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_stage_full_angles_defaults_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            _set_stage(page, "concept")
            self.app.processEvents()
            self.assertFalse(bool(page._use_full_angles_for_smoothness))
            _set_stage(page, "stabilization")
            self.app.processEvents()
            self.assertTrue(bool(page._use_full_angles_for_smoothness))
            _set_stage(page, "final")
            self.app.processEvents()
            self.assertTrue(bool(page._use_full_angles_for_smoothness))

    def test_explorer_concept_uses_target_deviation_summary_not_pareto(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_explorer_concept_summary_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            _set_stage(page, "concept")
            self.app.processEvents()
            panel_d = page._explorer_stage_panels["D"]
            self.assertEqual(str(panel_d.get("metric_key") or ""), "target_deviation_summary")
            self.assertEqual(str(panel_d.get("kind") or ""), "summary")
            self.assertIn("Target Deviation Summary", str(panel_d.get("title_label").text()))
            help_tip = str(panel_d.get("help_btn").toolTip() or "")
            self.assertIn("Pattern Ctrl", help_tip)
            self.assertIn("Overall Score", help_tip)

    def test_target_axis_color_setting_propagates_to_relevant_canvases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_target_axis_color_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._apply_analysis_config({"target_axis_color": "#FF7A4D"})
            cfg = page._current_analysis_config()
            self.assertEqual(str(cfg.get("target_axis_color") or ""), "#FF7A4D")
            plot_payload = dict(_sample_compare_plot_items()[0]["plot"])
            page._render_plot_payload(plot_payload)
            self.app.processEvents()
            explorer_heatmap = page._explorer_stage_panels["A"]["heatmap_canvas"]
            explorer_curve = page._explorer_stage_panels["B"]["curve_canvas"]
            explorer_summary = page._explorer_stage_panels["D"]["summary_canvas"]
            self.assertEqual(str(explorer_heatmap._target_axis_color.name()).upper(), "#FF7A4D")
            self.assertEqual(str(explorer_curve._target_axis_color.name()).upper(), "#FF7A4D")
            self.assertEqual(str(explorer_summary._target_axis_color.name()).upper(), "#FF7A4D")

    @unittest.skipIf(QTest is None or Qt is None, "Qt test utilities are required")
    def test_plot_tile_double_click_toggles_maximize_restore(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_double_click_maximize_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page.resize(1200, 780)
            page.show()
            self.app.processEvents()
            tile_canvas = page._explorer_stage_panels["A"]["heatmap_canvas"]
            QTest.mouseDClick(tile_canvas, Qt.LeftButton)
            self.app.processEvents()
            self.assertEqual(str(page._maximized_plot_slots.get("explorer") or ""), "A")
            self.assertTrue(bool(page._explorer_stage_panels["A"]["frame"].isVisible()))
            self.assertFalse(bool(page._explorer_stage_panels["B"]["frame"].isVisible()))
            QTest.mouseDClick(tile_canvas, Qt.LeftButton)
            self.app.processEvents()
            self.assertIsNone(page._maximized_plot_slots.get("explorer"))
            self.assertTrue(all(bool(panel["frame"].isVisible()) for panel in page._explorer_stage_panels.values()))
            page.hide()

    def test_compare_pareto_excludes_non_finite_values_without_crash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_plot_ux_pareto_non_finite_") as tmp:
            service = _build_service(Path(tmp))
            page = AnalysePage(service=service)
            page._compare_candidates = [
                {"batch_id": "B001", "version_id": "V001"},
                {"batch_id": "B002", "version_id": "V002"},
            ]
            page._compare_plot_items = [
                {
                    "candidate": {"batch_id": "B001", "version_id": "V001", "kpi_e_bw": float("nan"), "kpi_r_spill": 0.2},
                    "plot": {"stage_plot": {"summary": {"e_bw_mean": float("nan"), "r_spill_mean": 0.2}}},
                },
                {
                    "candidate": {"batch_id": "B002", "version_id": "V002", "kpi_e_bw": 1.1, "kpi_r_spill": float("inf")},
                    "plot": {"stage_plot": {"summary": {"e_bw_mean": 1.1, "r_spill_mean": float("inf")}}},
                },
            ]
            _set_stage(page, "concept")
            self.app.processEvents()
            page._render_compare_pareto()
            pareto_panel = next(
                (
                    panel
                    for panel in page._compare_stage_panels.values()
                    if str(panel.get("kind") or "").strip().lower() == "pareto"
                ),
                None,
            )
            assert pareto_panel is not None
            status = str(pareto_panel["pareto_canvas"]._status or "")
            self.assertIn("Compute KPIs", status)

    def test_metric_curve_marker_rendering_is_deterministic(self) -> None:
        canvas = MetricCurveCanvas()
        canvas.resize(540, 320)
        series = [
            {
                "label": "V001",
                "show_legend": True,
                "style": "trend_band",
                "show_band": True,
                "regime_markers": True,
                "thresholds": [2.0, 4.0],
                "points": [
                    {"freq_hz": 200.0, "value": 2.2},
                    {"freq_hz": 500.0, "value": 3.6},
                    {"freq_hz": 1000.0, "value": 2.9},
                    {"freq_hz": 2000.0, "value": 4.1},
                ],
                "color": (154, 172, 197),
            }
        ]
        canvas.set_series(series=series, x_scale_mode="log", x_label="Frequency (Hz, log)", y_label="DI Proxy (dB)")
        self.app.processEvents()
        first = _pixmap_png_bytes(canvas)
        canvas.set_series(series=series, x_scale_mode="log", x_label="Frequency (Hz, log)", y_label="DI Proxy (dB)")
        self.app.processEvents()
        second = _pixmap_png_bytes(canvas)
        self.assertTrue(first)
        self.assertEqual(first, second)

    def test_target_deviation_traffic_color_mapping_uses_three_buckets(self) -> None:
        good = _traffic_status_color(0.12)
        mid = _traffic_status_color(0.52)
        bad = _traffic_status_color(0.88)
        self.assertGreater(good.green(), good.red())
        self.assertGreater(mid.red(), good.red())
        self.assertGreater(bad.red(), bad.green())

    def test_metric_curve_draw_content_stays_within_plot_rect_clip(self) -> None:
        canvas = MetricCurveCanvas()
        canvas.resize(560, 320)
        styles = ("consistency_strip", "trend_band", "defect_band")
        for style in styles:
            series = [
                {
                    "label": "",
                    "show_legend": False,
                    "style": style,
                    "show_band": True,
                    "band_smooth": True,
                    "thresholds": [0.2, 0.5, 0.8],
                    "points": [
                        {"freq_hz": 200.0, "value": 0.30},
                        {"freq_hz": 500.0, "value": 0.55},
                        {"freq_hz": 1000.0, "value": 0.42},
                        {"freq_hz": 2000.0, "value": 0.66},
                    ],
                    "color": (154, 172, 197),
                }
            ]
            canvas.set_series(series=series, x_scale_mode="log", x_label="Frequency (Hz, log)", y_label="Metric")
            self.app.processEvents()
            pixmap = canvas.pixmap()
            self.assertIsNotNone(pixmap)
            assert pixmap is not None
            image = pixmap.toImage()
            margin_left, margin_right, margin_top, margin_bottom = tuple(canvas._applied_plot_margins)
            plot_w = max(image.width() - margin_left - margin_right, 1)
            plot_h = max(image.height() - margin_top - margin_bottom, 1)
            sample_x = min(image.width() - 2, margin_left + plot_w + 6)
            sample_y = min(image.height() - 2, margin_top + (plot_h // 2))
            outside_color = image.pixelColor(sample_x, sample_y)
            self.assertLessEqual(int(outside_color.alpha()), 26, msg=f"style={style} leaked outside plot rect")


if __name__ == "__main__":
    unittest.main()
