"""PySide6 GUI orchestrator for WUT Batcher."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import math
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import traceback
from typing import Any, Callable, Dict, List, Mapping, Optional

from app.analyzer.cache import AnalyzerPlotCache, resolve_cache_policy
from app.analyzer.heatmap_style import compare_overlay_color, get_vacs_like_lut
from app.analyzer.presets import (
    ALGO_VERSION,
    COVERAGE_PRESETS,
    DEFAULT_BAND_PRESET_ID,
    DEFAULT_COVERAGE_PRESET_ID,
    DEFAULT_STAGE_ID,
    DEFAULT_TOL_DEG,
    STAGE_PRESETS,
    resolve_band_limits,
)
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


class HeatmapCanvas(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AnalyzerHeatmapCanvas")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._matrix: List[List[Optional[float]]] = []
        self._clamp_enabled = True
        self._clamp_min_db = -30.0
        self._status = "Select run + plane to render heatmap."
        self._ref_angle_deg: Optional[float] = None
        self._lut = get_vacs_like_lut(256)

    def set_heatmap_data(
        self,
        *,
        matrix: List[List[Optional[float]]],
        clamp_enabled: bool,
        clamp_min_db: float,
        ref_angle_deg: Optional[float],
        status: str = "",
    ) -> None:
        self._matrix = [list(row) for row in list(matrix or [])]
        self._clamp_enabled = bool(clamp_enabled)
        self._clamp_min_db = float(clamp_min_db)
        self._ref_angle_deg = float(ref_angle_deg) if ref_angle_deg is not None else None
        self._status = str(status or "").strip()
        self._rerender()

    def clear_heatmap(self, message: str) -> None:
        self._matrix = []
        self._status = str(message or "No heatmap data.")
        self._rerender()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._rerender()

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
        painter.setRenderHint(QPainter.Antialiasing, False)

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

        min_db = float(self._clamp_min_db if self._clamp_enabled else -60.0)
        max_db = 0.0
        for row in self._matrix:
            for value in row:
                if value is None:
                    continue
                if not self._clamp_enabled:
                    min_db = min(min_db, float(value))
        span = max(max_db - min_db, 1.0)

        cell_w = max(width / float(cols), 1.0)
        cell_h = max(height / float(rows), 1.0)
        for y_idx, row in enumerate(self._matrix):
            top = int(round(y_idx * cell_h))
            bottom = int(round((y_idx + 1) * cell_h))
            for x_idx, value in enumerate(row):
                if value is None:
                    color = QColor("#1A1E26")
                else:
                    db = float(value)
                    if self._clamp_enabled:
                        db = max(min_db, min(max_db, db))
                    norm = (db - min_db) / span
                    color = self._color_for_value(norm)
                left = int(round(x_idx * cell_w))
                right = int(round((x_idx + 1) * cell_w))
                painter.fillRect(left, top, max(right - left, 1), max(bottom - top, 1), color)

        painter.setPen(QPen(QColor("#3A4252")))
        painter.drawRect(0, 0, width - 1, height - 1)
        if self._status:
            painter.setPen(QColor("#B8C1CF"))
            painter.drawText(8, 16, self._status)
        if self._ref_angle_deg is not None:
            painter.setPen(QColor("#A6AFBC"))
            painter.drawText(width - 180, 16, f"Ref: {self._ref_angle_deg:.1f} deg")
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
        self._status = "Beamwidth curve not available."

    def set_curve(
        self,
        *,
        curve: List[Dict[str, float]],
        target_deg: float,
        tol_deg: float,
        status: str = "",
    ) -> None:
        self._curve = [dict(item) for item in list(curve or []) if isinstance(item, dict)]
        self._target_deg = float(target_deg)
        self._tol_deg = float(tol_deg)
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

        margin_left = 46
        margin_right = 12
        margin_top = 12
        margin_bottom = 24
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

        log_min = math.log10(min(freqs))
        log_max = math.log10(max(freqs))
        if log_max <= log_min:
            log_max = log_min + 1.0
        y_max = max(max(bws), self._target_deg + self._tol_deg + 10.0, 20.0)
        y_min = max(min(min(bws), self._target_deg - self._tol_deg - 10.0, 0.0), 0.0)
        if y_max <= y_min:
            y_max = y_min + 1.0

        def x_of(freq: float) -> float:
            u = (math.log10(max(freq, 1.0)) - log_min) / (log_max - log_min)
            return float(margin_left + (u * plot_w))

        def y_of(width_deg: float) -> float:
            u = (float(width_deg) - y_min) / (y_max - y_min)
            return float(margin_top + ((1.0 - u) * plot_h))

        # background guides
        painter.setPen(QPen(QColor("#262C38"), 1))
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = int(round(margin_top + (frac * plot_h)))
            painter.drawLine(margin_left, y, margin_left + plot_w, y)

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
        painter.drawText(8, 16, self._status or "Beamwidth (-6 dB)")
        painter.drawText(8, height - 6, "BW (deg)")
        painter.drawText(width - 110, height - 6, "Freq (log Hz)")
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
        self._status = "Compare overlay not available."

    def set_series(
        self,
        *,
        series: List[Dict[str, Any]],
        target_deg: float,
        tol_deg: float,
        status: str = "",
    ) -> None:
        self._series = [dict(item) for item in list(series or []) if isinstance(item, dict)]
        self._target_deg = float(target_deg)
        self._tol_deg = float(tol_deg)
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

        margin_left = 46
        margin_right = 16
        margin_top = 14
        margin_bottom = 28
        plot_w = max(width - margin_left - margin_right, 30)
        plot_h = max(height - margin_top - margin_bottom, 30)

        freqs = [item[0] for item in flattened]
        widths = [item[1] for item in flattened]
        log_min = math.log10(min(freqs))
        log_max = math.log10(max(freqs))
        if log_max <= log_min:
            log_max = log_min + 1.0
        y_max = max(max(widths), self._target_deg + self._tol_deg + 10.0, 20.0)
        y_min = max(min(min(widths), self._target_deg - self._tol_deg - 10.0, 0.0), 0.0)
        if y_max <= y_min:
            y_max = y_min + 1.0

        def x_of(freq: float) -> float:
            u = (math.log10(max(freq, 1.0)) - log_min) / (log_max - log_min)
            return float(margin_left + (u * plot_w))

        def y_of(width_deg: float) -> float:
            u = (float(width_deg) - y_min) / (y_max - y_min)
            return float(margin_top + ((1.0 - u) * plot_h))

        painter.setPen(QPen(QColor("#262C38"), 1))
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = int(round(margin_top + (frac * plot_h)))
            painter.drawLine(margin_left, y, margin_left + plot_w, y)

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
            painter.drawText(width - 190, legend_y, 182, 14, Qt.AlignRight | Qt.AlignVCenter, label)
            legend_y += 14

        painter.setPen(QPen(QColor("#3A4252"), 1))
        painter.drawRect(margin_left, margin_top, plot_w, plot_h)
        painter.setPen(QColor("#A6AFBC"))
        painter.drawText(8, 16, self._status or "Beamwidth overlay (-6 dB)")
        painter.drawText(8, height - 6, "BW (deg)")
        painter.drawText(width - 120, height - 6, "Freq (log Hz)")
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
        band_low_hz: float,
        band_high_hz: float,
        cache: AnalyzerPlotCache,
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
        self._band_low_hz = float(band_low_hz)
        self._band_high_hz = float(band_high_hz)
        self._cache = cache
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
            payload = self._service.analyzer_load_plot_payload(
                source=self._source,
                project_id=self._project_id,
                batch_id=self._batch_id,
                run_id=self._run_id,
                version_id=self._version_id,
                plane=self._plane,
                band_low_hz=self._band_low_hz,
                band_high_hz=self._band_high_hz,
                cache=self._cache,
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
        band_low_hz: float,
        band_high_hz: float,
        cache: AnalyzerPlotCache,
    ) -> None:
        super().__init__()
        self._service = service
        self._request_id = int(request_id)
        self._source = str(source or "project")
        self._project_id = str(project_id or "").strip()
        self._candidates = [dict(item) for item in list(candidates or []) if isinstance(item, dict)]
        self._plane = str(plane or "H").strip().upper() or "H"
        self._band_low_hz = float(band_low_hz)
        self._band_high_hz = float(band_high_hz)
        self._cache = cache
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
                payload = self._service.analyzer_load_plot_payload(
                    source=self._source,
                    project_id=self._project_id,
                    batch_id=batch_id,
                    run_id=run_id,
                    version_id=version_id,
                    plane=self._plane,
                    band_low_hz=self._band_low_hz,
                    band_high_hz=self._band_high_hz,
                    cache=self._cache,
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

        form = QFormLayout()
        form.addRow("Library Folder", self.library_root)
        form.addRow("ATH", self.ath_exe)
        form.addRow("AKABAK", self.akabak_exe)
        form.addRow("VACS", self.vacs_exe)
        form.addRow("Template CFG", self.template_cfg)
        form.addRow("Automation", self.background_automation_mode)
        form.addRow("Simulation Timeout", self.simulation_timeout_minutes)
        form.addRow(QLabel("Analyzer Cache"))
        form.addRow("Cache mode", self.analyzer_cache_mode)
        form.addRow("Limit", self.analyzer_cache_limit_mb)
        form.addRow("Keep last runs", self.analyzer_cache_keep_last)
        form.addRow("", self.analyzer_cache_warning)

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
        root.addLayout(form)
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
        self._active_plane = "H"
        self._plane_buttons: Dict[str, QToolButton] = {}
        self._plot_debounce_timer = QTimer(self)
        self._plot_debounce_timer.setSingleShot(True)
        self._plot_debounce_timer.setInterval(220)
        self._plot_debounce_timer.timeout.connect(self._start_plot_request)
        self._compare_plot_debounce_timer = QTimer(self)
        self._compare_plot_debounce_timer.setSingleShot(True)
        self._compare_plot_debounce_timer.setInterval(220)
        self._compare_plot_debounce_timer.timeout.connect(self._start_compare_plot_request)

        presets = self.service.analyzer_presets()
        self._coverage_presets = [dict(item) for item in list(presets.get("coverage_presets", []) or []) if isinstance(item, dict)]
        self._band_presets = [dict(item) for item in list(presets.get("band_presets", []) or []) if isinstance(item, dict)]
        self._stage_presets = {
            str(key): dict(value) for key, value in dict(presets.get("stages", STAGE_PRESETS) or STAGE_PRESETS).items()
        }
        self._default_stage_id = str(presets.get("default_stage_id") or DEFAULT_STAGE_ID).strip().lower() or DEFAULT_STAGE_ID
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
        for stage_id in ("concept", "shaping", "stabilization"):
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
        self.custom_band_low_spin.setRange(20.0, 100000.0)
        self.custom_band_low_spin.setDecimals(0)
        self.custom_band_low_spin.setValue(200.0)
        self.custom_band_high_spin = QDoubleSpinBox()
        self.custom_band_high_spin.setObjectName("AnalyzerBandHighSpin")
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
        self.heatmap_clamp_min_spin.setValue(-30.0)

        self.exclude_flagged_check = QCheckBox("Exclude flagged")
        self.exclude_flagged_check.setObjectName("AnalyzerExcludeFlaggedCheck")
        controls.addWidget(self.exclude_flagged_check, 0, 0, 1, 2)
        self.exclude_warnings_check = QCheckBox("Exclude warnings")
        self.exclude_warnings_check.setObjectName("AnalyzerExcludeWarningsCheck")
        controls.addWidget(self.exclude_warnings_check, 0, 2, 1, 2)
        controls.addWidget(QLabel("Min score"), 0, 4, Qt.AlignLeft | Qt.AlignVCenter)
        self.min_score_spin = QDoubleSpinBox()
        self.min_score_spin.setObjectName("AnalyzerMinScoreSpin")
        self.min_score_spin.setRange(0.0, 100.0)
        self.min_score_spin.setDecimals(1)
        self.min_score_spin.setValue(0.0)
        controls.addWidget(self.min_score_spin, 0, 5)

        self.compute_btn = QPushButton("Compute KPIs")
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
                "Run ID",
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
            ("score", "score"),
            ("b_pc_oct", "B_PC (oct)"),
            ("e_bw", "E_BW (deg)"),
            ("e_cov", "E_cov (dB)"),
            ("r_spill", "R_spill"),
            ("flags", "flags"),
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
            self.plane_group.addButton(btn)
            self._plane_buttons[plane_key] = btn
            plane_layout.addWidget(btn, 0, Qt.AlignLeft | Qt.AlignVCenter)
        plane_layout.addStretch(1)
        context_layout.addWidget(plane_box, 1, 4, 1, 3)

        self.plot_loading_label = QLabel("Select run + plane for Explorer plots.")
        self.plot_loading_label.setObjectName("SummaryMeta")
        self.plot_cancel_btn = QPushButton("Cancel")
        self.plot_cancel_btn.setObjectName("BatchSecondaryButton")
        self.plot_cancel_btn.setVisible(False)
        self.plot_cancel_btn.setEnabled(False)
        context_layout.addWidget(self.plot_loading_label, 1, 7, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
        context_layout.addWidget(self.plot_cancel_btn, 1, 8, 1, 1, Qt.AlignRight | Qt.AlignVCenter)
        right_layout.addWidget(self.context_bar, 0)

        self.analysis_tabs = QTabWidget()
        self.analysis_tabs.setObjectName("AnalyzerPlotTabs")

        self.explorer_tab = QWidget()
        explorer_layout = QVBoxLayout(self.explorer_tab)
        explorer_layout.setContentsMargins(4, 4, 4, 4)
        explorer_layout.setSpacing(8)
        self.heatmap_canvas = HeatmapCanvas()
        self.beamwidth_canvas = BeamwidthCanvas()
        explorer_layout.addWidget(self.heatmap_canvas, 2)
        explorer_layout.addWidget(self.beamwidth_canvas, 1)
        self.analysis_tabs.addTab(self.explorer_tab, "Explorer")

        self.compare_tab = QWidget()
        compare_layout = QVBoxLayout(self.compare_tab)
        compare_layout.setContentsMargins(6, 6, 6, 6)
        compare_layout.setSpacing(8)
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
        self.compare_plane_combo = QComboBox()
        self.compare_plane_combo.setObjectName("AnalyzerComparePlaneCombo")
        self.compare_plane_combo.addItem("H", "H")
        self.compare_plane_combo.addItem("V", "V")
        self.compare_plane_combo.addItem("D", "D")
        compare_controls_layout.addWidget(self.compare_add_selected_btn, 0, 0)
        compare_controls_layout.addWidget(self.compare_auto_pick_btn, 0, 1)
        compare_controls_layout.addWidget(self.compare_save_btn, 0, 2)
        compare_controls_layout.addWidget(QLabel("Saved"), 0, 3, Qt.AlignRight | Qt.AlignVCenter)
        compare_controls_layout.addWidget(self.compare_analysis_selector, 0, 4)
        compare_controls_layout.addWidget(self.compare_load_btn, 0, 5)
        compare_controls_layout.addWidget(QLabel("Overlay plane"), 0, 6, Qt.AlignRight | Qt.AlignVCenter)
        compare_controls_layout.addWidget(self.compare_plane_combo, 0, 7)
        compare_controls_layout.addWidget(self.compare_cancel_btn, 0, 8)
        self.compare_notice = QLabel("Select up to 5 runs, then add or auto-pick top candidates.")
        self.compare_notice.setObjectName("SummaryMeta")
        self.compare_notice.setWordWrap(True)
        compare_controls_layout.addWidget(self.compare_notice, 1, 0, 1, 9)
        compare_layout.addWidget(self.compare_controls, 0)

        self.compare_slots_table = QTableWidget(0, 6)
        self.compare_slots_table.setObjectName("AnalyzerCompareSlotsTable")
        self.compare_slots_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.compare_slots_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.compare_slots_table.setHorizontalHeaderLabels(["Slot", "Batch", "Run", "Version", "Score", "Remove"])
        slots_header = self.compare_slots_table.horizontalHeader()
        slots_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        slots_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        slots_header.setSectionResizeMode(2, QHeaderView.Stretch)
        slots_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        slots_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        slots_header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.compare_slots_table.verticalHeader().setVisible(False)
        compare_layout.addWidget(self.compare_slots_table, 0)

        self.compare_table = QTableWidget(0, 8)
        self.compare_table.setObjectName("AnalyzerCompareTable")
        self.compare_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.compare_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.compare_table.setHorizontalHeaderLabels(
            ["Run ID", "Version", "Score", "B_PC", "E_BW", "E_cov", "R_spill", "Flags"]
        )
        compare_header = self.compare_table.horizontalHeader()
        compare_header.setSectionResizeMode(0, QHeaderView.Stretch)
        for idx in range(1, 8):
            compare_header.setSectionResizeMode(idx, QHeaderView.ResizeToContents)
        compare_layout.addWidget(self.compare_table, 1)

        self.compare_overlay_canvas = BeamwidthOverlayCanvas()
        self.compare_overlay_canvas.setObjectName("AnalyzerCompareOverlayCanvas")
        compare_layout.addWidget(self.compare_overlay_canvas, 2)

        heatmap_row = QWidget()
        heatmap_row_layout = QHBoxLayout(heatmap_row)
        heatmap_row_layout.setContentsMargins(0, 0, 0, 0)
        heatmap_row_layout.setSpacing(6)
        heatmap_row_layout.addWidget(QLabel("Heatmap candidate"), 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.compare_heatmap_selector = QComboBox()
        self.compare_heatmap_selector.setObjectName("AnalyzerCompareHeatmapSelector")
        heatmap_row_layout.addWidget(self.compare_heatmap_selector, 0)
        heatmap_row_layout.addStretch(1)
        compare_layout.addWidget(heatmap_row, 0)

        self.compare_heatmap_canvas = HeatmapCanvas()
        self.compare_heatmap_canvas.setObjectName("AnalyzerCompareHeatmapCanvas")
        compare_layout.addWidget(self.compare_heatmap_canvas, 2)

        compare_hint = QLabel("Compare overlay and heatmap use cached polar data; full multi-plot compare ships in Phase 2C+.")
        compare_hint.setObjectName("SummaryMeta")
        compare_hint.setWordWrap(True)
        compare_layout.addWidget(compare_hint, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.analysis_tabs.addTab(self.compare_tab, "Compare")

        right_layout.addWidget(self.analysis_tabs, 1)

        left.setMinimumWidth(360)
        right.setMinimumWidth(460)
        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 6)
        root.addWidget(self.splitter, 1)

        self.refresh_btn.clicked.connect(self.refresh_data)
        self.compute_btn.clicked.connect(self._start_kpi_compute)
        self.compute_cancel_btn.clicked.connect(self._cancel_kpi_compute)
        self.source_selector.currentIndexChanged.connect(self._on_source_changed)
        self.project_selector.currentIndexChanged.connect(self._on_project_changed)
        self.batch_selector.currentIndexChanged.connect(self._on_batch_changed)
        self.run_table.itemSelectionChanged.connect(self._on_run_selection_changed)
        self.stage_selector.currentIndexChanged.connect(self._on_stage_changed)
        self.target_selector.currentIndexChanged.connect(self._on_kpi_config_changed)
        self.tol_spin.valueChanged.connect(self._on_kpi_config_changed)
        self.band_selector.currentIndexChanged.connect(self._on_band_preset_changed)
        self.custom_band_low_spin.valueChanged.connect(self._on_kpi_config_changed)
        self.custom_band_high_spin.valueChanged.connect(self._on_kpi_config_changed)
        self.heatmap_clamp_check.toggled.connect(self._on_plot_config_changed)
        self.heatmap_clamp_min_spin.valueChanged.connect(self._on_plot_config_changed)
        self.exclude_flagged_check.toggled.connect(self._refresh_run_table)
        self.exclude_warnings_check.toggled.connect(self._refresh_run_table)
        self.min_score_spin.valueChanged.connect(self._refresh_run_table)
        self.plot_cancel_btn.clicked.connect(self._cancel_plot_request)
        self.analysis_tabs.currentChanged.connect(self._on_analysis_tab_changed)
        self.compare_add_selected_btn.clicked.connect(self._on_compare_add_selected)
        self.compare_auto_pick_btn.clicked.connect(self._open_compare_autopick_dialog)
        self.compare_save_btn.clicked.connect(self._save_compare_analysis)
        self.compare_load_btn.clicked.connect(self._load_selected_analysis)
        self.compare_plane_combo.currentIndexChanged.connect(self._schedule_compare_plot_refresh)
        self.compare_heatmap_selector.currentIndexChanged.connect(self._render_compare_heatmap_selection)
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
        self.compute_btn.setEnabled(self._source_key() == "project")
        self._set_details(None)
        self._clear_plot_views("Select run + plane to render plots.")
        self._refresh_saved_analyses()
        self._update_compare_slots()

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
        if self._source_key() == "project":
            self.project_selector.setEnabled(not bool(token))

    def refresh_data(self) -> None:
        self._request_metadata(mode="overview")

    def _source_key(self) -> str:
        value = str(self.source_selector.currentData() or "project").strip().lower()
        return value if value in {"project", "global"} else "project"

    def _selected_project_id(self) -> Optional[str]:
        if self._source_key() == "project" and self._project_context_id:
            return self._project_context_id
        token = str(self.project_selector.currentData() or "").strip()
        return token or None

    def _selected_batch_id(self) -> Optional[str]:
        token = str(self.batch_selector.currentData() or "").strip()
        return token or None

    def _selected_stage_id(self) -> str:
        token = str(self.stage_selector.currentData() or self._default_stage_id).strip().lower()
        return token if token in self._stage_presets else self._default_stage_id

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

    def _selected_plane(self) -> str:
        for plane_key in ("H", "V", "D"):
            button = self._plane_buttons.get(plane_key)
            if button is not None and button.isChecked():
                return plane_key
        return str(self._active_plane or "H")

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
            self.compare_notice.setText(str(text or "Loading compare candidates..."))
            return
        if not self._compare_candidates:
            self.compare_notice.setText("Select up to 5 runs, then add or auto-pick top candidates.")
        else:
            self.compare_notice.setText(str(text or f"{len(self._compare_candidates)} candidate(s) in compare set."))

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
            self._set_loading(False, "Run list updated.")
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
        result: List[str] = []
        for token in list(row.get("planes", []) or []):
            plane = str(token or "").strip().upper()
            if plane in {"H", "V", "D"} and plane not in result:
                result.append(plane)
        return result

    def _sync_plane_controls(self, row: Optional[Dict[str, Any]]) -> None:
        available = self._available_planes(dict(row or {}))
        for plane_key, button in self._plane_buttons.items():
            enabled = plane_key in available
            button.setVisible(enabled)
            button.setEnabled(enabled)
        if not available:
            self._active_plane = "H"
            self._set_plot_busy(False, "Plane not available for selected run.")
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
        self._schedule_plot_refresh()

    def _on_plot_config_changed(self, _value: Any = None) -> None:
        if self._control_sync_guard:
            return
        self._schedule_plot_refresh()
        self._render_compare_heatmap_selection()

    def _on_analysis_tab_changed(self, _index: int = 0) -> None:
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
            self._clear_plot_views("Select run + plane to render plots.")
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
            band_low_hz=float(band_low_hz),
            band_high_hz=float(band_high_hz),
            cache=self._plot_cache,
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
        self.heatmap_canvas.clear_heatmap(msg)
        self.beamwidth_canvas.clear_curve(msg)

    def _render_plot_payload(self, payload: Dict[str, Any]) -> None:
        message = str(payload.get("message") or "").strip()
        display_matrix = [list(row) for row in list(payload.get("display_matrix_db", []) or [])]
        curve = [dict(item) for item in list(payload.get("beamwidth_curve", []) or []) if isinstance(item, dict)]
        if not display_matrix:
            self._clear_plot_views(message or "No polar matrix available for this selection.")
            return
        clamp_enabled = bool(self.heatmap_clamp_check.isChecked())
        clamp_min = float(self.heatmap_clamp_min_spin.value())
        target = self._selected_target()
        plane = self._selected_plane()
        if plane == "H":
            target_deg = float(target.get("h_deg") or 90.0)
        elif plane == "V":
            target_deg = float(target.get("v_deg") or 40.0)
        else:
            target_deg = 0.5 * (float(target.get("h_deg") or 90.0) + float(target.get("v_deg") or 40.0))
        status = "Heatmap"
        ref_angle = payload.get("ref_angle_deg")
        if ref_angle is not None:
            status = f"Heatmap ({plane})"
        if message:
            status = message
        self.heatmap_canvas.set_heatmap_data(
            matrix=display_matrix,
            clamp_enabled=clamp_enabled,
            clamp_min_db=clamp_min,
            ref_angle_deg=float(ref_angle) if ref_angle is not None else None,
            status=status,
        )
        if curve:
            bw_status = "Beamwidth (-6 dB)"
            if bool(payload.get("insufficient_bw")):
                bw_status = "Insufficient angle coverage"
            self.beamwidth_canvas.set_curve(
                curve=curve,
                target_deg=float(target_deg),
                tol_deg=float(self.tol_spin.value()),
                status=bw_status,
            )
        else:
            self.beamwidth_canvas.clear_curve(message or "Insufficient angle coverage.")

    def _compare_identity(self, row: Dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row.get("batch_id") or "").strip(),
            str(row.get("run_id") or "").strip(),
            str(row.get("version_id") or "").strip(),
        )

    def _candidate_from_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "project_id": str(row.get("project_id") or self._selected_project_id() or "").strip(),
            "batch_id": str(row.get("batch_id") or "").strip(),
            "run_id": (str(row.get("run_id") or "").strip() or None),
            "version_id": str(row.get("version_id") or "").strip(),
            "run_label": str(row.get("run_id") or row.get("run_label") or "--"),
            "score": row.get("kpi_score"),
            "kpi_b_pc_oct": row.get("kpi_b_pc_oct"),
            "kpi_e_bw": row.get("kpi_e_bw"),
            "kpi_e_cov": row.get("kpi_e_cov"),
            "kpi_r_spill": row.get("kpi_r_spill"),
            "kpi_flags_count": int(row.get("kpi_flags_count") or 0) if row.get("kpi_score") is not None else None,
            "planes": [str(item) for item in list(row.get("planes", []) or [])],
            "imported_at": row.get("imported_at"),
        }

    def _set_compare_candidates(self, candidates: Sequence[Dict[str, Any]], *, message: str = "") -> None:
        dedup: Dict[tuple[str, str, str], Dict[str, Any]] = {}
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
            self._set_compare_busy(False, "Select run rows first, then Add selected.")
            return
        merged = list(self._compare_candidates) + [self._candidate_from_row(row) for row in rows]
        self._set_compare_candidates(merged, message="Added selected runs to compare set.")

    def _remove_compare_candidate(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._compare_candidates):
            return
        remaining = [dict(item) for idx, item in enumerate(self._compare_candidates) if idx != row_index]
        self._set_compare_candidates(remaining, message="Candidate removed.")

    def _update_compare_slots(self, *, message: str = "") -> None:
        slots = list(self._compare_candidates)
        self.compare_slots_table.setRowCount(len(slots))
        self.compare_table.setRowCount(len(slots))
        self.compare_heatmap_selector.clear()
        for row_index, candidate in enumerate(slots):
            label = f"C{row_index + 1}"
            run_text = str(candidate.get("run_id") or candidate.get("run_label") or "--")
            version_text = str(candidate.get("version_id") or "--")
            self.compare_slots_table.setItem(row_index, 0, QTableWidgetItem(label))
            self.compare_slots_table.setItem(row_index, 1, QTableWidgetItem(str(candidate.get("batch_id") or "--")))
            self.compare_slots_table.setItem(row_index, 2, QTableWidgetItem(run_text))
            self.compare_slots_table.setItem(row_index, 3, QTableWidgetItem(version_text))
            self.compare_slots_table.setItem(row_index, 4, QTableWidgetItem(self._format_float(candidate.get("score"), 2)))
            remove_btn = QPushButton("Remove")
            remove_btn.setObjectName("BatchSecondaryButton")
            remove_btn.clicked.connect(lambda _checked=False, idx=row_index: self._remove_compare_candidate(idx))
            self.compare_slots_table.setCellWidget(row_index, 5, remove_btn)

            flags_count = candidate.get("kpi_flags_count")
            compare_values = [
                run_text,
                version_text,
                self._format_float(candidate.get("score"), 2),
                self._format_float(candidate.get("kpi_b_pc_oct"), 2),
                self._format_float(candidate.get("kpi_e_bw"), 2),
                self._format_float(candidate.get("kpi_e_cov"), 2),
                self._format_float(candidate.get("kpi_r_spill"), 3),
                "--" if flags_count is None else str(int(flags_count)),
            ]
            for col_index, value in enumerate(compare_values):
                self.compare_table.setItem(row_index, col_index, QTableWidgetItem(value))
            self.compare_heatmap_selector.addItem(
                f"C{row_index + 1} | {candidate.get('batch_id')} | {version_text}",
                row_index,
            )

        self._sync_compare_plane_options()

        if self.compare_heatmap_selector.count() > 0:
            self.compare_heatmap_selector.setCurrentIndex(0)
        else:
            self.compare_heatmap_canvas.clear_heatmap("Select candidates to display compare heatmap.")
            self.compare_overlay_canvas.clear_series("Select candidates to display beamwidth overlay.")

        if message:
            self._set_compare_busy(False, message)
        elif not slots:
            self._set_compare_busy(False, "Select up to 5 runs, then add or auto-pick top candidates.")
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

    def _schedule_compare_plot_refresh(self) -> None:
        if self.analysis_tabs.currentWidget() is not self.compare_tab:
            return
        self._compare_plot_debounce_timer.start()

    def _start_compare_plot_request(self) -> None:
        if self.analysis_tabs.currentWidget() is not self.compare_tab:
            return
        project_id = str(self._selected_project_id() or "").strip()
        if not project_id:
            self.compare_overlay_canvas.clear_series("Open a project to compare candidates.")
            self.compare_heatmap_canvas.clear_heatmap("Open a project to compare candidates.")
            return
        if not self._compare_candidates:
            self.compare_overlay_canvas.clear_series("Select candidates to display beamwidth overlay.")
            self.compare_heatmap_canvas.clear_heatmap("Select candidates to display compare heatmap.")
            return
        band_low_hz, band_high_hz = self._resolved_band_limits()
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
            band_low_hz=float(band_low_hz),
            band_high_hz=float(band_high_hz),
            cache=self._plot_cache,
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
        self._compare_plot_items = [dict(item) for item in list(payload.get("items", []) or []) if isinstance(item, dict)]
        self._render_compare_overlay()
        self._render_compare_heatmap_selection()
        self._set_compare_busy(False, "Compare plots ready.")

    def _on_compare_plot_failed(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._compare_plot_request_id):
            return
        self._set_compare_busy(False, "Compare plot load failed.")
        self._set_error(str(message or "Compare plot load failed."))
        self.compare_overlay_canvas.clear_series("Compare plot load failed.")
        self.compare_heatmap_canvas.clear_heatmap("Compare heatmap load failed.")

    def _on_compare_plot_canceled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._compare_plot_request_id):
            return
        self._set_compare_busy(False, str(message or "Compare plot load canceled."))

    def _render_compare_overlay(self) -> None:
        if not self._compare_plot_items:
            self.compare_overlay_canvas.clear_series("Select candidates to display beamwidth overlay.")
            return
        target = self._selected_target()
        plane = self._compare_plane()
        if plane == "H":
            target_deg = float(target.get("h_deg") or 90.0)
        elif plane == "V":
            target_deg = float(target.get("v_deg") or 40.0)
        else:
            target_deg = 0.5 * (float(target.get("h_deg") or 90.0) + float(target.get("v_deg") or 40.0))
        series: List[Dict[str, Any]] = []
        for index, item in enumerate(self._compare_plot_items):
            candidate = dict(item.get("candidate") or {})
            plot = dict(item.get("plot") or {})
            curve = [dict(row) for row in list(plot.get("beamwidth_curve", []) or []) if isinstance(row, dict)]
            if not curve:
                continue
            color_rgb = compare_overlay_color(index)
            series.append(
                {
                    "label": f"C{index + 1} {candidate.get('batch_id')}/{candidate.get('version_id')}",
                    "curve": curve,
                    "color": color_rgb,
                }
            )
        if not series:
            self.compare_overlay_canvas.clear_series("Insufficient angle coverage for overlay.")
            return
        self.compare_overlay_canvas.set_series(
            series=series,
            target_deg=float(target_deg),
            tol_deg=float(self.tol_spin.value()),
            status=f"Beamwidth overlay ({plane})",
        )

    def _render_compare_heatmap_selection(self) -> None:
        index = int(self.compare_heatmap_selector.currentData() or 0)
        if index < 0 or index >= len(self._compare_plot_items):
            self.compare_heatmap_canvas.clear_heatmap("Select candidate for compare heatmap.")
            return
        item = dict(self._compare_plot_items[index])
        plot = dict(item.get("plot") or {})
        matrix = [list(row) for row in list(plot.get("display_matrix_db", []) or [])]
        if not matrix:
            self.compare_heatmap_canvas.clear_heatmap(str(plot.get("message") or "No heatmap data for candidate."))
            return
        candidate = dict(item.get("candidate") or {})
        label = f"C{index + 1} {candidate.get('batch_id')}/{candidate.get('version_id')}"
        self.compare_heatmap_canvas.set_heatmap_data(
            matrix=matrix,
            clamp_enabled=bool(self.heatmap_clamp_check.isChecked()),
            clamp_min_db=float(self.heatmap_clamp_min_spin.value()),
            ref_angle_deg=(float(plot["ref_angle_deg"]) if plot.get("ref_angle_deg") is not None else None),
            status=label,
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
            compare_cfg = dict(config.get("compare") or {})
            self._compare_last_strategy = str(compare_cfg.get("strategy") or self._compare_last_strategy)
            self._compare_last_kpi_key = str(compare_cfg.get("kpi_key") or self._compare_last_kpi_key)
            self._compare_exclude_flags = bool(compare_cfg.get("exclude_flags", self._compare_exclude_flags))
            self._compare_exclude_missing = bool(compare_cfg.get("exclude_missing_kpi", self._compare_exclude_missing))
        finally:
            self._control_sync_guard = False
        self._sync_band_custom_visibility()
        self._apply_stage_defaults()

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
        self._set_compare_candidates(candidates, message=f"Auto-picked {len(candidates)} candidates.")

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
                runs = int(row.get("run_version_count") or 0)
                measurements = int(row.get("measurement_count") or 0)
                label = f"{batch_id} ({runs} run/version, {measurements} measurements)"
                self.batch_selector.addItem(label, batch_id)
            if self.batch_selector.count() == 0:
                self.batch_selector.addItem("(no polar batches)", "")
            self._set_combo_current_by_data(self.batch_selector, active_batch_id)
        finally:
            self._selector_sync_guard = False
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
    def _row_has_warning(row: Dict[str, Any]) -> bool:
        status = str(row.get("run_status") or "").strip().lower()
        if not status:
            return False
        return any(token in status for token in ("warn", "fail", "error"))

    def _sync_band_custom_visibility(self) -> None:
        self.custom_band_widget.setVisible(str(self.band_selector.currentData() or "") == "custom")
        self.heatmap_clamp_min_spin.setEnabled(bool(self.heatmap_clamp_check.isChecked()))

    def _apply_stage_defaults(self) -> None:
        stage = dict(self._stage_presets.get(self._selected_stage_id(), {}) or {})
        filters = dict(stage.get("filters", {}) or {})
        self._control_sync_guard = True
        try:
            self.exclude_flagged_check.setChecked(bool(filters.get("exclude_flagged", False)))
            self.exclude_warnings_check.setChecked(bool(filters.get("exclude_warnings", False)))
            self.min_score_spin.setValue(float(filters.get("min_score", 0.0) or 0.0))
        finally:
            self._control_sync_guard = False
        self._apply_stage_column_visibility()

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
        source_rows = rows if rows is not None else self._all_run_rows
        has_kpi = any(row.get("kpi_score") is not None for row in source_rows)
        self.compute_btn.setText("Refresh KPIs" if has_kpi else "Compute KPIs")

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
        self._set_run_table_rows(self._filtered_rows())

    def _set_run_table_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.run_table.setSortingEnabled(False)
        self.run_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            planes = "/".join(str(item) for item in list(row.get("planes", []) or []))
            flags_count = int(row.get("kpi_flags_count") or 0)
            flags_text = "--"
            if row.get("kpi_score") is not None:
                flags_text = str(flags_count)
                if bool(row.get("kpi_insufficient_coverage")):
                    flags_text = f"{flags_count} (insufficient)"
            values = [
                str(row.get("run_id") or row.get("run_label") or "--"),
                str(row.get("version_id") or "--"),
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
        self.run_table.setSortingEnabled(True)
        if rows:
            self.run_table.selectRow(0)
            first = dict(rows[0])
            self._set_details(first)
            self._sync_plane_controls(first)
            self._schedule_plot_refresh()
        else:
            self._set_details(None)
            self._sync_plane_controls(None)
            self._clear_plot_views("Select run + plane to render plots.")
        self._update_compute_button_text(rows)

    def _apply_runs_payload(self, payload: Dict[str, Any]) -> None:
        rows = [dict(item) for item in list(payload.get("runs", []) or []) if isinstance(item, dict)]
        self._all_run_rows = rows
        if self._compare_candidates:
            lookup = {self._compare_identity(row): dict(row) for row in rows}
            merged: List[Dict[str, Any]] = []
            for candidate in self._compare_candidates:
                identity = self._compare_identity(candidate)
                merged.append(lookup.get(identity, dict(candidate)))
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
        self._loaded_analysis_id = None
        self._clear_plot_views("Select run + plane to render plots.")
        self.compare_overlay_canvas.clear_series("Select candidates to display beamwidth overlay.")
        self.compare_heatmap_canvas.clear_heatmap("Select candidates to display compare heatmap.")
        if self._source_key() == "project":
            self.project_selector.setEnabled(not bool(self._project_context_id))
            if self._compute_thread is None or not self._compute_thread.isRunning():
                self.compute_btn.setEnabled(True)
        else:
            self.project_selector.setEnabled(True)
            if self._compute_thread is None or not self._compute_thread.isRunning():
                self.compute_btn.setEnabled(False)
        self._refresh_saved_analyses()
        self.refresh_data()

    def _on_project_changed(self, _index: int = 0) -> None:
        if self._selector_sync_guard:
            return
        self._compare_candidates = []
        self._compare_plot_items = []
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
        self._apply_stage_defaults()
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
            self._clear_plot_views("Select run + plane to render plots.")
            return
        row_index = int(selected_indexes[0].row())
        item = self.run_table.item(row_index, self.COL_RUN_ID)
        payload = dict(item.data(Qt.UserRole) or {}) if item is not None else {}
        self._set_details(payload if payload else None)
        self._sync_plane_controls(payload if payload else None)
        self._schedule_plot_refresh()

    def _set_details(self, payload: Optional[Dict[str, Any]]) -> None:
        data = dict(payload or {})
        planes = "/".join(str(item) for item in list(data.get("planes", []) or []))
        source_files = "\n".join(str(item) for item in list(data.get("source_files", []) or []))
        file_hashes = "\n".join(str(item) for item in list(data.get("file_hashes", []) or []))
        flags_count = int(data.get("kpi_flags_count") or 0) if data.get("kpi_score") is not None else None
        if flags_count is None:
            flags_text = "--"
        elif bool(data.get("kpi_insufficient_coverage")):
            flags_text = f"{flags_count} (insufficient)"
        else:
            flags_text = str(flags_count)
        mapping = {
            "run_id": str(data.get("run_id") or data.get("run_label") or "--"),
            "version_id": str(data.get("version_id") or "--"),
            "project_id": str(data.get("project_id") or "--"),
            "batch_id": str(data.get("batch_id") or "--"),
            "planes": planes or "--",
            "freq_count": str(data.get("freq_count") if data.get("freq_count") is not None else "--"),
            "angle_count": str(data.get("angle_count") if data.get("angle_count") is not None else "--"),
            "norm_angle_deg": self._format_angle(data.get("norm_angle_deg")),
            "score": self._format_float(data.get("kpi_score"), 2),
            "b_pc_oct": self._format_float(data.get("kpi_b_pc_oct"), 2),
            "e_bw": self._format_float(data.get("kpi_e_bw"), 2),
            "e_cov": self._format_float(data.get("kpi_e_cov"), 2),
            "r_spill": self._format_float(data.get("kpi_r_spill"), 3),
            "flags": flags_text,
            "imported_at": str(data.get("imported_at") or "--"),
            "created_at": str(data.get("created_at") or "--"),
            "source_files": source_files or "--",
            "file_hashes": file_hashes or "--",
        }
        for key, label in self._detail_labels.items():
            label.setText(mapping.get(key, "--"))


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
            self.analyse_page.reload_cache_settings()
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
