"""Shared frameless dialog shell for Batch popups."""

from __future__ import annotations

from typing import Optional

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for styled dialogs.") from exc


class StyledDialogBase(QDialog):
    def __init__(
        self,
        *,
        title: str,
        parent: QWidget | None = None,
        min_width: int = 760,
        min_height: int = 620,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setProperty("framelessShell", True)
        self.setModal(True)
        self.setMinimumSize(int(min_width), int(min_height))
        self._drag_offset: Optional[QPoint] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        shell = QFrame(self)
        shell.setObjectName("FramelessShell")
        outer.addWidget(shell)

        shell_root = QVBoxLayout(shell)
        shell_root.setContentsMargins(14, 12, 14, 14)
        shell_root.setSpacing(10)

        title_bar = QWidget(shell)
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(0, 1, 2, 1)
        title_row.setSpacing(8)

        self.title_label = QLabel(str(title or "").strip(), title_bar)
        self.title_label.setObjectName("SectionTitle")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)

        close_btn = QPushButton("X", title_bar)
        close_btn.setObjectName("WindowCloseButton")
        close_btn.setFixedSize(28, 24)
        close_btn.clicked.connect(self.reject)
        title_row.addWidget(close_btn, alignment=Qt.AlignRight)

        shell_root.addWidget(title_bar)
        self._title_bar = title_bar
        self._title_bar.mousePressEvent = self._title_mouse_press  # type: ignore[assignment]
        self._title_bar.mouseMoveEvent = self._title_mouse_move  # type: ignore[assignment]
        self._title_bar.mouseReleaseEvent = self._title_mouse_release  # type: ignore[assignment]

        self._body_layout = QVBoxLayout()
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(8)
        shell_root.addLayout(self._body_layout, 1)

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

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
