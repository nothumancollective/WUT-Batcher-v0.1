"""Batch preview panel with auto-refresh STL viewer."""

from __future__ import annotations

from pathlib import Path

from ui.stl_preview_widget import StlPreviewWidget

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import (
        QFrame,
        QLabel,
        QProgressBar,
        QStackedLayout,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for batch preview panel.") from exc


class BatchPreviewPlaceholder(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ProjectSummaryPanel")

        self._busy = False
        self._last_loaded_stl: str | None = None
        self._has_mesh = False
        self._preview_parameters: dict[str, object] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self.setMinimumHeight(260)

        title = QLabel("Preview")
        title.setObjectName("SummaryTitle")
        root.addWidget(title)

        self.canvas_wrap = QWidget()
        canvas_layout = QVBoxLayout(self.canvas_wrap)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)

        self.stack_host = QWidget()
        self.stack = QStackedLayout(self.stack_host)
        self.stack.setContentsMargins(0, 0, 0, 0)

        message_page = QWidget()
        message_layout = QVBoxLayout(message_page)
        message_layout.setContentsMargins(0, 6, 0, 6)
        message_layout.setSpacing(4)
        self.message_label = QLabel("No preview mesh loaded.")
        self.message_label.setObjectName("SummaryText")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        message_layout.addStretch(1)
        message_layout.addWidget(self.message_label)
        message_layout.addStretch(1)
        self.stack.addWidget(message_page)

        loading_page = QWidget()
        loading_layout = QVBoxLayout(loading_page)
        loading_layout.setContentsMargins(0, 6, 0, 6)
        loading_layout.setSpacing(6)
        loading_layout.addStretch(1)
        self.loader = QProgressBar()
        self.loader.setRange(0, 0)
        self.loader.setFixedHeight(10)
        self.loader.setTextVisible(False)
        self.loader.setMaximumWidth(180)
        loading_layout.addWidget(self.loader, 0, Qt.AlignCenter)
        loading_text = QLabel("Generating preview STL...")
        loading_text.setObjectName("SummaryText")
        loading_layout.addWidget(loading_text, 0, Qt.AlignCenter)
        loading_layout.addStretch(1)
        self.stack.addWidget(loading_page)

        viewer_page = QWidget()
        viewer_layout = QVBoxLayout(viewer_page)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.setSpacing(0)
        self.viewer = StlPreviewWidget()
        viewer_layout.addWidget(self.viewer, 1)
        self.stack.addWidget(viewer_page)

        canvas_layout.addWidget(self.stack_host, 1)
        root.addWidget(self.canvas_wrap, 1)

        self._sync_state_views()

    def _sync_state_views(self) -> None:
        if self._busy:
            self.stack.setCurrentIndex(1)
            return
        if self._has_mesh:
            self.stack.setCurrentIndex(2)
            return
        self.stack.setCurrentIndex(0)

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_state_views()

    def set_preview_enabled(self, enabled: bool) -> None:
        _ = enabled

    def is_preview_enabled(self) -> bool:
        return True

    def set_preview_mesh(self, path: str | Path) -> None:
        stl_path = Path(path)
        self.viewer.load_stl(stl_path)
        self._apply_enclosure_overlay()
        self._last_loaded_stl = str(stl_path)
        self._has_mesh = True
        self._sync_state_views()

    def set_preview_parameters(self, parameters: dict[str, object] | None) -> None:
        self._preview_parameters = dict(parameters or {})
        if self._has_mesh:
            self._apply_enclosure_overlay()

    def set_error_message(self, message: str) -> None:
        text = str(message or "Preview generation failed.").strip()
        self.message_label.setProperty("severity", "warn")
        self.message_label.setText(text)
        self._has_mesh = False
        self._sync_message_style()
        self._sync_state_views()

    def set_info_message(self, message: str) -> None:
        self.message_label.setProperty("severity", "")
        self.message_label.setText(str(message or ""))
        self._has_mesh = False
        self._sync_message_style()
        self._sync_state_views()

    def last_preview_path(self) -> str | None:
        return self._last_loaded_stl

    def capture_snapshot(self, target_path: str | Path, *, width: int = 340, height: int = 220) -> bool:
        if not self._has_mesh:
            return False
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        pixmap = self.viewer.grab()
        if pixmap.isNull():
            pixmap = self.grab()
        if pixmap.isNull():
            return False
        scaled = pixmap.scaled(
            max(120, int(width)),
            max(80, int(height)),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        if isinstance(scaled, QPixmap):
            return bool(scaled.save(str(target), "PNG"))
        return False

    def _apply_enclosure_overlay(self) -> None:
        enclosure = self._preview_parameters.get("Mesh.Enclosure")
        if isinstance(enclosure, dict):
            self.viewer.set_enclosure_overlay(enclosure)
            return
        self.viewer.set_enclosure_overlay(None)

    def _sync_message_style(self) -> None:
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)
        self.message_label.update()
