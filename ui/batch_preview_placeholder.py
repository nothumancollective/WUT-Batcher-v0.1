"""Preview placeholder for future STL integration."""

from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for batch preview placeholder.") from exc


class BatchPreviewPlaceholder(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ProjectSummaryPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel("Preview (.stl)")
        title.setObjectName("SummaryTitle")
        root.addWidget(title)

        text = QLabel("Coming soon. STL viewport integration will be attached here.")
        text.setObjectName("SummaryText")
        text.setWordWrap(True)
        root.addWidget(text)

        stage = QLabel("No mesh loaded")
        stage.setObjectName("SummaryMeta")
        root.addWidget(stage)

        actions = QHBoxLayout()
        open_btn = QPushButton("Open")
        open_btn.setEnabled(False)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setEnabled(False)
        actions.addWidget(open_btn, 0, Qt.AlignLeft)
        actions.addWidget(refresh_btn, 0, Qt.AlignLeft)
        actions.addStretch(1)
        root.addLayout(actions)
        root.addStretch(1)
