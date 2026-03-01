"""Project Manager card widget with rounded preview presentation."""

from __future__ import annotations

try:
    from PySide6.QtCore import QRectF, QSize, Qt, Signal
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
    from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for ProjectCardV2.") from exc

from ui.theme_tokens import DEFAULT_THEME


class _ElidedSingleLineLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(20)
        self.setText(text)

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._apply_elide()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        available = max(0, int(self.contentsRect().width()))
        if available <= 0:
            super().setText(self._full_text)
            return
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full_text, Qt.ElideRight, available))


class _ProjectCardPreview(QWidget):
    def __init__(self, *, corner_radius: int = 15, size_hint: QSize, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._corner_radius = int(corner_radius)
        self._size_hint = QSize(size_hint)
        self._pixmap = QPixmap()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(int(self._size_hint.height()))
        self.setMinimumWidth(int(self._size_hint.width()))

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = QPixmap(pixmap) if isinstance(pixmap, QPixmap) else QPixmap()
        self.update()

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(self._size_hint)

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(self._size_hint)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        _ = event
        colors = DEFAULT_THEME.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect, self._corner_radius, self._corner_radius)
        painter.fillPath(clip_path, QColor("#17191D"))
        painter.save()
        painter.setClipPath(clip_path)

        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                int(rect.width()),
                int(rect.height()),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            draw_x = int(rect.x()) - max(0, int((scaled.width() - rect.width()) / 2))
            draw_y = int(rect.y()) - max(0, int((scaled.height() - rect.height()) / 2))
            painter.drawPixmap(draw_x, draw_y, scaled)
        else:
            painter.fillPath(clip_path, QColor(colors["surface"]))
            painter.setPen(QPen(QColor("#3B414A"), 1.2))
            painter.drawLine(int(rect.left()) + 32, int(rect.bottom()) - 54, int(rect.left()) + 88, int(rect.top()) + 86)
            painter.drawLine(int(rect.left()) + 88, int(rect.top()) + 86, int(rect.right()) - 50, int(rect.bottom()) - 74)
            painter.drawLine(int(rect.right()) - 50, int(rect.bottom()) - 74, int(rect.right()) - 28, int(rect.top()) + 70)
            painter.setBrush(QColor("#4A515C"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(int(rect.left()) + 34, int(rect.top()) + 42, 12, 12)

        painter.restore()
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(clip_path)


class ProjectCardV2(QWidget):
    clicked = Signal()
    doubleClicked = Signal()

    _OUTER_SIZE = QSize(240, 180)
    _CARD_INSET = 2
    _CARD_RADIUS = 20
    _CONTENT_PADDING = 12
    _CONTENT_SPACING = 8
    _GRID_SPACING = 13
    _TITLE_HEIGHT = 20

    @classmethod
    def preview_size_hint(cls) -> QSize:
        width = max(1, int(cls._OUTER_SIZE.width()) - (2 * int(cls._CONTENT_PADDING)))
        height = max(1, int(round(float(width) * 9.0 / 16.0)))
        return QSize(width, height)

    @classmethod
    def grid_spacing(cls) -> int:
        return int(cls._GRID_SPACING)

    def __init__(self, *, project_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        colors = DEFAULT_THEME.colors
        self._project_name = str(project_name or "")
        self._hovered = False
        self._selected = False

        self.setObjectName("ProjectCardV2")
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(self._OUTER_SIZE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            int(self._CONTENT_PADDING),
            int(self._CONTENT_PADDING),
            int(self._CONTENT_PADDING),
            int(self._CONTENT_PADDING),
        )
        layout.setSpacing(int(self._CONTENT_SPACING))

        self.preview = _ProjectCardPreview(size_hint=self.preview_size_hint(), parent=self)
        self.preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.title_label = _ElidedSingleLineLabel(project_name, self)
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_font = QFont(self.title_label.font())
        title_font.setPointSizeF(max(9.0, float(title_font.pointSizeF() or 9.0)))
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setFixedHeight(int(self._TITLE_HEIGHT))
        self.title_label.setObjectName("ProjectCardTitle")
        self.title_label.setStyleSheet(f"color: {colors['text']}; background: transparent;")

        layout.addWidget(self.preview, 0)
        layout.addWidget(self.title_label, 0, Qt.AlignLeft)

    @classmethod
    def size_hint(cls) -> QSize:
        return QSize(cls._OUTER_SIZE)

    @classmethod
    def grid_size_hint(cls) -> QSize:
        return QSize(cls._OUTER_SIZE)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return self.size_hint()

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        return self.size_hint()

    def set_project_name(self, project_name: str) -> None:
        self._project_name = str(project_name or "")
        self.title_label.setText(self._project_name)

    def set_preview_pixmap(self, pixmap: QPixmap) -> None:
        self.preview.set_pixmap(pixmap)

    def set_selected(self, selected: bool) -> None:
        next_state = bool(selected)
        if self._selected == next_state:
            return
        self._selected = next_state
        self.update()

    def is_selected(self) -> bool:
        return bool(self._selected)

    def enterEvent(self, event) -> None:  # type: ignore[override]
        super().enterEvent(event)
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        super().leaveEvent(event)
        self._hovered = False
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        _ = event
        colors = DEFAULT_THEME.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        outer_rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        card_rect = outer_rect.adjusted(self._CARD_INSET, self._CARD_INSET, -self._CARD_INSET, -self._CARD_INSET)

        if self._selected or self._hovered:
            shadow_color = QColor(0, 0, 0, 44 if self._selected else 26)
            shadow_rect = card_rect.adjusted(0, 2, 0, 2)
            for spread, alpha_scale in ((0, 1.0), (1, 0.65), (2, 0.35)):
                color = QColor(shadow_color)
                color.setAlpha(max(0, min(255, int(shadow_color.alpha() * alpha_scale))))
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(
                    shadow_rect.adjusted(-spread, -spread, spread, spread),
                    self._CARD_RADIUS,
                    self._CARD_RADIUS,
                )

        background = QColor(colors["surface2"])
        border = QColor(colors["border"])
        border.setAlpha(150)
        if self._hovered:
            background = QColor("#23262B")
            border = QColor("#8B929C")
        if self._selected:
            background = QColor("#262A30")
            border = QColor("#D5D7DB")

        painter.setPen(Qt.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(card_rect, self._CARD_RADIUS, self._CARD_RADIUS)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(border, 1.0))
        painter.drawRoundedRect(card_rect, self._CARD_RADIUS, self._CARD_RADIUS)
