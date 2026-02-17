"""Batch preview panel with toggle/update controls and STL viewer."""

from __future__ import annotations

from pathlib import Path

from ui.stl_preview_widget import StlPreviewWidget

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import (
        QFrame,
        QHBoxLayout,
        QLabel,
        QProgressBar,
        QPushButton,
        QStackedLayout,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for batch preview panel.") from exc


class BatchPreviewPlaceholder(QFrame):
    preview_toggled = Signal(bool)
    update_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ProjectSummaryPanel")

        self._enabled = False
        self._busy = False
        self._last_loaded_stl: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self.setMinimumHeight(260)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        title = QLabel("Preview")
        title.setObjectName("SummaryTitle")
        top_row.addWidget(title)
        top_row.addStretch(1)

        self.toggle_btn = QPushButton("Off")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setProperty("segment", "true")
        self.toggle_btn.setFixedHeight(30)
        self.toggle_btn.setMinimumWidth(68)
        top_row.addWidget(self.toggle_btn, 0, Qt.AlignRight)
        root.addLayout(top_row)

        self.canvas_wrap = QWidget()
        canvas_layout = QVBoxLayout(self.canvas_wrap)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(6)

        self.stack_host = QWidget()
        self.stack = QStackedLayout(self.stack_host)
        self.stack.setContentsMargins(0, 0, 0, 0)

        disabled_page = QWidget()
        disabled_layout = QVBoxLayout(disabled_page)
        disabled_layout.setContentsMargins(0, 6, 0, 6)
        disabled_layout.setSpacing(4)
        disabled_text = QLabel("Preview is disabled.")
        disabled_text.setObjectName("SummaryText")
        disabled_text.setAlignment(Qt.AlignCenter)
        disabled_layout.addStretch(1)
        disabled_layout.addWidget(disabled_text)
        disabled_layout.addStretch(1)
        self.stack.addWidget(disabled_page)

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
        viewer_layout.setSpacing(6)
        self.viewer = StlPreviewWidget()
        viewer_layout.addWidget(self.viewer, 1)
        self.status_label = QLabel("No preview mesh loaded.")
        self.status_label.setObjectName("SummaryMeta")
        self.status_label.setWordWrap(True)
        viewer_layout.addWidget(self.status_label)
        self.stack.addWidget(viewer_page)

        canvas_layout.addWidget(self.stack_host, 1)
        root.addWidget(self.canvas_wrap, 1)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(8)
        bottom_row.addStretch(1)
        self.preview_btn = QPushButton("Update Preview")
        self.preview_btn.setProperty("segment", "true")
        self.preview_btn.setFixedHeight(30)
        self.preview_btn.setMinimumWidth(124)
        self.preview_btn.setMaximumWidth(168)
        bottom_row.addWidget(self.preview_btn, 0, Qt.AlignRight)
        root.addLayout(bottom_row)

        self.toggle_btn.toggled.connect(self._on_toggle_changed)
        self.preview_btn.clicked.connect(self._on_update_clicked)
        self._sync_state_views()

    def _on_toggle_changed(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.toggle_btn.setText("On" if self._enabled else "Off")
        self._sync_state_views()
        self.preview_toggled.emit(self._enabled)

    def _on_update_clicked(self) -> None:
        if not self._enabled:
            return
        self.update_requested.emit()

    def _sync_state_views(self) -> None:
        self.canvas_wrap.setVisible(self._enabled)
        self.preview_btn.setVisible(self._enabled)
        self.preview_btn.setEnabled(self._enabled and (not self._busy))

        if not self._enabled:
            self.stack.setCurrentIndex(0)
            return
        if self._busy:
            self.stack.setCurrentIndex(1)
            return
        self.stack.setCurrentIndex(2)

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_state_views()

    def set_preview_enabled(self, enabled: bool) -> None:
        self.toggle_btn.setChecked(bool(enabled))

    def is_preview_enabled(self) -> bool:
        return bool(self._enabled)

    def set_preview_mesh(self, path: str | Path) -> None:
        stl_path = Path(path)
        self.viewer.load_stl(stl_path)
        self._last_loaded_stl = str(stl_path)
        self.status_label.setProperty("severity", "")
        self.status_label.setText(f"Loaded: {stl_path.name}")
        self.stack.setCurrentIndex(2)
        self._sync_status_style()

    def set_error_message(self, message: str) -> None:
        text = str(message or "Preview generation failed.").strip()
        self.status_label.setProperty("severity", "warn")
        self.status_label.setText(text)
        self.stack.setCurrentIndex(2)
        self._sync_status_style()

    def set_info_message(self, message: str) -> None:
        self.status_label.setProperty("severity", "")
        self.status_label.setText(str(message or ""))
        self._sync_status_style()

    def last_preview_path(self) -> str | None:
        return self._last_loaded_stl

    def _sync_status_style(self) -> None:
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.update()
