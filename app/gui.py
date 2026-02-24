"""PySide6 GUI orchestrator for WUT Batcher."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import html
import math
import json
import logging
import os
import re
from pathlib import Path
import subprocess
import sys
import threading
import traceback
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from app.analyzer.cache import AnalyzerPlotCache, resolve_cache_policy
from app.analyzer.heatmap_style import compare_overlay_color, get_vacs_like_lut
from app.analyzer.orientation import dedupe_orientations
from app.analyzer.presets import (
    ALGO_VERSION,
    COVERAGE_PRESETS,
    DEFAULT_BAND_PRESET_ID,
    DEFAULT_COVERAGE_PRESET_ID,
    DEFAULT_STAGE_ID,
    DEFAULT_TOL_DEG,
    STAGE_ORDER,
    STAGE_PRESETS,
    normalize_stage_id,
    resolve_band_limits,
)
from app.analyzer.reason_codes import reason_items_for_codes
from app.doctor_service import run_doctor_checks
from app.constants import DEFAULT_RUNNER_MODE
import app.resources_rc  # noqa: F401  # Registers Qt resource paths used by icons/QSS.
from app.models import AppConfig, Batch, Project, ProjectConstraints
from app.project_issue_model import UiProjectIssue, classify_ui_severity, issue_counts, normalize_project_issues
from app.services import OrchestratorService, PreviewGenerationCancelled
from app.settings_store import (
    SIMULATION_TIMEOUT_MINUTES_DEFAULT,
    SIMULATION_TIMEOUT_MINUTES_MAX,
    SIMULATION_TIMEOUT_MINUTES_MIN,
    UserSettings,
)
from app.ui_validation import UiValidationEngine
from app.widgets.command_header import CommandHeaderWidget
from ui.batch_export_panel import BatchExportPanel
from ui.batch_parameter_form import BatchParameterForm
from ui.batch_preview_placeholder import BatchPreviewPlaceholder
from ui.compat_ui_adapter import CompatUiAdapter
from ui.form_builder import ParameterForm
from ui.form_metrics import FORM_METRICS
from ui.form_schema import build_project_form_schema
from ui.styled_dialog import StyledDialogBase
from ui.theme import apply_theme, apply_windows_dark_titlebar, configure_windows_qt_darkmode_env

LOGGER = logging.getLogger(__name__)
_RUNTIME_LOG_LOCK = threading.Lock()
_RUNTIME_LOG_INSTALLED = False
_PREVIOUS_QT_MESSAGE_HANDLER = None
_RUNTIME_CONTEXT_PROVIDER: Callable[[], Dict[str, Any]] | None = None


def _runtime_log_path() -> Path:
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    base = Path(local_app_data) if local_app_data else (Path.home() / "AppData" / "Local")
    path = base / "WUTBatcher" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path / "ui_runtime_errors.log"


def _append_runtime_log(lines: List[str]) -> None:
    try:
        payload = "\n".join(lines).rstrip() + "\n\n"
        log_path = _runtime_log_path()
        with _RUNTIME_LOG_LOCK:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(payload)
    except Exception:
        # Logging should never crash the app flow.
        pass


def _install_runtime_exception_logging(*, context_provider: Callable[[], Dict[str, Any]] | None = None) -> None:
    global _RUNTIME_LOG_INSTALLED, _PREVIOUS_QT_MESSAGE_HANDLER, _RUNTIME_CONTEXT_PROVIDER
    if callable(context_provider):
        _RUNTIME_CONTEXT_PROVIDER = context_provider
    if _RUNTIME_LOG_INSTALLED:
        return
    _RUNTIME_LOG_INSTALLED = True

    previous_hook = sys.excepthook

    def _safe_context() -> Dict[str, Any]:
        provider = _RUNTIME_CONTEXT_PROVIDER
        if not callable(provider):
            return {}
        try:
            raw = provider() or {}
            if isinstance(raw, dict):
                return raw
            return {"context_provider_value": str(raw)}
        except Exception as exc:
            return {"context_provider_error": str(exc)}

    def _exception_hook(exc_type, exc_value, exc_tb) -> None:
        context = _safe_context()
        lines = [
            f"[{datetime.now(timezone.utc).isoformat()}] Unhandled Python exception",
            f"type: {getattr(exc_type, '__name__', str(exc_type))}",
            f"message: {exc_value}",
            f"context: {json.dumps(context, ensure_ascii=False)}",
            "traceback:",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).rstrip(),
        ]
        _append_runtime_log(lines)
        try:
            previous_hook(exc_type, exc_value, exc_tb)
        except Exception:
            pass

    sys.excepthook = _exception_hook

    try:
        qt_levels = {
            int(QtMsgType.QtDebugMsg): "DEBUG",
            int(QtMsgType.QtInfoMsg): "INFO",
            int(QtMsgType.QtWarningMsg): "WARNING",
            int(QtMsgType.QtCriticalMsg): "CRITICAL",
            int(QtMsgType.QtFatalMsg): "FATAL",
        }

        def _qt_message_handler(msg_type, context, message) -> None:
            level = qt_levels.get(int(msg_type), str(int(msg_type)))
            file_name = getattr(context, "file", "") or "<unknown>"
            line_no = int(getattr(context, "line", 0) or 0)
            function_name = getattr(context, "function", "") or "<unknown>"
            lines = [
                f"[{datetime.now(timezone.utc).isoformat()}] Qt message",
                f"level: {level}",
                f"location: {file_name}:{line_no} ({function_name})",
                f"message: {message}",
            ]
            _append_runtime_log(lines)
            if callable(_PREVIOUS_QT_MESSAGE_HANDLER):
                try:
                    _PREVIOUS_QT_MESSAGE_HANDLER(msg_type, context, message)
                except Exception:
                    pass

        _PREVIOUS_QT_MESSAGE_HANDLER = qInstallMessageHandler(_qt_message_handler)
    except Exception:
        _PREVIOUS_QT_MESSAGE_HANDLER = None

try:
    from PySide6.QtCore import (
        QEasingCurve,
        QPoint,
        QPropertyAnimation,
        QEvent,
        QObject,
        Qt,
        QtMsgType,
        QThread,
        QTimer,
        Signal,
        QSize,
        qInstallMessageHandler,
    )
    from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap, QIcon, QPalette, QImage, QPen
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QButtonGroup,
        QComboBox,
        QCheckBox,
        QDialog,
        QDoubleSpinBox,
        QFormLayout,
        QFrame,
        QGraphicsOpacityEffect,
        QGridLayout,
        QGroupBox,
        QHeaderView,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QListView,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QScrollArea,
        QSizePolicy,
        QSplitter,
        QSplashScreen,
        QSpinBox,
        QStackedWidget,
        QStatusBar,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for GUI mode. Install it with 'pip install PySide6'.") from exc


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class ElidedTitleLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._apply_elide()

    def _apply_elide(self) -> None:
        available = max(self.contentsRect().width(), 40)
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, available))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_elide()


class ElidedToolButton(QToolButton):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._apply_elide()

    def _apply_elide(self) -> None:
        available = max(int(self.contentsRect().width()) - 10, 20)
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, available))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_elide()


class IssueRowButton(QPushButton):
    def __init__(self, full_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = str(full_text or "")
        self.setText(self._full_text)
        self.setToolTip(self._full_text)

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._apply_elide()

    def _apply_elide(self) -> None:
        available = max(int(self.width()) - 14, 24)
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, available)
        self.setText(elided)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_elide()


def _format_freq_label(freq_hz: float) -> str:
    value = float(freq_hz)
    if value >= 1000.0:
        if abs(value % 1000.0) <= 1.0e-6:
            return f"{int(round(value / 1000.0))}k"
        return f"{value / 1000.0:.1f}k"
    return str(int(round(value)))


_ANALYZER_LOG_MAJOR_TICKS: Tuple[float, ...] = (200.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0, 16000.0)
_ANALYZER_LOG_MAJOR_TICKS_SMALL: Tuple[float, ...] = (500.0, 1000.0, 2000.0, 5000.0, 10000.0)


@dataclass(frozen=True)
class AnalyzerPlotStyle:
    left_margin_px: int = 90
    right_margin_no_legend_px: int = 24
    right_margin_with_legend_px: int = 136
    top_margin_px: int = 18
    bottom_margin_px: int = 64
    x_tick_label_y_offset_px: int = 20
    x_tick_label_height_px: int = 16
    x_axis_label_height_px: int = 18
    x_axis_label_bottom_pad_px: int = 6
    y_tick_label_height_px: int = 16
    y_tick_label_right_pad_px: int = 12
    y_axis_label_band_left_px: int = 6
    y_axis_label_band_width_px: int = 20
    grid_major_color: str = "#2F3A4D"
    grid_minor_color: str = "#232A35"
    grid_y_color: str = "#2A3344"
    tile_gap_px: int = 4
    tile_inner_padding_px: int = 4
    tile_header_spacing_px: int = 2
    y_tick_label_min_gap_px: int = 14


ANALYZER_PLOT_STYLE = AnalyzerPlotStyle()


def apply_analyzer_plot_margins(*, has_legend: bool = False) -> Tuple[int, int, int, int]:
    style = ANALYZER_PLOT_STYLE
    return (
        int(style.left_margin_px),
        int(style.right_margin_with_legend_px if has_legend else style.right_margin_no_legend_px),
        int(style.top_margin_px),
        int(style.bottom_margin_px),
    )


def apply_plot_theme(
    widget: QWidget,
    *,
    has_legend: bool = False,
    context: str = "plot",
) -> Dict[str, Any]:
    width = max(int(widget.width()), 1)
    height = max(int(widget.height()), 1)
    metrics = widget.fontMetrics()
    base_px = max(float(metrics.height()) * 0.78, 11.0)
    title_font_px = max(int(round(base_px * 1.05)), 9)
    axis_font_px = max(int(round(base_px * 0.75)), 8)
    tick_font_px = max(int(round(base_px * 0.65)), 7)
    legend_font_px = max(int(round(base_px * 0.70)), 7)
    em = max(float(tick_font_px), 7.0)
    if width < 520 or height < 280:
        size_class = "small"
    elif width < 860 or height < 420:
        size_class = "medium"
    else:
        size_class = "large"
    margins = {
        "left": max(40, int(round(6.0 * em))),
        "top": max(12, int(round(2.0 * em))),
        "right": max(18, int(round((12.0 if has_legend else 2.0) * em))),
        "bottom": max(28, int(round(5.0 * em))),
    }
    return {
        "context": str(context or "plot"),
        "size_class": size_class,
        "margins": margins,
        "title_font_px": title_font_px,
        "axis_font_px": axis_font_px,
        "tick_font_px": tick_font_px,
        "legend_font_px": legend_font_px,
        "x_tick_label_height_px": max(14, int(round(2.0 * em))),
        "x_tick_label_y_offset_px": max(16, int(round(2.3 * em))),
        "y_tick_label_height_px": max(14, int(round(2.0 * em))),
        "y_tick_label_right_pad_px": max(8, int(round(1.6 * em))),
        "y_tick_label_min_gap_px": max(12, int(round(1.8 * em))),
    }


def _font_with_pixel_size(base_font: QFont, pixel_size: int) -> QFont:
    font = QFont(base_font)
    font.setPixelSize(max(int(pixel_size), 7))
    return font


def format_series_label(version_id: Any) -> str:
    token = str(version_id or "").strip()
    match = re.search(r"(\d+)", token)
    if match:
        return f"V{int(match.group(1)):03d}"
    if token:
        return f"V{token}"
    return "V---"


def _plot_margins(*, has_legend: bool = False) -> Tuple[int, int, int, int]:
    return apply_analyzer_plot_margins(has_legend=has_legend)


def _log_tick_sets(freq_min: float, freq_max: float, *, size_class: str = "large") -> Tuple[List[float], List[float]]:
    lo = max(float(freq_min), 1.0)
    hi = max(float(freq_max), lo + 1.0e-6)
    source_ticks = _ANALYZER_LOG_MAJOR_TICKS_SMALL if str(size_class or "").strip().lower() == "small" else _ANALYZER_LOG_MAJOR_TICKS
    major: List[float] = [tick for tick in source_ticks if lo <= float(tick) <= hi]
    if not major:
        decade_min = int(math.floor(math.log10(lo)))
        decade_max = int(math.ceil(math.log10(hi)))
        for decade in range(decade_min, decade_max + 1):
            base = 10.0 ** decade
            for multiplier in (1.0, 2.0, 5.0):
                tick = base * multiplier
                if lo <= tick <= hi:
                    major.append(float(tick))
    major = sorted(set(round(float(item), 6) for item in major))

    decade_min = int(math.floor(math.log10(lo)))
    decade_max = int(math.ceil(math.log10(hi)))
    minor: List[float] = []
    for decade in range(decade_min, decade_max + 1):
        base = 10.0 ** decade
        for multiplier in (3.0, 4.0, 6.0, 7.0, 8.0, 9.0):
            tick = base * multiplier
            if lo <= tick <= hi:
                minor.append(float(tick))
    minor = sorted(set(round(value, 6) for value in minor if round(value, 6) not in set(major)))
    return major, minor


def _draw_analyzer_x_axis_label(
    painter: QPainter,
    *,
    text: str,
    margin_left: int,
    plot_w: int,
    canvas_height: int,
) -> None:
    style = ANALYZER_PLOT_STYLE
    label_h = int(style.x_axis_label_height_px)
    label_y = max(
        0,
        int(canvas_height - style.x_axis_label_bottom_pad_px - label_h),
    )
    painter.drawText(margin_left, label_y, plot_w, label_h, Qt.AlignHCenter | Qt.AlignVCenter, str(text or ""))


def _draw_analyzer_y_axis_label(
    painter: QPainter,
    *,
    text: str,
    margin_top: int,
    plot_h: int,
) -> None:
    style = ANALYZER_PLOT_STYLE
    if plot_h <= 0:
        return
    band_left = int(style.y_axis_label_band_left_px)
    band_width = int(max(style.y_axis_label_band_width_px, 12))
    center_x = float(band_left + (band_width / 2.0))
    center_y = float(margin_top + (plot_h / 2.0))
    painter.save()
    painter.translate(center_x, center_y)
    painter.rotate(-90.0)
    painter.drawText(int(-(plot_h / 2.0)), int(-(band_width / 2.0)), int(plot_h), int(band_width), Qt.AlignCenter, str(text or ""))
    painter.restore()


def _linear_ticks(minimum: float, maximum: float, *, max_count: int = 6) -> List[float]:
    lo = float(minimum)
    hi = float(maximum)
    if hi <= lo:
        hi = lo + 1.0
    span = hi - lo
    rough_step = span / max(float(max_count - 1), 1.0)
    if rough_step <= 0.0:
        rough_step = 1.0
    magnitude = 10.0 ** math.floor(math.log10(rough_step))
    normalized = rough_step / magnitude
    if normalized <= 1.0:
        step = 1.0 * magnitude
    elif normalized <= 2.0:
        step = 2.0 * magnitude
    elif normalized <= 5.0:
        step = 5.0 * magnitude
    else:
        step = 10.0 * magnitude
    tick_start = math.ceil(lo / step) * step
    ticks: List[float] = []
    value = tick_start
    while value <= hi + (0.5 * step):
        ticks.append(float(value))
        value += step
    if not ticks:
        ticks = [lo, hi]
    if abs(ticks[0] - lo) > 1.0e-6:
        ticks.insert(0, lo)
    if abs(ticks[-1] - hi) > 1.0e-6:
        ticks.append(hi)
    return sorted(set(round(item, 6) for item in ticks))


def _angle_ticks(min_angle: float, max_angle: float, *, size_class: str = "large") -> List[float]:
    lo = float(min_angle)
    hi = float(max_angle)
    if hi <= lo:
        return [lo]
    step = 30.0 if str(size_class or "").strip().lower() == "small" else 15.0
    ticks: List[float] = []
    if lo < 0.0 < hi:
        max_abs = max(abs(lo), abs(hi))
        bound = int(math.ceil(max_abs / step) * step)
        value = -bound
        while value <= bound + 1.0e-6:
            if lo - 1.0e-6 <= float(value) <= hi + 1.0e-6:
                ticks.append(float(value))
            value += step
    else:
        start = math.ceil(lo / step) * step
        value = start
        while value <= hi + 1.0e-6:
            ticks.append(float(value))
            value += step
    if not ticks:
        ticks = [lo, hi]
    return sorted(set(round(item, 6) for item in ticks))


def _visible_target_angle_window(
    *,
    angle_min: float,
    angle_max: float,
    half_window_deg: float,
) -> Tuple[Optional[Tuple[float, float]], List[float]]:
    lo = float(angle_min)
    hi = float(angle_max)
    half = max(float(half_window_deg), 0.5)
    if hi <= lo:
        return None, []
    if lo >= 0.0:
        window = (max(lo, 0.0), min(hi, half))
        boundaries = [0.0, half]
    elif hi <= 0.0:
        window = (max(lo, -half), min(hi, 0.0))
        boundaries = [-half, 0.0]
    else:
        window = (max(lo, -half), min(hi, half))
        boundaries = [-half, half]
    if window[1] <= window[0]:
        region: Optional[Tuple[float, float]] = None
    else:
        region = window
    lines = [float(boundary) for boundary in boundaries if lo - 1.0e-6 <= float(boundary) <= hi + 1.0e-6]
    return region, lines


def _should_render_minus6_angle(
    angle_value: float,
    *,
    angle_min: float,
    angle_max: float,
    show_mirrored: bool,
) -> bool:
    angle = float(angle_value)
    lo = float(angle_min)
    hi = float(angle_max)
    if bool(show_mirrored):
        return True
    if angle < (lo - 1.0e-6) or angle > (hi + 1.0e-6):
        return False
    if lo >= 0.0:
        return angle >= -1.0e-6
    if hi <= 0.0:
        return angle <= 1.0e-6
    return True


STAGE_EXPLORER_LAYOUTS: Dict[str, List[Dict[str, str]]] = {
    "concept": [
        {"slot": "A", "key": "heatmap", "title": "Polar Map", "help": "Heatmap with -6 dB contour and target window."},
        {"slot": "B", "key": "e_cov", "title": "Coverage Uniformity vs f", "help": "RMS variation inside the target coverage window."},
        {"slot": "C", "key": "r_spill", "title": "Spill Index vs f", "help": "Relative outside-vs-inside target energy ratio."},
        {
            "slot": "D",
            "key": "pareto_decision",
            "title": "Decision Trade-off (E_BW vs Spill)",
            "help": "Single-candidate Pareto snapshot for beamwidth error vs spill ratio.",
        },
    ],
    "stabilization": [
        {"slot": "A", "key": "heatmap", "title": "Polar Map", "help": "Heatmap with -6 dB contour and target window."},
        {"slot": "B", "key": "di_proxy", "title": "DI Trend Band vs f", "help": "Trend-focused DI proxy view with regime guides."},
        {"slot": "C", "key": "s_theta", "title": "Smoothness Stability Strip", "help": "Compact smoothness trend strip over frequency."},
        {"slot": "D", "key": "e_sym_shape", "title": "Plane Consistency Strip", "help": "Compact inter-plane consistency trend strip."},
    ],
    "final": [
        {"slot": "A", "key": "heatmap", "title": "Polar Map", "help": "Heatmap with -6 dB contour and target window."},
        {"slot": "B", "key": "r_off", "title": "Off-axis Ripple Defect View", "help": "Defect-focused ripple risk view with hotspot markers."},
        {"slot": "C", "key": "s_theta", "title": "Smoothness Stability Strip", "help": "Compact smoothness trend strip over frequency."},
        {"slot": "D", "key": "e_sym_shape", "title": "Plane Consistency Strip", "help": "Compact inter-plane consistency trend strip."},
    ],
}

STAGE_COMPARE_OVERLAY_KEY: Dict[str, str] = {
    "concept": "beamwidth",
    "stabilization": "di_proxy",
    "final": "r_off",
}

STAGE_COMPARE_LAYOUTS: Dict[str, List[Dict[str, str]]] = {
    "concept": [
        {"slot": "A", "kind": "heatmap", "key": "heatmap", "title": "Polar Heatmap", "help": "Single-candidate heatmap view (select C1..C5 above)."},
        {"slot": "B", "kind": "curve", "key": "beamwidth", "title": "Beamwidth Target Compare", "help": "Shortlist beamwidth overlay against target."},
        {"slot": "C", "kind": "pareto", "key": "pareto", "title": "Pareto Scatter", "help": "Concept trade-off scatter for shortlisted candidates."},
        {"slot": "D", "kind": "curve", "key": "e_cov", "title": "Coverage Compare (E_cov)", "help": "Coverage uniformity overlay across shortlisted candidates."},
    ],
    "stabilization": [
        {"slot": "A", "kind": "heatmap", "key": "heatmap", "title": "Polar Heatmap", "help": "Single-candidate heatmap view (select C1..C5 above)."},
        {"slot": "B", "kind": "curve", "key": "di_proxy", "title": "DI Trend Compare", "help": "DI-proxy trend overlay for shortlisted candidates."},
        {"slot": "C", "kind": "curve", "key": "s_theta", "title": "Smoothness Compare", "help": "S_theta overlay across shortlisted candidates."},
        {"slot": "D", "kind": "curve", "key": "e_sym_shape", "title": "Plane Consistency Compare", "help": "E_sym_shape overlay across shortlisted candidates."},
    ],
    "final": [
        {"slot": "A", "kind": "heatmap", "key": "heatmap", "title": "Polar Heatmap", "help": "Single-candidate heatmap view (select C1..C5 above)."},
        {"slot": "B", "kind": "curve", "key": "r_off", "title": "Ripple Defect Compare", "help": "Off-axis ripple defect overlay for shortlisted candidates."},
        {"slot": "C", "kind": "curve", "key": "e_sym_shape", "title": "Plane Consistency Compare", "help": "E_sym_shape overlay across shortlisted candidates."},
        {"slot": "D", "kind": "curve", "key": "s_theta", "title": "Smoothness Compare", "help": "S_theta overlay across shortlisted candidates."},
    ],
}

PARETO_AXIS_OPTIONS: List[Tuple[str, str]] = [
    ("score", "Score"),
    ("e_bw", "Beamwidth Error"),
    ("e_cov", "Coverage Error"),
    ("r_spill", "Spill Index"),
    ("b_pc_oct", "Pattern Control (oct)"),
    ("flags_count", "Flags"),
    ("di_proxy", "DI Proxy"),
    ("s_theta", "Smoothness"),
    ("e_sym_shape", "Plane Consistency"),
    ("r_off", "Off-axis Ripple"),
]

STAGE_PARETO_DEFAULTS: Dict[str, Tuple[str, str]] = {
    "concept": ("e_bw", "r_spill"),
    "stabilization": ("di_proxy", "s_theta"),
    "final": ("r_off", "s_theta"),
}

COMPARE_BASE_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("slot", "Slot"),
    ("selection", "Selection"),
    ("score", "Score"),
    ("flags", "Flags"),
)

COMPARE_DEFAULT_KPI_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("b_pc_oct", "Pattern Ctrl (oct)"),
    ("e_bw", "BW Err (deg)"),
    ("e_cov", "Cov Err (dB)"),
    ("r_spill", "Spill Ratio"),
)

COMPARE_STAGE_KPI_COLUMNS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "concept": (
        ("b_pc_oct", "Pattern Ctrl (oct)"),
        ("e_bw", "BW Err (deg)"),
        ("e_cov", "Cov Err (dB)"),
        ("r_spill", "Spill Ratio"),
    ),
    "stabilization": (
        ("di_proxy", "DI Trend (dB)"),
        ("s_theta", "Smoothness"),
        ("e_sym_shape", "Plane Consistency"),
    ),
    "final": (
        ("r_off", "Off-axis Ripple (dB)"),
        ("s_theta", "Smoothness"),
        ("e_sym_shape", "Plane Consistency"),
    ),
}

VERSION_INFO_STAGE_METRICS: Dict[str, Tuple[str, ...]] = {
    "concept": ("score", "b_pc_oct", "e_bw", "e_cov", "r_spill", "flags"),
    "stabilization": ("score", "di_proxy", "s_theta", "e_sym_shape", "flags"),
    "final": ("score", "r_off", "s_theta", "e_sym_shape", "flags"),
}

VERSION_INFO_METRIC_META: Dict[str, Dict[str, Any]] = {
    "score": {"label": "Score", "tip": "Stage score for the selected Batch/Version.", "digits": 2},
    "b_pc_oct": {"label": "Pattern Ctrl", "tip": "Pattern control, in octave units.", "digits": 2},
    "e_bw": {"label": "BW Error", "tip": "Beamwidth error in degrees.", "digits": 2},
    "e_cov": {"label": "Cov Error", "tip": "Coverage uniformity error in dB.", "digits": 2},
    "r_spill": {"label": "Spill", "tip": "Spill ratio in the selected window.", "digits": 3},
    "di_proxy": {"label": "DI Proxy", "tip": "Local-window level minus wide-angle proxy level.", "digits": 2},
    "s_theta": {"label": "Smoothness", "tip": "RMS angular gradient in the active window.", "digits": 3},
    "e_sym_shape": {"label": "Plane Consistency", "tip": "Inter-plane spread of beamwidth/DI behavior.", "digits": 3},
    "r_off": {"label": "Off-axis Ripple", "tip": "Ripple spread across key off-axis angles.", "digits": 2},
    "flags": {"label": "Flags", "tip": "Flag summary count and severity tags."},
}


class HeatmapCanvas(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AnalyzerHeatmapCanvas")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._matrix: List[List[Optional[float]]] = []
        self._freqs_hz: List[float] = []
        self._angles_deg: List[float] = []
        self._clamp_enabled = True
        self._clamp_min_db = -20.0
        self._show_raw_bins = False
        self._status = "Select version + plane to render heatmap."
        self._ref_angle_deg: Optional[float] = None
        self._minus6_contour: List[Dict[str, float]] = []
        self._target_half_window_deg: Optional[float] = None
        self._show_mirrored_minus6 = False
        self._x_label = "Frequency (Hz, log)"
        self._y_label = "Angle (deg)"
        self._target_shade_alpha = 24
        self._target_boundary_alpha = 140
        self._contour_color = QColor("#FFE38A")
        self._contour_width = 2.0
        self._applied_plot_margins: Tuple[int, int, int, int] = apply_analyzer_plot_margins(has_legend=False)
        self._lut = get_vacs_like_lut(256)

    def set_heatmap_data(
        self,
        *,
        matrix: List[List[Optional[float]]],
        freqs_hz: Optional[List[float]] = None,
        angles_deg: Optional[List[float]] = None,
        clamp_enabled: bool,
        clamp_min_db: float,
        show_raw_bins: bool = False,
        ref_angle_deg: Optional[float],
        minus6_contour: Optional[List[Dict[str, float]]] = None,
        target_half_window_deg: Optional[float] = None,
        show_mirrored_minus6: bool = False,
        target_shade_alpha: int = 24,
        target_boundary_alpha: int = 140,
        contour_color: Optional[Tuple[int, int, int]] = None,
        contour_width: float = 2.0,
        status: str = "",
    ) -> None:
        self._matrix = [list(row) for row in list(matrix or [])]
        self._freqs_hz = [float(value) for value in list(freqs_hz or []) if float(value) > 0.0]
        self._angles_deg = [float(value) for value in list(angles_deg or [])]
        self._clamp_enabled = bool(clamp_enabled)
        self._clamp_min_db = float(clamp_min_db)
        self._show_raw_bins = bool(show_raw_bins)
        self._ref_angle_deg = float(ref_angle_deg) if ref_angle_deg is not None else None
        self._minus6_contour = [dict(item) for item in list(minus6_contour or []) if isinstance(item, dict)]
        self._target_half_window_deg = (
            float(target_half_window_deg) if target_half_window_deg is not None else None
        )
        self._show_mirrored_minus6 = bool(show_mirrored_minus6)
        self._target_shade_alpha = max(0, min(int(target_shade_alpha), 255))
        self._target_boundary_alpha = max(0, min(int(target_boundary_alpha), 255))
        if isinstance(contour_color, tuple) and len(contour_color) >= 3:
            self._contour_color = QColor(int(contour_color[0]), int(contour_color[1]), int(contour_color[2]))
        else:
            self._contour_color = QColor("#FFE38A")
        try:
            contour_width_value = float(contour_width)
        except Exception:
            contour_width_value = 2.0
        self._contour_width = max(1.0, min(contour_width_value, 4.0))
        self._status = str(status or "").strip()
        self._rerender()

    def clear_heatmap(self, message: str) -> None:
        self._matrix = []
        self._status = str(message or "No heatmap data.")
        self._minus6_contour = []
        self._target_half_window_deg = None
        self._show_mirrored_minus6 = False
        self._target_shade_alpha = 24
        self._target_boundary_alpha = 140
        self._contour_color = QColor("#FFE38A")
        self._contour_width = 2.0
        self._rerender()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        QTimer.singleShot(0, self._rerender)

    def _color_for_value(self, value_db: float) -> QColor:
        t = max(0.0, min(1.0, float(value_db)))
        lut = self._lut if self._lut else [(20, 40, 120), (255, 220, 80)]
        index = min(int(round(t * float(len(lut) - 1))), len(lut) - 1)
        r, g, b = lut[index]
        return QColor(int(r), int(g), int(b))

    def _rerender(self) -> None:
        width = max(int(self.width()), 120)
        height = max(int(self.height()), 120)
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("#111217"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if not self._matrix:
            painter.setPen(QColor("#9AA4B2"))
            painter.drawText(image.rect(), Qt.AlignCenter, self._status or "No heatmap data.")
            painter.end()
            self.setPixmap(QPixmap.fromImage(image))
            return

        rows = len(self._matrix)
        cols = len(self._matrix[0]) if rows > 0 else 0
        if rows <= 0 or cols <= 0:
            painter.setPen(QColor("#9AA4B2"))
            painter.drawText(image.rect(), Qt.AlignCenter, self._status or "No heatmap data.")
            painter.end()
            self.setPixmap(QPixmap.fromImage(image))
            return

        theme = apply_plot_theme(self, has_legend=False, context="heatmap")
        margins = dict(theme.get("margins") or {})
        margin_left = int(margins.get("left", ANALYZER_PLOT_STYLE.left_margin_px))
        margin_right = int(margins.get("right", ANALYZER_PLOT_STYLE.right_margin_no_legend_px))
        margin_top = int(margins.get("top", ANALYZER_PLOT_STYLE.top_margin_px))
        margin_bottom = int(margins.get("bottom", ANALYZER_PLOT_STYLE.bottom_margin_px))
        self._applied_plot_margins = (margin_left, margin_right, margin_top, margin_bottom)
        plot_w = max(width - margin_left - margin_right, 24)
        plot_h = max(height - margin_top - margin_bottom, 24)

        min_db = float(self._clamp_min_db if self._clamp_enabled else -60.0)
        max_db = 0.0
        for row in self._matrix:
            for value in row:
                if value is None:
                    continue
                if not self._clamp_enabled:
                    min_db = min(min_db, float(value))
        span = max(max_db - min_db, 1.0)

        source_image = QImage(max(cols, 1), max(rows, 1), QImage.Format_ARGB32_Premultiplied)
        source_image.fill(QColor("#1A1E26"))
        for y_idx, row in enumerate(self._matrix):
            for x_idx, value in enumerate(row):
                if value is None:
                    color = QColor("#1A1E26")
                else:
                    db = float(value)
                    if self._clamp_enabled:
                        db = max(min_db, min(max_db, db))
                    norm = (db - min_db) / span
                    color = self._color_for_value(norm)
                draw_y = max(rows - 1 - y_idx, 0)
                source_image.setPixelColor(x_idx, draw_y, color)

        transform = Qt.FastTransformation if self._show_raw_bins else Qt.SmoothTransformation
        scaled = source_image.scaled(plot_w, plot_h, Qt.IgnoreAspectRatio, transform)
        painter.drawImage(margin_left, margin_top, scaled)

        freqs = list(self._freqs_hz)
        if len(freqs) == cols and min(freqs) > 0.0:
            f_min = float(min(freqs))
            f_max = float(max(freqs))
            log_min = math.log10(f_min)
            log_max = math.log10(f_max)

            size_class = str(theme.get("size_class") or "large")
            major_ticks, minor_ticks = _log_tick_sets(f_min, f_max, size_class=size_class)

            def x_of(freq: float) -> int:
                u = (math.log10(max(freq, 1.0)) - log_min) / max(log_max - log_min, 1.0e-6)
                return int(round(margin_left + (u * plot_w)))

            painter.setPen(QPen(QColor(ANALYZER_PLOT_STYLE.grid_minor_color), 1))
            for tick in minor_ticks:
                x = x_of(float(tick))
                painter.drawLine(x, margin_top, x, margin_top + plot_h)

            painter.setPen(QPen(QColor(ANALYZER_PLOT_STYLE.grid_major_color), 1))
            painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("tick_font_px", 8))))
            for tick in major_ticks:
                x = x_of(float(tick))
                painter.drawLine(x, margin_top, x, margin_top + plot_h)
                painter.setPen(QColor("#A6AFBC"))
                painter.drawText(
                    x - 22,
                    margin_top + plot_h + int(theme.get("x_tick_label_y_offset_px", ANALYZER_PLOT_STYLE.x_tick_label_y_offset_px)),
                    44,
                    int(theme.get("x_tick_label_height_px", ANALYZER_PLOT_STYLE.x_tick_label_height_px)),
                    Qt.AlignCenter,
                    _format_freq_label(tick),
                )
                painter.setPen(QPen(QColor(ANALYZER_PLOT_STYLE.grid_major_color), 1))

        angle_min = None
        angle_max = None
        if len(self._angles_deg) == rows:
            angle_min = float(min(self._angles_deg))
            angle_max = float(max(self._angles_deg))

            def y_of(angle_value: float) -> int:
                if angle_max <= angle_min:
                    return margin_top + plot_h // 2
                u = (float(angle_value) - angle_min) / max(angle_max - angle_min, 1.0e-6)
                return int(round(margin_top + ((1.0 - u) * plot_h)))

            painter.setPen(QPen(QColor(ANALYZER_PLOT_STYLE.grid_y_color), 1))
            for angle_tick in _angle_ticks(angle_min, angle_max, size_class=str(theme.get("size_class") or "large")):
                y = y_of(float(angle_tick))
                painter.drawLine(margin_left, y, margin_left + plot_w, y)
                painter.setPen(QColor("#A6AFBC"))
                painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("tick_font_px", 8))))
                tick_text_w = max(int(margin_left - int(theme.get("y_tick_label_right_pad_px", ANALYZER_PLOT_STYLE.y_tick_label_right_pad_px)) - 4), 20)
                painter.drawText(
                    4,
                    y - (int(theme.get("y_tick_label_height_px", ANALYZER_PLOT_STYLE.y_tick_label_height_px)) // 2),
                    tick_text_w,
                    int(theme.get("y_tick_label_height_px", ANALYZER_PLOT_STYLE.y_tick_label_height_px)),
                    Qt.AlignRight | Qt.AlignVCenter,
                    f"{angle_tick:.0f}",
                )
                painter.setPen(QPen(QColor(ANALYZER_PLOT_STYLE.grid_y_color), 1))

        if angle_min is not None and angle_max is not None and self._target_half_window_deg is not None:
            target_region, boundary_lines = _visible_target_angle_window(
                angle_min=float(angle_min),
                angle_max=float(angle_max),
                half_window_deg=float(self._target_half_window_deg),
            )
            if target_region is not None:
                y_hi = y_of(float(target_region[1]))
                y_lo = y_of(float(target_region[0]))
                shade_top = min(int(y_hi), int(y_lo))
                shade_height = max(abs(int(y_lo) - int(y_hi)), 1)
                painter.fillRect(
                    margin_left,
                    shade_top,
                    plot_w,
                    shade_height,
                    QColor(93, 168, 255, int(self._target_shade_alpha)),
                )
            if boundary_lines:
                painter.setPen(QPen(QColor(142, 196, 255, int(self._target_boundary_alpha)), 1, Qt.DashLine))
                for angle_line in boundary_lines:
                    y_line = y_of(float(angle_line))
                    painter.drawLine(margin_left, y_line, margin_left + plot_w, y_line)

        if (
            self._minus6_contour
            and len(freqs) == cols
            and min(freqs) > 0.0
            and angle_min is not None
            and angle_max is not None
            and angle_max > angle_min
        ):
            f_min = float(min(freqs))
            f_max = float(max(freqs))
            log_min = math.log10(f_min)
            log_max = math.log10(f_max)

            def x_of(freq_value: float) -> float:
                u = (math.log10(max(float(freq_value), 1.0)) - log_min) / max(log_max - log_min, 1.0e-6)
                return float(margin_left + (u * plot_w))

            def y_of(angle_value: float) -> float:
                u = (float(angle_value) - float(angle_min)) / max(float(angle_max - angle_min), 1.0e-6)
                return float(margin_top + ((1.0 - u) * plot_h))

            left_points: List[Tuple[float, float]] = []
            right_points: List[Tuple[float, float]] = []
            for row in self._minus6_contour:
                try:
                    freq_value = float(row.get("freq_hz"))
                    left_angle = float(row.get("left_angle_deg"))
                    right_angle = float(row.get("right_angle_deg"))
                except Exception:
                    continue
                if freq_value < f_min or freq_value > f_max:
                    continue
                if _should_render_minus6_angle(
                    left_angle,
                    angle_min=float(angle_min),
                    angle_max=float(angle_max),
                    show_mirrored=bool(self._show_mirrored_minus6),
                ):
                    left_points.append((x_of(freq_value), y_of(left_angle)))
                if _should_render_minus6_angle(
                    right_angle,
                    angle_min=float(angle_min),
                    angle_max=float(angle_max),
                    show_mirrored=bool(self._show_mirrored_minus6),
                ):
                    right_points.append((x_of(freq_value), y_of(right_angle)))
            painter.setPen(QPen(QColor(self._contour_color), float(self._contour_width)))
            for idx in range(len(left_points) - 1):
                x1, y1 = left_points[idx]
                x2, y2 = left_points[idx + 1]
                painter.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))
            for idx in range(len(right_points) - 1):
                x1, y1 = right_points[idx]
                x2, y2 = right_points[idx + 1]
                painter.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))

        painter.setPen(QPen(QColor("#3A4252"), 1))
        painter.drawRect(margin_left, margin_top, plot_w, plot_h)
        painter.setPen(QColor("#A6AFBC"))
        painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("axis_font_px", 9))))
        _draw_analyzer_x_axis_label(
            painter,
            text=self._x_label,
            margin_left=margin_left,
            plot_w=plot_w,
            canvas_height=height,
        )
        _draw_analyzer_y_axis_label(
            painter,
            text=self._y_label,
            margin_top=margin_top,
            plot_h=plot_h,
        )
        painter.setPen(QPen(QColor("#3A4252")))
        painter.drawRect(0, 0, width - 1, height - 1)
        if self._status:
            painter.setPen(QColor("#B8C1CF"))
            painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("tick_font_px", 8))))
            painter.drawText(margin_left + 4, margin_top + 16, self._status)
        painter.end()
        self.setPixmap(QPixmap.fromImage(image))


class MetricCurveCanvas(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AnalyzerMetricCurveCanvas")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._series: List[Dict[str, Any]] = []
        self._x_scale_mode = "log"
        self._x_label = "Frequency (Hz, log)"
        self._y_label = "Value"
        self._status = "Curve not available."
        self._applied_plot_margins: Tuple[int, int, int, int] = apply_analyzer_plot_margins(has_legend=False)

    def set_series(
        self,
        *,
        series: Sequence[Mapping[str, Any]],
        x_scale_mode: str = "log",
        x_label: str = "Frequency (Hz, log)",
        y_label: str = "Value",
        status: str = "",
    ) -> None:
        self._series = [dict(item) for item in list(series or []) if isinstance(item, Mapping)]
        token = str(x_scale_mode or "log").strip().lower()
        self._x_scale_mode = token if token in {"log", "linear"} else "log"
        self._x_label = str(x_label or "Frequency")
        self._y_label = str(y_label or "Value")
        self._status = str(status or "").strip()
        self._rerender()

    def clear_series(self, message: str) -> None:
        self._series = []
        self._status = str(message or "Curve not available.")
        self._rerender()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        QTimer.singleShot(0, self._rerender)

    def _rerender(self) -> None:
        width = max(int(self.width()), 180)
        height = max(int(self.height()), 140)
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("#111217"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)

        points_by_series: List[Dict[str, Any]] = []
        for index, row in enumerate(self._series):
            label = str(row.get("label") or f"S{index + 1}")
            show_legend = bool(row.get("show_legend", bool(label.strip())))
            points_raw = list(row.get("points", []) or [])
            style_token = str(row.get("style") or "line").strip().lower()
            if style_token not in {"line", "trend_band", "consistency_strip", "defect_band"}:
                style_token = "line"
            color_raw = row.get("color")
            if isinstance(color_raw, QColor):
                color = color_raw
            elif isinstance(color_raw, tuple):
                color = QColor(*color_raw)
            else:
                color = QColor(*compare_overlay_color(index))
            alpha_raw = row.get("alpha")
            if alpha_raw is not None:
                try:
                    alpha_value = float(alpha_raw)
                    if alpha_value <= 1.0:
                        color.setAlphaF(max(0.0, min(alpha_value, 1.0)))
                    else:
                        color.setAlpha(max(0, min(int(round(alpha_value)), 255)))
                except Exception:
                    pass
            try:
                line_width = float(row.get("line_width", 2.0))
            except Exception:
                line_width = 2.0
            line_width = max(1.0, min(line_width, 2.0))
            try:
                fill_alpha = float(row.get("fill_alpha", 0.18))
            except Exception:
                fill_alpha = 0.18
            fill_alpha = max(0.0, min(fill_alpha, 0.95))
            thresholds: List[float] = []
            for threshold_raw in list(row.get("thresholds", []) or []):
                try:
                    thresholds.append(float(threshold_raw))
                except Exception:
                    continue
            thresholds = sorted(set(thresholds))
            regime_markers = bool(row.get("regime_markers", False))
            points: List[Tuple[float, float]] = []
            for item in points_raw:
                if isinstance(item, Mapping):
                    try:
                        freq = float(item.get("freq_hz"))  # type: ignore[arg-type]
                        value = float(item.get("value"))  # type: ignore[arg-type]
                    except Exception:
                        continue
                elif isinstance(item, (tuple, list)) and len(item) >= 2:
                    try:
                        freq = float(item[0])
                        value = float(item[1])
                    except Exception:
                        continue
                else:
                    continue
                if freq <= 0.0:
                    continue
                points.append((freq, value))
            if points:
                points_by_series.append(
                    {
                        "label": label,
                        "points": points,
                        "color": color,
                        "show_legend": show_legend,
                        "line_width": line_width,
                        "style": style_token,
                        "fill_alpha": fill_alpha,
                        "thresholds": thresholds,
                        "regime_markers": regime_markers,
                        "hotspot_threshold": row.get("hotspot_threshold"),
                    }
                )

        if not points_by_series:
            painter.setPen(QColor("#9AA4B2"))
            painter.drawText(image.rect(), Qt.AlignCenter, self._status or "Curve not available.")
            painter.end()
            self.setPixmap(QPixmap.fromImage(image))
            return

        has_legend = any(bool(row.get("show_legend")) for row in points_by_series)
        theme = apply_plot_theme(self, has_legend=has_legend, context="curve")
        margins = dict(theme.get("margins") or {})
        margin_left = int(margins.get("left", ANALYZER_PLOT_STYLE.left_margin_px))
        margin_right = int(margins.get("right", ANALYZER_PLOT_STYLE.right_margin_with_legend_px if has_legend else ANALYZER_PLOT_STYLE.right_margin_no_legend_px))
        margin_top = int(margins.get("top", ANALYZER_PLOT_STYLE.top_margin_px))
        margin_bottom = int(margins.get("bottom", ANALYZER_PLOT_STYLE.bottom_margin_px))
        self._applied_plot_margins = (margin_left, margin_right, margin_top, margin_bottom)
        plot_w = max(width - margin_left - margin_right, 36)
        plot_h = max(height - margin_top - margin_bottom, 30)

        all_freqs = [point[0] for row in points_by_series for point in list(row.get("points", []) or [])]
        all_values = [point[1] for row in points_by_series for point in list(row.get("points", []) or [])]
        x_mode = self._x_scale_mode
        if x_mode == "linear":
            x_min = float(min(all_freqs))
            x_max = float(max(all_freqs))
            if x_max <= x_min:
                x_max = x_min + 1.0
        else:
            x_min = float(min(all_freqs))
            x_max = float(max(all_freqs))
            log_min = math.log10(max(x_min, 1.0))
            log_max = math.log10(max(x_max, x_min + 1.0e-6))
            if log_max <= log_min:
                log_max = log_min + 1.0
        y_min = float(min(all_values))
        y_max = float(max(all_values))
        if y_max <= y_min:
            y_max = y_min + 1.0

        def x_of(freq_hz: float) -> float:
            if x_mode == "linear":
                u = (float(freq_hz) - float(x_min)) / max(float(x_max - x_min), 1.0e-6)
            else:
                u = (math.log10(max(float(freq_hz), 1.0)) - float(log_min)) / max(float(log_max - log_min), 1.0e-6)
            return float(margin_left + (u * plot_w))

        def y_of(value: float) -> float:
            u = (float(value) - float(y_min)) / max(float(y_max - y_min), 1.0e-6)
            return float(margin_top + ((1.0 - u) * plot_h))

        y_ticks = _linear_ticks(y_min, y_max, max_count=6)
        y_positions: List[Tuple[float, int]] = []
        for y_tick in y_ticks:
            y = int(round(y_of(y_tick)))
            y_positions.append((float(y_tick), y))
            painter.setPen(QPen(QColor(ANALYZER_PLOT_STYLE.grid_y_color), 1))
            painter.drawLine(margin_left, y, margin_left + plot_w, y)
        painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("tick_font_px", 8))))
        last_label_y = -10_000
        for y_tick, y in sorted(y_positions, key=lambda item: item[1]):
            if abs(int(y) - int(last_label_y)) < int(theme.get("y_tick_label_min_gap_px", ANALYZER_PLOT_STYLE.y_tick_label_min_gap_px)):
                continue
            painter.setPen(QColor("#A6AFBC"))
            tick_text_w = max(int(margin_left - int(theme.get("y_tick_label_right_pad_px", ANALYZER_PLOT_STYLE.y_tick_label_right_pad_px)) - 4), 20)
            painter.drawText(
                4,
                y - (int(theme.get("y_tick_label_height_px", ANALYZER_PLOT_STYLE.y_tick_label_height_px)) // 2),
                tick_text_w,
                int(theme.get("y_tick_label_height_px", ANALYZER_PLOT_STYLE.y_tick_label_height_px)),
                Qt.AlignRight | Qt.AlignVCenter,
                f"{y_tick:.2f}",
            )
            last_label_y = int(y)

        if x_mode == "linear":
            major_ticks = _linear_ticks(x_min, x_max, max_count=6)
            minor_ticks: List[float] = []
        else:
            major_ticks, minor_ticks = _log_tick_sets(x_min, x_max, size_class=str(theme.get("size_class") or "large"))

        painter.setPen(QPen(QColor(ANALYZER_PLOT_STYLE.grid_minor_color), 1))
        for tick in minor_ticks:
            x = int(round(x_of(tick)))
            painter.drawLine(x, margin_top, x, margin_top + plot_h)
        painter.setPen(QPen(QColor(ANALYZER_PLOT_STYLE.grid_major_color), 1))
        painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("tick_font_px", 8))))
        for tick in major_ticks:
            x = int(round(x_of(tick)))
            painter.drawLine(x, margin_top, x, margin_top + plot_h)
            painter.setPen(QColor("#A6AFBC"))
            painter.drawText(
                x - 22,
                margin_top + plot_h + int(theme.get("x_tick_label_y_offset_px", ANALYZER_PLOT_STYLE.x_tick_label_y_offset_px)),
                44,
                int(theme.get("x_tick_label_height_px", ANALYZER_PLOT_STYLE.x_tick_label_height_px)),
                Qt.AlignCenter,
                _format_freq_label(tick),
            )
            painter.setPen(QPen(QColor(ANALYZER_PLOT_STYLE.grid_major_color), 1))

        defect_rows = [row for row in points_by_series if str(row.get("style") or "").strip().lower() == "defect_band"]

        def _fill_horizontal_band(value_lo: float, value_hi: float, color: QColor) -> None:
            lo = max(float(y_min), min(float(value_lo), float(y_max)))
            hi = max(float(y_min), min(float(value_hi), float(y_max)))
            if hi <= lo:
                return
            y_a = int(round(y_of(lo)))
            y_b = int(round(y_of(hi)))
            top = min(y_a, y_b)
            height_px = max(abs(y_b - y_a), 1)
            painter.fillRect(margin_left, top, plot_w, height_px, color)

        if defect_rows:
            defect_thresholds = sorted(
                {
                    float(item)
                    for row in defect_rows
                    for item in list(row.get("thresholds", []) or [])
                    if y_min <= float(item) <= y_max
                }
            )
            if len(defect_thresholds) >= 3:
                _fill_horizontal_band(y_min, defect_thresholds[0], QColor(74, 124, 90, 28))
                _fill_horizontal_band(defect_thresholds[0], defect_thresholds[1], QColor(170, 142, 72, 32))
                _fill_horizontal_band(defect_thresholds[1], defect_thresholds[2], QColor(186, 96, 82, 38))
                _fill_horizontal_band(defect_thresholds[2], y_max, QColor(204, 78, 78, 48))
            elif len(defect_thresholds) >= 2:
                _fill_horizontal_band(y_min, defect_thresholds[0], QColor(74, 124, 90, 28))
                _fill_horizontal_band(defect_thresholds[0], defect_thresholds[1], QColor(170, 142, 72, 34))
                _fill_horizontal_band(defect_thresholds[1], y_max, QColor(196, 82, 82, 44))

        threshold_values = sorted(
            {
                float(value)
                for row in points_by_series
                for value in list(row.get("thresholds", []) or [])
                if y_min <= float(value) <= y_max
            }
        )
        if threshold_values:
            painter.setPen(QPen(QColor(110, 118, 134, 120), 1, Qt.DashLine))
            for threshold in threshold_values:
                y_line = int(round(y_of(float(threshold))))
                painter.drawLine(margin_left, y_line, margin_left + plot_w, y_line)

        def _draw_polyline(points: List[Tuple[float, float]], color: QColor, width_px: float) -> None:
            painter.setPen(QPen(color, float(width_px)))
            for idx in range(len(points) - 1):
                x1, y1 = points[idx]
                x2, y2 = points[idx + 1]
                painter.drawLine(int(round(x_of(x1))), int(round(y_of(y1))), int(round(x_of(x2))), int(round(y_of(y2))))

        legend_y = margin_top + 4
        for row in points_by_series:
            label = str(row.get("label") or "")
            points = list(row.get("points", []) or [])
            color = QColor(row.get("color")) if isinstance(row.get("color"), QColor) else QColor("#9AA4B2")
            show_legend = bool(row.get("show_legend"))
            line_width = float(row.get("line_width", 2.0))
            style_token = str(row.get("style") or "line").strip().lower()
            if style_token == "trend_band" and len(points) >= 2:
                values = [float(value) for _freq, value in points]
                mean_value = float(sum(values) / float(len(values)))
                fill_alpha = float(row.get("fill_alpha", 0.18))
                fill_color = QColor(color)
                fill_color.setAlphaF(max(0.0, min(fill_alpha, 0.95)))
                band = QPainterPath()
                first_x, first_y = points[0]
                band.moveTo(x_of(first_x), y_of(first_y))
                for freq_hz, value in points[1:]:
                    band.lineTo(x_of(freq_hz), y_of(value))
                for freq_hz, _value in reversed(points):
                    band.lineTo(x_of(freq_hz), y_of(mean_value))
                band.closeSubpath()
                painter.fillPath(band, fill_color)
                _draw_polyline(points, color, max(line_width, 1.0))
                if bool(row.get("regime_markers")) and len(points) >= 3:
                    marker_brush = QColor(color)
                    marker_brush.setAlpha(196)
                    painter.setBrush(marker_brush)
                    painter.setPen(QPen(color, 1))
                    for idx in range(1, len(points) - 1):
                        prev_value = float(points[idx - 1][1])
                        curr_value = float(points[idx][1])
                        next_value = float(points[idx + 1][1])
                        slope_left = curr_value - prev_value
                        slope_right = next_value - curr_value
                        if abs(slope_left) <= 1.0e-9 or abs(slope_right) <= 1.0e-9:
                            continue
                        if slope_left * slope_right < 0.0:
                            marker_x = int(round(x_of(points[idx][0])))
                            marker_y = int(round(y_of(points[idx][1])))
                            painter.drawEllipse(QPoint(marker_x, marker_y), 3, 3)
                    painter.setBrush(Qt.NoBrush)
            elif style_token == "consistency_strip" and len(points) >= 2:
                strip_height = max(10, int(round(plot_h * 0.13)))
                strip_top = int(margin_top + 4)
                for idx in range(len(points) - 1):
                    x1, value1 = points[idx]
                    x2, _value2 = points[idx + 1]
                    seg_left = int(round(min(x_of(x1), x_of(x2))))
                    seg_right = int(round(max(x_of(x1), x_of(x2))))
                    seg_w = max(seg_right - seg_left, 1)
                    normalized = (float(value1) - float(y_min)) / max(float(y_max - y_min), 1.0e-6)
                    strip_color = QColor(color)
                    strip_color.setAlpha(int(round(34 + (150.0 * max(0.0, min(normalized, 1.0))))))
                    painter.fillRect(seg_left, strip_top, seg_w, strip_height, strip_color)
                _draw_polyline(points, color, max(line_width, 1.0))
            elif style_token == "defect_band" and len(points) >= 2:
                fill_alpha = float(row.get("fill_alpha", 0.22))
                fill_color = QColor(color)
                fill_color.setAlphaF(max(0.0, min(fill_alpha, 0.95)))
                band = QPainterPath()
                first_x, first_y = points[0]
                band.moveTo(x_of(first_x), y_of(first_y))
                for freq_hz, value in points[1:]:
                    band.lineTo(x_of(freq_hz), y_of(value))
                for freq_hz, _value in reversed(points):
                    band.lineTo(x_of(freq_hz), y_of(y_min))
                band.closeSubpath()
                painter.fillPath(band, fill_color)
                _draw_polyline(points, color, max(line_width, 1.0))
                hotspot_raw = row.get("hotspot_threshold")
                hotspot_threshold = None
                if hotspot_raw is not None:
                    try:
                        hotspot_threshold = float(hotspot_raw)
                    except Exception:
                        hotspot_threshold = None
                if hotspot_threshold is None:
                    thresholds = [float(item) for item in list(row.get("thresholds", []) or [])]
                    hotspot_threshold = max(thresholds) if thresholds else None
                if hotspot_threshold is not None:
                    painter.setBrush(QColor(255, 214, 166, 220))
                    painter.setPen(QPen(QColor(255, 168, 120), 1))
                    for freq_hz, value in points:
                        if float(value) >= float(hotspot_threshold):
                            painter.drawEllipse(QPoint(int(round(x_of(freq_hz))), int(round(y_of(value)))), 3, 3)
                    painter.setBrush(Qt.NoBrush)
            else:
                _draw_polyline(points, color, line_width)
            if has_legend and show_legend:
                painter.setPen(QPen(color, 1))
                painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("legend_font_px", 8))))
                text = painter.fontMetrics().elidedText(label, Qt.ElideRight, margin_right - 10)
                legend_h = max(int(theme.get("x_tick_label_height_px", 14)), 12)
                painter.drawText(width - margin_right + 4, legend_y, margin_right - 8, legend_h, Qt.AlignLeft | Qt.AlignVCenter, text)
                legend_y += legend_h

        painter.setPen(QPen(QColor("#3A4252"), 1))
        painter.drawRect(margin_left, margin_top, plot_w, plot_h)
        painter.setPen(QColor("#A6AFBC"))
        painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("axis_font_px", 9))))
        _draw_analyzer_x_axis_label(
            painter,
            text=self._x_label,
            margin_left=margin_left,
            plot_w=plot_w,
            canvas_height=height,
        )
        _draw_analyzer_y_axis_label(
            painter,
            text=self._y_label,
            margin_top=margin_top,
            plot_h=plot_h,
        )
        if self._status:
            painter.setPen(QColor("#B8C1CF"))
            painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("tick_font_px", 8))))
            painter.drawText(margin_left + 4, margin_top + 16, self._status)
        painter.end()
        self.setPixmap(QPixmap.fromImage(image))


class ParetoScatterCanvas(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AnalyzerParetoScatterCanvas")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._points: List[Dict[str, Any]] = []
        self._x_label = "X"
        self._y_label = "Y"
        self._status = "Select candidates to render Pareto scatter."

    def set_points(
        self,
        *,
        points: Sequence[Mapping[str, Any]],
        x_label: str,
        y_label: str,
        status: str = "",
    ) -> None:
        self._points = [dict(item) for item in list(points or []) if isinstance(item, Mapping)]
        self._x_label = str(x_label or "X")
        self._y_label = str(y_label or "Y")
        self._status = str(status or "").strip()
        self._rerender()

    def clear_points(self, message: str) -> None:
        self._points = []
        self._status = str(message or "Select candidates to render Pareto scatter.")
        self._rerender()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        QTimer.singleShot(0, self._rerender)

    def _rerender(self) -> None:
        width = max(int(self.width()), 180)
        height = max(int(self.height()), 140)
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("#111217"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)

        valid: List[Tuple[str, float, float, QColor, bool]] = []
        for index, row in enumerate(self._points):
            label = str(row.get("label") or f"C{index + 1}")
            try:
                x_value = float(row.get("x_value"))
                y_value = float(row.get("y_value"))
            except Exception:
                continue
            color = row.get("color")
            if isinstance(color, QColor):
                dot_color = color
            elif isinstance(color, tuple):
                dot_color = QColor(*color)
            else:
                dot_color = QColor(*compare_overlay_color(index))
            valid.append((label, x_value, y_value, dot_color, bool(row.get("selected", False))))

        if not valid:
            painter.setPen(QColor("#9AA4B2"))
            painter.drawText(image.rect(), Qt.AlignCenter, self._status or "Select candidates to render Pareto scatter.")
            painter.end()
            self.setPixmap(QPixmap.fromImage(image))
            return

        theme = apply_plot_theme(self, has_legend=False, context="pareto")
        margins = dict(theme.get("margins") or {})
        margin_left = int(margins.get("left", ANALYZER_PLOT_STYLE.left_margin_px))
        margin_right = int(margins.get("right", ANALYZER_PLOT_STYLE.right_margin_no_legend_px))
        margin_top = int(margins.get("top", ANALYZER_PLOT_STYLE.top_margin_px))
        margin_bottom = int(margins.get("bottom", ANALYZER_PLOT_STYLE.bottom_margin_px))
        plot_w = max(width - margin_left - margin_right, 36)
        plot_h = max(height - margin_top - margin_bottom, 30)
        x_values = [item[1] for item in valid]
        y_values = [item[2] for item in valid]
        x_min = min(x_values)
        x_max = max(x_values)
        y_min = min(y_values)
        y_max = max(y_values)
        if x_max <= x_min:
            x_max = x_min + 1.0
        if y_max <= y_min:
            y_max = y_min + 1.0

        def x_of(value: float) -> float:
            u = (float(value) - float(x_min)) / max(float(x_max - x_min), 1.0e-6)
            return float(margin_left + (u * plot_w))

        def y_of(value: float) -> float:
            u = (float(value) - float(y_min)) / max(float(y_max - y_min), 1.0e-6)
            return float(margin_top + ((1.0 - u) * plot_h))

        tick_max = 4 if str(theme.get("size_class") or "large") == "small" else 6
        painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("tick_font_px", 8))))
        for y_tick in _linear_ticks(y_min, y_max, max_count=tick_max):
            y = int(round(y_of(y_tick)))
            painter.setPen(QPen(QColor("#2A3344"), 1))
            painter.drawLine(margin_left, y, margin_left + plot_w, y)
            painter.setPen(QColor("#A6AFBC"))
            painter.drawText(
                4,
                y - (int(theme.get("y_tick_label_height_px", 16)) // 2),
                max(int(margin_left - int(theme.get("y_tick_label_right_pad_px", 12)) - 4), 20),
                int(theme.get("y_tick_label_height_px", 16)),
                Qt.AlignRight | Qt.AlignVCenter,
                f"{y_tick:.2f}",
            )
        for x_tick in _linear_ticks(x_min, x_max, max_count=tick_max):
            x = int(round(x_of(x_tick)))
            painter.setPen(QPen(QColor("#2F3A4D"), 1))
            painter.drawLine(x, margin_top, x, margin_top + plot_h)
            painter.setPen(QColor("#A6AFBC"))
            painter.drawText(
                x - 22,
                margin_top + plot_h + int(theme.get("x_tick_label_y_offset_px", 18)),
                44,
                int(theme.get("x_tick_label_height_px", 16)),
                Qt.AlignCenter,
                f"{x_tick:.2f}",
            )

        collision_counts: Dict[Tuple[int, int], int] = {}
        offsets = [(0, 0), (-4, -4), (4, -4), (-4, 4), (4, 4), (0, -6), (0, 6)]
        for label, x_value, y_value, color, selected in valid:
            x = int(round(x_of(x_value)))
            y = int(round(y_of(y_value)))
            key = (x, y)
            seen = int(collision_counts.get(key, 0))
            collision_counts[key] = seen + 1
            dx, dy = offsets[seen % len(offsets)]
            x += int(dx)
            y += int(dy)
            radius = 6 if selected else 4
            if selected:
                painter.setPen(QPen(QColor("#EAF2FF"), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(x - (radius + 2), y - (radius + 2), (radius + 2) * 2, (radius + 2) * 2)
            painter.setPen(QPen(color, 1))
            painter.setBrush(color)
            painter.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)
            painter.setPen(QPen(QColor("#D8E2F0"), 1))
            painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("legend_font_px", 8))))
            painter.drawText(x + 6, y - 2, label)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#3A4252"), 1))
        painter.drawRect(margin_left, margin_top, plot_w, plot_h)
        painter.setPen(QColor("#A6AFBC"))
        painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("axis_font_px", 9))))
        painter.drawText(4, margin_top - 2, margin_left - 8, max(int(theme.get("x_tick_label_height_px", 16)), 14), Qt.AlignLeft | Qt.AlignVCenter, self._y_label)
        painter.drawText(margin_left, height - 8, plot_w, max(int(theme.get("x_tick_label_height_px", 16)), 16), Qt.AlignHCenter | Qt.AlignVCenter, self._x_label)
        if self._status:
            painter.setPen(QColor("#B8C1CF"))
            painter.setFont(_font_with_pixel_size(self.font(), int(theme.get("tick_font_px", 8))))
            painter.drawText(margin_left + 4, margin_top + 16, self._status)
        painter.end()
        self.setPixmap(QPixmap.fromImage(image))


class BeamwidthCanvas(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AnalyzerBeamwidthCanvas")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._curve: List[Dict[str, float]] = []
        self._target_deg = 0.0
        self._tol_deg = 0.0
        self._x_scale_mode = "log"
        self._status = "Beamwidth curve not available."

    def set_curve(
        self,
        *,
        curve: List[Dict[str, float]],
        target_deg: float,
        tol_deg: float,
        x_scale_mode: str = "log",
        status: str = "",
    ) -> None:
        self._curve = [dict(item) for item in list(curve or []) if isinstance(item, dict)]
        self._target_deg = float(target_deg)
        self._tol_deg = float(tol_deg)
        scale = str(x_scale_mode or "log").strip().lower()
        self._x_scale_mode = scale if scale in {"log", "linear"} else "log"
        self._status = str(status or "").strip()
        self._rerender()

    def clear_curve(self, message: str) -> None:
        self._curve = []
        self._status = str(message or "Beamwidth curve not available.")
        self._rerender()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._rerender()

    def _rerender(self) -> None:
        width = max(int(self.width()), 140)
        height = max(int(self.height()), 120)
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("#111217"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if not self._curve:
            painter.setPen(QColor("#9AA4B2"))
            painter.drawText(image.rect(), Qt.AlignCenter, self._status or "Beamwidth curve not available.")
            painter.end()
            self.setPixmap(QPixmap.fromImage(image))
            return

        margin_left, margin_right, margin_top, margin_bottom = _plot_margins(has_legend=False)
        plot_w = max(width - margin_left - margin_right, 30)
        plot_h = max(height - margin_top - margin_bottom, 30)

        freqs = [float(item.get("freq_hz", 0.0)) for item in self._curve if float(item.get("freq_hz", 0.0)) > 0.0]
        bws = [float(item.get("beamwidth_deg", 0.0)) for item in self._curve]
        if not freqs or not bws:
            painter.setPen(QColor("#9AA4B2"))
            painter.drawText(image.rect(), Qt.AlignCenter, self._status or "Beamwidth curve not available.")
            painter.end()
            self.setPixmap(QPixmap.fromImage(image))
            return

        x_mode = str(self._x_scale_mode or "log")
        if x_mode == "linear":
            x_min = float(min(freqs))
            x_max = float(max(freqs))
            if x_max <= x_min:
                x_max = x_min + 1.0
        else:
            log_min = math.log10(min(freqs))
            log_max = math.log10(max(freqs))
            if log_max <= log_min:
                log_max = log_min + 1.0
        y_max = max(max(bws), self._target_deg + self._tol_deg + 10.0, 20.0)
        y_min = max(min(min(bws), self._target_deg - self._tol_deg - 10.0, 0.0), 0.0)
        if y_max <= y_min:
            y_max = y_min + 1.0

        def x_of(freq: float) -> float:
            if x_mode == "linear":
                u = (float(freq) - x_min) / max(x_max - x_min, 1.0e-6)
            else:
                u = (math.log10(max(freq, 1.0)) - log_min) / (log_max - log_min)
            return float(margin_left + (u * plot_w))

        def y_of(width_deg: float) -> float:
            u = (float(width_deg) - y_min) / (y_max - y_min)
            return float(margin_top + ((1.0 - u) * plot_h))

        y_ticks = _linear_ticks(y_min, y_max, max_count=6)
        painter.setPen(QPen(QColor("#2A3344"), 1))
        for y_tick in y_ticks:
            y = int(round(y_of(float(y_tick))))
            painter.drawLine(margin_left, y, margin_left + plot_w, y)
            painter.setPen(QColor("#A6AFBC"))
            painter.drawText(4, y - 8, margin_left - 12, 16, Qt.AlignRight | Qt.AlignVCenter, f"{y_tick:.0f}")
            painter.setPen(QPen(QColor("#2A3344"), 1))

        if x_mode == "linear":
            major_ticks = _linear_ticks(min(freqs), max(freqs), max_count=6)
            minor_ticks: List[float] = []
        else:
            major_ticks, minor_ticks = _log_tick_sets(min(freqs), max(freqs))

        painter.setPen(QPen(QColor("#232A35"), 1))
        for tick in minor_ticks:
            x = int(round(x_of(float(tick))))
            painter.drawLine(x, margin_top, x, margin_top + plot_h)

        last_x = -10_000
        painter.setPen(QPen(QColor("#2F3A4D"), 1))
        for tick in major_ticks:
            x = int(round(x_of(float(tick))))
            painter.drawLine(x, margin_top, x, margin_top + plot_h)
            if x - last_x < 36:
                continue
            last_x = x
            painter.setPen(QColor("#A6AFBC"))
            painter.drawText(x - 22, margin_top + plot_h + 18, 44, 16, Qt.AlignCenter, _format_freq_label(tick))
            painter.setPen(QPen(QColor("#2F3A4D"), 1))

        # tolerance band
        tol_top = y_of(self._target_deg + self._tol_deg)
        tol_bottom = y_of(self._target_deg - self._tol_deg)
        band_top = min(tol_top, tol_bottom)
        band_height = abs(tol_bottom - tol_top)
        painter.fillRect(
            margin_left,
            int(round(band_top)),
            plot_w,
            max(int(round(band_height)), 1),
            QColor(93, 168, 255, 36),
        )
        painter.setPen(QPen(QColor("#5DA8FF"), 1))
        y_target = int(round(y_of(self._target_deg)))
        painter.drawLine(margin_left, y_target, margin_left + plot_w, y_target)

        # curve
        painter.setPen(QPen(QColor("#E6D36A"), 2))
        points = []
        for row in self._curve:
            freq = float(row.get("freq_hz", 0.0))
            bw = float(row.get("beamwidth_deg", 0.0))
            if freq <= 0.0:
                continue
            points.append((x_of(freq), y_of(bw)))
        if len(points) >= 2:
            for idx in range(len(points) - 1):
                x1, y1 = points[idx]
                x2, y2 = points[idx + 1]
                painter.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))

        painter.setPen(QPen(QColor("#3A4252"), 1))
        painter.drawRect(margin_left, margin_top, plot_w, plot_h)
        painter.setPen(QColor("#A6AFBC"))
        painter.drawText(4, margin_top - 2, margin_left - 8, 14, Qt.AlignLeft | Qt.AlignVCenter, "Beamwidth (deg)")
        painter.drawText(
            margin_left,
            height - 8,
            plot_w,
            16,
            Qt.AlignHCenter | Qt.AlignVCenter,
            "Frequency (Hz, log)" if x_mode == "log" else "Frequency (Hz)",
        )
        if self._status:
            painter.setPen(QColor("#B8C1CF"))
            painter.drawText(margin_left + 4, margin_top + 16, self._status)
        painter.end()
        self.setPixmap(QPixmap.fromImage(image))


class BeamwidthOverlayCanvas(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AnalyzerBeamwidthOverlayCanvas")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._series: List[Dict[str, Any]] = []
        self._target_deg = 0.0
        self._tol_deg = 0.0
        self._x_scale_mode = "log"
        self._status = "Compare overlay not available."

    def set_series(
        self,
        *,
        series: List[Dict[str, Any]],
        target_deg: float,
        tol_deg: float,
        x_scale_mode: str = "log",
        status: str = "",
    ) -> None:
        self._series = [dict(item) for item in list(series or []) if isinstance(item, dict)]
        self._target_deg = float(target_deg)
        self._tol_deg = float(tol_deg)
        scale = str(x_scale_mode or "log").strip().lower()
        self._x_scale_mode = scale if scale in {"log", "linear"} else "log"
        self._status = str(status or "").strip()
        self._rerender()

    def clear_series(self, message: str) -> None:
        self._series = []
        self._status = str(message or "Compare overlay not available.")
        self._rerender()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._rerender()

    def _rerender(self) -> None:
        width = max(int(self.width()), 180)
        height = max(int(self.height()), 140)
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("#111217"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)

        flattened: List[Tuple[float, float, int, str]] = []
        for series_idx, series in enumerate(self._series):
            curve = [dict(item) for item in list(series.get("curve", []) or []) if isinstance(item, dict)]
            label = str(series.get("label") or f"C{series_idx + 1}")
            for row in curve:
                freq = float(row.get("freq_hz", 0.0))
                bw = float(row.get("beamwidth_deg", 0.0))
                if freq <= 0.0:
                    continue
                flattened.append((freq, bw, series_idx, label))

        if not flattened:
            painter.setPen(QColor("#9AA4B2"))
            painter.drawText(image.rect(), Qt.AlignCenter, self._status or "Compare overlay not available.")
            painter.end()
            self.setPixmap(QPixmap.fromImage(image))
            return

        legend_width = max(120, min(180, int(width * 0.28)))
        margin_left, _base_right, margin_top, margin_bottom = _plot_margins(has_legend=True)
        margin_right = max(_base_right, legend_width + 12)
        plot_w = max(width - margin_left - margin_right, 30)
        plot_h = max(height - margin_top - margin_bottom, 30)

        freqs = [item[0] for item in flattened]
        widths = [item[1] for item in flattened]
        x_mode = str(self._x_scale_mode or "log")
        if x_mode == "linear":
            x_min = float(min(freqs))
            x_max = float(max(freqs))
            if x_max <= x_min:
                x_max = x_min + 1.0
        else:
            log_min = math.log10(min(freqs))
            log_max = math.log10(max(freqs))
            if log_max <= log_min:
                log_max = log_min + 1.0
        y_max = max(max(widths), self._target_deg + self._tol_deg + 10.0, 20.0)
        y_min = max(min(min(widths), self._target_deg - self._tol_deg - 10.0, 0.0), 0.0)
        if y_max <= y_min:
            y_max = y_min + 1.0

        def x_of(freq: float) -> float:
            if x_mode == "linear":
                u = (float(freq) - x_min) / max(x_max - x_min, 1.0e-6)
            else:
                u = (math.log10(max(freq, 1.0)) - log_min) / (log_max - log_min)
            return float(margin_left + (u * plot_w))

        def y_of(width_deg: float) -> float:
            u = (float(width_deg) - y_min) / (y_max - y_min)
            return float(margin_top + ((1.0 - u) * plot_h))

        y_ticks = _linear_ticks(y_min, y_max, max_count=6)
        painter.setPen(QPen(QColor("#2A3344"), 1))
        for y_tick in y_ticks:
            y = int(round(y_of(float(y_tick))))
            painter.drawLine(margin_left, y, margin_left + plot_w, y)
            painter.setPen(QColor("#A6AFBC"))
            painter.drawText(4, y - 8, margin_left - 12, 16, Qt.AlignRight | Qt.AlignVCenter, f"{y_tick:.0f}")
            painter.setPen(QPen(QColor("#2A3344"), 1))

        if x_mode == "linear":
            major_ticks = _linear_ticks(min(freqs), max(freqs), max_count=6)
            minor_ticks: List[float] = []
        else:
            major_ticks, minor_ticks = _log_tick_sets(min(freqs), max(freqs))

        painter.setPen(QPen(QColor("#232A35"), 1))
        for tick in minor_ticks:
            x = int(round(x_of(float(tick))))
            painter.drawLine(x, margin_top, x, margin_top + plot_h)

        last_x = -10_000
        painter.setPen(QPen(QColor("#2F3A4D"), 1))
        for tick in major_ticks:
            x = int(round(x_of(float(tick))))
            painter.drawLine(x, margin_top, x, margin_top + plot_h)
            if x - last_x < 36:
                continue
            last_x = x
            painter.setPen(QColor("#A6AFBC"))
            painter.drawText(x - 22, margin_top + plot_h + 18, 44, 16, Qt.AlignCenter, _format_freq_label(tick))
            painter.setPen(QPen(QColor("#2F3A4D"), 1))

        tol_top = y_of(self._target_deg + self._tol_deg)
        tol_bottom = y_of(self._target_deg - self._tol_deg)
        band_top = min(tol_top, tol_bottom)
        band_height = abs(tol_bottom - tol_top)
        painter.fillRect(
            margin_left,
            int(round(band_top)),
            plot_w,
            max(int(round(band_height)), 1),
            QColor(93, 168, 255, 28),
        )
        painter.setPen(QPen(QColor("#5DA8FF"), 1))
        y_target = int(round(y_of(self._target_deg)))
        painter.drawLine(margin_left, y_target, margin_left + plot_w, y_target)

        legend_y = margin_top + 4
        for series_idx, series in enumerate(self._series):
            curve = [dict(item) for item in list(series.get("curve", []) or []) if isinstance(item, dict)]
            if len(curve) < 2:
                continue
            color = series.get("color")
            if isinstance(color, QColor):
                line_color = color
            elif isinstance(color, tuple):
                line_color = QColor(*color)
            else:
                palette_rgb = compare_overlay_color(series_idx)
                line_color = QColor(*palette_rgb)
            painter.setPen(QPen(line_color, 2))
            points: List[Tuple[float, float]] = []
            for row in curve:
                freq = float(row.get("freq_hz", 0.0))
                bw = float(row.get("beamwidth_deg", 0.0))
                if freq <= 0.0:
                    continue
                points.append((x_of(freq), y_of(bw)))
            for idx in range(len(points) - 1):
                x1, y1 = points[idx]
                x2, y2 = points[idx + 1]
                painter.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))
            label = str(series.get("label") or f"C{series_idx + 1}")
            painter.setPen(QPen(line_color, 1))
            text_width = max(100, legend_width - 4)
            label_elided = painter.fontMetrics().elidedText(label, Qt.ElideRight, text_width)
            painter.drawText(width - legend_width, legend_y, legend_width - 2, 14, Qt.AlignRight | Qt.AlignVCenter, label_elided)
            legend_y += 14

        painter.setPen(QPen(QColor("#3A4252"), 1))
        painter.drawRect(margin_left, margin_top, plot_w, plot_h)
        painter.setPen(QColor("#A6AFBC"))
        painter.drawText(4, margin_top - 2, margin_left - 8, 14, Qt.AlignLeft | Qt.AlignVCenter, "Beamwidth (deg)")
        painter.drawText(
            margin_left,
            height - 8,
            plot_w,
            16,
            Qt.AlignHCenter | Qt.AlignVCenter,
            "Frequency (Hz, log)" if x_mode == "log" else "Frequency (Hz)",
        )
        if self._status:
            painter.setPen(QColor("#B8C1CF"))
            painter.drawText(margin_left + 4, margin_top + 16, self._status)
        painter.end()
        self.setPixmap(QPixmap.fromImage(image))


class _BatchPreviewWorker(QObject):
    finished = Signal(int, dict)
    failed = Signal(int, str)
    canceled = Signal(int, str)

    def __init__(
        self,
        *,
        service: OrchestratorService,
        project_id: str,
        selected_params: Dict[str, Any],
        sweep_mode: str,
        request_id: int,
    ) -> None:
        super().__init__()
        self._service = service
        self._project_id = str(project_id)
        self._selected_params = dict(selected_params or {})
        self._sweep_mode = str(sweep_mode or "single")
        self._request_id = int(request_id)
        self._cancelled = False
        self._process: Optional[subprocess.Popen[str]] = None

    def cancel(self) -> None:
        self._cancelled = True
        proc = self._process
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception as exc:
            LOGGER.debug("Preview worker cancel terminate failed: %s", exc)
            return

    def _cancel_check(self) -> bool:
        return bool(self._cancelled)

    def _on_process_started(self, process: subprocess.Popen[str]) -> None:
        self._process = process
        if self._cancelled:
            try:
                if process.poll() is None:
                    process.terminate()
            except Exception as exc:
                LOGGER.debug("Preview worker post-start terminate failed: %s", exc)
                return

    def run(self) -> None:
        try:
            result = self._service.generate_preview_stl(
                project_id=self._project_id,
                selected_params=self._selected_params,
                sweep_mode=self._sweep_mode,
                run_id=f"ui_preview_{self._request_id}",
                cancel_check=self._cancel_check,
                process_handle_cb=self._on_process_started,
            )
        except PreviewGenerationCancelled as exc:
            self.canceled.emit(self._request_id, str(exc))
            return
        except Exception as exc:  # pragma: no cover - integration surface
            self.failed.emit(self._request_id, str(exc))
            return
        self.finished.emit(self._request_id, dict(result))


class _BatchRunWorker(QObject):
    finished = Signal(str, dict)
    failed = Signal(str, str)

    def __init__(
        self,
        *,
        service: OrchestratorService,
        project_id: str,
        batch_id: str,
        continue_on_error: bool,
    ) -> None:
        super().__init__()
        self._service = service
        self._project_id = str(project_id)
        self._batch_id = str(batch_id)
        self._continue_on_error = bool(continue_on_error)

    def run(self) -> None:
        try:
            summary = self._service.run_batch(
                self._project_id,
                self._batch_id,
                continue_on_error=self._continue_on_error,
            )
            payload = asdict(summary)
            self.finished.emit(self._batch_id, payload)
        except Exception:
            self.failed.emit(self._batch_id, traceback.format_exc())


class _AnalyzerMetadataWorker(QObject):
    finished = Signal(int, dict)
    failed = Signal(int, str)

    def __init__(
        self,
        *,
        service: OrchestratorService,
        request_id: int,
        source: str,
        project_id: Optional[str],
        batch_id: Optional[str],
        mode: str,
        stage_mode: str,
        target_h_deg: float,
        target_v_deg: float,
        tol_deg: float,
        band_low_hz: float,
        band_high_hz: float,
        algo_version: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._request_id = int(request_id)
        self._source = str(source or "project")
        self._project_id = str(project_id or "").strip() or None
        self._batch_id = str(batch_id or "").strip() or None
        self._mode = str(mode or "overview")
        self._stage_mode = str(stage_mode or DEFAULT_STAGE_ID)
        self._target_h_deg = float(target_h_deg)
        self._target_v_deg = float(target_v_deg)
        self._tol_deg = float(tol_deg)
        self._band_low_hz = float(band_low_hz)
        self._band_high_hz = float(band_high_hz)
        self._algo_version = str(algo_version or ALGO_VERSION)

    def run(self) -> None:
        try:
            if self._mode == "runs":
                if not self._project_id or not self._batch_id:
                    payload = {
                        "mode": "runs",
                        "project_id": self._project_id,
                        "batch_id": self._batch_id,
                        "runs": [],
                    }
                else:
                    rows = self._service.analyzer_list_batch_review_runs(
                        source=self._source,
                        project_id=self._project_id,
                        batch_id=self._batch_id,
                        stage_mode=self._stage_mode,
                        band_low_hz=self._band_low_hz,
                        band_high_hz=self._band_high_hz,
                        target_h_deg=self._target_h_deg,
                        target_v_deg=self._target_v_deg,
                        tol_deg=self._tol_deg,
                        algo_version=self._algo_version,
                    )
                    payload = {
                        "mode": "runs",
                        "project_id": self._project_id,
                        "batch_id": self._batch_id,
                        "runs": rows,
                    }
                self.finished.emit(self._request_id, payload)
                return

            projects = self._service.analyzer_list_polar_projects(source=self._source, project_id=self._project_id)
            active_project_id = self._project_id
            if not active_project_id and projects:
                active_project_id = str(projects[0].get("project_id") or "").strip() or None

            batches: List[Dict[str, Any]] = []
            runs: List[Dict[str, Any]] = []
            active_batch_id = self._batch_id
            if active_project_id:
                batches = self._service.analyzer_list_polar_batches(
                    source=self._source,
                    project_id=active_project_id,
                )
                batch_ids = [str(item.get("batch_id") or "").strip() for item in batches if str(item.get("batch_id") or "").strip()]
                if not active_batch_id and batch_ids:
                    active_batch_id = batch_ids[0]
                if active_batch_id:
                    runs = self._service.analyzer_list_batch_review_runs(
                        source=self._source,
                        project_id=active_project_id,
                        batch_id=active_batch_id,
                        stage_mode=self._stage_mode,
                        band_low_hz=self._band_low_hz,
                        band_high_hz=self._band_high_hz,
                        target_h_deg=self._target_h_deg,
                        target_v_deg=self._target_v_deg,
                        tol_deg=self._tol_deg,
                        algo_version=self._algo_version,
                    )
            payload = {
                "mode": "overview",
                "source": self._source,
                "project_id": active_project_id,
                "batch_id": active_batch_id,
                "projects": projects,
                "batches": batches,
                "runs": runs,
            }
            self.finished.emit(self._request_id, payload)
        except Exception:  # pragma: no cover - integration surface
            self.failed.emit(self._request_id, traceback.format_exc())


class _AnalyzerKpiComputeWorker(QObject):
    finished = Signal(int, dict)
    failed = Signal(int, str)
    progress = Signal(int, int, str)
    canceled = Signal(int, str)

    def __init__(
        self,
        *,
        service: OrchestratorService,
        request_id: int,
        project_id: str,
        batch_id: str,
        stage_mode: str,
        target_h_deg: float,
        target_v_deg: float,
        tol_deg: float,
        band_low_hz: float,
        band_high_hz: float,
        algo_version: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._request_id = int(request_id)
        self._project_id = str(project_id or "").strip()
        self._batch_id = str(batch_id or "").strip()
        self._stage_mode = str(stage_mode or DEFAULT_STAGE_ID)
        self._target_h_deg = float(target_h_deg)
        self._target_v_deg = float(target_v_deg)
        self._tol_deg = float(tol_deg)
        self._band_low_hz = float(band_low_hz)
        self._band_high_hz = float(band_high_hz)
        self._algo_version = str(algo_version or ALGO_VERSION)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _cancel_check(self) -> bool:
        return bool(self._cancelled)

    def run(self) -> None:
        try:
            result = self._service.analyzer_compute_batch_kpis(
                project_id=self._project_id,
                batch_id=self._batch_id,
                target_h_deg=self._target_h_deg,
                target_v_deg=self._target_v_deg,
                tol_deg=self._tol_deg,
                band_low_hz=self._band_low_hz,
                band_high_hz=self._band_high_hz,
                stage_mode=self._stage_mode,
                algo_version=self._algo_version,
                progress_cb=lambda done, total, message: self.progress.emit(
                    int(done),
                    int(total),
                    str(message or ""),
                ),
                cancel_check=self._cancel_check,
            )
        except Exception:  # pragma: no cover - integration surface
            self.failed.emit(self._request_id, traceback.format_exc())
            return
        if bool(result.get("canceled")):
            self.canceled.emit(self._request_id, "KPI compute canceled.")
            return
        self.finished.emit(self._request_id, dict(result))


class _AnalyzerPlotWorker(QObject):
    finished = Signal(int, dict)
    failed = Signal(int, str)
    canceled = Signal(int, str)

    def __init__(
        self,
        *,
        service: OrchestratorService,
        request_id: int,
        source: str,
        project_id: str,
        batch_id: str,
        run_id: Optional[str],
        version_id: str,
        plane: str,
        stage_mode: str,
        target_h_deg: float,
        target_v_deg: float,
        tol_deg: float,
        band_low_hz: float,
        band_high_hz: float,
        cache: AnalyzerPlotCache,
        use_full_angles_for_smoothness: bool = False,
    ) -> None:
        super().__init__()
        self._service = service
        self._request_id = int(request_id)
        self._source = str(source or "project")
        self._project_id = str(project_id or "").strip()
        self._batch_id = str(batch_id or "").strip()
        self._run_id = str(run_id or "").strip() or None
        self._version_id = str(version_id or "").strip()
        self._plane = str(plane or "H").strip().upper() or "H"
        self._stage_mode = str(stage_mode or DEFAULT_STAGE_ID)
        self._target_h_deg = float(target_h_deg)
        self._target_v_deg = float(target_v_deg)
        self._tol_deg = float(tol_deg)
        self._band_low_hz = float(band_low_hz)
        self._band_high_hz = float(band_high_hz)
        self._cache = cache
        self._use_full_angles_for_smoothness = bool(use_full_angles_for_smoothness)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _cancel_check(self) -> bool:
        return bool(self._cancelled)

    def run(self) -> None:
        if self._cancelled:
            self.canceled.emit(self._request_id, "Plot request canceled.")
            return
        try:
            payload = self._service.analyzer_load_stage_plot_payload(
                source=self._source,
                project_id=self._project_id,
                batch_id=self._batch_id,
                run_id=self._run_id,
                version_id=self._version_id,
                plane=self._plane,
                stage_mode=self._stage_mode,
                target_h_deg=self._target_h_deg,
                target_v_deg=self._target_v_deg,
                tol_deg=self._tol_deg,
                band_low_hz=self._band_low_hz,
                band_high_hz=self._band_high_hz,
                cache=self._cache,
                use_full_angles_for_smoothness=self._use_full_angles_for_smoothness,
                cancel_check=self._cancel_check,
            )
        except Exception as exc:  # pragma: no cover - integration surface
            if self._cancelled or "canceled" in str(exc).lower():
                self.canceled.emit(self._request_id, "Plot request canceled.")
                return
            self.failed.emit(self._request_id, traceback.format_exc())
            return
        if self._cancelled:
            self.canceled.emit(self._request_id, "Plot request canceled.")
            return
        self.finished.emit(self._request_id, dict(payload))


class _AnalyzerAutoPickDialog(StyledDialogBase):
    def __init__(
        self,
        *,
        batch_ids: Sequence[str],
        current_batch_id: Optional[str],
        strategy: str,
        kpi_key: str,
        exclude_flags: bool,
        exclude_missing_kpi: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title="Auto-pick Candidates", parent=parent, min_width=760, min_height=560)
        self._accepted_payload: Optional[Dict[str, Any]] = None
        body = self.body_layout()

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("Current batch", "current")
        self.scope_combo.addItem("Selected batches", "multi")
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem("A - Top N by Score (default)", "A")
        self.strategy_combo.addItem("B - Top N by selected KPI", "B")
        self.strategy_combo.addItem("C - Filter + score tie-break", "C")
        self.kpi_combo = QComboBox()
        self.kpi_combo.addItem("Score", "score")
        self.kpi_combo.addItem("B_PC (higher better)", "b_pc_oct")
        self.kpi_combo.addItem("E_BW (lower better)", "e_bw")
        self.kpi_combo.addItem("E_cov (lower better)", "e_cov")
        self.kpi_combo.addItem("R_spill (lower better)", "r_spill")
        self.kpi_combo.addItem("Flags (lower better)", "flags_count")
        self.top_n_label = QLabel("Top N: 5 (fixed)")
        self.top_n_label.setObjectName("SummaryMeta")

        form.addRow("Scope", self.scope_combo)
        form.addRow("Strategy", self.strategy_combo)
        form.addRow("KPI (for strategy B)", self.kpi_combo)
        form.addRow("Limit", self.top_n_label)
        body.addLayout(form)

        self.batch_list = QListWidget()
        self.batch_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.batch_list.setObjectName("AnalyzerAutopickBatchList")
        for batch_id in sorted({str(item).strip() for item in list(batch_ids or []) if str(item).strip()}):
            item = QListWidgetItem(batch_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            if current_batch_id and str(batch_id) == str(current_batch_id):
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.batch_list.addItem(item)
        body.addWidget(self.batch_list, 1)

        self.exclude_flags_check = QCheckBox("Exclude flagged candidates")
        self.exclude_flags_check.setChecked(bool(exclude_flags))
        self.exclude_missing_check = QCheckBox("Exclude missing KPI rows")
        self.exclude_missing_check.setChecked(bool(exclude_missing_kpi))
        filters_row = QHBoxLayout()
        filters_row.setContentsMargins(0, 0, 0, 0)
        filters_row.setSpacing(8)
        filters_row.addWidget(self.exclude_flags_check)
        filters_row.addWidget(self.exclude_missing_check)
        filters_row.addStretch(1)
        body.addLayout(filters_row)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("BatchSecondaryButton")
        apply_btn = QPushButton("Auto-pick")
        apply_btn.setObjectName("BatchPrimaryButton")
        cancel_btn.clicked.connect(self.reject)
        apply_btn.clicked.connect(self._accept_payload)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(apply_btn)
        body.addLayout(buttons)

        self._set_combo_current_by_data(self.strategy_combo, strategy)
        self._set_combo_current_by_data(self.kpi_combo, kpi_key)
        self.scope_combo.currentIndexChanged.connect(self._sync_controls)
        self.strategy_combo.currentIndexChanged.connect(self._sync_controls)
        self._sync_controls()

    @staticmethod
    def _set_combo_current_by_data(combo: QComboBox, value: str) -> None:
        token = str(value or "").strip().lower()
        for index in range(combo.count()):
            if str(combo.itemData(index) or "").strip().lower() == token:
                combo.setCurrentIndex(index)
                return

    def _sync_controls(self) -> None:
        scope = str(self.scope_combo.currentData() or "current")
        strategy = str(self.strategy_combo.currentData() or "A")
        self.batch_list.setVisible(scope == "multi")
        self.kpi_combo.setEnabled(strategy == "B")

    def _selected_batches(self) -> List[str]:
        scope = str(self.scope_combo.currentData() or "current")
        if scope != "multi":
            return []
        selected: List[str] = []
        for index in range(self.batch_list.count()):
            item = self.batch_list.item(index)
            if item is None:
                continue
            if item.checkState() == Qt.Checked:
                token = str(item.text() or "").strip()
                if token:
                    selected.append(token)
        return selected

    def _accept_payload(self) -> None:
        self._accepted_payload = {
            "scope": str(self.scope_combo.currentData() or "current"),
            "batch_ids": self._selected_batches(),
            "strategy": str(self.strategy_combo.currentData() or "A"),
            "kpi_key": str(self.kpi_combo.currentData() or "score"),
            "filters": {
                "exclude_flags": bool(self.exclude_flags_check.isChecked()),
                "exclude_missing_kpi": bool(self.exclude_missing_check.isChecked()),
            },
            "top_n": 5,
        }
        self.accept()

    def payload(self) -> Optional[Dict[str, Any]]:
        return dict(self._accepted_payload) if isinstance(self._accepted_payload, dict) else None


class _AnalyzerRunDetailsDialog(StyledDialogBase):
    def __init__(
        self,
        *,
        payload: Dict[str, Any],
        ath_param_rows: Optional[Sequence[Dict[str, Any]]] = None,
        visible_ath_keys: Optional[Sequence[str]] = None,
        on_toggle_ath_param: Optional[Callable[[str, bool], Any]] = None,
        max_visible_ath_params: int = 5,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title="Run Details", parent=parent, min_width=880, min_height=620)
        data = dict(payload or {})
        body = self.body_layout()

        tabs = QTabWidget()

        summary_tab = QWidget()
        summary_layout = QVBoxLayout(summary_tab)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        norm_raw = data.get("norm_angle_deg")
        if norm_raw is None:
            norm_text = "--"
        else:
            try:
                norm_text = f"{float(norm_raw):.2f}"
            except Exception:
                norm_text = str(norm_raw)
        reason_items = [dict(item) for item in list(data.get("kpi_reason_items", []) or []) if isinstance(item, dict)]
        if not reason_items:
            reason_items = reason_items_for_codes(
                [str(code) for code in list(data.get("kpi_reason_codes", []) or []) if str(code).strip()]
            )
        reason_lines: List[str] = []
        for item in reason_items:
            severity = str(item.get("severity") or "warn").upper()
            code = str(item.get("code") or "").strip()
            summary = str(item.get("summary") or "").strip()
            action = str(item.get("action") or "").strip()
            line = f"[{severity}] {code}" if code else f"[{severity}]"
            if summary:
                line = f"{line}: {summary}"
            if action:
                line = f"{line} | Action: {action}"
            reason_lines.append(line)
        rows = [
            ("Run ID", str(data.get("run_id") or data.get("run_label") or "--"), True),
            ("Version", str(data.get("version_id") or "--"), True),
            ("Project", str(data.get("project_id") or "--"), False),
            ("Batch", str(data.get("batch_id") or "--"), False),
            ("Planes", "/".join(str(item) for item in list(data.get("planes", []) or [])) or "--", False),
            ("freq_count", str(data.get("freq_count") if data.get("freq_count") is not None else "--"), False),
            ("angle_count", str(data.get("angle_count") if data.get("angle_count") is not None else "--"), False),
            ("norm_angle_deg", norm_text, False),
            ("norm_angle_source", str(data.get("norm_angle_source") or "--"), False),
            ("norm_angle_note", str(data.get("norm_angle_note") or "--"), False),
            ("score", str(data.get("kpi_score") if data.get("kpi_score") is not None else "--"), False),
            ("B_PC", str(data.get("kpi_b_pc_oct") if data.get("kpi_b_pc_oct") is not None else "--"), False),
            ("E_BW", str(data.get("kpi_e_bw") if data.get("kpi_e_bw") is not None else "--"), False),
            ("E_cov", str(data.get("kpi_e_cov") if data.get("kpi_e_cov") is not None else "--"), False),
            ("R_spill", str(data.get("kpi_r_spill") if data.get("kpi_r_spill") is not None else "--"), False),
            ("Flags", str(data.get("kpi_flags_count") if data.get("kpi_flags_count") is not None else "--"), False),
            (
                "KPI reason_codes",
                "\n".join(reason_lines) if reason_lines else "--",
                False,
            ),
            ("imported_at", str(data.get("imported_at") or "--"), False),
            ("created_at", str(data.get("created_at") or "--"), False),
        ]
        for label_text, value_text, copyable in rows:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            value_label = QLabel(str(value_text))
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row_layout.addWidget(value_label, 1)
            if copyable and str(value_text).strip() and str(value_text).strip() != "--":
                copy_btn = QPushButton("Copy")
                copy_btn.setObjectName("BatchSecondaryButton")
                copy_btn.clicked.connect(lambda _checked=False, text=str(value_text): QApplication.clipboard().setText(text))
                row_layout.addWidget(copy_btn, 0)
            form.addRow(label_text, row_widget)
        summary_layout.addLayout(form)
        summary_layout.addStretch(1)
        tabs.addTab(summary_tab, "Summary")

        ath_tab = QWidget()
        ath_layout = QVBoxLayout(ath_tab)
        ath_layout.setContentsMargins(0, 0, 0, 0)
        ath_layout.setSpacing(6)
        ath_hint = QLabel("Choose ATH parameters to display in Version Information column 2.")
        ath_hint.setObjectName("SummaryMeta")
        ath_hint.setWordWrap(True)
        ath_layout.addWidget(ath_hint, 0, Qt.AlignLeft | Qt.AlignVCenter)
        ath_limit_hint = QLabel("")
        ath_limit_hint.setObjectName("SummaryMeta")
        ath_limit_hint.setProperty("analyzerAthLimitHint", True)
        ath_limit_hint.setWordWrap(False)
        ath_limit_hint.setVisible(False)
        ath_layout.addWidget(ath_limit_hint, 0, Qt.AlignLeft | Qt.AlignVCenter)

        ath_table = QTableWidget(0, 4)
        ath_table.setObjectName("AnalyzerAthParamsTable")
        ath_table.setHorizontalHeaderLabels(["Group", "Parameter", "Value", "Visible"])
        ath_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ath_table.setSelectionMode(QAbstractItemView.NoSelection)
        ath_header = ath_table.horizontalHeader()
        ath_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        ath_header.setSectionResizeMode(1, QHeaderView.Stretch)
        ath_header.setSectionResizeMode(2, QHeaderView.Stretch)
        ath_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        ath_table.verticalHeader().setVisible(False)

        def _ath_group_for_key(param_key: str) -> str:
            key = str(param_key or "").strip()
            if key.startswith("Throat.") or key.startswith("OSSE") or key.startswith("R-OSSE"):
                return "Throat"
            if key.startswith("Morph."):
                return "Morph"
            if key.startswith("GCurve."):
                return "GCurve"
            if key.startswith("Mesh."):
                return "Mesh"
            if key.startswith("Term."):
                return "Term"
            return "Other"

        limit = max(1, int(max_visible_ath_params or 5))
        visible_ordered: List[str] = []
        seen_visible: set[str] = set()
        for raw in list(visible_ath_keys or []):
            key = str(raw or "").strip()
            if not key or key in seen_visible:
                continue
            seen_visible.add(key)
            visible_ordered.append(key)
        clamped_on_open = len(visible_ordered) > limit
        if clamped_on_open:
            visible_ordered = visible_ordered[:limit]
        selected_visible: set[str] = set(visible_ordered)
        if clamped_on_open:
            ath_limit_hint.setText(f"Max {limit} parameters. Loaded first {limit}.")
            ath_limit_hint.setVisible(True)
        normalized_rows = [dict(item) for item in list(ath_param_rows or []) if isinstance(item, dict)]
        normalized_rows.sort(key=lambda item: (_ath_group_for_key(str(item.get("param_name") or "")), str(item.get("param_name") or "")))

        for row in normalized_rows:
            param_name = str(row.get("param_name") or "").strip()
            if not param_name:
                continue
            value = row.get("value")
            row_index = ath_table.rowCount()
            ath_table.insertRow(row_index)
            ath_table.setItem(row_index, 0, QTableWidgetItem(_ath_group_for_key(param_name)))
            ath_table.setItem(row_index, 1, QTableWidgetItem(param_name))
            ath_table.setItem(row_index, 2, QTableWidgetItem(AnalysePage._format_param_value(value)))
            visible_check = QCheckBox()
            visible_check.setChecked(param_name in selected_visible)
            if callable(on_toggle_ath_param):
                def _handle_visible_toggle(checked: bool, *, key: str = param_name, control: QCheckBox = visible_check) -> None:
                    token = str(key or "").strip()
                    if not token:
                        return
                    if checked:
                        if token in selected_visible:
                            return
                        if len(selected_visible) >= limit:
                            control.blockSignals(True)
                            control.setChecked(False)
                            control.blockSignals(False)
                            ath_limit_hint.setText(f"Max {limit} parameters.")
                            ath_limit_hint.setVisible(True)
                            return
                        selected_visible.add(token)
                    else:
                        selected_visible.discard(token)
                    on_toggle_ath_param(str(token), bool(checked))

                visible_check.toggled.connect(_handle_visible_toggle)
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(0)
            cell_layout.addWidget(visible_check, 0, Qt.AlignCenter)
            ath_table.setCellWidget(row_index, 3, cell)
        if ath_table.rowCount() <= 0:
            ath_table.setRowCount(1)
            ath_table.setItem(0, 0, QTableWidgetItem("--"))
            ath_table.setItem(0, 1, QTableWidgetItem("No ATH parameters available."))
            ath_table.setItem(0, 2, QTableWidgetItem("--"))
            ath_table.setItem(0, 3, QTableWidgetItem("--"))
        ath_layout.addWidget(ath_table, 1)
        tabs.addTab(ath_tab, "ATH Params")

        files_tab = QWidget()
        files_layout = QVBoxLayout(files_tab)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.setSpacing(6)
        files_list = QTextEdit()
        files_list.setReadOnly(True)
        source_files = [str(item) for item in list(data.get("source_files", []) or [])]
        file_hashes = [str(item) for item in list(data.get("file_hashes", []) or [])]
        text_lines = ["Source files:"]
        text_lines.extend(source_files or ["--"])
        text_lines.append("")
        text_lines.append("File hashes:")
        text_lines.extend(file_hashes or ["--"])
        files_list.setPlainText("\n".join(text_lines))
        files_actions = QHBoxLayout()
        files_actions.setContentsMargins(0, 0, 0, 0)
        files_actions.addStretch(1)
        copy_files_btn = QPushButton("Copy files")
        copy_files_btn.setObjectName("BatchSecondaryButton")
        copy_files_btn.clicked.connect(lambda _checked=False: QApplication.clipboard().setText("\n".join(source_files)))
        copy_hashes_btn = QPushButton("Copy hashes")
        copy_hashes_btn.setObjectName("BatchSecondaryButton")
        copy_hashes_btn.clicked.connect(lambda _checked=False: QApplication.clipboard().setText("\n".join(file_hashes)))
        files_actions.addWidget(copy_files_btn)
        files_actions.addWidget(copy_hashes_btn)
        files_layout.addLayout(files_actions)
        files_layout.addWidget(files_list, 1)
        tabs.addTab(files_tab, "Files")

        raw_tab = QWidget()
        raw_layout = QVBoxLayout(raw_tab)
        raw_layout.setContentsMargins(0, 0, 0, 0)
        raw_layout.setSpacing(6)
        raw_text = QTextEdit()
        raw_text.setReadOnly(True)
        raw_text.setPlainText(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
        raw_layout.addWidget(raw_text, 1)
        tabs.addTab(raw_tab, "Raw")

        body.addWidget(tabs, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("BatchSecondaryButton")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        body.addLayout(actions)


class _AnalyzerVersionPickerDialog(QDialog):
    def __init__(
        self,
        *,
        entries: Sequence[Dict[str, Any]],
        current_identity: tuple[str, str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("AnalyzerVersionPickerDialog")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumWidth(420)
        self.setMinimumHeight(280)
        self._selected_payload: Dict[str, Any] = {}
        self._entries = [dict(item) for item in list(entries or []) if isinstance(item, dict)]
        self._current_identity = tuple(str(item or "").strip() for item in current_identity)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        title = QLabel("Versions")
        title.setObjectName("SectionTitle")
        root.addWidget(title, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.search = QLineEdit()
        self.search.setObjectName("AnalyzerVersionSearch")
        self.search.setPlaceholderText("Filter versions (Batch/Version, planes, score)...")
        root.addWidget(self.search, 0)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("AnalyzerVersionList")
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        root.addWidget(self.list_widget, 1)

        self.search.textChanged.connect(self._apply_filter)
        self.list_widget.itemActivated.connect(self._accept_item)
        self.search.returnPressed.connect(self._accept_current)
        self._apply_filter("")
        self.search.setFocus(Qt.PopupFocusReason)

    def _identity(self, payload: Dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(payload.get("batch_id") or "").strip(),
            str(payload.get("run_id") or "").strip(),
            str(payload.get("version_id") or "").strip(),
        )

    def _apply_filter(self, text: str) -> None:
        token = str(text or "").strip().lower()
        self.list_widget.clear()
        selected_row = -1
        for idx, row in enumerate(self._entries):
            label = str(row.get("label") or "").strip()
            if token and token not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, dict(row.get("payload") or {}))
            item.setToolTip(label)
            self.list_widget.addItem(item)
            payload = dict(row.get("payload") or {})
            if self._identity(payload) == self._current_identity:
                selected_row = self.list_widget.count() - 1
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(max(selected_row, 0))

    def _accept_item(self, item: QListWidgetItem) -> None:
        payload = dict(item.data(Qt.UserRole) or {})
        self._selected_payload = payload
        self.accept()

    def _accept_current(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            self.reject()
            return
        self._accept_item(item)

    def selected_payload(self) -> Dict[str, Any]:
        return dict(self._selected_payload)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            self._accept_current()
            event.accept()
            return
        super().keyPressEvent(event)


class _AnalyzerKpiPopoverDialog(QDialog):
    def __init__(self, *, payload: Dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("AnalyzerKpiPopoverDialog")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumWidth(300)
        self.setMinimumHeight(220)

        data = dict(payload or {})
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        title = QLabel("KPIs")
        title.setObjectName("SectionTitle")
        root.addWidget(title, 0, Qt.AlignLeft | Qt.AlignVCenter)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)
        rows = [
            ("Score", data.get("kpi_score"), "{:.2f}"),
            ("Pattern Control (oct)", data.get("kpi_b_pc_oct"), "{:.2f}"),
            ("Beamwidth Error (deg)", data.get("kpi_e_bw"), "{:.2f}"),
            ("Coverage Error (dB)", data.get("kpi_e_cov"), "{:.2f}"),
            ("Spill Ratio", data.get("kpi_r_spill"), "{:.3f}"),
            ("Flags", data.get("kpi_flags_count"), "{:.0f}"),
        ]
        for label_text, raw, fmt in rows:
            if raw is None:
                value_text = "--"
            else:
                try:
                    value_text = fmt.format(float(raw))
                except Exception:
                    value_text = str(raw)
            value = QLabel(value_text)
            value.setObjectName("SummaryMeta")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(label_text, value)
        root.addLayout(form)

class _AnalyzerFlagsHelpDialog(StyledDialogBase):
    def __init__(self, *, reason_items: Sequence[Dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(title="Flags Help", parent=parent, min_width=760, min_height=420)
        body = self.body_layout()
        intro = QLabel("Reason codes explain data limitations and what to do next.")
        intro.setObjectName("SummaryMeta")
        intro.setWordWrap(True)
        body.addWidget(intro, 0)

        items = [dict(item) for item in list(reason_items or []) if isinstance(item, dict)]
        if not items:
            empty = QLabel("No WARN/ERROR reason codes for the current selection.")
            empty.setObjectName("SummaryMeta")
            empty.setWordWrap(True)
            body.addWidget(empty, 1)
        else:
            table = QTableWidget(len(items), 4)
            table.setObjectName("AnalyzerFlagsHelpTable")
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.NoSelection)
            table.setHorizontalHeaderLabels(["Code", "Severity", "Meaning", "Suggested action"])
            table.verticalHeader().setVisible(False)
            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.Stretch)
            header.setSectionResizeMode(3, QHeaderView.Stretch)
            for row_index, row in enumerate(items):
                code = str(row.get("code") or "--")
                severity = str(row.get("severity") or "warn").upper()
                summary = str(row.get("summary") or "--")
                action = str(row.get("action") or "--")
                table.setItem(row_index, 0, QTableWidgetItem(code))
                table.setItem(row_index, 1, QTableWidgetItem(severity))
                table.setItem(row_index, 2, QTableWidgetItem(summary))
                table.setItem(row_index, 3, QTableWidgetItem(action))
            body.addWidget(table, 1)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("BatchSecondaryButton")
        close_btn.clicked.connect(self.accept)
        controls.addWidget(close_btn, 0)
        body.addLayout(controls)


class _AnalyzerAutoPickWorker(QObject):
    finished = Signal(int, dict)
    failed = Signal(int, str)
    progress = Signal(int, int, str)
    canceled = Signal(int, str)

    def __init__(
        self,
        *,
        service: OrchestratorService,
        request_id: int,
        project_id: str,
        batch_ids: Sequence[str],
        strategy: str,
        kpi_key: str,
        filters: Dict[str, Any],
        top_n: int,
        stage_mode: str,
        band_low_hz: float,
        band_high_hz: float,
        target_h_deg: float,
        target_v_deg: float,
        tol_deg: float,
        algo_version: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._request_id = int(request_id)
        self._project_id = str(project_id or "").strip()
        self._batch_ids = [str(item or "").strip() for item in list(batch_ids or []) if str(item or "").strip()]
        self._strategy = str(strategy or "A")
        self._kpi_key = str(kpi_key or "score")
        self._filters = dict(filters or {})
        self._top_n = max(1, min(int(top_n), 5))
        self._stage_mode = str(stage_mode or DEFAULT_STAGE_ID)
        self._band_low_hz = float(band_low_hz)
        self._band_high_hz = float(band_high_hz)
        self._target_h_deg = float(target_h_deg)
        self._target_v_deg = float(target_v_deg)
        self._tol_deg = float(tol_deg)
        self._algo_version = str(algo_version or ALGO_VERSION)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _cancel_check(self) -> bool:
        return bool(self._cancelled)

    def run(self) -> None:
        try:
            payload = self._service.analyzer_autopick_candidates(
                project_id=self._project_id,
                batch_ids=self._batch_ids,
                strategy=self._strategy,
                kpi_key=self._kpi_key,
                filters=self._filters,
                top_n=self._top_n,
                stage_mode=self._stage_mode,
                band_low_hz=self._band_low_hz,
                band_high_hz=self._band_high_hz,
                target_h_deg=self._target_h_deg,
                target_v_deg=self._target_v_deg,
                tol_deg=self._tol_deg,
                algo_version=self._algo_version,
                progress_cb=lambda done, total, message: self.progress.emit(int(done), int(total), str(message or "")),
                cancel_check=self._cancel_check,
            )
        except Exception:  # pragma: no cover - integration surface
            self.failed.emit(self._request_id, traceback.format_exc())
            return
        if bool(payload.get("canceled")):
            self.canceled.emit(self._request_id, "Auto-pick canceled.")
            return
        self.finished.emit(self._request_id, dict(payload))


class _AnalyzerComparePlotWorker(QObject):
    finished = Signal(int, dict)
    failed = Signal(int, str)
    progress = Signal(int, int, str)
    canceled = Signal(int, str)

    def __init__(
        self,
        *,
        service: OrchestratorService,
        request_id: int,
        source: str,
        project_id: str,
        candidates: Sequence[Dict[str, Any]],
        plane: str,
        stage_mode: str,
        target_h_deg: float,
        target_v_deg: float,
        tol_deg: float,
        band_low_hz: float,
        band_high_hz: float,
        cache: AnalyzerPlotCache,
        use_full_angles_for_smoothness: bool = False,
    ) -> None:
        super().__init__()
        self._service = service
        self._request_id = int(request_id)
        self._source = str(source or "project")
        self._project_id = str(project_id or "").strip()
        self._candidates = [dict(item) for item in list(candidates or []) if isinstance(item, dict)]
        self._plane = str(plane or "H").strip().upper() or "H"
        self._stage_mode = str(stage_mode or DEFAULT_STAGE_ID)
        self._target_h_deg = float(target_h_deg)
        self._target_v_deg = float(target_v_deg)
        self._tol_deg = float(tol_deg)
        self._band_low_hz = float(band_low_hz)
        self._band_high_hz = float(band_high_hz)
        self._cache = cache
        self._use_full_angles_for_smoothness = bool(use_full_angles_for_smoothness)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _cancel_check(self) -> bool:
        return bool(self._cancelled)

    def run(self) -> None:
        results: List[Dict[str, Any]] = []
        total = len(self._candidates)
        if callable(self._cancel_check) and self._cancel_check():
            self.canceled.emit(self._request_id, "Compare plot load canceled.")
            return
        for index, candidate in enumerate(self._candidates, start=1):
            if self._cancel_check():
                self.canceled.emit(self._request_id, "Compare plot load canceled.")
                return
            batch_id = str(candidate.get("batch_id") or "").strip()
            version_id = str(candidate.get("version_id") or "").strip()
            run_id = str(candidate.get("run_id") or "").strip() or None
            if not batch_id or not version_id:
                results.append({"candidate": dict(candidate), "plot": {"message": "Missing candidate identity."}})
                continue
            try:
                payload = self._service.analyzer_load_stage_plot_payload(
                    source=self._source,
                    project_id=self._project_id,
                    batch_id=batch_id,
                    run_id=run_id,
                    version_id=version_id,
                    plane=self._plane,
                    stage_mode=self._stage_mode,
                    target_h_deg=self._target_h_deg,
                    target_v_deg=self._target_v_deg,
                    tol_deg=self._tol_deg,
                    band_low_hz=self._band_low_hz,
                    band_high_hz=self._band_high_hz,
                    cache=self._cache,
                    use_full_angles_for_smoothness=self._use_full_angles_for_smoothness,
                    cancel_check=self._cancel_check,
                )
            except Exception:
                payload = {"message": "Failed to load candidate plot."}
            results.append({"candidate": dict(candidate), "plot": dict(payload)})
            self.progress.emit(index, total, f"Loaded {batch_id}/{version_id}")
        self.finished.emit(self._request_id, {"items": results, "plane": self._plane})


def _severity_rank(value: str) -> int:
    order = {"fatal": 0, "warn": 1, "info": 2}
    return order.get(str(value).lower(), 99)


def _highest_issue_severity(issues: List[Dict[str, Any]]) -> str:
    if not issues:
        return ""
    ranked = sorted((str(item.get("severity", "info")).lower() for item in issues), key=_severity_rank)
    return ranked[0] if ranked else ""


def _status_entries(detail: str) -> List[Dict[str, str]]:
    def _humanize_rule_id(value: str) -> str:
        token = str(value or "").strip()
        if not token:
            return "Issue"
        return token.replace("_", " ").replace(".", " ").strip().title()

    raw = str(detail or "").strip()
    if not raw:
        return [{"severity": "info", "title": "Status", "text": "No details available."}]

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [{"severity": "info", "title": "Status", "text": raw}]

    entries: List[Dict[str, str]] = []
    if isinstance(payload, dict):
        overall = str(payload.get("overall_status", "")).strip().lower()
        if overall:
            overall_map = {"ok": "ok", "warn": "warn", "fail": "fatal"}
            entries.append(
                {
                    "severity": overall_map.get(overall, "info"),
                    "title": "Doctor Overall",
                    "text": f"Overall status: {overall.upper()}",
                }
            )
        checks = payload.get("checks")
        if isinstance(checks, list):
            for item in checks:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status", "")).strip().lower()
                severity_map = {"ok": "ok", "warn": "warn", "fail": "fatal"}
                entries.append(
                    {
                        "severity": severity_map.get(status, "info"),
                        "title": str(item.get("label", "Check")).strip() or "Check",
                        "text": str(item.get("detail", "")).strip() or "No detail.",
                    }
                )
        issues = payload.get("issues")
        if isinstance(issues, list):
            for item in issues:
                if not isinstance(item, dict):
                    continue
                entries.append(
                    {
                        "severity": str(item.get("severity", "info")).strip().lower(),
                        "title": _humanize_rule_id(str(item.get("rule_id", "Issue"))),
                        "text": str(item.get("message", "")).strip() or "No detail.",
                    }
                )
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                entries.append(
                    {
                        "severity": str(item.get("severity", "info")).strip().lower(),
                        "title": _humanize_rule_id(str(item.get("rule_id", "Issue"))),
                        "text": str(item.get("message", "")).strip() or str(item),
                    }
                )
            else:
                entries.append({"severity": "info", "title": "Status", "text": str(item)})

    if not entries:
        entries.append({"severity": "info", "title": "Status", "text": raw})
    return entries


def _win32_force_foreground(window: QWidget) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = int(window.winId())
        SW_MAXIMIZE = 3
        SW_SHOWNORMAL = 1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        is_maximized = bool(window.windowState() & Qt.WindowMaximized)
        user32.ShowWindow(hwnd, SW_MAXIMIZE if is_maximized else SW_SHOWNORMAL)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        return


def _ensure_maximized_foreground(window: QWidget) -> None:
    if window is None:
        return
    state = window.windowState()
    state = (state | Qt.WindowMaximized) & ~Qt.WindowFullScreen & ~Qt.WindowMinimized
    window.setWindowState(state)
    window.showMaximized()
    window.raise_()
    window.activateWindow()
    _win32_force_foreground(window)


def _ensure_normal_foreground(window: QWidget) -> None:
    if window is None:
        return
    state = window.windowState()
    state = state & ~Qt.WindowFullScreen & ~Qt.WindowMinimized & ~Qt.WindowMaximized
    window.setWindowState(state)
    window.showNormal()
    window.raise_()
    window.activateWindow()
    _win32_force_foreground(window)


def _ensure_fullscreen_foreground(window: QWidget) -> None:
    if window is None:
        return
    state = window.windowState()
    state = (state | Qt.WindowFullScreen) & ~Qt.WindowMinimized
    window.setWindowState(state)
    window.showFullScreen()
    window.raise_()
    window.activateWindow()
    _win32_force_foreground(window)


def _center_window(window: QWidget) -> None:
    app = QApplication.instance()
    if app is None:
        return
    screen = window.screen() or app.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    frame = window.frameGeometry()
    frame.moveCenter(area.center())
    window.move(frame.topLeft())


class CompatibilityPanel(QGroupBox):
    request_show_details = Signal()

    def __init__(self, title: str = "Compatibility") -> None:
        super().__init__(title)
        root = QVBoxLayout(self)

        counts = QHBoxLayout()
        self.visible_count = QLabel("Visible fields: 0")
        self.locked_count = QLabel("Locked fields: 0")
        self.sweepable_count = QLabel("Sweepable fields: 0")
        counts.addWidget(self.visible_count)
        counts.addWidget(self.locked_count)
        counts.addWidget(self.sweepable_count)
        counts.addStretch(1)
        root.addLayout(counts)

        lists = QHBoxLayout()
        self.visible_list = QListWidget()
        self.visible_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.locked_list = QListWidget()
        self.locked_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.locked_list.setEnabled(False)
        self.locked_list.setToolTip("Locked by runner mode")
        lists.addWidget(self._wrap_list("Visible", self.visible_list), 2)
        lists.addWidget(self._wrap_list("Locked by runner mode", self.locked_list), 1)
        root.addLayout(lists)

        self.summary = QLabel("No issues.")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("IssueHint")
        root.addWidget(self.summary)

        self.show_details_btn = QPushButton("Show details")
        self.show_details_btn.clicked.connect(self.request_show_details.emit)
        root.addWidget(self.show_details_btn, alignment=Qt.AlignLeft)

        self._issues: List[Dict[str, Any]] = []
        self._update_lists([], [], [])

    def _wrap_list(self, label: str, widget: QListWidget) -> QWidget:
        box = QGroupBox(label)
        layout = QVBoxLayout(box)
        layout.addWidget(widget)
        return box

    def _update_lists(self, visible: List[str], locked: List[str], sweepable: List[str]) -> None:
        self.visible_list.clear()
        self.locked_list.clear()
        for key in visible:
            self.visible_list.addItem(QListWidgetItem(key))
        for key in locked:
            item = QListWidgetItem(key)
            item.setToolTip("Locked by runner mode")
            self.locked_list.addItem(item)
        self.visible_count.setText(f"Visible fields: {len(visible)}")
        self.locked_count.setText(f"Locked fields: {len(locked)}")
        self.sweepable_count.setText(f"Sweepable fields: {len(sweepable)}")

    def update_state(self, state: Dict[str, Any]) -> None:
        visible = sorted(str(item) for item in list(state.get("visible_keys", []) or []))
        locked = sorted(str(item) for item in list(state.get("locked_keys", []) or []))
        sweepable = sorted(str(item) for item in list(state.get("sweepable_keys", []) or []))
        issues = [item for item in list(state.get("issues", []) or []) if isinstance(item, dict)]
        self._issues = issues
        self._update_lists(visible, locked, sweepable)

        top = issues[:5]
        if not top:
            self.summary.setText("No validation issues.")
            self.summary.setProperty("severity", "")
            self.show_details_btn.setEnabled(False)
        else:
            lines = []
            for issue in top:
                severity = str(issue.get("severity", "info")).upper()
                rule_id = str(issue.get("rule_id", "unknown_rule"))
                evidence_type = str(issue.get("evidence_type", "hypothesis"))
                message = str(issue.get("message", ""))
                lines.append(f"[{severity}] {rule_id} ({evidence_type}) - {message}")
            self.summary.setText("\n".join(lines))
            self.summary.setProperty("severity", _highest_issue_severity(issues))
            self.show_details_btn.setEnabled(True)
        self.style().unpolish(self.summary)
        self.style().polish(self.summary)

    def issues(self) -> List[Dict[str, Any]]:
        return list(self._issues)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About WUT Batcher")
        self.setModal(True)
        self.resize(360, 220)

        layout = QVBoxLayout(self)
        logo = QLabel("[ LOGO ]")
        logo.setAlignment(Qt.AlignCenter)
        logo.setObjectName("SectionTitle")
        layout.addWidget(logo)

        version = QLabel("Version: 0.1-rebuild")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        author = QLabel("Entwickelt von Maximilian Heinze")
        author.setAlignment(Qt.AlignCenter)
        layout.addWidget(author)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class StatusDetailDialog(QDialog):
    def __init__(self, detail_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setWindowTitle("Status")
        self.resize(760, 520)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setProperty("framelessShell", True)
        self._drag_offset: Optional[QPoint] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)
        shell = QFrame()
        shell.setObjectName("FramelessShell")
        outer.addWidget(shell)
        root = QVBoxLayout(shell)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        title_bar = QWidget()
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        icon = QLabel("●")
        icon.setObjectName("StatusSymbol")
        title_row.addWidget(icon)
        title = QLabel("Status Details")
        title.setObjectName("SectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        close_btn = QPushButton("X")
        close_btn.setObjectName("WindowCloseButton")
        close_btn.setFixedSize(28, 24)
        close_btn.clicked.connect(self.accept)
        title_row.addWidget(close_btn, alignment=Qt.AlignRight)
        root.addWidget(title_bar)
        title_bar.mousePressEvent = self._title_mouse_press  # type: ignore[assignment]
        title_bar.mouseMoveEvent = self._title_mouse_move  # type: ignore[assignment]
        title_bar.mouseReleaseEvent = self._title_mouse_release  # type: ignore[assignment]

        scroll = QListWidget()
        scroll.setSelectionMode(QAbstractItemView.NoSelection)
        entries = _status_entries(detail_text)
        for entry in entries:
            sev = str(entry.get("severity", "info")).lower()
            title_text = str(entry.get("title", "Status"))
            body_text = str(entry.get("text", ""))
            item = QListWidgetItem()
            row_widget = QWidget()
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(4)

            title_label = QLabel(title_text)
            title_label.setObjectName("SectionTitle")
            body_label = QLabel(body_text)
            body_label.setWordWrap(True)
            body_label.setObjectName("IssueHint")
            body_label.setProperty("severity", sev if sev in {"fatal", "warn", "ok"} else "")
            row_layout.addWidget(title_label)
            row_layout.addWidget(body_label)

            item.setSizeHint(row_widget.sizeHint())
            scroll.addItem(item)
            scroll.setItemWidget(item, row_widget)
        root.addWidget(scroll, 1)

    def _title_mouse_press(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            return
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def _title_mouse_move(self, event) -> None:  # type: ignore[override]
        if self._drag_offset is None:
            return
        if not (event.buttons() & Qt.LeftButton):
            return
        self.move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    def _title_mouse_release(self, event) -> None:  # type: ignore[override]
        self._drag_offset = None
        event.accept()


class BatchRunDefaultsDialog(QDialog):
    def __init__(
        self,
        *,
        missing_keys: List[str],
        default_values: Dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setProperty("framelessShell", True)
        self.setModal(True)
        self.setMinimumSize(560, 360)
        self.resize(620, 420)
        self._drag_offset: Optional[QPoint] = None
        self._decision = "cancel"
        self._missing_keys = [str(item) for item in list(missing_keys or []) if str(item).strip()]
        self._default_values = dict(default_values or {})

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)
        shell = QFrame()
        shell.setObjectName("FramelessShell")
        outer.addWidget(shell)
        root = QVBoxLayout(shell)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        title_bar = QWidget()
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title = QLabel("Undefined Parameters For Run")
        title.setObjectName("SectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        close_btn = QPushButton("X")
        close_btn.setObjectName("WindowCloseButton")
        close_btn.setFixedSize(28, 24)
        close_btn.clicked.connect(self.reject)
        title_row.addWidget(close_btn, alignment=Qt.AlignRight)
        root.addWidget(title_bar)
        title_bar.mousePressEvent = self._title_mouse_press  # type: ignore[assignment]
        title_bar.mouseMoveEvent = self._title_mouse_move  # type: ignore[assignment]
        title_bar.mouseReleaseEvent = self._title_mouse_release  # type: ignore[assignment]

        text = QLabel(
            "The current configuration contains undefined policy-minimal parameters.\n"
            "Do you want to inspect them or use defaults for this run?"
        )
        text.setWordWrap(True)
        text.setObjectName("SummaryText")
        root.addWidget(text)

        list_box = QListWidget()
        list_box.setSelectionMode(QAbstractItemView.NoSelection)
        for key in self._missing_keys[:18]:
            hint = self._default_hint_for_key(key)
            label = f"{key}  ->  {hint}" if hint else key
            list_box.addItem(label)
        if len(self._missing_keys) > 18:
            list_box.addItem(f"... +{len(self._missing_keys) - 18} more")
        root.addWidget(list_box, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        show_btn = QPushButton("Show undefined")
        show_btn.setProperty("segment", "true")
        show_btn.setFixedHeight(32)
        defaults_btn = QPushButton("Use defaults")
        defaults_btn.setObjectName("PrimaryButton")
        defaults_btn.setFixedHeight(32)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(32)
        show_btn.clicked.connect(self._accept_show)
        defaults_btn.clicked.connect(self._accept_defaults)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(show_btn)
        buttons.addWidget(defaults_btn)
        root.addLayout(buttons)

    def _default_hint_for_key(self, key: str) -> str:
        token = str(key or "").strip()
        if not token:
            return ""
        if token.startswith("R-OSSE."):
            obj = dict(self._default_values.get("R-OSSE", {}) or {})
            return str(obj.get(token.split(".", 1)[1], ""))
        value = self._default_values.get(token)
        if value is None:
            return ""
        if isinstance(value, Mapping):
            return "{...}"
        return str(value)

    def _accept_show(self) -> None:
        self._decision = "show"
        self.accept()

    def _accept_defaults(self) -> None:
        self._decision = "use_defaults"
        self.accept()

    def decision(self) -> str:
        return str(self._decision or "cancel")

    def _title_mouse_press(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            return
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def _title_mouse_move(self, event) -> None:  # type: ignore[override]
        if self._drag_offset is None:
            return
        if not (event.buttons() & Qt.LeftButton):
            return
        self.move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    def _title_mouse_release(self, event) -> None:  # type: ignore[override]
        self._drag_offset = None
        event.accept()


class SettingsDialog(QDialog):
    settings_saved = Signal(dict)

    def __init__(self, service: OrchestratorService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(620, 390)

        self.library_root = QLineEdit()
        self.ath_exe = QLineEdit()
        self.akabak_exe = QLineEdit()
        self.vacs_exe = QLineEdit()
        self.template_cfg = QLineEdit()
        self.background_automation_mode = QCheckBox("Enable Background Automation Mode")
        self.background_automation_mode.setToolTip(
            "When enabled, the RUN screen stays in front while AKABAK/VACS automation runs in the background."
        )
        self.simulation_timeout_minutes = QSpinBox()
        self.simulation_timeout_minutes.setObjectName("SimulationTimeoutMinutesSpin")
        self.simulation_timeout_minutes.setRange(SIMULATION_TIMEOUT_MINUTES_MIN, SIMULATION_TIMEOUT_MINUTES_MAX)
        self.simulation_timeout_minutes.setSuffix(" min")
        self.simulation_timeout_minutes.setToolTip(
            "Maximum wait time for AKABAK solve completion per version before timeout."
        )
        self.analyzer_data_source = QComboBox()
        self.analyzer_data_source.setObjectName("AnalyzerDataSourceSettingsCombo")
        self.analyzer_data_source.addItem("Project", "project")
        self.analyzer_data_source.addItem("Global", "global")
        self.analyzer_data_source.setToolTip("Analyzer metadata source. MVP uses Project by default.")
        self.analyzer_cache_mode = QComboBox()
        self.analyzer_cache_mode.setObjectName("AnalyzerCacheModeCombo")
        self.analyzer_cache_mode.addItem("Low", "low")
        self.analyzer_cache_mode.addItem("Balanced", "balanced")
        self.analyzer_cache_mode.addItem("High", "high")
        self.analyzer_cache_mode.addItem("Extreme", "extreme")
        self.analyzer_cache_mode.addItem("Custom", "custom")
        self.analyzer_cache_limit_mb = QSpinBox()
        self.analyzer_cache_limit_mb.setObjectName("AnalyzerCacheLimitSpin")
        self.analyzer_cache_limit_mb.setRange(0, 10 * 1024)
        self.analyzer_cache_limit_mb.setSuffix(" MB")
        self.analyzer_cache_keep_last = QSpinBox()
        self.analyzer_cache_keep_last.setObjectName("AnalyzerCacheKeepLastSpin")
        self.analyzer_cache_keep_last.setRange(1, 200)
        self.analyzer_cache_warning = QLabel("High cache sizes may exceed RAM and cause OS swapping.")
        self.analyzer_cache_warning.setObjectName("SummaryMeta")
        self.analyzer_cache_warning.setWordWrap(True)

        general_tab = QWidget()
        general_form = QFormLayout(general_tab)
        general_form.addRow("Library Folder", self.library_root)
        general_form.addRow("ATH", self.ath_exe)
        general_form.addRow("AKABAK", self.akabak_exe)
        general_form.addRow("VACS", self.vacs_exe)
        general_form.addRow("Template CFG", self.template_cfg)
        general_form.addRow("Automation", self.background_automation_mode)
        general_form.addRow("Simulation Timeout", self.simulation_timeout_minutes)

        analyzer_tab = QWidget()
        analyzer_form = QFormLayout(analyzer_tab)
        analyzer_form.addRow("Data source", self.analyzer_data_source)
        analyzer_form.addRow(QLabel("Cache"))
        analyzer_form.addRow("Mode", self.analyzer_cache_mode)
        analyzer_form.addRow("Limit", self.analyzer_cache_limit_mb)
        analyzer_form.addRow("Keep last runs", self.analyzer_cache_keep_last)
        analyzer_form.addRow("", self.analyzer_cache_warning)

        tabs = QTabWidget()
        tabs.setObjectName("SettingsTabs")
        tabs.addTab(general_tab, "General")
        tabs.addTab(analyzer_tab, "Analyzer")

        save_btn = QPushButton("Save")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)

        root = QVBoxLayout(self)
        root.addWidget(tabs, 1)
        root.addLayout(buttons)

        self.analyzer_cache_mode.currentIndexChanged.connect(self._sync_cache_controls)
        self._load()

    def _load(self) -> None:
        settings = self.service.settings
        self.library_root.setText(settings.library_root)
        self.ath_exe.setText(settings.ath_exe or "")
        self.akabak_exe.setText(settings.akabak_exe or "")
        self.vacs_exe.setText(settings.vacs_exe or "")
        self.template_cfg.setText(settings.template_cfg or "")
        self.background_automation_mode.setChecked(bool(getattr(settings, "background_automation_mode", True)))
        self.simulation_timeout_minutes.setValue(
            int(
                getattr(settings, "simulation_timeout_minutes", SIMULATION_TIMEOUT_MINUTES_DEFAULT)
                or SIMULATION_TIMEOUT_MINUTES_DEFAULT
            )
        )
        source_token = str(getattr(settings, "analyzer_data_source", "project") or "project").strip().lower()
        self._set_combo_current_by_data(self.analyzer_data_source, source_token)
        mode_token = str(getattr(settings, "analyzer_cache_mode", "balanced") or "balanced").strip().lower()
        self._set_combo_current_by_data(self.analyzer_cache_mode, mode_token)
        self.analyzer_cache_limit_mb.setValue(int(getattr(settings, "analyzer_cache_limit_mb", 240) or 240))
        self.analyzer_cache_keep_last.setValue(int(getattr(settings, "analyzer_cache_keep_last_n", 5) or 5))
        self._sync_cache_controls()

    def _save(self) -> None:
        policy = resolve_cache_policy(
            mode=str(self.analyzer_cache_mode.currentData() or "balanced"),
            custom_limit_mb=int(self.analyzer_cache_limit_mb.value()),
            custom_keep_last_n=int(self.analyzer_cache_keep_last.value()),
        )
        settings = UserSettings(
            library_root=self.library_root.text().strip(),
            ath_exe=self.ath_exe.text().strip() or None,
            akabak_exe=self.akabak_exe.text().strip() or None,
            vacs_exe=self.vacs_exe.text().strip() or None,
            template_cfg=self.template_cfg.text().strip() or None,
            background_automation_mode=bool(self.background_automation_mode.isChecked()),
            simulation_timeout_minutes=int(self.simulation_timeout_minutes.value()),
            analyzer_data_source=str(self.analyzer_data_source.currentData() or "project"),
            analyzer_cache_mode=str(policy.mode),
            analyzer_cache_limit_mb=int(policy.size_limit_mb),
            analyzer_cache_keep_last_n=int(policy.keep_last_n),
        )
        result = self.service.save_settings(settings)
        issues = result.get("validation", {})
        self.settings_saved.emit(result)
        if issues:
            detail = "\n".join(f"- {key}: {value}" for key, value in issues.items())
            QMessageBox.warning(self, "Settings saved with warnings", detail)
        self.accept()

    @staticmethod
    def _set_combo_current_by_data(combo: QComboBox, value: str) -> None:
        token = str(value or "").strip().lower()
        if not token:
            return
        for index in range(combo.count()):
            if str(combo.itemData(index) or "").strip().lower() == token:
                combo.setCurrentIndex(index)
                return

    def _sync_cache_controls(self) -> None:
        mode = str(self.analyzer_cache_mode.currentData() or "balanced").strip().lower()
        if mode == "custom":
            self.analyzer_cache_limit_mb.setEnabled(True)
            self.analyzer_cache_keep_last.setEnabled(True)
            self.analyzer_cache_warning.setVisible(True)
            return
        policy = resolve_cache_policy(
            mode=mode,
            custom_limit_mb=int(self.analyzer_cache_limit_mb.value()),
            custom_keep_last_n=int(self.analyzer_cache_keep_last.value()),
        )
        self.analyzer_cache_limit_mb.blockSignals(True)
        self.analyzer_cache_keep_last.blockSignals(True)
        self.analyzer_cache_limit_mb.setValue(int(policy.size_limit_mb))
        self.analyzer_cache_keep_last.setValue(int(policy.keep_last_n))
        self.analyzer_cache_limit_mb.blockSignals(False)
        self.analyzer_cache_keep_last.blockSignals(False)
        self.analyzer_cache_limit_mb.setEnabled(False)
        self.analyzer_cache_keep_last.setEnabled(False)
        self.analyzer_cache_warning.setVisible(False)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class ExportDialog(QDialog):
    def __init__(self, versions_by_batch: Dict[str, List[str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.versions_by_batch = versions_by_batch
        self.setWindowTitle("Export Version")
        self.setModal(True)
        self.resize(420, 220)

        self.batch_combo = QComboBox()
        self.version_combo = QComboBox()
        self.export_stl = QCheckBox("STL")
        self.export_abec = QCheckBox("ABEC")
        self.export_abec.setChecked(True)

        for batch_id in sorted(self.versions_by_batch.keys()):
            self.batch_combo.addItem(batch_id)

        form = QFormLayout()
        form.addRow("Batch", self.batch_combo)
        form.addRow("Version", self.version_combo)
        form.addRow("Export STL", self.export_stl)
        form.addRow("Export ABEC", self.export_abec)

        self.batch_combo.currentTextChanged.connect(self._reload_versions)
        self._reload_versions(self.batch_combo.currentText())

        export_btn = QPushButton("Export")
        export_btn.setObjectName("PrimaryButton")
        export_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(export_btn)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(buttons)

    def _reload_versions(self, batch_id: str) -> None:
        self.version_combo.clear()
        for version_id in self.versions_by_batch.get(batch_id, []):
            self.version_combo.addItem(version_id)

    def payload(self) -> Dict[str, object]:
        return {
            "batch_id": self.batch_combo.currentText().strip(),
            "version_id": self.version_combo.currentText().strip(),
            "export_stl": self.export_stl.isChecked(),
            "export_abec": self.export_abec.isChecked(),
        }

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class RunManagerDialog(QDialog):
    def __init__(self, service: OrchestratorService, project_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.setWindowTitle("Runs verwalten")
        self.setModal(True)
        self.resize(760, 420)

        self.batch_filter = QComboBox()
        self.run_list = QListWidget()
        self.run_list.setSelectionMode(QAbstractItemView.SingleSelection)

        refresh_btn = QPushButton("Refresh")
        pin_btn = QPushButton("Pin")
        pin_btn.setToolTip("Markiert einen Run als Ergebnis, das behalten werden soll.")
        unpin_btn = QPushButton("Unpin")
        close_btn = QPushButton("Close")

        top = QFormLayout()
        top.addRow("Batch Filter", self.batch_filter)

        actions = QHBoxLayout()
        actions.addWidget(refresh_btn)
        actions.addWidget(pin_btn)
        actions.addWidget(unpin_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(self.run_list, 1)
        root.addLayout(actions)

        refresh_btn.clicked.connect(self._reload_runs)
        pin_btn.clicked.connect(self._pin_selected)
        unpin_btn.clicked.connect(self._unpin_selected)
        close_btn.clicked.connect(self.accept)
        self.batch_filter.currentTextChanged.connect(lambda _: self._reload_runs())

        self._reload_batches()
        self._reload_runs()

    def _reload_batches(self) -> None:
        self.batch_filter.clear()
        self.batch_filter.addItem("(all)")
        for batch in self.service.repo.list_batches(self.project_id):
            self.batch_filter.addItem(batch.batch_id)

    def _selected_run_id(self) -> Optional[str]:
        item = self.run_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return str(value) if value else None

    def _reload_runs(self) -> None:
        self.run_list.clear()
        batch_text = self.batch_filter.currentText().strip()
        batch_id = None if batch_text in {"", "(all)"} else batch_text
        rows = self.service.list_runs(project_id=self.project_id, batch_id=batch_id)
        for row in rows:
            status = str(row.get("status", ""))
            pinned = bool(row.get("pinned", False))
            tag = str(row.get("tag") or "")
            pin_flag = "PINNED" if pinned else "unpinned"
            tag_text = f" [{tag}]" if tag else ""
            label = f"{row['run_id']} | {row['batch_id']} | {status} | {pin_flag}{tag_text}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(row["run_id"]))
            self.run_list.addItem(item)

    def _pin_selected(self) -> None:
        run_id = self._selected_run_id()
        if not run_id:
            return
        tag, ok = QInputDialog.getText(self, "Run pinnen", "Tag (optional):")
        if not ok:
            return
        self.service.pin_run(project_id=self.project_id, run_id=run_id, tag=tag.strip() or None)
        self._reload_runs()

    def _unpin_selected(self) -> None:
        run_id = self._selected_run_id()
        if not run_id:
            return
        self.service.unpin_run(project_id=self.project_id, run_id=run_id)
        self._reload_runs()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class CleanupTestDataDialog(QDialog):
    def __init__(self, service: OrchestratorService, project_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.setWindowTitle("Testdaten aufraeumen")
        self.setModal(True)
        self.resize(760, 500)
        self._last_preview: Dict[str, Any] = {}

        info = QLabel("Behalten: angeheftete Runs. Loeschen: alle anderen Runs (Testdaten).")
        info.setWordWrap(True)

        self.delete_exports = QCheckBox("Exportdateien ebenfalls loeschen (empfohlen)")
        self.delete_exports.setChecked(True)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)

        self.confirm_input = QLineEdit()
        self.confirm_input.setPlaceholderText("Type DELETE to confirm")

        preview_btn = QPushButton("Preview")
        cleanup_btn = QPushButton("Cleanup")
        cleanup_btn.setObjectName("PrimaryButton")
        cancel_btn = QPushButton("Cancel")

        actions = QHBoxLayout()
        actions.addWidget(preview_btn)
        actions.addWidget(cleanup_btn)
        actions.addStretch(1)
        actions.addWidget(cancel_btn)

        root = QVBoxLayout(self)
        root.addWidget(info)
        root.addWidget(self.delete_exports)
        root.addWidget(self.preview_text, 1)
        root.addWidget(QLabel("Confirmation"))
        root.addWidget(self.confirm_input)
        root.addLayout(actions)

        preview_btn.clicked.connect(self._preview)
        cleanup_btn.clicked.connect(self._cleanup)
        cancel_btn.clicked.connect(self.reject)
        self._preview()

    def _preview(self) -> None:
        result = self.service.cleanup_test_data(
            project_id=self.project_id,
            delete_exports=self.delete_exports.isChecked(),
            dry_run=True,
        )
        self._last_preview = result
        run_ids = list(result.get("run_ids", []))
        counts = dict(result.get("counts", {}) or {})
        lines = [
            f"Project: {self.project_id}",
            f"Runs to delete: {len(run_ids)}",
            f"Counts: {json.dumps(counts, ensure_ascii=False)}",
            "",
            "Run IDs:",
            *[f"- {run_id}" for run_id in run_ids],
        ]
        self.preview_text.setPlainText("\n".join(lines))

    def _cleanup(self) -> None:
        if self.confirm_input.text().strip() != "DELETE":
            QMessageBox.warning(self, "Confirmation required", 'Type "DELETE" to continue.')
            return
        result = self.service.cleanup_test_data(
            project_id=self.project_id,
            delete_exports=self.delete_exports.isChecked(),
            dry_run=False,
        )
        self._last_preview = result
        QMessageBox.information(
            self,
            "Cleanup finished",
            f"Deleted runs: {len(list(result.get('run_ids', [])))}\nAudit: {result.get('audit_log')}",
        )
        self.accept()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class ConstraintSummaryGrid(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProjectSummaryPanel")
        self._entries: List[tuple[str, str]] = []
        self._last_render_cols: Optional[int] = None
        self._last_render_signature: Optional[tuple[tuple[str, str], ...]] = None
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        title = QLabel("Project Constraints")
        title.setObjectName("SummaryTitle")
        root.addWidget(title)
        self._grid_wrap = QWidget()
        self._grid = QGridLayout(self._grid_wrap)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(8)
        root.addWidget(self._grid_wrap)
        self._empty = QLabel("No project loaded.")
        self._empty.setObjectName("SummaryText")
        root.addWidget(self._empty)
        self._clear_grid()

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.4g}"
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    def set_constraints_payload(self, payload: Optional[Dict[str, Any]]) -> None:
        raw = dict(payload or {})
        entries: List[tuple[str, str]] = []
        for key, value in sorted(dict(raw.get("fixed_params", {}) or {}).items()):
            entries.append((str(key), self._format_value(value)))
        for key, value in sorted(dict(raw.get("limits", {}) or {}).items()):
            entries.append((f"{key} (limit)", self._format_value(value)))
        for row in list(raw.get("param_states", []) or []):
            if not isinstance(row, dict):
                continue
            if not bool(row.get("is_set")):
                continue
            key = str(row.get("param_name", "")).strip()
            if not key:
                continue
            if any(item[0] == key for item in entries):
                continue
            entries.append((key, self._format_value(row.get("value"))))
        self._entries = entries
        self._rebuild_grid()

    def _target_cols(self) -> int:
        width = max(int(self.width()), 1)
        return 1 if width < 620 else (2 if width < 980 else 3)

    def _rebuild_grid(self) -> None:
        signature = tuple((str(key), str(value)) for key, value in list(self._entries))
        cols = self._target_cols()
        if self._last_render_cols == cols and self._last_render_signature == signature:
            return
        self._last_render_cols = cols
        self._last_render_signature = signature
        self.setUpdatesEnabled(False)
        self._clear_grid()
        if not self._entries:
            self._empty.setVisible(True)
            self.setUpdatesEnabled(True)
            return
        self._empty.setVisible(False)
        for index, (key, value) in enumerate(list(self._entries)):
            row = index // cols
            col = index % cols
            card = QFrame()
            card.setObjectName("ConstraintCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 8, 8, 8)
            card_layout.setSpacing(2)
            k = QLabel(str(key))
            k.setObjectName("SummaryMeta")
            v = QLabel(str(value))
            v.setObjectName("SummaryText")
            v.setWordWrap(True)
            card_layout.addWidget(k)
            card_layout.addWidget(v)
            self._grid.addWidget(card, row, col)
        for col in range(cols):
            self._grid.setColumnStretch(col, 1)
        self.setUpdatesEnabled(True)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._rebuild_grid()


class DashboardPage(QWidget):
    request_new_batch = Signal()
    request_edit_batch = Signal(str)
    request_clone_batch = Signal(str)
    request_open_export_dialog = Signal()
    request_manage_runs = Signal()
    request_cleanup_testdata = Signal()
    request_settings = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 14)
        root.setSpacing(10)

        title = QLabel("DASHBOARD")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        self.constraints_summary = ConstraintSummaryGrid()
        root.addWidget(self.constraints_summary)

        batch_card = QFrame()
        batch_card.setObjectName("ProjectSummaryPanel")
        batch_layout = QVBoxLayout(batch_card)
        batch_layout.setContentsMargins(10, 8, 10, 10)
        batch_layout.setSpacing(8)
        batch_title = QLabel("Batches")
        batch_title.setObjectName("SummaryTitle")
        batch_layout.addWidget(batch_title)
        self.batch_list = QListWidget()
        self.batch_list.setObjectName("DashboardBatchList")
        batch_layout.addWidget(self.batch_list, 1)
        root.addWidget(batch_card, 1)

        actions_shell = QFrame()
        actions_shell.setObjectName("BatchActionBar")
        actions_shell.setFixedHeight(56)
        actions = QHBoxLayout(actions_shell)
        actions.setContentsMargins(10, 8, 10, 8)
        actions.setSpacing(10)
        self.new_batch_btn = QPushButton("New Batch")
        self.new_batch_btn.setObjectName("BatchSecondaryButton")
        self.edit_batch_btn = QPushButton("Edit Batch")
        self.edit_batch_btn.setObjectName("BatchSecondaryButton")
        self.clone_batch_btn = QPushButton("Clone Batch")
        self.clone_batch_btn.setObjectName("BatchSecondaryButton")
        actions.addWidget(self.new_batch_btn)
        actions.addWidget(self.edit_batch_btn)
        actions.addWidget(self.clone_batch_btn)
        actions.addStretch(1)
        root.addWidget(actions_shell)

        export_box = QFrame()
        export_box.setObjectName("ProjectSummaryPanel")
        export_root = QVBoxLayout(export_box)
        export_root.setContentsMargins(10, 8, 10, 10)
        export_root.setSpacing(8)
        export_title = QLabel("Export")
        export_title.setObjectName("SummaryTitle")
        export_root.addWidget(export_title)
        export_grid = QGridLayout()
        export_grid.setContentsMargins(0, 0, 0, 0)
        export_grid.setHorizontalSpacing(8)
        export_grid.setVerticalSpacing(8)
        self.export_btn = QPushButton("Open Export Dialog")
        self.export_btn.setObjectName("BatchPrimaryButton")
        self.manage_runs_btn = QPushButton("Runs verwalten...")
        self.manage_runs_btn.setObjectName("BatchSecondaryButton")
        self.cleanup_testdata_btn = QPushButton("Testdaten aufraeumen...")
        self.cleanup_testdata_btn.setObjectName("BatchSecondaryButton")
        export_grid.addWidget(self.export_btn, 0, 0)
        export_grid.addWidget(self.manage_runs_btn, 0, 1)
        export_grid.addWidget(self.cleanup_testdata_btn, 0, 2)
        export_root.addLayout(export_grid)
        root.addWidget(export_box)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setObjectName("BatchGhostButton")
        footer.addWidget(self.settings_btn)
        root.addLayout(footer)

        self.new_batch_btn.clicked.connect(self.request_new_batch.emit)
        self.edit_batch_btn.clicked.connect(self._emit_edit)
        self.clone_batch_btn.clicked.connect(self._emit_clone)
        self.export_btn.clicked.connect(self.request_open_export_dialog.emit)
        self.manage_runs_btn.clicked.connect(self.request_manage_runs.emit)
        self.cleanup_testdata_btn.clicked.connect(self.request_cleanup_testdata.emit)
        self.settings_btn.clicked.connect(self.request_settings.emit)

    def set_constraints_payload(self, payload: Optional[Dict[str, Any]]) -> None:
        self.constraints_summary.set_constraints_payload(payload)

    def _selected_batch_id(self) -> Optional[str]:
        item = self.batch_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        return str(data) if data else None

    def _emit_edit(self) -> None:
        batch_id = self._selected_batch_id()
        if batch_id:
            self.request_edit_batch.emit(batch_id)

    def _emit_clone(self) -> None:
        batch_id = self._selected_batch_id()
        if batch_id:
            self.request_clone_batch.emit(batch_id)

class ProjectIssuesPanel(QFrame):
    issue_selected = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        popup: bool = False,
        show_header: bool = True,
    ) -> None:
        _ = popup
        super().__init__(parent)
        self.setObjectName("ProjectIssuesPanel")
        self.setMinimumWidth(0)
        self.setMinimumHeight(96)
        self._show_header = bool(show_header)
        self._compact_counts = "E0 W0 I0"
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        if self._show_header:
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(6)
            self.counts = QLabel("Errors: 0 · Warnings: 0 · Incomplete: 0")
            self.counts.setObjectName("IssuesPanelCounts")
            header.addWidget(self.counts, 0, Qt.AlignLeft | Qt.AlignVCenter)
            header.addStretch(1)
            root.addLayout(header)
        else:
            self.counts = QLabel("")
            self.counts.setVisible(False)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setMinimumHeight(66)
        self._container = QWidget()
        self._rows = QVBoxLayout(self._container)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(5)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll)

    def _clear_rows(self) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def set_issues(self, issues: List[UiProjectIssue]) -> None:
        self._clear_rows()
        counts = issue_counts(issues)
        fatal_count = int(counts.get("error", 0))
        warn_count = int(counts.get("warn", 0))
        incomplete_count = int(counts.get("incomplete", 0))
        self._compact_counts = f"E{fatal_count} W{warn_count} I{incomplete_count}"
        if self._show_header:
            self.counts.setText(
                f"Errors: {fatal_count} · "
                f"Warnings: {warn_count} · "
                f"Incomplete: {incomplete_count}"
            )

        groups: Dict[str, List[UiProjectIssue]] = {"error": [], "warn": [], "incomplete": []}
        for issue in issues:
            groups.setdefault(issue.severity, []).append(issue)

        labels = {
            "error": "Errors",
            "warn": "Warnings",
            "incomplete": "Incomplete",
        }
        for severity in ("error", "warn", "incomplete"):
            rows = groups.get(severity, [])
            if not rows:
                continue
            section_label = QLabel(f"{labels[severity]} ({len(rows)})")
            section_label.setObjectName("IssuesPanelGroupTitle")
            section_label.setProperty("severity", severity)
            self._rows.addWidget(section_label)
            for issue in rows:
                badge = {"error": "[E]", "warn": "[W]", "incomplete": "[I]"}.get(severity, "[I]")
                button = IssueRowButton(
                    f"{badge}  {issue.field_label}: {issue.message}  [{issue.section}]"
                )
                button.setObjectName("IssueRowButton")
                button.setProperty("severity", severity)
                button.setCursor(Qt.PointingHandCursor)
                button.setFlat(True)
                button.setToolTip(f"{issue.field_label}: {issue.message}")
                button.clicked.connect(lambda _checked=False, key=issue.key: self.issue_selected.emit(str(key)))
                self._rows.addWidget(button)
        if self._rows.count() == 0:
            empty = QLabel("No open issues.")
            empty.setObjectName("IssuesPanelEmpty")
            self._rows.addWidget(empty)
        self._rows.addStretch(1)

    def show_for(self, anchor: QWidget) -> None:
        _ = anchor
        self.setVisible(True)

    def compact_counts(self) -> str:
        return self._compact_counts


class IssuesSubsectionHeader(QToolButton):
    toggled_request = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SummaryIssuesHeaderButton")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setProperty("severity", "ok")
        self.setMinimumHeight(30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setArrowType(Qt.LeftArrow)
        self.setText("Issues")
        self.setEnabled(False)
        self.clicked.connect(lambda _checked=False: self.toggled_request.emit())
        self._issue_total = 0

    def set_issue_total(self, total: int) -> None:
        self._issue_total = max(int(total), 0)
        if self._issue_total > 0:
            self.setText(f"Issues ({self._issue_total})")
            self.setEnabled(True)
        else:
            self.setText("Issues")
            self.setEnabled(False)

    def set_expanded(self, expanded: bool) -> None:
        self.setArrowType(Qt.RightArrow if expanded else Qt.LeftArrow)
        self.setProperty("expanded", "true" if expanded else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_severity(self, level: str) -> None:
        self.setProperty("severity", str(level or "ok"))
        self.style().unpolish(self)
        self.style().polish(self)

class SummaryIssuesSection(QFrame):
    issue_selected = Signal(str)
    toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SummaryIssuesSection")
        self._expanded = False
        self._target_body_width = 320
        self._target_body_height = 84
        self._collapsed_width = 96

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.body = QFrame(self)
        self.body.setObjectName("SummaryIssuesBody")
        self.body.installEventFilter(self)
        self.body.setMinimumHeight(self._target_body_height)
        self.body.setMaximumWidth(0)
        self.body.setMaximumHeight(0)
        self.body.setVisible(False)
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self.panel = ProjectIssuesPanel(self, popup=False, show_header=True)
        self.panel.setVisible(False)
        self.panel_effect = QGraphicsOpacityEffect(self.panel)
        self.panel_effect.setOpacity(0.0)
        self.panel.setGraphicsEffect(self.panel_effect)
        body_layout.addWidget(self.panel)
        root.addWidget(self.body, 1)

        self.header = IssuesSubsectionHeader(self)
        self.header.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        root.addWidget(self.header, 0)
        self._refresh_collapsed_width()

        self._width_anim = QPropertyAnimation(self.body, b"maximumWidth", self)
        self._width_anim.setDuration(200)
        self._width_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._opacity_anim = QPropertyAnimation(self.panel_effect, b"opacity", self)
        self._opacity_anim.setDuration(180)
        self._opacity_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.panel.issue_selected.connect(self.issue_selected.emit)

    def _refresh_collapsed_width(self) -> None:
        self._collapsed_width = max(int(self.header.sizeHint().width()) + 4, 78)
        self.header.setFixedWidth(self._collapsed_width)

    def collapsed_width(self) -> int:
        return self._collapsed_width

    def set_issues(self, issues: List[UiProjectIssue]) -> None:
        self.panel.set_issues(issues)
        counts = issue_counts(issues)
        fatal_count = int(counts.get("error", 0))
        warn_count = int(counts.get("warn", 0))
        incomplete_count = int(counts.get("incomplete", 0))
        self.header.set_issue_total(fatal_count + warn_count + incomplete_count)
        self._refresh_collapsed_width()
        if fatal_count > 0:
            self.header.set_severity("fatal")
        elif warn_count > 0:
            self.header.set_severity("warn")
        elif incomplete_count > 0:
            self.header.set_severity("incomplete")
        else:
            self.header.set_severity("ok")

    def set_body_target_size(self, width: int, height: int) -> None:
        self._target_body_width = max(int(width), 220)
        self._target_body_height = max(int(height), 36)
        self.body.setMinimumHeight(self._target_body_height)
        self.body.setMaximumHeight(self._target_body_height)
        if self._expanded:
            self.body.setMaximumWidth(self._target_body_width)
        else:
            self.body.setMaximumWidth(0)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded, animated=True)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, *, animated: bool) -> None:
        target = bool(expanded)
        if target == self._expanded:
            return
        self._expanded = target
        self.header.set_expanded(target)
        self.toggled.emit(target)
        self._width_anim.stop()
        self._opacity_anim.stop()
        if target:
            self.body.setVisible(True)
            self.panel.setVisible(True)

        start_width = int(self.body.maximumWidth())
        end_width = self._target_body_width if target else 0
        start_opacity = float(self.panel_effect.opacity())
        end_opacity = 1.0 if target else 0.0

        if animated:
            self._width_anim.setStartValue(start_width)
            self._width_anim.setEndValue(end_width)
            self._opacity_anim.setStartValue(start_opacity)
            self._opacity_anim.setEndValue(end_opacity)
            self._width_anim.start()
            self._opacity_anim.start()
            if not target:
                QTimer.singleShot(200, lambda: self.panel.setVisible(False))
                QTimer.singleShot(200, lambda: self.body.setVisible(False))
        else:
            self.body.setMaximumWidth(end_width)
            self.panel_effect.setOpacity(end_opacity)
            self.panel.setVisible(target)
            self.body.setVisible(target)

    def eventFilter(self, watched: QObject, event) -> bool:  # type: ignore[override]
        if watched is self.body and self._expanded and event.type() == QEvent.MouseButtonPress:
            target = self.body.childAt(event.pos())
            if target is None or target.objectName() != "IssueRowButton":
                self.set_expanded(False, animated=True)
                return False
        return super().eventFilter(watched, event)

class ProjectPage(QWidget):
    submit_project = Signal(str, dict)
    draft_changed = Signal(dict)
    blocked_interaction = Signal(str, str, str)

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 14)
        root.setSpacing(8)
        title = QLabel("PROJECT")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        root.addSpacing(4)

        form_column_width = (2 * FORM_METRICS.label_width) + (2 * FORM_METRICS.input_width) + FORM_METRICS.column_gap + 32
        self._form_column_width = form_column_width

        name_wrap = QWidget()
        name_row = QHBoxLayout(name_wrap)
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(10)
        left_col = QWidget()
        left_col.setMinimumWidth(form_column_width)
        left_col.setMaximumWidth(form_column_width)
        left_col_layout = QHBoxLayout(left_col)
        left_col_layout.setContentsMargins(0, 0, 0, 0)
        left_col_layout.setSpacing(0)
        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("Project Name")
        self.project_name.setToolTip("Project Name")
        self.project_name.setMinimumWidth(form_column_width)
        left_col_layout.addWidget(self.project_name)
        name_row.addWidget(left_col, 0, Qt.AlignTop)
        name_row.addStretch(1)
        root.addWidget(name_wrap)
        root.addSpacing(2)

        self.summary_panel = QFrame()
        self.summary_panel.setObjectName("ProjectSummaryPanel")
        self.summary_panel.setFixedHeight(108)
        summary_layout = QHBoxLayout(self.summary_panel)
        summary_layout.setContentsMargins(12, 6, 12, 6)
        summary_layout.setSpacing(10)
        self.summary_left = QWidget()
        summary_left_layout = QVBoxLayout(self.summary_left)
        summary_left_layout.setContentsMargins(0, 0, 0, 0)
        summary_left_layout.setSpacing(2)

        summary_head = QHBoxLayout()
        summary_head.setContentsMargins(0, 0, 0, 0)
        summary_head.setSpacing(6)
        summary_title = QLabel("Project constraints (locked after creation)")
        summary_title.setObjectName("SummaryTitle")
        summary_head.addWidget(summary_title)
        summary_head.addStretch(1)
        summary_left_layout.addLayout(summary_head)
        self.summary_line_1 = QLabel(
            "Everything you set here becomes fixed for the project and cannot be changed in Batch runs."
        )
        self.summary_line_1.setObjectName("SummaryText")
        self.summary_line_1.setWordWrap(False)
        summary_left_layout.addWidget(self.summary_line_1)
        summary_left_layout.addStretch(1)
        self.summary_chips_wrap = QWidget()
        self.summary_chips_layout = QHBoxLayout(self.summary_chips_wrap)
        self.summary_chips_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_chips_layout.setSpacing(6)
        summary_left_layout.addWidget(self.summary_chips_wrap)
        summary_layout.addWidget(self.summary_left, 1)

        self.summary_right = QWidget()
        self.summary_right.setObjectName("SummaryIssuesDock")
        summary_right_layout = QVBoxLayout(self.summary_right)
        summary_right_layout.setContentsMargins(10, 8, 10, 8)
        summary_right_layout.setSpacing(2)
        self.summary_issue_title = QLabel("Validation")
        self.summary_issue_title.setObjectName("SummaryTitle")
        summary_right_layout.addWidget(self.summary_issue_title)
        self.summary_issue_hint = QLabel("No validation issues.")
        self.summary_issue_hint.setObjectName("IssueHint")
        self.summary_issue_hint.setWordWrap(True)
        summary_right_layout.addWidget(self.summary_issue_hint)
        summary_right_layout.addStretch(1)
        self.summary_right.setMinimumWidth(320)
        self.summary_right.setMaximumWidth(420)
        summary_layout.addWidget(self.summary_right, 0)
        root.addWidget(self.summary_panel)
        root.addSpacing(2)

        self.constraints_form = ParameterForm(build_project_form_schema())
        root.addWidget(self.constraints_form, 1)

        self.action_bar = QFrame()
        self.action_bar.setObjectName("ProjectActionBar")
        self.action_bar.setFixedHeight(58)
        action_layout = QHBoxLayout(self.action_bar)
        action_layout.setContentsMargins(10, 8, 10, 8)
        action_layout.setSpacing(10)

        self.action_status_pill = QLabel("Ready to create project.")
        self.action_status_pill.setObjectName("ProjectStatusPill")
        self.action_status_pill.setProperty("severity", "ok")
        action_layout.addWidget(self.action_status_pill, 0, Qt.AlignVCenter)

        self.action_counts = QLabel("0 errors · 0 warnings · 0 incomplete")
        self.action_counts.setObjectName("ProjectStatusHint")
        action_layout.addWidget(self.action_counts, 0, Qt.AlignVCenter)

        self.action_status_hint = QLabel("")
        self.action_status_hint.setObjectName("ProjectStatusHint")
        action_layout.addWidget(self.action_status_hint, 0, Qt.AlignVCenter)

        action_layout.addStretch(1)

        self.create_btn = QPushButton("Create Project")
        self.create_btn.setObjectName("BatchPrimaryButton")
        action_layout.addWidget(self.create_btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        root.addWidget(self.action_bar)

        self.create_btn.clicked.connect(self._submit)
        self.constraints_form.changed.connect(self._emit_draft_changed)
        self.constraints_form.blocked_interaction.connect(self.blocked_interaction.emit)

        self._compat_state: Dict[str, Any] = {"visible_keys": [], "locked_keys": [], "sweepable_keys": [], "issues": []}
        self._latest_field_issues: List[Dict[str, Any]] = []
        self._ui_issues: List[UiProjectIssue] = []
        self._validation_phase = "idle"
        self._creating_project = False
        self._constraints_locked = False
        self._update_action_state()
        self._update_summary_panel()
        self._update_issues_panel()

    def _emit_draft_changed(self, payload: Dict[str, Any] | None = None) -> None:
        self.draft_changed.emit(payload or self._raw_constraints_payload())

    def _raw_constraints_payload(self) -> Dict[str, Any]:
        return self.constraints_form.payload()

    def apply_compatibility(self, state: Dict[str, Any]) -> None:
        self._compat_state = dict(state)
        self.constraints_form.apply_compatibility(state)

    def apply_ui_risks(self, issues: List[Dict[str, Any]]) -> None:
        raw_issues = [item for item in issues if isinstance(item, dict)]
        field_is_set = self.constraints_form.field_is_set_map()
        field_labels = self.constraints_form.field_label_map()
        field_sections = self.constraints_form.field_section_map()

        mapped: List[Dict[str, Any]] = []
        for issue in raw_issues:
            key = str(issue.get("field_key") or issue.get("key") or "").strip()
            severity = classify_ui_severity(issue, field_is_set=bool(field_is_set.get(key, False)))
            normalized = dict(issue)
            if severity == "error":
                normalized["severity"] = "fatal"
            elif severity == "warn":
                normalized["severity"] = "warn"
            elif severity == "incomplete":
                normalized["severity"] = "incomplete"
            mapped.append(normalized)

        self._latest_field_issues = mapped
        self._ui_issues = normalize_project_issues(
            raw_issues,
            field_is_set=field_is_set,
            field_labels=field_labels,
            field_sections=field_sections,
        )
        self.constraints_form.apply_ui_risks(mapped)
        if self._validation_phase == "validating":
            self._validation_phase = "idle"
        self._update_action_state()
        self._update_summary_panel()
        self._update_issues_panel()

    def set_validation_phase(self, phase: str) -> None:
        self._validation_phase = str(phase or "idle").strip().lower()
        self._update_action_state()

    def set_creating(self, creating: bool) -> None:
        self._creating_project = bool(creating)
        if creating:
            self._constraints_locked = False
        self._update_action_state()

    def set_constraints_locked(self, locked: bool) -> None:
        self._constraints_locked = bool(locked)
        if locked:
            self._creating_project = False
            self._validation_phase = "idle"
        self._update_action_state()
        self._update_summary_panel()
        self._update_issues_panel()

    def _issue_counts(self) -> Dict[str, int]:
        raw = issue_counts(self._ui_issues)
        return {
            "fatal": int(raw.get("error", 0)),
            "warn": int(raw.get("warn", 0)),
            "incomplete": int(raw.get("incomplete", 0)),
        }

    @staticmethod
    def _mode_label(mapping: Dict[int, str], value: Any, *, fallback: str) -> str:
        try:
            key = int(value)
        except Exception:
            return fallback
        return mapping.get(key, fallback)

    def _mode_chips(self, payload: Dict[str, Any]) -> List[str]:
        state_by_key: Dict[str, Dict[str, Any]] = {}
        for row in list(payload.get("param_states", []) or []):
            if not isinstance(row, dict):
                continue
            key = str(row.get("param_name", "")).strip()
            if not key:
                continue
            state_by_key[key] = {"is_set": bool(row.get("is_set")), "value": row.get("value")}

        def get_value(key: str) -> Any:
            row = state_by_key.get(key, {})
            if bool(row.get("is_set")):
                return row.get("value")
            return None

        throat_value = get_value("Throat.Profile")
        gcurve_value = get_value("GCurve.Type")
        morph_value = get_value("Morph.TargetShape")
        enclosure_enabled = bool(state_by_key.get("Mesh.Enclosure", {}).get("is_set", False))
        chips = [
            f"Throat: {self._mode_label({1: 'OS-SE', 2: 'R-OSSE', 3: 'Circular Arc'}, throat_value, fallback='unset')}",
            f"Morph: {self._mode_label({0: 'no morph', 1: 'rectangle', 2: 'circle'}, morph_value if morph_value is not None else 0, fallback='no morph')}",
            f"GCurve: {self._mode_label({0: 'no GCurve', 1: 'Superellipse', 2: 'Superformula'}, gcurve_value if gcurve_value is not None else 0, fallback='no GCurve')}",
            f"Enclosure: {'enabled' if enclosure_enabled else 'disabled'}",
        ]
        return chips

    def _set_summary_chips(self, chips: List[str]) -> None:
        while self.summary_chips_layout.count():
            item = self.summary_chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        max_visible = 4
        visible = chips[:max_visible]
        for chip_text in visible:
            chip = QLabel(chip_text)
            chip.setObjectName("SummaryChip")
            self.summary_chips_layout.addWidget(chip, 0, Qt.AlignVCenter)
        remaining = max(0, len(chips) - max_visible)
        if remaining > 0:
            more_chip = QLabel(f"+{remaining}")
            more_chip.setObjectName("SummaryChip")
            self.summary_chips_layout.addWidget(more_chip, 0, Qt.AlignVCenter)
        self.summary_chips_layout.addStretch(1)

    def _update_summary_panel(self) -> None:
        payload = self._raw_constraints_payload()
        self._set_summary_chips(self._mode_chips(payload))

    def _update_issues_panel(self) -> None:
        counts = issue_counts(self._ui_issues)
        fatal = int(counts.get("error", 0))
        warn = int(counts.get("warn", 0))
        incomplete = int(counts.get("incomplete", 0))
        if self._ui_issues:
            top = self._ui_issues[0]
            teaser = str(top.message or "").strip()
            if len(teaser) > 132:
                teaser = f"{teaser[:129].rstrip()}..."
        else:
            teaser = "No validation issues."
        if fatal > 0:
            self.summary_issue_hint.setProperty("severity", "fatal")
            self.summary_issue_hint.setText(teaser or f"{fatal} fatal issue(s).")
        elif warn > 0:
            self.summary_issue_hint.setProperty("severity", "warn")
            self.summary_issue_hint.setText(teaser or f"{warn} warning(s).")
        elif incomplete > 0:
            self.summary_issue_hint.setProperty("severity", "")
            self.summary_issue_hint.setText("Configuration incomplete. Fill required values when ready.")
        else:
            self.summary_issue_hint.setProperty("severity", "")
            self.summary_issue_hint.setText("No validation issues.")
        self.summary_issue_hint.style().unpolish(self.summary_issue_hint)
        self.summary_issue_hint.style().polish(self.summary_issue_hint)

    def _update_action_state(self) -> None:
        counts = self._issue_counts()
        fatal = int(counts.get("fatal", 0))
        warn = int(counts.get("warn", 0))
        incomplete = int(counts.get("incomplete", 0))

        if self._creating_project:
            text = "Creating project..."
            severity = "progress"
            hint = ""
        elif self._constraints_locked:
            text = "Constraints locked for this project"
            severity = "ok"
            hint = ""
        elif self._validation_phase == "validating":
            text = "Checking constraints..."
            severity = "progress"
            hint = ""
        elif fatal > 0:
            text = "Resolve errors to continue."
            severity = "fatal"
            hint = "Resolve errors to proceed."
        elif incomplete > 0 and warn > 0:
            text = "Configuration incomplete. You can create the project, but review warnings."
            severity = "warn"
            hint = "Missing required values are shown as incomplete."
        elif incomplete > 0:
            text = "Configuration incomplete. You can create the project and complete values later."
            severity = "neutral"
            hint = ""
        elif warn > 0:
            text = "Warnings present — you can continue, but review them."
            severity = "warn"
            hint = "You can continue, but results may be unstable."
        else:
            text = "Ready to create project."
            severity = "ok"
            hint = ""

        self.action_status_pill.setText(text)
        self.action_status_pill.setProperty("severity", severity)
        self.action_status_pill.style().unpolish(self.action_status_pill)
        self.action_status_pill.style().polish(self.action_status_pill)
        self.action_status_hint.setText(hint)
        self.action_status_hint.setVisible(bool(hint))
        self.action_counts.setText(f"{fatal} errors · {warn} warnings · {incomplete} incomplete")

        enabled = (fatal == 0) and (not self._creating_project) and (not self._constraints_locked)
        self.create_btn.setEnabled(enabled)
        if self._constraints_locked:
            self.create_btn.setToolTip("Project is already created; constraints are locked.")
        elif not enabled and fatal > 0:
            self.create_btn.setToolTip("Resolve errors before creating the project.")
        else:
            self.create_btn.setToolTip("")

    def _toggle_issues_panel(self) -> None:
        return

    def _focus_issue_key(self, key: str) -> None:
        self.constraints_form.focus_issue_key(str(key))
        self._update_action_state()

    def _set_issues_open(self, open_state: bool, *, animated: bool) -> None:
        _ = (open_state, animated)
        return

    def _summary_issues_dimensions(self) -> tuple[int, int, int]:
        return (320, 420, 96)

    def _sync_summary_issues_geometry(self) -> None:
        return

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)

    def _submit(self) -> None:
        if not self.create_btn.isEnabled() or self._creating_project or self._constraints_locked:
            return
        payload = self._raw_constraints_payload()
        self.submit_project.emit(self.project_name.text().strip(), payload)


class BatchPage(QWidget):
    save_batch = Signal(dict)
    run_batch = Signal(dict)
    draft_changed = Signal(dict)
    blocked_interaction = Signal(str, str, str)

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 14)
        root.setSpacing(8)
        self._root_layout = root

        self.command_header = CommandHeaderWidget(context_label="Batch")
        self.batch_name = self.command_header.batch_name_edit
        self.save_btn = self.command_header.save_button
        self.run_btn = self.command_header.run_button
        self.summary_issue_hint = self.command_header.issues_chip
        root.addWidget(self.command_header)

        self.parameter_form = BatchParameterForm(build_project_form_schema())
        self.export_panel = BatchExportPanel()
        self.preview_panel = BatchPreviewPlaceholder()
        self.preview_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.export_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.export_panel.setMinimumHeight(220)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        left_panel = QFrame()
        left_panel.setObjectName("ProjectIssuesPanel")
        left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_panel.setMinimumWidth(0)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        left_layout.addWidget(self.parameter_form, 1)
        self.parameter_form.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.parameter_form.setMinimumWidth(0)
        body.addWidget(left_panel, 3)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(self.preview_panel, 3)
        right_layout.addWidget(self.export_panel, 1)
        body.addWidget(right_panel, 2)
        root.addLayout(body, 1)

        self.compat_panel = CompatibilityPanel("Batch Compatibility")
        self.compat_panel.setVisible(False)

        self.save_btn.clicked.connect(lambda: self.save_batch.emit(self._payload()))
        self.run_btn.clicked.connect(lambda: self.run_batch.emit(self._payload()))

        self.parameter_form.changed.connect(self._emit_draft_changed)
        self.parameter_form.blocked_interaction.connect(self.blocked_interaction.emit)
        self.export_panel.changed.connect(self._emit_draft_changed)
        self.export_panel.open_enclosure.connect(self.parameter_form.open_enclosure_dialog)
        self.batch_name.textChanged.connect(self._emit_draft_changed)

        self._body_layout = body
        self._left_panel = left_panel
        self._right_panel = right_panel

        self._compat_state: Dict[str, Any] = {"visible_keys": [], "locked_keys": [], "sweepable_keys": [], "issues": []}
        self._latest_field_issues: List[Dict[str, Any]] = []
        self._project_fixed_keys: set[str] = set()
        self._eta_seconds: Optional[float] = None
        self._eta_sample_count: int = 0
        self._eta_chip_text = "ETA: unknown"
        self._eta_chip_tooltip = "No historical duration data available yet."
        self._suspend_draft_events = False
        self._update_summary_widgets()
        QTimer.singleShot(0, self._apply_equal_widths)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_equal_widths()

    def _apply_equal_widths(self) -> None:
        margins = self._root_layout.contentsMargins()
        available_width = max(int(self.width() - margins.left() - margins.right()), 1)
        self.command_header.apply_responsive_layout(available_width)

        body_total = max(available_width, 1)
        body_spacing = max(int(self._body_layout.spacing()), 0)
        right_width = max((body_total - body_spacing) // 3, 1)
        left_width = max(body_total - body_spacing - right_width, 1)
        self._left_panel.setMaximumWidth(left_width)
        self._right_panel.setMinimumWidth(right_width)
        self._right_panel.setMaximumWidth(right_width)

    def _emit_draft_changed(self) -> None:
        if self._suspend_draft_events:
            return
        self._update_summary_widgets()
        self.draft_changed.emit(self._payload(include_name=False))

    def set_preview_busy(self, busy: bool) -> None:
        self.preview_panel.set_busy(bool(busy))

    def set_preview_error(self, message: str) -> None:
        self.preview_panel.set_error_message(str(message or "Preview generation failed."))

    def set_preview_mesh(self, path: str) -> None:
        self.preview_panel.set_preview_mesh(str(path))

    def set_preview_parameters(self, parameters: Dict[str, Any]) -> None:
        self.preview_panel.set_preview_parameters(dict(parameters or {}))

    def set_project_fixed_keys(self, keys: List[str]) -> None:
        self._project_fixed_keys = {str(item) for item in list(keys or []) if str(item).strip()}
        self.parameter_form.set_project_fixed_keys(sorted(self._project_fixed_keys))
        self._update_summary_widgets()

    def highlight_policy_missing_keys(self, keys: List[str]) -> List[str]:
        return self.parameter_form.highlight_policy_missing_keys(list(keys or []))

    def clear_policy_missing_highlights(self) -> None:
        self.parameter_form.clear_manual_highlights()

    def apply_policy_defaults(self, defaults: Dict[str, Any]) -> None:
        self._suspend_draft_events = True
        try:
            self.parameter_form.apply_default_values(dict(defaults or {}))
        finally:
            self._suspend_draft_events = False
        self._emit_draft_changed()

    def set_policy_default_suggestions(self, defaults: Dict[str, Any]) -> None:
        self.parameter_form.set_policy_default_suggestions(dict(defaults or {}))

    def set_eta(self, eta_seconds: Optional[float], *, sample_count: int, median_seconds: Optional[float]) -> None:
        self._eta_seconds = eta_seconds
        self._eta_sample_count = max(int(sample_count), 0)
        if eta_seconds is None:
            self._eta_chip_text = "ETA: unknown"
            self._eta_chip_tooltip = "No historical duration data available yet."
        else:
            total = max(float(eta_seconds), 0.0)
            minutes = int(total // 60)
            seconds = int(round(total - (minutes * 60)))
            if minutes > 0:
                text = f"ETA: ~{minutes}m {seconds:02d}s"
            else:
                text = f"ETA: ~{seconds}s"
            self._eta_chip_text = text
            median_hint = "unknown" if median_seconds is None else f"{float(median_seconds):.1f}s/version"
            self._eta_chip_tooltip = (
                f"Estimated from historical median ({median_hint}) across {self._eta_sample_count} successful versions."
            )
        self._update_summary_widgets()

    def apply_compatibility(self, state: Dict[str, Any]) -> None:
        self._compat_state = dict(state)
        self.parameter_form.apply_compatibility(state)
        self.compat_panel.update_state(state)
        self._update_summary_widgets()

    def apply_ui_risks(self, issues: List[Dict[str, Any]]) -> None:
        self._latest_field_issues = [dict(item) for item in list(issues or []) if isinstance(item, dict)]
        self.parameter_form.apply_ui_risks(self._latest_field_issues)
        self._update_summary_widgets()

    def _payload(self, *, include_name: bool = True) -> Dict[str, object]:
        selected = self.parameter_form.selected_params_payload()
        sweeps = self.parameter_form.sweeps_payload()

        visible = set(str(item) for item in list(self._compat_state.get("visible_keys", []) or []))
        locked = set(str(item) for item in list(self._compat_state.get("locked_keys", []) or []))
        sweepable = set(str(item) for item in list(self._compat_state.get("sweepable_keys", []) or []))
        if visible or self._project_fixed_keys:
            selected = {
                key: value
                for key, value in selected.items()
                if (not visible or str(key) in visible)
                and str(key) not in locked
                and str(key) not in self._project_fixed_keys
            }
        if sweepable:
            sweeps = {
                key: value
                for key, value in sweeps.items()
                if str(key) in sweepable and str(key) not in locked and str(key) not in self._project_fixed_keys
            }

        payload: Dict[str, object] = {
            "sweep_mode": self.export_panel.sweep_mode_value(),
            "selected_params": selected,
            "sweeps": sweeps,
            "sim_export_params": self.export_panel.sim_export_params_payload(),
        }
        if include_name:
            payload["batch_name"] = self.batch_name.text().strip()
        return payload

    def reset_draft(self) -> None:
        self._suspend_draft_events = True
        try:
            self.batch_name.clear()
            self.export_panel.set_sweep_mode("single")
            self.parameter_form.set_selected_params({})
            self.parameter_form.set_sweeps({})
            self.parameter_form.set_policy_default_suggestions({})
            self.export_panel.set_from_payload({})
            self.set_eta(None, sample_count=0, median_seconds=None)
            self.preview_panel.set_busy(False)
            self.preview_panel.set_preview_parameters({})
            self.preview_panel.set_info_message("No preview mesh loaded.")
        finally:
            self._suspend_draft_events = False
        self._emit_draft_changed()

    def load_from_batch(self, batch: Batch, *, batch_name: Optional[str] = None) -> None:
        self._suspend_draft_events = True
        try:
            name = batch_name
            if not name:
                name = str(batch.extra.get("batch_name", batch.batch_id))
            self.batch_name.setText(name)
            mode = str(batch.sweep_mode or "single")
            self.export_panel.set_sweep_mode(mode if mode in {"single", "combined"} else "single")
            self.parameter_form.set_from_batch(batch)
            self.export_panel.set_from_batch(batch)
        finally:
            self._suspend_draft_events = False
        self._emit_draft_changed()

    def _update_summary_widgets(self) -> None:
        visible_count = len(self.parameter_form.visible_field_keys())
        active_sweeps = int(self.parameter_form.active_sweep_count())
        version_preview = int(self._compat_state.get("version_count_preview", 0) or 0)
        export_specs = int(self.export_panel.export_spec_count())
        selected = self.parameter_form.selected_params_payload()
        mode = self.export_panel.sweep_mode_value()

        issues = list(self._latest_field_issues or self.compat_panel.issues())
        fatal_count = 0
        warn_count = 0
        incomplete_count = 0
        for issue in issues:
            severity = str(issue.get("severity", "")).lower()
            if severity == "warn":
                warn_count += 1
                continue
            if severity != "fatal":
                continue
            issue_key = str(issue.get("field_key") or issue.get("key") or "").strip()
            ui_severity = classify_ui_severity(issue, field_is_set=bool(selected.get(issue_key) is not None))
            if ui_severity == "incomplete":
                incomplete_count += 1
            else:
                fatal_count += 1
        def _issue_rank(raw: Dict[str, Any]) -> tuple[int, str]:
            sev = str(raw.get("severity", "")).strip().lower()
            if sev == "fatal":
                return (0, str(raw.get("message", "")))
            if sev == "warn":
                return (1, str(raw.get("message", "")))
            if sev == "incomplete":
                return (2, str(raw.get("message", "")))
            return (3, str(raw.get("message", "")))

        sorted_issues = sorted([dict(item) for item in issues], key=_issue_rank)

        issue_lines: List[str] = []
        for issue in sorted_issues:
            msg = str(issue.get("message", "")).strip()
            if not msg:
                continue
            issue_lines.append(msg)
        estimate_chips = [
            self._eta_chip_text,
            f"Visible vars: {visible_count}",
            f"Active sweeps: {active_sweeps}",
            f"Export specs: {export_specs}",
        ]
        if len(str(mode)) <= 10:
            estimate_chips.append(f"Mode: {mode}")
        estimate_chips.append(f"Versions: {version_preview}")
        self.command_header.set_estimate_chips(estimate_chips[:6])
        self.command_header.set_issue_state(
            messages=issue_lines,
            fatal_count=fatal_count,
            warn_count=warn_count,
            incomplete_count=incomplete_count,
        )

        has_name = bool(self.batch_name.text().strip())
        can_save = has_name
        # Keep run button interactive once a name is present; run-time validation
        # dialog explains blockers/default options without silently disabling action.
        can_run = has_name
        self.save_btn.setEnabled(can_save)
        self.run_btn.setEnabled(can_run)
        if not has_name:
            self.save_btn.setToolTip("Provide a batch name first.")
        elif fatal_count > 0:
            self.save_btn.setToolTip("Resolve fatal validation issues before saving.")
        else:
            self.save_btn.setToolTip("Save current batch configuration")
        if not has_name:
            self.run_btn.setToolTip("Provide a batch name first.")
        elif incomplete_count > 0:
            self.run_btn.setToolTip("Undefined policy parameters will be offered with defaults on run.")
        elif fatal_count > 0:
            self.run_btn.setToolTip("Resolve fatal validation issues before running.")
        else:
            self.run_btn.setToolTip("Run simulation batch with current configuration")
        run_ready = bool(has_name and fatal_count == 0 and incomplete_count == 0)
        self.run_btn.setProperty("runReady", "true" if run_ready else "false")
        self.run_btn.style().unpolish(self.run_btn)
        self.run_btn.style().polish(self.run_btn)


class RunPage(QWidget):
    back_to_dashboard = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(0)
        root.addStretch(1)

        shell = QFrame()
        shell.setObjectName("RunScreenShell")
        shell.setMaximumWidth(860)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(24, 20, 24, 20)
        shell_layout.setSpacing(12)

        title = QLabel("RUN")
        title.setObjectName("PageTitle")
        shell_layout.addWidget(title, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.hint_label = QLabel(
            "AKABAK/VACS are driven via UI automation. This screen stays in front until the run finishes."
        )
        self.hint_label.setObjectName("SummaryText")
        self.hint_label.setWordWrap(True)
        shell_layout.addWidget(self.hint_label)

        self.progress = QProgressBar()
        self.progress.setObjectName("RunProgressBar")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(12)
        shell_layout.addWidget(self.progress)

        self.version_label = QLabel("Version 0/0")
        self.version_label.setObjectName("SummaryMeta")
        self.mode_label = QLabel("Mode: --")
        self.mode_label.setObjectName("SummaryMeta")
        self.eta_label = QLabel("ETA: --")
        self.eta_label.setObjectName("SummaryMeta")
        shell_layout.addWidget(self.version_label)
        shell_layout.addWidget(self.mode_label)
        shell_layout.addWidget(self.eta_label)
        shell_layout.addSpacing(6)

        self.back_btn = QPushButton("Back to Dashboard")
        self.back_btn.setObjectName("BatchSecondaryButton")
        self.back_btn.setEnabled(False)
        self.back_btn.clicked.connect(self.back_to_dashboard.emit)
        shell_layout.addWidget(self.back_btn, 0, Qt.AlignRight)

        root.addWidget(shell, 0, Qt.AlignHCenter | Qt.AlignVCenter)
        root.addStretch(1)

    def set_running_state(self) -> None:
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.version_label.setText("Version 0/0")
        self.mode_label.setText("Mode: running...")
        self.eta_label.setText("ETA: calculating...")
        self.back_btn.setEnabled(False)

    def set_background_mode(self, enabled: bool) -> None:
        if enabled:
            self.hint_label.setText(
                "AKABAK/VACS are driven via UI automation. This screen stays in front until the run finishes."
            )
        else:
            self.hint_label.setText(
                "AKABAK/VACS are driven via UI automation. Background mode is disabled; tool windows may come to front."
            )

    def set_finished_state(self, *, version_count: int, dry_run: bool) -> None:
        count = max(int(version_count), 0)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setTextVisible(True)
        self.format_progress_label()
        self.version_label.setText(f"Version {count}/{count}")
        self.mode_label.setText("Mode: dry-run" if dry_run else "Mode: real")
        self.eta_label.setText("ETA: done")
        self.back_btn.setEnabled(True)

    def set_failed_state(self) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Run failed")
        self.mode_label.setText("Mode: failed")
        self.eta_label.setText("ETA: --")
        self.back_btn.setEnabled(True)

    def format_progress_label(self) -> None:
        self.progress.setFormat("Run complete")


class AnalysePage(QWidget):
    COL_RUN_ID = 0
    COL_VERSION = 1
    COL_PLANES = 2
    COL_FREQ_COUNT = 3
    COL_ANGLE_COUNT = 4
    COL_NORM_ANGLE = 5
    COL_SCORE = 6
    COL_B_PC = 7
    COL_E_BW = 8
    COL_E_COV = 9
    COL_R_SPILL = 10
    COL_FLAGS = 11
    COL_IMPORTED_AT = 12
    COL_CREATED_AT = 13

    def __init__(self, *, service: OrchestratorService) -> None:
        super().__init__()
        self.service = service
        self._project_context_id: Optional[str] = None
        self._selector_sync_guard = False
        self._control_sync_guard = False
        self._run_selector_sync_guard = False
        self._metadata_request_id = 0
        self._metadata_thread: Optional[QThread] = None
        self._metadata_worker: Optional[_AnalyzerMetadataWorker] = None
        self._compute_request_id = 0
        self._compute_thread: Optional[QThread] = None
        self._compute_worker: Optional[_AnalyzerKpiComputeWorker] = None
        self._plot_request_id = 0
        self._plot_thread: Optional[QThread] = None
        self._plot_worker: Optional[_AnalyzerPlotWorker] = None
        self._compare_plot_request_id = 0
        self._compare_plot_thread: Optional[QThread] = None
        self._compare_plot_worker: Optional[_AnalyzerComparePlotWorker] = None
        self._autopick_request_id = 0
        self._autopick_thread: Optional[QThread] = None
        self._autopick_worker: Optional[_AnalyzerAutoPickWorker] = None
        self._all_run_rows: List[Dict[str, Any]] = []
        self._compare_candidates: List[Dict[str, Any]] = []
        self._compare_plot_items: List[Dict[str, Any]] = []
        self._compare_last_strategy = "A"
        self._compare_last_kpi_key = "score"
        self._compare_exclude_flags = True
        self._compare_exclude_missing = True
        self._loaded_analysis_id: Optional[str] = None
        self._selected_compare_slot_index: Optional[int] = None
        self._selected_detail_payload: Dict[str, Any] = {}
        self._ath_visible_param_keys: List[str] = []
        self._ath_visible_pref_key = "ath_visible_params"
        self._version_pin_pref_key = "version_pins_v1"
        self._pinned_version_tokens: set[str] = set()
        self._ath_all_param_rows_by_version: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        self._version_note_max_chars = 200
        self._note_sync_guard = False
        self._pin_sync_guard = False
        self._pending_note_context: Optional[Tuple[str, str, str]] = None
        self._pending_note_text = ""
        self._use_full_angles_for_smoothness = False
        self._show_mirrored_minus6_contour = False
        self._latest_plot_payload: Dict[str, Any] = {}
        self._explorer_stage_panels: Dict[str, Dict[str, Any]] = {}
        self._compare_stage_panels: Dict[str, Dict[str, Any]] = {}
        self._compare_overlay_curve_key = "beamwidth"
        self._compare_kpi_columns: List[Tuple[str, str]] = list(COMPARE_DEFAULT_KPI_COLUMNS)
        self._ath_visible_param_limit = 5
        self._active_plane = "H"
        self._analyzer_controls_row_min_height = 0
        self._plane_buttons: Dict[str, QToolButton] = {}
        self._plot_debounce_timer = QTimer(self)
        self._plot_debounce_timer.setSingleShot(True)
        self._plot_debounce_timer.setInterval(220)
        self._plot_debounce_timer.timeout.connect(self._start_plot_request)
        self._compare_plot_debounce_timer = QTimer(self)
        self._compare_plot_debounce_timer.setSingleShot(True)
        self._compare_plot_debounce_timer.setInterval(220)
        self._compare_plot_debounce_timer.timeout.connect(self._start_compare_plot_request)
        self._note_save_timer = QTimer(self)
        self._note_save_timer.setSingleShot(True)
        self._note_save_timer.setInterval(450)
        self._note_save_timer.timeout.connect(self._persist_pending_version_note)

        presets = self.service.analyzer_presets()
        self._coverage_presets = [dict(item) for item in list(presets.get("coverage_presets", []) or []) if isinstance(item, dict)]
        self._band_presets = [dict(item) for item in list(presets.get("band_presets", []) or []) if isinstance(item, dict)]
        raw_stage_presets = {
            normalize_stage_id(str(key)): dict(value)
            for key, value in dict(presets.get("stages", STAGE_PRESETS) or STAGE_PRESETS).items()
        }
        self._stage_presets = {}
        for stage_id in STAGE_ORDER:
            stage_payload = dict(raw_stage_presets.get(stage_id) or STAGE_PRESETS.get(stage_id, {}))
            stage_payload["label"] = str(stage_payload.get("label") or stage_id.title())
            self._stage_presets[stage_id] = stage_payload
        self._default_stage_id = normalize_stage_id(str(presets.get("default_stage_id") or DEFAULT_STAGE_ID))
        self._default_coverage_preset_id = str(
            presets.get("default_coverage_preset_id") or DEFAULT_COVERAGE_PRESET_ID
        ).strip() or DEFAULT_COVERAGE_PRESET_ID
        self._default_band_preset_id = str(presets.get("default_band_preset_id") or DEFAULT_BAND_PRESET_ID).strip() or DEFAULT_BAND_PRESET_ID
        self._default_tol_deg = float(presets.get("default_tol_deg") or DEFAULT_TOL_DEG)
        self._algo_version = str(presets.get("algo_version") or ALGO_VERSION)
        self._plot_cache = AnalyzerPlotCache(self._cache_policy_from_settings())

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 14)
        root.setSpacing(8)

        self.header_row = QWidget()
        self.header_row.setObjectName("AnalyzerHeaderRow")
        header_layout = QHBoxLayout(self.header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel("ANALYZER")
        title.setObjectName("PageTitle")
        header_layout.addWidget(title, 0, Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addStretch(1)
        source_label = QLabel("Data source")
        source_label.setObjectName("SummaryMeta")
        header_layout.addWidget(source_label, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.source_selector = QComboBox()
        self.source_selector.setObjectName("AnalyzerDataSourceCombo")
        self.source_selector.addItem("Project", "project")
        self.source_selector.addItem("Global", "global")
        self.source_selector.setToolTip("Choose metadata source database.")
        header_layout.addWidget(self.source_selector, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("BatchSecondaryButton")
        self.refresh_btn.setToolTip("Reload Analyzer metadata.")
        header_layout.addWidget(self.refresh_btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        root.addWidget(self.header_row)

        self.controls_panel = QFrame()
        self.controls_panel.setObjectName("ProjectSummaryPanel")
        controls = QGridLayout(self.controls_panel)
        controls.setContentsMargins(10, 8, 10, 8)
        controls.setHorizontalSpacing(10)
        controls.setVerticalSpacing(6)

        self.stage_selector = QComboBox()
        self.stage_selector.setObjectName("AnalyzerStageCombo")
        for stage_id in STAGE_ORDER:
            stage = dict(self._stage_presets.get(stage_id, {}) or {})
            self.stage_selector.addItem(str(stage.get("label") or stage_id.title()), stage_id)
        self.target_selector = QComboBox()
        self.target_selector.setObjectName("AnalyzerTargetPresetCombo")
        for preset in self._coverage_presets:
            preset_id = str(preset.get("id") or "").strip()
            label = str(preset.get("label") or preset_id)
            self.target_selector.addItem(label, preset_id)
        self.tol_spin = QDoubleSpinBox()
        self.tol_spin.setObjectName("AnalyzerToleranceSpin")
        self.tol_spin.setRange(0.5, 30.0)
        self.tol_spin.setDecimals(1)
        self.tol_spin.setValue(float(self._default_tol_deg))
        self.band_selector = QComboBox()
        self.band_selector.setObjectName("AnalyzerBandPresetCombo")
        for preset in self._band_presets:
            preset_id = str(preset.get("id") or "").strip()
            label = str(preset.get("label") or preset_id)
            self.band_selector.addItem(label, preset_id)

        self.custom_band_widget = QWidget()
        custom_band_row = QHBoxLayout(self.custom_band_widget)
        custom_band_row.setContentsMargins(0, 0, 0, 0)
        custom_band_row.setSpacing(6)
        self.custom_band_low_spin = QDoubleSpinBox()
        self.custom_band_low_spin.setObjectName("AnalyzerBandLowSpin")
        self.custom_band_low_spin.setProperty("analyzerBandEdge", True)
        self.custom_band_low_spin.setRange(20.0, 100000.0)
        self.custom_band_low_spin.setDecimals(0)
        self.custom_band_low_spin.setValue(200.0)
        self.custom_band_high_spin = QDoubleSpinBox()
        self.custom_band_high_spin.setObjectName("AnalyzerBandHighSpin")
        self.custom_band_high_spin.setProperty("analyzerBandEdge", True)
        self.custom_band_high_spin.setRange(20.0, 100000.0)
        self.custom_band_high_spin.setDecimals(0)
        self.custom_band_high_spin.setValue(16000.0)
        custom_band_row.addWidget(QLabel("Low"))
        custom_band_row.addWidget(self.custom_band_low_spin)
        custom_band_row.addWidget(QLabel("High"))
        custom_band_row.addWidget(self.custom_band_high_spin)

        self.heatmap_clamp_check = QCheckBox("Clamp heatmap")
        self.heatmap_clamp_check.setObjectName("AnalyzerHeatmapClampCheck")
        self.heatmap_clamp_check.setChecked(True)
        self.heatmap_clamp_min_spin = QDoubleSpinBox()
        self.heatmap_clamp_min_spin.setObjectName("AnalyzerHeatmapClampMinSpin")
        self.heatmap_clamp_min_spin.setRange(-60.0, -20.0)
        self.heatmap_clamp_min_spin.setDecimals(1)
        self.heatmap_clamp_min_spin.setValue(-20.0)

        self.exclude_flagged_check = QToolButton()
        self.exclude_flagged_check.setText("Exclude flagged")
        self.exclude_flagged_check.setCheckable(True)
        self.exclude_flagged_check.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.exclude_flagged_check.setObjectName("AnalyzerExcludeFlaggedCheck")
        self.exclude_flagged_check.setProperty("analyzerToggle", True)
        controls.addWidget(self.exclude_flagged_check, 0, 0, 1, 2)
        self.exclude_warnings_check = QToolButton()
        self.exclude_warnings_check.setText("Exclude warnings")
        self.exclude_warnings_check.setCheckable(True)
        self.exclude_warnings_check.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.exclude_warnings_check.setObjectName("AnalyzerExcludeWarningsCheck")
        self.exclude_warnings_check.setProperty("analyzerToggle", True)
        controls.addWidget(self.exclude_warnings_check, 0, 2, 1, 2)
        controls.addWidget(QLabel("Min score"), 0, 4, Qt.AlignLeft | Qt.AlignVCenter)
        self.min_score_spin = QDoubleSpinBox()
        self.min_score_spin.setObjectName("AnalyzerMinScoreSpin")
        self.min_score_spin.setRange(0.0, 100.0)
        self.min_score_spin.setDecimals(1)
        self.min_score_spin.setValue(0.0)
        controls.addWidget(self.min_score_spin, 0, 5)

        self.compute_btn = QPushButton("Refresh KPIs")
        self.compute_btn.setObjectName("AnalyzerComputeKpisButton")
        self.compute_btn.setToolTip("Compute or refresh KPI scalars for the selected batch.")
        controls.addWidget(self.compute_btn, 0, 6, 1, 1)
        root.addWidget(self.controls_panel)

        self.compute_row = QWidget()
        compute_row_layout = QHBoxLayout(self.compute_row)
        compute_row_layout.setContentsMargins(0, 0, 0, 0)
        compute_row_layout.setSpacing(8)
        self.compute_progress = QProgressBar()
        self.compute_progress.setObjectName("AnalyzerComputeProgress")
        self.compute_progress.setVisible(False)
        self.compute_cancel_btn = QPushButton("Cancel")
        self.compute_cancel_btn.setObjectName("BatchSecondaryButton")
        self.compute_cancel_btn.setVisible(False)
        compute_row_layout.addWidget(self.compute_progress, 1)
        compute_row_layout.addWidget(self.compute_cancel_btn, 0)
        root.addWidget(self.compute_row)

        self.loading_label = QLabel("Ready.")
        self.loading_label.setObjectName("SummaryMeta")
        self.loading_label.setVisible(False)
        root.addWidget(self.loading_label, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.error_label = QLabel("")
        self.error_label.setObjectName("BatchValidationHint")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("AnalyzerSplitter")
        self.splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.selector_panel = QFrame()
        self.selector_panel.setObjectName("ProjectSummaryPanel")
        selector_layout = QFormLayout(self.selector_panel)
        selector_layout.setContentsMargins(10, 8, 10, 8)
        selector_layout.setSpacing(6)
        self.project_selector = QComboBox()
        self.project_selector.setObjectName("AnalyzerProjectCombo")
        self.project_selector.setToolTip("Project filtered to rows with polar measurements.")
        self.batch_selector = QComboBox()
        self.batch_selector.setObjectName("AnalyzerBatchCombo")
        self.batch_selector.setToolTip("Batches containing imported polar measurements.")
        selector_layout.addRow("Project", self.project_selector)
        selector_layout.addRow("Batch", self.batch_selector)
        left_layout.addWidget(self.selector_panel, 0)

        self.run_table = QTableWidget(0, 14)
        self.run_table.setObjectName("AnalyzerRunTable")
        self.run_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.run_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.run_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.run_table.setSortingEnabled(True)
        self.run_table.setAlternatingRowColors(False)
        self.run_table.setHorizontalHeaderLabels(
            [
                "Batch/Version",
                "Version",
                "Planes",
                "freq_count",
                "angle_count",
                "norm_angle_deg",
                "Score",
                "B_PC (oct)",
                "E_BW (deg)",
                "E_cov (dB)",
                "R_spill",
                "Flags",
                "imported_at",
                "created_at",
            ]
        )
        header = self.run_table.horizontalHeader()
        header.setSectionResizeMode(self.COL_RUN_ID, QHeaderView.Stretch)
        for idx in range(1, 14):
            header.setSectionResizeMode(idx, QHeaderView.ResizeToContents)
        left_layout.addWidget(self.run_table, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.details_panel = QFrame()
        self.details_panel.setObjectName("ProjectSummaryPanel")
        details_layout = QFormLayout(self.details_panel)
        details_layout.setContentsMargins(10, 8, 10, 8)
        details_layout.setSpacing(6)
        self._detail_labels: Dict[str, QLabel] = {}
        for key, label_text in (
            ("run_id", "Run ID"),
            ("version_id", "Version"),
            ("project_id", "Project"),
            ("batch_id", "Batch"),
            ("planes", "Planes"),
            ("freq_count", "freq_count"),
            ("angle_count", "angle_count"),
            ("norm_angle_deg", "norm_angle_deg"),
            ("norm_angle_note", "norm_angle_note"),
            ("score", "score"),
            ("b_pc_oct", "B_PC (oct)"),
            ("e_bw", "E_BW (deg)"),
            ("e_cov", "E_cov (dB)"),
            ("r_spill", "R_spill"),
            ("flags", "flags"),
            ("kpi_reason_codes", "kpi_reason_codes"),
            ("imported_at", "imported_at"),
            ("created_at", "created_at"),
            ("source_files", "source_files"),
            ("file_hashes", "file_hash"),
        ):
            value = QLabel("--")
            value.setObjectName("SummaryMeta")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._detail_labels[key] = value
            details_layout.addRow(label_text, value)
        right_layout.addWidget(self.details_panel, 0)

        self.context_bar = QFrame()
        self.context_bar.setObjectName("ProjectSummaryPanel")
        context_layout = QGridLayout(self.context_bar)
        context_layout.setContentsMargins(10, 8, 10, 8)
        context_layout.setHorizontalSpacing(8)
        context_layout.setVerticalSpacing(6)
        context_layout.addWidget(QLabel("Stage"), 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        context_layout.addWidget(self.stage_selector, 0, 1)
        context_layout.addWidget(QLabel("Target"), 0, 2, Qt.AlignLeft | Qt.AlignVCenter)
        context_layout.addWidget(self.target_selector, 0, 3)
        context_layout.addWidget(QLabel("Band"), 0, 4, Qt.AlignLeft | Qt.AlignVCenter)
        context_layout.addWidget(self.band_selector, 0, 5)
        context_layout.addWidget(self.custom_band_widget, 0, 6)
        context_layout.addWidget(QLabel("Tol (+/-deg)"), 0, 7, Qt.AlignLeft | Qt.AlignVCenter)
        context_layout.addWidget(self.tol_spin, 0, 8)
        context_layout.addWidget(self.heatmap_clamp_check, 1, 0, 1, 2)
        context_layout.addWidget(QLabel("Clamp min dB"), 1, 2, Qt.AlignLeft | Qt.AlignVCenter)
        context_layout.addWidget(self.heatmap_clamp_min_spin, 1, 3)

        plane_box = QWidget()
        plane_layout = QHBoxLayout(plane_box)
        plane_layout.setContentsMargins(0, 0, 0, 0)
        plane_layout.setSpacing(4)
        plane_layout.addWidget(QLabel("Plane"), 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.plane_group = QButtonGroup(self)
        self.plane_group.setExclusive(True)
        for plane_key in ("H", "V", "D"):
            btn = QToolButton()
            btn.setObjectName(f"AnalyzerPlane{plane_key}Button")
            btn.setText(plane_key)
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setProperty("analyzerPlaneToggle", True)
            if plane_key == "H":
                btn.setProperty("analyzerPlaneSegment", "first")
            elif plane_key == "D":
                btn.setProperty("analyzerPlaneSegment", "last")
            else:
                btn.setProperty("analyzerPlaneSegment", "middle")
            self.plane_group.addButton(btn)
            self._plane_buttons[plane_key] = btn
            plane_layout.addWidget(btn, 0, Qt.AlignLeft | Qt.AlignVCenter)
        plane_layout.addStretch(1)
        context_layout.addWidget(plane_box, 1, 4, 1, 3)

        self.plot_loading_label = QLabel("Select version + plane for Explorer plots.")
        self.plot_loading_label.setObjectName("SummaryMeta")
        self.plot_cancel_btn = QPushButton("Cancel")
        self.plot_cancel_btn.setObjectName("BatchSecondaryButton")
        self.plot_cancel_btn.setVisible(False)
        self.plot_cancel_btn.setEnabled(False)
        plot_cancel_policy = self.plot_cancel_btn.sizePolicy()
        plot_cancel_policy.setRetainSizeWhenHidden(True)
        self.plot_cancel_btn.setSizePolicy(plot_cancel_policy)
        context_layout.addWidget(self.plot_loading_label, 1, 7, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
        context_layout.addWidget(self.plot_cancel_btn, 1, 8, 1, 1, Qt.AlignRight | Qt.AlignVCenter)
        right_layout.addWidget(self.context_bar, 0)

        self.analysis_tabs = QTabWidget()
        self.analysis_tabs.setObjectName("AnalyzerPlotTabs")

        self.explorer_tab = QWidget()
        explorer_layout = QVBoxLayout(self.explorer_tab)
        explorer_layout.setContentsMargins(4, 4, 4, 4)
        explorer_layout.setSpacing(8)
        self.explorer_grid_widget = QWidget()
        self.explorer_grid_widget.setObjectName("AnalyzerExplorerGrid")
        self.explorer_grid_layout = QGridLayout(self.explorer_grid_widget)
        self.explorer_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.explorer_grid_layout.setHorizontalSpacing(ANALYZER_PLOT_STYLE.tile_gap_px)
        self.explorer_grid_layout.setVerticalSpacing(ANALYZER_PLOT_STYLE.tile_gap_px)
        self._explorer_stage_panels = {}
        for idx, slot in enumerate(("A", "B", "C", "D")):
            panel = self._create_stage_plot_panel(
                panel_id=f"Explorer{slot}",
                title=f"Plot {slot}",
                help_text="Stage plot panel.",
                kind="curve" if slot != "A" else "heatmap",
            )
            self._explorer_stage_panels[slot] = panel
            self.explorer_grid_layout.addWidget(panel["frame"], idx // 2, idx % 2, 1, 1)
        self.explorer_grid_layout.setColumnStretch(0, 1)
        self.explorer_grid_layout.setColumnStretch(1, 1)
        self.explorer_grid_layout.setRowStretch(0, 1)
        self.explorer_grid_layout.setRowStretch(1, 1)
        self.heatmap_canvas = self._explorer_stage_panels["A"]["heatmap_canvas"]
        self.beamwidth_canvas = self._explorer_stage_panels["B"]["curve_canvas"]
        explorer_layout.addWidget(self.explorer_grid_widget, 1)
        self.analysis_tabs.addTab(self.explorer_tab, "Explorer")

        self.compare_tab = QWidget()
        compare_layout = QVBoxLayout(self.compare_tab)
        compare_layout.setContentsMargins(6, 6, 6, 6)
        compare_layout.setSpacing(8)

        self.compare_splitter = QSplitter(Qt.Horizontal)
        self.compare_splitter.setObjectName("AnalyzerCompareSplitter")
        self.compare_splitter.setChildrenCollapsible(False)

        compare_left_content = QWidget()
        compare_left_content.setObjectName("AnalyzerCompareLeftContent")
        compare_left_layout = QVBoxLayout(compare_left_content)
        compare_left_layout.setContentsMargins(0, 0, 0, 0)
        compare_left_layout.setSpacing(8)

        self.compare_controls = QFrame()
        self.compare_controls.setObjectName("ProjectSummaryPanel")
        compare_controls_layout = QGridLayout(self.compare_controls)
        compare_controls_layout.setContentsMargins(10, 8, 10, 8)
        compare_controls_layout.setHorizontalSpacing(8)
        compare_controls_layout.setVerticalSpacing(6)
        self.compare_add_selected_btn = QPushButton("Add selected")
        self.compare_add_selected_btn.setObjectName("BatchSecondaryButton")
        self.compare_auto_pick_btn = QPushButton("Auto-pick...")
        self.compare_auto_pick_btn.setObjectName("BatchSecondaryButton")
        self.compare_save_btn = QPushButton("Save Analysis...")
        self.compare_save_btn.setObjectName("BatchSecondaryButton")
        self.compare_analysis_selector = QComboBox()
        self.compare_analysis_selector.setObjectName("AnalyzerAnalysisSelector")
        self.compare_load_btn = QPushButton("Load")
        self.compare_load_btn.setObjectName("BatchSecondaryButton")
        self.compare_cancel_btn = QPushButton("Cancel")
        self.compare_cancel_btn.setObjectName("BatchSecondaryButton")
        self.compare_cancel_btn.setVisible(False)
        self.compare_cancel_btn.setEnabled(False)
        compare_cancel_policy = self.compare_cancel_btn.sizePolicy()
        compare_cancel_policy.setRetainSizeWhenHidden(True)
        self.compare_cancel_btn.setSizePolicy(compare_cancel_policy)
        self.compare_plane_combo = QComboBox()
        self.compare_plane_combo.setObjectName("AnalyzerComparePlaneCombo")
        self.compare_plane_combo.addItem("H", "H")
        self.compare_plane_combo.addItem("V", "V")
        self.compare_plane_combo.addItem("D", "D")
        compare_controls_layout.addWidget(self.compare_add_selected_btn, 0, 0)
        compare_controls_layout.addWidget(self.compare_auto_pick_btn, 0, 1)
        compare_controls_layout.addWidget(self.compare_save_btn, 0, 2)
        compare_controls_layout.addWidget(QLabel("Saved"), 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        compare_controls_layout.addWidget(self.compare_analysis_selector, 1, 1, 1, 2)
        compare_controls_layout.addWidget(self.compare_load_btn, 1, 3)
        compare_controls_layout.addWidget(self.compare_cancel_btn, 1, 4)
        self.compare_notice = ElidedTitleLabel("Select up to 5 versions, then add or auto-pick top candidates.")
        self.compare_notice.setObjectName("SummaryMeta")
        self.compare_notice.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.compare_notice.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        compare_controls_layout.addWidget(self.compare_notice, 2, 0, 1, 5)
        compare_left_layout.addWidget(self.compare_controls, 0)

        self.compare_slots_table = QTableWidget(5, 1)
        self.compare_slots_table.setObjectName("AnalyzerCompareSlotsTable")
        self.compare_slots_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.compare_slots_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.compare_slots_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.compare_slots_table.setWordWrap(False)
        self.compare_slots_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.compare_slots_table.verticalHeader().setVisible(False)
        compare_left_layout.addWidget(self.compare_slots_table, 1)
        self._configure_compare_slots_table()

        compare_left_scroll = QScrollArea()
        compare_left_scroll.setObjectName("AnalyzerCompareLeftScroll")
        compare_left_scroll.setFrameShape(QFrame.NoFrame)
        compare_left_scroll.setWidgetResizable(True)
        compare_left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        compare_left_scroll.setWidget(compare_left_content)
        compare_left_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        compare_left_scroll.setMinimumWidth(240)
        compare_left_scroll.setMaximumWidth(360)
        self.compare_splitter.addWidget(compare_left_scroll)

        compare_right = QWidget()
        compare_right.setObjectName("AnalyzerCompareRightPanel")
        compare_right_layout = QVBoxLayout(compare_right)
        compare_right_layout.setContentsMargins(0, 0, 0, 0)
        compare_right_layout.setSpacing(8)

        compare_top_row = QWidget()
        compare_top_layout = QHBoxLayout(compare_top_row)
        compare_top_layout.setContentsMargins(0, 0, 0, 0)
        compare_top_layout.setSpacing(6)
        compare_top_layout.addWidget(QLabel("Overlay plane"), 0, Qt.AlignLeft | Qt.AlignVCenter)
        compare_top_layout.addWidget(self.compare_plane_combo, 0)
        compare_top_layout.addWidget(QLabel("Heatmap candidate"), 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.compare_heatmap_selector = QComboBox()
        self.compare_heatmap_selector.setObjectName("AnalyzerCompareHeatmapSelector")
        self.compare_heatmap_selector.setToolTip(
            "Choose which candidate heatmap is shown; beamwidth remains overlaid."
        )
        compare_top_layout.addWidget(self.compare_heatmap_selector, 0)
        compare_top_layout.addStretch(1)
        compare_right_layout.addWidget(compare_top_row, 0)
        compare_top_row.setVisible(False)
        compare_top_row.setMaximumHeight(0)
        self.compare_plane_combo.setVisible(False)
        self.compare_heatmap_selector.setVisible(False)

        self.compare_grid_widget = QWidget()
        self.compare_grid_widget.setObjectName("AnalyzerCompareGrid")
        self.compare_grid_layout = QGridLayout(self.compare_grid_widget)
        self.compare_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.compare_grid_layout.setHorizontalSpacing(ANALYZER_PLOT_STYLE.tile_gap_px)
        self.compare_grid_layout.setVerticalSpacing(ANALYZER_PLOT_STYLE.tile_gap_px)

        self.compare_overlay_panel = self._create_stage_plot_panel(
            panel_id="CompareA",
            title="Beamwidth Overlay (-6 dB)",
            help_text="Overlay of shortlisted candidate key curves across frequency.",
            kind="curve",
        )
        self.compare_overlay_canvas = self.compare_overlay_panel["curve_canvas"]
        self.compare_overlay_canvas.setObjectName("AnalyzerCompareOverlayCanvas")
        self.compare_overlay_title_label = self.compare_overlay_panel["title_label"]
        self.compare_overlay_help_btn = self.compare_overlay_panel["help_btn"]
        self.compare_grid_layout.addWidget(self.compare_overlay_panel["frame"], 0, 1, 1, 1)

        self.compare_heatmap_panel = self._create_stage_plot_panel(
            panel_id="CompareB",
            title="Polar Heatmap",
            help_text="Single-candidate heatmap view (select C1..C5 above).",
            kind="heatmap",
        )
        self.compare_heatmap_canvas = self.compare_heatmap_panel["heatmap_canvas"]
        self.compare_heatmap_canvas.setObjectName("AnalyzerCompareHeatmapCanvas")
        self.compare_grid_layout.addWidget(self.compare_heatmap_panel["frame"], 0, 0, 1, 1)

        self.compare_focus_panel = self._create_stage_plot_panel(
            panel_id="CompareC",
            title="Active Candidate Curve",
            help_text="Focused view for the currently active shortlist candidate.",
            kind="curve",
        )
        self.compare_focus_canvas = self.compare_focus_panel["curve_canvas"]
        self.compare_focus_canvas.setObjectName("AnalyzerCompareFocusCanvas")
        self.compare_grid_layout.addWidget(self.compare_focus_panel["frame"], 1, 0, 1, 1)

        self.compare_pareto_panel = self._create_stage_plot_panel(
            panel_id="CompareD",
            title="Pareto Scatter",
            help_text="Scatter view for shortlist KPI trade-offs. Configure axes in panel header.",
            kind="pareto",
        )
        self.compare_pareto_title_label = self.compare_pareto_panel["title_label"]
        self.compare_pareto_help_btn = self.compare_pareto_panel["help_btn"]
        self.compare_pareto_canvas = self.compare_pareto_panel["pareto_canvas"]
        self.compare_pareto_axis_row = QWidget()
        pareto_axis_layout = QHBoxLayout(self.compare_pareto_axis_row)
        pareto_axis_layout.setContentsMargins(0, 0, 0, 0)
        pareto_axis_layout.setSpacing(4)
        pareto_axis_layout.addWidget(QLabel("X"), 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.compare_pareto_x_combo = QComboBox()
        self.compare_pareto_x_combo.setObjectName("AnalyzerCompareParetoXCombo")
        pareto_axis_layout.addWidget(self.compare_pareto_x_combo, 1)
        pareto_axis_layout.addWidget(QLabel("Y"), 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.compare_pareto_y_combo = QComboBox()
        self.compare_pareto_y_combo.setObjectName("AnalyzerCompareParetoYCombo")
        pareto_axis_layout.addWidget(self.compare_pareto_y_combo, 1)
        for key, label in PARETO_AXIS_OPTIONS:
            self.compare_pareto_x_combo.addItem(label, key)
            self.compare_pareto_y_combo.addItem(label, key)
        header_layout = self.compare_pareto_panel["header_layout"]
        if isinstance(header_layout, QHBoxLayout):
            header_layout.addWidget(self.compare_pareto_axis_row, 0)
        self.compare_grid_layout.addWidget(self.compare_pareto_panel["frame"], 1, 1, 1, 1)
        self._compare_stage_panels = {
            "A": self.compare_heatmap_panel,
            "B": self.compare_overlay_panel,
            "C": self.compare_focus_panel,
            "D": self.compare_pareto_panel,
        }

        self.compare_grid_layout.setColumnStretch(0, 1)
        self.compare_grid_layout.setColumnStretch(1, 1)
        self.compare_grid_layout.setRowStretch(0, 1)
        self.compare_grid_layout.setRowStretch(1, 1)
        compare_right_layout.addWidget(self.compare_grid_widget, 1)

        self.compare_table = QTableWidget(0, 7)
        self.compare_table.setObjectName("AnalyzerCompareTable")
        self.compare_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.compare_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.compare_table.setHorizontalHeaderLabels(["Slot", "Score", "B_PC", "E_BW", "E_cov", "R_spill", "Flags"])
        compare_header = self.compare_table.horizontalHeader()
        compare_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for idx in range(1, 7):
            compare_header.setSectionResizeMode(idx, QHeaderView.ResizeToContents)
        self.compare_table.setVisible(False)

        compare_right.setMinimumWidth(0)
        compare_right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.compare_splitter.addWidget(compare_right)
        self.compare_splitter.setStretchFactor(0, 0)
        self.compare_splitter.setStretchFactor(1, 1)
        self.compare_splitter.setSizes([300, 900])
        compare_layout.addWidget(self.compare_splitter, 1)
        self.analysis_tabs.addTab(self.compare_tab, "Compare")

        right_layout.addWidget(self.analysis_tabs, 1)

        left.setMinimumWidth(360)
        right.setMinimumWidth(460)
        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 6)
        root.addWidget(self.splitter, 1)

        self.analyzer_toolbar = QFrame()
        self.analyzer_toolbar.setObjectName("ProjectSummaryPanel")
        toolbar_layout = QHBoxLayout(self.analyzer_toolbar)
        toolbar_layout.setContentsMargins(10, 4, 10, 4)
        toolbar_layout.setSpacing(8)
        self.scope_chip = QLabel("Scope: Project")
        self.scope_chip.setObjectName("SummaryMeta")
        self.scope_chip.setVisible(False)

        self.batch_selector.setMinimumWidth(220)
        self.batch_selector.setMaximumWidth(480)
        self.batch_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.batch_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)

        self.selection_left_box = QWidget()
        left_box_layout = QHBoxLayout(self.selection_left_box)
        left_box_layout.setContentsMargins(0, 0, 0, 0)
        left_box_layout.setSpacing(0)
        left_box_layout.addWidget(self.batch_selector, 1, Qt.AlignLeft | Qt.AlignVCenter)

        self.selection_center_box = QWidget()
        center_box_layout = QHBoxLayout(self.selection_center_box)
        center_box_layout.setContentsMargins(0, 0, 0, 0)
        center_box_layout.setSpacing(4)
        self.version_prev_btn = QToolButton()
        self.version_prev_btn.setObjectName("AnalyzerVersionPrevButton")
        self.version_prev_btn.setText("<")
        self.version_prev_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.version_prev_btn.setProperty("analyzerAction", True)
        self.version_prev_btn.setMinimumHeight(24)
        self.version_prev_btn.setMaximumHeight(24)
        self.version_prev_btn.setFixedWidth(30)
        center_box_layout.addWidget(self.version_prev_btn, 0, Qt.AlignVCenter)
        self.versions_btn = ElidedToolButton("B---/V---")
        self.versions_btn.setObjectName("AnalyzerVersionsButton")
        self.versions_btn.setToolTip("Select version")
        self.versions_btn.setMinimumWidth(260)
        self.versions_btn.setMaximumWidth(440)
        self.versions_btn.setMinimumHeight(24)
        self.versions_btn.setMaximumHeight(24)
        self.versions_btn.setProperty("analyzerAction", True)
        center_box_layout.addWidget(self.versions_btn, 1, Qt.AlignVCenter)
        self.version_next_btn = QToolButton()
        self.version_next_btn.setObjectName("AnalyzerVersionNextButton")
        self.version_next_btn.setText(">")
        self.version_next_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.version_next_btn.setProperty("analyzerAction", True)
        self.version_next_btn.setMinimumHeight(24)
        self.version_next_btn.setMaximumHeight(24)
        self.version_next_btn.setFixedWidth(30)
        center_box_layout.addWidget(self.version_next_btn, 0, Qt.AlignVCenter)

        self.selection_right_box = QWidget()
        right_box_layout = QHBoxLayout(self.selection_right_box)
        right_box_layout.setContentsMargins(0, 0, 0, 0)
        right_box_layout.setSpacing(6)
        right_box_layout.addStretch(1)

        self.run_selector = QComboBox()
        self.run_selector.setObjectName("AnalyzerRunSelector")
        self.run_selector.setMinimumWidth(220)
        self.run_selector.setMaximumWidth(520)
        self.run_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.run_selector.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        self.run_selector.setVisible(False)
        self.compute_btn.setMinimumHeight(24)
        self.compute_btn.setMaximumHeight(24)
        self.compute_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.compute_btn.setProperty("analyzerAction", True)
        self.run_details_btn = QPushButton("Version Details")
        self.run_details_btn.setObjectName("BatchSecondaryButton")
        self.run_details_btn.setMinimumHeight(24)
        self.run_details_btn.setMaximumHeight(24)
        right_box_layout.addWidget(self.run_details_btn, 0, Qt.AlignVCenter)
        right_box_layout.addWidget(self.compute_btn, 0, Qt.AlignVCenter)

        toolbar_layout.addWidget(self.selection_left_box, 1, Qt.AlignLeft | Qt.AlignVCenter)
        toolbar_layout.addWidget(self.selection_center_box, 0, Qt.AlignHCenter | Qt.AlignVCenter)
        toolbar_layout.addWidget(self.selection_right_box, 1, Qt.AlignRight | Qt.AlignVCenter)

        self.run_summary_run_chip = ElidedTitleLabel("Selection: --", parent=self)
        self.run_summary_run_chip.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.run_summary_run_chip.setMinimumWidth(150)
        self.run_summary_run_chip.setObjectName("SummaryMeta")
        self.run_summary_run_chip.setVisible(False)
        self.run_summary_run_chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.run_summary_planes_chip = ElidedTitleLabel("Planes: --", parent=self)
        self.run_summary_planes_chip.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.run_summary_planes_chip.setMinimumWidth(86)
        self.run_summary_planes_chip.setObjectName("SummaryMeta")
        self.run_summary_planes_chip.setVisible(False)
        self.run_summary_planes_chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.run_summary_score_chip = ElidedTitleLabel("Score: --", parent=self)
        self.run_summary_score_chip.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.run_summary_score_chip.setMinimumWidth(96)
        self.run_summary_score_chip.setObjectName("SummaryMeta")
        self.run_summary_score_chip.setVisible(False)
        self.run_summary_score_chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.run_summary_flags_chip = ElidedTitleLabel("Flags: --", parent=self)
        self.run_summary_flags_chip.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.run_summary_flags_chip.setMinimumWidth(88)
        self.run_summary_flags_chip.setObjectName("SummaryMeta")
        self.run_summary_flags_chip.setVisible(False)
        self.run_summary_flags_chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.flags_help_btn = QToolButton(self)
        self.flags_help_btn.setObjectName("AnalyzerFlagsHelpButton")
        self.flags_help_btn.setText("")
        self.flags_help_btn.setIcon(QIcon(":/icons/settings.svg"))
        self.flags_help_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.flags_help_btn.setAutoRaise(True)
        self.flags_help_btn.setIconSize(QSize(14, 14))
        self.flags_help_btn.setToolTip("Show reason severities and recommended actions for current flags.")
        self.flags_help_btn.setMinimumHeight(24)
        self.flags_help_btn.setMaximumHeight(24)
        self.flags_help_btn.setMinimumWidth(24)
        self.flags_help_btn.setMaximumWidth(24)
        self.flags_help_btn.setProperty("analyzerAction", True)

        self.analyzer_controls_row = QFrame()
        self.analyzer_controls_row.setObjectName("ProjectSummaryPanel")
        self.analyzer_controls_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        controls_row_layout = QHBoxLayout(self.analyzer_controls_row)
        controls_row_layout.setContentsMargins(8, 4, 8, 4)
        controls_row_layout.setSpacing(6)

        self.analysis_controls_tile = QFrame()
        self.analysis_controls_tile.setObjectName("ProjectSummaryPanel")
        self.analysis_controls_tile.setProperty("analyzerSurface", "1")
        self.analysis_controls_tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        analysis_controls_layout = QGridLayout(self.analysis_controls_tile)
        analysis_controls_layout.setContentsMargins(8, 4, 8, 4)
        analysis_controls_layout.setHorizontalSpacing(4)
        analysis_controls_layout.setVerticalSpacing(2)
        analysis_title = QLabel("Analysis")
        analysis_title.setObjectName("SummaryMeta")
        analysis_title.setProperty("analyzerBlockTitle", True)
        analysis_title.setMinimumHeight(20)
        analysis_controls_layout.addWidget(analysis_title, 0, 0, 1, 4, Qt.AlignLeft | Qt.AlignVCenter)
        analysis_controls_layout.addWidget(QLabel("Stage"), 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
        analysis_controls_layout.addWidget(self.stage_selector, 1, 1)
        analysis_controls_layout.addWidget(QLabel("Target"), 1, 2, Qt.AlignLeft | Qt.AlignVCenter)
        analysis_controls_layout.addWidget(self.target_selector, 1, 3)
        analysis_controls_layout.addWidget(QLabel("Min score"), 2, 0, Qt.AlignLeft | Qt.AlignVCenter)
        analysis_controls_layout.addWidget(self.min_score_spin, 2, 1)
        analysis_filter_row = QWidget()
        analysis_filter_row_layout = QHBoxLayout(analysis_filter_row)
        analysis_filter_row_layout.setContentsMargins(0, 0, 0, 0)
        analysis_filter_row_layout.setSpacing(4)
        analysis_filter_row_layout.addWidget(self.exclude_flagged_check, 0, Qt.AlignLeft | Qt.AlignVCenter)
        analysis_filter_row_layout.addWidget(self.exclude_warnings_check, 0, Qt.AlignLeft | Qt.AlignVCenter)
        analysis_filter_row_layout.addStretch(1)
        analysis_controls_layout.addWidget(analysis_filter_row, 3, 0, 1, 4)
        analysis_controls_layout.setColumnStretch(0, 0)
        analysis_controls_layout.setColumnStretch(1, 1)
        analysis_controls_layout.setColumnStretch(2, 0)
        analysis_controls_layout.setColumnStretch(3, 1)
        controls_row_layout.addWidget(self.analysis_controls_tile, 1, Qt.AlignVCenter)

        self.kpi_controls_tile = QFrame()
        self.kpi_controls_tile.setObjectName("ProjectSummaryPanel")
        self.kpi_controls_tile.setProperty("analyzerSurface", "2")
        self.kpi_controls_tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        kpi_controls_layout = QVBoxLayout(self.kpi_controls_tile)
        kpi_controls_layout.setContentsMargins(8, 4, 8, 4)
        kpi_controls_layout.setSpacing(4)
        kpi_title = QLabel("Version Information")
        kpi_title.setObjectName("SummaryMeta")
        kpi_title.setProperty("analyzerBlockTitle", True)
        kpi_title.setMinimumHeight(20)
        kpi_controls_layout.addWidget(kpi_title, 0, Qt.AlignLeft | Qt.AlignVCenter)

        version_info_body = QWidget()
        version_info_body_layout = QHBoxLayout(version_info_body)
        version_info_body_layout.setContentsMargins(0, 0, 0, 0)
        version_info_body_layout.setSpacing(6)

        self.version_info_scores_col = QWidget()
        self.version_info_scores_col.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.version_info_scores_col.setMinimumWidth(170)
        self.version_info_scores_col.setMaximumWidth(220)
        scores_layout = QGridLayout(self.version_info_scores_col)
        scores_layout.setContentsMargins(6, 4, 6, 4)
        scores_layout.setHorizontalSpacing(4)
        scores_layout.setVerticalSpacing(3)
        self._version_info_metric_labels: Dict[str, QLabel] = {}
        self._version_info_metric_rows: List[Dict[str, Any]] = []
        metric_value_font = QFont()
        metric_value_font.setStyleHint(QFont.Monospace)
        metric_value_font.setFixedPitch(True)
        default_metric_keys = list(
            VERSION_INFO_STAGE_METRICS.get(
                DEFAULT_STAGE_ID,
                ("score", "b_pc_oct", "e_bw", "e_cov", "r_spill", "flags"),
            )
        )
        for row_idx, metric_key in enumerate(default_metric_keys):
            meta = dict(VERSION_INFO_METRIC_META.get(str(metric_key), {}) or {})
            label = QLabel(str(meta.get("label") or str(metric_key)))
            label.setObjectName("SummaryMeta")
            tip = str(meta.get("tip") or "")
            label.setToolTip(tip)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            label.setMinimumWidth(66)
            label.setMaximumWidth(88)
            value = QLabel("--")
            value.setObjectName("SummaryMeta")
            value.setProperty("analyzerMetricValue", True)
            value.setWordWrap(False)
            value.setToolTip(tip)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setFont(metric_value_font)
            value.setMinimumWidth(58)
            value.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
            self._version_info_metric_labels[f"row_{row_idx}"] = value
            self._version_info_metric_rows.append(
                {
                    "metric_key": str(metric_key),
                    "key_label": label,
                    "value_label": value,
                }
            )
            scores_layout.addWidget(label, row_idx, 0, Qt.AlignLeft | Qt.AlignVCenter)
            scores_layout.addWidget(value, row_idx, 1)
        scores_layout.setColumnStretch(0, 0)
        scores_layout.setColumnStretch(1, 0)
        version_info_body_layout.addWidget(self.version_info_scores_col, 1)
        scores_divider = QFrame()
        scores_divider.setObjectName("AnalyzerInfoDivider")
        scores_divider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        version_info_body_layout.addWidget(scores_divider, 0)

        self.version_info_extra_col = QWidget()
        extra_layout = QHBoxLayout(self.version_info_extra_col)
        extra_layout.setContentsMargins(6, 4, 6, 4)
        extra_layout.setSpacing(8)

        self.version_info_col1 = QWidget()
        self.version_info_col1.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.version_info_col1.setMinimumWidth(160)
        self.version_info_col1.setMaximumWidth(200)
        col1_layout = QVBoxLayout(self.version_info_col1)
        col1_layout.setContentsMargins(0, 0, 0, 0)
        col1_layout.setSpacing(3)
        self.version_dims_label = ElidedTitleLabel("--")
        self.version_dims_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.version_dims_label.setObjectName("SummaryMeta")
        self.version_dims_label.setToolTip("Final dimensions (L x W x H) in mm.")
        col1_layout.addWidget(self.version_dims_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self._version_chip_labels: Dict[str, QLabel] = {}
        for key in ("throat", "gcurve", "morph", "driver", "enclosure"):
            chip = QLabel("--")
            chip.setObjectName("SummaryMeta")
            chip.setWordWrap(False)
            chip.setToolTip("Not available from DB yet.")
            self._version_chip_labels[key] = chip
            col1_layout.addWidget(chip, 0, Qt.AlignLeft | Qt.AlignVCenter)
        col1_layout.addStretch(1)
        extra_layout.addWidget(self.version_info_col1, 1)
        divider_1 = QFrame()
        divider_1.setObjectName("AnalyzerInfoDivider")
        divider_1.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        extra_layout.addWidget(divider_1, 0)

        self.version_info_col2 = QWidget()
        self.version_info_col2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        col2_layout = QVBoxLayout(self.version_info_col2)
        col2_layout.setContentsMargins(0, 0, 0, 0)
        col2_layout.setSpacing(3)
        self.version_sweep_value_label = ElidedTitleLabel("--")
        self.version_sweep_value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.version_sweep_value_label.setObjectName("SummaryMeta")
        self.version_sweep_value_label.setProperty("analyzerSweepChip", True)
        self.version_sweep_value_label.setMinimumWidth(180)
        self.version_sweep_value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        col2_layout.addWidget(self.version_sweep_value_label, 0)
        self.version_ath_params_rows_widget = QWidget()
        ath_rows_layout = QGridLayout(self.version_ath_params_rows_widget)
        ath_rows_layout.setContentsMargins(0, 0, 0, 0)
        ath_rows_layout.setHorizontalSpacing(6)
        ath_rows_layout.setVerticalSpacing(3)
        self._version_ath_param_key_labels: List[QLabel] = []
        self._version_ath_param_value_labels: List[ElidedTitleLabel] = []
        for idx in range(int(self._ath_visible_param_limit)):
            key_label = QLabel("--")
            key_label.setObjectName("SummaryMeta")
            key_label.setProperty("analyzerInfoKey", True)
            key_label.setWordWrap(False)
            key_label.setVisible(False)
            value_label = ElidedTitleLabel("--")
            value_label.setObjectName("SummaryMeta")
            value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            value_label.setProperty("analyzerInfoValue", True)
            value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            value_label.setVisible(False)
            self._version_ath_param_key_labels.append(key_label)
            self._version_ath_param_value_labels.append(value_label)
            ath_rows_layout.addWidget(key_label, idx, 0, Qt.AlignLeft | Qt.AlignVCenter)
            ath_rows_layout.addWidget(value_label, idx, 1)
        ath_rows_layout.setColumnStretch(0, 0)
        ath_rows_layout.setColumnStretch(1, 1)
        self.version_ath_params_empty_label = ElidedTitleLabel("ATH params: --")
        self.version_ath_params_empty_label.setObjectName("SummaryMeta")
        self.version_ath_params_empty_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.version_ath_params_empty_label.setVisible(True)
        col2_layout.addWidget(self.version_ath_params_rows_widget, 1, Qt.AlignLeft | Qt.AlignTop)
        col2_layout.addWidget(self.version_ath_params_empty_label, 0, Qt.AlignLeft | Qt.AlignTop)
        extra_layout.addWidget(self.version_info_col2, 1)
        divider_2 = QFrame()
        divider_2.setObjectName("AnalyzerInfoDivider")
        divider_2.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        extra_layout.addWidget(divider_2, 0)

        self.version_info_col3 = QWidget()
        self.version_info_col3.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.version_info_col3.setMinimumWidth(220)
        col3_layout = QVBoxLayout(self.version_info_col3)
        col3_layout.setContentsMargins(0, 0, 0, 0)
        col3_layout.setSpacing(3)
        col3_title = QLabel("Notes")
        col3_title.setObjectName("SummaryMeta")
        col3_title.setProperty("analyzerBlockTitle", True)
        col3_layout.addWidget(col3_title, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.version_note_edit = QTextEdit()
        self.version_note_edit.setObjectName("AnalyzerVersionNoteEdit")
        self.version_note_edit.setAcceptRichText(False)
        self.version_note_edit.setPlaceholderText("Short note for this B###/V### selection...")
        self.version_note_edit.setMaximumHeight(62)
        col3_layout.addWidget(self.version_note_edit, 1)
        self.version_note_counter = QLabel(f"{self._version_note_max_chars} left")
        self.version_note_counter.setObjectName("SummaryMeta")
        self.version_note_counter.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        col3_layout.addWidget(self.version_note_counter, 0)
        self.version_info_buttons_row = QWidget()
        buttons_row_layout = QHBoxLayout(self.version_info_buttons_row)
        buttons_row_layout.setContentsMargins(0, 0, 0, 0)
        buttons_row_layout.setSpacing(4)
        buttons_row_layout.addWidget(self.flags_help_btn, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.version_pin_btn = QToolButton(self)
        self.version_pin_btn.setObjectName("AnalyzerVersionPinButton")
        self.version_pin_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.version_pin_btn.setCheckable(True)
        self.version_pin_btn.setAutoRaise(False)
        self.version_pin_btn.setMinimumSize(24, 24)
        self.version_pin_btn.setMaximumSize(24, 24)
        self.version_pin_btn.setProperty("analyzerAction", True)
        buttons_row_layout.addWidget(self.version_pin_btn, 0, Qt.AlignLeft | Qt.AlignVCenter)
        buttons_row_layout.addStretch(1)
        col3_layout.addWidget(self.version_info_buttons_row, 0)
        extra_layout.addWidget(self.version_info_col3, 1)
        extra_layout.setStretch(0, 0)
        extra_layout.setStretch(1, 1)
        extra_layout.setStretch(2, 0)

        version_info_body_layout.addWidget(self.version_info_extra_col, 3)
        version_info_body_layout.setStretch(0, 1)
        version_info_body_layout.setStretch(1, 0)
        version_info_body_layout.setStretch(2, 3)
        kpi_controls_layout.addWidget(version_info_body, 1)
        controls_row_layout.addWidget(self.kpi_controls_tile, 2)

        self.display_controls_tile = QFrame()
        self.display_controls_tile.setObjectName("ProjectSummaryPanel")
        self.display_controls_tile.setProperty("analyzerSurface", "1")
        self.display_controls_tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        display_controls_layout = QGridLayout(self.display_controls_tile)
        display_controls_layout.setContentsMargins(8, 4, 8, 4)
        display_controls_layout.setHorizontalSpacing(4)
        display_controls_layout.setVerticalSpacing(2)
        display_title = QLabel("Display")
        display_title.setObjectName("SummaryMeta")
        display_title.setProperty("analyzerBlockTitle", True)
        display_title.setMinimumHeight(20)
        display_controls_layout.addWidget(display_title, 0, 0, 1, 4, Qt.AlignLeft | Qt.AlignVCenter)
        self.x_axis_scale_combo = QComboBox()
        self.x_axis_scale_combo.setObjectName("AnalyzerXAxisScaleCombo")
        self.x_axis_scale_combo.addItem("Log", "log")
        self.x_axis_scale_combo.addItem("Linear", "linear")
        self.norm_mode_combo = QComboBox()
        self.norm_mode_combo.setObjectName("AnalyzerNormalizationModeCombo")
        self.norm_mode_combo.addItem("Relative (0 deg ref)", "relative_zero")
        self.norm_mode_combo.addItem("Absolute (raw dB)", "absolute")
        self.norm_angle_selector = QComboBox()
        self.norm_angle_selector.setObjectName("AnalyzerNormAngleCombo")
        self.norm_angle_selector.addItem("0 deg", "0")
        self.norm_angle_selector.addItem("10 deg", "10")
        self.norm_angle_selector.setEnabled(False)
        self.norm_angle_selector.setToolTip(
            "Normalization angle switching is disabled: current plot engine normalizes to nearest 0 deg from data."
        )
        self.raw_bins_check = QCheckBox("Show raw bins")
        self.raw_bins_check.setObjectName("AnalyzerRawBinsCheck")
        self.raw_bins_check.setChecked(False)
        self.display_advanced_btn = QPushButton("Advanced...")
        self.display_advanced_btn.setObjectName("BatchSecondaryButton")
        self.display_advanced_btn.setMinimumHeight(24)
        self.display_advanced_btn.setMaximumHeight(24)
        self.band_selector.setToolTip("Affects plotted range and KPI computation window.")
        self.tol_spin.setToolTip("Affects plotted range and KPI computation window.")
        self.display_slot_frames: List[QFrame] = []
        display_split_row = QWidget()
        display_split_layout = QHBoxLayout(display_split_row)
        display_split_layout.setContentsMargins(0, 0, 0, 0)
        display_split_layout.setSpacing(6)

        band_frame = QFrame()
        band_frame.setObjectName("AnalyzerDisplaySlotFrame")
        band_layout = QGridLayout(band_frame)
        band_layout.setContentsMargins(6, 4, 6, 4)
        band_layout.setHorizontalSpacing(4)
        band_layout.setVerticalSpacing(2)
        band_layout.addWidget(QLabel("Band"), 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        band_layout.addWidget(self.band_selector, 0, 1)
        self.custom_band_low_label = QLabel("Low")
        self.custom_band_high_label = QLabel("High")
        self.custom_band_low_label.setProperty("analyzerBandEdgeLabel", True)
        self.custom_band_high_label.setProperty("analyzerBandEdgeLabel", True)
        band_layout.addWidget(self.custom_band_low_label, 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
        band_layout.addWidget(self.custom_band_low_spin, 1, 1)
        band_layout.addWidget(self.custom_band_high_label, 2, 0, Qt.AlignLeft | Qt.AlignVCenter)
        band_layout.addWidget(self.custom_band_high_spin, 2, 1)
        band_layout.setColumnStretch(0, 0)
        band_layout.setColumnStretch(1, 1)
        display_split_layout.addWidget(band_frame, 1)
        self.display_slot_frames.append(band_frame)

        plane_frame = QFrame()
        plane_frame.setObjectName("AnalyzerDisplaySlotFrame")
        plane_layout = QGridLayout(plane_frame)
        plane_layout.setContentsMargins(6, 4, 6, 4)
        plane_layout.setHorizontalSpacing(4)
        plane_layout.setVerticalSpacing(2)
        plane_box = QWidget()
        plane_box_layout = QHBoxLayout(plane_box)
        plane_box_layout.setContentsMargins(0, 0, 0, 0)
        plane_box_layout.setSpacing(0)
        for plane_key in ("H", "V", "D"):
            btn = self._plane_buttons.get(plane_key)
            if btn is not None:
                plane_box_layout.addWidget(btn, 0, Qt.AlignLeft | Qt.AlignVCenter)
        plane_box_layout.addStretch(1)
        plane_layout.addWidget(QLabel("Plane"), 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        plane_layout.addWidget(plane_box, 0, 1, 1, 2)
        plane_layout.addWidget(self.display_advanced_btn, 1, 2, Qt.AlignRight | Qt.AlignVCenter)
        plane_layout.setColumnStretch(0, 0)
        plane_layout.setColumnStretch(1, 1)
        plane_layout.setColumnStretch(2, 0)
        display_split_layout.addWidget(plane_frame, 1)
        self.display_slot_frames.append(plane_frame)

        display_split_layout.setStretch(0, 1)
        display_split_layout.setStretch(1, 1)
        display_controls_layout.addWidget(display_split_row, 1, 0, 1, 4)
        display_controls_layout.addWidget(self.plot_cancel_btn, 2, 3, 1, 1, Qt.AlignRight | Qt.AlignVCenter)
        display_controls_layout.setColumnStretch(0, 1)
        display_controls_layout.setColumnStretch(1, 1)
        display_controls_layout.setColumnStretch(2, 1)
        display_controls_layout.setColumnStretch(3, 0)
        controls_row_layout.addWidget(self.display_controls_tile, 1, Qt.AlignVCenter)
        controls_row_layout.setStretch(0, 1)
        controls_row_layout.setStretch(1, 2)
        controls_row_layout.setStretch(2, 1)

        self.analysis_mode_row = QFrame()
        self.analysis_mode_row.setObjectName("ProjectSummaryPanel")
        mode_row_layout = QHBoxLayout(self.analysis_mode_row)
        mode_row_layout.setContentsMargins(10, 4, 10, 4)
        mode_row_layout.setSpacing(6)
        self.analysis_mode_group = QButtonGroup(self)
        self.analysis_mode_group.setExclusive(True)
        self.analysis_explorer_btn = QToolButton()
        self.analysis_explorer_btn.setObjectName("ModeBarButton")
        self.analysis_explorer_btn.setText("Explorer")
        self.analysis_explorer_btn.setCheckable(True)
        self.analysis_compare_btn = QToolButton()
        self.analysis_compare_btn.setObjectName("ModeBarButton")
        self.analysis_compare_btn.setText("Compare")
        self.analysis_compare_btn.setCheckable(True)
        self.analysis_mode_group.addButton(self.analysis_explorer_btn)
        self.analysis_mode_group.addButton(self.analysis_compare_btn)
        mode_row_layout.addWidget(self.analysis_explorer_btn, 0)
        mode_row_layout.addWidget(self.analysis_compare_btn, 0)
        mode_row_layout.addStretch(1)

        root.insertWidget(0, self.analyzer_toolbar)
        root.insertWidget(1, self.analyzer_controls_row)
        root.insertWidget(2, self.analysis_mode_row)
        self.header_row.setVisible(False)
        self.controls_panel.setVisible(False)
        self.selector_panel.setVisible(False)
        self.details_panel.setVisible(False)
        self.context_bar.setVisible(False)

        self.splitter.setSizes([0, 1600])
        self.splitter.widget(0).setMinimumWidth(0)
        self.splitter.widget(0).setMaximumWidth(0)
        self.analysis_tabs.tabBar().setExpanding(True)
        self.analysis_tabs.tabBar().setMinimumHeight(34)
        self.analysis_tabs.tabBar().setVisible(False)

        self.compute_btn.clicked.connect(self._start_kpi_compute)
        self.compute_cancel_btn.clicked.connect(self._cancel_kpi_compute)
        self.project_selector.currentIndexChanged.connect(self._on_project_changed)
        self.batch_selector.currentIndexChanged.connect(self._on_batch_changed)
        self.batch_selector.currentIndexChanged.connect(self._sync_batch_selector_tooltip)
        self.run_table.itemSelectionChanged.connect(self._on_run_selection_changed)
        self.run_selector.currentIndexChanged.connect(self._on_run_selector_changed)
        self.versions_btn.clicked.connect(self._open_version_picker)
        self.version_prev_btn.clicked.connect(lambda: self._step_selected_version(-1))
        self.version_next_btn.clicked.connect(lambda: self._step_selected_version(1))
        self.flags_help_btn.clicked.connect(self._open_flags_help_dialog)
        self.run_details_btn.clicked.connect(self._open_run_details_dialog)
        self.version_pin_btn.toggled.connect(self._on_version_pin_toggled)
        self.version_note_edit.textChanged.connect(self._on_version_note_text_changed)
        self.stage_selector.currentIndexChanged.connect(self._on_stage_changed)
        self.target_selector.currentIndexChanged.connect(self._on_kpi_config_changed)
        self.tol_spin.valueChanged.connect(self._on_kpi_config_changed)
        self.band_selector.currentIndexChanged.connect(self._on_band_preset_changed)
        self.custom_band_low_spin.valueChanged.connect(self._on_kpi_config_changed)
        self.custom_band_high_spin.valueChanged.connect(self._on_kpi_config_changed)
        self.x_axis_scale_combo.currentIndexChanged.connect(self._on_plot_config_changed)
        self.norm_mode_combo.currentIndexChanged.connect(self._on_plot_config_changed)
        self.raw_bins_check.toggled.connect(self._on_plot_config_changed)
        self.display_advanced_btn.clicked.connect(self._open_display_advanced_dialog)
        self.heatmap_clamp_check.toggled.connect(self._on_plot_config_changed)
        self.heatmap_clamp_min_spin.valueChanged.connect(self._on_plot_config_changed)
        self.exclude_flagged_check.toggled.connect(self._refresh_run_table)
        self.exclude_warnings_check.toggled.connect(self._refresh_run_table)
        self.min_score_spin.valueChanged.connect(self._refresh_run_table)
        self.plot_cancel_btn.clicked.connect(self._cancel_plot_request)
        self.analysis_tabs.currentChanged.connect(self._on_analysis_tab_changed)
        self.analysis_explorer_btn.clicked.connect(lambda: self.analysis_tabs.setCurrentWidget(self.explorer_tab))
        self.analysis_compare_btn.clicked.connect(lambda: self.analysis_tabs.setCurrentWidget(self.compare_tab))
        self.compare_add_selected_btn.clicked.connect(self._on_compare_add_selected)
        self.compare_auto_pick_btn.clicked.connect(self._open_compare_autopick_dialog)
        self.compare_save_btn.clicked.connect(self._save_compare_analysis)
        self.compare_load_btn.clicked.connect(self._load_selected_analysis)
        self.compare_plane_combo.currentIndexChanged.connect(self._schedule_compare_plot_refresh)
        self.compare_heatmap_selector.currentIndexChanged.connect(self._render_compare_heatmap_selection)
        self.compare_pareto_x_combo.currentIndexChanged.connect(self._render_compare_pareto)
        self.compare_pareto_y_combo.currentIndexChanged.connect(self._render_compare_pareto)
        self.compare_slots_table.itemSelectionChanged.connect(self._on_compare_slot_selection_changed)
        self.compare_cancel_btn.clicked.connect(self._cancel_compare_operations)
        for plane_key, button in self._plane_buttons.items():
            button.toggled.connect(lambda checked, key=plane_key: self._on_plane_toggled(key, checked))
        self._control_sync_guard = True
        self._set_combo_current_by_data(self.stage_selector, self._default_stage_id)
        self._set_combo_current_by_data(self.target_selector, self._default_coverage_preset_id)
        self._set_combo_current_by_data(self.band_selector, self._default_band_preset_id)
        self._control_sync_guard = False
        if "H" in self._plane_buttons:
            self._plane_buttons["H"].setChecked(True)
        self.reload_cache_settings()
        self._sync_band_custom_visibility()
        self._apply_stage_defaults()
        self._apply_stage_plot_layout()
        QTimer.singleShot(0, self._sync_side_tile_heights)
        self.compute_btn.setEnabled(self._source_key() == "project")
        self._set_details(None)
        self.run_selector.addItem("(no versions)", "")
        self.run_selector.setEnabled(False)
        self.run_details_btn.setEnabled(False)
        self.version_pin_btn.setEnabled(False)
        self._refresh_version_pin_button(enabled=False, pinned=False)
        self.flags_help_btn.setEnabled(False)
        self.version_note_edit.setEnabled(False)
        self._update_version_note_counter(remaining=self._version_note_max_chars)
        self._sync_batch_selector_tooltip()
        self._sync_version_stepper()
        self._sync_selection_action_button_sizes()
        self._clear_plot_views("Select version + plane to render plots.")
        self._refresh_saved_analyses()
        self._update_compare_slots()
        self.analysis_explorer_btn.setChecked(True)
        self._update_toolbar_context_chips()
        self._update_toolbar_compaction()

    def _create_stage_plot_panel(
        self,
        *,
        panel_id: str,
        title: str,
        help_text: str,
        kind: str,
    ) -> Dict[str, Any]:
        frame = QFrame()
        frame.setObjectName("ProjectIssuesPanel")
        frame.setMinimumHeight(180)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(
            ANALYZER_PLOT_STYLE.tile_inner_padding_px,
            ANALYZER_PLOT_STYLE.tile_inner_padding_px,
            ANALYZER_PLOT_STYLE.tile_inner_padding_px,
            ANALYZER_PLOT_STYLE.tile_inner_padding_px,
        )
        frame_layout.setSpacing(ANALYZER_PLOT_STYLE.tile_header_spacing_px)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(ANALYZER_PLOT_STYLE.tile_header_spacing_px)
        title_label = QLabel(str(title or panel_id))
        title_label.setObjectName("SectionTitle")
        title_label.setProperty("analyzerPlotTitle", True)
        header_layout.addWidget(title_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        target_badge_label = QLabel("")
        target_badge_label.setObjectName("SummaryMeta")
        target_badge_label.setProperty("analyzerTargetBadge", True)
        target_badge_label.setVisible(False)
        header_layout.addWidget(target_badge_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        help_btn = QToolButton()
        help_btn.setObjectName("BatchSecondaryToolButton")
        help_btn.setText("")
        help_btn.setIcon(QIcon(":/icons/settings.svg"))
        help_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        help_btn.setAutoRaise(True)
        help_btn.setIconSize(QSize(14, 14))
        help_btn.setFixedSize(18, 18)
        help_btn.setToolTip(str(help_text or "Analyzer stage panel."))
        header_layout.addWidget(help_btn, 0, Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addStretch(1)
        frame_layout.addWidget(header, 0)

        stack = QStackedWidget()
        stack.setObjectName(f"AnalyzerStagePlotStack{panel_id}")
        heatmap_canvas = HeatmapCanvas()
        heatmap_canvas.setObjectName(f"AnalyzerStageHeatmapCanvas{panel_id}")
        curve_canvas = MetricCurveCanvas()
        curve_canvas.setObjectName(f"AnalyzerStageMetricCanvas{panel_id}")
        pareto_canvas = ParetoScatterCanvas()
        pareto_canvas.setObjectName(f"AnalyzerStageParetoCanvas{panel_id}")
        placeholder = QLabel("No data available for this stage panel.")
        placeholder.setObjectName("SummaryMeta")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setWordWrap(True)
        stack.addWidget(heatmap_canvas)
        stack.addWidget(curve_canvas)
        stack.addWidget(pareto_canvas)
        stack.addWidget(placeholder)
        frame_layout.addWidget(stack, 1)

        panel = {
            "panel_id": panel_id,
            "frame": frame,
            "header": header,
            "header_layout": header_layout,
            "title_label": title_label,
            "target_badge_label": target_badge_label,
            "help_btn": help_btn,
            "stack": stack,
            "heatmap_canvas": heatmap_canvas,
            "curve_canvas": curve_canvas,
            "pareto_canvas": pareto_canvas,
            "placeholder": placeholder,
            "kind": "",
            "metric_key": "",
        }
        self._set_stage_panel_kind(panel, kind)
        return panel

    @staticmethod
    def _set_stage_panel_kind(panel: Dict[str, Any], kind: str) -> None:
        token = str(kind or "curve").strip().lower()
        if token not in {"heatmap", "curve", "pareto", "placeholder"}:
            token = "curve"
        panel["kind"] = token
        stack = panel.get("stack")
        if not isinstance(stack, QStackedWidget):
            return
        if token == "heatmap":
            stack.setCurrentWidget(panel.get("heatmap_canvas"))
        elif token == "curve":
            stack.setCurrentWidget(panel.get("curve_canvas"))
        elif token == "pareto":
            stack.setCurrentWidget(panel.get("pareto_canvas"))
        else:
            stack.setCurrentWidget(panel.get("placeholder"))

    def _apply_stage_plot_layout(self) -> None:
        stage_id = self._selected_stage_id()
        layout_spec = list(STAGE_EXPLORER_LAYOUTS.get(stage_id, STAGE_EXPLORER_LAYOUTS.get(DEFAULT_STAGE_ID, [])))
        slot_order = ("A", "B", "C", "D")
        for slot, spec in zip(slot_order, layout_spec):
            panel = self._explorer_stage_panels.get(slot)
            if not isinstance(panel, dict):
                continue
            key = str(spec.get("key") or "heatmap").strip().lower()
            panel["metric_key"] = key
            title_label = panel.get("title_label")
            if isinstance(title_label, QLabel):
                title_label.setText(str(spec.get("title") or f"Plot {slot}"))
            help_btn = panel.get("help_btn")
            if isinstance(help_btn, QToolButton):
                help_btn.setToolTip(str(spec.get("help") or "Stage plot panel."))
            if key == "heatmap":
                self._set_stage_panel_kind(panel, "heatmap")
            elif key.startswith("pareto"):
                self._set_stage_panel_kind(panel, "pareto")
            else:
                self._set_stage_panel_kind(panel, "curve")
        for slot in slot_order[len(layout_spec):]:
            panel = self._explorer_stage_panels.get(slot)
            if not isinstance(panel, dict):
                continue
            panel["metric_key"] = ""
            title_label = panel.get("title_label")
            if isinstance(title_label, QLabel):
                title_label.setText(f"Plot {slot}")
            self._set_stage_panel_kind(panel, "placeholder")

        compare_layout = list(
            STAGE_COMPARE_LAYOUTS.get(stage_id, STAGE_COMPARE_LAYOUTS.get(DEFAULT_STAGE_ID, []))
        )
        compare_lookup = {
            str(spec.get("slot") or "").strip().upper(): dict(spec)
            for spec in compare_layout
            if isinstance(spec, Mapping)
        }
        compare_slot_order = ("A", "B", "C", "D")
        active_pareto_panel: Optional[Dict[str, Any]] = None
        overlay_key = str(STAGE_COMPARE_OVERLAY_KEY.get(stage_id, "beamwidth")).strip().lower() or "beamwidth"
        for slot in compare_slot_order:
            panel = self._compare_stage_panels.get(slot)
            if not isinstance(panel, dict):
                continue
            spec = dict(compare_lookup.get(slot) or {})
            key = str(spec.get("key") or "").strip().lower()
            kind = str(spec.get("kind") or "").strip().lower()
            if not key:
                key = "heatmap" if kind == "heatmap" else "beamwidth"
            if kind not in {"heatmap", "curve", "pareto", "placeholder"}:
                if key == "heatmap":
                    kind = "heatmap"
                elif key.startswith("pareto"):
                    kind = "pareto"
                else:
                    kind = "curve"
            panel["metric_key"] = key
            title_label = panel.get("title_label")
            if isinstance(title_label, QLabel):
                title_label.setText(str(spec.get("title") or f"Plot {slot}"))
            help_btn = panel.get("help_btn")
            if isinstance(help_btn, QToolButton):
                help_btn.setToolTip(str(spec.get("help") or "Compare stage plot panel."))
            self._set_stage_panel_kind(panel, kind)
            if slot == "B" and kind == "curve":
                overlay_key = key
            if kind == "pareto":
                active_pareto_panel = panel
        self._compare_overlay_curve_key = overlay_key

        if isinstance(getattr(self, "compare_overlay_title_label", None), QLabel):
            overlay_spec = dict(compare_lookup.get("B") or {})
            self.compare_overlay_title_label.setText(str(overlay_spec.get("title") or "Key Curve Compare"))
        if isinstance(getattr(self, "compare_overlay_help_btn", None), QToolButton):
            overlay_spec = dict(compare_lookup.get("B") or {})
            self.compare_overlay_help_btn.setToolTip(
                str(overlay_spec.get("help") or "Overlay of shortlisted candidate curves.")
            )

        defaults = STAGE_PARETO_DEFAULTS.get(stage_id, STAGE_PARETO_DEFAULTS.get(DEFAULT_STAGE_ID, ("e_bw", "r_spill")))
        self._set_combo_current_by_data(self.compare_pareto_x_combo, defaults[0])
        self._set_combo_current_by_data(self.compare_pareto_y_combo, defaults[1])
        if isinstance(getattr(self, "compare_pareto_axis_row", None), QWidget):
            self.compare_pareto_axis_row.setVisible(active_pareto_panel is not None)
            if active_pareto_panel is not None:
                header_layout = active_pareto_panel.get("header_layout")
                if isinstance(header_layout, QHBoxLayout):
                    header_layout.addWidget(self.compare_pareto_axis_row, 0)
        self._update_stage_target_badges()
        self._apply_plot_panel_header_theme()

    def _update_stage_target_badges(self) -> None:
        target = self._selected_target()
        badge_text = f"Target {int(round(float(target.get('h_deg') or 90.0)))}x{int(round(float(target.get('v_deg') or 40.0)))}"
        for panel in list(self._explorer_stage_panels.values()) + list(self._compare_stage_panels.values()):
            if not isinstance(panel, dict):
                continue
            badge = panel.get("target_badge_label")
            if not isinstance(badge, QLabel):
                continue
            metric_key = str(panel.get("metric_key") or "").strip().lower()
            is_heatmap = metric_key == "heatmap"
            badge.setVisible(is_heatmap)
            if is_heatmap:
                badge.setText(badge_text)
                badge.setToolTip("Active target window used for heatmap overlay.")

    def _apply_plot_panel_header_theme(self) -> None:
        all_panels = list(self._explorer_stage_panels.values()) + list(self._compare_stage_panels.values())
        for panel in all_panels:
            if not isinstance(panel, dict):
                continue
            frame = panel.get("frame")
            if not isinstance(frame, QWidget):
                continue
            theme = apply_plot_theme(frame, has_legend=False, context="header")
            title_label = panel.get("title_label")
            if isinstance(title_label, QLabel):
                title_label.setFont(_font_with_pixel_size(title_label.font(), int(theme.get("title_font_px", 11))))
            target_badge = panel.get("target_badge_label")
            if isinstance(target_badge, QLabel):
                target_badge.setFont(_font_with_pixel_size(target_badge.font(), int(theme.get("legend_font_px", 8))))
            help_btn = panel.get("help_btn")
            if isinstance(help_btn, QToolButton):
                icon_px = max(12, int(theme.get("title_font_px", 11)))
                help_btn.setIconSize(QSize(icon_px, icon_px))

    def _update_toolbar_compaction(self) -> None:
        width = max(int(self.width()), 1)
        max_batch_width = max(220, min(int(width * 0.33), 720))
        self.batch_selector.setMaximumWidth(max_batch_width)
        self._sync_selection_action_button_sizes()
        self._sync_version_stepper()
        self._sync_batch_selector_tooltip()
        self._sync_side_tile_heights()

    def _sync_side_tile_heights(self) -> None:
        if not hasattr(self, "analysis_controls_tile") or not hasattr(self, "display_controls_tile"):
            return
        hinted = max(
            int(self.analysis_controls_tile.sizeHint().height()),
            int(self.display_controls_tile.sizeHint().height()),
        )
        if hinted <= 0:
            return
        self.analysis_controls_tile.setMinimumHeight(hinted)
        self.analysis_controls_tile.setMaximumHeight(hinted)
        self.display_controls_tile.setMinimumHeight(hinted)
        self.display_controls_tile.setMaximumHeight(hinted)

    def _stabilize_analyzer_controls_row_height(self) -> None:
        if self._analyzer_controls_row_min_height > 0:
            self.analyzer_controls_row.setMinimumHeight(int(self._analyzer_controls_row_min_height))
            return
        layout = self.analyzer_controls_row.layout()
        if layout is not None:
            layout.activate()
        hinted = max(
            int(self.analyzer_controls_row.sizeHint().height()),
            int(self.analyzer_controls_row.minimumSizeHint().height()),
        )
        if hinted <= 0:
            return
        self._analyzer_controls_row_min_height = hinted
        self.analyzer_controls_row.setMinimumHeight(int(hinted))

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._stabilize_analyzer_controls_row_height()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_toolbar_compaction()
        QTimer.singleShot(0, self._apply_plot_panel_header_theme)

    def _sync_selection_action_button_sizes(self) -> None:
        refresh_width = max(int(self.compute_btn.sizeHint().width()), 128)
        details_width = max(int(self.run_details_btn.sizeHint().width()), 128)
        target_width = max(refresh_width, details_width)
        self.compute_btn.setFixedWidth(target_width)
        self.run_details_btn.setFixedWidth(target_width)

    def _sync_batch_selector_tooltip(self, _index: int = 0) -> None:
        text = str(self.batch_selector.currentText() or "").strip()
        self.batch_selector.setToolTip(text)

    def _run_selector_rows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for idx in range(self.run_selector.count()):
            payload = dict(self.run_selector.itemData(idx) or {})
            if not payload:
                continue
            rows.append(payload)
        return rows

    def _sync_version_stepper(self) -> None:
        rows = self._run_selector_rows()
        if not rows:
            self.versions_btn.set_full_text("B---/V---")
            self.versions_btn.setEnabled(False)
            self.version_prev_btn.setEnabled(False)
            self.version_next_btn.setEnabled(False)
            return
        index = max(0, min(int(self.run_selector.currentIndex()), len(rows) - 1))
        payload = dict(rows[index])
        selection = f"{str(payload.get('batch_id') or '--')}/{str(payload.get('version_id') or '--')}"
        self.versions_btn.set_full_text(selection)
        self.versions_btn.setEnabled(True)
        self.version_prev_btn.setEnabled(index > 0)
        self.version_next_btn.setEnabled(index < (len(rows) - 1))

    def _step_selected_version(self, direction: int) -> None:
        rows = self._run_selector_rows()
        if not rows:
            self._sync_version_stepper()
            return
        current = max(0, min(int(self.run_selector.currentIndex()), len(rows) - 1))
        target = max(0, min(current + int(direction), len(rows) - 1))
        if target == current:
            self._sync_version_stepper()
            return
        self.run_selector.setCurrentIndex(target)
        self._sync_version_stepper()

    def _build_plot_placeholder(self, text: str) -> QWidget:
        shell = QWidget()
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)
        frame = QFrame()
        frame.setObjectName("ProjectIssuesPanel")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(8, 8, 8, 8)
        frame_layout.setSpacing(0)
        label = QLabel(str(text))
        label.setObjectName("SummaryText")
        label.setAlignment(Qt.AlignCenter)
        frame_layout.addStretch(1)
        frame_layout.addWidget(label, 0, Qt.AlignCenter)
        frame_layout.addStretch(1)
        layout.addWidget(frame, 1)
        return shell

    def shutdown(self) -> None:
        self._stop_metadata_worker()
        self._stop_compute_worker()
        self._stop_plot_worker()
        self._stop_compare_plot_worker()
        self._stop_autopick_worker()
        self._plot_debounce_timer.stop()
        self._compare_plot_debounce_timer.stop()

    def set_project_context(self, project_id: Optional[str]) -> None:
        token = str(project_id or "").strip() or None
        self._project_context_id = token
        self.project_selector.setEnabled(False)
        self._ath_all_param_rows_by_version.clear()
        self._reload_project_ui_prefs()
        self._update_toolbar_context_chips()

    def refresh_data(self) -> None:
        self._request_metadata(mode="overview")

    def _source_key(self) -> str:
        value = str(getattr(self.service.settings, "analyzer_data_source", "project") or "project").strip().lower()
        return value if value in {"project", "global"} else "project"

    def _selected_project_id(self) -> Optional[str]:
        if self._project_context_id:
            return self._project_context_id
        token = str(self.project_selector.currentData() or "").strip()
        return token or None

    def _selected_batch_id(self) -> Optional[str]:
        token = str(self.batch_selector.currentData() or "").strip()
        return token or None

    def _selected_stage_id(self) -> str:
        return normalize_stage_id(
            str(self.stage_selector.currentData() or self._default_stage_id),
            fallback=self._default_stage_id,
        )

    def _selected_target(self) -> Dict[str, Any]:
        preset_id = str(self.target_selector.currentData() or self._default_coverage_preset_id).strip()
        for preset in self._coverage_presets:
            if str(preset.get("id") or "").strip() == preset_id:
                return dict(preset)
        return {"id": self._default_coverage_preset_id, "h_deg": 90.0, "v_deg": 40.0}

    def _freq_bounds_hint(self) -> tuple[float, float]:
        lows: List[float] = []
        highs: List[float] = []
        for row in self._all_run_rows:
            try:
                low = float(row.get("freq_min_hz"))
                high = float(row.get("freq_max_hz"))
            except Exception:
                continue
            if low > 0.0:
                lows.append(low)
            if high > 0.0:
                highs.append(high)
        if lows and highs:
            return (min(lows), max(highs))
        return (200.0, 16000.0)

    def _resolved_band_limits(self) -> tuple[float, float]:
        preset_id = str(self.band_selector.currentData() or self._default_band_preset_id).strip()
        freq_min_hz, freq_max_hz = self._freq_bounds_hint()
        return resolve_band_limits(
            preset_id=preset_id,
            freq_min_hz=freq_min_hz,
            freq_max_hz=freq_max_hz,
            custom_low_hz=float(self.custom_band_low_spin.value()),
            custom_high_hz=float(self.custom_band_high_spin.value()),
        )

    def _active_kpi_config(self) -> Dict[str, Any]:
        target = self._selected_target()
        band_low_hz, band_high_hz = self._resolved_band_limits()
        return {
            "stage_mode": self._selected_stage_id(),
            "target_h_deg": float(target.get("h_deg") or 90.0),
            "target_v_deg": float(target.get("v_deg") or 40.0),
            "tol_deg": float(self.tol_spin.value()),
            "band_low_hz": float(band_low_hz),
            "band_high_hz": float(band_high_hz),
            "algo_version": self._algo_version,
        }

    def _cache_policy_from_settings(self):
        settings = self.service.settings
        return resolve_cache_policy(
            mode=str(getattr(settings, "analyzer_cache_mode", "balanced") or "balanced"),
            custom_limit_mb=int(getattr(settings, "analyzer_cache_limit_mb", 240) or 240),
            custom_keep_last_n=int(getattr(settings, "analyzer_cache_keep_last_n", 5) or 5),
        )

    def reload_cache_settings(self) -> None:
        self._plot_cache.configure(self._cache_policy_from_settings())

    def reload_user_settings(self) -> None:
        self.reload_cache_settings()
        self.compute_btn.setEnabled(self._source_key() == "project")
        self._update_toolbar_context_chips()
        self._on_source_changed()

    def _selected_plane(self) -> str:
        active = str(self._active_plane or "H").strip().upper() or "H"
        if active not in {"H", "V", "D"}:
            return active
        for plane_key in ("H", "V", "D"):
            button = self._plane_buttons.get(plane_key)
            if button is not None and button.isChecked():
                return plane_key
        return active

    def _x_axis_mode(self) -> str:
        token = str(self.x_axis_scale_combo.currentData() or "log").strip().lower()
        return token if token in {"log", "linear"} else "log"

    def _set_loading(self, loading: bool, text: Optional[str] = None) -> None:
        if loading:
            self.loading_label.setText(str(text or "Loading metadata..."))
            return
        self.loading_label.setText(str(text or "Ready."))

    def _set_error(self, message: str) -> None:
        text = str(message or "").strip()
        self.error_label.setVisible(bool(text))
        self.error_label.setText(text)

    def _set_compute_busy(self, busy: bool, text: str = "") -> None:
        self.compute_btn.setEnabled((not busy) and self._source_key() == "project")
        self.compute_progress.setVisible(bool(busy))
        self.compute_cancel_btn.setVisible(bool(busy))
        if busy:
            self.compute_progress.setRange(0, 0)
            self.compute_progress.setFormat(str(text or "Computing KPIs..."))
        else:
            self.compute_progress.setRange(0, 100)
            self.compute_progress.setValue(0)
            self.compute_progress.setFormat("%p%")

    def _set_plot_busy(self, busy: bool, text: str = "") -> None:
        self.plot_cancel_btn.setVisible(bool(busy))
        self.plot_cancel_btn.setEnabled(bool(busy))
        if busy:
            self.plot_loading_label.setText(str(text or "Loading plot data..."))
            return
        self.plot_loading_label.setText(str(text or "Ready."))

    def _set_compare_busy(self, busy: bool, text: str = "") -> None:
        self.compare_cancel_btn.setVisible(bool(busy))
        self.compare_cancel_btn.setEnabled(bool(busy))
        if busy:
            self.compare_notice.set_full_text(str(text or "Loading compare candidates..."))
            return
        if not self._compare_candidates:
            self.compare_notice.set_full_text("Select up to 5 versions, then add or auto-pick top candidates.")
        else:
            self.compare_notice.set_full_text(str(text or f"{len(self._compare_candidates)} candidate(s) in compare set."))

    def _clear_metadata_worker_refs(self, thread: Optional[QThread] = None) -> None:
        if thread is None:
            self._metadata_worker = None
            self._metadata_thread = None
            return
        if self._metadata_thread is thread:
            self._metadata_worker = None
            self._metadata_thread = None

    def _clear_compute_worker_refs(self, thread: Optional[QThread] = None) -> None:
        if thread is None:
            self._compute_worker = None
            self._compute_thread = None
            return
        if self._compute_thread is thread:
            self._compute_worker = None
            self._compute_thread = None

    def _clear_plot_worker_refs(self, thread: Optional[QThread] = None) -> None:
        if thread is None:
            self._plot_worker = None
            self._plot_thread = None
            return
        if self._plot_thread is thread:
            self._plot_worker = None
            self._plot_thread = None

    def _clear_compare_plot_worker_refs(self, thread: Optional[QThread] = None) -> None:
        if thread is None:
            self._compare_plot_worker = None
            self._compare_plot_thread = None
            return
        if self._compare_plot_thread is thread:
            self._compare_plot_worker = None
            self._compare_plot_thread = None

    def _clear_autopick_worker_refs(self, thread: Optional[QThread] = None) -> None:
        if thread is None:
            self._autopick_worker = None
            self._autopick_thread = None
            return
        if self._autopick_thread is thread:
            self._autopick_worker = None
            self._autopick_thread = None

    def _stop_metadata_worker(self) -> None:
        thread = self._metadata_thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(1500)
        self._clear_metadata_worker_refs()

    def _stop_compute_worker(self) -> None:
        worker = self._compute_worker
        if worker is not None:
            worker.cancel()
        thread = self._compute_thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(1500)
        self._clear_compute_worker_refs()
        self._set_compute_busy(False)

    def _stop_plot_worker(self) -> None:
        worker = self._plot_worker
        if worker is not None:
            worker.cancel()
        thread = self._plot_thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(1000)
        self._clear_plot_worker_refs()
        self._set_plot_busy(False)

    def _stop_compare_plot_worker(self) -> None:
        worker = self._compare_plot_worker
        if worker is not None:
            worker.cancel()
        thread = self._compare_plot_thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(1000)
        self._clear_compare_plot_worker_refs()
        self._set_compare_busy(False)

    def _stop_autopick_worker(self) -> None:
        worker = self._autopick_worker
        if worker is not None:
            worker.cancel()
        thread = self._autopick_thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(1000)
        self._clear_autopick_worker_refs()

    def _request_metadata(
        self,
        *,
        mode: str,
        project_id: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> None:
        source = self._source_key()
        project_token = project_id if project_id is not None else self._selected_project_id()
        batch_token = batch_id if batch_id is not None else self._selected_batch_id()
        self._stop_metadata_worker()
        self._metadata_request_id += 1
        request_id = int(self._metadata_request_id)
        config = self._active_kpi_config()
        worker = _AnalyzerMetadataWorker(
            service=self.service,
            request_id=request_id,
            source=source,
            project_id=project_token,
            batch_id=batch_token,
            mode=mode,
            stage_mode=str(config["stage_mode"]),
            target_h_deg=float(config["target_h_deg"]),
            target_v_deg=float(config["target_v_deg"]),
            tol_deg=float(config["tol_deg"]),
            band_low_hz=float(config["band_low_hz"]),
            band_high_hz=float(config["band_high_hz"]),
            algo_version=str(config["algo_version"]),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_metadata_ready)
        worker.failed.connect(self._on_metadata_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_metadata_worker_refs(thread))
        self._metadata_worker = worker
        self._metadata_thread = thread
        self._set_loading(True, "Loading metadata...")
        self._set_error("")
        thread.start()

    def _start_kpi_compute(self) -> None:
        project_id = self._selected_project_id()
        batch_id = self._selected_batch_id()
        if not project_id or not batch_id:
            self._set_error("Select a project and batch before computing KPIs.")
            return
        if self._source_key() != "project":
            self._set_error("KPI compute is available only for Project data source.")
            return
        self._stop_compute_worker()
        self._compute_request_id += 1
        request_id = int(self._compute_request_id)
        config = self._active_kpi_config()
        worker = _AnalyzerKpiComputeWorker(
            service=self.service,
            request_id=request_id,
            project_id=project_id,
            batch_id=batch_id,
            stage_mode=str(config["stage_mode"]),
            target_h_deg=float(config["target_h_deg"]),
            target_v_deg=float(config["target_v_deg"]),
            tol_deg=float(config["tol_deg"]),
            band_low_hz=float(config["band_low_hz"]),
            band_high_hz=float(config["band_high_hz"]),
            algo_version=str(config["algo_version"]),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_compute_progress)
        worker.finished.connect(self._on_compute_finished)
        worker.failed.connect(self._on_compute_failed)
        worker.canceled.connect(self._on_compute_canceled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.canceled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_compute_worker_refs(thread))
        self._compute_worker = worker
        self._compute_thread = thread
        self._set_compute_busy(True, "Computing KPIs...")
        self._set_error("")
        self._set_loading(True, "Computing KPIs in background...")
        thread.start()

    def _cancel_kpi_compute(self) -> None:
        worker = self._compute_worker
        if worker is not None:
            worker.cancel()
        self._set_loading(True, "Canceling KPI compute...")

    def _on_compute_progress(self, done: int, total: int, message: str) -> None:
        done_value = max(int(done), 0)
        total_value = max(int(total), 0)
        if total_value <= 0:
            self.compute_progress.setRange(0, 0)
            self.compute_progress.setFormat(str(message or "Computing KPIs..."))
            return
        self.compute_progress.setRange(0, total_value)
        self.compute_progress.setValue(min(done_value, total_value))
        self.compute_progress.setFormat(f"{min(done_value, total_value)}/{total_value} {str(message or '').strip()}")

    def _on_compute_finished(self, request_id: int, payload: Dict[str, Any]) -> None:
        if int(request_id) != int(self._compute_request_id):
            return
        self._set_compute_busy(False)
        computed = int(payload.get("computed") or 0)
        skipped = int(payload.get("skipped_cached") or 0)
        failed = int(payload.get("failed") or 0)
        self._set_loading(False, f"KPI compute done (computed={computed}, skipped={skipped}, failed={failed}).")
        self._request_runs_for_selected_batch()

    def _on_compute_failed(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._compute_request_id):
            return
        self._set_compute_busy(False)
        self._set_loading(False, "KPI compute failed.")
        self._set_error(str(message or "Analyzer KPI compute failed."))

    def _on_compute_canceled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._compute_request_id):
            return
        self._set_compute_busy(False)
        self._set_loading(False, str(message or "KPI compute canceled."))

    def _on_metadata_ready(self, request_id: int, payload: Dict[str, Any]) -> None:
        if int(request_id) != int(self._metadata_request_id):
            return
        mode = str(payload.get("mode", "overview") or "overview")
        if mode == "runs":
            self._apply_runs_payload(payload)
            self._set_loading(False, "Ready.")
            return
        self._apply_overview_payload(payload)
        self._set_loading(False, "Metadata loaded.")

    def _on_metadata_failed(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._metadata_request_id):
            return
        self._set_loading(False, "Metadata load failed.")
        self._set_error(str(message or "Analyzer metadata query failed."))

    def _selected_row_payloads(self) -> List[Dict[str, Any]]:
        model = self.run_table.selectionModel()
        if model is None:
            return []
        selected = sorted({int(index.row()) for index in model.selectedRows()})
        rows: List[Dict[str, Any]] = []
        for row_idx in selected:
            item = self.run_table.item(row_idx, self.COL_RUN_ID)
            if item is None:
                continue
            payload = dict(item.data(Qt.UserRole) or {})
            if payload:
                rows.append(payload)
        return rows

    def _available_planes(self, row: Dict[str, Any]) -> List[str]:
        values = [str(token or "").strip() for token in list(row.get("planes", []) or [])]
        known = [token for token in dedupe_orientations(values) if token in {"H", "V", "D"}]
        fallback = [token for token in dedupe_orientations(values) if token not in {"H", "V", "D"}]
        return list(known) + list(fallback)

    @staticmethod
    def _plane_unavailable_reason(row: Dict[str, Any], plane_key: str) -> str:
        token = str(plane_key or "").strip().upper()
        if token not in {"H", "V", "D"}:
            return "Plane not available for selected Batch/Version."
        reason_codes = {str(code).strip().upper() for code in list(row.get("kpi_reason_codes", []) or []) if str(code).strip()}
        if "MISSING_PLANE" in reason_codes:
            return (
                f"{token} not available in imported polar data for this Batch/Version (MISSING_PLANE). "
                "Verify polar export includes H/V/D and angle coverage."
            )
        return f"{token} not available for selected Batch/Version."

    def _sync_plane_controls(self, row: Optional[Dict[str, Any]]) -> None:
        row_payload = dict(row or {})
        available = self._available_planes(row_payload)
        for plane_key, button in self._plane_buttons.items():
            enabled = plane_key in available
            button.setVisible(True)
            button.setEnabled(enabled)
            button.setToolTip("" if enabled else self._plane_unavailable_reason(row_payload, plane_key))
        if not available:
            self._active_plane = "H"
            self._set_plot_busy(False, "No planes available for selected run/version.")
            return
        if self._active_plane not in available:
            self._active_plane = available[0]
        button = self._plane_buttons.get(self._active_plane)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def _on_plane_toggled(self, plane_key: str, checked: bool) -> None:
        if not checked:
            return
        self._active_plane = str(plane_key or "H").strip().upper() or "H"
        if str(self.compare_plane_combo.currentData() or "").strip().upper() != self._active_plane:
            self._set_combo_current_by_data(self.compare_plane_combo, self._active_plane)
        if self.analysis_tabs.currentWidget() is self.compare_tab:
            self._update_compare_slots()
        self._schedule_plot_refresh()
        self._schedule_compare_plot_refresh()

    def _on_plot_config_changed(self, _value: Any = None) -> None:
        if self._control_sync_guard:
            return
        self._update_toolbar_context_chips()
        if self._latest_plot_payload:
            self._render_plot_payload(dict(self._latest_plot_payload))
        self._schedule_plot_refresh()
        self._schedule_compare_plot_refresh()
        self._render_compare_visuals()

    def _open_display_advanced_dialog(self) -> None:
        dialog = StyledDialogBase(title="Display Advanced", parent=self, min_width=560, min_height=360)
        body = dialog.body_layout()
        intro = QLabel("Configure hidden display options and rendering toggles.")
        intro.setObjectName("SummaryText")
        intro.setWordWrap(True)
        body.addWidget(intro, 0)

        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)

        x_axis_combo = QComboBox()
        for idx in range(self.x_axis_scale_combo.count()):
            x_axis_combo.addItem(self.x_axis_scale_combo.itemText(idx), self.x_axis_scale_combo.itemData(idx))
        self._set_combo_current_by_data(x_axis_combo, str(self.x_axis_scale_combo.currentData() or "log"))
        form.addWidget(QLabel("X-axis"), 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(x_axis_combo, 0, 1)

        norm_mode_combo = QComboBox()
        for idx in range(self.norm_mode_combo.count()):
            norm_mode_combo.addItem(self.norm_mode_combo.itemText(idx), self.norm_mode_combo.itemData(idx))
        self._set_combo_current_by_data(norm_mode_combo, str(self.norm_mode_combo.currentData() or "relative_zero"))
        form.addWidget(QLabel("Normalization"), 0, 2, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(norm_mode_combo, 0, 3)

        norm_angle_combo = QComboBox()
        for idx in range(self.norm_angle_selector.count()):
            norm_angle_combo.addItem(self.norm_angle_selector.itemText(idx), self.norm_angle_selector.itemData(idx))
        self._set_combo_current_by_data(norm_angle_combo, str(self.norm_angle_selector.currentData() or "0"))
        norm_angle_combo.setEnabled(bool(self.norm_angle_selector.isEnabled()))
        norm_angle_combo.setToolTip(str(self.norm_angle_selector.toolTip() or ""))
        form.addWidget(QLabel("Norm angle"), 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(norm_angle_combo, 1, 1)
        tol_spin = QDoubleSpinBox()
        tol_spin.setRange(self.tol_spin.minimum(), self.tol_spin.maximum())
        tol_spin.setDecimals(self.tol_spin.decimals())
        tol_spin.setSingleStep(self.tol_spin.singleStep())
        tol_spin.setValue(float(self.tol_spin.value()))
        form.addWidget(QLabel("Tol (+/-deg)"), 1, 2, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(tol_spin, 1, 3)

        clamp_check = QCheckBox("Clamp heatmap")
        clamp_check.setChecked(bool(self.heatmap_clamp_check.isChecked()))
        clamp_min_spin = QDoubleSpinBox()
        clamp_min_spin.setRange(self.heatmap_clamp_min_spin.minimum(), self.heatmap_clamp_min_spin.maximum())
        clamp_min_spin.setDecimals(self.heatmap_clamp_min_spin.decimals())
        clamp_min_spin.setValue(float(self.heatmap_clamp_min_spin.value()))
        raw_bins_check = QCheckBox("Show raw bins")
        raw_bins_check.setChecked(bool(self.raw_bins_check.isChecked()))
        form.addWidget(clamp_check, 2, 0, 1, 2, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(QLabel("Clamp min dB"), 2, 2, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(clamp_min_spin, 2, 3)
        form.addWidget(raw_bins_check, 3, 0, 1, 2, Qt.AlignLeft | Qt.AlignVCenter)

        mirrored_minus6_check = QCheckBox("Show mirrored -6 dB contour")
        mirrored_minus6_check.setChecked(bool(getattr(self, "_show_mirrored_minus6_contour", False)))
        form.addWidget(mirrored_minus6_check, 3, 2, 1, 2, Qt.AlignLeft | Qt.AlignVCenter)

        smoothness_check = QCheckBox("Use full angles for smoothness (S_theta)")
        smoothness_check.setObjectName("AnalyzerFullAnglesSmoothnessCheck")
        smoothness_check.setChecked(bool(self._use_full_angles_for_smoothness))
        smoothness_check.setToolTip("When enabled, S_theta uses all angles instead of the target window.")
        form.addWidget(smoothness_check, 4, 0, 1, 4, Qt.AlignLeft | Qt.AlignVCenter)
        body.addLayout(form)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("BatchSecondaryButton")
        close_btn = QPushButton("Close")
        close_btn.setObjectName("BatchSecondaryButton")

        def _apply_and_close() -> None:
            plot_changed = False
            if str(self.x_axis_scale_combo.currentData() or "log") != str(x_axis_combo.currentData() or "log"):
                plot_changed = True
            if str(self.norm_mode_combo.currentData() or "relative_zero") != str(norm_mode_combo.currentData() or "relative_zero"):
                plot_changed = True
            if str(self.norm_angle_selector.currentData() or "0") != str(norm_angle_combo.currentData() or "0"):
                plot_changed = True
            tol_changed = abs(float(self.tol_spin.value()) - float(tol_spin.value())) > 1.0e-9
            if bool(self.heatmap_clamp_check.isChecked()) != bool(clamp_check.isChecked()):
                plot_changed = True
            if abs(float(self.heatmap_clamp_min_spin.value()) - float(clamp_min_spin.value())) > 1.0e-9:
                plot_changed = True
            if bool(self.raw_bins_check.isChecked()) != bool(raw_bins_check.isChecked()):
                plot_changed = True
            mirrored_changed = bool(getattr(self, "_show_mirrored_minus6_contour", False)) != bool(mirrored_minus6_check.isChecked())
            if mirrored_changed:
                plot_changed = True
            smoothness_changed = bool(self._use_full_angles_for_smoothness) != bool(smoothness_check.isChecked())

            self._control_sync_guard = True
            self._set_combo_current_by_data(self.x_axis_scale_combo, str(x_axis_combo.currentData() or "log"))
            self._set_combo_current_by_data(self.norm_mode_combo, str(norm_mode_combo.currentData() or "relative_zero"))
            self._set_combo_current_by_data(self.norm_angle_selector, str(norm_angle_combo.currentData() or "0"))
            self.tol_spin.setValue(float(tol_spin.value()))
            self.heatmap_clamp_check.setChecked(bool(clamp_check.isChecked()))
            self.heatmap_clamp_min_spin.setValue(float(clamp_min_spin.value()))
            self.raw_bins_check.setChecked(bool(raw_bins_check.isChecked()))
            self._show_mirrored_minus6_contour = bool(mirrored_minus6_check.isChecked())
            self._use_full_angles_for_smoothness = bool(smoothness_check.isChecked())
            self._control_sync_guard = False

            if plot_changed:
                self._on_plot_config_changed()
            if tol_changed:
                self._on_kpi_config_changed()
            if smoothness_changed:
                self._schedule_plot_refresh()
                self._schedule_compare_plot_refresh()
            dialog.accept()

        apply_btn.clicked.connect(_apply_and_close)
        close_btn.clicked.connect(dialog.accept)
        close_row.addWidget(apply_btn)
        close_row.addWidget(close_btn)
        body.addLayout(close_row)
        dialog.exec()

    def _on_analysis_tab_changed(self, _index: int = 0) -> None:
        is_compare = self.analysis_tabs.currentWidget() is self.compare_tab
        self.analysis_explorer_btn.blockSignals(True)
        self.analysis_compare_btn.blockSignals(True)
        self.analysis_explorer_btn.setChecked(not is_compare)
        self.analysis_compare_btn.setChecked(is_compare)
        self.analysis_explorer_btn.blockSignals(False)
        self.analysis_compare_btn.blockSignals(False)
        if self.analysis_tabs.currentWidget() is self.compare_tab:
            self._stop_plot_worker()
            self._set_plot_busy(False, "Compare tab active.")
            self._refresh_saved_analyses()
            self._set_compare_busy(False)
            self._update_compare_slots()
            self._schedule_compare_plot_refresh()
            return
        self._stop_autopick_worker()
        self._stop_compare_plot_worker()
        self._schedule_plot_refresh()

    def _schedule_plot_refresh(self) -> None:
        if self.analysis_tabs.currentWidget() is not self.explorer_tab:
            return
        self._plot_debounce_timer.start()

    def _start_plot_request(self) -> None:
        if self.analysis_tabs.currentWidget() is not self.explorer_tab:
            return
        rows = self._selected_row_payloads()
        if not rows:
            self._clear_plot_views("Select version + plane to render plots.")
            return
        row = dict(rows[0])
        project_id = str(row.get("project_id") or self._selected_project_id() or "").strip()
        batch_id = str(row.get("batch_id") or self._selected_batch_id() or "").strip()
        version_id = str(row.get("version_id") or "").strip()
        run_id = str(row.get("run_id") or "").strip() or None
        if not project_id or not batch_id or not version_id:
            self._clear_plot_views("Select a valid run/version first.")
            return
        plane = self._selected_plane()
        if plane not in self._available_planes(row):
            self._clear_plot_views("Plane not available for selected run.")
            return

        band_low_hz, band_high_hz = self._resolved_band_limits()
        target = self._selected_target()
        self._stop_plot_worker()
        self._plot_request_id += 1
        request_id = int(self._plot_request_id)
        worker = _AnalyzerPlotWorker(
            service=self.service,
            request_id=request_id,
            source=self._source_key(),
            project_id=project_id,
            batch_id=batch_id,
            run_id=run_id,
            version_id=version_id,
            plane=plane,
            stage_mode=self._selected_stage_id(),
            target_h_deg=float(target.get("h_deg") or 90.0),
            target_v_deg=float(target.get("v_deg") or 40.0),
            tol_deg=float(self.tol_spin.value()),
            band_low_hz=float(band_low_hz),
            band_high_hz=float(band_high_hz),
            cache=self._plot_cache,
            use_full_angles_for_smoothness=bool(self._use_full_angles_for_smoothness),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_plot_ready)
        worker.failed.connect(self._on_plot_failed)
        worker.canceled.connect(self._on_plot_canceled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.canceled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_plot_worker_refs(thread))
        self._plot_worker = worker
        self._plot_thread = thread
        self._set_plot_busy(True, f"Loading {plane} plane...")
        self._set_error("")
        thread.start()

    def _cancel_plot_request(self) -> None:
        worker = self._plot_worker
        if worker is not None:
            worker.cancel()
        self._set_plot_busy(True, "Canceling plot request...")

    def _on_plot_ready(self, request_id: int, payload: Dict[str, Any]) -> None:
        if int(request_id) != int(self._plot_request_id):
            return
        self._set_plot_busy(False, "Plot ready.")
        self._render_plot_payload(dict(payload or {}))

    def _on_plot_failed(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._plot_request_id):
            return
        self._set_plot_busy(False, "Plot load failed.")
        self._set_error(str(message or "Analyzer plot load failed."))
        self._clear_plot_views("Failed to load selected polar plot.")

    def _on_plot_canceled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._plot_request_id):
            return
        self._set_plot_busy(False, str(message or "Plot request canceled."))

    def _clear_plot_views(self, message: str) -> None:
        msg = str(message or "No plot data.")
        self._latest_plot_payload = {}
        for panel in self._explorer_stage_panels.values():
            heatmap_canvas = panel.get("heatmap_canvas")
            if isinstance(heatmap_canvas, HeatmapCanvas):
                heatmap_canvas.clear_heatmap(msg)
            curve_canvas = panel.get("curve_canvas")
            if isinstance(curve_canvas, MetricCurveCanvas):
                curve_canvas.clear_series(msg)
            pareto_canvas = panel.get("pareto_canvas")
            if isinstance(pareto_canvas, ParetoScatterCanvas):
                pareto_canvas.clear_points(msg)
            placeholder = panel.get("placeholder")
            if isinstance(placeholder, QLabel):
                placeholder.setText(msg)
        self._clear_compare_stage_canvases(
            curve_message="Select candidates to display compare plot.",
            heatmap_message="Select candidates to display compare heatmap.",
            pareto_message="Select candidates to render Pareto scatter.",
        )

    @staticmethod
    def _stage_curve_points(curves: Mapping[str, Any], key: str) -> List[Dict[str, Any]]:
        token = str(key or "").strip().lower()
        raw_curve = list(curves.get(token, []) or [])
        points: List[Dict[str, Any]] = []
        for row in raw_curve:
            if not isinstance(row, Mapping):
                continue
            try:
                freq_hz = float(row.get("freq_hz"))  # type: ignore[arg-type]
            except Exception:
                continue
            if freq_hz <= 0.0:
                continue
            value_raw = row.get("value")
            if value_raw is None and token == "beamwidth":
                value_raw = row.get("beamwidth_deg")
            try:
                value = float(value_raw)  # type: ignore[arg-type]
            except Exception:
                continue
            points.append(
                {
                    "freq_hz": freq_hz,
                    "value": value,
                    "saturated": bool(row.get("saturated", False)),
                }
            )
        points.sort(key=lambda item: float(item.get("freq_hz", 0.0)))
        return points

    @staticmethod
    def _stage_curve_y_label(key: str) -> str:
        mapping = {
            "beamwidth": "Beamwidth (deg)",
            "e_bw": "Beamwidth error (deg)",
            "e_cov": "Coverage uniformity (dB)",
            "r_spill": "Spill (ratio)",
            "di_proxy": "DI Proxy (dB)",
            "s_theta": "Pattern smoothness",
            "e_sym_shape": "Plane consistency",
            "r_off": "Off-axis ripple (dB)",
        }
        return str(mapping.get(str(key or "").strip().lower(), "Value"))

    @staticmethod
    def _metric_palette_color(metric_key: str) -> Tuple[int, int, int]:
        token = str(metric_key or "").strip().lower()
        mapping: Dict[str, Tuple[int, int, int]] = {
            "e_cov": (98, 197, 214),
            "r_spill": (223, 163, 88),
            "di_proxy": (154, 172, 197),
            "r_off": (216, 121, 96),
            "s_theta": (137, 194, 128),
            "e_sym_shape": (182, 151, 214),
            "beamwidth": (210, 194, 98),
            "e_bw": (210, 194, 98),
        }
        return tuple(mapping.get(token, (160, 179, 205)))

    def _target_half_window_deg_for_plane(self, plane_key: str) -> float:
        target = self._selected_target()
        token = str(plane_key or "H").strip().upper()
        h_deg = float(target.get("h_deg") or 90.0)
        v_deg = float(target.get("v_deg") or 40.0)
        if token == "H":
            return max(h_deg * 0.5, 0.5)
        if token == "V":
            return max(v_deg * 0.5, 0.5)
        return max(((h_deg + v_deg) * 0.5) * 0.5, 0.5)

    @staticmethod
    def _heatmap_overlay_profile(stage_id: str) -> Dict[str, Any]:
        stage_token = normalize_stage_id(stage_id, fallback=DEFAULT_STAGE_ID)
        return {
            "target_shade_alpha": 48 if stage_token == "concept" else 44,
            "target_boundary_alpha": 186 if stage_token == "concept" else 172,
            "contour_color": (255, 226, 128),
            "contour_width": 2.2 if stage_token == "concept" else 2.0,
        }

    @staticmethod
    def _curve_style_profile(*, stage_id: str, metric_key: str, context: str) -> Dict[str, Any]:
        stage_token = normalize_stage_id(stage_id, fallback=DEFAULT_STAGE_ID)
        key_token = str(metric_key or "").strip().lower()
        context_token = str(context or "explorer").strip().lower()
        if stage_token == "stabilization":
            if key_token == "di_proxy":
                return {
                    "style": "trend_band",
                    "fill_alpha": 0.24 if context_token == "explorer" else 0.14,
                    "regime_markers": bool(context_token == "explorer"),
                    "thresholds": [2.0, 4.0],
                    "line_width": 1.4 if context_token == "explorer" else 1.2,
                }
            if key_token in {"s_theta", "e_sym_shape"}:
                return {
                    "style": "consistency_strip",
                    "line_width": 1.2,
                    "thresholds": [0.20, 0.40] if key_token == "s_theta" else [0.35, 0.75],
                }
        if stage_token == "final":
            if key_token == "r_off":
                return {
                    "style": "defect_band",
                    "fill_alpha": 0.28 if context_token == "explorer" else 0.18,
                    "line_width": 1.4 if context_token == "explorer" else 1.2,
                    "thresholds": [2.0, 4.0, 6.0],
                    "hotspot_threshold": 6.0,
                }
            if key_token in {"s_theta", "e_sym_shape"}:
                return {
                    "style": "consistency_strip",
                    "line_width": 1.2,
                    "thresholds": [0.20, 0.40] if key_token == "s_theta" else [0.35, 0.75],
                }
        return {}

    def _render_plot_payload(self, payload: Dict[str, Any]) -> None:
        self._latest_plot_payload = dict(payload or {})
        message = str(payload.get("message") or "").strip()
        display_matrix = [list(row) for row in list(payload.get("display_matrix_db", []) or [])]
        stage_payload = dict(payload.get("stage_plot") or {})
        curves = dict(stage_payload.get("curves") or {})
        heatmap_overlays = dict(stage_payload.get("heatmap_overlays") or {})
        if not display_matrix:
            self._clear_plot_views(message or "No polar matrix available for this selection.")
            return
        clamp_enabled = bool(self.heatmap_clamp_check.isChecked())
        clamp_min = float(self.heatmap_clamp_min_spin.value())
        overlay_profile = self._heatmap_overlay_profile(self._selected_stage_id())
        status = ""
        ref_angle = payload.get("ref_angle_deg")
        if message:
            status = message
        for panel in self._explorer_stage_panels.values():
            key = str(panel.get("metric_key") or "").strip().lower()
            if key == "heatmap":
                heatmap_canvas = panel.get("heatmap_canvas")
                if not isinstance(heatmap_canvas, HeatmapCanvas):
                    continue
                heatmap_canvas.set_heatmap_data(
                    matrix=display_matrix,
                    freqs_hz=[float(value) for value in list(payload.get("display_freqs_hz", []) or [])],
                    angles_deg=[float(value) for value in list(payload.get("angles_deg", []) or [])],
                    clamp_enabled=clamp_enabled,
                    clamp_min_db=clamp_min,
                    show_raw_bins=bool(self.raw_bins_check.isChecked()),
                    ref_angle_deg=float(ref_angle) if ref_angle is not None else None,
                    minus6_contour=[
                        dict(item)
                        for item in list(heatmap_overlays.get("minus6_contour", []) or [])
                        if isinstance(item, dict)
                    ],
                    target_half_window_deg=(
                        float(heatmap_overlays.get("target_half_window_deg"))
                        if heatmap_overlays.get("target_half_window_deg") is not None
                        else float(self._target_half_window_deg_for_plane(self._active_plane))
                    ),
                    show_mirrored_minus6=bool(self._show_mirrored_minus6_contour),
                    target_shade_alpha=int(overlay_profile.get("target_shade_alpha", 24)),
                    target_boundary_alpha=int(overlay_profile.get("target_boundary_alpha", 140)),
                    contour_color=tuple(overlay_profile.get("contour_color", (255, 227, 138))),
                    contour_width=float(overlay_profile.get("contour_width", 2.0)),
                    status=status,
                )
                continue

            if key.startswith("pareto"):
                pareto_canvas = panel.get("pareto_canvas")
                if isinstance(pareto_canvas, ParetoScatterCanvas):
                    summary = dict(stage_payload.get("summary") or {})
                    x_value = summary.get("e_bw_mean")
                    y_value = summary.get("r_spill_mean")
                    if x_value is not None and y_value is not None:
                        pareto_canvas.set_points(
                            points=[
                                {
                                    "label": format_series_label(dict(self._selected_detail_payload or {}).get("version_id")),
                                    "x_value": float(x_value),
                                    "y_value": float(y_value),
                                    "color": compare_overlay_color(0),
                                    "selected": True,
                                }
                            ],
                            x_label="Beamwidth Error (deg)",
                            y_label="Spill Ratio",
                            status="",
                        )
                    else:
                        pareto_canvas.clear_points(message or "Pareto snapshot unavailable for this selection.")
                continue

            curve_canvas = panel.get("curve_canvas")
            if not isinstance(curve_canvas, MetricCurveCanvas):
                continue
            curve_points = self._stage_curve_points(curves, key)
            if curve_points:
                style_profile = self._curve_style_profile(
                    stage_id=self._selected_stage_id(),
                    metric_key=key,
                    context="explorer",
                )
                series_row: Dict[str, Any] = {
                    "label": "",
                    "show_legend": False,
                    "points": curve_points,
                    "color": self._metric_palette_color(key),
                }
                series_row.update(style_profile)
                curve_canvas.set_series(
                    series=[series_row],
                    x_scale_mode=self._x_axis_mode(),
                    x_label="Frequency (Hz, log)" if self._x_axis_mode() == "log" else "Frequency (Hz)",
                    y_label=self._stage_curve_y_label(key),
                    status="",
                )
            else:
                missing_msg = message or "Curve unavailable for selected stage."
                curve_canvas.clear_series(missing_msg)
            placeholder = panel.get("placeholder")
            if isinstance(placeholder, QLabel):
                placeholder.setText(message or "No stage plot data available.")

    def _compare_identity(self, row: Dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(row.get("project_id") or "").strip(),
            str(row.get("batch_id") or "").strip(),
            str(row.get("run_id") or "").strip(),
            str(row.get("version_id") or "").strip(),
        )

    def _candidate_from_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        batch_id = str(row.get("batch_id") or "").strip() or "--"
        version_id = str(row.get("version_id") or "").strip() or "--"
        score_raw = row.get("kpi_score")
        if score_raw is None:
            score_raw = row.get("score")
        aggregate = dict(dict(row.get("kpi", {}) or {}).get("aggregate", {}) or {})
        candidate = {
            "project_id": str(row.get("project_id") or self._selected_project_id() or "").strip(),
            "batch_id": batch_id,
            "run_id": (str(row.get("run_id") or "").strip() or None),
            "version_id": version_id,
            "run_label": f"{batch_id}/{version_id}",
            "score": score_raw,
            "kpi_b_pc_oct": row.get("kpi_b_pc_oct"),
            "kpi_e_bw": row.get("kpi_e_bw"),
            "kpi_e_cov": row.get("kpi_e_cov"),
            "kpi_r_spill": row.get("kpi_r_spill"),
            "kpi_di_proxy": row.get("kpi_di_proxy", aggregate.get("di_proxy")),
            "kpi_s_theta": row.get("kpi_s_theta", aggregate.get("s_theta")),
            "kpi_e_sym_shape": row.get("kpi_e_sym_shape", aggregate.get("e_sym_shape")),
            "kpi_r_off": row.get("kpi_r_off", aggregate.get("r_off")),
            "kpi_flags_count": int(row.get("kpi_flags_count") or 0) if score_raw is not None else None,
            "kpi_reason_codes": [str(code) for code in list(row.get("kpi_reason_codes", []) or []) if str(code).strip()],
            "planes": [str(item) for item in list(row.get("planes", []) or [])],
            "kpi": dict(row.get("kpi", {}) or {}) if isinstance(row.get("kpi"), dict) else {},
            "imported_at": row.get("imported_at"),
        }
        return self._apply_pin_state_to_row(candidate)

    def _compare_table_columns(self) -> List[Tuple[str, str]]:
        return list(COMPARE_BASE_COLUMNS) + list(self._compare_kpi_columns) + [("remove", "Remove")]

    def _compare_stage_kpi_columns(self) -> List[Tuple[str, str]]:
        stage_id = self._selected_stage_id()
        configured = COMPARE_STAGE_KPI_COLUMNS.get(stage_id)
        if configured:
            return [tuple(item) for item in configured]
        return [tuple(item) for item in COMPARE_DEFAULT_KPI_COLUMNS]

    def _refresh_compare_table_column_mapping(self) -> None:
        self._compare_kpi_columns = list(self._compare_stage_kpi_columns())

    def _configure_compare_slots_table(self) -> None:
        self._refresh_compare_table_column_mapping()
        columns = self._compare_table_columns()
        self.compare_slots_table.setColumnCount(len(columns))
        self.compare_slots_table.setHorizontalHeaderLabels([str(label) for _key, label in columns])
        header = self.compare_slots_table.horizontalHeader()
        for index, (key, _label) in enumerate(columns):
            if key == "selection":
                header.setSectionResizeMode(index, QHeaderView.Stretch)
            elif key == "slot":
                header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
            elif key == "remove":
                header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeToContents)

    def _compare_candidate_metric_text(self, candidate: Mapping[str, Any], metric_key: str) -> str:
        token = str(metric_key or "").strip().lower()
        aggregate = dict(dict(candidate.get("kpi", {}) or {}).get("aggregate", {}) or {})
        direct_fields = {
            "b_pc_oct": ("kpi_b_pc_oct", 2),
            "e_bw": ("kpi_e_bw", 2),
            "e_cov": ("kpi_e_cov", 2),
            "r_spill": ("kpi_r_spill", 3),
            "di_proxy": ("kpi_di_proxy", 2),
            "s_theta": ("kpi_s_theta", 3),
            "e_sym_shape": ("kpi_e_sym_shape", 3),
            "r_off": ("kpi_r_off", 2),
        }
        field = direct_fields.get(token)
        value = None
        digits = 2
        if field is not None:
            value = candidate.get(field[0])
            digits = int(field[1])
        if value is None:
            value = aggregate.get(token)
        if value is None:
            stage_summary = self._compare_stage_summary_for_candidate(candidate)
            if stage_summary:
                value = stage_summary.get(f"{token}_mean")
        return self._format_float(value, digits)

    def _compare_stage_summary_for_candidate(self, candidate: Mapping[str, Any]) -> Dict[str, Any]:
        target_identity = self._compare_identity(dict(candidate))
        for item in self._compare_plot_items:
            if not isinstance(item, dict):
                continue
            row_candidate = dict(item.get("candidate") or {})
            if self._compare_identity(row_candidate) != target_identity:
                continue
            stage_plot = dict(dict(item.get("plot") or {}).get("stage_plot", {}) or {})
            return dict(stage_plot.get("summary") or {})
        return {}

    def _set_compare_candidates(self, candidates: Sequence[Dict[str, Any]], *, message: str = "") -> None:
        dedup: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
        ordered: List[Dict[str, Any]] = []
        for candidate in list(candidates or []):
            if not isinstance(candidate, dict):
                continue
            normalized = self._candidate_from_row(dict(candidate))
            identity = self._compare_identity(normalized)
            if not identity[0] or not identity[2]:
                continue
            if identity in dedup:
                continue
            dedup[identity] = normalized
            ordered.append(normalized)
            if len(ordered) >= 5:
                break
        self._compare_candidates = ordered
        self._compare_plot_items = []
        self._update_compare_slots(message=message)
        self._schedule_compare_plot_refresh()

    def _on_compare_add_selected(self) -> None:
        rows = [dict(item) for item in self._selected_row_payloads()]
        if not rows:
            self._set_compare_busy(False, "Select version rows first, then Add selected.")
            return
        merged = list(self._compare_candidates) + [self._candidate_from_row(row) for row in rows]
        self._set_compare_candidates(merged, message="Added selected versions to compare set.")

    def _remove_compare_candidate(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._compare_candidates):
            return
        remaining = [dict(item) for idx, item in enumerate(self._compare_candidates) if idx != row_index]
        if self._selected_compare_slot_index is not None and int(self._selected_compare_slot_index) == int(row_index):
            self._selected_compare_slot_index = None
        self._set_compare_candidates(remaining, message="Candidate removed.")

    def _on_compare_slot_selection_changed(self) -> None:
        model = self.compare_slots_table.selectionModel()
        if model is None:
            self._selected_compare_slot_index = None
            self._update_compare_kpi_panel()
            self._render_compare_visuals()
            return
        selected = model.selectedRows()
        if not selected:
            self._selected_compare_slot_index = None
            self._update_compare_kpi_panel()
            self._render_compare_visuals()
            return
        row_index = int(selected[0].row())
        self._selected_compare_slot_index = row_index if row_index < len(self._compare_candidates) else None
        self._update_compare_kpi_panel()
        self._render_compare_visuals()

    def _update_compare_kpi_panel(self) -> None:
        idx = self._selected_compare_slot_index
        selected_col = int(idx) if idx is not None and 0 <= int(idx) < len(self._compare_candidates) else None
        if selected_col is None:
            self.compare_notice.set_full_text("Select up to 5 versions, then add or auto-pick top candidates.")
        else:
            selected = dict(self._compare_candidates[selected_col] or {})
            marker = "[PIN] " if bool(selected.get("version_pinned")) else ""
            self.compare_notice.set_full_text(
                f"Active: C{selected_col + 1} {marker}{selected.get('batch_id')}/{selected.get('version_id')}"
            )
        if self.compare_heatmap_selector.count() > 0 and selected_col is not None:
            if 0 <= int(selected_col) < int(self.compare_heatmap_selector.count()):
                self.compare_heatmap_selector.setCurrentIndex(int(selected_col))

    def _update_compare_slots(self, *, message: str = "") -> None:
        slots = list(self._compare_candidates)
        self._configure_compare_slots_table()
        self.compare_slots_table.setRowCount(5)
        self.compare_heatmap_selector.clear()
        selected_plane = self._compare_plane()
        columns = self._compare_table_columns()
        col_index = {key: idx for idx, (key, _label) in enumerate(columns)}
        remove_col = int(col_index.get("remove", max(len(columns) - 1, 0)))
        for row_index in range(5):
            slot_label = f"C{row_index + 1}"
            color_item = QTableWidgetItem(slot_label)
            color_rgb = compare_overlay_color(row_index)
            color_item.setBackground(QColor(*color_rgb))
            color_item.setForeground(QColor("#0D1117"))
            if "slot" in col_index:
                self.compare_slots_table.setItem(row_index, int(col_index["slot"]), color_item)
            candidate = dict(slots[row_index]) if row_index < len(slots) else {}
            if candidate:
                selection_label = f"{str(candidate.get('batch_id') or '--')}/{str(candidate.get('version_id') or '--')}"
                marker = "[PIN] " if bool(candidate.get("version_pinned")) else ""
                planes_present = {str(token).strip().upper() for token in list(candidate.get("planes", []) or []) if str(token).strip()}
                missing_note = f" [missing {selected_plane}]" if selected_plane not in planes_present else ""
                selection_text = f"{marker}{selection_label}{missing_note}"
                score_text = self._format_float(candidate.get("score"), 2)
                flags_count = candidate.get("kpi_flags_count")
                flags_text = "--" if flags_count is None else str(int(flags_count))
                for key, idx in col_index.items():
                    if key in {"slot", "remove"}:
                        continue
                    if key == "selection":
                        item = QTableWidgetItem(selection_text)
                        item.setToolTip(selection_text)
                    elif key == "score":
                        item = QTableWidgetItem(score_text)
                        item.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
                    elif key == "flags":
                        item = QTableWidgetItem(flags_text)
                        item.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
                        codes = [str(code) for code in list(candidate.get("kpi_reason_codes", []) or []) if str(code).strip()]
                        if codes:
                            item.setToolTip(", ".join(codes))
                    else:
                        metric_text = self._compare_candidate_metric_text(candidate, key)
                        item = QTableWidgetItem(metric_text)
                        item.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
                        if metric_text == "--":
                            item.setToolTip(f"{key}: --\nCompute KPIs to populate.")
                        else:
                            item.setToolTip(f"{key}: {metric_text}")
                    self.compare_slots_table.setItem(row_index, int(idx), item)
                self.compare_heatmap_selector.addItem(f"{slot_label} | {selection_text}", row_index)
            else:
                for key, idx in col_index.items():
                    if key in {"slot", "remove"}:
                        continue
                    item = QTableWidgetItem("--")
                    if key != "selection":
                        item.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
                    self.compare_slots_table.setItem(row_index, int(idx), item)

            remove_btn = QPushButton("Remove")
            remove_btn.setObjectName("BatchSecondaryButton")
            remove_btn.setEnabled(bool(candidate))
            remove_btn.clicked.connect(lambda _checked=False, idx=row_index: self._remove_compare_candidate(idx))
            self.compare_slots_table.setCellWidget(row_index, remove_col, remove_btn)

        self._sync_compare_plane_options()

        if self.compare_heatmap_selector.count() > 0:
            desired = 0
            if self._selected_compare_slot_index is not None and 0 <= int(self._selected_compare_slot_index) < self.compare_heatmap_selector.count():
                desired = int(self._selected_compare_slot_index)
            self.compare_heatmap_selector.setCurrentIndex(desired)
        else:
            self._clear_compare_stage_canvases(
                curve_message="Select candidates to display compare plot.",
                heatmap_message="Select candidates to display compare heatmap.",
                pareto_message="Select candidates to render Pareto scatter.",
            )
        if self._selected_compare_slot_index is None and slots:
            self._selected_compare_slot_index = 0
        if self._selected_compare_slot_index is not None and (self._selected_compare_slot_index >= len(slots)):
            self._selected_compare_slot_index = None
        if self._selected_compare_slot_index is not None:
            self.compare_slots_table.selectRow(int(self._selected_compare_slot_index))
        self._update_compare_kpi_panel()
        self._render_compare_visuals()

        if message:
            self._set_compare_busy(False, message)
        elif not slots:
            self._set_compare_busy(False, "Select up to 5 versions, then add or auto-pick top candidates.")
        else:
            self._set_compare_busy(False, f"{len(slots)} candidate(s) in compare set.")

    def _compare_plane(self) -> str:
        token = str(self.compare_plane_combo.currentData() or "H").strip().upper()
        return token if token in {"H", "V", "D"} else "H"

    def _sync_compare_plane_options(self) -> None:
        has_d = any("D" in {str(token).upper() for token in list(candidate.get("planes", []) or [])} for candidate in self._compare_candidates)
        model = self.compare_plane_combo.model()
        for index in range(self.compare_plane_combo.count()):
            data = str(self.compare_plane_combo.itemData(index) or "")
            enabled = bool(data in {"H", "V"} or (data == "D" and has_d))
            model_item = model.item(index) if hasattr(model, "item") else None
            if model_item is not None:
                flags = model_item.flags()
                if enabled:
                    model_item.setFlags(flags | Qt.ItemIsEnabled)
                else:
                    model_item.setFlags(flags & ~Qt.ItemIsEnabled)
        if not has_d and self._compare_plane() == "D":
            self._set_combo_current_by_data(self.compare_plane_combo, "H")

    def _clear_compare_stage_canvases(
        self,
        *,
        curve_message: str,
        heatmap_message: str,
        pareto_message: str,
    ) -> None:
        for panel in self._compare_stage_panels.values():
            if not isinstance(panel, dict):
                continue
            curve_canvas = panel.get("curve_canvas")
            if isinstance(curve_canvas, MetricCurveCanvas):
                curve_canvas.clear_series(curve_message)
            heatmap_canvas = panel.get("heatmap_canvas")
            if isinstance(heatmap_canvas, HeatmapCanvas):
                heatmap_canvas.clear_heatmap(heatmap_message)
            pareto_canvas = panel.get("pareto_canvas")
            if isinstance(pareto_canvas, ParetoScatterCanvas):
                pareto_canvas.clear_points(pareto_message)

    def _schedule_compare_plot_refresh(self) -> None:
        if self.analysis_tabs.currentWidget() is not self.compare_tab:
            return
        self._compare_plot_debounce_timer.start()

    def _start_compare_plot_request(self) -> None:
        if self.analysis_tabs.currentWidget() is not self.compare_tab:
            return
        project_id = str(self._selected_project_id() or "").strip()
        if not project_id:
            self._clear_compare_stage_canvases(
                curve_message="Open a project to compare candidates.",
                heatmap_message="Open a project to compare candidates.",
                pareto_message="Open a project to compare candidates.",
            )
            return
        if not self._compare_candidates:
            self._clear_compare_stage_canvases(
                curve_message="Select candidates to display compare plot.",
                heatmap_message="Select candidates to display compare heatmap.",
                pareto_message="Select candidates to render Pareto scatter.",
            )
            return
        band_low_hz, band_high_hz = self._resolved_band_limits()
        target = self._selected_target()
        self._stop_compare_plot_worker()
        self._compare_plot_request_id += 1
        request_id = int(self._compare_plot_request_id)
        worker = _AnalyzerComparePlotWorker(
            service=self.service,
            request_id=request_id,
            source=self._source_key(),
            project_id=project_id,
            candidates=list(self._compare_candidates),
            plane=self._compare_plane(),
            stage_mode=self._selected_stage_id(),
            target_h_deg=float(target.get("h_deg") or 90.0),
            target_v_deg=float(target.get("v_deg") or 40.0),
            tol_deg=float(self.tol_spin.value()),
            band_low_hz=float(band_low_hz),
            band_high_hz=float(band_high_hz),
            cache=self._plot_cache,
            use_full_angles_for_smoothness=bool(self._use_full_angles_for_smoothness),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_compare_plot_progress)
        worker.finished.connect(self._on_compare_plot_ready)
        worker.failed.connect(self._on_compare_plot_failed)
        worker.canceled.connect(self._on_compare_plot_canceled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.canceled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_compare_plot_worker_refs(thread))
        self._compare_plot_worker = worker
        self._compare_plot_thread = thread
        self._set_compare_busy(True, "Loading compare plot data...")
        thread.start()

    def _on_compare_plot_progress(self, done: int, total: int, message: str) -> None:
        done_value = max(int(done), 0)
        total_value = max(int(total), 0)
        if total_value <= 0:
            self._set_compare_busy(True, str(message or "Loading compare plot data..."))
            return
        self._set_compare_busy(True, f"{done_value}/{total_value} {str(message or '').strip()}")

    def _on_compare_plot_ready(self, request_id: int, payload: Dict[str, Any]) -> None:
        if int(request_id) != int(self._compare_plot_request_id):
            return
        normalized_items: List[Dict[str, Any]] = []
        for raw_item in list(payload.get("items", []) or []):
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            item["candidate"] = self._apply_pin_state_to_row(dict(item.get("candidate") or {}))
            normalized_items.append(item)
        self._compare_plot_items = normalized_items
        self._render_compare_visuals()
        self._set_compare_busy(False, "Compare plots ready.")

    def _on_compare_plot_failed(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._compare_plot_request_id):
            return
        self._set_compare_busy(False, "Compare plot load failed.")
        self._set_error(str(message or "Compare plot load failed."))
        self._clear_compare_stage_canvases(
            curve_message="Compare plot load failed.",
            heatmap_message="Compare heatmap load failed.",
            pareto_message="Compare plot load failed.",
        )

    def _on_compare_plot_canceled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._compare_plot_request_id):
            return
        self._set_compare_busy(False, str(message or "Compare plot load canceled."))

    def _compare_panel_for_slot(self, slot: str) -> Optional[Dict[str, Any]]:
        token = str(slot or "").strip().upper()
        panel = self._compare_stage_panels.get(token)
        return panel if isinstance(panel, dict) else None

    def _render_compare_visuals(self) -> None:
        self._render_compare_overlay()
        self._render_compare_heatmap_selection()
        self._render_compare_focus_curve()
        self._render_compare_slot_panel(
            self._compare_panel_for_slot("D"),
            empty_message="Select candidates to display compare plot.",
        )
        self._render_compare_pareto()

    def _render_compare_focus_curve(self) -> None:
        panel = self._compare_panel_for_slot("C")
        self._render_compare_slot_panel(panel, empty_message="Select candidates to display compare plot.")

    def _render_compare_overlay(self) -> None:
        panel = self._compare_panel_for_slot("B")
        self._render_compare_slot_panel(panel, empty_message="Select candidates to display overlay.")

    def _render_compare_heatmap_selection(self) -> None:
        for slot in ("A", "B", "C", "D"):
            panel = self._compare_panel_for_slot(slot)
            if not isinstance(panel, dict):
                continue
            if str(panel.get("kind") or "").strip().lower() != "heatmap":
                continue
            self._render_compare_heatmap_panel(panel)

    def _render_compare_slot_panel(self, panel: Optional[Dict[str, Any]], *, empty_message: str) -> None:
        if not isinstance(panel, dict):
            return
        kind = str(panel.get("kind") or "").strip().lower()
        metric_key = str(panel.get("metric_key") or "").strip().lower()
        if kind == "heatmap":
            self._render_compare_heatmap_panel(panel)
            return
        if kind == "pareto":
            self._render_compare_pareto_panel(panel, empty_message="Select candidates with available KPI values.")
            return
        if kind == "curve":
            key = metric_key or "beamwidth"
            self._render_compare_curve_panel(panel, metric_key=key, empty_message=empty_message)
            return
        curve_canvas = panel.get("curve_canvas")
        if isinstance(curve_canvas, MetricCurveCanvas):
            curve_canvas.clear_series(empty_message)
        pareto_canvas = panel.get("pareto_canvas")
        if isinstance(pareto_canvas, ParetoScatterCanvas):
            pareto_canvas.clear_points(empty_message)
        heatmap_canvas = panel.get("heatmap_canvas")
        if isinstance(heatmap_canvas, HeatmapCanvas):
            heatmap_canvas.clear_heatmap(empty_message)

    def _render_compare_curve_panel(
        self,
        panel: Dict[str, Any],
        *,
        metric_key: str,
        empty_message: str,
    ) -> None:
        curve_canvas = panel.get("curve_canvas")
        if not isinstance(curve_canvas, MetricCurveCanvas):
            return
        if not self._compare_plot_items:
            curve_canvas.clear_series(empty_message)
            return
        curve_key = str(metric_key or "beamwidth").strip().lower()
        selected_index = (
            int(self._selected_compare_slot_index)
            if self._selected_compare_slot_index is not None and 0 <= int(self._selected_compare_slot_index) < len(self._compare_plot_items)
            else None
        )
        selected_plane = self._compare_plane()
        style_profile = self._curve_style_profile(
            stage_id=self._selected_stage_id(),
            metric_key=curve_key,
            context="compare",
        )
        series: List[Dict[str, Any]] = []
        saturated_bins = 0
        missing_plane_labels: List[str] = []
        for index, item in enumerate(self._compare_plot_items):
            candidate = dict(item.get("candidate") or {})
            plot = dict(item.get("plot") or {})
            stage_plot = dict(plot.get("stage_plot") or {})
            curves = dict(stage_plot.get("curves") or {})
            points = self._stage_curve_points(curves, curve_key)
            if not points:
                planes_present = {str(token).strip().upper() for token in list(candidate.get("planes", []) or []) if str(token).strip()}
                plot_message = str(plot.get("message") or "").strip().lower()
                if selected_plane not in planes_present or "plane not available" in plot_message:
                    missing_plane_labels.append(format_series_label(candidate.get("version_id")))
                continue
            saturated_bins += sum(1 for point in points if bool(point.get("saturated")))
            is_active = bool(selected_index is not None and selected_index == index)
            line_width = 2.0 if is_active else 1.0
            alpha = 1.0 if selected_index is None or is_active else 0.62
            series_row: Dict[str, Any] = {
                "label": format_series_label(candidate.get("version_id")),
                "points": points,
                "color": compare_overlay_color(index),
                "line_width": line_width,
                "alpha": alpha,
            }
            for style_key in ("style", "fill_alpha", "thresholds", "regime_markers", "hotspot_threshold"):
                if style_key in style_profile:
                    series_row[style_key] = style_profile.get(style_key)
            series.append(series_row)
        if not series:
            if missing_plane_labels:
                curve_canvas.clear_series(f"No curve data for {selected_plane}. Missing plane: {', '.join(missing_plane_labels)}")
            elif self._compare_candidates:
                curve_canvas.clear_series("Compute KPIs to populate.")
            else:
                curve_canvas.clear_series(empty_message)
            return
        status = ""
        if curve_key == "beamwidth":
            target = self._selected_target()
            if selected_plane == "H":
                target_deg = float(target.get("h_deg") or 90.0)
            elif selected_plane == "V":
                target_deg = float(target.get("v_deg") or 40.0)
            else:
                target_deg = float((float(target.get("h_deg") or 90.0) + float(target.get("v_deg") or 40.0)) * 0.5)
            freq_union = sorted(
                {
                    float(point.get("freq_hz"))
                    for row in series
                    for point in list(row.get("points", []) or [])
                    if float(point.get("freq_hz") or 0.0) > 0.0
                }
            )
            if freq_union:
                series.append(
                    {
                        "label": "",
                        "show_legend": False,
                        "points": [{"freq_hz": float(freq), "value": float(target_deg)} for freq in freq_union],
                        "color": (140, 145, 160),
                    }
                )
            if saturated_bins > 0:
                status = f"Saturated bins: {saturated_bins} (no -6 dB crossing in available angle range)."
        if missing_plane_labels:
            missing_note = f"Missing {selected_plane}: {', '.join(missing_plane_labels)}."
            status = f"{status} {missing_note}".strip() if status else missing_note
        curve_canvas.set_series(
            series=series,
            x_scale_mode=self._x_axis_mode(),
            x_label="Frequency (Hz, log)" if self._x_axis_mode() == "log" else "Frequency (Hz)",
            y_label=self._stage_curve_y_label(curve_key),
            status=status,
        )

    def _render_compare_heatmap_panel(self, panel: Dict[str, Any]) -> None:
        heatmap_canvas = panel.get("heatmap_canvas")
        if not isinstance(heatmap_canvas, HeatmapCanvas):
            return
        index = int(self.compare_heatmap_selector.currentData() or 0)
        if index < 0 or index >= len(self._compare_plot_items):
            if self._compare_candidates:
                heatmap_canvas.clear_heatmap("Compute KPIs to populate.")
            else:
                heatmap_canvas.clear_heatmap("Select candidate for compare heatmap.")
            return
        item = dict(self._compare_plot_items[index])
        plot = dict(item.get("plot") or {})
        matrix = [list(row) for row in list(plot.get("display_matrix_db", []) or [])]
        if not matrix:
            heatmap_canvas.clear_heatmap(str(plot.get("message") or "No heatmap data for candidate."))
            return
        stage_plot = dict(plot.get("stage_plot") or {})
        overlays = dict(stage_plot.get("heatmap_overlays") or {})
        overlay_profile = self._heatmap_overlay_profile(self._selected_stage_id())
        heatmap_canvas.set_heatmap_data(
            matrix=matrix,
            freqs_hz=[float(value) for value in list(plot.get("display_freqs_hz", []) or [])],
            angles_deg=[float(value) for value in list(plot.get("angles_deg", []) or [])],
            clamp_enabled=bool(self.heatmap_clamp_check.isChecked()),
            clamp_min_db=float(self.heatmap_clamp_min_spin.value()),
            show_raw_bins=bool(self.raw_bins_check.isChecked()),
            ref_angle_deg=(float(plot["ref_angle_deg"]) if plot.get("ref_angle_deg") is not None else None),
            minus6_contour=[dict(item) for item in list(overlays.get("minus6_contour", []) or []) if isinstance(item, dict)],
            target_half_window_deg=(
                float(overlays.get("target_half_window_deg"))
                if overlays.get("target_half_window_deg") is not None
                else float(self._target_half_window_deg_for_plane(self._compare_plane()))
            ),
            show_mirrored_minus6=bool(self._show_mirrored_minus6_contour),
            target_shade_alpha=int(overlay_profile.get("target_shade_alpha", 24)),
            target_boundary_alpha=int(overlay_profile.get("target_boundary_alpha", 140)),
            contour_color=tuple(overlay_profile.get("contour_color", (255, 227, 138))),
            contour_width=float(overlay_profile.get("contour_width", 2.0)),
            status="",
        )

    @staticmethod
    def _candidate_metric_value(
        candidate: Mapping[str, Any],
        *,
        key: str,
        stage_summary: Optional[Mapping[str, Any]] = None,
    ) -> Optional[float]:
        token = str(key or "").strip().lower()
        direct_map = {
            "score": "score",
            "b_pc_oct": "kpi_b_pc_oct",
            "e_bw": "kpi_e_bw",
            "e_cov": "kpi_e_cov",
            "r_spill": "kpi_r_spill",
            "flags_count": "kpi_flags_count",
        }
        if token in direct_map:
            raw = candidate.get(direct_map[token])
            try:
                return float(raw) if raw is not None else None
            except Exception:
                return None
        if stage_summary is None:
            return None
        summary_key = f"{token}_mean"
        try:
            value = stage_summary.get(summary_key)
        except Exception:
            value = None
        try:
            return float(value) if value is not None else None
        except Exception:
            return None

    def _render_compare_pareto(self, _index: int = 0) -> None:
        rendered = False
        for slot in ("A", "B", "C", "D"):
            panel = self._compare_panel_for_slot(slot)
            if not isinstance(panel, dict):
                continue
            if str(panel.get("kind") or "").strip().lower() != "pareto":
                continue
            self._render_compare_pareto_panel(panel, empty_message="Select candidates with available KPI values.")
            rendered = True
        if rendered:
            return
        panel = self._compare_panel_for_slot("D")
        if not isinstance(panel, dict):
            return
        pareto_canvas = panel.get("pareto_canvas")
        if isinstance(pareto_canvas, ParetoScatterCanvas):
            pareto_canvas.clear_points("Pareto panel is not active in this stage.")

    def _render_compare_pareto_panel(self, panel: Dict[str, Any], *, empty_message: str) -> None:
        pareto_canvas = panel.get("pareto_canvas")
        if not isinstance(pareto_canvas, ParetoScatterCanvas):
            return
        x_key = str(self.compare_pareto_x_combo.currentData() or "e_bw").strip().lower()
        y_key = str(self.compare_pareto_y_combo.currentData() or "r_spill").strip().lower()
        x_label = str(self.compare_pareto_x_combo.currentText() or "X")
        y_label = str(self.compare_pareto_y_combo.currentText() or "Y")
        points: List[Dict[str, Any]] = []
        selected_index = (
            int(self._selected_compare_slot_index)
            if self._selected_compare_slot_index is not None and 0 <= int(self._selected_compare_slot_index) < len(self._compare_plot_items)
            else None
        )
        for index, item in enumerate(self._compare_plot_items):
            candidate = dict(item.get("candidate") or {})
            plot = dict(item.get("plot") or {})
            stage_plot = dict(plot.get("stage_plot") or {})
            summary = dict(stage_plot.get("summary") or {})
            x_value = self._candidate_metric_value(candidate, key=x_key, stage_summary=summary)
            y_value = self._candidate_metric_value(candidate, key=y_key, stage_summary=summary)
            if x_value is None or y_value is None:
                continue
            points.append(
                {
                    "label": format_series_label(candidate.get("version_id")),
                    "x_value": float(x_value),
                    "y_value": float(y_value),
                    "color": compare_overlay_color(index),
                    "selected": bool(selected_index is not None and selected_index == index),
                }
            )
        if not points:
            if self._compare_candidates:
                pareto_canvas.clear_points("Compute KPIs to populate.")
            else:
                pareto_canvas.clear_points(empty_message)
            return
        pareto_canvas.set_points(
            points=points,
            x_label=x_label,
            y_label=y_label,
            status="",
        )

    def _cancel_compare_operations(self) -> None:
        self._compare_plot_debounce_timer.stop()
        self._stop_autopick_worker()
        self._stop_compare_plot_worker()
        self._set_compare_busy(False, "Compare operation canceled.")

    def _refresh_saved_analyses(self) -> None:
        if self._source_key() != "project":
            self.compare_analysis_selector.clear()
            self.compare_analysis_selector.addItem("(project source only)", "")
            self.compare_load_btn.setEnabled(False)
            self.compare_save_btn.setEnabled(False)
            return
        self.compare_save_btn.setEnabled(True)
        project_id = str(self._selected_project_id() or "").strip()
        self.compare_analysis_selector.clear()
        if not project_id:
            self.compare_analysis_selector.addItem("(open a project)", "")
            self.compare_load_btn.setEnabled(False)
            return
        rows = self.service.analyzer_list_analyses(project_id=project_id)
        for row in rows:
            analysis_id = str(row.get("analysis_id") or "").strip()
            name = str(row.get("name") or analysis_id)
            updated_at = str(row.get("updated_at") or "")
            self.compare_analysis_selector.addItem(f"{name} ({updated_at})", analysis_id)
        if self.compare_analysis_selector.count() == 0:
            self.compare_analysis_selector.addItem("(no saved analyses)", "")
            self.compare_load_btn.setEnabled(False)
        else:
            self.compare_load_btn.setEnabled(True)

    def _current_analysis_config(self) -> Dict[str, Any]:
        target = self._selected_target()
        band_low_hz, band_high_hz = self._resolved_band_limits()
        return {
            "config_version": 1,
            "artifact_type": "POLAR",
            "stage_mode": self._selected_stage_id(),
            "target_preset_id": str(self.target_selector.currentData() or ""),
            "target_h_deg": float(target.get("h_deg") or 90.0),
            "target_v_deg": float(target.get("v_deg") or 40.0),
            "band_preset_id": str(self.band_selector.currentData() or ""),
            "band_low_hz": float(band_low_hz),
            "band_high_hz": float(band_high_hz),
            "custom_band_low_hz": float(self.custom_band_low_spin.value()),
            "custom_band_high_hz": float(self.custom_band_high_spin.value()),
            "tol_deg": float(self.tol_spin.value()),
            "clamp_enabled": bool(self.heatmap_clamp_check.isChecked()),
            "clamp_min_db": float(self.heatmap_clamp_min_spin.value()),
            "use_full_angles_for_smoothness": bool(self._use_full_angles_for_smoothness),
            "compare": {
                "strategy": str(self._compare_last_strategy),
                "kpi_key": str(self._compare_last_kpi_key),
                "exclude_flags": bool(self._compare_exclude_flags),
                "exclude_missing_kpi": bool(self._compare_exclude_missing),
            },
        }

    def _save_compare_analysis(self) -> None:
        if self._source_key() != "project":
            self._set_compare_busy(False, "Saved analyses are available only for Project source.")
            return
        project_id = str(self._selected_project_id() or "").strip()
        if not project_id:
            self._set_compare_busy(False, "Open a project before saving analyses.")
            return
        if not self._compare_candidates:
            self._set_compare_busy(False, "Add candidates before saving analysis.")
            return
        name, accepted = QInputDialog.getText(self, "Save Analysis", "Analysis name:")
        if not accepted:
            return
        label = str(name or "").strip()
        if not label:
            self._set_compare_busy(False, "Analysis name cannot be empty.")
            return
        result = self.service.analyzer_save_analysis(
            project_id=project_id,
            name=label,
            config=self._current_analysis_config(),
            candidates=list(self._compare_candidates),
            analysis_id=self._loaded_analysis_id,
        )
        self._loaded_analysis_id = str(result.get("analysis_id") or "").strip() or None
        self._refresh_saved_analyses()
        self._set_compare_busy(False, f"Saved analysis '{label}'.")

    def _load_selected_analysis(self) -> None:
        if self._source_key() != "project":
            return
        project_id = str(self._selected_project_id() or "").strip()
        analysis_id = str(self.compare_analysis_selector.currentData() or "").strip()
        if not project_id or not analysis_id:
            return
        payload = self.service.analyzer_load_analysis(project_id=project_id, analysis_id=analysis_id)
        if not isinstance(payload, dict):
            self._set_compare_busy(False, "Selected analysis not found.")
            return
        self._loaded_analysis_id = analysis_id
        config = dict(payload.get("config") or {})
        self._apply_analysis_config(config)
        loaded_candidates = [dict(item) for item in list(payload.get("candidates", []) or []) if isinstance(item, dict)]
        rows_by_identity = {self._compare_identity(row): dict(row) for row in self._all_run_rows}
        candidate_rows: List[Dict[str, Any]] = []
        for candidate in loaded_candidates:
            identity = (
                str(candidate.get("batch_id") or "").strip(),
                str(candidate.get("run_id") or "").strip(),
                str(candidate.get("version_id") or "").strip(),
            )
            resolved = rows_by_identity.get(identity)
            if resolved is not None:
                candidate_rows.append(resolved)
            else:
                candidate_rows.append(
                    {
                        "project_id": project_id,
                        "batch_id": identity[0],
                        "run_id": identity[1] or None,
                        "version_id": identity[2],
                        "run_label": identity[1] or "(no run id)",
                    }
                )
        self._set_compare_candidates(candidate_rows, message=f"Loaded analysis '{payload.get('name')}'.")

    def _apply_analysis_config(self, config: Dict[str, Any]) -> None:
        self._control_sync_guard = True
        try:
            self._set_combo_current_by_data(self.stage_selector, str(config.get("stage_mode") or self._default_stage_id))
            self._set_combo_current_by_data(
                self.target_selector,
                str(config.get("target_preset_id") or self._default_coverage_preset_id),
            )
            self._set_combo_current_by_data(
                self.band_selector,
                str(config.get("band_preset_id") or self._default_band_preset_id),
            )
            self.custom_band_low_spin.setValue(float(config.get("custom_band_low_hz") or self.custom_band_low_spin.value()))
            self.custom_band_high_spin.setValue(float(config.get("custom_band_high_hz") or self.custom_band_high_spin.value()))
            self.tol_spin.setValue(float(config.get("tol_deg") or self.tol_spin.value()))
            self.heatmap_clamp_check.setChecked(bool(config.get("clamp_enabled", True)))
            self.heatmap_clamp_min_spin.setValue(float(config.get("clamp_min_db") or self.heatmap_clamp_min_spin.value()))
            self._use_full_angles_for_smoothness = bool(
                config.get("use_full_angles_for_smoothness", self._use_full_angles_for_smoothness)
            )
            compare_cfg = dict(config.get("compare") or {})
            self._compare_last_strategy = str(compare_cfg.get("strategy") or self._compare_last_strategy)
            self._compare_last_kpi_key = str(compare_cfg.get("kpi_key") or self._compare_last_kpi_key)
            self._compare_exclude_flags = bool(compare_cfg.get("exclude_flags", self._compare_exclude_flags))
            self._compare_exclude_missing = bool(compare_cfg.get("exclude_missing_kpi", self._compare_exclude_missing))
        finally:
            self._control_sync_guard = False
        self._sync_band_custom_visibility()
        self._apply_stage_defaults(include_filters=False)

    def _open_compare_autopick_dialog(self) -> None:
        if self._source_key() != "project":
            self._set_compare_busy(False, "Auto-pick uses project-local cached KPIs only.")
            return
        project_id = str(self._selected_project_id() or "").strip()
        if not project_id:
            self._set_compare_busy(False, "Open a project before auto-pick.")
            return
        batch_rows = self.service.analyzer_list_polar_batches(project_id=project_id, source="project")
        batch_ids = [str(row.get("batch_id") or "").strip() for row in batch_rows if str(row.get("batch_id") or "").strip()]
        dialog = _AnalyzerAutoPickDialog(
            batch_ids=batch_ids,
            current_batch_id=self._selected_batch_id(),
            strategy=self._compare_last_strategy,
            kpi_key=self._compare_last_kpi_key,
            exclude_flags=self._compare_exclude_flags,
            exclude_missing_kpi=self._compare_exclude_missing,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.payload()
        if not isinstance(payload, dict):
            return
        scope = str(payload.get("scope") or "current")
        selected_batches = [str(item) for item in list(payload.get("batch_ids", []) or []) if str(item).strip()]
        if scope == "current":
            current_batch = str(self._selected_batch_id() or "").strip()
            if not current_batch:
                self._set_compare_busy(False, "Select a batch before using current-scope auto-pick.")
                return
            selected_batches = [current_batch] if current_batch else []
        if scope == "multi" and not selected_batches:
            self._set_compare_busy(False, "Select at least one batch for multi-batch auto-pick.")
            return
        self._compare_last_strategy = str(payload.get("strategy") or "A")
        self._compare_last_kpi_key = str(payload.get("kpi_key") or "score")
        filters = dict(payload.get("filters") or {})
        self._compare_exclude_flags = bool(filters.get("exclude_flags", self._compare_exclude_flags))
        self._compare_exclude_missing = bool(filters.get("exclude_missing_kpi", self._compare_exclude_missing))
        self._start_autopick_worker(
            project_id=project_id,
            batch_ids=selected_batches,
            strategy=self._compare_last_strategy,
            kpi_key=self._compare_last_kpi_key,
            filters={
                "exclude_flags": self._compare_exclude_flags,
                "exclude_missing_kpi": self._compare_exclude_missing,
            },
            top_n=5,
        )

    def _start_autopick_worker(
        self,
        *,
        project_id: str,
        batch_ids: Sequence[str],
        strategy: str,
        kpi_key: str,
        filters: Dict[str, Any],
        top_n: int,
    ) -> None:
        self._stop_autopick_worker()
        self._autopick_request_id += 1
        request_id = int(self._autopick_request_id)
        config = self._active_kpi_config()
        worker = _AnalyzerAutoPickWorker(
            service=self.service,
            request_id=request_id,
            project_id=project_id,
            batch_ids=batch_ids,
            strategy=strategy,
            kpi_key=kpi_key,
            filters=filters,
            top_n=top_n,
            stage_mode=str(config["stage_mode"]),
            band_low_hz=float(config["band_low_hz"]),
            band_high_hz=float(config["band_high_hz"]),
            target_h_deg=float(config["target_h_deg"]),
            target_v_deg=float(config["target_v_deg"]),
            tol_deg=float(config["tol_deg"]),
            algo_version=str(config["algo_version"]),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_autopick_progress)
        worker.finished.connect(self._on_autopick_finished)
        worker.failed.connect(self._on_autopick_failed)
        worker.canceled.connect(self._on_autopick_canceled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.canceled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_autopick_worker_refs(thread))
        self._autopick_worker = worker
        self._autopick_thread = thread
        self._set_compare_busy(True, "Auto-picking candidates...")
        thread.start()

    def _on_autopick_progress(self, done: int, total: int, message: str) -> None:
        done_value = max(int(done), 0)
        total_value = max(int(total), 0)
        if total_value <= 0:
            self._set_compare_busy(True, str(message or "Auto-picking candidates..."))
            return
        self._set_compare_busy(True, f"{done_value}/{total_value} {str(message or '').strip()}")

    def _on_autopick_finished(self, request_id: int, payload: Dict[str, Any]) -> None:
        if int(request_id) != int(self._autopick_request_id):
            return
        candidates = [dict(item) for item in list(payload.get("candidates", []) or []) if isinstance(item, dict)]
        message = str(payload.get("message") or "").strip()
        if not message:
            message = f"Auto-picked {len(candidates)} candidates."
        self._set_compare_candidates(candidates, message=message)

    def _on_autopick_failed(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._autopick_request_id):
            return
        self._set_compare_busy(False, "Auto-pick failed.")
        self._set_error(str(message or "Auto-pick failed."))

    def _on_autopick_canceled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._autopick_request_id):
            return
        self._set_compare_busy(False, str(message or "Auto-pick canceled."))

    def _apply_overview_payload(self, payload: Dict[str, Any]) -> None:
        projects = [dict(item) for item in list(payload.get("projects", []) or []) if isinstance(item, dict)]
        batches = [dict(item) for item in list(payload.get("batches", []) or []) if isinstance(item, dict)]
        active_project_id = str(payload.get("project_id") or "").strip() or None
        active_batch_id = str(payload.get("batch_id") or "").strip() or None

        if self._source_key() == "project" and self._project_context_id:
            found_context = any(str(item.get("project_id") or "").strip() == self._project_context_id for item in projects)
            if not found_context:
                projects.insert(
                    0,
                    {
                        "project_id": self._project_context_id,
                        "measurement_count": 0,
                        "batch_count": 0,
                    },
                )
            active_project_id = self._project_context_id

        self._selector_sync_guard = True
        try:
            self.project_selector.clear()
            for row in projects:
                project_id = str(row.get("project_id") or "").strip()
                if not project_id:
                    continue
                batch_count = int(row.get("batch_count") or 0)
                measurement_count = int(row.get("measurement_count") or 0)
                label = f"{project_id} ({batch_count} batches, {measurement_count} measurements)"
                self.project_selector.addItem(label, project_id)
            if self.project_selector.count() == 0:
                self.project_selector.addItem("(no polar data)", "")
            self._set_combo_current_by_data(self.project_selector, active_project_id)
            self.project_selector.setEnabled(not (self._source_key() == "project" and bool(self._project_context_id)))

            self.batch_selector.clear()
            for row in batches:
                batch_id = str(row.get("batch_id") or "").strip()
                if not batch_id:
                    continue
                batch_name = str(row.get("batch_name") or "").strip()
                runs = int(row.get("run_version_count") or 0)
                measurements = int(row.get("measurement_count") or 0)
                count_text = f"{runs} run/version, {measurements} measurements"
                if batch_name and batch_name != batch_id:
                    label = f"{batch_id} | {batch_name} ({count_text})"
                else:
                    label = f"{batch_id} ({count_text})"
                self.batch_selector.addItem(label, batch_id)
                self.batch_selector.setItemData(self.batch_selector.count() - 1, label, Qt.ToolTipRole)
            if self.batch_selector.count() == 0:
                self.batch_selector.addItem("(no polar batches)", "")
            self._set_combo_current_by_data(self.batch_selector, active_batch_id)
        finally:
            self._selector_sync_guard = False
        self._ath_all_param_rows_by_version.clear()
        self._reload_project_ui_prefs()
        self._sync_batch_selector_tooltip()
        self._apply_runs_payload(payload)
        self._refresh_saved_analyses()

    def _set_combo_current_by_data(self, combo: QComboBox, value: Optional[str]) -> None:
        token = str(value or "").strip()
        if not token:
            if combo.count() > 0:
                combo.setCurrentIndex(0)
            return
        for index in range(combo.count()):
            if str(combo.itemData(index) or "").strip().lower() == token.lower():
                combo.setCurrentIndex(index)
                return
        if combo.count() > 0:
            combo.setCurrentIndex(0)

    @staticmethod
    def _run_identity(row: Dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row.get("batch_id") or "").strip(),
            str(row.get("run_id") or "").strip(),
            str(row.get("version_id") or "").strip(),
        )

    def _select_run_table_row_by_identity(self, target_identity: tuple[str, str, str]) -> bool:
        for row_index in range(self.run_table.rowCount()):
            item = self.run_table.item(row_index, self.COL_RUN_ID)
            if item is None:
                continue
            row_payload = dict(item.data(Qt.UserRole) or {})
            if self._run_identity(row_payload) == target_identity:
                self.run_table.selectRow(row_index)
                return True
        return False

    def _on_run_selector_changed(self, _index: int = 0) -> None:
        if self._run_selector_sync_guard:
            self._sync_version_stepper()
            return
        payload = dict(self.run_selector.currentData() or {})
        if not payload:
            self._sync_version_stepper()
            return
        target_identity = self._run_identity(payload)
        self._select_run_table_row_by_identity(target_identity)
        self._sync_version_stepper()

    def _open_version_picker(self) -> None:
        entries: List[Dict[str, Any]] = []
        for row in list(self._filtered_rows()):
            if not isinstance(row, dict):
                continue
            selection = f"{str(row.get('batch_id') or '--')}/{str(row.get('version_id') or '--')}"
            planes = "/".join(str(item) for item in list(row.get("planes", []) or []))
            score = self._format_float(row.get("kpi_score"), 2)
            label = f"{selection}   Planes: {planes or '--'}   Score: {score}"
            entries.append({"label": label, "payload": dict(row)})
        if not entries:
            return
        current_identity = self._run_identity(self._selected_detail_payload)
        dialog = _AnalyzerVersionPickerDialog(entries=entries, current_identity=current_identity, parent=self)
        anchor = self.versions_btn.mapToGlobal(QPoint(0, self.versions_btn.height() + 2))
        dialog.move(anchor)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.selected_payload()
        if not payload:
            return
        target_identity = self._run_identity(payload)
        self._run_selector_sync_guard = True
        for index in range(self.run_selector.count()):
            row_payload = dict(self.run_selector.itemData(index) or {})
            if self._run_identity(row_payload) == target_identity:
                self.run_selector.setCurrentIndex(index)
                break
        self._run_selector_sync_guard = False
        self._on_run_selector_changed()
        self._sync_version_stepper()

    def _open_flags_help_dialog(self) -> None:
        payload = dict(self._selected_detail_payload or {})
        if not payload:
            return
        reason_items = self._reason_items(payload)
        dialog = _AnalyzerFlagsHelpDialog(reason_items=reason_items, parent=self)
        anchor = self.flags_help_btn.mapToGlobal(QPoint(0, self.flags_help_btn.height() + 2))
        dialog.move(anchor)
        dialog.exec()

    def _open_run_details_dialog(self) -> None:
        payload = dict(self._selected_detail_payload or {})
        if not payload:
            return
        ath_rows = [row for row in self._version_param_rows(payload) if bool(row.get("is_set"))]
        dialog = _AnalyzerRunDetailsDialog(
            payload=payload,
            ath_param_rows=ath_rows,
            visible_ath_keys=list(self._ath_visible_param_keys),
            on_toggle_ath_param=self._set_ath_param_visibility,
            max_visible_ath_params=int(self._ath_visible_param_limit),
            parent=self,
        )
        dialog.exec()

    @staticmethod
    def _format_angle(value: Any) -> str:
        if value is None:
            return "--"
        try:
            return f"{float(value):.2f}"
        except Exception:
            return str(value)

    @staticmethod
    def _format_float(value: Any, digits: int = 2) -> str:
        if value is None:
            return "--"
        try:
            return f"{float(value):.{digits}f}"
        except Exception:
            return str(value)

    @staticmethod
    def _format_param_value(value: Any) -> str:
        if value is None:
            return "--"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            if float(value).is_integer():
                return str(int(value))
            return f"{float(value):.3f}".rstrip("0").rstrip(".")
        if isinstance(value, Mapping):
            entries = [f"{str(k)}={AnalysePage._format_param_value(v)}" for k, v in list(dict(value).items())[:4]]
            return "{" + ", ".join(entries) + (" ..." if len(list(dict(value).items())) > 4 else "") + "}"
        if isinstance(value, list):
            preview = ", ".join(AnalysePage._format_param_value(item) for item in list(value)[:4])
            return "[" + preview + (" ..." if len(list(value)) > 4 else "") + "]"
        return str(value)

    def _reload_project_ui_prefs(self) -> None:
        project_id = str(self._selected_project_id() or "").strip()
        if not project_id or self._source_key() != "project":
            self._ath_visible_param_keys = []
            self._pinned_version_tokens = set()
            self._refresh_version_pin_button(enabled=False, pinned=False)
            return
        payload = self.service.analyzer_get_ui_pref(project_id=project_id, pref_key=self._ath_visible_pref_key)
        raw_keys = list(payload.get("visible_keys", []) or []) if isinstance(payload, dict) else []
        seen: set[str] = set()
        ordered: List[str] = []
        for raw in raw_keys:
            key = str(raw or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)
        limit = max(1, int(getattr(self, "_ath_visible_param_limit", 5) or 5))
        if len(ordered) > limit:
            LOGGER.info(
                "Analyzer ATH visible params clamped to %s entries for project %s (had %s).",
                int(limit),
                str(project_id),
                len(ordered),
            )
            ordered = ordered[:limit]
        self._ath_visible_param_keys = ordered
        pin_payload = self.service.analyzer_get_ui_pref(project_id=project_id, pref_key=self._version_pin_pref_key)
        raw_pin_keys = list(pin_payload.get("keys", []) or []) if isinstance(pin_payload, dict) else []
        self._pinned_version_tokens = {str(token or "").strip() for token in raw_pin_keys if str(token or "").strip()}
        self._apply_pin_state_to_rows()
        self._refresh_version_pin_button(
            enabled=bool(self._source_key() == "project" and self._has_version_pin_identity(self._selected_detail_payload)),
            pinned=self._is_version_pinned(self._selected_detail_payload),
        )

    @staticmethod
    def _version_pin_identity(payload: Mapping[str, Any]) -> Tuple[str, str, str, str]:
        return (
            str(payload.get("project_id") or "").strip(),
            str(payload.get("batch_id") or "").strip(),
            str(payload.get("version_id") or "").strip(),
            str(payload.get("run_id") or "").strip(),
        )

    @staticmethod
    def _version_pin_token(identity: Tuple[str, str, str, str]) -> str:
        return "|".join(
            (
                str(identity[0] or "").strip(),
                str(identity[1] or "").strip(),
                str(identity[2] or "").strip(),
                str(identity[3] or "").strip(),
            )
        )

    def _has_version_pin_identity(self, payload: Mapping[str, Any]) -> bool:
        identity = self._version_pin_identity(payload)
        return bool(identity[0] and identity[1] and identity[2])

    def _is_version_pinned(self, payload: Mapping[str, Any]) -> bool:
        identity = self._version_pin_identity(payload)
        if not identity[0] or not identity[1] or not identity[2]:
            return False
        return self._version_pin_token(identity) in self._pinned_version_tokens

    @staticmethod
    def _build_pin_icon(*, pinned: bool) -> QIcon:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        accent = QColor("#9A86CC") if pinned else QColor("#A7AFBB")
        pen = QPen(accent)
        pen.setWidthF(1.35)
        painter.setPen(pen)
        painter.setBrush(accent if pinned else Qt.NoBrush)
        painter.drawEllipse(5, 1, 6, 6)
        painter.drawLine(8, 7, 8, 13)
        painter.drawLine(6, 11, 10, 11)
        painter.end()
        return QIcon(pixmap)

    def _set_version_info_pin_highlight(self, pinned: bool) -> None:
        self.kpi_controls_tile.setProperty("analyzerPinned", bool(pinned))
        style = self.kpi_controls_tile.style()
        if style is not None:
            style.unpolish(self.kpi_controls_tile)
            style.polish(self.kpi_controls_tile)
        self.kpi_controls_tile.update()

    def _refresh_version_pin_button(self, *, enabled: bool, pinned: bool) -> None:
        self._pin_sync_guard = True
        self.version_pin_btn.setEnabled(bool(enabled))
        self.version_pin_btn.setChecked(bool(enabled and pinned))
        self.version_pin_btn.setIcon(self._build_pin_icon(pinned=bool(enabled and pinned)))
        if not enabled:
            self.version_pin_btn.setToolTip("Pin is available for project-backed Batch/Version selections.")
        elif pinned:
            self.version_pin_btn.setToolTip("Pinned for this Batch/Version. Click to unpin.")
        else:
            self.version_pin_btn.setToolTip("Pin this Batch/Version for quick comparison.")
        self._pin_sync_guard = False
        self._set_version_info_pin_highlight(bool(enabled and pinned))

    def _apply_pin_state_to_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        token = self._version_pin_token(self._version_pin_identity(row))
        normalized = dict(row)
        normalized["version_pinned"] = bool(token and token in self._pinned_version_tokens)
        return normalized

    def _apply_pin_state_to_rows(self) -> None:
        self._all_run_rows = [self._apply_pin_state_to_row(dict(row)) for row in self._all_run_rows if isinstance(row, dict)]
        self._compare_candidates = [
            self._apply_pin_state_to_row(dict(candidate))
            for candidate in self._compare_candidates
            if isinstance(candidate, dict)
        ]
        if self._selected_detail_payload:
            self._selected_detail_payload = self._apply_pin_state_to_row(dict(self._selected_detail_payload))

    def _persist_version_pin_pref(self) -> None:
        project_id = str(self._selected_project_id() or "").strip()
        if not project_id or self._source_key() != "project":
            return
        keys = sorted(self._pinned_version_tokens)
        self.service.analyzer_set_ui_pref(
            project_id=project_id,
            pref_key=self._version_pin_pref_key,
            payload={"keys": keys},
        )

    def _on_version_pin_toggled(self, checked: bool) -> None:
        if self._pin_sync_guard:
            return
        payload = dict(self._selected_detail_payload or {})
        identity = self._version_pin_identity(payload)
        if not identity[0] or not identity[1] or not identity[2]:
            self._refresh_version_pin_button(enabled=False, pinned=False)
            return
        token = self._version_pin_token(identity)
        if checked:
            self._pinned_version_tokens.add(token)
        else:
            self._pinned_version_tokens.discard(token)
        self._persist_version_pin_pref()
        self._apply_pin_state_to_rows()
        self._refresh_version_pin_button(
            enabled=bool(self._source_key() == "project" and self._has_version_pin_identity(payload)),
            pinned=bool(checked),
        )
        self._refresh_run_table()
        self._update_compare_slots()

    def _persist_ath_visible_pref(self) -> None:
        project_id = str(self._selected_project_id() or "").strip()
        if not project_id or self._source_key() != "project":
            return
        limit = max(1, int(getattr(self, "_ath_visible_param_limit", 5) or 5))
        sanitized = list(self._ath_visible_param_keys)[:limit]
        if sanitized != list(self._ath_visible_param_keys):
            self._ath_visible_param_keys = sanitized
        self.service.analyzer_set_ui_pref(
            project_id=project_id,
            pref_key=self._ath_visible_pref_key,
            payload={"visible_keys": list(sanitized)},
        )

    def _set_ath_param_visibility(self, key: str, visible: bool) -> None:
        token = str(key or "").strip()
        if not token:
            return
        current = list(self._ath_visible_param_keys)
        limit = max(1, int(getattr(self, "_ath_visible_param_limit", 5) or 5))
        if visible and token not in current:
            if len(current) >= limit:
                return
            current.append(token)
        if not visible and token in current:
            current = [item for item in current if item != token]
        self._ath_visible_param_keys = current
        self._persist_ath_visible_pref()
        self._update_version_information_panel(dict(self._selected_detail_payload or {}))

    def _version_identity_key(self, payload: Mapping[str, Any]) -> Tuple[str, str, str]:
        return (
            str(payload.get("project_id") or "").strip(),
            str(payload.get("batch_id") or "").strip(),
            str(payload.get("version_id") or "").strip(),
        )

    def _version_param_rows(self, payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
        identity = self._version_identity_key(payload)
        if not all(identity):
            return []
        if identity in self._ath_all_param_rows_by_version:
            return [dict(item) for item in list(self._ath_all_param_rows_by_version.get(identity, []))]
        rows = self.service.analyzer_list_version_param_rows(
            project_id=identity[0],
            batch_id=identity[1],
            version_id=identity[2],
        )
        normalized = [dict(item) for item in list(rows or []) if isinstance(item, dict)]
        self._ath_all_param_rows_by_version[identity] = normalized
        return [dict(item) for item in normalized]

    def _visible_ath_param_lines(self, payload: Mapping[str, Any]) -> List[str]:
        if not self._ath_visible_param_keys:
            return ["ATH params: use Details -> ATH Params to pick visible keys."]
        identity = self._version_identity_key(payload)
        if not all(identity):
            return ["ATH params: --"]
        visible_keys = list(self._ath_visible_param_keys)[: int(self._ath_visible_param_limit)]
        values = self.service.analyzer_version_param_values(
            project_id=identity[0],
            batch_id=identity[1],
            version_id=identity[2],
            keys=visible_keys,
        )
        lines: List[str] = []
        for key in visible_keys:
            if key not in values:
                lines.append(f"{key}: --")
                continue
            lines.append(f"{key}: {self._format_param_value(values.get(key))}")
        return lines or ["ATH params: --"]

    @staticmethod
    def _split_key_value_line(line: str) -> Tuple[str, str]:
        text = str(line or "").strip()
        if not text:
            return ("--", "--")
        if ":" not in text:
            return (text, "--")
        key, value = text.split(":", 1)
        return (str(key or "").strip() or "--", str(value or "").strip() or "--")

    @staticmethod
    def _styled_key_value_text(key_text: str, value_text: str) -> str:
        key = html.escape(str(key_text or "").strip() or "--")
        value = html.escape(str(value_text or "").strip() or "--")
        return (
            "<span style='color:#A2A2A2;'>"
            + key
            + "</span>: <span style='color:#E2E2E2;'>"
            + value
            + "</span>"
        )

    def _render_ath_param_lines(self, lines: Sequence[str]) -> None:
        entries = [self._split_key_value_line(item) for item in list(lines or []) if str(item or "").strip()]
        entries = entries[: int(self._ath_visible_param_limit)]
        for key_label, value_label in zip(self._version_ath_param_key_labels, self._version_ath_param_value_labels):
            key_label.setVisible(False)
            value_label.setVisible(False)
            key_label.setText("--")
            value_label.set_full_text("--")
        if not entries:
            self.version_ath_params_empty_label.set_full_text("ATH params: --")
            self.version_ath_params_empty_label.setVisible(True)
            return
        self.version_ath_params_empty_label.setVisible(False)
        for idx, (key_text, value_text) in enumerate(entries):
            key_label = self._version_ath_param_key_labels[idx]
            value_label = self._version_ath_param_value_labels[idx]
            key_label.setText(f"{key_text}:")
            key_label.setToolTip(key_text)
            value_label.set_full_text(value_text)
            key_label.setVisible(True)
            value_label.setVisible(True)

    def _update_version_note_counter(self, *, remaining: int) -> None:
        self.version_note_counter.setText(f"{max(int(remaining), 0)} left")

    def _on_version_note_text_changed(self) -> None:
        if self._note_sync_guard:
            return
        text = str(self.version_note_edit.toPlainText() or "")
        if len(text) > int(self._version_note_max_chars):
            self._note_sync_guard = True
            cursor = self.version_note_edit.textCursor()
            self.version_note_edit.setPlainText(text[: int(self._version_note_max_chars)])
            cursor.setPosition(min(cursor.position(), int(self._version_note_max_chars)))
            self.version_note_edit.setTextCursor(cursor)
            self._note_sync_guard = False
            text = str(self.version_note_edit.toPlainText() or "")
        remaining = int(self._version_note_max_chars) - len(text)
        self._update_version_note_counter(remaining=remaining)
        identity = self._version_identity_key(self._selected_detail_payload)
        if not all(identity):
            return
        self._pending_note_context = identity
        self._pending_note_text = text
        self._note_save_timer.start()

    def _persist_pending_version_note(self) -> None:
        context = self._pending_note_context
        if context is None:
            return
        project_id, batch_id, version_id = context
        if not project_id or not batch_id or not version_id:
            return
        self.service.analyzer_set_version_note(
            project_id=project_id,
            batch_id=batch_id,
            version_id=version_id,
            note_text=self._pending_note_text,
        )
        if (
            str(self._selected_detail_payload.get("project_id") or "").strip() == project_id
            and str(self._selected_detail_payload.get("batch_id") or "").strip() == batch_id
            and str(self._selected_detail_payload.get("version_id") or "").strip() == version_id
        ):
            self._selected_detail_payload["version_note"] = self._pending_note_text
            self._selected_detail_payload["version_note_updated_at"] = (
                datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            )

    @staticmethod
    def _render_dim_key_value(label_text: str, value_text: str) -> str:
        key = html.escape(str(label_text or "").strip())
        value = html.escape(str(value_text or "--").strip() or "--")
        return f"<span style='color:#A2A2A2'>{key}</span>: <span style='color:#E6E6E6'>{value}</span>"

    def _stage_version_metric_keys(self) -> List[str]:
        stage_id = self._selected_stage_id()
        configured = VERSION_INFO_STAGE_METRICS.get(stage_id)
        if configured:
            return [str(key) for key in configured]
        return [str(key) for key in VERSION_INFO_STAGE_METRICS.get(DEFAULT_STAGE_ID, ("score", "flags"))]

    @staticmethod
    def _version_aggregate_payload(data: Dict[str, Any]) -> Dict[str, Any]:
        return dict(dict(data.get("kpi", {}) or {}).get("aggregate", {}) or {})

    def _version_metric_value_text(self, data: Dict[str, Any], metric_key: str) -> str:
        token = str(metric_key or "").strip().lower()
        if token == "flags":
            return self._flags_text(data)
        if token == "score":
            return self._format_float(data.get("kpi_score"), 2)
        direct_field_map = {
            "b_pc_oct": "kpi_b_pc_oct",
            "e_bw": "kpi_e_bw",
            "e_cov": "kpi_e_cov",
            "r_spill": "kpi_r_spill",
        }
        value = None
        field_name = direct_field_map.get(token)
        if field_name:
            value = data.get(field_name)
        if value is None:
            value = self._version_aggregate_payload(data).get(token)
        digits = int(dict(VERSION_INFO_METRIC_META.get(token, {}) or {}).get("digits", 2) or 2)
        return self._format_float(value, digits)

    def _sync_version_metric_rows(self, data: Dict[str, Any]) -> None:
        metric_keys = self._stage_version_metric_keys()
        hint = "Compute KPIs to populate this metric."
        for index, row in enumerate(self._version_info_metric_rows):
            key_label = row.get("key_label")
            value_label = row.get("value_label")
            if not isinstance(key_label, QLabel) or not isinstance(value_label, QLabel):
                continue
            if index >= len(metric_keys):
                row["metric_key"] = ""
                key_label.setVisible(False)
                value_label.setVisible(False)
                continue
            metric_key = str(metric_keys[index] or "").strip().lower()
            meta = dict(VERSION_INFO_METRIC_META.get(metric_key, {}) or {})
            tip = str(meta.get("tip") or "")
            row["metric_key"] = metric_key
            key_label.setVisible(True)
            value_label.setVisible(True)
            key_label.setText(str(meta.get("label") or metric_key))
            key_label.setToolTip(tip)
            value_text = self._version_metric_value_text(data, metric_key) if data else "--"
            value_label.setText(value_text)
            if value_text == "--":
                value_label.setToolTip(f"{tip}\n{hint}" if tip else hint)
            else:
                value_label.setToolTip(tip)

    def _update_version_information_panel(self, payload: Dict[str, Any]) -> None:
        data = dict(payload or {})
        self._sync_version_metric_rows(data)
        if not data:
            self.version_dims_label.set_full_text("--")
            for label in self._version_chip_labels.values():
                label.setText("--")
                label.setToolTip("missing")
            self.version_sweep_value_label.set_full_text("--")
            self._render_ath_param_lines(["ATH params: --"])
            self._refresh_version_pin_button(enabled=False, pinned=False)
            self.version_note_edit.setEnabled(False)
            self._note_sync_guard = True
            self.version_note_edit.setPlainText("")
            self._note_sync_guard = False
            self._update_version_note_counter(remaining=self._version_note_max_chars)
            return

        length_mm = data.get("ath_length_mm")
        width_mm = data.get("ath_width_mm")
        height_mm = data.get("ath_height_mm")
        if None in (length_mm, width_mm, height_mm):
            self.version_dims_label.set_full_text("--")
            self.version_dims_label.setToolTip("missing")
        else:
            self.version_dims_label.set_full_text(
                f"{float(length_mm):.1f} x {float(width_mm):.1f} x {float(height_mm):.1f} mm"
            )
            self.version_dims_label.setToolTip("Final dimensions (L x W x H).")

        def _mode_text(mapping: Dict[int, str], raw_value: Any, default: str) -> str:
            try:
                token = int(float(raw_value))
            except Exception:
                return default
            return mapping.get(token, default)

        throat_text = _mode_text({1: "OSSE", 2: "R-OSSE", 3: "Circular Arc"}, data.get("throat_profile"), "--")
        gcurve_text = _mode_text({0: "No GCurve", 1: "Superellipse", 2: "Superformula"}, data.get("gcurve_type"), "No GCurve")
        morph_text = _mode_text({0: "No Morph", 1: "Rectangle", 2: "Circle"}, data.get("morph_shape"), "No Morph")
        enclosure_text = "Enclosure" if bool(data.get("enclosure_enabled")) else "No Enclosure"
        chip_values = {
            "throat": ("Throat", throat_text),
            "gcurve": ("GCurve", gcurve_text),
            "morph": ("Morph", morph_text),
            "driver": ("Driver", str(data.get("driver_label") or "Generic25")),
            "enclosure": ("Enclosure", enclosure_text),
        }
        for key, label in self._version_chip_labels.items():
            pair = chip_values.get(key)
            if not isinstance(pair, tuple):
                label.setText("--")
                label.setToolTip("missing")
                continue
            key_text = str(pair[0] or "--")
            value_text = str(pair[1] or "--")
            label.setText(self._styled_key_value_text(key_text, value_text))
            label.setToolTip(f"{key_text}: {value_text}" if value_text != "--" else "missing")

        sweep_params = dict(data.get("sweep_parameters") or {})
        if sweep_params:
            lines = [f"{name}: {self._format_param_value(value)}" for name, value in list(sweep_params.items())[:3]]
            if len(sweep_params) > 3:
                lines.append(f"+{len(sweep_params) - 3} more")
            self.version_sweep_value_label.set_full_text(" | ".join(lines))
        else:
            self.version_sweep_value_label.set_full_text("--")

        ath_lines = self._visible_ath_param_lines(data)
        self._render_ath_param_lines(ath_lines)

        note_text = str(data.get("version_note") or "")
        can_edit_note = bool(self._source_key() == "project" and all(self._version_identity_key(data)))
        self._note_sync_guard = True
        self.version_note_edit.setEnabled(can_edit_note)
        self.version_note_edit.setPlainText(note_text[: int(self._version_note_max_chars)])
        self._note_sync_guard = False
        self._update_version_note_counter(
            remaining=int(self._version_note_max_chars) - len(str(self.version_note_edit.toPlainText() or ""))
        )
        self._refresh_version_pin_button(
            enabled=bool(self._source_key() == "project" and self._has_version_pin_identity(data)),
            pinned=self._is_version_pinned(data),
        )

    @staticmethod
    def _row_has_warning(row: Dict[str, Any]) -> bool:
        reason_items = AnalysePage._reason_items(row, include_info=True)
        if any(str(item.get("severity") or "").lower() in {"warn", "error"} for item in reason_items):
            return True
        status = str(row.get("run_status") or "").strip().lower()
        if not status:
            return False
        return any(token in status for token in ("warn", "fail", "error"))

    @staticmethod
    def _reason_items(row: Dict[str, Any], *, include_info: bool = False) -> List[Dict[str, Any]]:
        direct = [dict(item) for item in list(row.get("kpi_reason_items", []) or []) if isinstance(item, dict)]
        if direct:
            items = direct
        else:
            codes = [str(code) for code in list(row.get("kpi_reason_codes", []) or []) if str(code).strip()]
            items = reason_items_for_codes(codes)
        normalized: List[Dict[str, Any]] = []
        for item in items:
            code = str(item.get("code") or "").strip().upper()
            if not code:
                continue
            severity = str(item.get("severity") or "warn").strip().lower()
            entry = {
                "code": code,
                "severity": severity,
                "summary": str(item.get("summary") or ""),
                "impact": str(item.get("impact") or ""),
                "action": str(item.get("action") or ""),
            }
            normalized.append(entry)
        if include_info:
            return normalized
        return [item for item in normalized if str(item.get("severity") or "").lower() != "info"]

    @staticmethod
    def _flags_text(row: Dict[str, Any]) -> str:
        reason_items = AnalysePage._reason_items(row)
        flags_count = int(row.get("kpi_flags_count") or 0) if row.get("kpi_score") is not None else None
        if flags_count is None:
            if any(str(item.get("code") or "").upper() == "MISSING_KPI_ROWS" for item in reason_items):
                return "missing"
            if reason_items:
                first = reason_items[0]
                return f"{str(first.get('severity') or 'warn').upper()}:{str(first.get('code') or '')}"
            return "--"
        warn_count = sum(1 for item in reason_items if str(item.get("severity") or "").lower() == "warn")
        error_count = sum(1 for item in reason_items if str(item.get("severity") or "").lower() == "error")
        tags: List[str] = []
        if error_count > 0:
            tags.append(f"{error_count}E")
        if warn_count > 0:
            tags.append(f"{warn_count}W")
        if tags:
            return f"{flags_count} ({'/'.join(tags)})"
        return str(flags_count)

    def _sync_band_custom_visibility(self) -> None:
        is_custom = str(self.band_selector.currentData() or "") == "custom"
        self.custom_band_low_spin.setEnabled(bool(is_custom))
        self.custom_band_high_spin.setEnabled(bool(is_custom))
        self.custom_band_low_label.setEnabled(bool(is_custom))
        self.custom_band_high_label.setEnabled(bool(is_custom))
        self.heatmap_clamp_min_spin.setEnabled(bool(self.heatmap_clamp_check.isChecked()))
        self._update_toolbar_context_chips()

    def _update_toolbar_context_chips(self) -> None:
        self.compute_btn.setText("Refresh KPIs")

    def _apply_stage_defaults(self, *, include_filters: bool = True) -> None:
        stage = dict(self._stage_presets.get(self._selected_stage_id(), {}) or {})
        if include_filters:
            filters = dict(stage.get("filters", {}) or {})
            self._control_sync_guard = True
            try:
                self.exclude_flagged_check.setChecked(bool(filters.get("exclude_flagged", False)))
                self.exclude_warnings_check.setChecked(bool(filters.get("exclude_warnings", False)))
                self.min_score_spin.setValue(float(filters.get("min_score", 0.0) or 0.0))
            finally:
                self._control_sync_guard = False
        self._refresh_compare_table_column_mapping()
        self._apply_stage_column_visibility()
        self._apply_stage_plot_layout()

    def _apply_stage_column_visibility(self) -> None:
        stage = dict(self._stage_presets.get(self._selected_stage_id(), {}) or {})
        visible = {str(item) for item in list(stage.get("visible_columns", []) or [])}
        metric_columns = {
            "score": self.COL_SCORE,
            "b_pc_oct": self.COL_B_PC,
            "e_bw": self.COL_E_BW,
            "e_cov": self.COL_E_COV,
            "r_spill": self.COL_R_SPILL,
            "flags_count": self.COL_FLAGS,
        }
        for key, col_idx in metric_columns.items():
            self.run_table.setColumnHidden(col_idx, key not in visible)

    def _update_compute_button_text(self, rows: Optional[List[Dict[str, Any]]] = None) -> None:
        _ = rows if rows is not None else self._all_run_rows
        self.compute_btn.setText("Refresh KPIs")

    def _filtered_rows(self) -> List[Dict[str, Any]]:
        rows = list(self._all_run_rows)
        exclude_flagged = bool(self.exclude_flagged_check.isChecked())
        exclude_warnings = bool(self.exclude_warnings_check.isChecked())
        min_score = float(self.min_score_spin.value())
        filtered: List[Dict[str, Any]] = []
        for row in rows:
            if exclude_flagged and bool(row.get("kpi_flagged")):
                continue
            if exclude_warnings and self._row_has_warning(row):
                continue
            score = row.get("kpi_score")
            if min_score > 0.0 and (score is None or float(score) < min_score):
                continue
            filtered.append(row)
        return filtered

    def _refresh_run_table(self, *_args: Any) -> None:
        self._update_toolbar_context_chips()
        self._set_run_table_rows(self._filtered_rows())

    def _set_run_table_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.run_table.setSortingEnabled(False)
        self.run_table.setRowCount(len(rows))
        previous_identity = self._run_identity(self._selected_detail_payload) if self._selected_detail_payload else ("", "", "")
        selected_row_index = 0
        self._run_selector_sync_guard = True
        self.run_selector.clear()
        for row_index, row in enumerate(rows):
            planes = "/".join(str(item) for item in list(row.get("planes", []) or []))
            flags_text = self._flags_text(row)
            batch_id = str(row.get("batch_id") or "--")
            version_id = str(row.get("version_id") or "--")
            selection_label = f"{batch_id}/{version_id}"
            values = [
                selection_label,
                version_id,
                planes or "--",
                str(row.get("freq_count") if row.get("freq_count") is not None else "--"),
                str(row.get("angle_count") if row.get("angle_count") is not None else "--"),
                self._format_angle(row.get("norm_angle_deg")),
                self._format_float(row.get("kpi_score"), 2),
                self._format_float(row.get("kpi_b_pc_oct"), 2),
                self._format_float(row.get("kpi_e_bw"), 2),
                self._format_float(row.get("kpi_e_cov"), 2),
                self._format_float(row.get("kpi_r_spill"), 3),
                flags_text,
                str(row.get("imported_at") or "--"),
                str(row.get("created_at") or "--"),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index == self.COL_RUN_ID:
                    item.setData(Qt.UserRole, dict(row))
                self.run_table.setItem(row_index, col_index, item)
            run_label = selection_label
            self.run_selector.addItem(run_label, dict(row))
            if previous_identity != ("", "", "") and self._run_identity(row) == previous_identity:
                selected_row_index = row_index
        self.run_table.setSortingEnabled(True)
        self._run_selector_sync_guard = False
        self.run_selector.setEnabled(bool(rows))
        if rows:
            selected_row_index = max(0, min(int(selected_row_index), len(rows) - 1))
            self.run_table.selectRow(selected_row_index)
            selected = dict(rows[selected_row_index])
            self._set_details(selected)
            self._sync_plane_controls(selected)
            self._schedule_plot_refresh()
            self._run_selector_sync_guard = True
            self.run_selector.setCurrentIndex(selected_row_index)
            self._run_selector_sync_guard = False
        else:
            self._set_details(None)
            self._sync_plane_controls(None)
            self._clear_plot_views("Select version + plane to render plots.")
            self._run_selector_sync_guard = True
            self.run_selector.addItem("(no versions)", "")
            self.run_selector.setCurrentIndex(0)
            self._run_selector_sync_guard = False
        self._sync_version_stepper()
        self._update_compute_button_text(rows)

    def _apply_runs_payload(self, payload: Dict[str, Any]) -> None:
        rows = [dict(item) for item in list(payload.get("runs", []) or []) if isinstance(item, dict)]
        self._all_run_rows = rows
        self._apply_pin_state_to_rows()
        if self._compare_candidates:
            lookup = {self._compare_identity(row): dict(row) for row in self._all_run_rows}
            merged: List[Dict[str, Any]] = []
            for candidate in self._compare_candidates:
                identity = self._compare_identity(candidate)
                merged_row = lookup.get(identity, dict(candidate))
                merged.append(self._candidate_from_row(dict(merged_row)))
            self._compare_candidates = merged[:5]
        self._refresh_run_table()
        self._update_compare_slots()

    def _on_source_changed(self, _index: int = 0) -> None:
        if self._selector_sync_guard:
            return
        self._stop_plot_worker()
        self._stop_compare_plot_worker()
        self._stop_autopick_worker()
        self._compare_candidates = []
        self._compare_plot_items = []
        self._ath_all_param_rows_by_version.clear()
        self._loaded_analysis_id = None
        self._clear_plot_views("Select version + plane to render plots.")
        self._clear_compare_stage_canvases(
            curve_message="Select candidates to display compare plot.",
            heatmap_message="Select candidates to display compare heatmap.",
            pareto_message="Select candidates to render Pareto scatter.",
        )
        self.project_selector.setEnabled(False)
        if self._compute_thread is None or not self._compute_thread.isRunning():
            self.compute_btn.setEnabled(self._source_key() == "project")
        self._refresh_saved_analyses()
        self._update_toolbar_context_chips()
        self.refresh_data()

    def _on_project_changed(self, _index: int = 0) -> None:
        if self._selector_sync_guard:
            return
        self._compare_candidates = []
        self._compare_plot_items = []
        self._ath_all_param_rows_by_version.clear()
        self._loaded_analysis_id = None
        self._update_compare_slots()
        self._refresh_saved_analyses()
        self._request_metadata(mode="overview", project_id=self._selected_project_id(), batch_id=None)

    def _request_runs_for_selected_batch(self) -> None:
        self._request_metadata(
            mode="runs",
            project_id=self._selected_project_id(),
            batch_id=self._selected_batch_id(),
        )

    def _on_batch_changed(self, _index: int = 0) -> None:
        if self._selector_sync_guard:
            return
        self._request_runs_for_selected_batch()

    def _on_stage_changed(self, _index: int = 0) -> None:
        if self._control_sync_guard:
            return
        self._apply_stage_defaults(include_filters=False)
        self._update_version_information_panel(dict(self._selected_detail_payload or {}))
        self._update_compare_slots()
        self._update_toolbar_context_chips()
        if not self._selected_project_id() or not self._selected_batch_id():
            self._schedule_plot_refresh()
            self._schedule_compare_plot_refresh()
            return
        self._request_runs_for_selected_batch()
        self._schedule_plot_refresh()
        self._schedule_compare_plot_refresh()

    def _on_kpi_config_changed(self, _value: Any = None) -> None:
        if self._control_sync_guard:
            return
        self._update_toolbar_context_chips()
        self._update_stage_target_badges()
        if not self._selected_project_id() or not self._selected_batch_id():
            self._schedule_plot_refresh()
            self._schedule_compare_plot_refresh()
            return
        self._request_runs_for_selected_batch()
        self._schedule_plot_refresh()
        self._schedule_compare_plot_refresh()

    def _on_band_preset_changed(self, _index: int = 0) -> None:
        self._sync_band_custom_visibility()
        self._on_kpi_config_changed()

    def _on_run_selection_changed(self) -> None:
        selected_indexes = list(self.run_table.selectionModel().selectedRows()) if self.run_table.selectionModel() else []
        if not selected_indexes:
            self._set_details(None)
            self._sync_plane_controls(None)
            self._clear_plot_views("Select version + plane to render plots.")
            self._sync_version_stepper()
            return
        row_index = int(selected_indexes[0].row())
        item = self.run_table.item(row_index, self.COL_RUN_ID)
        payload = dict(item.data(Qt.UserRole) or {}) if item is not None else {}
        if payload:
            target_identity = self._run_identity(payload)
            self._run_selector_sync_guard = True
            for combo_index in range(self.run_selector.count()):
                row_payload = dict(self.run_selector.itemData(combo_index) or {})
                if self._run_identity(row_payload) == target_identity:
                    self.run_selector.setCurrentIndex(combo_index)
                    break
            self._run_selector_sync_guard = False
            self._sync_version_stepper()
        self._set_details(payload if payload else None)
        self._sync_plane_controls(payload if payload else None)
        self._schedule_plot_refresh()

    def _set_details(self, payload: Optional[Dict[str, Any]]) -> None:
        data = dict(payload or {})
        self._selected_detail_payload = dict(data) if data else {}
        planes = "/".join(str(item) for item in list(data.get("planes", []) or []))
        source_files = "\n".join(str(item) for item in list(data.get("source_files", []) or []))
        file_hashes = "\n".join(str(item) for item in list(data.get("file_hashes", []) or []))
        reason_items = self._reason_items(data)
        reason_codes = [str(item.get("code") or "") for item in reason_items if str(item.get("code") or "").strip()]
        norm_note = str(data.get("norm_angle_note") or "--")
        norm_source = str(data.get("norm_angle_source") or "").strip()
        if norm_note != "--" and norm_source:
            norm_note = f"{norm_note} [{norm_source}]"
        flags_text = self._flags_text(data)
        reason_summary = "--"
        if reason_items:
            rendered: List[str] = []
            for item in reason_items:
                sev = str(item.get("severity") or "warn").upper()
                code = str(item.get("code") or "").strip()
                summary = str(item.get("summary") or "").strip()
                if summary:
                    rendered.append(f"[{sev}] {code}: {summary}")
                else:
                    rendered.append(f"[{sev}] {code}")
            reason_summary = "; ".join(rendered)
        mapping = {
            "run_id": str(data.get("run_id") or data.get("run_label") or "--"),
            "version_id": str(data.get("version_id") or "--"),
            "project_id": str(data.get("project_id") or "--"),
            "batch_id": str(data.get("batch_id") or "--"),
            "planes": planes or "--",
            "freq_count": str(data.get("freq_count") if data.get("freq_count") is not None else "--"),
            "angle_count": str(data.get("angle_count") if data.get("angle_count") is not None else "--"),
            "norm_angle_deg": self._format_angle(data.get("norm_angle_deg")),
            "norm_angle_note": norm_note,
            "score": self._format_float(data.get("kpi_score"), 2),
            "b_pc_oct": self._format_float(data.get("kpi_b_pc_oct"), 2),
            "e_bw": self._format_float(data.get("kpi_e_bw"), 2),
            "e_cov": self._format_float(data.get("kpi_e_cov"), 2),
            "r_spill": self._format_float(data.get("kpi_r_spill"), 3),
            "flags": flags_text,
            "kpi_reason_codes": reason_summary,
            "imported_at": str(data.get("imported_at") or "--"),
            "created_at": str(data.get("created_at") or "--"),
            "source_files": source_files or "--",
            "file_hashes": file_hashes or "--",
        }
        for key, label in self._detail_labels.items():
            label.setText(mapping.get(key, "--"))
        self.run_details_btn.setEnabled(bool(data))
        self._update_version_information_panel(data)

        if not data:
            self.run_summary_run_chip.set_full_text("Selection: --")
            self.run_summary_planes_chip.set_full_text("Planes: --")
            self.run_summary_score_chip.set_full_text("Score: --")
            self.run_summary_flags_chip.set_full_text("Flags: --")
            self.flags_help_btn.setEnabled(False)
            self._pending_note_context = None
            return

        batch_id = str(data.get("batch_id") or "--")
        version = str(data.get("version_id") or "--")
        selection = f"{batch_id}/{version}"
        self.run_summary_run_chip.set_full_text(f"Selection: {selection}")
        self.run_summary_planes_chip.set_full_text(f"Planes: {planes or '--'}")
        self.run_summary_score_chip.set_full_text(f"Score: {self._format_float(data.get('kpi_score'), 2)}")
        self.run_summary_flags_chip.set_full_text(f"Flags: {flags_text}")
        self.flags_help_btn.setEnabled(bool(reason_items))


class ProjectManagerWindow(QMainWindow):
    open_project = Signal(str)
    create_project = Signal()

    def __init__(self, service: OrchestratorService) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle("WUT Batcher - Project Manager")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setProperty("framelessShell", True)
        self.setMinimumSize(760, 520)
        self.resize(920, 620)
        self._drag_offset: Optional[QPoint] = None

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)
        shell = QFrame()
        shell.setObjectName("FramelessShell")
        outer.addWidget(shell)
        root = QVBoxLayout(shell)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        title_bar = QWidget()
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title = QLabel("Project Manager")
        title.setObjectName("SectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        close_btn = QPushButton("X")
        close_btn.setObjectName("WindowCloseButton")
        close_btn.setFixedSize(28, 24)
        close_btn.clicked.connect(self.close)
        title_row.addWidget(close_btn, alignment=Qt.AlignRight)
        root.addWidget(title_bar)
        title_bar.mousePressEvent = self._title_mouse_press  # type: ignore[assignment]
        title_bar.mouseMoveEvent = self._title_mouse_move  # type: ignore[assignment]
        title_bar.mouseReleaseEvent = self._title_mouse_release  # type: ignore[assignment]

        self.project_list = QListWidget()
        self.project_list.setObjectName("ProjectTileList")
        self.project_list.setViewMode(QListView.IconMode)
        self.project_list.setResizeMode(QListView.Adjust)
        self.project_list.setMovement(QListView.Static)
        self.project_list.setWrapping(True)
        self.project_list.setSpacing(12)
        self.project_list.setIconSize(QSize(170, 120))
        self.project_list.setGridSize(QSize(210, 170))
        self.project_list.setWordWrap(True)
        self.project_list.setSelectionRectVisible(False)
        list_palette = self.project_list.palette()
        list_palette.setColor(QPalette.Highlight, QColor(0, 0, 0, 0))
        list_palette.setColor(QPalette.HighlightedText, QColor("#F1F1F1"))
        self.project_list.setPalette(list_palette)
        root.addWidget(self.project_list, 1)

        buttons = QHBoxLayout()
        self.open_btn = QPushButton("Open Project")
        self.open_btn.setObjectName("ProjectManagerButton")
        self.new_btn = QPushButton("New Project")
        self.new_btn.setObjectName("ProjectManagerButton")
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("ProjectManagerButton")
        buttons.addWidget(self.open_btn)
        buttons.addWidget(self.new_btn)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.open_btn.clicked.connect(self._emit_open)
        self.new_btn.clicked.connect(self.create_project.emit)
        self.refresh_btn.clicked.connect(self.refresh)
        self.project_list.currentItemChanged.connect(lambda _current, _previous: self._sync_open_enabled())
        self.project_list.itemSelectionChanged.connect(self._sync_open_enabled)
        self.project_list.itemDoubleClicked.connect(self._emit_open)
        self.refresh()

    def refresh(self) -> None:
        previous_item = self.project_list.currentItem()
        previous_id = str(previous_item.data(Qt.UserRole)) if previous_item is not None and previous_item.data(Qt.UserRole) else ""
        self.project_list.clear()
        selected_index = -1
        for project in self.service.list_projects():
            item = QListWidgetItem()
            item.setIcon(self._project_tile_icon(project.name, project.project_id))
            item.setText("")
            item.setToolTip(f"{project.project_id} | {project.name}")
            item.setData(Qt.UserRole, project.project_id)
            self.project_list.addItem(item)
            if previous_id and str(project.project_id) == previous_id:
                selected_index = self.project_list.count() - 1
        if self.project_list.count() > 0:
            self.project_list.setCurrentRow(selected_index if selected_index >= 0 else 0)
        self._sync_open_enabled()

    def _project_tile_icon(self, project_name: str, project_id: str) -> QIcon:
        pixmap = QPixmap(170, 120)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        frame = QPainterPath()
        frame.addRoundedRect(1, 1, 168, 118, 10, 10)
        painter.fillPath(frame, QColor("#13161A"))
        painter.setPen(QColor("#2C323A"))
        painter.drawPath(frame)

        painter.setPen(QColor("#F1F1F1"))
        title_font = QFont("Segoe UI", 9)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(8, 8, 154, 22, Qt.AlignCenter | Qt.TextWordWrap, str(project_name or "Project"))

        thumbnail_rect = (18, 36, 134, 72)
        image_path = self.service.project_preview_image_path(project_id)
        preview = QPixmap(str(image_path)) if image_path.exists() else QPixmap()
        if not preview.isNull():
            zoom_factor = 1.8
            crop_w = max(1, int(preview.width() / zoom_factor))
            crop_h = max(1, int(preview.height() / zoom_factor))
            crop_x = max(0, (preview.width() - crop_w) // 2)
            crop_y = max(0, (preview.height() - crop_h) // 2)
            cropped = preview.copy(crop_x, crop_y, crop_w, crop_h)
            clipped = cropped.scaled(
                thumbnail_rect[2],
                thumbnail_rect[3],
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            draw_x = thumbnail_rect[0] - max(0, (clipped.width() - thumbnail_rect[2]) // 2)
            draw_y = thumbnail_rect[1] - max(0, (clipped.height() - thumbnail_rect[3]) // 2)
            painter.setClipRect(*thumbnail_rect)
            painter.drawPixmap(draw_x, draw_y, clipped)
            painter.setClipping(False)
            painter.setPen(QColor("#323941"))
            painter.drawRoundedRect(*thumbnail_rect, 8, 8)
        else:
            painter.setPen(QColor("#252B33"))
            painter.setBrush(QColor("#1A1F25"))
            painter.drawRoundedRect(*thumbnail_rect, 8, 8)
            painter.setPen(QColor("#3A424D"))
            painter.drawLine(28, 95, 78, 58)
            painter.drawLine(78, 58, 112, 86)
            painter.drawLine(112, 86, 138, 65)
            painter.setBrush(QColor("#3A424D"))
            painter.drawEllipse(38, 54, 8, 8)
        painter.end()
        return QIcon(pixmap)

    def _sync_open_enabled(self) -> None:
        has_selection = self.project_list.currentItem() is not None or bool(self.project_list.selectedItems())
        self.open_btn.setEnabled(has_selection)

    def _emit_open(self, item: QListWidgetItem | None = None) -> None:
        target = item or self.project_list.currentItem()
        if target is None:
            selected = self.project_list.selectedItems()
            target = selected[0] if selected else None
        if target is None:
            return
        project_id = target.data(Qt.UserRole)
        if project_id:
            self.open_project.emit(str(project_id))

    def _title_mouse_press(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            return
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def _title_mouse_move(self, event) -> None:  # type: ignore[override]
        if self._drag_offset is None:
            return
        if not (event.buttons() & Qt.LeftButton):
            return
        self.move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    def _title_mouse_release(self, event) -> None:  # type: ignore[override]
        self._drag_offset = None
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self, service: OrchestratorService) -> None:
        super().__init__()
        self.service = service
        self.compat_ui_adapter = CompatUiAdapter(build_project_form_schema())
        self.current_project: Optional[Project] = None
        self.last_status_detail = ""
        self.ui_validation = UiValidationEngine()
        self._project_validation_debounce_ms = 100
        self._pending_project_payload: Optional[Dict[str, object]] = None
        self._project_validation_timer = QTimer(self)
        self._project_validation_timer.setSingleShot(True)
        self._project_validation_timer.setInterval(self._project_validation_debounce_ms)
        self._project_validation_timer.timeout.connect(self._flush_project_draft_validation)
        self._project_reconcile_guard = False
        self._batch_validation_debounce_ms = 100
        self._pending_batch_payload: Optional[Dict[str, object]] = None
        self._batch_reconcile_guard = False
        self._batch_validation_timer = QTimer(self)
        self._batch_validation_timer.setSingleShot(True)
        self._batch_validation_timer.setInterval(self._batch_validation_debounce_ms)
        self._batch_validation_timer.timeout.connect(self._flush_batch_draft_validation)
        self._project_manager_handler: Optional[Callable[[], None]] = None
        self._project_create_in_progress = False
        self._preview_request_id = 0
        self._preview_thread: Optional[QThread] = None
        self._preview_worker: Optional[_BatchPreviewWorker] = None
        self._batch_run_thread: Optional[QThread] = None
        self._batch_run_worker: Optional[_BatchRunWorker] = None
        self._preview_update_debounce_ms = 280
        self._pending_preview_payload: Optional[Dict[str, object]] = None
        self._preview_update_timer = QTimer(self)
        self._preview_update_timer.setSingleShot(True)
        self._preview_update_timer.setInterval(self._preview_update_debounce_ms)
        self._preview_update_timer.timeout.connect(self._flush_batch_preview_update)
        self._run_foreground_timer = QTimer(self)
        self._run_foreground_timer.setSingleShot(False)
        self._run_foreground_timer.setInterval(850)
        self._run_foreground_timer.timeout.connect(self._enforce_run_foreground)
        self._run_fullscreen_active = False
        self._window_state_before_run = Qt.WindowNoState
        self._window_topmost_before_run = False

        self.setWindowTitle("WUT Batcher")
        self.setMinimumSize(1280, 800)
        self.resize(1280, 860)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.dashboard_page = DashboardPage()
        self.project_page = ProjectPage()
        self.batch_page = BatchPage()
        self.analyse_page = AnalysePage(service=self.service)
        self.run_page = RunPage()

        self.stack.addWidget(self.dashboard_page)
        self.stack.addWidget(self.project_page)
        self.stack.addWidget(self.batch_page)
        self.stack.addWidget(self.analyse_page)
        self.stack.addWidget(self.run_page)
        self._build_navigation_shell()
        self.stack.currentChanged.connect(self._on_stack_page_changed)

        self._build_statusbar()
        self._connect_page_signals()
        try:
            self.service.cleanup_preview_cache()
        except Exception as exc:
            # Non-critical startup maintenance; runtime preview requests handle errors explicitly.
            LOGGER.warning("Startup preview cache cleanup failed: %s", exc)
        self.show_dashboard()
        self._sync_navigation_state()

    def _build_navigation_shell(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.top_bar = QWidget(central)
        self.top_bar.setObjectName("GlobalTopBar")
        self.top_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.top_bar.setMinimumHeight(44)
        self.top_bar.setMaximumHeight(44)
        top_row = QHBoxLayout(self.top_bar)
        top_row.setContentsMargins(10, 6, 10, 6)
        top_row.setSpacing(8)

        self.home_button = QToolButton(self.top_bar)
        self.home_button.setObjectName("TopBarIconButton")
        self.home_button.setAutoRaise(True)
        self.home_button.setToolTip("Project Manager")
        self.home_button.setIcon(QIcon(":/icons/home.svg"))
        self.home_button.setIconSize(QSize(18, 18))
        self.home_button.clicked.connect(self._open_project_manager)
        top_row.addWidget(self.home_button, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.page_title_label = ElidedTitleLabel("")
        self.page_title_label.setObjectName("SectionTitle")
        self.page_title_label.setMinimumWidth(180)
        top_row.addWidget(self.page_title_label, 1, Qt.AlignVCenter)

        self.settings_button = QToolButton(self.top_bar)
        self.settings_button.setObjectName("TopBarIconButton")
        self.settings_button.setAutoRaise(True)
        self.settings_button.setToolTip("Settings")
        self.settings_button.setIcon(QIcon(":/icons/settings.svg"))
        self.settings_button.setIconSize(QSize(18, 18))
        self.settings_button.clicked.connect(self._open_settings)
        top_row.addWidget(self.settings_button, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.bottom_mode_bar = QWidget(central)
        self.bottom_mode_bar.setObjectName("GlobalModeBar")
        self.bottom_mode_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.bottom_mode_bar.setMinimumHeight(38)
        self.bottom_mode_bar.setMaximumHeight(38)
        mode_row = QHBoxLayout(self.bottom_mode_bar)
        mode_row.setContentsMargins(12, 4, 12, 4)
        mode_row.setSpacing(6)

        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.setExclusive(True)
        self.project_mode_button = ElidedToolButton("Project")
        self.batch_mode_button = ElidedToolButton("Batch")
        self.analyse_mode_button = ElidedToolButton("Analyse")
        for button in (self.project_mode_button, self.batch_mode_button, self.analyse_mode_button):
            button.setObjectName("ModeBarButton")
            button.setCheckable(True)
            button.setMinimumHeight(28)
            button.setMaximumHeight(28)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.mode_button_group.addButton(button)
            mode_row.addWidget(button)

        self.project_mode_button.clicked.connect(self.show_dashboard)
        self.batch_mode_button.clicked.connect(self.show_batch)
        self.analyse_mode_button.clicked.connect(self.show_analyse)

        root.addWidget(self.top_bar)
        root.addWidget(self.stack, 1)
        root.addWidget(self.bottom_mode_bar)
        self.setCentralWidget(central)

    def _on_stack_page_changed(self, _index: int) -> None:
        self._sync_navigation_state()

    def _sync_navigation_state(self) -> None:
        current = self.stack.currentWidget()
        self.page_title_label.set_full_text(self._title_for_page(current))
        self._sync_mode_buttons(current)

    def _title_for_page(self, page: QWidget | None) -> str:
        if page is self.batch_page:
            return "BATCH"
        if page is self.analyse_page:
            return "Analyse"
        if page is self.run_page:
            return "Run"
        return "Project"

    def _sync_mode_buttons(self, page: QWidget | None) -> None:
        target = self.project_mode_button
        if page is self.batch_page or page is self.run_page:
            target = self.batch_mode_button
        elif page is self.analyse_page:
            target = self.analyse_mode_button
        for button in (self.project_mode_button, self.batch_mode_button, self.analyse_mode_button):
            button.blockSignals(True)
            button.setChecked(button is target)
            button.blockSignals(False)

    def _build_statusbar(self) -> None:
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.setStatusBar(bar)

        self.status_message = ClickableLabel("Ready.")
        self.status_message.clicked.connect(self._show_status_detail)
        bar.addWidget(self.status_message, 1)

        self.brand = ClickableLabel("WUT BATCHER")
        self.brand.setObjectName("StatusBrand")
        self.brand.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.brand.clicked.connect(self._show_about)
        bar.addPermanentWidget(self.brand)

    def set_project_manager_handler(self, handler: Callable[[], None]) -> None:
        self._project_manager_handler = handler

    def _open_project_manager(self) -> None:
        if callable(self._project_manager_handler):
            self._project_manager_handler()

    def _connect_page_signals(self) -> None:
        self.dashboard_page.request_new_batch.connect(self.show_batch)
        self.dashboard_page.request_edit_batch.connect(self._edit_batch)
        self.dashboard_page.request_clone_batch.connect(self._clone_batch)
        self.dashboard_page.request_open_export_dialog.connect(self._open_export_dialog)
        self.dashboard_page.request_manage_runs.connect(self._open_run_manager)
        self.dashboard_page.request_cleanup_testdata.connect(self._open_cleanup_dialog)
        self.dashboard_page.request_settings.connect(self._open_settings)

        self.project_page.submit_project.connect(self._create_project)
        self.project_page.draft_changed.connect(self._queue_project_draft_changed)
        self.project_page.blocked_interaction.connect(self._on_project_blocked_interaction)

        self.batch_page.save_batch.connect(self._save_batch)
        self.batch_page.run_batch.connect(self._run_batch)
        self.batch_page.draft_changed.connect(self._queue_batch_draft_changed)
        self.batch_page.blocked_interaction.connect(self._on_batch_blocked_interaction)
        self.batch_page.compat_panel.request_show_details.connect(
            lambda: self._show_validation_details(self.batch_page.compat_panel.issues(), "Batch Validation Details")
        )
        self.run_page.back_to_dashboard.connect(self.show_dashboard)

    def _enter_run_presentation(self) -> None:
        if not self._background_automation_enabled():
            self._run_foreground_timer.stop()
            self._run_fullscreen_active = False
            if self.statusBar() is not None:
                self.statusBar().setVisible(True)
            self.show()
            return
        if not self._run_fullscreen_active:
            self._window_state_before_run = self.windowState()
            self._window_topmost_before_run = bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.show()
        if self.statusBar() is not None:
            self.statusBar().setVisible(False)
        self._run_fullscreen_active = True
        _ensure_fullscreen_foreground(self)
        self._run_foreground_timer.start()

    def _exit_run_presentation(self) -> None:
        if not self._run_fullscreen_active:
            return
        self._run_foreground_timer.stop()
        self._run_fullscreen_active = False
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self._window_topmost_before_run)
        self.show()
        if self.statusBar() is not None:
            self.statusBar().setVisible(True)
        previous_state = self._window_state_before_run
        if bool(previous_state & Qt.WindowMaximized):
            _ensure_maximized_foreground(self)
        elif bool(previous_state & Qt.WindowFullScreen):
            _ensure_fullscreen_foreground(self)
        else:
            _ensure_normal_foreground(self)

    def _enforce_run_foreground(self) -> None:
        if not self._run_fullscreen_active:
            return
        if self.stack.currentWidget() is not self.run_page:
            return
        _ensure_fullscreen_foreground(self)

    def _background_automation_enabled(self) -> bool:
        return bool(getattr(self.service.settings, "background_automation_mode", True))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._run_in_progress():
            QMessageBox.warning(
                self,
                "Run in progress",
                "A run is still in progress. Please wait until it finishes.",
            )
            event.ignore()
            return
        self.analyse_page.shutdown()
        self._stop_preview_worker()
        super().closeEvent(event)

    def _stop_preview_worker(self) -> None:
        self._cancel_pending_preview_update()
        worker = self._preview_worker
        thread = self._preview_thread
        if worker is not None:
            worker.cancel()
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(1800)
        self._preview_worker = None
        self._preview_thread = None

    def _run_in_progress(self) -> bool:
        thread = self._batch_run_thread
        return bool(thread is not None and thread.isRunning())

    def _clear_batch_run_worker_refs(self, thread: Optional[QThread] = None) -> None:
        if thread is None:
            self._batch_run_thread = None
            self._batch_run_worker = None
            return
        if self._batch_run_thread is thread:
            self._batch_run_thread = None
            self._batch_run_worker = None

    def _start_batch_run_worker(self, *, project_id: str, batch_id: str, continue_on_error: bool) -> None:
        worker = _BatchRunWorker(
            service=self.service,
            project_id=project_id,
            batch_id=batch_id,
            continue_on_error=continue_on_error,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_batch_run_finished)
        worker.failed.connect(self._on_batch_run_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_batch_run_worker_refs(thread))
        self._batch_run_worker = worker
        self._batch_run_thread = thread
        thread.start()

    def _on_batch_run_finished(self, batch_id: str, summary_payload: Dict[str, Any]) -> None:
        version_count = len(list(summary_payload.get("versions", []) or []))
        dry_run = bool(summary_payload.get("dry_run", False))
        self.run_page.set_finished_state(version_count=version_count, dry_run=dry_run)
        self.set_status(
            f"Run finished for {batch_id}",
            detail=json.dumps(summary_payload, indent=2, ensure_ascii=False),
        )
        self.refresh_dashboard()
        self._exit_run_presentation()

    def _on_batch_run_failed(self, batch_id: str, detail: str) -> None:
        self.run_page.set_failed_state()
        self.set_status(
            f"Run failed for {batch_id}",
            detail=str(detail or "unknown error"),
        )
        self._exit_run_presentation()

    def _cancel_pending_preview_update(self) -> None:
        self._pending_preview_payload = None
        self._preview_update_timer.stop()

    def _queue_batch_preview_update(self, payload: Dict[str, object]) -> None:
        self._pending_preview_payload = dict(payload)
        self._preview_update_timer.start()

    def _flush_batch_preview_update(self) -> None:
        payload = self._pending_preview_payload
        self._pending_preview_payload = None
        if payload is None:
            payload = self.batch_page._payload(include_name=False)
        self._request_batch_preview_update(payload)

    def _request_batch_preview_update(self, payload: Dict[str, object]) -> None:
        if self.current_project is None:
            self.batch_page.set_preview_busy(False)
            self.batch_page.set_preview_error("Open a project before generating preview.")
            self.batch_page.set_policy_default_suggestions({})
            return

        self._stop_preview_worker()

        selected_params = dict(payload.get("selected_params", {}) or {})
        sweep_mode = str(payload.get("sweep_mode", "single") or "single")

        self._preview_request_id += 1
        request_id = int(self._preview_request_id)
        worker = _BatchPreviewWorker(
            service=self.service,
            project_id=self.current_project.project_id,
            selected_params=selected_params,
            sweep_mode=sweep_mode,
            request_id=request_id,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_batch_preview_ready)
        worker.failed.connect(self._on_batch_preview_failed)
        worker.canceled.connect(self._on_batch_preview_canceled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.canceled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._preview_worker = worker
        self._preview_thread = thread
        self.batch_page.set_preview_busy(True)
        thread.start()

    def _on_batch_preview_ready(self, request_id: int, result: Dict[str, Any]) -> None:
        if int(request_id) != int(self._preview_request_id):
            return
        cache_path = str(result.get("cache_stl", "")).strip()
        if not cache_path:
            self.batch_page.set_preview_busy(False)
            self.batch_page.set_preview_error("Preview finished without cached STL path.")
            self._preview_worker = None
            self._preview_thread = None
            return
        try:
            self.batch_page.set_preview_mesh(cache_path)
        except Exception as exc:
            self.batch_page.set_preview_busy(False)
            self.batch_page.set_preview_error(f"Preview load failed: {exc}")
            self._preview_worker = None
            self._preview_thread = None
            return
        self.batch_page.set_preview_busy(False)
        self.batch_page.set_policy_default_suggestions(dict(result.get("policy_default_values", {}) or {}))
        self.set_status("Preview updated.", detail=json.dumps(result, indent=2, ensure_ascii=False))
        self._preview_worker = None
        self._preview_thread = None

    def _on_batch_preview_failed(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._preview_request_id):
            return
        self.batch_page.set_preview_busy(False)
        self.batch_page.set_preview_error(str(message or "Preview generation failed."))
        self.batch_page.set_policy_default_suggestions({})
        self.set_status("Preview generation failed.", detail=str(message or "unknown error"))
        self._preview_worker = None
        self._preview_thread = None

    def _on_batch_preview_canceled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._preview_request_id):
            return
        self.batch_page.set_preview_busy(False)
        self.batch_page.preview_panel.set_info_message("Preview update canceled.")
        self.batch_page.set_policy_default_suggestions({})
        self._preview_worker = None
        self._preview_thread = None

    @staticmethod
    def _project_fixed_keys_from_constraints(constraints: ProjectConstraints) -> List[str]:
        keys = {
            *(str(key) for key in dict(getattr(constraints, "fixed_params", {}) or {}).keys()),
            *(str(key) for key in dict(getattr(constraints, "limits", {}) or {}).keys()),
        }
        for row in list(getattr(constraints, "param_states", []) or []):
            if not isinstance(row, dict):
                continue
            if not bool(row.get("is_set")):
                continue
            key = str(row.get("param_name", "")).strip()
            if key:
                keys.add(key)
        return sorted(keys)

    @staticmethod
    def _sanitize_batch_payload_for_project_constraints(
        payload: Dict[str, Any],
        constraints: ProjectConstraints,
        compat_state: Dict[str, Any],
    ) -> tuple[Dict[str, Any], bool]:
        visible_keys = {
            str(item)
            for item in list(compat_state.get("visible_keys", []) or [])
            if str(item).strip()
        }
        sweepable_keys = {
            str(item)
            for item in list(compat_state.get("sweepable_keys", []) or [])
            if str(item).strip()
        }
        fixed_keys = set(MainWindow._project_fixed_keys_from_constraints(constraints))

        selected_in = dict(payload.get("selected_params", {}) or {})
        sweeps_in = dict(payload.get("sweeps", {}) or {})

        selected_out: Dict[str, Any] = {}
        for key, value in selected_in.items():
            key_s = str(key).strip()
            if not key_s:
                continue
            if key_s in fixed_keys:
                continue
            if key_s not in visible_keys:
                continue
            selected_out[key_s] = value

        sweeps_out: Dict[str, Any] = {}
        for key, sweep in sweeps_in.items():
            key_s = str(key).strip()
            if not key_s:
                continue
            if key_s in fixed_keys:
                continue
            if key_s not in visible_keys:
                continue
            if key_s not in sweepable_keys:
                continue
            sweeps_out[key_s] = sweep

        changed = (selected_out != selected_in) or (sweeps_out != sweeps_in)
        sanitized = dict(payload)
        sanitized["selected_params"] = selected_out
        sanitized["sweeps"] = sweeps_out
        return sanitized, changed

    def set_status(self, text: str, detail: Optional[str] = None) -> None:
        self.status_message.setText(text)
        self.last_status_detail = detail or text

    def _on_project_blocked_interaction(self, _target_key: str, cause_key: str, message: str) -> None:
        if cause_key:
            self.project_page.constraints_form.flash_cause_key(cause_key)
        hint = str(message or "").strip()
        if hint:
            self.set_status(hint)

    def _on_batch_blocked_interaction(self, _target_key: str, cause_key: str, message: str) -> None:
        if cause_key:
            self.batch_page.parameter_form.flash_cause_key(cause_key)
        hint = str(message or "").strip()
        if hint:
            self.set_status(hint)

    def _show_status_detail(self) -> None:
        StatusDetailDialog(self.last_status_detail or "No details.", self).exec()

    def _show_about(self) -> None:
        AboutDialog(self).exec()

    def _show_validation_details(self, issues: List[Dict[str, Any]], title: str) -> None:
        if not issues:
            QMessageBox.information(self, title, "No validation issues.")
            return
        lines = []
        for issue in issues:
            severity = str(issue.get("severity", "info")).upper()
            rule_id = str(issue.get("rule_id", "unknown_rule"))
            evidence_type = str(issue.get("evidence_type", "hypothesis"))
            message = str(issue.get("message", ""))
            lines.append(f"[{severity}] {rule_id} ({evidence_type})\n{message}")
        QMessageBox.information(self, title, "\n\n".join(lines))

    def _present_validation_summary(
        self,
        *,
        title: str,
        issues: List[Dict[str, Any]],
        block_on_fatal: bool,
    ) -> bool:
        if not issues:
            return True
        fatal_count = sum(1 for issue in issues if str(issue.get("severity", "")).lower() == "fatal")
        top = issues[:5]
        lines = []
        for issue in top:
            severity = str(issue.get("severity", "info")).upper()
            rule_id = str(issue.get("rule_id", "unknown_rule"))
            evidence_type = str(issue.get("evidence_type", "hypothesis"))
            message = str(issue.get("message", ""))
            lines.append(f"[{severity}] {rule_id} ({evidence_type}) - {message}")
        detail_lines = [
            {
                "severity": issue.get("severity"),
                "rule_id": issue.get("rule_id"),
                "evidence_type": issue.get("evidence_type"),
                "message": issue.get("message"),
                "scope": issue.get("scope"),
            }
            for issue in issues
        ]
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setIcon(QMessageBox.Warning if fatal_count == 0 else QMessageBox.Critical)
        dialog.setText(f"Validation Summary ({len(issues)} issues)")
        dialog.setInformativeText("\n".join(lines) + "\n\nShow details for full list.")
        dialog.setDetailedText(json.dumps(detail_lines, indent=2, ensure_ascii=False))
        if fatal_count > 0 and block_on_fatal:
            dialog.setStandardButtons(QMessageBox.Ok)
            dialog.exec()
            return False
        dialog.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        return dialog.exec() == QMessageBox.Ok

    def _normalize_batch_issues_for_ui(
        self,
        issues: List[Dict[str, Any]],
        *,
        selected_params: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for issue in issues:
            entry = dict(issue)
            severity = str(entry.get("severity", "")).strip().lower()
            if severity != "fatal":
                normalized.append(entry)
                continue
            key = str(entry.get("field_key") or entry.get("key") or "").strip()
            ui_severity = classify_ui_severity(entry, field_is_set=bool(selected_params.get(key) is not None))
            if ui_severity == "incomplete":
                entry["severity"] = "incomplete"
            normalized.append(entry)
        return normalized

    @staticmethod
    def _batch_issue_counts(issues: List[Dict[str, Any]]) -> Dict[str, int]:
        counts = {"fatal": 0, "warn": 0, "incomplete": 0}
        for issue in issues:
            severity = str(issue.get("severity", "")).strip().lower()
            if severity in counts:
                counts[severity] += 1
        return counts

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.service, self)
        dialog.settings_saved.connect(lambda _: self._on_settings_saved())
        dialog.exec()

    def _on_settings_saved(self) -> None:
        self.set_status("Settings saved.")
        try:
            self.analyse_page.reload_user_settings()
        except Exception:
            pass

    def load_project(self, project: Project) -> None:
        self.current_project = project
        self.project_page.set_constraints_locked(True)
        fixed_keys = self._project_fixed_keys_from_constraints(project.constraints)
        self.batch_page.set_project_fixed_keys(fixed_keys)
        self.analyse_page.set_project_context(project.project_id)
        self.refresh_dashboard()
        self._on_project_draft_changed(self.project_page._raw_constraints_payload())
        self._on_batch_draft_changed(self.batch_page._payload(include_name=False))
        self.show_dashboard()

    def refresh_dashboard(self) -> None:
        if self.current_project is None:
            self.dashboard_page.set_constraints_payload(None)
            self.dashboard_page.batch_list.clear()
            self.analyse_page.set_project_context(None)
            return

        self.dashboard_page.set_constraints_payload(self.current_project.constraints.to_dict())
        self.dashboard_page.batch_list.clear()
        for batch in self.service.repo.list_batches(self.current_project.project_id):
            label = f"{batch.batch_id} | {batch.extra.get('batch_name', batch.batch_id)}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, batch.batch_id)
            self.dashboard_page.batch_list.addItem(item)

    def show_dashboard(self) -> None:
        self._stop_preview_worker()
        self._exit_run_presentation()
        self.stack.setCurrentWidget(self.dashboard_page)

    def show_project(self) -> None:
        self._stop_preview_worker()
        self._exit_run_presentation()
        self._on_project_draft_changed(self.project_page._raw_constraints_payload())
        self.stack.setCurrentWidget(self.project_page)

    def show_batch(self) -> None:
        if self.current_project is None:
            self.set_status("Open or create a project before entering Batch mode.")
            self.show_dashboard()
            self._sync_navigation_state()
            return
        self._exit_run_presentation()
        self.batch_page.reset_draft()
        self._on_batch_draft_changed(self.batch_page._payload(include_name=False))
        self.stack.setCurrentWidget(self.batch_page)

    def show_analyse(self) -> None:
        self._stop_preview_worker()
        self._exit_run_presentation()
        if self.current_project is None:
            self.set_status("Open or create a project before entering Analyse mode.")
            self.show_dashboard()
            self._sync_navigation_state()
            return
        self.analyse_page.set_project_context(self.current_project.project_id if self.current_project else None)
        self.analyse_page.refresh_data()
        self.stack.setCurrentWidget(self.analyse_page)

    def show_run(self) -> None:
        self._stop_preview_worker()
        self.stack.setCurrentWidget(self.run_page)
        self.run_page.set_background_mode(self._background_automation_enabled())
        self._enter_run_presentation()

    def _create_project(self, project_name: str, constraints: Dict[str, object]) -> None:
        if self._project_create_in_progress:
            return
        self._project_create_in_progress = True
        self.project_page.set_creating(True)
        try:
            validation = self.service.evaluate_project_constraints(dict(constraints))
            issues = [item for item in list(validation.get("issues", []) or []) if isinstance(item, dict)]
            project = self.service.create_project(project_name, constraints)
            self.load_project(project)
            self.project_page.set_constraints_locked(True)
            if issues:
                self.set_status(
                    f"Project created: {project.project_id} (draft issues: {len(issues)})",
                    detail=json.dumps(issues, indent=2, ensure_ascii=False),
                )
            else:
                self.set_status(f"Project created: {project.project_id}")
        finally:
            self._project_create_in_progress = False
            self.project_page.set_creating(False)

    def _save_batch(self, payload: Dict[str, object], *, for_run: bool = False) -> Optional[str]:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return None
        raw_payload = dict(payload)
        raw_selected_params = dict(raw_payload.get("selected_params", {}) or {})
        raw_sweeps = dict(raw_payload.get("sweeps", {}) or {})
        raw_mode = str(raw_payload.get("sweep_mode", "single"))
        validation = self.service.evaluate_batch_definition(
            project_id=self.current_project.project_id,
            selected_params=raw_selected_params,
            sweeps=raw_sweeps,
            sweep_mode=raw_mode,
        )
        sanitized_payload, changed = self._sanitize_batch_payload_for_project_constraints(
            raw_payload,
            self.current_project.constraints,
            validation,
        )
        payload = sanitized_payload
        selected_params = dict(payload.get("selected_params", {}) or {})
        if changed:
            validation = self.service.evaluate_batch_definition(
                project_id=self.current_project.project_id,
                selected_params=selected_params,
                sweeps=dict(payload.get("sweeps", {}) or {}),
                sweep_mode=str(payload.get("sweep_mode", "single")),
            )
        raw_issues = [item for item in list(validation.get("issues", []) or []) if isinstance(item, dict)]
        issues = self._normalize_batch_issues_for_ui(raw_issues, selected_params=selected_params)
        issues.extend(self.batch_page.export_panel.validation_issues())
        counts = self._batch_issue_counts(issues)
        block_count = int(counts.get("fatal", 0))
        if for_run:
            block_count += int(counts.get("incomplete", 0))
        should_prompt = int(counts.get("fatal", 0)) > 0
        if should_prompt:
            if not self._present_validation_summary(
                title="Batch Validation Summary",
                issues=issues,
                block_on_fatal=(block_count > 0),
            ):
                self.set_status("Batch save blocked by validation.")
                return None
        summary = self.service.create_batch(
            project_id=self.current_project.project_id,
            batch_name=str(payload.get("batch_name", "")),
            selected_params=dict(payload.get("selected_params", {}) or {}),
            sweeps=dict(payload.get("sweeps", {}) or {}),
            sweep_mode=str(payload.get("sweep_mode", "single")),
            sim_export_params=dict(payload.get("sim_export_params", {}) or {}),
        )
        self.set_status(
            f"Batch saved: {summary.batch_id}, versions={summary.version_count}",
            detail=json.dumps(asdict(summary), indent=2, ensure_ascii=False),
        )
        self.refresh_dashboard()
        if not for_run:
            self.show_dashboard()
        return summary.batch_id

    @staticmethod
    def _merge_policy_defaults(
        selected_params: Dict[str, Any],
        default_values: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = dict(selected_params or {})
        for raw_key, raw_value in dict(default_values or {}).items():
            key = str(raw_key).strip()
            if not key:
                continue
            if key.startswith("R-OSSE."):
                obj = dict(merged.get("R-OSSE", {}) or {})
                sub_key = key.split(".", 1)[1]
                if obj.get(sub_key) is None:
                    obj[sub_key] = raw_value
                merged["R-OSSE"] = obj
                continue
            if key == "R-OSSE" and isinstance(raw_value, Mapping):
                obj = dict(merged.get("R-OSSE", {}) or {})
                for sub_key, sub_value in dict(raw_value).items():
                    if obj.get(str(sub_key)) is None:
                        obj[str(sub_key)] = sub_value
                merged["R-OSSE"] = obj
                continue
            if merged.get(key) is None:
                merged[key] = raw_value
        return merged

    def _resolve_run_policy_defaults(self, payload: Dict[str, object]) -> Optional[Dict[str, object]]:
        if self.current_project is None:
            return payload
        selected_params = dict(payload.get("selected_params", {}) or {})
        policy = self.service.evaluate_batch_default_policy(
            project_id=self.current_project.project_id,
            selected_params=selected_params,
        )
        missing_keys = [str(item) for item in list(policy.get("missing_keys", []) or []) if str(item).strip()]
        default_values = dict(policy.get("default_values", {}) or {})
        self.batch_page.clear_policy_missing_highlights()
        if not missing_keys:
            return payload

        dialog = BatchRunDefaultsDialog(
            missing_keys=missing_keys,
            default_values=default_values,
            parent=self,
        )
        decision = "cancel"
        if dialog.exec() == QDialog.Accepted:
            decision = dialog.decision()
        if decision == "show":
            highlighted = self.batch_page.highlight_policy_missing_keys(missing_keys)
            if highlighted:
                self.set_status(f"Highlighted undefined parameters: {len(highlighted)}")
            else:
                self.set_status("No visible undefined parameters to highlight.")
            return None
        if decision != "use_defaults":
            self.set_status("Run canceled.")
            return None

        merged_selected = self._merge_policy_defaults(selected_params, default_values)
        next_payload = dict(payload)
        next_payload["selected_params"] = merged_selected
        self.batch_page.apply_policy_defaults(default_values)
        self.batch_page.clear_policy_missing_highlights()
        self.set_status("Applied policy defaults for run.")
        return next_payload

    def _run_batch(self, payload: Dict[str, object]) -> None:
        if self._run_in_progress():
            self.set_status("Run already in progress.")
            return
        self._stop_preview_worker()
        run_payload = self._resolve_run_policy_defaults(dict(payload))
        if run_payload is None:
            return
        batch_id = self._save_batch(run_payload, for_run=True)
        if self.current_project is None or not batch_id:
            return
        self._ensure_project_preview_thumbnail()
        self.show_run()
        self.run_page.set_running_state()
        self.set_status(f"Run started for {batch_id}")
        QApplication.processEvents()
        self._start_batch_run_worker(
            project_id=self.current_project.project_id,
            batch_id=batch_id,
            continue_on_error=True,
        )

    def _ensure_project_preview_thumbnail(self) -> None:
        if self.current_project is None:
            return
        target = self.service.project_preview_image_path(self.current_project.project_id)
        if target.exists():
            return
        ok = self.batch_page.preview_panel.capture_snapshot(target)
        if not ok:
            return
        self.refresh_dashboard()

    def _open_export_dialog(self) -> None:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return
        rows = self.service.list_versions(self.current_project.project_id)
        versions_by_batch: Dict[str, List[str]] = {}
        for row in rows:
            batch_id = str(row["batch_id"])
            versions_by_batch.setdefault(batch_id, []).append(str(row["version_id"]))
        if not versions_by_batch:
            self.set_status("No versions available for export.")
            return
        dialog = ExportDialog(versions_by_batch, self)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.payload()
        self._export_version(
            str(payload["batch_id"]),
            str(payload["version_id"]),
            bool(payload["export_stl"]),
            bool(payload["export_abec"]),
        )

    def _open_run_manager(self) -> None:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return
        RunManagerDialog(self.service, self.current_project.project_id, self).exec()
        self.refresh_dashboard()

    def _open_cleanup_dialog(self) -> None:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return
        dialog = CleanupTestDataDialog(self.service, self.current_project.project_id, self)
        if dialog.exec() == QDialog.Accepted:
            self.set_status("Cleanup finished.")
            self.refresh_dashboard()

    def _edit_batch(self, batch_id: str) -> None:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return
        try:
            batch = self.service.repo.load_batch(self.current_project.project_id, batch_id)
        except Exception as exc:
            self.set_status(f"Edit Batch failed for {batch_id}", detail=str(exc))
            return
        self.batch_page.load_from_batch(batch)
        self._on_batch_draft_changed(self.batch_page._payload(include_name=False))
        self.stack.setCurrentWidget(self.batch_page)
        self.set_status(f"Batch loaded: {batch_id}")

    def _clone_batch(self, batch_id: str) -> None:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return
        try:
            batch = self.service.repo.load_batch(self.current_project.project_id, batch_id)
        except Exception as exc:
            self.set_status(f"Clone Batch failed for {batch_id}", detail=str(exc))
            return
        source_name = str(batch.extra.get("batch_name", batch.batch_id)).strip() or batch.batch_id
        clone_name = f"{source_name} Clone"
        self.batch_page.load_from_batch(batch, batch_name=clone_name)
        self._on_batch_draft_changed(self.batch_page._payload(include_name=False))
        self.stack.setCurrentWidget(self.batch_page)
        self.set_status(f"Batch cloned into draft: {clone_name}")

    def _export_version(self, batch_id: str, version_id: str, export_stl: bool, export_abec: bool) -> None:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return
        try:
            result = self.service.export_version(
                project_id=self.current_project.project_id,
                batch_id=batch_id,
                version_id=version_id,
                export_stl=export_stl,
                export_abec=export_abec,
            )
        except Exception as exc:
            self.set_status(f"Export failed for {version_id}", detail=str(exc))
            return
        self.set_status(f"Export finished for {version_id}", detail=json.dumps(result, indent=2, ensure_ascii=False))

    def _queue_project_draft_changed(self, payload: Dict[str, object]) -> None:
        self._pending_project_payload = dict(payload)
        self.project_page.set_validation_phase("validating")
        self._project_validation_timer.start()

    def _flush_project_draft_validation(self) -> None:
        payload = self._pending_project_payload
        self._pending_project_payload = None
        if payload is None:
            payload = self.project_page._raw_constraints_payload()
        self._on_project_draft_changed(payload)

    def _queue_batch_draft_changed(self, payload: Dict[str, object]) -> None:
        self._pending_batch_payload = dict(payload)
        self._batch_validation_timer.start()

    def _flush_batch_draft_validation(self) -> None:
        payload = self._pending_batch_payload
        self._pending_batch_payload = None
        if payload is None:
            payload = self.batch_page._payload(include_name=False)
        self._on_batch_draft_changed(payload)

    def _on_project_draft_changed(self, payload: Dict[str, object]) -> None:
        runner_mode = DEFAULT_RUNNER_MODE
        if self.current_project is not None:
            runner_mode = self.current_project.constraints.runner_mode
        constraints_payload = {
            "fixed_params": dict(payload.get("fixed_params", {}) or {}),
            "limits": dict(payload.get("limits", {}) or {}),
            "param_states": [item for item in list(payload.get("param_states", []) or []) if isinstance(item, dict)],
            "runner_mode": runner_mode,
        }
        state_raw = self.service.evaluate_project_constraints(constraints_payload)
        ui_state = self.compat_ui_adapter.compute_project_ui_state(
            draft_payload=constraints_payload,
            compat_state=state_raw,
            evaluate_constraints=self.service.evaluate_project_constraints,
            last_changed_key=self.project_page.constraints_form.last_changed_key(),
        )
        state = dict(state_raw)
        state["compat_ui_state"] = ui_state
        self.project_page.apply_compatibility(state)
        if not self._project_reconcile_guard:
            reconciled_payload = self.project_page._raw_constraints_payload()
            reconciled_constraints = {
                "fixed_params": dict(reconciled_payload.get("fixed_params", {}) or {}),
                "limits": dict(reconciled_payload.get("limits", {}) or {}),
                "param_states": [item for item in list(reconciled_payload.get("param_states", []) or []) if isinstance(item, dict)],
                "runner_mode": runner_mode,
            }
            if reconciled_constraints != constraints_payload:
                self._project_reconcile_guard = True
                try:
                    self._on_project_draft_changed(reconciled_payload)
                finally:
                    self._project_reconcile_guard = False
                return
        visible_keys = set(str(item) for item in list(state.get("visible_keys", []) or []))
        issues = [item for item in list(state.get("issues", []) or []) if isinstance(item, dict)]
        field_issues = self.ui_validation.evaluate(
            draft_payload=constraints_payload,
            validation_state=state,
            visible_keys=visible_keys,
        )
        self.project_page.apply_ui_risks(field_issues)
        _ = issues

    def _on_batch_draft_changed(self, payload: Dict[str, object]) -> None:
        if self.current_project is None:
            self._cancel_pending_preview_update()
            self._stop_preview_worker()
            self.batch_page.set_project_fixed_keys([])
            self.batch_page.apply_compatibility(
                {
                    "visible_keys": [],
                    "locked_keys": [],
                    "sweepable_keys": [],
                    "compat_ui_state": {},
                    "issues": [],
                }
            )
            self.batch_page.apply_ui_risks([])
            self.batch_page.set_eta(None, sample_count=0, median_seconds=None)
            self.batch_page.set_preview_busy(False)
            self.batch_page.set_preview_parameters({})
            self.batch_page.preview_panel.set_info_message("No preview mesh loaded.")
            return
        raw_payload = dict(payload)
        raw_sweep_mode = str(raw_payload.get("sweep_mode", "single"))
        raw_selected_params = dict(raw_payload.get("selected_params", {}) or {})
        raw_sweeps = dict(raw_payload.get("sweeps", {}) or {})
        state_raw = self.service.evaluate_batch_definition(
            project_id=self.current_project.project_id,
            selected_params=raw_selected_params,
            sweeps=raw_sweeps,
            sweep_mode=raw_sweep_mode,
        )
        sanitized_payload, _changed = self._sanitize_batch_payload_for_project_constraints(
            raw_payload,
            self.current_project.constraints,
            state_raw,
        )
        payload = sanitized_payload
        sweep_mode = str(payload.get("sweep_mode", "single"))
        selected_params = dict(payload.get("selected_params", {}) or {})
        sweeps = dict(payload.get("sweeps", {}) or {})
        if selected_params != raw_selected_params or sweeps != raw_sweeps or sweep_mode != raw_sweep_mode:
            state_raw = self.service.evaluate_batch_definition(
                project_id=self.current_project.project_id,
                selected_params=selected_params,
                sweeps=sweeps,
                sweep_mode=sweep_mode,
            )
        ui_state = self.compat_ui_adapter.compute_batch_ui_state(
            selected_params=selected_params,
            sweeps=sweeps,
            sweep_mode=sweep_mode,
            compat_state=state_raw,
            project_constraints=self.current_project.constraints.to_dict(),
            evaluate_batch=lambda sel, sw, mode: self.service.evaluate_batch_definition(
                project_id=self.current_project.project_id,
                selected_params=sel,
                sweeps=sw,
                sweep_mode=mode,
            ),
            last_changed_key=self.batch_page.parameter_form.last_changed_key(),
        )
        state = dict(state_raw)
        state["compat_ui_state"] = ui_state
        self.batch_page.apply_compatibility(state)
        if not self._batch_reconcile_guard:
            reconciled_payload = self.batch_page._payload(include_name=False)
            reconciled_selected = dict(reconciled_payload.get("selected_params", {}) or {})
            reconciled_sweeps = dict(reconciled_payload.get("sweeps", {}) or {})
            if reconciled_selected != selected_params or reconciled_sweeps != sweeps:
                self._batch_reconcile_guard = True
                try:
                    self._on_batch_draft_changed(reconciled_payload)
                finally:
                    self._batch_reconcile_guard = False
                return

        project_constraints = self.current_project.constraints.to_dict()
        draft_fixed = dict(project_constraints.get("fixed_params", {}) or {})
        draft_limits = dict(project_constraints.get("limits", {}) or {})
        draft_param_states = [
            dict(item)
            for item in list(project_constraints.get("param_states", []) or [])
            if isinstance(item, dict)
        ]
        for key, value in selected_params.items():
            key_s = str(key).strip()
            if not key_s:
                continue
            if value is not None:
                draft_fixed[key_s] = value
            draft_param_states.append(
                {
                    "param_name": key_s,
                    "is_set": 1 if value is not None else 0,
                    "value": value if value is not None else None,
                }
            )
        batch_draft_payload = {
            "fixed_params": draft_fixed,
            "limits": draft_limits,
            "param_states": draft_param_states,
            "runner_mode": project_constraints.get("runner_mode", DEFAULT_RUNNER_MODE),
        }
        visible_keys = set(str(item) for item in list(state.get("visible_keys", []) or []))
        batch_field_issues_raw = self.ui_validation.evaluate(
            draft_payload=batch_draft_payload,
            validation_state=state,
            visible_keys=visible_keys,
        )
        batch_field_issues = self._normalize_batch_issues_for_ui(
            [dict(item) for item in list(batch_field_issues_raw or []) if isinstance(item, dict)],
            selected_params=selected_params,
        )
        export_validation_issues = [dict(item) for item in list(self.batch_page.export_panel.validation_issues() or [])]
        self.batch_page.apply_ui_risks([*batch_field_issues, *export_validation_issues])

        estimate = self.service.estimate_batch_runtime(
            project_id=self.current_project.project_id,
            selected_params=selected_params,
            sweeps=sweeps,
            sweep_mode=sweep_mode,
            validation_state=state,
        )
        self.batch_page.set_eta(
            estimate.get("eta_seconds"),
            sample_count=int(estimate.get("sample_count", 0) or 0),
            median_seconds=estimate.get("median_seconds_per_version"),
        )
        if self.isVisible() and self.stack.currentWidget() is self.batch_page:
            self._queue_batch_preview_update(
                {
                    "selected_params": selected_params,
                    "sweep_mode": sweep_mode,
                }
            )
        self.batch_page.set_preview_parameters(selected_params)


class GuiController:
    def __init__(self, service: OrchestratorService) -> None:
        self.service = service
        self.project_manager = ProjectManagerWindow(service)
        self.main_window = MainWindow(service)
        self.project_manager.open_project.connect(self._open_project)
        self.project_manager.create_project.connect(self._new_project)
        self.main_window.set_project_manager_handler(self._open_project_manager_from_main)

    def show_project_manager(self) -> None:
        self.project_manager.refresh()
        self._show_window_normal_foreground(self.project_manager)

    def _show_main_window_maximized(self) -> None:
        self._show_window_maximized_foreground(self.main_window)

    @staticmethod
    def _show_window_normal_foreground(window: QMainWindow) -> None:
        _center_window(window)
        window.show()
        apply_windows_dark_titlebar(window)
        _ensure_normal_foreground(window)

    @staticmethod
    def _show_window_maximized_foreground(window: QMainWindow) -> None:
        window.show()
        apply_windows_dark_titlebar(window)
        _ensure_maximized_foreground(window)

    def _open_project(self, project_id: str) -> None:
        try:
            project = self.service.repo.load_project(project_id)
        except Exception as exc:
            QMessageBox.warning(
                self.project_manager,
                "Open project failed",
                f"Could not open project '{project_id}'.\n{exc}",
            )
            self.project_manager.refresh()
            return
        self.main_window.load_project(project)
        self._show_main_window_maximized()
        self.project_manager.hide()

    def _new_project(self) -> None:
        self.main_window.current_project = None
        self.main_window.project_page.set_constraints_locked(False)
        self._show_main_window_maximized()
        self.main_window.show_project()
        self.project_manager.hide()

    def _open_project_manager_from_main(self) -> None:
        self.project_manager.refresh()
        self._show_window_normal_foreground(self.project_manager)
        self.main_window.hide()


def _make_splash(app: QApplication) -> QSplashScreen:
    width, height = 760, 360
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, float(width), float(height), 18.0, 18.0)
    painter.fillPath(path, QColor("#101010"))
    painter.setPen(QColor("#F1F1F1"))
    font = QFont("Condor", 58)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "WUT BATCHER")
    painter.end()
    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
    splash.setAttribute(Qt.WA_TranslucentBackground, True)
    splash.show()
    app.processEvents()
    return splash


def _run_doctor_for_splash(service: OrchestratorService) -> Dict[str, object]:
    settings = service.settings
    config = AppConfig(projects_root=settings.library_root)
    report = run_doctor_checks(
        config,
        config_path=None,
        fix=False,
        kill_zombies=False,
        report_path=None,
        tool_paths={
            "ath_exe": settings.ath_exe,
            "akabak_exe": settings.akabak_exe,
            "vacs_exe": settings.vacs_exe,
        },
    )
    tool_versions: Dict[str, str] = {}
    for key, exe_path in {
        "ath": settings.ath_exe,
    }.items():
        if not exe_path:
            continue
        try:
            result = subprocess.run(
                [exe_path, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
                check=False,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0),
            )
            text = (result.stdout or result.stderr or "").strip().splitlines()
            if text:
                tool_versions[key] = text[0]
        except Exception:
            continue
    return {
        "overall_status": report.overall_status,
        "checks": [check.__dict__ for check in report.checks],
        "tool_versions": tool_versions,
    }


def launch_gui() -> int:
    configure_windows_qt_darkmode_env()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)

    _install_runtime_exception_logging()
    service = OrchestratorService()
    splash = _make_splash(app)
    doctor_payload = _run_doctor_for_splash(service)
    controller = GuiController(service)
    _install_runtime_exception_logging(
        context_provider=lambda: {
            "page": type(controller.main_window.stack.currentWidget()).__name__,
            "mode": (
                "project"
                if controller.main_window.project_mode_button.isChecked()
                else "batch"
                if controller.main_window.batch_mode_button.isChecked()
                else "analyse"
                if controller.main_window.analyse_mode_button.isChecked()
                else "unknown"
            ),
            "project_id": (
                controller.main_window.current_project.project_id
                if controller.main_window.current_project is not None
                else None
            ),
        }
    )
    doctor_status = str(doctor_payload["overall_status"]).lower()
    if doctor_status in {"fail", "warn"}:
        controller.main_window.set_status(
            f"Doctor {doctor_status}: click for details",
            detail=json.dumps(doctor_payload, indent=2, ensure_ascii=False),
        )
    else:
        controller.main_window.set_status(
            "Doctor ok.",
            detail=json.dumps(doctor_payload, indent=2, ensure_ascii=False),
        )
    splash.finish(controller.project_manager)
    controller.show_project_manager()
    return app.exec()


def main() -> int:
    from app.audit_mode import enable_audit_mode

    enable_audit_mode(entrypoint="app.gui.main")
    return int(launch_gui())
