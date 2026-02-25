"""Compact helper row widget for inline contextual hints."""

from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for helper row widgets.") from exc


class HelperRow(QFrame):
    """Reusable low-profile helper row with optional icon and wrapped text."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HelperRow")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setVisible(False)

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 2, 4, 2)
        root.setSpacing(6)

        self.icon_label = QLabel("")
        self.icon_label.setObjectName("HelperRowIcon")
        self.icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.icon_label.setVisible(False)
        root.addWidget(self.icon_label, 0, Qt.AlignTop)

        self.text_label = QLabel("")
        self.text_label.setObjectName("FieldStateHint")
        self.text_label.setWordWrap(True)
        self.text_label.setProperty("severity", "info")
        root.addWidget(self.text_label, 1)

    def set_message(self, text: str, *, severity: str = "info", icon_text: str | None = None) -> None:
        message = str(text or "").strip()
        level = str(severity or "info").strip().lower() or "info"
        self.text_label.setProperty("severity", level)
        self.text_label.setText(message)
        self.text_label.setVisible(bool(message))

        icon = str(icon_text or "").strip()
        show_icon = bool(icon)
        self.icon_label.setText(icon if show_icon else "")
        self.icon_label.setVisible(show_icon and bool(message))
        self.setProperty("severity", level)
        self.setVisible(bool(message))
