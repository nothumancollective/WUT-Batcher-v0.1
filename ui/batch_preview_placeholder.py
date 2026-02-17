"""Preview placeholder for future STL integration."""

from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for batch preview placeholder.") from exc


class BatchPreviewPlaceholder(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ProjectSummaryPanel")
        self._preview_requested = False
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 12)
        root.setSpacing(8)
        self.setMinimumHeight(260)

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

        root.addStretch(1)

        self.preview_btn = QPushButton("show preview")
        self.preview_btn.setProperty("segment", "true")
        self.preview_btn.setFixedHeight(26)
        self.preview_btn.setMinimumWidth(124)
        self.preview_btn.setMaximumWidth(164)
        self.preview_btn.clicked.connect(self._on_preview_clicked)
        root.addWidget(self.preview_btn, 0, Qt.AlignRight | Qt.AlignBottom)

    def _on_preview_clicked(self) -> None:
        if not self._preview_requested:
            self._preview_requested = True
            self.preview_btn.setText("update preview")
